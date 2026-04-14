#!/usr/bin/env python3
"""
90-day backtest runner for autotuner data generation.

Fetches 1h OHLCV from Binance public API for BTC/ETH/SOL/XRP,
runs a simplified regime-based simulation, and outputs
closed_trades.jsonl compatible with the autotuner's _valid_trades() filter.

Required autotuner fields:
  - entry_predictability_score > 0
  - realized_return_bps_estimate (abs >= 0.01)
  - realized_pnl_usd_estimate
  - holding_minutes
  - best_return_bps / worst_return_bps
  - exit_reason (contains "STOP" for stop-loss exits)

Usage:
  python scripts/run_backtest_90d.py [--days 90] [--equity 1000]
"""
from __future__ import annotations

import argparse
import json
import math
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

# ── Strategy parameters ──────────────────────────────────────────────────────
EMA_SHORT = 9
EMA_LONG = 21
EMA_TREND = 50
ATR_PERIOD = 14
RSI_PERIOD = 14
VOL_SMA_PERIOD = 20

ATR_STOP_MULTIPLE = 2.0        # Stop at 2x ATR from entry
ATR_TP_MULTIPLE = 3.0          # Take-profit at 3x ATR
MAX_HOLDING_HOURS = 8          # 8h max holding → 480 min
SLIPPAGE_BPS = 10.0            # 0.10% round-trip slippage
PER_TRADE_RISK_FRACTION = 0.0055
BASE_EQUITY_USD = 1000.0


# ── Binance API ──────────────────────────────────────────────────────────────

def fetch_klines_page(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    limit: int = 1000,
) -> list[list]:
    """Fetch one page of klines from Binance public API."""
    url = (
        f"{BINANCE_KLINES_URL}?symbol={symbol}&interval={interval}"
        f"&startTime={start_ms}&endTime={end_ms}&limit={limit}"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        print(f"  [WARN] Binance API error for {symbol}: {e}")
        return []


def fetch_all_klines(symbol: str, interval: str = "1h", days: int = 90) -> list[dict]:
    """Fetch all klines for the past `days` days, handling pagination."""
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    start_ms = now_ms - days * 24 * 3600 * 1000

    candles = []
    cursor = start_ms
    while cursor < now_ms:
        print(f"  Fetching {symbol} {interval} from {datetime.fromtimestamp(cursor/1000, tz=timezone.utc).date()} ...")
        page = fetch_klines_page(symbol, interval, cursor, now_ms)
        if not page:
            break
        for k in page:
            candles.append({
                "open_time": k[0],
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": k[6],
            })
        cursor = page[-1][0] + 1  # next page starts after last candle
        if len(page) < 1000:
            break
        time.sleep(0.12)  # ~8 req/sec, well within Binance rate limit

    # Remove duplicates, sort by time
    seen: set[int] = set()
    unique = []
    for c in candles:
        if c["open_time"] not in seen:
            seen.add(c["open_time"])
            unique.append(c)
    unique.sort(key=lambda c: c["open_time"])
    return unique


# ── Technical indicators ─────────────────────────────────────────────────────

def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1)
    # Seed with SMA
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    for i in range(period, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)  # type: ignore[operator]
    return out


def atr(candles: list[dict], period: int = ATR_PERIOD) -> list[float | None]:
    trs: list[float] = []
    for i, c in enumerate(candles):
        if i == 0:
            trs.append(c["high"] - c["low"])
        else:
            prev_close = candles[i - 1]["close"]
            tr = max(c["high"] - c["low"], abs(c["high"] - prev_close), abs(c["low"] - prev_close))
            trs.append(tr)

    out: list[float | None] = [None] * len(candles)
    if len(trs) < period:
        return out
    # Wilder's smoothing (RMA)
    seed = sum(trs[:period]) / period
    out[period - 1] = seed
    for i in range(period, len(trs)):
        out[i] = (out[i - 1] * (period - 1) + trs[i]) / period  # type: ignore[operator]
    return out


def rsi(closes: list[float], period: int = RSI_PERIOD) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(closes)):
        j = i - period  # index into gains/losses
        avg_gain = (avg_gain * (period - 1) + gains[j]) / period
        avg_loss = (avg_loss * (period - 1) + losses[j]) / period
        rs = avg_gain / (avg_loss + 1e-10)
        out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = sum(values[i - period + 1 : i + 1]) / period
    return out


def compute_all_indicators(candles: list[dict]) -> dict[str, list[float | None]]:
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    return {
        "ema_short": ema(closes, EMA_SHORT),
        "ema_long": ema(closes, EMA_LONG),
        "ema_trend": ema(closes, EMA_TREND),
        "atr": atr(candles, ATR_PERIOD),
        "rsi": rsi(closes, RSI_PERIOD),
        "vol_sma": sma(volumes, VOL_SMA_PERIOD),
    }


# ── Predictability score ─────────────────────────────────────────────────────

def compute_predictability_score(
    candles: list[dict],
    ind: dict[str, list[float | None]],
    i: int,
) -> float:
    """
    Composite signal strength score (0-100).
    Mimics the system's predictability_score used in _valid_trades() filter.
    """
    ema_s = ind["ema_short"][i]
    ema_l = ind["ema_long"][i]
    ema_t = ind["ema_trend"][i]
    rsi_v = ind["rsi"][i]
    vol_s = ind["vol_sma"][i]
    atr_v = ind["atr"][i]

    if any(v is None for v in [ema_s, ema_l, ema_t, rsi_v, vol_s, atr_v]):
        return 0.0

    close = candles[i]["close"]
    vol = candles[i]["volume"]

    score = 0.0

    # EMA alignment (0-30 pts)
    if ema_s > ema_l > ema_t:  # type: ignore
        # Bullish stack
        gap_sl = (ema_s - ema_l) / (ema_l + 1e-10) * 100  # type: ignore
        gap_lt = (ema_l - ema_t) / (ema_t + 1e-10) * 100  # type: ignore
        score += min(30.0, 10.0 + gap_sl * 5 + gap_lt * 3)
    elif ema_s < ema_l < ema_t:  # type: ignore
        # Bearish stack
        gap_sl = (ema_l - ema_s) / (ema_l + 1e-10) * 100  # type: ignore
        gap_lt = (ema_t - ema_l) / (ema_t + 1e-10) * 100  # type: ignore
        score += min(30.0, 10.0 + gap_sl * 5 + gap_lt * 3)

    # RSI position (0-20 pts)
    if 40 <= rsi_v <= 60:  # type: ignore
        score += 20.0
    elif 30 <= rsi_v < 40 or 60 < rsi_v <= 70:  # type: ignore
        score += 12.0
    elif rsi_v < 30 or rsi_v > 70:  # type: ignore
        score += 5.0

    # Volume confirmation (0-25 pts)
    vol_ratio = vol / (vol_s + 1e-10)  # type: ignore
    if vol_ratio > 1.5:
        score += 25.0
    elif vol_ratio > 1.2:
        score += 18.0
    elif vol_ratio > 1.0:
        score += 10.0

    # Price vs EMA distance (0-15 pts) — breakout confirmation
    dist_from_trend = abs(close - ema_t) / (ema_t + 1e-10) * 100  # type: ignore
    if 0.2 <= dist_from_trend <= 2.0:
        score += 15.0
    elif dist_from_trend < 0.2:
        score += 8.0  # too close, consolidating
    else:
        score += 3.0  # too extended, overheated

    # ATR normalization bonus (0-10 pts) — stable volatility
    atr_pct = atr_v / (close + 1e-10) * 100  # type: ignore
    if 0.3 <= atr_pct <= 1.5:
        score += 10.0
    elif atr_pct < 0.3 or atr_pct > 3.0:
        score += 2.0

    return round(min(100.0, max(0.0, score)), 2)


# ── Trade simulation ──────────────────────────────────────────────────────────

def determine_signal(
    candles: list[dict],
    ind: dict[str, list[float | None]],
    i: int,
) -> str:
    """Return 'long', 'short', or 'none'."""
    ema_s = ind["ema_short"][i]
    ema_l = ind["ema_long"][i]
    ema_t = ind["ema_trend"][i]
    rsi_v = ind["rsi"][i]
    atr_v = ind["atr"][i]

    if any(v is None for v in [ema_s, ema_l, ema_t, rsi_v, atr_v]):
        return "none"

    close = candles[i]["close"]
    prev_ema_s = ind["ema_short"][i - 1] if i > 0 else None
    prev_ema_l = ind["ema_long"][i - 1] if i > 0 else None

    bullish_stack = ema_s > ema_l > ema_t  # type: ignore
    bearish_stack = ema_s < ema_l < ema_t  # type: ignore

    # EMA crossover (short crosses above/below long)
    long_cross = (
        prev_ema_s is not None
        and prev_ema_l is not None
        and prev_ema_s <= prev_ema_l  # type: ignore
        and ema_s > ema_l  # type: ignore
    )
    short_cross = (
        prev_ema_s is not None
        and prev_ema_l is not None
        and prev_ema_s >= prev_ema_l  # type: ignore
        and ema_s < ema_l  # type: ignore
    )

    # Long: bullish stack + crossover (or strong stack) + RSI momentum
    if bullish_stack and (long_cross or (ema_s > ema_l * 1.001)) and 40 <= rsi_v <= 65:  # type: ignore
        return "long"

    # Short: bearish stack + crossover + RSI momentum
    if bearish_stack and (short_cross or (ema_s < ema_l * 0.999)) and 35 <= rsi_v <= 60:  # type: ignore
        return "short"

    return "none"


def simulate_symbol(
    symbol: str,
    candles: list[dict],
    equity_usd: float = BASE_EQUITY_USD,
) -> list[dict[str, Any]]:
    """Simulate trades for one symbol. Returns list of closed trade records."""
    if len(candles) < EMA_TREND + 10:
        print(f"  [WARN] {symbol}: insufficient data ({len(candles)} candles)")
        return []

    ind = compute_all_indicators(candles)
    trades: list[dict[str, Any]] = []

    in_position = False
    entry_idx = 0
    entry_price = 0.0
    side = "long"
    stop_price = 0.0
    tp_price = 0.0
    atr_at_entry = 0.0
    score_at_entry = 0.0

    # Track in-trade high/low for best/worst return calculation
    trade_high = 0.0
    trade_low = float("inf")

    for i in range(EMA_TREND + 1, len(candles)):
        c = candles[i]
        close = c["close"]
        high = c["high"]
        low = c["low"]
        entry_time_ms = candles[entry_idx]["open_time"] if in_position else 0
        holding_hours = (c["open_time"] - entry_time_ms) / 3_600_000 if in_position else 0

        if not in_position:
            signal = determine_signal(candles, ind, i)
            if signal == "none":
                continue

            score = compute_predictability_score(candles, ind, i)
            # Only enter if score is meaningful (> 50 ensures predictability_score > 0)
            if score < 50.0:
                continue

            atr_v = ind["atr"][i]
            if atr_v is None or atr_v <= 0:
                continue

            entry_price = close
            side = signal
            atr_at_entry = float(atr_v)
            score_at_entry = score

            if side == "long":
                stop_price = entry_price - ATR_STOP_MULTIPLE * atr_at_entry
                tp_price = entry_price + ATR_TP_MULTIPLE * atr_at_entry
            else:
                stop_price = entry_price + ATR_STOP_MULTIPLE * atr_at_entry
                tp_price = entry_price - ATR_TP_MULTIPLE * atr_at_entry

            in_position = True
            entry_idx = i
            trade_high = entry_price
            trade_low = entry_price
            continue

        # Update trade extremes
        trade_high = max(trade_high, high)
        trade_low = min(trade_low, low)

        # Check exit conditions
        exit_reason = None
        exit_price = close

        if side == "long":
            if low <= stop_price:
                exit_reason = "STOP_LOSS"
                exit_price = stop_price
            elif high >= tp_price:
                exit_reason = "TAKE_PROFIT"
                exit_price = tp_price
        else:  # short
            if high >= stop_price:
                exit_reason = "STOP_LOSS"
                exit_price = stop_price
            elif low <= tp_price:
                exit_reason = "TAKE_PROFIT"
                exit_price = tp_price

        if exit_reason is None and holding_hours >= MAX_HOLDING_HOURS:
            exit_reason = "MAX_HOLDING"
            exit_price = close

        if exit_reason is None:
            continue

        # --- Compute PnL ---
        if side == "long":
            raw_ret_bps = (exit_price - entry_price) / entry_price * 10000.0
        else:
            raw_ret_bps = (entry_price - exit_price) / entry_price * 10000.0

        # Apply slippage: -0.1% = -10 bps (conservative)
        ret_bps = raw_ret_bps - SLIPPAGE_BPS

        # Position size based on risk
        risk_usd = equity_usd * PER_TRADE_RISK_FRACTION
        stop_dist_pct = abs(entry_price - stop_price) / entry_price
        qty_usd = risk_usd / (stop_dist_pct + 1e-10)
        qty_usd = min(qty_usd, equity_usd * 0.3)  # cap at 30% of equity
        quantity = qty_usd / entry_price

        pnl_usd = qty_usd * (ret_bps / 10000.0)
        equity_usd += pnl_usd

        # Best/worst return (for stop waste analysis)
        if side == "long":
            best_ret_bps = (trade_high - entry_price) / entry_price * 10000.0 - SLIPPAGE_BPS
            worst_ret_bps = (trade_low - entry_price) / entry_price * 10000.0 - SLIPPAGE_BPS
        else:
            best_ret_bps = (entry_price - trade_low) / entry_price * 10000.0 - SLIPPAGE_BPS
            worst_ret_bps = (entry_price - trade_high) / entry_price * 10000.0 - SLIPPAGE_BPS

        holding_minutes = holding_hours * 60.0
        entry_time_str = datetime.fromtimestamp(
            candles[entry_idx]["open_time"] / 1000, tz=timezone.utc
        ).isoformat()
        exit_time_str = datetime.fromtimestamp(
            c["close_time"] / 1000, tz=timezone.utc
        ).isoformat()

        hour_utc = datetime.fromtimestamp(
            candles[entry_idx]["open_time"] / 1000, tz=timezone.utc
        ).strftime("%H:00")

        trades.append({
            "symbol": symbol,
            "side": side,
            "market": "futures",
            "entry_price": round(entry_price, 8),
            "exit_price": round(exit_price, 8),
            "entry_time": entry_time_str,
            "exit_time": exit_time_str,
            "exit_reason": exit_reason,
            "quantity": round(quantity, 8),
            "realized_pnl_usd_estimate": round(pnl_usd, 6),
            "realized_return_bps_estimate": round(ret_bps, 6),
            "entry_predictability_score": round(score_at_entry, 2),
            "holding_minutes": round(holding_minutes, 2),
            "best_return_bps": round(best_ret_bps, 4),
            "worst_return_bps": round(worst_ret_bps, 4),
            "partial_exit": False,
            "loss_combo_key": f"{symbol}|{side}|{hour_utc}",
            "loss_combo_time_bucket_utc": hour_utc,
        })

        in_position = False

    return trades


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="90-day backtest for autotuner")
    parser.add_argument("--days", type=int, default=90, help="Lookback days (default: 90)")
    parser.add_argument("--equity", type=float, default=BASE_EQUITY_USD, help="Starting equity USD")
    parser.add_argument("--dry-run", action="store_true", help="Print stats, don't write files")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Override output directory (default: quant_runtime/output/paper-live-shell/<timestamp>/logs/)",
    )
    args = parser.parse_args()

    # Determine output path
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        out_dir = Path("quant_runtime/output/paper-live-shell") / f"backtest-90d-{ts}" / "logs"

    all_trades: list[dict[str, Any]] = []

    for symbol in SYMBOLS:
        print(f"\n[{symbol}] Fetching {args.days}-day 1h OHLCV ...")
        candles = fetch_all_klines(symbol, interval="1h", days=args.days)
        print(f"  → {len(candles)} candles loaded")

        if not candles:
            print(f"  [SKIP] No data for {symbol}")
            continue

        print(f"[{symbol}] Running simulation ...")
        trades = simulate_symbol(symbol, candles, equity_usd=args.equity)
        print(f"  → {len(trades)} trades generated")

        wins = [t for t in trades if t["realized_return_bps_estimate"] > 0]
        losses = [t for t in trades if t["realized_return_bps_estimate"] <= 0]
        total_pnl = sum(t["realized_pnl_usd_estimate"] for t in trades)
        win_rate = len(wins) / len(trades) * 100 if trades else 0
        avg_ret = sum(t["realized_return_bps_estimate"] for t in trades) / len(trades) if trades else 0
        print(f"  WR={win_rate:.1f}%  avgRet={avg_ret:+.1f}bps  totalPnL=${total_pnl:+.2f}")

        all_trades.extend(trades)

    print(f"\n{'='*50}")
    print(f"Total trades across all symbols: {len(all_trades)}")
    valid = [
        t for t in all_trades
        if abs(t.get("realized_return_bps_estimate", 0)) >= 0.01
        and t.get("entry_predictability_score", 0) > 0
    ]
    print(f"Valid trades (for autotuner): {len(valid)}")

    if args.dry_run:
        print("[DRY RUN] Skipping file write.")
        return

    if not all_trades:
        print("[ERROR] No trades generated. Check API connectivity.")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "closed_trades.jsonl"

    with out_file.open("w", encoding="utf-8") as f:
        for trade in all_trades:
            f.write(json.dumps(trade, ensure_ascii=False) + "\n")

    print(f"\nWrote {len(all_trades)} trades → {out_file}")
    print(f"Run autotuner:\n  python -m quant_binance.autotuner.analyzer --base-dir quant_runtime --override-path quant_runtime/artifacts/strategy_override.approved.json")


if __name__ == "__main__":
    main()
