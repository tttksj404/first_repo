#!/usr/bin/env python3
"""Phase 5: Final report + winner selection.

Reads phase4_validate.json → produce ranked deploy recommendations:
  - Tier S (safe): all_safe_pass=True, ruin<5%, WF 4/4
  - Tier A (aggressive): all_aggressive_pass=True, ruin<10%
  - Tier B (high-risk reward): high return but ruin 10-25%

Output: quant_runtime/master_engine_runs/final_winner_report.json + console table
"""
from __future__ import annotations

import json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "quant_runtime" / "master_engine_runs" / "phase4_validate.json"
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "final_winner_report.json"


def main():
    if not SRC.exists():
        print(f"[err] {SRC} missing"); return
    cands = json.loads(SRC.read_text())
    print(f"\n{'='*120}")
    print(f"FINAL WINNER REPORT — {len(cands)} validated candidates")
    print(f"{'='*120}\n")

    safe = [c for c in cands if c["all_safe_pass"]]
    aggro = [c for c in cands if c["all_aggressive_pass"] and not c["all_safe_pass"]]
    high_risk = [c for c in cands if not c["all_aggressive_pass"]
                  and c["ruin_10k"]["ruin_pct"] <= 25
                  and c["wf"]["pass"] >= 3]
    fail = [c for c in cands if c not in safe and c not in aggro and c not in high_risk]

    # Sort tiers by total_pnl
    safe.sort(key=lambda c: -c["full_year"]["total_pnl"])
    aggro.sort(key=lambda c: -c["full_year"]["total_pnl"])
    high_risk.sort(key=lambda c: -c["full_year"]["total_pnl"])

    def show(label, lst, n=10):
        if not lst:
            print(f"\n[{label}] (none)\n")
            return
        print(f"\n[{label}] {len(lst)} candidates — top {min(n, len(lst))}:")
        print(f"  {'rank':>4s} {'strategy':<55s} {'N':>4s} {'WR':>5s} {'PF':>5s} {'PnL$':>9s} {'%/yr':>8s} {'maxDD':>7s} {'ruin%':>6s} {'WF':>4s} {'slip5':>7s}")
        for c in lst[:n]:
            p = c["params"]
            sig = f"{p['sig']}/{p['univ'][:14]}/lv{p['lev']}/mp{p['mp']:.2f}/tp{p['tp']}/sl{p['sl']}/h{p['hold']}/lo{int(p['long_only'])}"
            fy = c["full_year"]
            ruin = c["ruin_10k"]["ruin_pct"]
            wf = f"{c['wf']['pass']}/4"
            slip5 = next((s["total"] for s in c["slippage"] if s["bps"] == 5), 0)
            pf = fy["pf"] if fy["pf"] is not None else "-"
            print(f"  #{c['rank']:>3d} {sig:<55s} {fy['n']:>4d} {fy['wr']*100:>4.1f}% {pf!s:>5s} ${fy['total_pnl']:>+7.2f} {fy['annual_pct']:>+7.1f}% ${fy['max_dd']:>5.2f} {ruin:>5.1f}% {wf:>4s} ${slip5:>+5.1f}")

    show("S - SAFE (ruin≤5%, all gates pass)", safe, 15)
    show("A - AGGRESSIVE (ruin≤10%)", aggro, 15)
    show("B - HIGH-RISK (ruin≤25%, WF≥3/4)", high_risk, 10)
    print(f"\n[FAIL] {len(fail)} candidates didn't qualify")

    # Recommendations
    print(f"\n{'='*120}")
    print("DEPLOY RECOMMENDATIONS")
    print(f"{'='*120}")
    if safe:
        c = safe[0]; p = c["params"]
        print(f"\n>>> PRIMARY (safe): #{c['rank']}")
        print(f"    signal={p['sig']}, universe={p['priority']}")
        print(f"    lev={p['lev']}x, margin_pct={p['mp']:.2f} (margin=${50*p['mp']:.2f}, notional=${50*p['mp']*p['lev']:.2f})")
        print(f"    TP={p['tp']}% ROE, SL={p['sl']}% ROE, hold={p['hold']}h, long_only={p['long_only']}")
        print(f"    Expected: ${c['full_year']['total_pnl']:+.2f}/yr ({c['full_year']['annual_pct']:+.1f}%/yr on $50)")
        print(f"    Risk: maxDD ${c['full_year']['max_dd']:.2f}, ruin {c['ruin_10k']['ruin_pct']:.1f}%, WF {c['wf']['pass']}/4")
    if aggro:
        c = aggro[0]; p = c["params"]
        print(f"\n>>> AGGRESSIVE: #{c['rank']}")
        print(f"    signal={p['sig']}, universe={p['priority']}")
        print(f"    lev={p['lev']}x, margin_pct={p['mp']:.2f}, TP={p['tp']}%, SL={p['sl']}%, hold={p['hold']}h")
        print(f"    Expected: ${c['full_year']['total_pnl']:+.2f}/yr ({c['full_year']['annual_pct']:+.1f}%/yr)")
        print(f"    Risk: maxDD ${c['full_year']['max_dd']:.2f}, ruin {c['ruin_10k']['ruin_pct']:.1f}%")
    if high_risk:
        c = high_risk[0]; p = c["params"]
        print(f"\n>>> HIGH-REWARD/HIGH-RISK: #{c['rank']}")
        print(f"    signal={p['sig']}, universe={p['priority']}, lev{p['lev']}, TP{p['tp']} SL{p['sl']}")
        print(f"    Expected: {c['full_year']['annual_pct']:+.1f}%/yr  Risk: ruin {c['ruin_10k']['ruin_pct']:.1f}%")

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_candidates": len(cands),
        "tier_S_safe": safe,
        "tier_A_aggressive": aggro,
        "tier_B_high_risk": high_risk,
        "tier_F_fail_count": len(fail),
    }
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nSaved: {OUT}")


if __name__ == "__main__":
    main()
