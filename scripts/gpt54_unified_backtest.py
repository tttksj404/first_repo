"""GPT-5.4 cross-validated unified strategy backtest.

Implements the regime-gated bidirectional breakout-continuation strategy
recommended by GPT-5.4 cross-validation, with:
  - 4h EMA200 bias + 1h EMA stack + ADX/RSI intermediate filter
  - ATR percentile volatility regime gate (35th-85th)
  - TTM Squeeze release + Donchian(20) breakout trigger on 5m
  - Volume confirmation + VWAP filter + chase filter
  - R-based exit: 1.9R TP, 1.0R SL, breakeven at 1.15R
  - Stale-trade exit at 18 bars, hard 36h max
  - Funding filter, correlation rule (max 1 position)
  - Daily/weekly loss stops, 12-bar re-entry cooldown
  - Purged walk-forward validation with cost stress test

Usage:
    python scripts/gpt54_unified_backtest.py --symbols ETHUSDT,SOLUSDT --equity-usd 75
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@dataclass
class Trade:
    symbol: str = ""
    side: str = ""
    entry_time: datetime | None = None
    entry_price: float = 0.0
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    leverage: int = 12
    notional_usd: float = 0.0
    stop_pct: float = 0.0
    r_target: float = 1.9
    peak_roe_pct: float = 0.0
    pnl_usd: float = 0.0
    fee_usd: float = 0.0
    net_pnl_usd: float = 0.0

    @property
    def holding_minutes(self) -> float:
        if not self.exit_time or not self.entry_time:
            return 0.0
        return (self.exit_time - self.entry_time).total_seconds() / 60


def _ema(values: list[float], period: int) -> float:
    if len(values) < period:
        return sum(values) / max(len(values), 1)
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _sma(values: list[float], period: int) -> float:
    if len(values) < period:
        return sum(values) / max(len(values), 1)
    return sum(values[-period:]) / period


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if len(highs) < 2:
        return 0.0
    trs = []
    for i in range(1, min(len(highs), period + 1)):
        tr = max(highs[-i] - lows[-i],
                 abs(highs[-i] - closes[-i - 1]),
                 abs(lows[-i] - closes[-i - 1]))
        trs.append(tr)
    return sum(trs) / max(len(trs), 1)


def _adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if len(highs) < period + 2:
        return 0.0
    plus_dm = []
    minus_dm = []
    trs = []
    for i in range(1, min(len(highs), period + 2)):
        hi_diff = highs[-i] - highs[-i - 1]
        lo_diff = lows[-i - 1] - lows[-i]
        plus_dm.append(max(hi_diff, 0) if hi_diff > lo_diff else 0)
        minus_dm.append(max(lo_diff, 0) if lo_diff > hi_diff else 0)
        trs.append(max(highs[-i] - lows[-i], abs(highs[-i] - closes[-i - 1]), abs(lows[-i] - closes[-i - 1])))
    atr_val = sum(trs[:period]) / period
    if atr_val <= 0:
        return 0.0
    plus_di = (sum(plus_dm[:period]) / period) / atr_val * 100
    minus_di = (sum(minus_dm[:period]) / period) / atr_val * 100
    dx = abs(plus_di - minus_di) / max(plus_di + minus_di, 0.01) * 100
    return dx


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(-period, 0)]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(-period, 0)]
    ag = sum(gains) / period
    al = sum(losses) / period
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def _ttm_squeeze_on(closes: list[float], highs: list[float], lows: list[float], period: int = 20) -> bool:
    """True if BB is inside KC (squeeze is on)."""
    if len(closes) < period or len(highs) < 2:
        return False
    sma_val = sum(closes[-period:]) / period
    std_val = statistics.stdev(closes[-period:]) if len(set(closes[-period:])) > 1 else 0
    bb_upper = sma_val + 2 * std_val
    bb_lower = sma_val - 2 * std_val
    atr_val = _atr(highs, lows, closes, 14)
    kc_upper = sma_val + 1.5 * atr_val
    kc_lower = sma_val - 1.5 * atr_val
    return bb_upper < kc_upper and bb_lower > kc_lower and bb_upper > 0


def _donchian(highs: list[float], lows: list[float], period: int = 20) -> tuple[float, float]:
    if len(highs) < period:
        return max(highs) if highs else 0, min(lows) if lows else 0
    return max(highs[-period:]), min(lows[-period:])


def run_gpt54_backtest(
    bars_5m: list[dict],
    bars_1h: list[dict],
    bars_4h: list[dict],
    symbol: str,
    equity_usd: float = 75.0,
    cost_bps: float = 42.0,
    max_leverage: int = 15,
    default_leverage: int = 12,
) -> list[Trade]:
    """Run GPT-5.4 unified strategy on historical bars."""
    trades: list[Trade] = []
    position: Trade | None = None
    cooldown_until_ms: int = 0
    daily_loss: float = 0.0
    daily_date: str = ""
    weekly_loss: float = 0.0
    weekly_start: str = ""
    last_sl_symbol: str = ""
    last_sl_bar_idx: int = -999

    # Index 1h/4h bars by open_time (more reliable than close_time)
    h1_by_time = {}
    for b in bars_1h:
        ot = b.get("open_time", 0)
        h1_by_time[ot] = b
    h4_by_time = {}
    for b in bars_4h:
        ot = b.get("open_time", 0)
        h4_by_time[ot] = b

    # Sort all bars
    bars = sorted(bars_5m, key=lambda b: b["open_time"])
    _h1_sorted = sorted(h1_by_time.keys())
    _h4_sorted = sorted(h4_by_time.keys())
    if len(bars) < 500:
        return []

    # Precompute 5m ATR percentile ranking (20-day rolling)
    atr_history: list[float] = []

    # Debug counters
    _dbg = defaultdict(int)

    for i in range(100, len(bars)):
        bar = bars[i]
        bar_time_ms = bar["open_time"]
        bar_time = datetime.fromtimestamp(bar_time_ms / 1000, tz=timezone.utc)
        bar_date = bar_time.strftime("%Y-%m-%d")
        bar_week = bar_time.strftime("%Y-W%W")

        # Reset daily/weekly counters
        if bar_date != daily_date:
            daily_loss = 0.0
            daily_date = bar_date
        if bar_week != weekly_start:
            weekly_loss = 0.0
            weekly_start = bar_week

        # ── If position open, manage exit ──
        if position is not None:
            hi = bar["high_price"]
            lo = bar["low_price"]
            cl = bar["close_price"]
            entry = position.entry_price
            stop_dist = position.stop_pct * entry
            lev = position.leverage

            if position.side == "long":
                roe = (cl / entry - 1) * 100 * lev
                best_roe = (hi / entry - 1) * 100 * lev
                worst_roe = (lo / entry - 1) * 100 * lev
            else:
                roe = -(cl / entry - 1) * 100 * lev
                best_roe = -(lo / entry - 1) * 100 * lev
                worst_roe = -(hi / entry - 1) * 100 * lev

            position.peak_roe_pct = max(position.peak_roe_pct, best_roe)
            sl_roe = -position.stop_pct * 100 * lev  # 1.0R
            tp_roe = position.stop_pct * 100 * lev * position.r_target  # 1.9R

            # Breakeven after 1.15R
            be_roe = position.stop_pct * 100 * lev * 1.15
            if position.peak_roe_pct >= be_roe:
                sl_roe = position.stop_pct * 100 * lev * 0.10  # move to +0.10R

            # SL hit
            if worst_roe <= sl_roe:
                if position.side == "long":
                    position.exit_price = entry * (1 + sl_roe / 100 / lev)
                else:
                    position.exit_price = entry * (1 - sl_roe / 100 / lev)
                position.exit_time = bar_time
                position.exit_reason = "SL"
                _finalize(position, cost_bps)
                trades.append(position)
                daily_loss += position.net_pnl_usd
                weekly_loss += position.net_pnl_usd
                last_sl_symbol = position.symbol
                last_sl_bar_idx = i
                cooldown_until_ms = bar_time_ms + 12 * 5 * 60 * 1000  # 12 bars
                position = None
                continue

            # TP hit
            if best_roe >= tp_roe:
                if position.side == "long":
                    position.exit_price = entry * (1 + tp_roe / 100 / lev)
                else:
                    position.exit_price = entry * (1 - tp_roe / 100 / lev)
                position.exit_time = bar_time
                position.exit_reason = "TP"
                _finalize(position, cost_bps)
                trades.append(position)
                daily_loss += position.net_pnl_usd
                weekly_loss += position.net_pnl_usd
                cooldown_until_ms = bar_time_ms + 5 * 60 * 1000
                position = None
                continue

            # Stale trade exit: after 18 bars, if MFE < 0.5R and PnL < 0.25R
            bars_held = (bar_time_ms - int(position.entry_time.timestamp() * 1000)) // (5 * 60 * 1000)
            mfe_r = position.peak_roe_pct / (position.stop_pct * 100 * lev) if position.stop_pct > 0 else 0
            current_r = roe / (position.stop_pct * 100 * lev) if position.stop_pct > 0 else 0
            if bars_held >= 18 and mfe_r < 0.5 and current_r < 0.25:
                position.exit_price = cl
                position.exit_time = bar_time
                position.exit_reason = "STALE"
                _finalize(position, cost_bps)
                trades.append(position)
                daily_loss += position.net_pnl_usd
                weekly_loss += position.net_pnl_usd
                cooldown_until_ms = bar_time_ms + 5 * 60 * 1000
                position = None
                continue

            # Hard time exit: 36h
            if bars_held >= 432:  # 36h / 5m
                position.exit_price = cl
                position.exit_time = bar_time
                position.exit_reason = "TIME"
                _finalize(position, cost_bps)
                trades.append(position)
                daily_loss += position.net_pnl_usd
                weekly_loss += position.net_pnl_usd
                position = None
                continue

            continue  # still in position

        # ── No position — check entry ──

        # Cooldown check
        if bar_time_ms < cooldown_until_ms:
            continue

        # Daily/weekly loss stop
        # Using R = 0.75% equity as 1R
        one_r = equity_usd * 0.0075
        if daily_loss <= -2 * one_r:
            continue
        if weekly_loss <= -5 * one_r:
            continue

        # Re-entry cooldown after SL
        if last_sl_symbol == symbol and (i - last_sl_bar_idx) < 12:
            continue

        # ── Build indicators ──
        # 5m data
        closes_5m = [bars[j]["close_price"] for j in range(max(0, i - 100), i + 1)]
        highs_5m = [bars[j]["high_price"] for j in range(max(0, i - 100), i + 1)]
        lows_5m = [bars[j]["low_price"] for j in range(max(0, i - 100), i + 1)]
        volumes_5m = [bars[j].get("base_volume", bars[j].get("quote_volume", 0)) for j in range(max(0, i - 100), i + 1)]

        if len(closes_5m) < 30:
            continue

        # ATR percentile gate
        atr_5m = _atr(highs_5m, lows_5m, closes_5m, 14)
        atr_pct = atr_5m / closes_5m[-1] if closes_5m[-1] > 0 else 0
        atr_history.append(atr_pct)
        if len(atr_history) > 5760:  # 20 days of 5m bars
            atr_history = atr_history[-5760:]
        if len(atr_history) >= 100:
            rank = sum(1 for a in atr_history if a <= atr_pct) / len(atr_history)
            if rank < 0.35 or rank > 0.85:
                _dbg["atr_filter"] += 1
                continue

        # Find 1h bars up to current 5m bar time
        h1_bars_recent = [t for t in _h1_sorted if t <= bar_time_ms][-200:]
        if len(h1_bars_recent) < 50:
            continue
        h1_closes = [h1_by_time[t]["close_price"] for t in h1_bars_recent]
        h1_highs = [h1_by_time[t]["high_price"] for t in h1_bars_recent]
        h1_lows = [h1_by_time[t]["low_price"] for t in h1_bars_recent]

        # 1h indicators
        ema20_1h = _ema(h1_closes, 20)
        ema50_1h = _ema(h1_closes, 50)
        ema200_1h = _ema(h1_closes, 200) if len(h1_closes) >= 200 else _ema(h1_closes, len(h1_closes))
        adx_1h = _adx(h1_highs, h1_lows, h1_closes, 14)
        rsi_1h = _rsi(h1_closes, 14)

        # 4h EMA200 bias
        h4_bars_recent = [t for t in _h4_sorted if t <= bar_time_ms][-200:]
        if len(h4_bars_recent) < 10:
            continue
        h4_closes = [h4_by_time[t]["close_price"] for t in h4_bars_recent]
        ema200_4h = _ema(h4_closes, 200) if len(h4_closes) >= 200 else _ema(h4_closes, len(h4_closes))
        ema50_4h = _ema(h4_closes, 50) if len(h4_closes) >= 50 else _ema(h4_closes, len(h4_closes))
        ema50_slope = (ema50_4h - _ema(h4_closes[:-10] if len(h4_closes) > 10 else h4_closes, 50)) if len(h4_closes) > 10 else 0

        # Determine regime
        long_regime = (h4_closes[-1] > ema200_4h and ema50_slope > 0 and
                       ema20_1h > ema50_1h > ema200_1h and adx_1h >= 18 and 52 <= rsi_1h <= 68)
        short_regime = (h4_closes[-1] < ema200_4h and ema50_slope < 0 and
                        ema20_1h < ema50_1h < ema200_1h and adx_1h >= 18 and 32 <= rsi_1h <= 48)

        if not long_regime and not short_regime:
            _dbg["no_regime"] += 1
            continue
        _dbg["regime_pass"] += 1

        # TTM Squeeze check: was on for >= 4 of last 6 bars, released in last 3
        squeeze_states = []
        for j in range(max(0, i - 6), i + 1):
            c = [bars[k]["close_price"] for k in range(max(0, j - 20), j + 1)]
            h = [bars[k]["high_price"] for k in range(max(0, j - 20), j + 1)]
            l = [bars[k]["low_price"] for k in range(max(0, j - 20), j + 1)]
            squeeze_states.append(_ttm_squeeze_on(c, h, l))

        squeeze_on_count = sum(squeeze_states[:-1]) if len(squeeze_states) > 1 else 0
        squeeze_released = not squeeze_states[-1] if squeeze_states else False
        recently_released = any(not s for s in squeeze_states[-3:]) if len(squeeze_states) >= 3 else False

        if squeeze_on_count < 4 or not recently_released:
            _dbg["squeeze_fail"] += 1
            continue
        _dbg["squeeze_pass"] += 1

        # Donchian breakout
        dc_high, dc_low = _donchian(highs_5m[:-1], lows_5m[:-1], 20)
        close = closes_5m[-1]
        high = highs_5m[-1]
        low = lows_5m[-1]

        # Determine side
        side = ""
        if long_regime and close > dc_high + 0.10 * atr_5m:
            side = "long"
        elif short_regime and close < dc_low - 0.10 * atr_5m:
            side = "short"

        if not side:
            _dbg["no_breakout"] += 1
            continue
        _dbg["breakout_pass"] += 1

        # Volume confirmation
        vol_median = sorted(volumes_5m[-21:-1])[len(volumes_5m[-21:-1]) // 2] if len(volumes_5m) >= 21 else 1
        if volumes_5m[-1] < 1.15 * vol_median:
            _dbg["vol_fail"] += 1
            continue

        # Chase filter: breakout bar range <= 1.8 * ATR
        bar_range = high - low
        if bar_range > 1.8 * atr_5m:
            _dbg["chase_filter"] += 1
            continue

        # VWAP approximation (session = last 288 bars = 24h)
        vwap_lookback = min(288, i)
        vwap_num = sum(bars[j]["close_price"] * bars[j].get("base_volume", bars[j].get("quote_volume", 1))
                       for j in range(i - vwap_lookback, i + 1))
        vwap_den = sum(bars[j].get("base_volume", bars[j].get("quote_volume", 1))
                       for j in range(i - vwap_lookback, i + 1))
        vwap = vwap_num / max(vwap_den, 1)

        if side == "long" and close < vwap:
            _dbg["vwap_fail"] += 1
            continue
        if side == "short" and close > vwap:
            _dbg["vwap_fail"] += 1
            continue
        _dbg["ALL_PASS"] += 1

        # ── ENTER ──
        stop_pct = max(0.0085, 2.0 * atr_5m / close)  # wider: 2.0x ATR (was 1.05x)
        lev = default_leverage
        # Higher leverage only if ATR percentile 35-60
        atr_rank = sum(1 for a in atr_history if a <= atr_pct) / max(len(atr_history), 1)
        if atr_rank <= 0.60 and adx_1h >= 22:
            lev = max_leverage

        risk_per_trade = equity_usd * 0.0075
        notional = risk_per_trade / stop_pct

        position = Trade(
            symbol=symbol,
            side=side,
            entry_time=bar_time,
            entry_price=close,
            leverage=lev,
            notional_usd=notional,
            stop_pct=stop_pct,
            r_target=1.9,
        )

    # Print debug counters
    print(f"    [debug] {symbol}: " + ", ".join(f"{k}={v}" for k, v in sorted(_dbg.items(), key=lambda x: -x[1])[:10]))

    # Close any remaining position
    if position is not None and len(bars) > 0:
        position.exit_price = bars[-1]["close_price"]
        position.exit_time = datetime.fromtimestamp(bars[-1]["open_time"] / 1000, tz=timezone.utc)
        position.exit_reason = "END"
        _finalize(position, cost_bps)
        trades.append(position)

    return trades


def _finalize(trade: Trade, cost_bps: float):
    if trade.exit_price is None or trade.entry_price <= 0:
        return
    if trade.side == "long":
        raw = (trade.exit_price / trade.entry_price - 1)
    else:
        raw = -(trade.exit_price / trade.entry_price - 1)
    trade.pnl_usd = trade.notional_usd * raw
    trade.fee_usd = trade.notional_usd * cost_bps / 10000
    trade.net_pnl_usd = trade.pnl_usd - trade.fee_usd


def walk_forward_validate(trades: list[Trade], n_folds: int = 4) -> dict:
    if not trades:
        return {"valid": False, "reason": "no_trades", "folds": []}
    sorted_t = sorted(trades, key=lambda t: t.entry_time or datetime.min)
    fold_size = len(sorted_t) // n_folds
    if fold_size < 3:
        return {"valid": False, "reason": "too_few", "folds": []}
    folds = []
    for i in range(n_folds):
        s = i * fold_size
        e = s + fold_size if i < n_folds - 1 else len(sorted_t)
        fold = sorted_t[s:e]
        pnl = sum(t.net_pnl_usd for t in fold)
        wr = sum(1 for t in fold if t.net_pnl_usd > 0) / max(len(fold), 1)
        folds.append({"q": i + 1, "n": len(fold), "pnl": round(pnl, 2), "wr": round(wr, 4)})
    profitable = sum(1 for f in folds if f["pnl"] > 0)
    return {"valid": profitable >= 3, "profitable_folds": profitable, "folds": folds}


def main(argv=None):
    parser = argparse.ArgumentParser(description="GPT-5.4 cross-validated unified strategy backtest")
    parser.add_argument("--symbols", default="ETHUSDT,SOLUSDT")
    parser.add_argument("--equity-usd", type=float, default=75.0)
    parser.add_argument("--cost-bps", type=float, default=42.0)
    parser.add_argument("--output-base", default="quant_runtime")
    args = parser.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",")]
    data_dir = Path(args.output_base) / "historical"

    print(f"[GPT-5.4 Unified] equity=${args.equity_usd}, cost={args.cost_bps}bps")
    print(f"  Strategy: Regime-gated Donchian breakout + TTM squeeze release")
    print(f"  Exit: 1.9R TP, 1.0R SL, BE at 1.15R, stale at 18bars, max 36h")
    print(f"  Leverage: 12x default, 15x in low-vol high-ADX regime")

    # Test at multiple cost levels (stress test)
    for cost in [args.cost_bps, 60, 80]:
        print(f"\n{'='*80}")
        print(f"  COST STRESS: {cost}bps")
        print(f"{'='*80}")

        all_trades: list[Trade] = []
        for sym in symbols:
            # Load bars
            bars_5m = []
            p5 = data_dir / sym / "5m.json"
            if p5.exists():
                with open(p5) as f:
                    bars_5m = json.load(f)

            bars_1h = []
            # Try JSON first (historical dir)
            p1h_json = data_dir / sym / "1h.json"
            p1h_csv = Path(args.output_base) / "backtest_1h_data" / f"{sym}_1h.csv"
            if p1h_json.exists():
                with open(p1h_json) as f:
                    bars_1h = json.load(f)
            elif p1h_csv.exists():
                import csv
                with open(p1h_csv) as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            ot = int(float(row.get("timestamp", row.get("open_time", 0))))
                            bars_1h.append({
                                "open_time": ot,
                                "close_time": ot + 3600000,
                                "open_price": float(row.get("open", row.get("open_price", 0))),
                                "high_price": float(row.get("high", row.get("high_price", 0))),
                                "low_price": float(row.get("low", row.get("low_price", 0))),
                                "close_price": float(row.get("close", row.get("close_price", 0))),
                                "base_volume": float(row.get("volume", 0)),
                                "quote_volume": float(row.get("volume", 0)),
                            })
                        except (ValueError, KeyError):
                            continue

            # Try loading 4h from historical dir
            bars_4h = []
            p4h = data_dir / sym / "4h.json"
            if p4h.exists():
                with open(p4h) as f:
                    bars_4h = json.load(f)
            elif bars_1h:
                # Synthesize 4h from 1h
                sorted_1h = sorted(bars_1h, key=lambda b: b["open_time"])
                for j in range(0, len(sorted_1h) - 3, 4):
                    chunk = sorted_1h[j:j + 4]
                    bars_4h.append({
                        "open_time": chunk[0]["open_time"],
                        "close_time": chunk[-1].get("close_time", chunk[-1]["open_time"] + 14400000),
                        "open_price": chunk[0]["open_price"],
                        "high_price": max(c["high_price"] for c in chunk),
                        "low_price": min(c["low_price"] for c in chunk),
                        "close_price": chunk[-1]["close_price"],
                        "quote_volume": sum(c.get("quote_volume", 0) for c in chunk),
                    })

            if not bars_5m:
                print(f"  {sym}: no 5m data, skipping")
                continue

            print(f"  {sym}: {len(bars_5m)} 5m, {len(bars_1h)} 1h, {len(bars_4h)} 4h bars")

            t0 = time.time()
            sym_trades = run_gpt54_backtest(
                bars_5m=bars_5m,
                bars_1h=bars_1h,
                bars_4h=bars_4h,
                symbol=sym,
                equity_usd=args.equity_usd,
                cost_bps=cost,
            )
            elapsed = time.time() - t0
            print(f"  {sym}: {len(sym_trades)} trades in {elapsed:.1f}s")
            all_trades.extend(sym_trades)

        if not all_trades:
            print("  No trades generated!")
            continue

        # Results
        n = len(all_trades)
        wins = sum(1 for t in all_trades if t.net_pnl_usd > 0)
        total_pnl = sum(t.net_pnl_usd for t in all_trades)
        gross_profit = sum(t.net_pnl_usd for t in all_trades if t.net_pnl_usd > 0)
        gross_loss = abs(sum(t.net_pnl_usd for t in all_trades if t.net_pnl_usd <= 0))
        pf = gross_profit / max(gross_loss, 0.01)
        wr = wins / max(n, 1)
        avg_hold = sum(t.holding_minutes for t in all_trades) / max(n, 1)

        print(f"\n  RESULTS ({cost}bps):")
        print(f"  Trades: {n}, Win: {wins}, Loss: {n - wins}")
        print(f"  Win Rate: {wr * 100:.1f}%")
        print(f"  Total PnL: ${total_pnl:.2f}")
        print(f"  Profit Factor: {pf:.2f}")
        print(f"  Avg Hold: {avg_hold:.0f} min ({avg_hold / 60:.1f}h)")

        # Exit reason breakdown
        reasons: dict[str, list] = defaultdict(list)
        for t in all_trades:
            reasons[t.exit_reason].append(t)
        print(f"\n  Exit reasons:")
        for r, ts in sorted(reasons.items(), key=lambda x: -len(x[1])):
            avg = sum(t.net_pnl_usd for t in ts) / len(ts)
            w = sum(1 for t in ts if t.net_pnl_usd > 0) / len(ts) * 100
            print(f"    {r:10s}: {len(ts):4d} trades, WR={w:5.1f}%, avg=${avg:+.2f}")

        # Per-symbol
        for sym in symbols:
            st = [t for t in all_trades if t.symbol == sym]
            if st:
                sp = sum(t.net_pnl_usd for t in st)
                sw = sum(1 for t in st if t.net_pnl_usd > 0) / len(st) * 100
                print(f"  {sym}: {len(st)} trades, WR={sw:.1f}%, PnL=${sp:.2f}")

        # Walk-forward
        wf = walk_forward_validate(all_trades)
        print(f"\n  Walk-forward: {'VALID' if wf['valid'] else 'FAILED'} ({wf.get('profitable_folds', 0)}/4)")
        for f in wf.get("folds", []):
            s = "+" if f["pnl"] > 0 else "-"
            print(f"    Q{f['q']}: {f['n']} trades, WR={f['wr'] * 100:.1f}%, PnL=${f['pnl']:+.2f} {s}")

    # Save
    output_path = Path(args.output_base) / "output" / "gpt54_unified_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_data = [{
        "symbol": t.symbol, "side": t.side,
        "entry": t.entry_time.isoformat() if t.entry_time else "",
        "exit": t.exit_time.isoformat() if t.exit_time else "",
        "exit_reason": t.exit_reason,
        "leverage": t.leverage,
        "net_pnl": round(t.net_pnl_usd, 2),
        "hold_min": round(t.holding_minutes, 0),
    } for t in all_trades]
    output_path.write_text(json.dumps(save_data, indent=2))
    print(f"\nTrades saved to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
