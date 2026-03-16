from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from quant_binance.models import DecisionIntent
from quant_binance.risk.sizing import quantity_from_notional


class SupportsTestOrder(Protocol):
    exchange_id: str

    def test_order(self, *, market: str, order_params: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class OrderTestResult:
    symbol: str
    market: str
    side: str
    quantity: float
    accepted: bool
    response: dict[str, Any]


class DecisionOrderTestAdapter:
    def __init__(self, client: SupportsTestOrder) -> None:
        self.client = client

    def _exchange_id(self) -> str:
        return getattr(self.client, "exchange_id", "binance")

    def _execution_symbol(self, decision: DecisionIntent) -> str:
        return decision.execution_symbol or decision.symbol

    def _uses_spot_quote_notional(self, decision: DecisionIntent) -> bool:
        return (
            decision.final_mode == "spot"
            and decision.side == "long"
            and (decision.spot_quote_asset or "USDT") == "USDT"
            and self._execution_symbol(decision).endswith("USDT")
        )

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
        side = "BUY" if decision.side == "long" else "SELL"
        if self._exchange_id() == "bitget":
            order_params = {
                "symbol": self._execution_symbol(decision),
                "side": side.lower(),
                "orderType": "market",
                "clientOid": decision.decision_id,
            }
            if market == "spot" and side == "BUY" and self._uses_spot_quote_notional(decision):
                order_params["size"] = f"{decision.order_intent_notional_usd:.2f}"
            else:
                order_params["size"] = f"{quantity:.8f}"
            if market == "futures":
                order_params["productType"] = "USDT-FUTURES"
                order_params["marginCoin"] = "USDT"
                order_params["marginMode"] = "crossed"
                order_params["reduceOnly"] = "NO"
            return market, order_params
        order_params = {
            "symbol": self._execution_symbol(decision),
            "side": side,
            "type": "MARKET",
        }
        if market == "spot" and side == "BUY" and self._uses_spot_quote_notional(decision):
            order_params["quoteOrderQty"] = f"{decision.order_intent_notional_usd:.2f}"
        else:
            order_params["quantity"] = f"{quantity:.8f}"
        if market == "futures":
            order_params["reduceOnly"] = "false"
        return market, order_params

    def test_decision(
        self,
        *,
        decision: DecisionIntent,
        reference_price: float,
    ) -> OrderTestResult | None:
        built = self.build_order_params(decision=decision, reference_price=reference_price)
        if built is None:
            return None
        market, order_params = built
        response = self.client.test_order(market=market, order_params=order_params)
        quantity = float(order_params.get("quantity", order_params.get("size", 0.0)))
        accepted = response.get("status", "ok") not in {"error", "rejected"}
        return OrderTestResult(
            symbol=decision.symbol,
            market=market,
            side=order_params["side"],
            quantity=quantity,
            accepted=accepted,
            response=response,
        )
