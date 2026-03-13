from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from quant_binance.models import DecisionIntent
from quant_binance.risk.sizing import quantity_from_notional, select_futures_leverage
from quant_binance.settings import Settings


class SupportsLiveOrder(Protocol):
    exchange_id: str

    def place_order(self, *, market: str, order_params: dict[str, Any]) -> dict[str, Any]:
        ...

    def set_futures_leverage(self, *, symbol: str, leverage: int) -> dict[str, Any]:
        ...

    def place_futures_position_tpsl(self, *, order_params: dict[str, Any]) -> dict[str, Any]:
        ...

    def place_spot_plan_order(self, *, order_params: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class LiveOrderResult:
    symbol: str
    market: str
    side: str
    quantity: float
    accepted: bool
    response: dict[str, Any]
    protection_orders: tuple[dict[str, Any], ...] = ()
    protection_error: str = ""


class DecisionLiveOrderAdapter:
    def __init__(self, client: SupportsLiveOrder, settings: Settings | None = None) -> None:
        self.client = client
        self.settings = settings

    def _exchange_id(self) -> str:
        return getattr(self.client, "exchange_id", "binance")

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

    def _set_futures_leverage_if_supported(self, *, decision: DecisionIntent) -> None:
        if self.settings is None:
            return
        leverage = self._target_futures_leverage(decision)
        try:
            self.client.set_futures_leverage(symbol=decision.symbol, leverage=leverage)
        except Exception as exc:
            if self._exchange_id() == "bitget":
                message = str(exc)
                if "40893" in message or "Unable to update the leverage factor" in message:
                    return
            raise

    def _is_bitget_unilateral_error(self, message: str) -> bool:
        normalized = message.lower()
        return (
            "40774" in message
            or "40762" in message
            or "unilateral position type" in normalized
            or "one-way position" in normalized
            or "one way position" in normalized
        )

    def _bitget_alternate_futures_params(self, order_params: dict[str, Any]) -> dict[str, Any]:
        alternate = dict(order_params)
        if "tradeSide" in alternate:
            alternate.pop("tradeSide", None)
            alternate["reduceOnly"] = "NO"
        else:
            alternate.pop("reduceOnly", None)
            alternate["tradeSide"] = "open"
        return alternate

    def _format_price(self, value: float) -> str:
        return f"{max(value, 0.0):.8f}"

    def _protection_prices(
        self,
        *,
        decision: DecisionIntent,
        reference_price: float,
    ) -> tuple[float, float]:
        stop_fraction = max(decision.stop_distance_bps, 0.0) / 10000.0
        reward_fraction = stop_fraction
        if self.settings is not None:
            reward_fraction = stop_fraction * self.settings.exit_rules.partial_take_profit_r
        if decision.side == "short":
            take_profit = reference_price * max(0.0, 1.0 - reward_fraction)
            stop_loss = reference_price * (1.0 + stop_fraction)
        else:
            take_profit = reference_price * (1.0 + reward_fraction)
            stop_loss = reference_price * max(0.0, 1.0 - stop_fraction)
        return take_profit, stop_loss

    def _build_bitget_protection_payloads(
        self,
        *,
        decision: DecisionIntent,
        reference_price: float,
        quantity: float,
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        take_profit, stop_loss = self._protection_prices(
            decision=decision,
            reference_price=reference_price,
        )
        if decision.final_mode == "futures":
            hold_side = "buy" if decision.side == "long" else "sell"
            return (
                (
                    "futures",
                    {
                        "marginCoin": "USDT",
                        "productType": "USDT-FUTURES",
                        "symbol": decision.symbol,
                        "stopSurplusTriggerPrice": self._format_price(take_profit),
                        "stopSurplusTriggerType": "mark_price",
                        "stopSurplusExecutePrice": "0",
                        "stopLossTriggerPrice": self._format_price(stop_loss),
                        "stopLossTriggerType": "mark_price",
                        "stopLossExecutePrice": "0",
                        "holdSide": hold_side,
                        "stopSurplusClientOid": f"{decision.decision_id}-tp",
                        "stopLossClientOid": f"{decision.decision_id}-sl",
                    },
                ),
            )
        if decision.final_mode == "spot" and decision.side == "long":
            size = f"{quantity:.8f}"
            return (
                (
                    "spot",
                    {
                        "symbol": decision.symbol,
                        "side": "sell",
                        "triggerPrice": self._format_price(take_profit),
                        "triggerType": "market_price",
                        "orderType": "market",
                        "planType": "amount",
                        "size": size,
                        "clientOid": f"{decision.decision_id}-tp",
                    },
                ),
                (
                    "spot",
                    {
                        "symbol": decision.symbol,
                        "side": "sell",
                        "triggerPrice": self._format_price(stop_loss),
                        "triggerType": "market_price",
                        "orderType": "market",
                        "planType": "amount",
                        "size": size,
                        "clientOid": f"{decision.decision_id}-sl",
                    },
                ),
            )
        return ()

    def _submit_protection_orders(
        self,
        *,
        decision: DecisionIntent,
        reference_price: float,
        quantity: float,
    ) -> tuple[dict[str, Any], ...]:
        if self._exchange_id() != "bitget":
            return ()
        payloads = self._build_bitget_protection_payloads(
            decision=decision,
            reference_price=reference_price,
            quantity=quantity,
        )
        results: list[dict[str, Any]] = []
        for market, order_params in payloads:
            if market == "futures":
                result = self.client.place_futures_position_tpsl(order_params=order_params)
            else:
                result = self.client.place_spot_plan_order(order_params=order_params)
            results.append(
                {
                    "market": market,
                    "request": order_params,
                    "response": result,
                }
            )
        return tuple(results)

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
            params = {
                "symbol": decision.symbol,
                "side": side.lower(),
                "orderType": "market",
                "clientOid": decision.decision_id,
            }
            if market == "spot" and side == "BUY":
                params["size"] = f"{decision.order_intent_notional_usd:.2f}"
            else:
                params["size"] = f"{quantity:.8f}"
            if market == "futures":
                params["productType"] = "USDT-FUTURES"
                params["marginCoin"] = "USDT"
                params["marginMode"] = "crossed"
                params["tradeSide"] = "close" if decision.side == "flat" else "open"
            return market, params
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
        if market == "futures":
            self._set_futures_leverage_if_supported(decision=decision)
        try:
            response = self.client.place_order(market=market, order_params=order_params)
        except Exception as exc:
            if self._exchange_id() == "bitget" and market == "futures" and self._is_bitget_unilateral_error(str(exc)):
                order_params = self._bitget_alternate_futures_params(order_params)
                response = self.client.place_order(market=market, order_params=order_params)
            else:
                raise
        quantity = float(order_params.get("quantity", order_params.get("size", 0.0)))
        accepted = response.get("status", "").upper() not in {"REJECTED", "EXPIRED"} if response else False
        protection_orders = ()
        protection_error = ""
        if accepted:
            try:
                protection_orders = self._submit_protection_orders(
                    decision=decision,
                    reference_price=reference_price,
                    quantity=quantity,
                )
            except Exception as exc:
                protection_error = repr(exc)
        return LiveOrderResult(
            symbol=decision.symbol,
            market=market,
            side=order_params["side"],
            quantity=quantity,
            accepted=accepted,
            response=response,
            protection_orders=protection_orders,
            protection_error=protection_error,
        )
