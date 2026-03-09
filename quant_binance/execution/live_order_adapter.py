from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from quant_binance.models import DecisionIntent
from quant_binance.risk.sizing import quantity_from_notional


class SupportsLiveOrder(Protocol):
    def place_order(self, *, market: str, order_params: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class LiveOrderResult:
    symbol: str
    market: str
    side: str
    quantity: float
    accepted: bool
    response: dict[str, Any]


class DecisionLiveOrderAdapter:
    def __init__(self, client: SupportsLiveOrder) -> None:
        self.client = client

    def build_order_params(
        self,
        *,
        decision: DecisionIntent,
        reference_price: float,
    ) -> tuple[str, dict[str, Any]] | None:
        if decision.final_mode not in {"spot", "futures"}:
            return None
        quantity = quantity_from_notional(decision.order_intent_notional_usd, reference_price)
        market = "futures" if decision.final_mode == "futures" else "spot"
        params = {
            "symbol": decision.symbol,
            "side": "BUY" if decision.side == "long" else "SELL",
            "type": "MARKET",
            "quantity": f"{quantity:.8f}",
            "newOrderRespType": "RESULT",
        }
        if market == "futures":
            params["reduceOnly"] = "false"
        return market, params

    def execute_decision(
        self,
        *,
        decision: DecisionIntent,
        reference_price: float,
    ) -> LiveOrderResult | None:
        built = self.build_order_params(decision=decision, reference_price=reference_price)
        if built is None:
            return None
        market, order_params = built
        response = self.client.place_order(market=market, order_params=order_params)
        quantity = float(order_params["quantity"])
        accepted = response.get("status", "").upper() not in {"REJECTED", "EXPIRED"} if response else False
        return LiveOrderResult(
            symbol=decision.symbol,
            market=market,
            side=order_params["side"],
            quantity=quantity,
            accepted=accepted,
            response=response,
        )
