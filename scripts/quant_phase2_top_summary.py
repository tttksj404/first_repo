#!/usr/bin/env python3
"""Quick summary of Phase 2 coarse top winners."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "quant_runtime" / "master_engine_runs" / "phase2_coarse.jsonl"


def score(r):
    pnl = r.get("total_pnl", 0)
    if r.get("n", 0) < 10: return -1e9
    ruin = r.get("mc_ruin_pct", 50) or 50
    dd = r.get("max_dd", 0)
    return pnl * (1 - ruin / 100) - 0.1 * dd


recs = []
with open(SRC) as f:
    for ln in f:
        try:
            recs.append(json.loads(ln))
        except: pass

# Filter: n>=20, pnl>0, ruin<=20
sane = [r for r in recs if r.get("n", 0) >= 20 and r.get("total_pnl", 0) > 0
         and (r.get("mc_ruin_pct") is None or r.get("mc_ruin_pct", 100) <= 20)]
sane.sort(key=score, reverse=True)

print(f"Total recs: {len(recs)}, sane (n≥20 pnl>0 ruin≤20%): {len(sane)}")
print(f"\n{'rank':>4s} {'score':>7s} {'sig':<14s} {'univ':<22s} {'lev':>3s} {'mp':>4s} {'tp':>4s} {'sl':>4s} {'h':>3s} {'lo':>2s} {'N':>4s} {'WR%':>5s} {'PF':>5s} {'PnL$':>9s} {'%/yr':>7s} {'maxDD':>7s} {'ruin%':>6s}")
for i, r in enumerate(sane[:30], 1):
    pf = r.get("pf"); pf_s = f"{pf:.2f}" if isinstance(pf, (int, float)) else "-"
    print(f"  {i:>2d} {score(r):>7.1f} {r['sig']:<14s} {r['univ']:<22s} {r['lev']:>3d} {r['mp']:>4.2f} {r['tp']:>4d} {r['sl']:>4d} {r['hold']:>3d} {int(r['long_only']):>2d} {r['n']:>4d} {r['wr']*100:>4.1f} {pf_s:>5s} ${r['total_pnl']:>+7.2f} {r['annual_pct']:>+6.1f} ${r['max_dd']:>5.2f} {r.get('mc_ruin_pct',0):>5.1f}")

# Group analysis
from collections import Counter
sig_count = Counter(r["sig"] for r in sane[:100])
univ_count = Counter(r["univ"] for r in sane[:100])
lev_count = Counter(r["lev"] for r in sane[:100])
print(f"\nTop-100 signal distribution: {dict(sig_count)}")
print(f"Top-100 universe distribution: {dict(univ_count)}")
print(f"Top-100 lev distribution: {dict(sorted(lev_count.items()))}")
