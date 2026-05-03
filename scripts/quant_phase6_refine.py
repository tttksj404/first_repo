#!/usr/bin/env python3
"""Phase 6: Fine-grain refinement around the SAFE winner.

Winner: x1 / PEPE_DOGE / lv5 / mp0.5 / tp100 / sl-15 / h48 / lo=False

Sweep:
  - lev: 4, 5, 6, 7, 8
  - mp: 0.30, 0.40, 0.50, 0.60, 0.75
  - tp: 60, 80, 100, 120, 150
  - sl: -10, -12, -15, -18, -20
  - hold: 24, 36, 48, 60, 72
  - long_only: True/False

Total ~5*5*5*5*5*2 = 6250 configs, ~2 min.
Goal: find sweet-spot stability around the winner.
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
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase6_refine.jsonl"
LOG = ROOT / "quant_runtime" / "master_engine_runs" / "phase6_refine.log"


def emit(m):
    with open(LOG, "a") as f: f.write(m + "\n")
    print(m, flush=True)


def main():
    t0 = time.time()
    univ = "PEPE_DOGE"  # winner universe
    priority = PRIORITY_UNIVERSES[univ]
    cache = {}
    for s in priority:
        a = load_1h(s)
        if a is None: continue
        cache[s] = compute_indicators(a)
    n_bars = min(len(cache[s]["close"]) for s in cache)
    emit(f"[load] {len(cache)} syms × {n_bars} bars in {time.time()-t0:.1f}s")

    levs = [4, 5, 6, 7, 8]
    mps = [0.30, 0.40, 0.50, 0.60, 0.75]
    tps = [60, 80, 100, 120, 150]
    sls = [-10, -12, -15, -18, -20]
    holds = [24, 36, 48, 60, 72]
    los = [True, False]
    sig = "x1"

    configs = []
    for lev, mp, tp, sl, h, lo in itertools.product(levs, mps, tps, sls, holds, los):
        if tp < abs(sl): continue
        configs.append((lev, mp, tp, sl, h, lo))
    emit(f"[grid] {len(configs)} configs")

    fh = open(OUT, "w")
    n = 0
    for lev, mp, tp, sl, h, lo in configs:
        p = RotationParams(signal=sig, long_only=lo, lev=lev, margin_pct=mp,
                            tp_roe=tp, sl_roe=sl, abort_roe=min(sl - 5, -16),
                            hold_h=h, use_atr_exit=False)
        try:
            tr = rotation_backtest(priority, cache, p, idx_start=200, idx_end=n_bars)
        except Exception:
            continue
        agg = aggregate(tr)
        rec = {"sig": sig, "univ": univ, "lev": lev, "mp": mp,
               "tp": tp, "sl": sl, "hold": h, "long_only": lo, **agg}
        if agg["n"] >= 5:
            mc = mc_ruin(tr, n_runs=2000)
            rec.update({f"mc_{k}": v for k, v in mc.items()})
        fh.write(json.dumps(rec, default=str) + "\n")
        n += 1
        if n % 500 == 0:
            emit(f"[{n}/{len(configs)}] {n/(time.time()-t0):.1f}/s")
    fh.close()
    emit(f"[done] {n} configs in {time.time()-t0:.0f}s")

    # Quick safe top-30
    recs = []
    with open(OUT) as f:
        for ln in f:
            try: recs.append(json.loads(ln))
            except: pass
    safe = [r for r in recs if r.get("n", 0) >= 25
             and r.get("total_pnl", 0) > 30
             and (r.get("mc_ruin_pct") or 100) <= 5]
    safe.sort(key=lambda r: -r["total_pnl"])
    emit(f"\n[refine top-15 SAFE (n>=25, pnl>$30, ruin<=5%)] {len(safe)} matches")
    print(f"\n{'rank':>4s} {'lv':>3s} {'mp':>5s} {'tp':>4s} {'sl':>4s} {'h':>3s} {'lo':>2s} {'N':>4s} {'WR%':>5s} {'PF':>5s} {'PnL$':>8s} {'%/yr':>7s} {'maxDD':>7s} {'ruin%':>6s}")
    for i, r in enumerate(safe[:15], 1):
        pf = r.get("pf"); pf_s = f"{pf:.2f}" if isinstance(pf, (int, float)) else "-"
        print(f"  {i:>2d} {r['lev']:>3d} {r['mp']:>5.2f} {r['tp']:>4d} {r['sl']:>4d} {r['hold']:>3d} {int(r['long_only']):>2d} {r['n']:>4d} {r['wr']*100:>4.1f} {pf_s:>5s} ${r['total_pnl']:>+6.2f} {r['annual_pct']:>+6.1f} ${r['max_dd']:>5.2f} {r.get('mc_ruin_pct',0):>5.1f}")


if __name__ == "__main__":
    main()
