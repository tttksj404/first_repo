from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from quant_binance.data.futures_stream import (
    parse_futures_book_ticker_event,
    parse_futures_kline_event,
    parse_futures_trade_event,
    parse_mark_price_event,
    parse_open_interest_event,
)
from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.spot_stream import parse_book_ticker_event, parse_kline_event, parse_spot_trade_event
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.models import DecisionIntent
from quant_binance.risk.kill_switch import KillSwitch
from quant_binance.service import PaperTradingService


PrimitiveBuilder = Callable[[str, datetime], PrimitiveInputs]
HistoryProvider = Callable[[str, datetime], FeatureHistoryContext]


class EventDispatcher:
    def __init__(self, store: MarketStateStore) -> None:
        self.store = store

    def dispatch(self, payload: dict[str, Any]) -> str | None:
        stream = payload.get("stream", "")
        data = payload.get("data", payload)
        if stream.endswith("@trade"):
            if "ps" in data:
                trade = parse_futures_trade_event(data)
            else:
                trade = parse_spot_trade_event(data)
            self.store.apply_trade(trade)
            return trade.symbol
        if stream.endswith("@bookTicker"):
            symbol = data["s"]
            if "ps" in data:
                top = parse_futures_book_ticker_event(data)
            else:
                top = parse_book_ticker_event(data)
            self.store.apply_top_of_book(symbol, top)
            return symbol
        if "@kline_" in stream:
            if "ps" in data:
                bar = parse_futures_kline_event(data)
            else:
                bar = parse_kline_event(data)
            self.store.apply_kline(bar)
            return bar.symbol
        if stream.endswith("@markPrice"):
            parsed = parse_mark_price_event(data)
            self.store.apply_mark_price(
                symbol=str(parsed["symbol"]),
                funding_rate=float(parsed["funding_rate"]),
                mark_price=float(parsed["mark_price"]),
                index_price=float(parsed["index_price"]),
                event_time=parsed["event_time"],  # type: ignore[arg-type]
            )
            return str(parsed["symbol"])
        if stream.endswith("@openInterest"):
            parsed = parse_open_interest_event(data)
            self.store.apply_open_interest(
                symbol=str(parsed["symbol"]),
                open_interest=float(parsed["open_interest"]),
                event_time=parsed["event_time"],  # type: ignore[arg-type]
            )
            return str(parsed["symbol"])
        return None


class LivePaperRuntime:
    def __init__(
        self,
        *,
        dispatcher: EventDispatcher,
        paper_service: PaperTradingService,
        primitive_builder: PrimitiveBuilder,
        history_provider: HistoryProvider,
        decision_interval_minutes: int,
        kill_switch: KillSwitch | None = None,
        eligible_symbols: set[str] | None = None,
    ) -> None:
        self.dispatcher = dispatcher
        self.paper_service = paper_service
        self.primitive_builder = primitive_builder
        self.history_provider = history_provider
        self.decision_interval_minutes = decision_interval_minutes
        self.kill_switch = kill_switch or KillSwitch()
        self.eligible_symbols = eligible_symbols

    def on_payload(
        self,
        payload: dict[str, Any],
        *,
        equity_usd: float,
        remaining_portfolio_capacity_usd: float,
    ) -> DecisionIntent | None:
        if self.kill_switch.armed:
            return None
        symbol = self.dispatcher.dispatch(payload)
        if symbol is None:
            return None
        stream = payload.get("stream", "")
        if "@kline_" not in stream:
            return None
        data = payload.get("data", payload)
        kline = data["k"]
        if not bool(kline["x"]):
            return None
        decision_time = datetime.fromtimestamp(kline["T"] / 1000, tz=timezone.utc)
        if decision_time.minute % self.decision_interval_minutes != 0:
            return None
        state = self.dispatcher.store.get(symbol)
        if state is None:
            return None
        if self.eligible_symbols is not None and symbol not in self.eligible_symbols:
            return None
        stale_ms = state.freshness_ms(decision_time)
        if stale_ms > self.paper_service.settings.operational_limits.stale_data_alarm_sla_seconds * 1000:
            self.kill_switch.arm("STALE_DATA")
            return None
        primitive_inputs = self.primitive_builder(symbol, decision_time)
        history = self.history_provider(symbol, decision_time)
        return self.paper_service.run_cycle(
            state=state,
            primitive_inputs=primitive_inputs,
            history=history,
            decision_time=decision_time,
            equity_usd=equity_usd,
            remaining_portfolio_capacity_usd=remaining_portfolio_capacity_usd,
        )
