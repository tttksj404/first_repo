"""
B3 Market Structure Breakout (MSB) Strategy
============================================
1h 봉 기준으로 스윙 고점/저점 돌파 시 진입.

설정 (strategy_override.approved.json "b3_msb_strategy" 섹션):
- swing_window: 15 (스윙 고점/저점 계산 윈도우)
- atr_tp_multiple: 4.0 (TP = 진입가 ± ATR × 4.0)
- breakout_confirmation_pct: 0.001 (돌파 확인 버퍼 0.1%)
- trend_filter: "adx20" (ADX(14) >= 20 이상일 때만 진입)
- symbols: 허용 심볼 목록

SL: 돌파 방향 반대의 직전 스윙 저점/고점
TP: 진입가 ± ATR × atr_tp_multiple
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant_binance.data.state import KlineBar, SymbolMarketState

# 동일 심볼 재진입 쿨다운 (4시간)
_ENTRY_COOLDOWN_SECONDS: float = 4 * 3600.0


@dataclass
class MsbConfig:
    enabled: bool = False
    swing_window: int = 15
    atr_tp_multiple: float = 4.0
    breakout_confirmation_pct: float = 0.001
    trend_filter: str = "adx20"           # "adx20" | "none"
    adx_min: float = 20.0
    symbols: list[str] = field(default_factory=list)
    notional_usd_per_trade: float = 50.0
    interval: str = "1h"


@dataclass
class MsbSignal:
    symbol: str
    side: str                   # "long" | "short"
    entry_price: float
    stop_price: float
    tp_price: float
    atr: float
    swing_level: float          # 돌파된 스윙 레벨
    adx: float
    signal_time: datetime


@dataclass
class MsbPosition:
    symbol: str
    side: str
    entry_price: float
    stop_price: float
    tp_price: float
    atr: float
    notional_usd: float
    entry_time: datetime
    max_hold_until: datetime    # 최대 48시간 보유
    # 청산 필드
    pnl_usd: float = 0.0
    exit_reason: str = ""
    exit_price: float = 0.0
    exit_time: datetime | None = None


# ---------------------------------------------------------------------------
# 지표 계산 유틸
# ---------------------------------------------------------------------------

def _atr(bars: list[KlineBar], period: int = 14) -> float:
    """ATR(period) 계산."""
    if len(bars) < 2:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(bars)):
        b = bars[i]
        prev_close = bars[i - 1].close_price
        trs.append(max(
            b.high_price - b.low_price,
            abs(b.high_price - prev_close),
            abs(b.low_price - prev_close),
        ))
    return mean(trs[-period:]) if trs else 0.0


def _adx(bars: list[KlineBar], period: int = 14) -> float:
    """ADX(period) 계산. bars는 시간순(오름차순)."""
    if len(bars) < period + 2:
        return 0.0

    plus_dms: list[float] = []
    minus_dms: list[float] = []
    trs: list[float] = []

    for i in range(1, len(bars)):
        b = bars[i]
        prev = bars[i - 1]
        high_diff = b.high_price - prev.high_price
        low_diff = prev.low_price - b.low_price
        plus_dm = max(high_diff, 0.0) if high_diff > low_diff else 0.0
        minus_dm = max(low_diff, 0.0) if low_diff > high_diff else 0.0
        plus_dms.append(plus_dm)
        minus_dms.append(minus_dm)
        tr = max(
            b.high_price - b.low_price,
            abs(b.high_price - prev.close_price),
            abs(b.low_price - prev.close_price),
        )
        trs.append(tr)

    if len(trs) < period:
        return 0.0

    # Wilder smoothing (초기값: 단순합)
    def _wilder(values: list[float], p: int) -> list[float]:
        out = [sum(values[:p])]
        for v in values[p:]:
            out.append(out[-1] - out[-1] / p + v)
        return out

    sm_tr = _wilder(trs, period)
    sm_plus = _wilder(plus_dms, period)
    sm_minus = _wilder(minus_dms, period)

    dx_list: list[float] = []
    for tr_s, p_s, m_s in zip(sm_tr, sm_plus, sm_minus):
        if tr_s < 1e-12:
            continue
        plus_di = 100.0 * p_s / tr_s
        minus_di = 100.0 * m_s / tr_s
        di_sum = plus_di + minus_di
        if di_sum < 1e-12:
            dx_list.append(0.0)
        else:
            dx_list.append(100.0 * abs(plus_di - minus_di) / di_sum)

    if not dx_list:
        return 0.0
    tail = dx_list[-period:]
    return mean(tail)


def _swing_highs_lows(
    bars: list[KlineBar],
    window: int,
) -> tuple[float, float]:
    """
    최근 window 개 봉의 스윙 고점/저점 반환.
    마지막 봉(현재 봉)은 제외하고 계산.
    Returns (swing_high, swing_low)
    """
    if len(bars) < window + 1:
        return 0.0, float("inf")
    lookback = bars[-(window + 1):-1]  # 현재 봉 제외
    highs = [b.high_price for b in lookback]
    lows = [b.low_price for b in lookback]
    return max(highs), min(lows)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_msb_config(override: dict) -> MsbConfig:
    raw = dict(override.get("b3_msb_strategy") or {})
    if not raw:
        return MsbConfig(enabled=False)
    return MsbConfig(
        enabled=bool(raw.get("enabled", False)),
        swing_window=int(raw.get("swing_window", 15)),
        atr_tp_multiple=float(raw.get("atr_tp_multiple", 4.0)),
        breakout_confirmation_pct=float(raw.get("breakout_confirmation_pct", 0.001)),
        trend_filter=str(raw.get("trend_filter", "adx20")),
        adx_min=float(raw.get("adx_min", 20.0)),
        symbols=list(raw.get("symbols") or []),
        notional_usd_per_trade=float(raw.get("notional_usd_per_trade", 50.0)),
        interval=str(raw.get("interval", "1h")),
    )


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class MsbTracker:
    """B3 MSB 전략 포지션 라이프사이클 관리."""

    def __init__(self, config: MsbConfig) -> None:
        self.config = config
        self._last_entry_by_symbol: dict[str, datetime] = {}
        self.open_positions: dict[str, MsbPosition] = {}
        self.closed_trades: list[dict[str, object]] = []

    def generate_signals(
        self,
        states: dict[str, SymbolMarketState],
        now: datetime,
    ) -> list[MsbSignal]:
        if not self.config.enabled:
            return []

        signals: list[MsbSignal] = []
        for symbol in self.config.symbols:
            state = states.get(symbol)
            if state is None:
                continue
            if symbol in self.open_positions:
                continue

            # 쿨다운 체크
            last_entry = self._last_entry_by_symbol.get(symbol)
            if last_entry is not None:
                if (now - last_entry).total_seconds() < _ENTRY_COOLDOWN_SECONDS:
                    continue

            bars = list(state.klines.get(self.config.interval) or [])
            if len(bars) < self.config.swing_window + 2:
                continue

            atr = _atr(bars)
            if atr <= 0:
                continue

            # ADX 필터
            adx = 0.0
            if self.config.trend_filter == "adx20":
                adx = _adx(bars)
                if adx < self.config.adx_min:
                    continue

            swing_high, swing_low = _swing_highs_lows(bars, self.config.swing_window)
            if swing_high <= 0 or swing_low >= float("inf"):
                continue

            price = state.last_trade_price
            if price <= 0:
                continue

            buf = self.config.breakout_confirmation_pct
            signal: MsbSignal | None = None

            # 롱: 스윙 고점 상향 돌파
            if price > swing_high * (1.0 + buf):
                sl = swing_low
                tp = price + atr * self.config.atr_tp_multiple
                signal = MsbSignal(
                    symbol=symbol,
                    side="long",
                    entry_price=price,
                    stop_price=sl,
                    tp_price=tp,
                    atr=atr,
                    swing_level=swing_high,
                    adx=adx,
                    signal_time=now,
                )

            # 숏: 스윙 저점 하향 돌파
            elif price < swing_low * (1.0 - buf):
                sl = swing_high
                tp = price - atr * self.config.atr_tp_multiple
                signal = MsbSignal(
                    symbol=symbol,
                    side="short",
                    entry_price=price,
                    stop_price=sl,
                    tp_price=tp,
                    atr=atr,
                    swing_level=swing_low,
                    adx=adx,
                    signal_time=now,
                )

            if signal is not None:
                signals.append(signal)

        return signals

    def open_position(self, signal: MsbSignal) -> MsbPosition:
        pos = MsbPosition(
            symbol=signal.symbol,
            side=signal.side,
            entry_price=signal.entry_price,
            stop_price=signal.stop_price,
            tp_price=signal.tp_price,
            atr=signal.atr,
            notional_usd=self.config.notional_usd_per_trade,
            entry_time=signal.signal_time,
            max_hold_until=signal.signal_time + timedelta(hours=48),
        )
        self.open_positions[signal.symbol] = pos
        self._last_entry_by_symbol[signal.symbol] = signal.signal_time
        return pos

    def evaluate_exits(
        self,
        states: dict[str, SymbolMarketState],
        now: datetime,
    ) -> list[tuple[str, str, float]]:
        exits: list[tuple[str, str, float]] = []
        for symbol, pos in list(self.open_positions.items()):
            state = states.get(symbol)
            if state is None:
                exits.append((symbol, "no_state", pos.entry_price))
                continue
            price = state.last_trade_price
            if price <= 0:
                continue
            if now >= pos.max_hold_until:
                exits.append((symbol, "max_hold", price))
            elif pos.side == "long":
                if price <= pos.stop_price:
                    exits.append((symbol, "stop_loss", price))
                elif price >= pos.tp_price:
                    exits.append((symbol, "take_profit", price))
            else:
                if price >= pos.stop_price:
                    exits.append((symbol, "stop_loss", price))
                elif price <= pos.tp_price:
                    exits.append((symbol, "take_profit", price))
        return exits

    def close_position(
        self,
        symbol: str,
        exit_reason: str,
        exit_price: float,
        exit_time: datetime,
    ) -> MsbPosition | None:
        pos = self.open_positions.pop(symbol, None)
        if pos is None:
            return None
        direction = 1 if pos.side == "long" else -1
        pnl_usd = (
            (exit_price - pos.entry_price)
            / max(pos.entry_price, 1e-12)
            * direction
            * pos.notional_usd
        )
        pos.pnl_usd = round(pnl_usd, 6)
        pos.exit_reason = exit_reason
        pos.exit_price = exit_price
        pos.exit_time = exit_time
        self.closed_trades.append({
            "symbol": symbol,
            "side": pos.side,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "pnl_usd": pos.pnl_usd,
            "notional_usd": pos.notional_usd,
            "entry_time": pos.entry_time.isoformat(),
            "exit_time": exit_time.isoformat(),
            "atr": pos.atr,
            "stop_price": pos.stop_price,
            "tp_price": pos.tp_price,
        })
        return pos

    def summary(self) -> dict[str, object]:
        total_pnl = sum(float(t.get("pnl_usd", 0)) for t in self.closed_trades)
        wins = sum(1 for t in self.closed_trades if float(t.get("pnl_usd", 0)) > 0)
        total = len(self.closed_trades)
        return {
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total, 4) if total else 0.0,
            "total_pnl_usd": round(total_pnl, 4),
            "open_positions": list(self.open_positions.keys()),
        }
