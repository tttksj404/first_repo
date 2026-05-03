#!/usr/bin/env python3
"""Phase GG: latency-robust strategy tagging.

Phase AA generated delay 0/1/2/3 PnL per strategy.
Tag each strategy with delay-tier:
  ROBUST   = d=1 net > 0 AND d=2 net > -50% of d=0  (entry up to 2h late OK)
  ACCEPTABLE = d=1 net > 0 (entry up to 1h late OK)
  FRAGILE  = d=1 net <= 0  (must hit within 5 min or skip)

Output: delay tier per strategy + recommendation.
"""
from __future__ import annotations
import json
from pathlib import Path

p = Path("quant_runtime/output/auto4h/phaseAA_latency.json")
data = json.loads(p.read_text())["results"]

print(f"{'sid':<20} {'side':<5} {'d=0':>7} {'d=1':>7} {'d=2':>7} {'d=3':>7}  TIER")
out = []
for r in data:
    sid = r["sid"]; side = r["side"]
    d0, d1, d2, d3 = (r["delays"][i]["net"] for i in range(4))
    if d1 > 0 and d2 > 0.5*d0:
        tier = "ROBUST"
    elif d1 > 0:
        tier = "ACCEPTABLE"
    else:
        tier = "FRAGILE"
    out.append({"sid": sid, "side": side, "d0": d0, "d1": d1, "d2": d2, "d3": d3, "tier": tier})
    print(f"{sid:<20} {side:<5} ${d0:>+5.0f} ${d1:>+5.0f} ${d2:>+5.0f} ${d3:>+5.0f}  {tier}")

print(f"\n=== Summary ===")
n_rob = sum(1 for o in out if o["tier"]=="ROBUST")
n_acc = sum(1 for o in out if o["tier"]=="ACCEPTABLE")
n_frg = sum(1 for o in out if o["tier"]=="FRAGILE")
print(f"  ROBUST:     {n_rob:>2} (entry up to 2h late OK — relaxed watchdog)")
print(f"  ACCEPTABLE: {n_acc:>2} (entry up to 1h late OK — current 5-min watchdog)")
print(f"  FRAGILE:    {n_frg:>2} (must enter <5 min — strict watchdog)")

print(f"\n=== ROBUST strategies (live-priority) ===")
for o in out:
    if o["tier"]=="ROBUST":
        print(f"  {o['sid']:<20} {o['side']}")

print(f"\n=== FRAGILE strategies (require strict latency) ===")
for o in out:
    if o["tier"]=="FRAGILE":
        print(f"  {o['sid']:<20} {o['side']}  (d=1 net=${o['d1']:+.0f})")

out_path = Path("quant_runtime/output/auto4h/phaseGG_delay_tier.json")
out_path.write_text(json.dumps({"results": out, "n_robust": n_rob,
                                "n_acceptable": n_acc, "n_fragile": n_frg}, indent=2))
print(f"\n[saved] {out_path}")
