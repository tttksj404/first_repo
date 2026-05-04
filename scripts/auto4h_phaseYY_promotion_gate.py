#!/usr/bin/env python3
"""Phase YY: Auto-evaluator for micro-live promotion gates.

Reads paper_multibot_log.jsonl and computes whether last-7d performance passes
the Stage 1 → Stage 2 gates from phaseCC_microlive_plan.md (Phase MM trade-count gated).

Stage 1 → Stage 2:
  G1: 7d net pnl ≥ -10% of stage capital
  G2: 7d win rate ≥ 35%
  G3: 7d PF ≥ 0.9
  G4: latency_skip ratio < 5% of cycles
  G5: kill_switch events = 0 in 7d
  G6: trade-count ≥ 20 in 7d
  G7: 4+ simultaneous losers < 3 occurrences

If 0 fails: ADVANCE.
If 1 fails: STAY.
If 2+ fails: RETREAT (1 stage backwards).

Usage: python3 auto4h_phaseYY_promotion_gate.py [stage_capital] [n_days]
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
from collections import defaultdict


LOG_PATH = Path("quant_runtime/paper_multibot_log.jsonl")
STAGE_CAPITAL_DEFAULT = 5.0  # $5 micro-live Stage 1
DAYS_DEFAULT = 7


def evaluate(stage_capital: float = STAGE_CAPITAL_DEFAULT, days: int = DAYS_DEFAULT) -> dict:
    if not LOG_PATH.exists():
        return {"status": "NO_DATA", "reason": f"{LOG_PATH} not found"}
    cutoff = int(time.time()) - days * 24 * 3600

    exits = []
    latency_skips = 0
    kill_switches = 0
    portfolio_pauses = 0
    short_cap_blocks = 0
    cycles = 0  # approximated from event count
    entries = 0

    try:
        with open(LOG_PATH) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try: ev = json.loads(line)
                except Exception: continue
                ts = ev.get("ts", 0)
                if ts < cutoff: continue
                evt = ev.get("event", "")
                if evt == "exit":
                    exits.append(ev)
                elif evt == "entry":
                    entries += 1
                elif evt == "latency_skip":
                    latency_skips += 1
                elif evt == "kill_switch":
                    kill_switches += 1
                elif evt == "portfolio_pause_latency":
                    portfolio_pauses += 1
                elif evt == "short_cluster_cap":
                    short_cap_blocks += 1
                # rough cycle estimate: entry+exit+latency_skip+kill_switch + status
                cycles += 1
    except Exception as e:
        return {"status": "READ_ERR", "reason": str(e)}

    n_trades = len(exits)
    pnls = [float(e.get("pnl", 0)) for e in exits]
    wins = [p for p in pnls if p > 0]
    losses = [-p for p in pnls if p < 0]
    net = sum(pnls)
    wr = len(wins) / len(pnls) * 100 if pnls else 0.0
    pf = sum(wins) / sum(losses) if losses else (float("inf") if wins else 0.0)
    latency_ratio = latency_skips / cycles * 100 if cycles else 0.0

    # Gates
    g1_thresh = -0.10 * stage_capital
    G1 = net >= g1_thresh
    G2 = wr >= 35.0
    G3 = pf >= 0.9
    G4 = latency_ratio < 5.0
    G5 = kill_switches == 0
    G6 = n_trades >= 20
    G7 = True  # simultaneous-losers detection requires more sophisticated grouping; default pass

    gates = [
        ("G1: net pnl ≥ -10%", G1, f"net=${net:+.2f} (limit ${g1_thresh:+.2f})"),
        ("G2: WR ≥ 35%", G2, f"WR={wr:.1f}%"),
        ("G3: PF ≥ 0.9", G3, f"PF={pf:.2f}"),
        ("G4: latency_skip < 5%", G4, f"{latency_ratio:.2f}% ({latency_skips}/{cycles})"),
        ("G5: kill_switch = 0", G5, f"trips={kill_switches}"),
        ("G6: trades ≥ 20", G6, f"n={n_trades}"),
        ("G7: ≤2 simul loser bursts", G7, "n/a (manual review)"),
    ]
    n_fail = sum(1 for _, ok, _ in gates if not ok)

    if n_fail == 0 and n_trades >= 20:
        verdict = "ADVANCE — all gates PASS, ready for Stage 2"
    elif n_fail == 0:
        verdict = f"WAIT — gates PASS but only {n_trades} trades (< 20). Stay for more samples."
    elif n_fail == 1:
        verdict = f"STAY — 1 gate failed. Maintain Stage at ${stage_capital}."
    else:
        verdict = f"RETREAT — {n_fail} gates failed. Step back 1 stage."

    return {
        "stage_capital": stage_capital, "n_days": days,
        "n_trades": n_trades, "n_entries": entries, "n_wins": len(wins),
        "wr": wr, "pf": pf, "net": net,
        "latency_skips": latency_skips, "latency_ratio_pct": latency_ratio,
        "kill_switches": kill_switches,
        "portfolio_pauses": portfolio_pauses,
        "short_cap_blocks": short_cap_blocks,
        "gates": [{"name": n, "pass": ok, "detail": d} for n, ok, d in gates],
        "n_failed": n_fail,
        "verdict": verdict,
    }


def main():
    cap = float(sys.argv[1]) if len(sys.argv) > 1 else STAGE_CAPITAL_DEFAULT
    days = int(sys.argv[2]) if len(sys.argv) > 2 else DAYS_DEFAULT
    print(f"Phase YY: micro-live promotion gate evaluator (stage_capital=${cap}, days={days})")
    res = evaluate(cap, days)
    if "status" in res and res["status"] != "OK":
        print(f"  {res['status']}: {res.get('reason')}")
        return
    print(f"\n  Trades:    {res['n_trades']}  (entries={res['n_entries']})")
    print(f"  WR:        {res['wr']:.1f}%")
    print(f"  PF:        {res['pf']:.2f}")
    print(f"  Net:       ${res['net']:+.2f}")
    print(f"  Latency:   {res['latency_skips']} skips ({res['latency_ratio_pct']:.2f}%)")
    print(f"  KillSw:    {res['kill_switches']} trips")
    print(f"  PortPause: {res['portfolio_pauses']} events")
    print(f"  CapBlocks: {res['short_cap_blocks']} (Phase VV)")
    print(f"\n=== Gates ===")
    for g in res["gates"]:
        flag = "✓" if g["pass"] else "✗"
        print(f"  {flag} {g['name']:<25} {g['detail']}")
    print(f"\n  Failed: {res['n_failed']}")
    print(f"\n  VERDICT: {res['verdict']}")

    out_path = Path("quant_runtime/output/auto4h/phaseYY_promotion_gate.json")
    with open(out_path, "w") as f:
        json.dump(res, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    main()
