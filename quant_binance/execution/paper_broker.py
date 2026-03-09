from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from quant_binance.models import DecisionIntent


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    symbol: str
    mode: str
    side: str
    notional_usd: float
    created_at: datetime
    decision_hash: str


class PaperBroker:
    """Minimal in-memory paper broker for deterministic strategy testing."""

    def __init__(self) -> None:
        self.orders: list[PaperOrder] = []

    def submit(self, decision: DecisionIntent) -> PaperOrder | None:
        if decision.final_mode == "cash" or decision.order_intent_notional_usd <= 0:
            return None
        order = PaperOrder(
            order_id=str(uuid4()),
            symbol=decision.symbol,
            mode=decision.final_mode,
            side=decision.side,
            notional_usd=decision.order_intent_notional_usd,
            created_at=decision.timestamp,
            decision_hash=decision.decision_hash,
        )
        self.orders.append(order)
        return order
