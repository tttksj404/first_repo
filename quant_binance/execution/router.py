from __future__ import annotations

from quant_binance.execution.paper_broker import PaperBroker, PaperOrder
from quant_binance.models import DecisionIntent


class ExecutionRouter:
    def __init__(
        self,
        *,
        spot_broker: PaperBroker | None = None,
        futures_broker: PaperBroker | None = None,
    ) -> None:
        self.spot_broker = spot_broker or PaperBroker()
        self.futures_broker = futures_broker or PaperBroker()

    def route(self, decision: DecisionIntent, *, reference_price: float | None = None) -> PaperOrder | None:
        if decision.final_mode == "spot":
            order = self.spot_broker.submit(decision)
            if reference_price is not None:
                self.spot_broker.ensure_position(decision, reference_price=reference_price)
            return order
        if decision.final_mode == "futures":
            order = self.futures_broker.submit(decision)
            if reference_price is not None:
                self.futures_broker.ensure_position(decision, reference_price=reference_price)
            return order
        return None
