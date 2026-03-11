from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
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


@dataclass
class LiveDecisionLoopStats:
    closed_decision_kline_count: int = 0
    emitted_decision_count: int = 0
    dropped_closed_decision_kline_reasons: dict[str, int] = field(default_factory=dict)
    last_closed_decision_kline_symbol: str | None = None
    last_closed_decision_time: datetime | None = None
    last_emitted_symbol: str | None = None
    last_emitted_decision_time: datetime | None = None
    last_drop_symbol: str | None = None
    last_drop_decision_time: datetime | None = None
    last_drop_reason: str | None = None

    def note_closed_kline(self, *, symbol: str, decision_time: datetime) -> None:
        self.closed_decision_kline_count += 1
        self.last_closed_decision_kline_symbol = symbol
        self.last_closed_decision_time = decision_time

    def note_emitted_decision(self, *, symbol: str, decision_time: datetime) -> None:
        self.emitted_decision_count += 1
        self.last_emitted_symbol = symbol
        self.last_emitted_decision_time = decision_time

    def note_drop(self, *, reason: str, symbol: str, decision_time: datetime) -> None:
        self.dropped_closed_decision_kline_reasons[reason] = (
            self.dropped_closed_decision_kline_reasons.get(reason, 0) + 1
        )
        self.last_drop_symbol = symbol
        self.last_drop_decision_time = decision_time
        self.last_drop_reason = reason

    def as_dict(self) -> dict[str, Any]:
        return {
            "closed_decision_kline_count": self.closed_decision_kline_count,
            "emitted_decision_count": self.emitted_decision_count,
            "dropped_closed_decision_kline_reasons": dict(self.dropped_closed_decision_kline_reasons),
            "last_closed_decision_kline_symbol": self.last_closed_decision_kline_symbol,
            "last_closed_decision_time": self.last_closed_decision_time,
            "last_emitted_symbol": self.last_emitted_symbol,
            "last_emitted_decision_time": self.last_emitted_decision_time,
            "last_drop_symbol": self.last_drop_symbol,
            "last_drop_decision_time": self.last_drop_decision_time,
            "last_drop_reason": self.last_drop_reason,
        }


def _binance_interval_label(interval_minutes: int) -> str:
    if interval_minutes % (24 * 60) == 0:
        return f"{interval_minutes // (24 * 60)}d"
    if interval_minutes % 60 == 0:
        return f"{interval_minutes // 60}h"
    return f"{interval_minutes}m"


def _closed_kline_decision_time(kline: dict[str, Any]) -> datetime:
    close_time = datetime.fromtimestamp(int(kline["T"]) / 1000, tz=timezone.utc)
    if close_time.second == 0 and close_time.microsecond == 0:
        return close_time
    # Binance live kline close timestamps are the final millisecond inside the bar.
    return datetime.fromtimestamp((int(kline["T"]) + 1) / 1000, tz=timezone.utc)


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
        self.decision_interval_stream = _binance_interval_label(decision_interval_minutes)
        self.kill_switch = kill_switch or KillSwitch()
        self.eligible_symbols = eligible_symbols
        self.loop_stats = LiveDecisionLoopStats()

    def on_payload(
        self,
        payload: dict[str, Any],
        *,
        equity_usd: float,
        remaining_portfolio_capacity_usd: float,
    ) -> DecisionIntent | None:
        stream = payload.get("stream", "")
        data = payload.get("data", payload)
        kline = data.get("k") if isinstance(data, dict) else None
        is_closed_decision_kline = (
            "@kline_" in stream
            and isinstance(kline, dict)
            and bool(kline.get("x"))
            and str(kline.get("i", "")) == self.decision_interval_stream
        )
        if self.kill_switch.armed:
            if is_closed_decision_kline:
                symbol = str(kline.get("s") or data.get("s") or "")
                decision_time = _closed_kline_decision_time(kline)
                self.loop_stats.note_closed_kline(symbol=symbol, decision_time=decision_time)
                self.loop_stats.note_drop(
                    reason="KILL_SWITCH_ARMED",
                    symbol=symbol,
                    decision_time=decision_time,
                )
            return None
        symbol = self.dispatcher.dispatch(payload)
        if symbol is None:
            return None
        if "@kline_" not in stream:
            return None
        if not isinstance(data, dict) or not isinstance(kline, dict):
            return None
        if not bool(kline["x"]):
            return None
        if str(kline.get("i", "")) != self.decision_interval_stream:
            return None
        decision_time = _closed_kline_decision_time(kline)
        self.loop_stats.note_closed_kline(symbol=symbol, decision_time=decision_time)
        if int(decision_time.timestamp() // 60) % self.decision_interval_minutes != 0:
            self.loop_stats.note_drop(
                reason="MISALIGNED_CLOSE_TIME",
                symbol=symbol,
                decision_time=decision_time,
            )
            return None
        state = self.dispatcher.store.get(symbol)
        if state is None:
            self.loop_stats.note_drop(
                reason="MISSING_STATE",
                symbol=symbol,
                decision_time=decision_time,
            )
            return None
        if self.eligible_symbols is not None and symbol not in self.eligible_symbols:
            self.loop_stats.note_drop(
                reason="INELIGIBLE_SYMBOL",
                symbol=symbol,
                decision_time=decision_time,
            )
            return None
        stale_ms = state.freshness_ms(decision_time)
        if stale_ms > self.paper_service.settings.operational_limits.stale_data_alarm_sla_seconds * 1000:
            self.kill_switch.arm("STALE_DATA")
            self.loop_stats.note_drop(
                reason="STALE_DATA",
                symbol=symbol,
                decision_time=decision_time,
            )
            return None
        primitive_inputs = self.primitive_builder(symbol, decision_time)
        history = self.history_provider(symbol, decision_time)
        decision = self.paper_service.run_cycle(
            state=state,
            primitive_inputs=primitive_inputs,
            history=history,
            decision_time=decision_time,
            equity_usd=equity_usd,
            remaining_portfolio_capacity_usd=remaining_portfolio_capacity_usd,
        )
        self.loop_stats.note_emitted_decision(symbol=symbol, decision_time=decision_time)
        return decision
