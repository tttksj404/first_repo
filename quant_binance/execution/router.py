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

    def route(self, decision: DecisionIntent) -> PaperOrder | None:
        if decision.final_mode == "spot":
            return self.spot_broker.submit(decision)
        if decision.final_mode == "futures":
            return self.futures_broker.submit(decision)
        return None
