from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from quant_binance.models import DecisionIntent
from quant_binance.risk.sizing import quantity_from_notional, select_futures_leverage
from quant_binance.settings import Settings


class SupportsLiveOrder(Protocol):
    def place_order(self, *, market: str, order_params: dict[str, Any]) -> dict[str, Any]:
        ...

    def set_futures_leverage(self, *, symbol: str, leverage: int) -> dict[str, Any]:
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
    def __init__(self, client: SupportsLiveOrder, settings: Settings | None = None) -> None:
        self.client = client
        self.settings = settings

    def _target_futures_leverage(self, decision: DecisionIntent) -> int:
        if self.settings is None:
            return 1
        return select_futures_leverage(
            predictability_score=decision.predictability_score,
            trend_strength=decision.trend_strength,
            volume_confirmation=decision.volume_confirmation,
            liquidity_score=decision.liquidity_score,
            volatility_penalty=decision.volatility_penalty,
            overheat_penalty=decision.overheat_penalty,
            net_expected_edge_bps=decision.net_expected_edge_bps,
            estimated_round_trip_cost_bps=decision.estimated_round_trip_cost_bps,
            settings=self.settings,
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
        params = {
            "symbol": decision.symbol,
            "side": side,
            "type": "MARKET",
            "newOrderRespType": "RESULT",
        }
        if market == "spot" and side == "BUY":
            params["quoteOrderQty"] = f"{decision.order_intent_notional_usd:.2f}"
        else:
            params["quantity"] = f"{quantity:.8f}"
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
        if market == "futures" and self.settings is not None:
            leverage = self._target_futures_leverage(decision)
            self.client.set_futures_leverage(symbol=decision.symbol, leverage=leverage)
        response = self.client.place_order(market=market, order_params=order_params)
        quantity = float(order_params.get("quantity", 0.0))
        accepted = response.get("status", "").upper() not in {"REJECTED", "EXPIRED"} if response else False
        return LiveOrderResult(
            symbol=decision.symbol,
            market=market,
            side=order_params["side"],
            quantity=quantity,
            accepted=accepted,
            response=response,
        )
