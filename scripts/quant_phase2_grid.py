#!/usr/bin/env python3
"""Phase 2: Massive grid search via rotation engine.

Grid:
  signal     : x1, x4, momentum, atr_breakout, combined, turnaround
  universe   : rotation_30x_orig, memes_first, wide_basket, alt_first, PEPE_DOGE, memes_alts, majors_first, PEPE_only
  lev        : 3, 5, 10, 15, 20, 25, 30, 40
  margin_pct : 0.35, 0.50, 0.75, 1.0
  tp_roe     : 15, 25, 35, 50, 80, 120
  sl_roe     : -5, -8, -10, -15
  abort_roe  : -16, -25
  hold_h     : 24, 48, 72
  long_only  : True, False

Saves each batch incrementally to JSON. Designed to run in background.

Output: quant_runtime/master_engine_runs/phase2_grid.jsonl  (one JSON per line)
        quant_runtime/master_engine_runs/phase2_grid_progress.json
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import (  # type: ignore
    RotationParams, rotation_backtest, aggregate, mc_ruin,
    load_1h, compute_indicators, PRIORITY_UNIVERSES,
)

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "quant_runtime" / "master_engine_runs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
JSONL = OUT_DIR / "phase2_grid.jsonl"
PROG = OUT_DIR / "phase2_grid_progress.json"
LOG = OUT_DIR / "phase2_grid.log"


def emit(msg: str):
    with open(LOG, "a") as f:
        f.write(msg + "\n")
    print(msg, flush=True)


def main():
    t0 = time.time()
    # Load all symbols that appear in any universe
    all_syms = set()
    for u in PRIORITY_UNIVERSES.values():
        all_syms.update(u)
    data_cache = {}
    for s in sorted(all_syms):
        a = load_1h(s)
        if a is None:
            emit(f"[skip] {s}: data missing")
            continue
        data_cache[s] = compute_indicators(a)
    emit(f"[load] {len(data_cache)} symbols × indicators in {time.time()-t0:.1f}s")
    n_bars = min(len(data_cache[s]["close"]) for s in data_cache)
    emit(f"[load] common bars = {n_bars}")

    # ===== Grid =====
    signals = ["x1", "x4", "momentum", "atr_breakout", "combined", "turnaround"]
    universes = ["rotation_30x_orig", "memes_first", "memes_alts", "wide_basket",
                  "alt_first", "PEPE_DOGE", "majors_first", "PEPE_only", "DOGE_first", "ETH_first"]
    levs = [3, 5, 10, 15, 20, 25, 30, 40]
    margin_pcts = [0.35, 0.5, 0.75, 1.0]
    tp_roes = [15, 25, 35, 50, 80, 120]
    sl_roes = [-5, -8, -10, -15]
    abort_roes = [-16, -25]
    hold_hs = [24, 48, 72]
    long_only_opts = [True, False]

    # Restrict turnaround to long_only=True
    # Skip dumb combinations: tp_roe < |sl_roe| (no positive expectancy possible without high WR)

    all_configs = []
    for sig, univ, lev, mp, tp, sl, ab, hh, lo in itertools.product(
        signals, universes, levs, margin_pcts, tp_roes, sl_roes, abort_roes, hold_hs, long_only_opts
    ):
        if sig == "turnaround" and not lo:
            continue
        if sig == "x4" and lo:
            # x4 short side often valuable; don't double up
            pass
        # Filter trivially bad: TP < |SL| AND lev high (won't pay off)
        if tp < abs(sl) and lev >= 20:
            continue
        # Skip when abort >= sl (abort must be deeper than sl)
        if ab > sl:
            continue
        # PEPE_only with ETH-first signals → meaningless variety; keep
        all_configs.append((sig, univ, lev, mp, tp, sl, ab, hh, lo))

    emit(f"[grid] total configs = {len(all_configs)}")
    PROG.write_text(json.dumps({"total_configs": len(all_configs), "completed": 0,
                                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))

    # Resume support: count existing jsonl lines
    completed = 0
    if JSONL.exists():
        with open(JSONL) as f:
            completed = sum(1 for _ in f)
        emit(f"[resume] {completed} configs already done, skipping")
    else:
        JSONL.touch()

    out_handle = open(JSONL, "a")

    # Backtest loop
    n_done = completed
    n_skip_data = 0
    qualifying = []  # quick filter: total_pnl > 0 AND ruin_quick < 30%
    for idx, (sig, univ, lev, mp, tp, sl, ab, hh, lo) in enumerate(all_configs):
        if idx < completed:
            continue
        priority = PRIORITY_UNIVERSES[univ]
        if not all(s in data_cache for s in priority):
            n_skip_data += 1
            n_done += 1
            continue
        p = RotationParams(
            signal=sig, long_only=lo, lev=lev, margin_pct=mp,
            tp_roe=tp, sl_roe=sl, abort_roe=ab, hold_h=hh,
            use_atr_exit=False, extra_bps=0.0,
        )
        try:
            trades = rotation_backtest(priority, data_cache, p, idx_start=200, idx_end=n_bars)
        except Exception as ex:
            emit(f"[err] {sig}/{univ}/lev{lev}/mp{mp}/tp{tp}/sl{sl}/h{hh}/lo{lo}: {ex}")
            n_done += 1
            continue
        agg = aggregate(trades)
        if agg["n"] < 5:
            # too few trades; record but skip MC
            rec = {
                "sig": sig, "univ": univ, "lev": lev, "mp": mp,
                "tp": tp, "sl": sl, "abort": ab, "hold": hh, "long_only": lo,
                **agg, "ruin_pct": None, "p5_min_eq": None,
            }
        else:
            ruin = mc_ruin(trades, n_runs=2000)  # quick MC; refine top winners later
            rec = {
                "sig": sig, "univ": univ, "lev": lev, "mp": mp,
                "tp": tp, "sl": sl, "abort": ab, "hold": hh, "long_only": lo,
                **agg, **{f"mc_{k}": v for k, v in ruin.items()},
            }
            if agg["total_pnl"] > 0 and ruin["ruin_pct"] < 30:
                qualifying.append(rec)
        out_handle.write(json.dumps(rec, default=str) + "\n")
        out_handle.flush()
        n_done += 1
        if n_done % 100 == 0:
            elapsed = time.time() - t0
            rate = n_done / elapsed
            eta = (len(all_configs) - n_done) / rate if rate > 0 else 0
            PROG.write_text(json.dumps({
                "total_configs": len(all_configs),
                "completed": n_done,
                "qualifying_so_far": len(qualifying),
                "elapsed_s": round(elapsed, 1),
                "rate_per_s": round(rate, 2),
                "eta_s": round(eta, 1),
                "last_update": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }, indent=2))
            emit(f"[prog] {n_done}/{len(all_configs)} done, qual={len(qualifying)}, rate={rate:.1f}/s, ETA {eta/60:.1f}min")

    out_handle.close()
    PROG.write_text(json.dumps({
        "total_configs": len(all_configs),
        "completed": n_done,
        "qualifying_total": len(qualifying),
        "elapsed_s": round(time.time() - t0, 1),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, indent=2))
    emit(f"[done] {n_done} configs in {time.time()-t0:.1f}s. Qualifying: {len(qualifying)}.")


if __name__ == "__main__":
    main()
