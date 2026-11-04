"""What Meta charges for each call, since its API has no way to ask what has been spent.

Prices are from https://dev.meta.ai/docs/pricing-rate-limits, as listed on 2026-11-04.
"""

from collections.abc import Callable
from typing import Any

SAM_IMAGE = 2.50 / 1000
MUSE_IMAGE = 0.01
# Dollars per token: uncached input, cached input and output.
SPARK = (1.25 / 1e6, 0.15 / 1e6, 4.25 / 1e6)
# For a reply that does not say how many tokens it used. Generous for this app's short requests.
UNKNOWN_CHAT_TOKENS = 4000

_ledger: Callable[[float], None] | None = None


def set_meta_ledger(ledger: Callable[[float], None] | None) -> None:
    global _ledger
    _ledger = ledger


def note_meta_cost(amount: float) -> None:
    if _ledger is not None:
        _ledger(amount)


def chat_cost(usage: Any, prices: tuple[float, float, float]) -> float:  # noqa: ANN401
    """The real cost of a chat reply from the token counts it reports."""
    uncached_price, cached_price, output_price = prices
    if usage is None:
        return UNKNOWN_CHAT_TOKENS * output_price
    details = getattr(usage, "prompt_tokens_details", None)
    cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
    prompt = (usage.prompt_tokens or 0) - cached
    return (
        prompt * uncached_price
        + cached * cached_price
        + (usage.completion_tokens or 0) * output_price
    )


def note_chat_cost(response: Any, prices: tuple[float, float, float]) -> None:  # noqa: ANN401
    note_meta_cost(chat_cost(getattr(response, "usage", None), prices))
