from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
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

    def get_max_openable_quantity(
        self,
        *,
        symbol: str,
        pos_side: str,
        order_type: str = "market",
        open_amount: float | None = None,
    ) -> float | None:
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
        self._exchange_info_cache: dict[str, dict[str, dict[str, Any]]] = {}
        self._last_preflight_rejection: dict[str, Any] | None = None

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

    def pop_last_preflight_rejection(self) -> dict[str, Any] | None:
        payload = self._last_preflight_rejection
        self._last_preflight_rejection = None
        return payload

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
        code = self._bitget_error_code(message)
        normalized = message.lower()
        has_unilateral_marker = (
            "unilateral position type" in normalized
            or "one-way position" in normalized
            or "one way position" in normalized
        )
        return code == "40774" or has_unilateral_marker

    def _bitget_error_code(self, message: str) -> str:
        match = re.search(r'"code":"?([0-9A-Za-z_-]+)"?', message)
        if match is None:
            return ""
        return match.group(1)

    def _bitget_reduce_only_value(self, order_params: dict[str, Any]) -> str:
        existing = str(order_params.get("reduceOnly", "")).strip().upper()
        if existing in {"YES", "NO"}:
            return existing
        trade_side = str(order_params.get("tradeSide", "")).strip().lower()
        return "YES" if trade_side == "close" else "NO"

    def _bitget_alternate_futures_params(self, order_params: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        reduce_only_value = self._bitget_reduce_only_value(order_params)
        trade_side = str(order_params.get("tradeSide", "")).strip().lower() or "open"
        alternates: list[dict[str, Any]] = []

        def add(candidate: dict[str, Any]) -> None:
            if candidate == order_params:
                return
            if candidate in alternates:
                return
            alternates.append(candidate)

        without_trade_side = dict(order_params)
        without_trade_side.pop("tradeSide", None)
        add(without_trade_side)

        with_reduce_only = dict(without_trade_side)
        with_reduce_only["reduceOnly"] = reduce_only_value
        add(with_reduce_only)

        without_reduce_only = dict(order_params)
        without_reduce_only.pop("reduceOnly", None)
        add(without_reduce_only)

        with_trade_side = dict(without_reduce_only)
        with_trade_side["tradeSide"] = trade_side
        add(with_trade_side)

        return tuple(alternates)

    def _bitget_symbol_metadata(self, *, market: str, symbol: str) -> dict[str, Any]:
        cache = self._exchange_info_cache.setdefault(market, {})
        if symbol in cache:
            return cache[symbol]
        getter = getattr(self.client, "get_exchange_info", None)
        if not callable(getter):
            cache[symbol] = {}
            return cache[symbol]
        try:
            info = getter(market=market)
        except Exception:
            cache[symbol] = {}
            return cache[symbol]
        for row in info.get("symbols", []):
            row_symbol = str(row.get("symbol", ""))
            if not row_symbol:
                continue
            cache[row_symbol] = dict(row.get("raw") or {})
        cache.setdefault(symbol, {})
        return cache[symbol]

    def _bitget_price_decimals(self, *, market: str, symbol: str) -> int | None:
        metadata = self._bitget_symbol_metadata(market=market, symbol=symbol)
        for key in ("pricePlace", "priceScale"):
            value = metadata.get(key)
            if value not in (None, ""):
                try:
                    return max(int(value), 0)
                except (TypeError, ValueError):
                    continue
        tick_size = metadata.get("tickSize")
        if tick_size in (None, ""):
            return None
        text = str(tick_size).strip()
        if not text or "." not in text:
            return 0 if text else None
        return max(len(text.rstrip("0").split(".", 1)[1]), 0)

    def _bitget_min_quantity(self, *, market: str, symbol: str) -> float:
        metadata = self._bitget_symbol_metadata(market=market, symbol=symbol)
        for key in ("minTradeNum", "minQty"):
            value = metadata.get(key)
            if value not in (None, ""):
                try:
                    return max(float(value), 0.0)
                except (TypeError, ValueError):
                    continue
        return 0.0

    def _bitget_quantity_step(self, *, market: str, symbol: str) -> float:
        metadata = self._bitget_symbol_metadata(market=market, symbol=symbol)
        for key in ("sizeMultiplier", "stepSize"):
            value = metadata.get(key)
            if value not in (None, ""):
                try:
                    return max(float(value), 0.0)
                except (TypeError, ValueError):
                    continue
        return 0.0

    def normalize_quantity(self, *, market: str, symbol: str, quantity: float) -> float:
        safe_quantity = max(float(quantity), 0.0)
        if self._exchange_id() != "bitget":
            return round(safe_quantity, 8)
        step = self._bitget_quantity_step(market=market, symbol=symbol)
        if step <= 0.0:
            return round(safe_quantity, 8)
        step_dec = Decimal(str(step))
        qty_dec = Decimal(str(safe_quantity))
        normalized = (qty_dec // step_dec) * step_dec
        return float(normalized)

    def format_quantity(self, *, market: str, symbol: str, quantity: float) -> str:
        normalized = self.normalize_quantity(market=market, symbol=symbol, quantity=quantity)
        if self._exchange_id() != "bitget":
            return f"{normalized:.8f}"
        metadata = self._bitget_symbol_metadata(market=market, symbol=symbol)
        decimals = metadata.get("volumePlace")
        try:
            precision = max(int(decimals), 0)
        except (TypeError, ValueError):
            step = self._bitget_quantity_step(market=market, symbol=symbol)
            if step <= 0.0:
                precision = 8
            else:
                step_text = str(step).rstrip("0")
                precision = len(step_text.split(".", 1)[1]) if "." in step_text else 0
        return format(Decimal(str(normalized)), f".{precision}f")

    def format_trigger_price(self, *, value: float, market: str, symbol: str) -> str:
        safe_value = max(value, 0.0)
        if self._exchange_id() != "bitget":
            return f"{safe_value:.8f}"
        decimals = self._bitget_price_decimals(market=market, symbol=symbol)
        if decimals is None:
            return f"{safe_value:.8f}"
        quantum = Decimal("1").scaleb(-decimals)
        rounded = Decimal(str(safe_value)).quantize(quantum, rounding=ROUND_HALF_UP)
        return format(rounded, f".{decimals}f")

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
            hold_side = "long" if decision.side == "long" else "short"
            return (
                (
                    "futures",
                    {
                        "marginCoin": "USDT",
                        "productType": "USDT-FUTURES",
                        "symbol": decision.symbol,
                        "stopSurplusTriggerPrice": self.format_trigger_price(
                            value=take_profit,
                            market="futures",
                            symbol=decision.symbol,
                        ),
                        "stopSurplusTriggerType": "mark_price",
                        "stopLossTriggerPrice": self.format_trigger_price(
                            value=stop_loss,
                            market="futures",
                            symbol=decision.symbol,
                        ),
                        "stopLossTriggerType": "mark_price",
                        "holdSide": hold_side,
                        "stopSurplusClientOid": f"{decision.decision_id}-tp",
                        "stopLossClientOid": f"{decision.decision_id}-sl",
                    },
                ),
            )
        if decision.final_mode == "spot" and decision.side == "long":
            if not self._uses_spot_quote_notional(decision):
                return ()
            size = f"{quantity:.8f}"
            return (
                (
                    "spot",
                    {
                        "symbol": execution_symbol,
                        "side": "sell",
                        "triggerPrice": self.format_trigger_price(
                            value=take_profit,
                            market="spot",
                            symbol=self._execution_symbol(decision),
                        ),
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
                        "symbol": execution_symbol,
                        "side": "sell",
                        "triggerPrice": self.format_trigger_price(
                            value=stop_loss,
                            market="spot",
                            symbol=self._execution_symbol(decision),
                        ),
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
        if self._exchange_id() == "bitget" and decision.final_mode == "futures":
            return ()
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

    def _spot_quantity_reference_price(self, decision: DecisionIntent, reference_price: float) -> float:
        if (decision.spot_quote_asset or "USDT") == "USDT":
            return reference_price
        quote_asset_usd_price = float(decision.spot_quote_asset_usd_price or 0.0)
        if quote_asset_usd_price <= 0.0:
            return reference_price
        return reference_price * quote_asset_usd_price

    def build_order_params(
        self,
        *,
        decision: DecisionIntent,
        reference_price: float,
    ) -> tuple[str, dict[str, Any]] | None:
        self._last_preflight_rejection = None
        if decision.final_mode not in {"spot", "futures"}:
            return None
        quantity = quantity_from_notional(decision.order_intent_notional_usd, self._spot_quantity_reference_price(decision, reference_price) if decision.final_mode == "spot" else reference_price)
        market = "futures" if decision.final_mode == "futures" else "spot"
        side = "BUY" if decision.side == "long" else "SELL"
        execution_symbol = self._execution_symbol(decision)
        if market == "futures" and self._exchange_id() == "bitget" and hasattr(self.client, "get_max_openable_quantity"):
            max_open = self.client.get_max_openable_quantity(
                symbol=decision.symbol,
                pos_side="long" if decision.side == "long" else "short",
                order_type="market",
            )
            if max_open is not None:
                if max_open <= 0.0:
                    self._last_preflight_rejection = {
                        "symbol": decision.symbol,
                        "market": "futures",
                        "reason": "BITGET_MAX_OPEN_ZERO",
                        "message": "Bitget preflight rejected order because max openable quantity is 0.",
                    }
                    return None
                quantity = min(quantity, max_open)
        if self._exchange_id() == "bitget":
            quantity = self.normalize_quantity(market=market, symbol=execution_symbol, quantity=quantity)
            min_quantity = self._bitget_min_quantity(market=market, symbol=execution_symbol)
            if quantity <= 0.0 or (min_quantity > 0.0 and quantity < min_quantity):
                reason = "BITGET_MAX_OPEN_BELOW_MIN_QTY" if market == "futures" else "BITGET_MIN_QTY"
                self._last_preflight_rejection = {
                    "symbol": decision.symbol,
                    "market": market,
                    "reason": reason,
                    "message": f"Bitget preflight rejected order because normalized quantity {quantity:.8f} is below minimum {min_quantity:.8f} for {execution_symbol}.",
                }
                return None
            params = {
                "symbol": execution_symbol,
                "side": side.lower(),
                "orderType": "market",
                "clientOid": decision.decision_id,
            }
            if market == "spot" and side == "BUY" and self._uses_spot_quote_notional(decision):
                params["size"] = f"{decision.order_intent_notional_usd:.2f}"
            else:
                params["size"] = f"{quantity:.8f}"
            if market == "futures":
                params["productType"] = "USDT-FUTURES"
                params["marginCoin"] = "USDT"
                params["marginMode"] = "crossed"
                params["tradeSide"] = "close" if decision.side == "flat" else "open"
                if decision.side in {"long", "short"}:
                    take_profit, stop_loss = self._protection_prices(
                        decision=decision,
                        reference_price=reference_price,
                    )
                    params["presetStopSurplusPrice"] = self.format_trigger_price(
                        value=take_profit,
                        market="futures",
                        symbol=decision.symbol,
                    )
                    params["presetStopLossPrice"] = self.format_trigger_price(
                        value=stop_loss,
                        market="futures",
                        symbol=decision.symbol,
                    )
            return market, params
        params = {
            "symbol": self._execution_symbol(decision),
            "side": side,
            "type": "MARKET",
            "newOrderRespType": "RESULT",
        }
        if market == "spot" and side == "BUY" and self._uses_spot_quote_notional(decision):
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
            if self._exchange_id() != "bitget" or market != "futures" or not self._is_bitget_unilateral_error(str(exc)):
                raise
            retry_error = exc
            for alternate_params in self._bitget_alternate_futures_params(order_params):
                try:
                    response = self.client.place_order(market=market, order_params=alternate_params)
                except Exception as retry_exc:
                    retry_error = retry_exc
                    if not self._is_bitget_unilateral_error(str(retry_exc)):
                        raise
                    continue
                order_params = alternate_params
                break
            else:
                raise retry_error
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
