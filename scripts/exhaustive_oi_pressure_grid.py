#!/usr/bin/env python3
"""Exhaustive finite grid for the third Oracle OI-pressure candidate.

The goal is not a pretty experiment; it is to close a specific search space and
make the "best candidate" claim evidence-backed:

- OI-pressure continuation
- OI deleveraging reversal
- crowded OI fade
- multiple lookback windows, thresholds, exits, leverage, and symbol subsets
"""
from __future__ import annotations

import json
import sys
from itertools import combinations, product
from pathlib import Path
from typing import Any

import numpy as np

import search_oi_pressure_oracle_candidates as base

OUT = base.ROOT / "quant_binance" / "strategies" / "_scripts" / "g4702_oi_pressure_exhaustive_grid.json"

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


def _ensure_windows(d: dict[str, np.ndarray], windows: list[int]) -> None:
    oi = d["oi"]
    close = d["close"]
    for h in windows:
        if f"oi_{h}h" not in d:
            r = np.full_like(oi, np.nan)
            valid = (oi[h:] > 0) & (oi[:-h] > 0)
            r[h:][valid] = oi[h:][valid] / oi[:-h][valid] - 1.0
            d[f"oi_{h}h"] = r
        if f"ret_{h}h" not in d:
            r = np.zeros_like(close)
            r[h:] = close[h:] / close[:-h] - 1.0
            d[f"ret_{h}h"] = r


def _load() -> dict[str, dict[str, np.ndarray]]:
    price_data: dict[str, dict[str, np.ndarray]] = {}
    for sym in sorted(set(base.ALT_SYMBOLS + base.OI_SYMBOLS)):
        p = base._load_price(sym)
        if p is not None:
            price_data[sym] = base.enrich_price(p)
    oi_data: dict[str, dict[str, np.ndarray]] = {}
    for sym in base.OI_SYMBOLS:
        oi = base._load_oi(sym)
        if oi and sym in price_data:
            d = base.attach_oi(price_data[sym], oi)
            _ensure_windows(d, WINDOWS)
            oi_data[sym] = d
    return oi_data


def _symbol_subsets(symbols: list[str]) -> list[list[str]]:
    if "--all-symbols-only" in sys.argv:
        return [list(symbols)]
    subsets: list[list[str]] = []
    for n in range(2, len(symbols) + 1):
        for combo in combinations(symbols, n):
            subsets.append(list(combo))
    return subsets


def _passes_basic(r: dict[str, Any]) -> bool:
    return (
        r["weighted"]["n"] >= 40
        and r["weighted"]["liquidations"] == 0
        and r["all_periods_positive"]
        and r["weighted"]["max_dd_usd"] <= 140.0
    )


def _rank_key(r: dict[str, Any]) -> list[float]:
    checks = r["checks"]
    return [
        -int(checks["liq_zero"]),
        -int(r["all_periods_positive"]),
        -int(checks["maxdd_le_120"]),
        -r["weighted"]["annual_pnl_usd"],
        -r["weighted"]["pnl_usd"],
        r["weighted"]["max_dd_usd"],
        -r["weighted"]["n"],
    ]


def main() -> int:
    oi_data = _load()
    symbols = list(oi_data)
    subsets = _symbol_subsets(symbols)
    total = (
        len(ENGINES)
        * len(subsets)
        * len(WINDOWS)
        * len(PRICE_MOVES)
        * len(OI_MOVES)
        * len(VOL_RATIOS)
        * len(HOLDS)
        * len(TPS)
        * len(SLS)
        * len(LEVS)
    )
    print(f"loaded={symbols} subsets={len(subsets)} total_specs={total}", flush=True)

    top: list[dict[str, Any]] = []
    strict: list[dict[str, Any]] = []
    n = 0
    gid = 9000
    for engine, subset, window, price_move, oi_move, volr, hold, tp, sl, lev in product(
        ENGINES, subsets, WINDOWS, PRICE_MOVES, OI_MOVES, VOL_RATIOS, HOLDS, TPS, SLS, LEVS
    ):
        n += 1
        if tp < sl * 0.6:
            continue
        spec = {
            "id": f"G{gid}",
            "engine": engine,
            "symbols": subset,
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
        r = base.evaluate_own(spec, oi_data)
        if _passes_basic(r):
            r.pop("keys", None)
            if all(r["checks"].values()):
                strict.append(r)
                strict = sorted(strict, key=_rank_key)[:200]
            top.append(r)
            top = sorted(top, key=_rank_key)[:300]
        if n % 5000 == 0:
            best = top[0]["weighted"]["annual_pnl_usd"] if top else None
            print(f"progress {n}/{total} top_annual={best} strict={len(strict)}", flush=True)

    top = sorted(top, key=_rank_key)
    strict = sorted(strict, key=_rank_key)
    payload = {
        "search_space": {
            "engines": ENGINES,
            "symbols": symbols,
            "subsets": len(subsets),
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
        "n_basic_pass_retained": len(top),
        "n_strict_retained": len(strict),
        "strict": strict[:100],
        "top": top[:100],
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)
    if top:
        for r in top[:10]:
            print(r["id"], r["engine"], r["weighted"], r["periods"], r["spec"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
