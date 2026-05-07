#!/usr/bin/env python3
"""Fast exhaustive grid for all-symbol OI-pressure candidates."""
from __future__ import annotations

import json
from functools import lru_cache
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np

import search_oi_pressure_oracle_candidates as base

OUT = base.ROOT / "quant_binance" / "strategies" / "_scripts" / "g4703_fast_oi_pressure_grid.json"

WINDOWS = [3, 6, 12, 24]
PRICE_MOVES = [0.02, 0.03, 0.04, 0.05, 0.065, 0.08, 0.10, 0.12]
OI_MOVES = [0.01, 0.015, 0.02, 0.03, 0.04, 0.055, 0.07, 0.09]
VOL_RATIOS = [0.8, 1.0, 1.4]
HOLDS = [6, 9, 12, 18, 24]
TPS = [0.04, 0.06, 0.08, 0.10, 0.12, 0.15]
SLS = [0.015, 0.025, 0.035, 0.05, 0.07]
LEVS = [5, 8, 10, 12]
SIZE = 0.35
ENGINES = ["oi_pressure_continuation", "oi_deleveraging_reversal", "oi_crowded_fade"]
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]

REASON = {1: "sl", 2: "tp", 3: "time", 4: "liquidation"}


def _ensure_windows(d: dict[str, np.ndarray]) -> None:
    close = d["close"]
    oi = d["oi"]
    for h in WINDOWS:
        if f"ret_{h}h" not in d:
            r = np.zeros_like(close)
            r[h:] = close[h:] / close[:-h] - 1.0
            d[f"ret_{h}h"] = r
        if f"oi_{h}h" not in d:
            r = np.full_like(oi, np.nan)
            valid = (oi[h:] > 0) & (oi[:-h] > 0)
            r[h:][valid] = oi[h:][valid] / oi[:-h][valid] - 1.0
            d[f"oi_{h}h"] = r


def load_data() -> dict[str, dict[str, np.ndarray]]:
    price_data = {}
    for sym in SYMBOLS:
        p = base._load_price(sym)
        if p is None:
            raise RuntimeError(f"missing price {sym}")
        price_data[sym] = base.enrich_price(p)
    out = {}
    for sym in SYMBOLS:
        oi = base._load_oi(sym)
        if not oi:
            raise RuntimeError(f"missing oi {sym}")
        d = base.attach_oi(price_data[sym], oi)
        _ensure_windows(d)
        out[sym] = d
    return out


DATA = load_data()


def cooldown(idxs: np.ndarray, gap: int) -> np.ndarray:
    if len(idxs) == 0:
        return idxs
    kept = []
    last = -10**9
    for x in idxs:
        xi = int(x)
        if xi - last >= gap:
            kept.append(xi)
            last = xi
    return np.array(kept, dtype=np.int64)


@lru_cache(maxsize=None)
def outcomes(sym: str, side: int, hold: int, tp: float, sl: float, lev: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    d = DATA[sym]
    n = len(d["close"])
    pnl = np.full(n, np.nan, dtype=np.float64)
    liq = np.zeros(n, dtype=bool)
    reason = np.zeros(n, dtype=np.int8)
    max_idx = n - hold - 2
    if max_idx <= 1:
        return pnl, liq, reason
    idx = np.arange(0, max_idx, dtype=np.int64)
    entry_idx = idx + 1
    entry = d["close"][entry_idx]
    exit_px = d["close"][entry_idx + hold].copy()
    r = np.full(len(idx), 3, dtype=np.int8)
    open_mask = entry > 0
    tp_px = np.where(side > 0, entry * (1.0 + tp), entry * (1.0 - tp))
    sl_px = np.where(side > 0, entry * (1.0 - sl), entry * (1.0 + sl))
    for off in range(1, hold + 1):
        active = open_mask & (r == 3)
        if not active.any():
            break
        hi = d["high"][entry_idx + off]
        lo = d["low"][entry_idx + off]
        if side > 0:
            hit_tp = hi >= tp_px
            hit_sl = lo <= sl_px
            adverse = lo / entry - 1.0
            liq_px = entry * (1.0 - 0.92 / lev)
        else:
            hit_tp = lo <= tp_px
            hit_sl = hi >= sl_px
            adverse = entry / hi - 1.0
            liq_px = entry * (1.0 + 0.92 / lev)
        hit_liq = adverse * lev <= -0.92
        both = hit_sl & hit_tp
        m = active & hit_liq
        exit_px[m] = liq_px[m]
        r[m] = 4
        liq[idx[m]] = True
        m = active & (r == 3) & both
        exit_px[m] = sl_px[m]
        r[m] = 1
        m = active & (r == 3) & hit_sl
        exit_px[m] = sl_px[m]
        r[m] = 1
        m = active & (r == 3) & hit_tp
        exit_px[m] = tp_px[m]
        r[m] = 2
    raw = (exit_px / entry - 1.0) * side
    net = raw - base.COST_BPS / 10000.0
    pnl[idx] = base.EQUITY * SIZE * lev * net
    reason[idx] = r
    return pnl, liq, reason


@lru_cache(maxsize=None)
def event_indices(sym: str, engine: str, window: int, price_move: float, oi_move: float, volr: float, hold: int) -> tuple[np.ndarray, np.ndarray]:
    d = DATA[sym]
    valid = np.zeros(len(d["close"]), dtype=bool)
    valid[80 : max(80, len(d["close"]) - hold - 2)] = True
    valid &= (d["ts"] >= base.PERIODS["OOS25_OI"][0]) & np.isfinite(d[f"oi_{window}h"])
    ret = d[f"ret_{window}h"]
    oi = d[f"oi_{window}h"]
    if engine == "oi_pressure_continuation":
        common = valid & (np.abs(ret) >= price_move) & (oi >= oi_move) & (d["vol_ratio"] >= volr)
        long_mask = common & (ret > 0)
        short_mask = common & (ret < 0)
    elif engine == "oi_deleveraging_reversal":
        common = valid & (np.abs(ret) >= price_move) & (oi <= -oi_move) & (d["vol_ratio"] >= volr)
        long_mask = common & (ret < 0)
        short_mask = common & (ret > 0)
    else:
        common = valid & (np.abs(ret) >= price_move) & (oi >= oi_move) & (d["vol_ratio"] >= volr)
        long_mask = common & (ret < 0)
        short_mask = common & (ret > 0)
    return cooldown(np.flatnonzero(long_mask), hold), cooldown(np.flatnonzero(short_mask), hold)


def summarize(ts: np.ndarray, pnl: np.ndarray, liq: np.ndarray, side: np.ndarray, reason: np.ndarray, start: int, end: int) -> dict[str, Any]:
    m = (ts >= start) & (ts < end)
    if not m.any():
        return {"n": 0, "wr": 0.0, "pnl_usd": 0.0, "annual_pnl_usd": 0.0, "monthly_pnl_usd": 0.0, "max_dd_usd": 0.0, "liquidations": 0, "liq_rate": 0.0}
    order = np.argsort(ts[m])
    p = pnl[m][order]
    l = liq[m][order]
    s = side[m][order]
    rr = reason[m][order]
    eq = base.EQUITY + np.cumsum(p)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    days = (end - start) / 86400000.0
    total = float(p.sum())
    n = len(p)
    return {
        "n": int(n),
        "wr": float((p > 0).mean()),
        "pnl_usd": round(total, 2),
        "annual_pnl_usd": round(total * 365.0 / max(days, 1.0), 2),
        "monthly_pnl_usd": round(total * 30.0 / max(days, 1.0), 2),
        "max_dd_usd": round(float(dd.max(initial=0.0)), 2),
        "liquidations": int(l.sum()),
        "liq_rate": round(float(l.mean()), 4),
        "long_n": int((s > 0).sum()),
        "short_n": int((s < 0).sum()),
        "exit_reasons": {REASON[k]: int((rr == k).sum()) for k in sorted(set(int(x) for x in rr)) if k in REASON},
    }


def evaluate(spec: dict[str, Any]) -> dict[str, Any]:
    ts_parts = []
    pnl_parts = []
    liq_parts = []
    side_parts = []
    reason_parts = []
    for sym in SYMBOLS:
        d = DATA[sym]
        long_idx, short_idx = event_indices(sym, spec["engine"], spec["window"], spec["price_move"], spec["oi_move"], spec["vol_ratio"], spec["hold"])
        for side_value, idxs in [(1, long_idx), (-1, short_idx)]:
            if len(idxs) == 0:
                continue
            p, l, rr = outcomes(sym, side_value, spec["hold"], spec["tp"], spec["sl"], spec["lev"])
            good = np.isfinite(p[idxs])
            idxs = idxs[good]
            if len(idxs) == 0:
                continue
            ts_parts.append(d["ts"][idxs + 1])
            pnl_parts.append(p[idxs])
            liq_parts.append(l[idxs])
            side_parts.append(np.full(len(idxs), side_value, dtype=np.int8))
            reason_parts.append(rr[idxs])
    if not ts_parts:
        periods = {name: summarize(np.array([], dtype=np.int64), np.array([]), np.array([], dtype=bool), np.array([], dtype=np.int8), np.array([], dtype=np.int8), start, end) for name, (start, end) in base.PERIODS.items()}
        weighted = periods["OOS25_OI"]
    else:
        ts = np.concatenate(ts_parts)
        pnl = np.concatenate(pnl_parts)
        liq = np.concatenate(liq_parts)
        side = np.concatenate(side_parts)
        reason = np.concatenate(reason_parts)
        periods = {name: summarize(ts, pnl, liq, side, reason, start, end) for name, (start, end) in base.PERIODS.items()}
        start = min(v[0] for v in base.PERIODS.values())
        end = max(v[1] for v in base.PERIODS.values())
        weighted = summarize(ts, pnl, liq, side, reason, start, end)
    checks = {
        "n_ge_40": weighted["n"] >= 40,
        "annual_ge_150": weighted["annual_pnl_usd"] >= 150.0,
        "min_period_positive": all(p["pnl_usd"] > 0 for p in periods.values()),
        "liq_zero": weighted["liquidations"] == 0,
        "maxdd_le_120": weighted["max_dd_usd"] <= 120.0,
    }
    return {
        "id": spec["id"],
        "engine": spec["engine"],
        "spec": spec,
        "periods": periods,
        "weighted": weighted,
        "all_periods_positive": all(p["pnl_usd"] > 0 for p in periods.values()),
        "checks": checks,
    }


def rank_key(r: dict[str, Any]) -> list[float]:
    return [
        -int(r["checks"]["liq_zero"]),
        -int(r["all_periods_positive"]),
        -int(r["checks"]["maxdd_le_120"]),
        -r["weighted"]["annual_pnl_usd"],
        -r["weighted"]["pnl_usd"],
        r["weighted"]["max_dd_usd"],
        -r["weighted"]["n"],
    ]


def main() -> int:
    total = len(ENGINES) * len(WINDOWS) * len(PRICE_MOVES) * len(OI_MOVES) * len(VOL_RATIOS) * len(HOLDS) * len(TPS) * len(SLS) * len(LEVS)
    print(f"total_specs={total}", flush=True)
    top: list[dict[str, Any]] = []
    strict: list[dict[str, Any]] = []
    gid = 10000
    n = 0
    for engine, window, price_move, oi_move, volr, hold, tp, sl, lev in product(ENGINES, WINDOWS, PRICE_MOVES, OI_MOVES, VOL_RATIOS, HOLDS, TPS, SLS, LEVS):
        n += 1
        if tp < sl * 0.6:
            continue
        spec = {
            "id": f"G{gid}",
            "engine": engine,
            "symbols": SYMBOLS,
            "window": window,
            "price_move": price_move,
            "oi_move": oi_move,
            "oi_drop": oi_move,
            "vol_ratio": volr,
            "hold": hold,
            "tp": tp,
            "sl": sl,
            "lev": lev,
            "size": SIZE,
            "cooldown": hold,
        }
        gid += 1
        r = evaluate(spec)
        if r["weighted"]["n"] >= 40 and r["weighted"]["liquidations"] == 0 and r["all_periods_positive"]:
            top.append(r)
            top = sorted(top, key=rank_key)[:300]
            if all(r["checks"].values()):
                strict.append(r)
                strict = sorted(strict, key=rank_key)[:300]
        if n % 5000 == 0:
            best = top[0]["weighted"]["annual_pnl_usd"] if top else None
            print(f"progress={n}/{total} best={best} strict={len(strict)}", flush=True)
    top = sorted(top, key=rank_key)
    strict = sorted(strict, key=rank_key)
    payload = {
        "search_space": {
            "engines": ENGINES,
            "symbols": SYMBOLS,
            "windows": WINDOWS,
            "price_moves": PRICE_MOVES,
            "oi_moves": OI_MOVES,
            "vol_ratios": VOL_RATIOS,
            "holds": HOLDS,
            "take_profits": TPS,
            "stop_losses": SLS,
            "leverages": LEVS,
            "size": SIZE,
            "total_specs": total,
        },
        "n_checked": n,
        "n_top_retained": len(top),
        "n_strict_retained": len(strict),
        "strict": strict[:100],
        "top": top[:100],
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)
    for r in top[:10]:
        print(r["id"], r["engine"], r["weighted"], r["periods"], r["spec"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
