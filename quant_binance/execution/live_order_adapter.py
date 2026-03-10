from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from quant_binance.models import DecisionIntent
from quant_binance.risk.sizing import quantity_from_notional
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
        risk = self.settings.risk
        thresholds = self.settings.mode_thresholds
        strong_setup = (
            decision.predictability_score >= thresholds.futures_score_min + 8.0
            and decision.net_expected_edge_bps >= decision.estimated_round_trip_cost_bps * 1.8
            and decision.liquidity_score >= thresholds.futures_liquidity_min + 0.08
            and decision.volatility_penalty <= max(0.0, thresholds.futures_volatility_penalty_max - 0.10)
            and decision.overheat_penalty <= max(0.0, thresholds.futures_overheat_penalty_max - 0.08)
        )
        good_setup = (
            decision.predictability_score >= thresholds.futures_score_min + 3.0
            and decision.net_expected_edge_bps >= decision.estimated_round_trip_cost_bps * 1.25
            and decision.liquidity_score >= thresholds.futures_liquidity_min
            and decision.volatility_penalty <= thresholds.futures_volatility_penalty_max
            and decision.overheat_penalty <= thresholds.futures_overheat_penalty_max
        )
        if strong_setup:
            return max(1, int(round(risk.max_futures_leverage)))
        if good_setup:
            return max(1, int(round(risk.target_futures_leverage)))
        return 1

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
