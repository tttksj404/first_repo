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


@dataclass(frozen=True)
class LiveOrderResult:
    symbol: str
    market: str
    side: str
    quantity: float
    accepted: bool
    response: dict[str, Any]


class DecisionLiveOrderAdapter:
    _BITGET_MARGIN_SAFETY_BUFFER = 0.9

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

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _extract_effective_futures_leverage(self, response: dict[str, Any] | None, fallback: int) -> int:
        if not isinstance(response, dict):
            return max(int(fallback), 1)
        for key in ("leverage", "longLeverage", "shortLeverage", "crossMarginLeverage"):
            parsed = self._safe_float(response.get(key))
            if parsed > 0:
                return max(int(round(parsed)), 1)
        return max(int(fallback), 1)

    def _fetch_futures_available_balance_usd(self) -> float | None:
        getter = getattr(self.client, "get_account", None)
        if getter is None or not callable(getter):
            return None
        try:
            payload = getter(market="futures")
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        available = self._safe_float(payload.get("availableBalance"))
        if available > 0:
            return available
        available = self._safe_float(payload.get("rawAvailableBalance"))
        if available > 0:
            return available
        available = self._safe_float(payload.get("crossedMaxAvailable"))
        if available > 0:
            return available
        return None

    def _cap_futures_notional_by_balance(
        self,
        *,
        requested_notional_usd: float,
        effective_leverage: int,
    ) -> float:
        if self.settings is None:
            return requested_notional_usd
        available_balance = self._fetch_futures_available_balance_usd()
        if available_balance is None or available_balance <= 0:
            return requested_notional_usd
        reserve_fraction = max(self.settings.cash_reserve.when_futures_enabled, 0.0)
        capped_notional = (
            available_balance
            * max(float(effective_leverage), 1.0)
            * max(1.0 - reserve_fraction, 0.0)
            * self._BITGET_MARGIN_SAFETY_BUFFER
        )
        if capped_notional <= 0:
            return requested_notional_usd
        return min(requested_notional_usd, round(capped_notional, 6))

    def build_order_params(
        self,
        *,
        decision: DecisionIntent,
        reference_price: float,
        notional_override_usd: float | None = None,
    ) -> tuple[str, dict[str, Any]] | None:
        if decision.final_mode not in {"spot", "futures"}:
            return None
        target_notional_usd = (
            decision.order_intent_notional_usd
            if notional_override_usd is None
            else max(float(notional_override_usd), 0.0)
        )
        quantity = quantity_from_notional(target_notional_usd, reference_price)
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
                params["size"] = f"{target_notional_usd:.2f}"
            else:
                params["size"] = f"{quantity:.8f}"
            if market == "futures":
                params["productType"] = "USDT-FUTURES"
                params["marginCoin"] = "USDT"
                params["marginMode"] = "crossed"
                params["reduceOnly"] = "NO"
            return market, params
        params = {
            "symbol": decision.symbol,
            "side": side,
            "type": "MARKET",
            "newOrderRespType": "RESULT",
        }
        if market == "spot" and side == "BUY":
            params["quoteOrderQty"] = f"{target_notional_usd:.2f}"
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
            effective_leverage = leverage
            try:
                leverage_response = self.client.set_futures_leverage(symbol=decision.symbol, leverage=leverage)
                effective_leverage = self._extract_effective_futures_leverage(leverage_response, fallback=leverage)
            except Exception as exc:
                if self._exchange_id() == "bitget" and "code=40893" in str(exc):
                    # Bitget can reject leverage updates for temporary margin reasons; continue with conservative sizing.
                    effective_leverage = 1
                else:
                    raise
            capped_notional = self._cap_futures_notional_by_balance(
                requested_notional_usd=decision.order_intent_notional_usd,
                effective_leverage=effective_leverage,
            )
            if capped_notional < decision.order_intent_notional_usd:
                rebuilt = self.build_order_params(
                    decision=decision,
                    reference_price=reference_price,
                    notional_override_usd=capped_notional,
                )
                if rebuilt is not None:
                    market, order_params = rebuilt
        response = self.client.place_order(market=market, order_params=order_params)
        quantity = float(order_params.get("quantity", order_params.get("size", 0.0)))
        accepted = response.get("status", "").upper() not in {"REJECTED", "EXPIRED"} if response else False
        return LiveOrderResult(
            symbol=decision.symbol,
            market=market,
            side=order_params["side"],
            quantity=quantity,
            accepted=accepted,
            response=response,
        )
