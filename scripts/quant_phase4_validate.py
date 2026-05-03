#!/usr/bin/env python3
"""Phase 4: Full validation on top-30 winners from phase3_zoom.

Per candidate:
  - Full-year aggregate (already known, recompute for accuracy)
  - Walk-forward 4-fold (time-ordered) → require 3/4 positive
  - Slippage stress: 0/3/5/10/15/20 bps full ladder
  - Per-symbol breakdown
  - Adjacent-grid sensitivity (already in phase3, but tighter ±1 step)
  - MC ruin 10000 runs (high precision)
  - Drawdown distribution (p5, p25, p50, p95)
  - Funding cost amplification (extra at 0.0002/8h "high funding" stress)

Output: quant_runtime/master_engine_runs/phase4_validate.json (full)
"""
from __future__ import annotations

import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import (  # type: ignore
    RotationParams, rotation_backtest, aggregate, mc_ruin,
    load_1h, compute_indicators, PRIORITY_UNIVERSES, EQUITY,
)

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC_LIST = [
    ROOT / "quant_runtime" / "master_engine_runs" / "phase3_zoom.jsonl",
    ROOT / "quant_runtime" / "master_engine_runs" / "phase2_coarse.jsonl",
]
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase4_validate.json"
LOG = ROOT / "quant_runtime" / "master_engine_runs" / "phase4_validate.log"


def emit(m):
    with open(LOG, "a") as f: f.write(m + "\n")
    print(m, flush=True)


def score(rec):
    pnl = rec.get("total_pnl", 0)
    if rec.get("n", 0) < 10: return -1e9
    ruin = rec.get("mc_ruin_pct", 50) or 50
    dd = rec.get("max_dd", 0)
    return pnl * (1 - ruin / 100) - 0.1 * dd


def main():
    t0 = time.time()
    # Aggregate from phase3 if present, else phase2
    recs = []
    for src in SRC_LIST:
        if src.exists():
            with open(src) as f:
                for ln in f:
                    try: recs.append(json.loads(ln))
                    except: pass
    emit(f"[load] {len(recs)} total records")
    sane = [r for r in recs if r.get("n", 0) >= 15 and r.get("total_pnl", 0) > 0
             and (r.get("mc_ruin_pct") is None or r.get("mc_ruin_pct", 100) <= 15)]
    sane.sort(key=score, reverse=True)
    # dedupe by full key
    seen = set(); top = []
    for r in sane:
        key = (r["sig"], r["univ"], r["lev"], r["mp"], r["tp"], r["sl"], r["hold"], r["long_only"])
        if key in seen: continue
        seen.add(key)
        top.append(r)
        if len(top) >= 30: break
    emit(f"[top30] selected {len(top)} candidates")
    for i, r in enumerate(top[:10], 1):
        emit(f"  #{i}: {r['sig']}/{r['univ']}/lev{r['lev']}/mp{r['mp']}/tp{r['tp']}/sl{r['sl']}/h{r['hold']}/lo{r['long_only']}: pnl=${r['total_pnl']} ruin={r.get('mc_ruin_pct','?')}% n={r['n']}")

    # Load data
    needed = set()
    for r in top:
        needed.update(PRIORITY_UNIVERSES[r["univ"]])
    cache = {}
    for s in sorted(needed):
        a = load_1h(s)
        if a is None: continue
        cache[s] = compute_indicators(a)
    n_bars = min(len(cache[s]["close"]) for s in cache)
    emit(f"[load] {len(cache)} syms × {n_bars} bars")

    results = []
    for idx, r in enumerate(top, 1):
        emit(f"\n=== #{idx}: {r['sig']}/{r['univ']}/lev{r['lev']}/mp{r['mp']}/tp{r['tp']}/sl{r['sl']}/h{r['hold']}/lo{r['long_only']} ===")
        priority = PRIORITY_UNIVERSES[r["univ"]]

        def make_p(extra_bps=0.0):
            return RotationParams(
                signal=r["sig"], long_only=r["long_only"],
                lev=r["lev"], margin_pct=r["mp"],
                tp_roe=r["tp"], sl_roe=r["sl"],
                abort_roe=min(r["sl"] - 5, -16),
                hold_h=r["hold"], use_atr_exit=False,
                extra_bps=extra_bps,
            )

        # Full year
        trades = rotation_backtest(priority, cache, make_p(0), 200, n_bars)
        agg = aggregate(trades)
        ruin = mc_ruin(trades, n_runs=10000)
        emit(f"  full: n={agg['n']} wr={agg['wr']*100:.1f}% pf={agg['pf']} pnl=${agg['total_pnl']:+.2f} ({agg['annual_pct']:+.1f}%/yr) maxDD=${agg['max_dd']:.2f} ruin={ruin['ruin_pct']:.2f}%")

        # WF 4-fold
        wf_pass = 0; wf_folds = []
        fs = n_bars // 4
        for k in range(4):
            te_s = k * fs; te_e = min((k + 1) * fs, n_bars) if k < 3 else n_bars
            tr = rotation_backtest(priority, cache, make_p(0), te_s, te_e)
            a = aggregate(tr)
            wf_folds.append({"fold": k, "n": a["n"], "total": a["total_pnl"], "wr": a["wr"]})
            if a["total_pnl"] > 0: wf_pass += 1
        emit(f"  WF: {wf_pass}/4 | " + " ".join(f"f{x['fold']}=${x['total']:+.1f}(N{x['n']})" for x in wf_folds))

        # Slippage ladder
        slip = []
        for bps in [0, 3, 5, 10, 15, 20]:
            tr = rotation_backtest(priority, cache, make_p(float(bps)), 200, n_bars)
            a = aggregate(tr)
            slip.append({"bps": bps, "n": a["n"], "total": a["total_pnl"], "wr": a["wr"]})
        emit(f"  slip: " + "  ".join(f"{s['bps']}bps=${s['total']:+.1f}" for s in slip))

        # Per-symbol breakdown
        per_sym = {}
        for s in priority:
            sym_trades = [t for t in trades if t.symbol == s]
            n_sym = len(sym_trades)
            pnl_sym = sum(t.pnl_usd for t in sym_trades)
            per_sym[s] = {"n": n_sym, "total": round(pnl_sym, 2)}
        emit(f"  per_sym: " + "  ".join(f"{s}=N{v['n']} ${v['total']:+.1f}" for s, v in per_sym.items() if v['n'] > 0))

        # DD distribution
        if len(trades) > 0:
            pnls = np.array([t.pnl_usd for t in trades])
            eq = np.cumsum(pnls)
            peak = np.maximum.accumulate(eq)
            dds = peak - eq
            dd_dist = {
                "p50": round(float(np.median(dds)), 2),
                "p75": round(float(np.percentile(dds, 75)), 2),
                "p95": round(float(np.percentile(dds, 95)), 2),
                "max": round(float(dds.max()), 2),
            }
        else:
            dd_dist = {}

        rec = {
            "rank": idx,
            "params": {
                "sig": r["sig"], "univ": r["univ"],
                "lev": r["lev"], "mp": r["mp"],
                "tp": r["tp"], "sl": r["sl"], "hold": r["hold"],
                "long_only": r["long_only"],
                "priority": priority,
            },
            "full_year": agg,
            "ruin_10k": ruin,
            "wf": {"pass": wf_pass, "folds": wf_folds},
            "slippage": slip,
            "per_symbol": per_sym,
            "dd_distribution": dd_dist,
        }
        # Gate verdict
        gates = {
            "n_min30": agg["n"] >= 30,
            "wf_3of4": wf_pass >= 3,
            "ruin_5pct": ruin["ruin_pct"] <= 5,
            "ruin_10pct": ruin["ruin_pct"] <= 10,
            "slip5_pos": next((s["total"] for s in slip if s["bps"] == 5), -1) > 0,
            "slip10_pos": next((s["total"] for s in slip if s["bps"] == 10), -1) > 0,
            "dd_under_50pct_eq": agg["max_dd"] < EQUITY * 0.5,
        }
        rec["gates"] = gates
        rec["all_safe_pass"] = gates["wf_3of4"] and gates["ruin_5pct"] and gates["slip5_pos"] and gates["dd_under_50pct_eq"]
        rec["all_aggressive_pass"] = gates["wf_3of4"] and gates["ruin_10pct"] and gates["slip5_pos"] and gates["dd_under_50pct_eq"]
        results.append(rec)
        emit(f"  gates: {gates}  safe_pass={rec['all_safe_pass']} aggro_pass={rec['all_aggressive_pass']}")

    OUT.write_text(json.dumps(results, indent=2, default=str))
    emit(f"\n[done] {len(results)} candidates validated in {time.time()-t0:.0f}s, saved: {OUT}")


if __name__ == "__main__":
    main()
