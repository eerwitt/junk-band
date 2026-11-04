import asyncio
import gzip
import os
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from services.gateway.app import create_app
from services.gateway.config import Settings
from services.gateway.limits import (
    META_BUDGET_USED,
    OUT_OF_META,
    OUT_OF_MODAL,
    SiteGuard,
    WorkQueue,
    is_out_of_credit,
)
from services.gateway.meta_costs import SPARK, chat_cost, note_meta_cost
from services.gateway.retention import expired_sessions, remove_expired_sessions
from services.gateway.studio_files import StudioFiles

DAY = 86400.0
NOVEMBER_4 = 1793750400.0


def bill(metered: str = "4.90", billed: str = "0") -> SimpleNamespace:
    return SimpleNamespace(metered_cost=Decimal(metered), billed_cost=Decimal(billed))


class Clock:
    def __init__(self) -> None:
        self.now = NOVEMBER_4

    def __call__(self) -> float:
        return self.now


def guard(tmp_path: Path, clock: Clock, *, limit: int = 2, **options: object) -> SiteGuard:
    settings: dict = {
        "enabled": True,
        "uses_modal": True,
        "read_bill": bill,
        "clock": clock,
        **options,
    }
    return SiteGuard(tmp_path, limit, 28.0, lambda: None, **settings)


def refused(site: SiteGuard) -> str:
    with pytest.raises(HTTPException) as caught:
        asyncio.run(site.admit())
    assert caught.value.status_code == 429
    return str(caught.value.detail)


def test_the_daily_limit_covers_the_whole_site_and_resets_at_midnight(tmp_path: Path) -> None:
    clock = Clock()
    site = guard(tmp_path, clock)
    asyncio.run(site.admit())
    asyncio.run(site.admit())
    assert site.used_today() == 2
    assert "all 2" in refused(site)
    assert site.used_today() == 2, "A refused request is not counted"
    # A restarted container reads the same count back from the volume.
    assert "all 2" in refused(guard(tmp_path, clock))
    clock.now += DAY
    asyncio.run(site.admit())
    assert site.used_today() == 1


def test_used_credit_or_a_real_charge_stops_requests_before_they_spend(tmp_path: Path) -> None:
    clock = Clock()
    assert refused(guard(tmp_path, clock, read_bill=lambda: bill("28.00"))) == OUT_OF_MODAL
    assert refused(guard(tmp_path, clock, read_bill=lambda: bill("5", "0.01"))) == OUT_OF_MODAL
    assert guard(tmp_path, clock).used_today() == 0
    asyncio.run(guard(tmp_path, clock).admit())


def test_the_bill_is_not_read_on_every_request(tmp_path: Path) -> None:
    clock = Clock()
    reads = []
    site = guard(tmp_path, clock, limit=10, read_bill=lambda: reads.append(1) or bill())
    asyncio.run(site.admit())
    asyncio.run(site.admit())
    assert len(reads) == 1
    clock.now += 301
    asyncio.run(site.admit())
    assert len(reads) == 2


def test_an_unreadable_bill_does_not_take_the_site_down_and_is_retried_soon(
    tmp_path: Path,
) -> None:
    clock = Clock()
    reads = []

    def broken() -> None:
        reads.append(1)
        raise RuntimeError("no permission")

    site = guard(tmp_path, clock, limit=10, read_bill=broken)
    asyncio.run(site.admit())
    asyncio.run(site.admit())
    assert len(reads) == 1
    clock.now += 61
    asyncio.run(site.admit())
    assert len(reads) == 2


def test_a_meta_billing_error_pauses_requests_for_a_while(tmp_path: Path) -> None:
    clock = Clock()
    site = guard(tmp_path, clock, limit=10)
    site.note_out_of_meta_credit()
    assert refused(site) == OUT_OF_META
    clock.now += 601
    asyncio.run(site.admit())


def test_only_a_402_counts_as_out_of_credit() -> None:
    request = httpx.Request("POST", "https://api.meta.ai/v1/images")

    def status(code: int) -> httpx.HTTPStatusError:
        return httpx.HTTPStatusError("x", request=request, response=httpx.Response(code))

    assert is_out_of_credit(status(402))
    assert not is_out_of_credit(status(429))
    assert not is_out_of_credit(ValueError("402"))


def test_demo_mode_never_counts_or_checks(tmp_path: Path) -> None:
    clock = Clock()
    site = guard(tmp_path, clock, limit=0, enabled=False, read_bill=lambda: bill("99", "99"))
    asyncio.run(site.admit())
    assert site.used_today() == 0


def test_the_queue_is_first_come_first_served_and_says_who_is_ahead() -> None:
    async def run() -> None:
        queue = WorkQueue(1, 2)
        first, second, third = queue.join(), queue.join(), queue.join()
        assert [queue.ahead_of(t) for t in (first, second, third)] == [0, 1, 2]
        with pytest.raises(HTTPException) as full:
            queue.join()
        assert full.value.status_code == 503
        order = []

        async def work(ticket: object, name: str) -> None:
            await queue.wait(ticket)
            order.append(name)
            await asyncio.sleep(0)
            await queue.leave(ticket)

        await asyncio.gather(work(third, "third"), work(second, "second"), work(first, "first"))
        assert order == ["first", "second", "third"]
        assert queue.ahead_of(first) == 0

    asyncio.run(run())


def test_a_slot_is_given_back_even_when_the_work_fails() -> None:
    async def run() -> None:
        queue = WorkQueue(1, 0)
        with pytest.raises(ValueError):
            async with queue.slot():
                raise ValueError("boom")
        async with queue.slot():
            pass

    asyncio.run(run())


def test_old_sessions_are_removed_and_everything_else_is_kept(tmp_path: Path) -> None:
    old, fresh = tmp_path / ("a" * 32), tmp_path / ("b" * 32)
    site = tmp_path / "_site"
    for folder in (old, fresh, site):
        folder.mkdir()
        (folder / "file.json").write_text("{}")
    long_ago = time.time() - 30 * 3600
    os.utime(old / "file.json", (long_ago, long_ago))
    os.utime(site / "file.json", (long_ago, long_ago))
    assert expired_sessions(tmp_path, 24) == [old.resolve()]
    assert remove_expired_sessions(tmp_path, 24) == 1
    assert not old.exists() and fresh.exists() and site.exists()


def test_the_page_serves_compressed_engine_files_with_the_right_type(tmp_path: Path) -> None:
    engine = b"\0asm" + b"x" * 5000
    (tmp_path / "junk.wasm").write_bytes(engine)
    (tmp_path / "junk.wasm.gz").write_bytes(gzip.compress(engine))
    (tmp_path / "index.html").write_text("<p>hi</p>")
    app = FastAPI()
    app.mount("/", StudioFiles(directory=tmp_path, html=True))
    with TestClient(app) as client:
        response = client.get("/junk.wasm", headers={"accept-encoding": "gzip"})
        assert response.status_code == 200 and response.content == engine
        assert response.headers["content-encoding"] == "gzip"
        assert response.headers["content-type"] == "application/wasm"
        assert response.headers["cache-control"] == "no-cache"
        plain = client.get("/junk.wasm", headers={"accept-encoding": "identity"})
        assert plain.content == engine and "content-encoding" not in plain.headers
        assert plain.headers["content-type"] == "application/wasm"
        assert "hi" in client.get("/").text


def live_settings(tmp_path: Path, limit: int) -> Settings:
    return Settings(
        mode="live",
        data_dir=tmp_path,
        session_secret="x" * 40,
        meta_key="k",
        modal_enabled=False,
        daily_request_limit=limit,
    )


def test_paid_routes_answer_to_the_daily_limit_before_calling_anyone(tmp_path: Path) -> None:
    with TestClient(create_app(live_settings(tmp_path, 0))) as client:
        for path, body in (
            ("/api/interpret", {"description": "a tin"}),
            ("/api/wonder", {"instruction": "x", "performers": []}),
        ):
            response = client.post(path, json=body)
            if response.status_code == 422:
                continue
            assert response.status_code == 429, (path, response.text)
            assert "today" in response.json()["detail"]
        limits = client.get("/api/health").json()["limits"]
    assert limits["requests_today"] == 0 and limits["daily_limit"] == 0
    assert "today" in limits["paused"]


def test_the_site_trusts_its_own_address_and_no_other(tmp_path: Path) -> None:
    with TestClient(
        create_app(live_settings(tmp_path, 5)), base_url="https://junk.example"
    ) as client:
        ours = client.post(
            "/api/interpret",
            json={"description": "a tin"},
            headers={"origin": "https://junk.example"},
        )
        assert ours.status_code != 403
        other = client.post(
            "/api/interpret",
            json={"description": "a tin"},
            headers={"origin": "https://elsewhere.example"},
        )
        assert other.status_code == 403


def test_modal_stops_at_its_budget_from_the_real_bill(tmp_path: Path) -> None:
    clock = Clock()
    settings = {"enabled": True, "uses_modal": True, "clock": clock}
    site = SiteGuard(tmp_path, 10, 20.0, lambda: None, read_bill=lambda: bill("19.99"), **settings)
    asyncio.run(site.admit())
    at_limit = SiteGuard(tmp_path, 10, 20.0, lambda: None, read_bill=lambda: bill("20"), **settings)
    assert refused(at_limit) == OUT_OF_MODAL


def test_meta_spend_adds_up_stops_at_its_budget_and_resets_each_month(tmp_path: Path) -> None:
    clock = Clock()
    site = guard(tmp_path, clock, limit=100, meta_monthly_limit=0.05)
    site.add_meta_spend(0.03)
    asyncio.run(site.admit())
    site.add_meta_spend(0.02)
    assert site.meta_spent() == pytest.approx(0.05)
    assert refused(site) == META_BUDGET_USED
    # A restarted container keeps the total.
    assert guard(tmp_path, clock, meta_monthly_limit=0.05).meta_spent() == pytest.approx(0.05)
    clock.now += 31 * DAY
    assert site.meta_spent() == 0
    asyncio.run(site.admit())


def test_meta_costs_use_the_published_prices_and_the_reply_token_counts() -> None:
    usage = SimpleNamespace(
        prompt_tokens=1000,
        completion_tokens=100,
        prompt_tokens_details=SimpleNamespace(cached_tokens=400),
    )
    expected = 600 * 1.25 / 1e6 + 400 * 0.15 / 1e6 + 100 * 4.25 / 1e6
    assert chat_cost(usage, SPARK) == pytest.approx(expected)
    assert chat_cost(None, SPARK) > 0, "A reply with no counts still costs something"


def test_a_live_gateway_totals_meta_calls_and_a_demo_one_does_not(tmp_path: Path) -> None:
    from services.gateway import meta_costs

    create_app(live_settings(tmp_path, 5))
    note_meta_cost(0.01)
    note_meta_cost(0.0025)
    with TestClient(create_app(live_settings(tmp_path, 5))) as client:
        assert client.get("/api/health").json()["limits"]["meta_spent_this_month"] == 0.0125
    meta_costs.set_meta_ledger(None)
