#!/usr/bin/env python3
"""Bybit 5m surge-strategy grid search.

Uses local Bybit-style historical candles under quant_runtime/historical.
No live orders, no private API access. The goal is to compare sudden-surge
candidate rules on the same symbols, costs, and walk-forward split.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from bisect import bisect_right
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "quant_runtime" / "historical"
OUT_PATH = ROOT / "quant_runtime" / "output" / "bybit_surge_grid_search.json"


@dataclass
class Bars:
    symbol: str
    ts: list[int]
    o: list[float]
    h: list[float]
    l: list[float]
    c: list[float]
    v: list[float]
    oi: list[float | None]


@dataclass
class Trade:
    symbol: str
    strategy: str
    side: str
    entry_i: int
    exit_i: int
    entry: float
    exit: float
    pnl_bps: float
    reason: str


def _f(row: dict, *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return float(row[key])
    return default


def load_bars(symbol: str) -> Bars | None:
    path = DATA_DIR / symbol / "5m.json"
    if not path.exists():
        return None
    rows = json.loads(path.read_text())
    if len(rows) < 1500:
        return None
    ts, o, h, l, c, v = [], [], [], [], [], []
    for row in rows:
        ts.append(int(row.get("open_time") or row.get("ts") or 0))
        o.append(_f(row, "open_price", "o", "open"))
        h.append(_f(row, "high_price", "h", "high"))
        l.append(_f(row, "low_price", "l", "low"))
        c.append(_f(row, "close_price", "c", "close"))
        v.append(_f(row, "quote_volume", "base_volume", "v", "volume"))
    oi = align_oi(symbol, ts)
    return Bars(symbol=symbol, ts=ts, o=o, h=h, l=l, c=c, v=v, oi=oi)


def align_oi(symbol: str, ts: list[int]) -> list[float | None]:
    path = DATA_DIR / symbol / "oi_1h.json"
    if not path.exists():
        return [None] * len(ts)
    rows = json.loads(path.read_text())
    points: list[tuple[int, float]] = []
    for row in rows:
        t = int(row.get("timestamp") or row.get("open_time") or row.get("ts") or 0)
        val = _f(row, "open_interest", "oi", "sumOpenInterest", default=math.nan)
        if t and math.isfinite(val):
            points.append((t, val))
    points.sort()
    if not points:
        return [None] * len(ts)
    out: list[float | None] = []
    j = 0
    last: float | None = None
    for t in ts:
        while j < len(points) and points[j][0] <= t:
            last = points[j][1]
            j += 1
        out.append(last)
    return out


def sma(vals: list[float], i: int, n: int) -> float | None:
    if i - n + 1 < 0:
        return None
    return sum(vals[i - n + 1 : i + 1]) / n


def atr(b: Bars, i: int, n: int = 14) -> float | None:
    if i - n < 0:
        return None
    trs = []
    for j in range(i - n + 1, i + 1):
        trs.append(max(b.h[j] - b.l[j], abs(b.h[j] - b.c[j - 1]), abs(b.l[j] - b.c[j - 1])))
    return sum(trs) / len(trs)


def volume_ratio(b: Bars, i: int, lookback: int) -> float:
    base = sma(b.v, i - 1, lookback)
    if not base or base <= 0:
        return 0.0
    return b.v[i] / base


def oi_delta_pct(b: Bars, i: int, lookback: int) -> float | None:
    if i - lookback < 0:
        return None
    now, prev = b.oi[i], b.oi[i - lookback]
    if now is None or prev is None or prev <= 0:
        return None
    return (now / prev - 1.0) * 100.0


def rolling_high(vals: list[float], end_exclusive: int, n: int) -> float | None:
    if end_exclusive - n < 0:
        return None
    return max(vals[end_exclusive - n : end_exclusive])


def rolling_low(vals: list[float], end_exclusive: int, n: int) -> float | None:
    if end_exclusive - n < 0:
        return None
    return min(vals[end_exclusive - n : end_exclusive])


def exit_trade(
    b: Bars,
    *,
    i: int,
    side: str,
    hold: int,
    stop_pct: float,
    tp_pct: float,
    cost_bps: float,
    strategy: str,
) -> Trade:
    entry_i = min(i + 1, len(b.c) - 1)
    entry = b.o[entry_i]
    side_mult = 1.0 if side == "long" else -1.0
    stop = entry * (1.0 - side_mult * stop_pct)
    target = entry * (1.0 + side_mult * tp_pct)
    exit_i = min(entry_i + hold, len(b.c) - 1)
    exit_px = b.c[exit_i]
    reason = "TIME"
    for j in range(entry_i + 1, exit_i + 1):
        if side == "long":
            if b.l[j] <= stop:
                exit_i, exit_px, reason = j, stop, "SL"
                break
            if b.h[j] >= target:
                exit_i, exit_px, reason = j, target, "TP"
                break
        else:
            if b.h[j] >= stop:
                exit_i, exit_px, reason = j, stop, "SL"
                break
            if b.l[j] <= target:
                exit_i, exit_px, reason = j, target, "TP"
                break
    gross = ((exit_px / entry - 1.0) * side_mult) * 10000.0
    return Trade(
        symbol=b.symbol,
        strategy=strategy,
        side=side,
        entry_i=entry_i,
        exit_i=exit_i,
        entry=entry,
        exit=exit_px,
        pnl_bps=gross - cost_bps,
        reason=reason,
    )


def signals_surge_momentum(b: Bars, cfg: dict) -> Iterable[tuple[int, str]]:
    lb = cfg["lookback"]
    high_lb = cfg["breakout_lookback"]
    for i in range(max(lb, high_lb, 60), len(b.c) - cfg["hold"] - 2):
        ret = b.c[i] / b.c[i - lb] - 1.0
        hi = rolling_high(b.h, i, high_lb)
        oi = oi_delta_pct(b, i, lb)
        if ret >= cfg["min_ret"] and hi and b.c[i] > hi and volume_ratio(b, i, cfg["vol_lookback"]) >= cfg["vol_mult"]:
            if cfg["require_oi_up"] and oi is not None and oi < cfg["min_oi_delta"]:
                continue
            yield i, "long"


def signals_surge_pullback(b: Bars, cfg: dict) -> Iterable[tuple[int, str]]:
    impulse_lb = cfg["impulse_lookback"]
    pull_lb = cfg["pullback_lookback"]
    for i in range(max(impulse_lb + pull_lb, 80), len(b.c) - cfg["hold"] - 2):
        start = i - impulse_lb - pull_lb
        peak = max(b.h[start : i + 1])
        pre = b.c[start]
        impulse = peak / pre - 1.0 if pre > 0 else 0.0
        impulse_abs = peak - pre
        retrace = (peak - b.c[i]) / impulse_abs if impulse_abs > 0 else 0.0
        ma = sma(b.c, i, cfg["ma"])
        if impulse >= cfg["min_impulse"] and cfg["min_retrace"] <= retrace <= cfg["max_retrace"]:
            reclaim = b.c[i] > b.c[i - 1] and b.c[i] > b.o[i]
            if reclaim and ma and b.c[i] > ma and volume_ratio(b, i, cfg["vol_lookback"]) >= cfg["vol_mult"]:
                yield i, "long"


def signals_volume_breakout(b: Bars, cfg: dict) -> Iterable[tuple[int, str]]:
    for i in range(max(cfg["range_lookback"], cfg["vol_lookback"], 60), len(b.c) - cfg["hold"] - 2):
        hi = rolling_high(b.h, i, cfg["range_lookback"])
        lo = rolling_low(b.l, i, cfg["range_lookback"])
        if not hi or not lo:
            continue
        rng = (hi - lo) / b.c[i]
        if rng > cfg["max_range"]:
            continue
        if b.c[i] > hi and volume_ratio(b, i, cfg["vol_lookback"]) >= cfg["vol_mult"]:
            yield i, "long"


def signals_failed_surge_short(b: Bars, cfg: dict) -> Iterable[tuple[int, str]]:
    lb = cfg["lookback"]
    for i in range(max(lb, cfg["vol_lookback"], 60), len(b.c) - cfg["hold"] - 2):
        ret = b.h[i] / b.c[i - lb] - 1.0
        candle_range = b.h[i] - b.l[i]
        upper_wick = b.h[i] - max(b.o[i], b.c[i])
        rejection = upper_wick / candle_range if candle_range > 0 else 0.0
        close_pos = (b.c[i] - b.l[i]) / candle_range if candle_range > 0 else 1.0
        oi = oi_delta_pct(b, i, lb)
        oi_not_confirming = oi is not None and oi <= cfg["max_oi_delta"]
        if ret >= cfg["min_ret"] and rejection >= cfg["min_rejection"] and volume_ratio(b, i, cfg["vol_lookback"]) >= cfg["vol_mult"]:
            if close_pos > cfg["max_close_pos"]:
                continue
            if cfg["prefer_oi_fade"] and not oi_not_confirming:
                continue
            yield i, "short"


SIGNAL_FNS = {
    "surge_momentum": signals_surge_momentum,
    "surge_pullback": signals_surge_pullback,
    "volume_breakout": signals_volume_breakout,
    "failed_surge_short": signals_failed_surge_short,
}


def _btc_close_at(btc: Bars | None, ts: int) -> tuple[int, float] | None:
    if btc is None:
        return None
    idx = bisect_right(btc.ts, ts) - 1
    if idx < 0:
        return None
    return idx, btc.c[idx]


def passes_combo_filters(b: Bars, i: int, cfg: dict, btc: Bars | None) -> bool:
    symbol_filter = cfg.get("symbol_filter", "none")
    if symbol_filter == "sma24_up":
        ma = sma(b.c, i, 24)
        prev = sma(b.c, i - 6, 24) if i >= 6 else None
        if not ma or not prev or not (b.c[i] > ma and ma >= prev):
            return False
    elif symbol_filter == "sma48_up":
        ma = sma(b.c, i, 48)
        if not ma or b.c[i] <= ma:
            return False

    atr_min = cfg.get("atr_min")
    atr_max = cfg.get("atr_max")
    if atr_min is not None or atr_max is not None:
        at = atr(b, i, 14)
        atr_pct = at / b.c[i] if at and b.c[i] > 0 else None
        if atr_pct is None:
            return False
        if atr_min is not None and atr_pct < atr_min:
            return False
        if atr_max is not None and atr_pct > atr_max:
            return False

    btc_filter = cfg.get("btc_filter", "none")
    if btc_filter != "none":
        hit = _btc_close_at(btc, b.ts[i])
        if hit is None:
            return False
        bi, bc = hit
        if btc_filter == "not_dumping":
            if bi < 12 or bc / btc.c[bi - 12] - 1.0 < -0.006:
                return False
        elif btc_filter == "sma48_up":
            ma = sma(btc.c, bi, 48)
            prev = sma(btc.c, bi - 12, 48) if bi >= 12 else None
            if not ma or not prev or not (bc > ma and ma >= prev):
                return False
        elif btc_filter == "weak_or_dumping":
            ma = sma(btc.c, bi, 48)
            if ma and bc > ma and (bi < 12 or bc / btc.c[bi - 12] - 1.0 > -0.002):
                return False
    return True


def cfg_grid(*, preset: str = "full") -> list[dict]:
    out: list[dict] = []
    if preset == "combo":
        momentum_grid = product([3, 6], [0.012, 0.02], [2.5], [3, 6], [0.01], [1.2, 1.8], [True], ["sma24_up"], ["not_dumping", "sma48_up"])
        pullback_grid = product([6, 12, 24], [0.3], [0.75, 1.05], [1.5], [6, 12], [0.008], [1.5, 2.2], ["sma24_up"], ["not_dumping", "sma48_up"])
        breakout_grid = product([24, 48], [0.02, 0.035], [2.5], [3, 6], [0.01], [1.2, 1.8], ["sma24_up"], ["not_dumping", "sma48_up"])
        failed_grid = product([6, 12], [0.02, 0.035], [0.45, 0.6], [2.0], [3, 6], [0.008], [1.5], [False, True], ["none"], ["none", "weak_or_dumping"])
    elif preset == "coarse":
        momentum_grid = product([3, 6, 12], [0.012, 0.02], [1.5, 3.0], [3, 6], [0.01], [1.8], [False, True])
        pullback_grid = product([6, 12, 24], [0.2], [0.55], [1.5], [6, 12], [0.008], [2.0])
        breakout_grid = product([12, 24, 48], [0.02, 0.035], [2.0], [3, 6], [0.01], [1.8])
        failed_grid = product([3, 6, 12], [0.02, 0.035], [0.3], [1.5, 3.0], [3, 6], [0.01], [1.8], [False, True])
    else:
        momentum_grid = product([3, 6, 12], [0.006, 0.012, 0.02], [1.5, 2.5, 4.0], [3, 6, 12], [0.006, 0.01, 0.016], [1.2, 1.8, 2.5], [False, True])
        pullback_grid = product([6, 12, 24], [0.15, 0.25], [0.45, 0.65], [1.0, 1.5, 2.5], [6, 12, 18], [0.006, 0.01], [1.5, 2.2])
        breakout_grid = product([12, 24, 48], [0.012, 0.02, 0.035], [1.5, 2.5, 4.0], [3, 6, 12], [0.006, 0.01, 0.016], [1.2, 1.8, 2.5])
        failed_grid = product([3, 6, 12], [0.012, 0.02, 0.035], [0.25, 0.4], [1.5, 2.5, 4.0], [3, 6, 12], [0.006, 0.01, 0.016], [1.2, 1.8, 2.5], [False, True])
    for row in momentum_grid:
        if preset == "combo":
            lookback, min_ret, vol_mult, hold, sl, rr, oi_gate, sym_filter, btc_filter = row
        else:
            lookback, min_ret, vol_mult, hold, sl, rr, oi_gate = row
            sym_filter, btc_filter = "none", "none"
        out.append({
            "strategy": "surge_momentum",
            "lookback": lookback,
            "min_ret": min_ret,
            "vol_mult": vol_mult,
            "vol_lookback": 48,
            "breakout_lookback": 24,
            "hold": hold,
            "stop_pct": sl,
            "tp_pct": sl * rr,
            "require_oi_up": oi_gate,
            "min_oi_delta": 0.2,
            "symbol_filter": sym_filter,
            "btc_filter": btc_filter,
            "atr_min": 0.0015,
            "atr_max": 0.025,
        })
    for row in pullback_grid:
        if preset == "combo":
            impulse, retr_min, retr_max, vol_mult, hold, sl, rr, sym_filter, btc_filter = row
        else:
            impulse, retr_min, retr_max, vol_mult, hold, sl, rr = row
            sym_filter, btc_filter = "none", "none"
        out.append({
            "strategy": "surge_pullback",
            "impulse_lookback": impulse,
            "pullback_lookback": 6,
            "min_impulse": 0.015,
            "min_retrace": retr_min,
            "max_retrace": retr_max,
            "ma": 24,
            "vol_mult": vol_mult,
            "vol_lookback": 48,
            "hold": hold,
            "stop_pct": sl,
            "tp_pct": sl * rr,
            "symbol_filter": sym_filter,
            "btc_filter": btc_filter,
            "atr_min": 0.0015,
            "atr_max": 0.025,
        })
    for row in breakout_grid:
        if preset == "combo":
            range_lb, max_range, vol_mult, hold, sl, rr, sym_filter, btc_filter = row
        else:
            range_lb, max_range, vol_mult, hold, sl, rr = row
            sym_filter, btc_filter = "none", "none"
        out.append({
            "strategy": "volume_breakout",
            "range_lookback": range_lb,
            "max_range": max_range,
            "vol_mult": vol_mult,
            "vol_lookback": 48,
            "hold": hold,
            "stop_pct": sl,
            "tp_pct": sl * rr,
            "symbol_filter": sym_filter,
            "btc_filter": btc_filter,
            "atr_min": 0.0015,
            "atr_max": 0.025,
        })
    for row in failed_grid:
        if preset == "combo":
            lookback, min_ret, rejection, vol_mult, hold, sl, rr, oi_fade, sym_filter, btc_filter = row
        else:
            lookback, min_ret, rejection, vol_mult, hold, sl, rr, oi_fade = row
            sym_filter, btc_filter = "none", "none"
        out.append({
            "strategy": "failed_surge_short",
            "lookback": lookback,
            "min_ret": min_ret,
            "min_rejection": rejection,
            "max_close_pos": 0.45,
            "vol_mult": vol_mult,
            "vol_lookback": 48,
            "hold": hold,
            "stop_pct": sl,
            "tp_pct": sl * rr,
            "prefer_oi_fade": oi_fade,
            "max_oi_delta": 0.0,
            "symbol_filter": sym_filter,
            "btc_filter": btc_filter,
            "atr_min": 0.0015,
            "atr_max": 0.035,
        })
    return out


def run_config(bars_by_symbol: list[Bars], cfg: dict, cost_bps: float) -> list[Trade]:
    fn = SIGNAL_FNS[cfg["strategy"]]
    trades: list[Trade] = []
    btc = next((x for x in bars_by_symbol if x.symbol == "BTCUSDT"), None)
    for b in bars_by_symbol:
        last_exit = -1
        for i, side in fn(b, cfg):
            if i <= last_exit:
                continue
            if not passes_combo_filters(b, i, cfg, btc):
                continue
            t = exit_trade(
                b,
                i=i,
                side=side,
                hold=cfg["hold"],
                stop_pct=cfg["stop_pct"],
                tp_pct=cfg["tp_pct"],
                cost_bps=cost_bps,
                strategy=cfg["strategy"],
            )
            trades.append(t)
            last_exit = t.exit_i
    return trades


def summarize(trades: list[Trade], cfg: dict) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0, "score": -999999, "cfg": cfg}
    pnl = [t.pnl_bps for t in trades]
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss else 99.0
    avg = statistics.mean(pnl)
    med = statistics.median(pnl)
    downside = statistics.pstdev(losses) if len(losses) > 1 else max(abs(min(pnl)), 1.0)
    score = avg * min(math.log10(n + 1), 2.0) + min(pf, 5.0) * 4.0 - downside * 0.03
    fold_size = max(n // 4, 1)
    folds = []
    ordered = sorted(trades, key=lambda t: (t.symbol, t.entry_i))
    for k in range(4):
        part = ordered[k * fold_size : (k + 1) * fold_size if k < 3 else n]
        folds.append(round(sum(t.pnl_bps for t in part), 2))
    positive_folds = sum(1 for x in folds if x > 0)
    by_symbol = {}
    for t in trades:
        by_symbol.setdefault(t.symbol, []).append(t.pnl_bps)
    symbol_stats = [
        {"symbol": sym, "n": len(vals), "pnl_bps": round(sum(vals), 2), "avg_bps": round(statistics.mean(vals), 2)}
        for sym, vals in sorted(by_symbol.items())
    ]
    return {
        "strategy": cfg["strategy"],
        "n": n,
        "winrate": round(len(wins) / n, 4),
        "avg_bps": round(avg, 3),
        "median_bps": round(med, 3),
        "total_bps": round(sum(pnl), 2),
        "pf": round(pf, 3),
        "positive_folds": positive_folds,
        "fold_pnl_bps": folds,
        "score": round(score, 3),
        "cfg": cfg,
        "symbol_stats": sorted(symbol_stats, key=lambda x: x["pnl_bps"], reverse=True)[:12],
    }


def pick_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols:
        return [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    syms = []
    for path in DATA_DIR.glob("*/5m.json"):
        try:
            n = len(json.loads(path.read_text()))
        except Exception:
            continue
        if n >= args.min_bars:
            syms.append(path.parent.name)
    return sorted(syms)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="", help="Comma-separated symbols. Defaults to every local symbol with enough 5m bars.")
    ap.add_argument("--min-bars", type=int, default=8000)
    ap.add_argument("--cost-bps", type=float, default=24.0, help="Round-trip cost in bps.")
    ap.add_argument("--preset", choices=["coarse", "combo", "full"], default="coarse")
    ap.add_argument("--max-configs", type=int, default=0, help="Optional cap after grid generation.")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    bars = [b for s in pick_symbols(args) if (b := load_bars(s)) is not None]
    configs = cfg_grid(preset=args.preset)
    if args.max_configs > 0:
        configs = configs[: args.max_configs]
    results = []
    print(f"Bybit surge grid search | symbols={len(bars)} configs={len(configs)} cost={args.cost_bps}bps")
    for idx, cfg in enumerate(configs, 1):
        trades = run_config(bars, cfg, args.cost_bps)
        row = summarize(trades, cfg)
        if row["n"] >= 5:
            results.append(row)
        if idx % 200 == 0:
            print(f"  tested {idx}/{len(configs)} configs, kept={len(results)}", flush=True)
    results.sort(key=lambda r: (r["score"], r["positive_folds"], r["pf"], r["avg_bps"]), reverse=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "exchange": "bybit_public_linear_historical",
        "symbols": [b.symbol for b in bars],
        "symbol_count": len(bars),
        "config_count": len(configs),
        "cost_bps_roundtrip": args.cost_bps,
        "top": results[: args.top],
        "best_by_strategy": [],
    }
    for strategy in sorted(SIGNAL_FNS):
        rows = [r for r in results if r["strategy"] == strategy]
        if rows:
            payload["best_by_strategy"].append(rows[0])
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    print("\nTOP RESULTS")
    for rank, row in enumerate(results[: args.top], 1):
        cfg = row["cfg"]
        print(
            f"{rank:2d}. {row['strategy']:<20} score={row['score']:>7.2f} "
            f"n={row['n']:>4} wr={row['winrate']*100:>5.1f}% pf={row['pf']:>5.2f} "
            f"avg={row['avg_bps']:>7.2f}bps folds={row['positive_folds']}/4 "
            f"hold={cfg['hold']} sl={cfg['stop_pct']*100:.2f}% tp={cfg['tp_pct']*100:.2f}%"
        )
    print(f"\nSaved: {OUT_PATH}")


if __name__ == "__main__":
    main()
