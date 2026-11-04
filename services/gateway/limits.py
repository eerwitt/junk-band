"""What stands between the public site and the bill: a queue, a daily limit and a credit check."""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from openai import APIError

from services.gateway.repository import ensure_dir, through_refusals

logger = logging.getLogger(__name__)

MODAL_CHECK_SECONDS = 300.0
# A failed look at the bill says nothing about the bill, so it is simply tried again soon.
MODAL_RECHECK_SECONDS = 60.0
# Meta has no way to ask for a balance, so after it says no there is a pause before asking again.
META_PAUSE_SECONDS = 600.0

OUT_OF_MODAL = "The band has used this month's sound budget, so new requests are paused."
META_BUDGET_USED = "The band has used this month's picture budget, so new requests are paused."
OUT_OF_META = (
    "The band is out of picture credit for now, so new requests are paused. Try again later."
)


def read_modal_bill() -> Any:  # noqa: ANN401
    import modal

    return modal.Workspace.from_context().billing.summary()


def is_out_of_credit(error: BaseException) -> bool:
    """Meta's documented answer for a low balance or lapsed payment: 402 Payment Required."""
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code == 402
    return isinstance(error, APIError) and getattr(error, "status_code", None) == 402


class SiteGuard:
    """Asked before anything that costs money. Cached results never reach it."""

    def __init__(
        self,
        data_dir: Path,
        daily_limit: int,
        modal_monthly_limit: float,
        flush: Callable[[], None],
        *,
        enabled: bool,
        uses_modal: bool,
        read_bill: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.time,
        meta_monthly_limit: float = 100.0,
    ) -> None:
        self.path = data_dir / "_site" / "usage.json"
        self.spend_path = data_dir / "_site" / "meta-spend.json"
        self.meta_monthly_limit = meta_monthly_limit
        self._modal_used: Decimal | None = None
        self.daily_limit = daily_limit
        self.modal_monthly_limit = Decimal(str(modal_monthly_limit))
        self.flush = flush
        self.enabled = enabled
        self.uses_modal = uses_modal
        self.read_bill = read_bill or (lambda: read_modal_bill())
        self.clock = clock
        self._meta_paused_until = 0.0
        self._modal_problem: str | None = None
        self._modal_checked_until = 0.0

    def _today(self) -> str:
        return datetime.fromtimestamp(self.clock(), UTC).strftime("%Y-%m-%d")

    def used_today(self) -> int:
        try:
            record = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        return int(record.get("used", 0)) if record.get("day") == self._today() else 0

    def _month(self) -> str:
        return datetime.fromtimestamp(self.clock(), UTC).strftime("%Y-%m")

    def meta_spent(self) -> float:
        """This site's Meta spend this month, added up from real calls at published prices."""
        try:
            record = json.loads(self.spend_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0.0
        return float(record.get("spent", 0.0)) if record.get("month") == self._month() else 0.0

    def _save(self, path: Path, record: dict[str, Any]) -> None:
        # Bookkeeping must not sink work that is already paid for, so a failure is only logged.
        temporary = path.with_suffix(".tmp")

        def save() -> None:
            ensure_dir(path.parent, parents=True)
            temporary.write_text(json.dumps(record), encoding="utf-8")
            temporary.replace(path)

        try:
            through_refusals(save)
        except OSError as error:
            logger.error("Could not save %s, so a limit may undercount: %s", path.name, error)
            return
        self.flush()

    def add_meta_spend(self, amount: float) -> None:
        self._save(self.spend_path, {"month": self._month(), "spent": self.meta_spent() + amount})

    def _record_use(self, used: int) -> None:
        self._save(self.path, {"day": self._today(), "used": used})

    async def _modal_credit_problem(self) -> str | None:
        if not self.uses_modal or self.clock() < self._modal_checked_until:
            return self._modal_problem
        try:
            bill = await asyncio.to_thread(self.read_bill)
        except Exception as error:
            # Modal stops work itself at the account's limit, and the daily limit still applies.
            logger.warning("Could not read the Modal bill: %s", type(error).__name__)
            self._modal_checked_until = self.clock() + MODAL_RECHECK_SECONDS
            return self._modal_problem
        billed, metered = Decimal(bill.billed_cost), Decimal(bill.metered_cost)
        self._modal_used = metered
        self._modal_problem = (
            OUT_OF_MODAL if billed > 0 or metered >= self.modal_monthly_limit else None
        )
        self._modal_checked_until = self.clock() + MODAL_CHECK_SECONDS
        return self._modal_problem

    def note_out_of_meta_credit(self) -> None:
        self._meta_paused_until = self.clock() + META_PAUSE_SECONDS
        logger.warning("Meta reported a billing problem; pausing paid requests")

    async def problem(self) -> str | None:
        """Why paid work cannot run right now, without using up a request."""
        if not self.enabled:
            return None
        if self.clock() < self._meta_paused_until:
            return OUT_OF_META
        if self.meta_spent() >= self.meta_monthly_limit:
            return META_BUDGET_USED
        if await self._modal_credit_problem():
            return self._modal_problem
        if self.used_today() >= self.daily_limit:
            return (
                f"The band has used all {self.daily_limit} of today's new requests. "
                "They come back at midnight UTC."
            )
        return None

    async def admit(self) -> None:
        reason = await self.problem()
        if reason:
            raise HTTPException(429, reason)
        if self.enabled:
            self._record_use(self.used_today() + 1)

    async def status(self) -> dict[str, Any]:
        reason = await self.problem()
        return {
            "requests_today": self.used_today(),
            "daily_limit": self.daily_limit,
            "modal_used_this_month": float(self._modal_used) if self._modal_used else None,
            "modal_monthly_limit": float(self.modal_monthly_limit),
            "meta_spent_this_month": round(self.meta_spent(), 4),
            "meta_monthly_limit": self.meta_monthly_limit,
            "paused": reason,
        }


class WorkQueue:
    """First come, first served across the whole site, with places people can be told about."""

    def __init__(self, slots: int, max_waiting: int) -> None:
        self.slots = slots
        self.max_waiting = max_waiting
        self._line: list[object] = []
        self._turn = asyncio.Condition()

    def join(self) -> object:
        if len(self._line) >= self.slots + self.max_waiting:
            raise HTTPException(503, "The queue is full right now. Try again in a few minutes.")
        ticket = object()
        self._line.append(ticket)
        return ticket

    def ahead_of(self, ticket: object) -> int:
        """How many are still waiting in front of this one. 0 once it is running or next up."""
        if ticket not in self._line:
            return 0
        return max(0, self._line.index(ticket) - self.slots + 1)

    def _running(self, ticket: object) -> bool:
        return ticket in self._line[: self.slots]

    async def wait(self, ticket: object) -> None:
        async with self._turn:
            await self._turn.wait_for(lambda: self._running(ticket))

    async def leave(self, ticket: object) -> None:
        if ticket in self._line:
            self._line.remove(ticket)
        async with self._turn:
            self._turn.notify_all()

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        ticket = self.join()
        try:
            await self.wait(ticket)
            yield
        finally:
            await self.leave(ticket)
