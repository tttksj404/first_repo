#!/usr/bin/env python3
"""Phase 2-COARSE: tight broad grid (~3-5 min) to map profitable regions.

After this completes, top-100 winners go to phase3_zoom.
"""
from __future__ import annotations

import itertools, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import (  # type: ignore
    RotationParams, rotation_backtest, aggregate, mc_ruin,
    load_1h, compute_indicators, PRIORITY_UNIVERSES,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase2_coarse.jsonl"
LOG = ROOT / "quant_runtime" / "master_engine_runs" / "phase2_coarse.log"
PROG = ROOT / "quant_runtime" / "master_engine_runs" / "phase2_coarse_progress.json"
OUT.parent.mkdir(parents=True, exist_ok=True)


def emit(m):
    with open(LOG, "a") as f:
        f.write(m + "\n")
    print(m, flush=True)


def main():
    t0 = time.time()
    all_syms = set()
    for u in PRIORITY_UNIVERSES.values():
        all_syms.update(u)
    cache = {}
    for s in sorted(all_syms):
        a = load_1h(s)
        if a is None:
            continue
        cache[s] = compute_indicators(a)
    n_bars = min(len(cache[s]["close"]) for s in cache)
    emit(f"[load] {len(cache)} syms × {n_bars} bars in {time.time()-t0:.1f}s")

    # Coarse grid — ~5000 configs
    signals = ["x1", "momentum", "atr_breakout", "combined", "turnaround"]
    universes = list(PRIORITY_UNIVERSES.keys())
    levs = [5, 10, 15, 20, 30]
    margins = [0.35, 0.5, 1.0]
    tps = [25, 50, 100]
    sls = [-8, -10, -15]
    holds = [24, 48]
    long_onlys = [True, False]

    configs = []
    for sig, univ, lev, mp, tp, sl, h, lo in itertools.product(
        signals, universes, levs, margins, tps, sls, holds, long_onlys
    ):
        if sig == "turnaround" and not lo:
            continue
        # Skip degenerate: TP smaller than abs(SL) when lev big (negative EV)
        if tp < abs(sl):
            continue
        configs.append((sig, univ, lev, mp, tp, sl, h, lo))
    emit(f"[grid] {len(configs)} configs")

    fh = open(OUT, "w")
    n = 0
    for sig, univ, lev, mp, tp, sl, h, lo in configs:
        priority = PRIORITY_UNIVERSES[univ]
        if not all(s in cache for s in priority):
            continue
        p = RotationParams(signal=sig, long_only=lo, lev=lev, margin_pct=mp,
                            tp_roe=tp, sl_roe=sl, abort_roe=min(sl - 5, -16),
                            hold_h=h, use_atr_exit=False)
        try:
            tr = rotation_backtest(priority, cache, p, idx_start=200, idx_end=n_bars)
        except Exception as ex:
            emit(f"[err] {sig}/{univ}: {ex}")
            continue
        agg = aggregate(tr)
        rec = {"sig": sig, "univ": univ, "lev": lev, "mp": mp,
               "tp": tp, "sl": sl, "hold": h, "long_only": lo, **agg}
        if agg["n"] >= 5:
            mc = mc_ruin(tr, n_runs=1500)
            rec.update({f"mc_{k}": v for k, v in mc.items()})
        fh.write(json.dumps(rec, default=str) + "\n")
        n += 1
        if n % 250 == 0:
            elapsed = time.time() - t0
            rate = n / elapsed
            eta = (len(configs) - n) / rate if rate > 0 else 0
            PROG.write_text(json.dumps({"completed": n, "total": len(configs),
                                         "elapsed_s": round(elapsed, 1),
                                         "rate": round(rate, 2),
                                         "eta_s": round(eta, 1)}, indent=2))
            emit(f"[{n}/{len(configs)}] rate={rate:.1f}/s ETA={eta/60:.1f}min")
    fh.close()
    PROG.write_text(json.dumps({"completed": n, "total": len(configs),
                                 "elapsed_s": round(time.time()-t0, 1),
                                 "finished": True}, indent=2))
    emit(f"[done] {n} configs in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
