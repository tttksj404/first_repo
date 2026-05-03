#!/usr/bin/env python3
"""Phase 3: Zoom on top winners from phase2_coarse.

Read phase2_coarse.jsonl → rank → take top 100 → for each, expand neighborhood:
  - lev: ±5 (or nearest in {3, 5, 7, 10, 12, 15, 18, 20, 25, 30, 35, 40})
  - margin: ±0.15 (clip 0.2..1.0)
  - tp: ±15 (clip 10..200)
  - sl: ±3 (clip -25..-3)
  - hold: try ±12 (12, 24, 48, 72, 96)

Run finer MC (3000 runs).
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
SRC = ROOT / "quant_runtime" / "master_engine_runs" / "phase2_coarse.jsonl"
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase3_zoom.jsonl"
LOG = ROOT / "quant_runtime" / "master_engine_runs" / "phase3_zoom.log"
PROG = ROOT / "quant_runtime" / "master_engine_runs" / "phase3_zoom_progress.json"


def emit(m):
    with open(LOG, "a") as f: f.write(m + "\n")
    print(m, flush=True)


def score(rec):
    """Composite score: PnL × (1 - ruin/100) - 0.1 × maxDD."""
    pnl = rec.get("total_pnl", 0)
    if rec.get("n", 0) < 10:
        return -1e9
    ruin = rec.get("mc_ruin_pct", 50)  # default to penalty if missing
    if ruin is None:
        ruin = 50
    dd = rec.get("max_dd", 0)
    return pnl * (1 - ruin / 100) - 0.1 * dd


def neighbors(rec):
    """Generate neighbor configs around a winner."""
    sig = rec["sig"]; univ = rec["univ"]
    lev0 = rec["lev"]; mp0 = rec["mp"]
    tp0 = rec["tp"]; sl0 = rec["sl"]; h0 = rec["hold"]
    lo = rec["long_only"]
    # Lev neighbors
    lev_grid = sorted({max(2, lev0 - 5), max(3, lev0 - 3), lev0, lev0 + 3, lev0 + 5, min(50, lev0 + 10)})
    # Margin neighbors (clip 0.2..1.0)
    mp_grid = sorted({round(max(0.2, mp0 - 0.15), 2), mp0, round(min(1.0, mp0 + 0.15), 2)})
    # TP neighbors
    tp_grid = sorted({max(10, tp0 - 25), max(15, tp0 - 15), tp0, tp0 + 15, tp0 + 30, min(250, tp0 + 50)})
    # SL neighbors
    sl_grid = sorted({max(-25, sl0 - 5), max(-20, sl0 - 3), sl0, min(-3, sl0 + 3), min(-3, sl0 + 5)})
    # Hold neighbors
    h_grid = sorted({max(8, h0 - 24), max(12, h0 - 12), h0, h0 + 12, h0 + 24, min(168, h0 + 48)})
    out = []
    for lev, mp, tp, sl, h in itertools.product(lev_grid, mp_grid, tp_grid, sl_grid, h_grid):
        if tp < abs(sl):
            continue
        out.append((sig, univ, lev, mp, tp, sl, h, lo))
    return out


def main():
    t0 = time.time()
    if not SRC.exists():
        emit(f"[err] phase2 source missing: {SRC}")
        return
    recs = []
    with open(SRC) as f:
        for ln in f:
            try:
                recs.append(json.loads(ln))
            except Exception:
                pass
    emit(f"[load] {len(recs)} phase2 records")
    # Filter sane: n>=10, total_pnl>0
    sane = [r for r in recs if r.get("n", 0) >= 10 and r.get("total_pnl", 0) > 0]
    emit(f"[filter] {len(sane)} have n>=10 & pnl>0")
    sane.sort(key=score, reverse=True)
    top = sane[:100]
    emit(f"[top100] best score={score(top[0]):.2f}, worst score={score(top[-1]):.2f}")
    emit(f"  best: {top[0]['sig']}/{top[0]['univ']}/lev{top[0]['lev']}/tp{top[0]['tp']}/sl{top[0]['sl']}/h{top[0]['hold']} pnl=${top[0]['total_pnl']} ruin={top[0].get('mc_ruin_pct')}")

    # Load data
    syms_needed = set()
    for r in top:
        syms_needed.update(PRIORITY_UNIVERSES[r["univ"]])
    cache = {}
    for s in sorted(syms_needed):
        a = load_1h(s)
        if a is None: continue
        cache[s] = compute_indicators(a)
    n_bars = min(len(cache[s]["close"]) for s in cache)
    emit(f"[load] {len(cache)} syms × {n_bars} bars")

    # Generate neighbor set, dedupe
    seen = set()
    pending = []
    for r in top:
        for cfg in neighbors(r):
            key = cfg
            if key in seen: continue
            seen.add(key)
            pending.append(cfg)
    emit(f"[neighbors] {len(pending)} unique configs to test")

    fh = open(OUT, "w")
    n = 0
    for sig, univ, lev, mp, tp, sl, h, lo in pending:
        priority = PRIORITY_UNIVERSES[univ]
        if not all(s in cache for s in priority): continue
        p = RotationParams(signal=sig, long_only=lo, lev=lev, margin_pct=mp,
                            tp_roe=tp, sl_roe=sl, abort_roe=min(sl - 5, -16),
                            hold_h=h, use_atr_exit=False)
        try:
            tr = rotation_backtest(priority, cache, p, idx_start=200, idx_end=n_bars)
        except Exception as ex:
            continue
        agg = aggregate(tr)
        rec = {"sig": sig, "univ": univ, "lev": lev, "mp": mp,
               "tp": tp, "sl": sl, "hold": h, "long_only": lo, **agg}
        if agg["n"] >= 5:
            mc = mc_ruin(tr, n_runs=3000)
            rec.update({f"mc_{k}": v for k, v in mc.items()})
        fh.write(json.dumps(rec, default=str) + "\n")
        n += 1
        if n % 200 == 0:
            elapsed = time.time() - t0
            rate = n / elapsed
            eta = (len(pending) - n) / rate if rate > 0 else 0
            PROG.write_text(json.dumps({"completed": n, "total": len(pending),
                                         "elapsed_s": round(elapsed, 1),
                                         "rate": round(rate, 2),
                                         "eta_s": round(eta, 1)}, indent=2))
            emit(f"[{n}/{len(pending)}] rate={rate:.1f}/s ETA={eta/60:.1f}min")
    fh.close()
    PROG.write_text(json.dumps({"completed": n, "total": len(pending),
                                 "elapsed_s": round(time.time()-t0, 1),
                                 "finished": True}, indent=2))
    emit(f"[done] {n} configs in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
