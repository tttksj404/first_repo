#!/usr/bin/env python3
"""Search high-upside non-breakout Bitget futures paper candidates.

The deployed Oracle slots are breakout/CH1-like, so this script deliberately
tests different families:

- overreaction_reversal: buy dumps / short pumps after exhaustion
- trend_pullback: enter a pullback inside a 24h trend
- zscore_reversion: Bollinger-style mean reversion
- pair_spread_reversion: market-neutral relative-value spread

It uses local Bitget native 1h history and evaluates three time windows:
2024, 2025, and 2026-to-available. Output is a ranked JSON file.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(r"C:\Users\SSAFY\Desktop\first_repo")
HIST_CANDIDATES = [
    ROOT / "quant_runtime" / "historical_bitget",
    ROOT / "quant_runtime" / "historical_top50",
    ROOT / "quant_runtime" / "historical",
    ROOT / "quant_runtime" / "historical_2024",
    ROOT / "quant_runtime" / "historical_is25",
]
OUT = ROOT / "quant_binance" / "strategies" / "_scripts" / "g4700_nonbreakout_exhaustive_results.json"

COST_BPS = 24.0
EQUITY = 100.0

PERIODS = {
    "OOS24": (1704067200000, 1735689600000),
    "OOS25": (1735689600000, 1767225600000),
    "IS26": (1767225600000, 1798761600000),
}


def load_symbol(symbol: str) -> dict[str, np.ndarray] | None:
    path = None
    for root in HIST_CANDIDATES:
        candidate = root / symbol / "1h.json"
        if candidate.exists() and candidate.stat().st_size > 0:
            path = candidate
            break
    if path is None:
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if len(raw) < 1000:
        return None
    arr = {
        "ts": np.array([int(r["open_time"]) for r in raw], dtype=np.int64),
        "open": np.array([float(r["open_price"]) for r in raw], dtype=np.float64),
        "high": np.array([float(r["high_price"]) for r in raw], dtype=np.float64),
        "low": np.array([float(r["low_price"]) for r in raw], dtype=np.float64),
        "close": np.array([float(r["close_price"]) for r in raw], dtype=np.float64),
        "vol": np.array([float(r.get("base_volume", 0.0)) for r in raw], dtype=np.float64),
    }
    return arr


def ema(x: np.ndarray, period: int) -> np.ndarray:
    out = np.empty_like(x, dtype=np.float64)
    out[0] = x[0]
    a = 2.0 / (period + 1.0)
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def rolling_mean(x: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < period:
        return out
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[period - 1 :] = (c[period:] - c[:-period]) / period
    return out


def rolling_std(x: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < period:
        return out
    mean = rolling_mean(x, period)
    mean2 = rolling_mean(x * x, period)
    var = np.maximum(mean2 - mean * mean, 0.0)
    out = np.sqrt(var)
    return out


def indicators(arr: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    close = arr["close"]
    high = arr["high"]
    low = arr["low"]
    vol = arr["vol"]
    ret = np.zeros_like(close)
    ret[1:] = close[1:] / close[:-1] - 1.0
    ret_3 = np.zeros_like(close)
    ret_6 = np.zeros_like(close)
    ret_24 = np.zeros_like(close)
    ret_72 = np.zeros_like(close)
    for h, target in [(3, ret_3), (6, ret_6), (24, ret_24), (72, ret_72)]:
        target[h:] = close[h:] / close[:-h] - 1.0
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    atr = ema(tr, 14)
    atr_pct = atr / close
    vol_ma = rolling_mean(vol, 24)
    vol_ratio = np.where(vol_ma > 0, vol / vol_ma, 1.0)
    ma = rolling_mean(close, 48)
    sd = rolling_std(close, 48)
    z = np.where(sd > 0, (close - ma) / sd, 0.0)
    ema20 = ema(close, 20)
    ema50 = ema(close, 50)
    return {
        **arr,
        "ret_1h": ret,
        "ret_3h": ret_3,
        "ret_6h": ret_6,
        "ret_24h": ret_24,
        "ret_72h": ret_72,
        "atr_pct": atr_pct,
        "vol_ratio": vol_ratio,
        "z48": z,
        "ema20": ema20,
        "ema50": ema50,
    }


@dataclass
class Trade:
    ts: int
    symbol: str
    side: str
    engine: str
    pnl_usd: float
    ret_bps: float
    liquidated: bool
    exit_reason: str


def exit_trade(
    d: dict[str, np.ndarray],
    idx: int,
    side: int,
    hold: int,
    tp: float,
    sl: float,
    lev: float,
    size: float,
    engine: str,
) -> Trade | None:
    entry_idx = idx + 1
    if entry_idx + 1 >= len(d["close"]):
        return None
    end = min(entry_idx + hold, len(d["close"]) - 1)
    entry = d["close"][entry_idx]
    if entry <= 0:
        return None
    tp_px = entry * (1 + tp) if side > 0 else entry * (1 - tp)
    sl_px = entry * (1 - sl) if side > 0 else entry * (1 + sl)
    exit_px = d["close"][end]
    reason = "time"
    liquidated = False
    for j in range(entry_idx + 1, end + 1):
        hi = d["high"][j]
        lo = d["low"][j]
        hit_tp = hi >= tp_px if side > 0 else lo <= tp_px
        hit_sl = lo <= sl_px if side > 0 else hi >= sl_px
        adverse = (lo / entry - 1.0) if side > 0 else (entry / hi - 1.0)
        if adverse * lev <= -0.92:
            liquidated = True
            exit_px = entry * (1 - 0.92 / lev) if side > 0 else entry * (1 + 0.92 / lev)
            reason = "liquidation"
            break
        if hit_sl and hit_tp:
            exit_px = sl_px
            reason = "sl"
            break
        if hit_sl:
            exit_px = sl_px
            reason = "sl"
            break
        if hit_tp:
            exit_px = tp_px
            reason = "tp"
            break
    raw = (exit_px / entry - 1.0) * side
    net = raw - COST_BPS / 10000.0
    pnl = EQUITY * size * lev * net
    return Trade(
        ts=int(d["ts"][entry_idx]),
        symbol=str(d["symbol"]),
        side="long" if side > 0 else "short",
        engine=engine,
        pnl_usd=float(pnl),
        ret_bps=float(net * 10000.0),
        liquidated=liquidated,
        exit_reason=reason,
    )


def summarize(trades: list[Trade], days: float) -> dict[str, Any]:
    if not trades:
        return {
            "n": 0,
            "wr": 0.0,
            "pnl_usd": 0.0,
            "annual_pnl_usd": 0.0,
            "monthly_pnl_usd": 0.0,
            "max_dd_usd": 0.0,
            "liquidations": 0,
            "liq_rate": 0.0,
        }
    pnl = np.array([t.pnl_usd for t in trades], dtype=np.float64)
    eq = EQUITY + np.cumsum(pnl)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    n = len(trades)
    total = float(pnl.sum())
    return {
        "n": n,
        "wr": float((pnl > 0).mean()),
        "pnl_usd": round(total, 2),
        "annual_pnl_usd": round(total * 365.0 / max(days, 1.0), 2),
        "monthly_pnl_usd": round(total * 30.0 / max(days, 1.0), 2),
        "max_dd_usd": round(float(dd.max(initial=0.0)), 2),
        "liquidations": int(sum(1 for t in trades if t.liquidated)),
        "liq_rate": round(sum(1 for t in trades if t.liquidated) / n, 4),
        "long_n": int(sum(1 for t in trades if t.side == "long")),
        "short_n": int(sum(1 for t in trades if t.side == "short")),
        "exit_reasons": {k: int(sum(1 for t in trades if t.exit_reason == k)) for k in sorted({t.exit_reason for t in trades})},
    }


def nonoverlap_key(t: Trade) -> tuple[str, int, str, str]:
    return (t.symbol, int(t.ts // 86_400_000), t.side, t.engine)


def evaluate_events(spec: dict[str, Any], data: dict[str, dict[str, np.ndarray]]) -> dict[str, Any]:
    trades: list[Trade] = []
    for sym in spec["symbols"]:
        d = data[sym]
        engine = spec["engine"]
        valid = np.zeros(len(d["close"]), dtype=bool)
        valid[80 : max(80, len(d["close"]) - spec["hold"] - 2)] = True
        valid &= d["ts"] >= PERIODS["OOS24"][0]
        if engine == "overreaction_reversal":
            common = valid & (d["vol_ratio"] >= spec["vol_ratio"]) & (d["atr_pct"] >= spec["atr_min"])
            long_mask = common & (d["ret_6h"] <= -spec["move_6h"])
            short_mask = common & (d["ret_6h"] >= spec["move_6h"]) if spec["both_sides"] else np.zeros_like(common)
        elif engine == "trend_pullback":
            long_mask = valid & (d["ret_24h"] >= spec["trend_24h"]) & (d["ret_3h"] <= -spec["pullback_3h"]) & (d["ema20"] >= d["ema50"])
            short_mask = valid & (d["ret_24h"] <= -spec["trend_24h"]) & (d["ret_3h"] >= spec["pullback_3h"]) & (d["ema20"] <= d["ema50"]) if spec["both_sides"] else np.zeros_like(long_mask)
        elif engine == "zscore_reversion":
            common = valid & (np.abs(d["ret_24h"]) >= spec["move_24h"]) & (d["vol_ratio"] >= spec["vol_ratio"])
            long_mask = common & (d["z48"] <= -spec["z"])
            short_mask = common & (d["z48"] >= spec["z"]) if spec["both_sides"] else np.zeros_like(common)
        else:
            continue
        events: list[tuple[int, int]] = [(int(i), 1) for i in np.where(long_mask)[0]]
        events.extend((int(i), -1) for i in np.where(short_mask)[0])
        events.sort(key=lambda x: x[0])
        next_allowed = -1
        for idx, side in events:
            if idx < next_allowed:
                continue
            trade = exit_trade(d, idx, side, spec["hold"], spec["tp"], spec["sl"], spec["lev"], spec["size"], engine)
            if trade:
                trades.append(trade)
                next_allowed = idx + spec["cooldown"]
    return score_spec(spec, trades)


def pair_spread(spec: dict[str, Any], data: dict[str, dict[str, np.ndarray]]) -> dict[str, Any]:
    a, b = spec["pair"]
    da, db = data[a], data[b]
    n = min(len(da["close"]), len(db["close"]))
    spread = np.log(da["close"][:n]) - spec["beta"] * np.log(db["close"][:n])
    ma = rolling_mean(spread, spec["lookback"])
    sd = rolling_std(spread, spec["lookback"])
    z = np.where(sd > 0, (spread - ma) / sd, 0.0)
    trades: list[Trade] = []
    idx = spec["lookback"] + 5
    while idx < n - spec["hold"] - 2:
        side = 0
        if z[idx] >= spec["z"]:
            side = -1
        elif z[idx] <= -spec["z"]:
            side = 1
        if not side:
            idx += 1
            continue
        e = idx + 1
        x = min(e + spec["hold"], n - 1)
        # side=1 means long a, short b. side=-1 means short a, long b.
        ra = (da["close"][x] / da["close"][e] - 1.0) * side
        rb = (db["close"][x] / db["close"][e] - 1.0) * -side
        net = (ra + rb) * 0.5 - COST_BPS / 10000.0
        pnl = EQUITY * spec["size"] * spec["lev"] * net
        adverse = min(ra, rb)
        liq = adverse * spec["lev"] <= -0.92
        trades.append(
            Trade(
                ts=int(da["ts"][e]),
                symbol=f"{a}/{b}",
                side="long_spread" if side > 0 else "short_spread",
                engine="pair_spread_reversion",
                pnl_usd=float(pnl),
                ret_bps=float(net * 10000),
                liquidated=liq,
                exit_reason="time",
            )
        )
        idx += spec["cooldown"]
    return score_spec(spec, trades)


def score_spec(spec: dict[str, Any], trades: list[Trade]) -> dict[str, Any]:
    periods: dict[str, Any] = {}
    all_keys = set()
    for name, (start, end) in PERIODS.items():
        pt = [t for t in trades if start <= t.ts < end]
        periods[name] = summarize(pt, (end - start) / 86_400_000)
        all_keys.update(nonoverlap_key(t) for t in pt)
    weighted = summarize([t for t in trades if t.ts >= PERIODS["OOS24"][0]], 850)
    pvals = list(periods.values())
    allpos = all(p["pnl_usd"] > 0 for p in pvals)
    min_ann = min((p["annual_pnl_usd"] for p in pvals), default=0)
    max_dd = max((p["max_dd_usd"] for p in pvals), default=0)
    liq = sum(p["liquidations"] for p in pvals)
    n = sum(p["n"] for p in pvals)
    wr = sum(p["wr"] * p["n"] for p in pvals) / max(n, 1)
    annual = sum(p["annual_pnl_usd"] for p in pvals) / max(len(pvals), 1)
    score = annual + min_ann * 0.55 + wr * 80.0 - max_dd * 0.35 - liq * 100.0
    return {
        "id": spec["id"],
        "family": spec["engine"],
        "spec": spec,
        "periods": periods,
        "weighted": weighted,
        "checks": {
            "n_>=_40": n >= 40,
            "wr_>=_55": wr >= 0.55,
            "avg_annual_>=_150": annual >= 150,
            "min_period_annual_>_0": min_ann > 0,
            "all_periods_positive": allpos,
            "liq_==_0": liq == 0,
            "max_dd_<=_120": max_dd <= 120,
        },
        "score": round(score, 4),
        "keys": sorted(list(all_keys))[:2000],
    }


def main() -> int:
    data: dict[str, dict[str, np.ndarray]] = {}
    symbols: set[str] = set()
    for root in HIST_CANDIDATES:
        if root.exists():
            symbols.update(p.name for p in root.iterdir() if p.is_dir())
    for sym in sorted(symbols):
        loaded = load_symbol(sym)
        if loaded:
            ind = indicators(loaded)
            ind["symbol"] = sym
            data[sym] = ind

    majors = [s for s in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT", "WIFUSDT", "PEPEUSDT"] if s in data]
    alts = [s for s in majors if s not in {"BTCUSDT", "ETHUSDT"}]

    specs: list[dict[str, Any]] = []
    gid = 4700
    for move, volr, hold, tp, sl, lev, size in product(
        [0.025, 0.04, 0.06, 0.08, 0.12],
        [1.2, 1.8, 2.5],
        [3, 6, 12],
        [0.015, 0.03, 0.05, 0.08],
        [0.012, 0.025, 0.045],
        [5, 8, 12],
        [0.2, 0.35],
    ):
        if tp < sl * 0.6:
            continue
        specs.append({"id": f"G{gid}", "engine": "overreaction_reversal", "symbols": alts, "move_6h": move, "vol_ratio": volr, "atr_min": 0.0, "both_sides": True, "hold": hold, "tp": tp, "sl": sl, "lev": lev, "size": size, "cooldown": hold})
        gid += 1
    for trend, pull, hold, tp, sl, lev, size in product(
        [0.04, 0.07, 0.10, 0.14],
        [0.01, 0.025, 0.045],
        [6, 12, 24],
        [0.02, 0.05, 0.09],
        [0.015, 0.035, 0.07],
        [5, 8, 12],
        [0.2, 0.35],
    ):
        specs.append({"id": f"G{gid}", "engine": "trend_pullback", "symbols": majors, "trend_24h": trend, "pullback_3h": pull, "both_sides": True, "hold": hold, "tp": tp, "sl": sl, "lev": lev, "size": size, "cooldown": hold})
        gid += 1
    for z, move, volr, hold, tp, sl, lev, size in product(
        [1.5, 2.0, 2.5, 3.0],
        [0.03, 0.06, 0.10],
        [1.0, 1.6, 2.2],
        [3, 6, 12],
        [0.012, 0.03, 0.05],
        [0.012, 0.025, 0.045],
        [5, 8, 12],
        [0.2, 0.35],
    ):
        specs.append({"id": f"G{gid}", "engine": "zscore_reversion", "symbols": alts, "z": z, "move_24h": move, "vol_ratio": volr, "both_sides": True, "hold": hold, "tp": tp, "sl": sl, "lev": lev, "size": size, "cooldown": hold})
        gid += 1

    results = []
    for i, spec in enumerate(specs, 1):
        results.append(evaluate_events(spec, data))
        if i % 1000 == 0:
            print(f"event specs {i}/{len(specs)}", flush=True)

    pairs = [(a, b) for a, b in [("ETHUSDT", "BTCUSDT"), ("SOLUSDT", "ETHUSDT"), ("DOGEUSDT", "SOLUSDT"), ("SUIUSDT", "SOLUSDT"), ("WIFUSDT", "DOGEUSDT"), ("PEPEUSDT", "DOGEUSDT")] if a in data and b in data]
    for pair, lb, z, hold, lev, size in product(pairs, [48, 96, 168, 336], [1.5, 2.0, 2.5, 3.0], [6, 12, 24, 48], [2, 3, 5], [0.2, 0.3, 0.4]):
        spec = {"id": f"G{gid}", "engine": "pair_spread_reversion", "pair": pair, "beta": 1.0, "lookback": lb, "z": z, "hold": hold, "lev": lev, "size": size, "cooldown": hold}
        results.append(pair_spread(spec, data))
        gid += 1

    for r in results:
        r.pop("keys", None)
    results.sort(key=lambda r: (sum(1 for v in r["checks"].values() if v), r["score"], r["weighted"]["annual_pnl_usd"]), reverse=True)
    strict = [r for r in results if all(r["checks"].values())]
    near = [r for r in results if sum(1 for v in r["checks"].values() if v) >= 5]
    payload = {
        "generated_at": "2026-05-06",
        "question": "Best high-upside non-breakout Bitget futures paper candidate for Oracle third slot",
        "cost_bps": COST_BPS,
        "equity": EQUITY,
        "n_specs": len(results),
        "n_strict": len(strict),
        "top_strict": strict[:25],
        "top_near": near[:50],
        "top_overall": results[:100],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(OUT), "n_specs": len(results), "n_strict": len(strict), "top": results[:5]}, ensure_ascii=False, indent=2)[:20000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
