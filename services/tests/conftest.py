from decimal import Decimal
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def no_real_billing_lookups(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the real Modal bill, wherever a gateway is created."""
    monkeypatch.setattr(
        "services.gateway.limits.read_modal_bill",
        lambda: SimpleNamespace(metered_cost=Decimal("1"), billed_cost=Decimal("0")),
    )
