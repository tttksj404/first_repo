from __future__ import annotations

import asyncio
from datetime import datetime, timezone
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
    ) -> None:
        self.rest_client = rest_client
        self.symbols = symbols
        self.decision_interval_minutes = decision_interval_minutes
        self.poll_interval_seconds = poll_interval_seconds
        self._last_emitted_close_ms: dict[str, int] = {}

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

    async def run(self, handler) -> None:  # type: ignore[no-untyped-def]
        while True:
            now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
            for symbol in self.symbols:
                candles = self.rest_client.get_klines(
                    market="futures",
                    symbol=symbol,
                    interval=self.interval_label,
                    limit=2,
                )
                if not isinstance(candles, list) or not candles:
                    continue
                ordered = sorted(candles, key=lambda item: int(item.get("open_time", 0)))
                latest = ordered[-1]
                close_time_ms = int(latest["open_time"]) + self._interval_ms() - 1
                if close_time_ms >= now_ms:
                    continue
                prev_close = self._last_emitted_close_ms.get(symbol)
                if prev_close is None:
                    self._last_emitted_close_ms[symbol] = close_time_ms
                    continue
                if close_time_ms <= prev_close:
                    continue
                await handler(self._to_payload(symbol=symbol, candle=latest))
                self._last_emitted_close_ms[symbol] = close_time_ms
            await asyncio.sleep(self.poll_interval_seconds)
