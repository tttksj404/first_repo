from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any


class BitgetPollingWebSocketClient:
    """REST-polling event source that emits Binance-shaped closed kline payloads."""

    def __init__(
        self,
        *,
        rest_client: Any,
        symbols: tuple[str, ...],
        decision_interval_minutes: int,
        poll_interval_seconds: float = 2.0,
        symbol_poll_interval_seconds: float | None = None,
        rate_limit_backoff_initial_seconds: float = 5.0,
        rate_limit_backoff_max_seconds: float = 60.0,
    ) -> None:
        self.rest_client = rest_client
        self.symbols = symbols
        self.decision_interval_minutes = decision_interval_minutes
        self.poll_interval_seconds = poll_interval_seconds
        base_symbol_interval = max(self.poll_interval_seconds * max(len(self.symbols), 1), 20.0)
        self.symbol_poll_interval_seconds = (
            base_symbol_interval
            if symbol_poll_interval_seconds is None
            else max(float(symbol_poll_interval_seconds), self.poll_interval_seconds)
        )
        self.rate_limit_backoff_initial_seconds = max(rate_limit_backoff_initial_seconds, 1.0)
        self.rate_limit_backoff_max_seconds = max(rate_limit_backoff_max_seconds, self.rate_limit_backoff_initial_seconds)
        self._last_emitted_close_ms: dict[str, int] = {}
        self._last_polled_at: dict[str, datetime] = {}
        self._rate_limit_backoff_until: datetime | None = None
        self._next_rate_limit_backoff_seconds = self.rate_limit_backoff_initial_seconds

    @property
    def interval_label(self) -> str:
        return f"{self.decision_interval_minutes}m"

    def _interval_ms(self) -> int:
        return self.decision_interval_minutes * 60 * 1000

    def _to_payload(self, *, symbol: str, candle: dict[str, Any]) -> dict[str, Any]:
        open_time_ms = int(candle["open_time"])
        close_time_ms = open_time_ms + self._interval_ms() - 1
        return {
            "stream": f"{symbol.lower()}@kline_{self.interval_label}",
            "data": {
                "s": symbol,
                "ps": symbol,
                "k": {
                    "i": self.interval_label,
                    "t": open_time_ms,
                    "T": close_time_ms,
                    "o": str(candle["open_price"]),
                    "h": str(candle["high_price"]),
                    "l": str(candle["low_price"]),
                    "c": str(candle["close_price"]),
                    "v": str(candle["base_volume"]),
                    "q": str(candle["quote_volume"]),
                    "x": True,
                    "s": symbol,
                },
            },
        }

    def _can_poll_symbol(self, *, symbol: str, now: datetime) -> bool:
        if self._rate_limit_backoff_until is not None and now < self._rate_limit_backoff_until:
            return False
        last_polled = self._last_polled_at.get(symbol)
        if last_polled is None:
            return True
        return (now - last_polled).total_seconds() >= self.symbol_poll_interval_seconds

    def _record_symbol_polled(self, *, symbol: str, now: datetime) -> None:
        self._last_polled_at[symbol] = now

    def _record_rate_limit(self, *, now: datetime, error: Exception) -> bool:
        if "code=429" not in str(error):
            return False
        backoff_seconds = self._next_rate_limit_backoff_seconds
        self._rate_limit_backoff_until = now + timedelta(seconds=backoff_seconds)
        self._next_rate_limit_backoff_seconds = min(
            self._next_rate_limit_backoff_seconds * 2.0,
            self.rate_limit_backoff_max_seconds,
        )
        print(
            f"[RATE_LIMIT] bitget_candles cooldown={backoff_seconds:.1f}s error={error}",
            flush=True,
        )
        return True

    def _record_success(self) -> None:
        if self._rate_limit_backoff_until is not None:
            self._rate_limit_backoff_until = None
        self._next_rate_limit_backoff_seconds = self.rate_limit_backoff_initial_seconds

    def _select_latest_closed_candle(
        self,
        *,
        candles: list[dict[str, Any]],
        now_ms: int,
    ) -> tuple[dict[str, Any], int] | None:
        if not candles:
            return None
        ordered = sorted(candles, key=lambda item: int(item.get("open_time", 0)))
        for candle in reversed(ordered):
            close_time_ms = int(candle["open_time"]) + self._interval_ms() - 1
            if close_time_ms < now_ms:
                return candle, close_time_ms
        return None

    async def run(self, handler) -> None:  # type: ignore[no-untyped-def]
        while True:
            now = datetime.now(tz=timezone.utc)
            now_ms = int(now.timestamp() * 1000)
            if self._rate_limit_backoff_until is not None and now < self._rate_limit_backoff_until:
                remaining = (self._rate_limit_backoff_until - now).total_seconds()
                await asyncio.sleep(min(self.poll_interval_seconds, max(remaining, 0.1)))
                continue
            for symbol in self.symbols:
                poll_time = datetime.now(tz=timezone.utc)
                if not self._can_poll_symbol(symbol=symbol, now=poll_time):
                    continue
                self._record_symbol_polled(symbol=symbol, now=poll_time)
                try:
                    candles = self.rest_client.get_klines(
                        market="futures",
                        symbol=symbol,
                        interval=self.interval_label,
                        limit=2,
                    )
                except Exception as exc:
                    if self._record_rate_limit(now=poll_time, error=exc):
                        break
                    print(f"[POLL_ERROR] symbol={symbol} error={exc}", flush=True)
                    continue
                if not isinstance(candles, list) or not candles:
                    continue
                self._record_success()
                closed = self._select_latest_closed_candle(candles=candles, now_ms=now_ms)
                if closed is None:
                    continue
                latest, close_time_ms = closed
                prev_close = self._last_emitted_close_ms.get(symbol)
                if prev_close is None:
                    self._last_emitted_close_ms[symbol] = close_time_ms
                    continue
                if close_time_ms <= prev_close:
                    continue
                await handler(self._to_payload(symbol=symbol, candle=latest))
                self._last_emitted_close_ms[symbol] = close_time_ms
            await asyncio.sleep(self.poll_interval_seconds)
