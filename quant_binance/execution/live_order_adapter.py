from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    _BITGET_MAX_BALANCE_LEVERAGE_FOR_SIZING = 6.0
    _BITGET_MIN_NOTIONAL_BUFFER = 1.02
    _BITGET_ZERO_CROSS_FALLBACK_FACTOR = 0.08

    def __init__(self, client: SupportsLiveOrder, settings: Settings | None = None) -> None:
        self.client = client
        self.settings = settings
        self._last_set_leverage_by_symbol: dict[str, int] = {}
        self._last_set_leverage_at_by_symbol: dict[str, datetime] = {}
        self._leverage_refresh_interval = timedelta(seconds=300)

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

    def _bitget_required_min_notional_usd(self, *, symbol: str) -> float:
        if self._exchange_id() != "bitget":
            return 0.0
        min_trade_reader = getattr(self.client, "_futures_min_trade_usdt", None)
        if not callable(min_trade_reader):
            return 0.0
        try:
            min_trade_usdt = self._safe_float(min_trade_reader(symbol=symbol))
        except Exception:
            return 0.0
        if min_trade_usdt <= 0:
            return 0.0
        return min_trade_usdt * self._BITGET_MIN_NOTIONAL_BUFFER

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
        if self._exchange_id() == "bitget":
            effective = self._safe_float(payload.get("effectiveAvailableBalance"))
            if effective > 0:
                return effective
            crossed = self._safe_float(payload.get("crossedMaxAvailable"))
            if crossed > 0:
                return crossed
            # Some Bitget account snapshots report crossed/effective as zero even when
            # raw available balance is positive. Use a conservative fraction fallback
            # to keep live execution responsive while containing 40762 risk.
            raw_available = self._safe_float(payload.get("availableBalance"))
            raw_available = max(raw_available, self._safe_float(payload.get("rawAvailableBalance")))
            union_available = self._safe_float(payload.get("unionAvailable"))
            fallback_base = min(raw_available, union_available) if union_available > 0 else raw_available
            if fallback_base > 0:
                return fallback_base * self._BITGET_ZERO_CROSS_FALLBACK_FACTOR
        effective = self._safe_float(payload.get("effectiveAvailableBalance"))
        if effective > 0:
            return effective
        crossed = self._safe_float(payload.get("crossedMaxAvailable"))
        if crossed > 0:
            return crossed
        union_available = self._safe_float(payload.get("unionAvailable"))
        available = self._safe_float(payload.get("availableBalance"))
        if union_available > 0 and available > 0:
            return min(union_available, available)
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
        symbol: str,
        requested_notional_usd: float,
        effective_leverage: int,
    ) -> float:
        if self.settings is None:
            return requested_notional_usd
        available_balance = self._fetch_futures_available_balance_usd()
        if available_balance is None:
            return requested_notional_usd
        if available_balance <= 0:
            if self._exchange_id() == "bitget":
                return 0.0
            return requested_notional_usd
        reserve_fraction = max(self.settings.cash_reserve.when_futures_enabled, 0.0)
        if self._exchange_id() == "bitget":
            # Session-level execution capping already applies reserve; avoid compounding conservative reserve twice.
            reserve_fraction = 0.0
        leverage_for_sizing = max(float(effective_leverage), 1.0)
        if self._exchange_id() == "bitget":
            # Keep Bitget live sizing bounded by available margin to avoid repeated 40762 balance rejections.
            leverage_for_sizing = min(leverage_for_sizing, self._BITGET_MAX_BALANCE_LEVERAGE_FOR_SIZING)
        capped_notional = (
            available_balance
            * leverage_for_sizing
            * max(1.0 - reserve_fraction, 0.0)
            * self._BITGET_MARGIN_SAFETY_BUFFER
        )
        if self._exchange_id() == "bitget":
            # If conservative sizing falls below exchange minimum notional, allow using the
            # currently active leverage (already validated by exchange) to keep orders executable.
            required_min_notional = self._bitget_required_min_notional_usd(symbol=symbol)
            if required_min_notional > 0 and capped_notional + 1e-9 < required_min_notional:
                expanded_cap = (
                    available_balance
                    * max(float(effective_leverage), 1.0)
                    * max(1.0 - reserve_fraction, 0.0)
                    * self._BITGET_MARGIN_SAFETY_BUFFER
                )
                if expanded_cap + 1e-9 >= required_min_notional:
                    capped_notional = min(requested_notional_usd, expanded_cap)
        if capped_notional <= 0:
            return requested_notional_usd
        return min(requested_notional_usd, round(capped_notional, 6))

    def _ensure_bitget_min_order_leverage(
        self,
        *,
        symbol: str,
        effective_leverage: int,
        now: datetime,
    ) -> int:
        if self._exchange_id() != "bitget" or self.settings is None:
            return effective_leverage
        available_balance = self._fetch_futures_available_balance_usd()
        if available_balance is None or available_balance <= 0:
            return effective_leverage
        required_min_notional = self._bitget_required_min_notional_usd(symbol=symbol)
        if required_min_notional <= 0:
            return effective_leverage
        current_capacity = (
            available_balance
            * max(float(effective_leverage), 1.0)
            * self._BITGET_MARGIN_SAFETY_BUFFER
        )
        if current_capacity + 1e-9 >= required_min_notional:
            return effective_leverage
        max_allowed_leverage = max(int(math.ceil(self.settings.risk.max_futures_leverage)), 1)
        needed_leverage = int(
            math.ceil(
                required_min_notional
                / max(available_balance * self._BITGET_MARGIN_SAFETY_BUFFER, 1e-9)
            )
        )
        target_leverage = min(
            max(max(needed_leverage, int(effective_leverage) + 1), 1),
            max_allowed_leverage,
        )
        if target_leverage <= int(effective_leverage):
            return effective_leverage
        try:
            leverage_response = self.client.set_futures_leverage(symbol=symbol, leverage=target_leverage)
        except Exception:
            return effective_leverage
        boosted = self._extract_effective_futures_leverage(
            leverage_response,
            fallback=target_leverage,
        )
        self._last_set_leverage_by_symbol[symbol] = boosted
        self._last_set_leverage_at_by_symbol[symbol] = now
        return boosted

    def _should_refresh_leverage(self, *, symbol: str, target_leverage: int, now: datetime) -> bool:
        previous = self._last_set_leverage_by_symbol.get(symbol)
        if previous is None:
            return True
        if previous != target_leverage:
            return True
        last_set_at = self._last_set_leverage_at_by_symbol.get(symbol)
        if last_set_at is None:
            return True
        return now - last_set_at >= self._leverage_refresh_interval

    def _bitget_futures_order_is_executable(self, *, symbol: str, order_params: dict[str, Any]) -> bool:
        if self._exchange_id() != "bitget":
            return True
        raw_size = self._safe_float(order_params.get("size"))
        if raw_size <= 0:
            return False
        normalizer = getattr(self.client, "_normalize_futures_size", None)
        normalized_size = raw_size
        if callable(normalizer):
            try:
                normalized_size = self._safe_float(normalizer(symbol=symbol, size=raw_size))
            except Exception:
                normalized_size = raw_size
            if normalized_size <= 0:
                return False
            order_params["size"] = f"{normalized_size:.8f}"
        min_trade_reader = getattr(self.client, "_futures_min_trade_usdt", None)
        if not callable(min_trade_reader):
            return True
        min_trade_usdt = 0.0
        try:
            min_trade_usdt = self._safe_float(min_trade_reader(symbol=symbol))
        except Exception:
            min_trade_usdt = 0.0
        if min_trade_usdt <= 0:
            return True
        ticker_reader = getattr(self.client, "get_book_ticker", None)
        if not callable(ticker_reader):
            return True
        try:
            ticker = ticker_reader(market="futures", symbol=symbol)
        except Exception:
            return True
        bid_price = self._safe_float(ticker.get("bidPrice")) if isinstance(ticker, dict) else 0.0
        if bid_price <= 0:
            return True
        required_min_notional = min_trade_usdt * self._BITGET_MIN_NOTIONAL_BUFFER
        return (normalized_size * bid_price + 1e-9) >= required_min_notional

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
            now = datetime.now(tz=timezone.utc)
            leverage = self._target_futures_leverage(decision)
            effective_leverage = leverage
            if self._should_refresh_leverage(symbol=decision.symbol, target_leverage=leverage, now=now):
                try:
                    leverage_response = self.client.set_futures_leverage(symbol=decision.symbol, leverage=leverage)
                    fallback_leverage = self._last_set_leverage_by_symbol.get(
                        decision.symbol,
                        1 if self._exchange_id() == "bitget" else leverage,
                    )
                    effective_leverage = self._extract_effective_futures_leverage(
                        leverage_response,
                        fallback=fallback_leverage,
                    )
                    self._last_set_leverage_by_symbol[decision.symbol] = effective_leverage
                    self._last_set_leverage_at_by_symbol[decision.symbol] = now
                except Exception as exc:
                    if self._exchange_id() == "bitget" and "code=40893" in str(exc):
                        # Bitget can reject leverage updates when changing leverage is temporarily blocked.
                        # Fall back to the most recent known leverage (or target leverage if unknown).
                        effective_leverage = max(self._last_set_leverage_by_symbol.get(decision.symbol, leverage), 1)
                        self._last_set_leverage_by_symbol[decision.symbol] = effective_leverage
                        self._last_set_leverage_at_by_symbol[decision.symbol] = now
                    else:
                        raise
            else:
                effective_leverage = self._last_set_leverage_by_symbol.get(
                    decision.symbol,
                    1 if self._exchange_id() == "bitget" else leverage,
                )
            effective_leverage = self._ensure_bitget_min_order_leverage(
                symbol=decision.symbol,
                effective_leverage=effective_leverage,
                now=now,
            )
            capped_notional = self._cap_futures_notional_by_balance(
                symbol=decision.symbol,
                requested_notional_usd=decision.order_intent_notional_usd,
                effective_leverage=effective_leverage,
            )
            if capped_notional <= 0:
                return None
            if capped_notional < decision.order_intent_notional_usd:
                rebuilt = self.build_order_params(
                    decision=decision,
                    reference_price=reference_price,
                    notional_override_usd=capped_notional,
                )
                if rebuilt is not None:
                    market, order_params = rebuilt
        if market == "futures" and not self._bitget_futures_order_is_executable(symbol=decision.symbol, order_params=order_params):
            return None
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
