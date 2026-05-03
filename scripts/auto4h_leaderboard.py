#!/usr/bin/env python3
"""Consolidated leaderboard merging all phases A-K.

Composite score: oos_pf_score * adj_score * net_score * stress_score
Tiered:
  TIER 1 STRONG:  Stage 3 + Phase C OOS verified
  TIER 1.5 NEW:   Phase I + K OOS + adj 18/27+ verified
  TIER 2 BOOST:   Phase D/E/H/J enhancements over baseline
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path("/Users/tttksj/first_repo/quant_runtime/output/auto4h")


def load(name):
    p = ROOT / name
    if not p.exists(): return None
    return json.loads(p.read_text())


def run():
    print("=" * 80)
    print("CONSOLIDATED LEADERBOARD — All phases A-K merged")
    print("=" * 80)

    phc = load("phaseC_oos.json")
    phd = load("phaseD_ensemble.json")
    phe = load("phaseE_regime.json")
    phf = load("phaseF_dynexit.json")
    phg = load("phaseG_timeofday.json")
    phh = load("phaseH_volregime.json")
    phj = load("phaseJ_entry.json")
    phk = load("phaseK_validate.json")

    leaderboard = []

    # TIER 1: Phase C OOS verified
    if phc:
        for r in phc["results"]:
            if r["verdict"] not in ("🥇 OOS_STRONG", "🥈 OOS_OK"): continue
            score = (r["oos"]["pf"] if r["oos"]["pf"] < 100 else 100) * max(r["oos"]["net"], 1) / 50
            leaderboard.append({
                "tier": "T1_STRONG" if r["verdict"] == "🥇 OOS_STRONG" else "T1_OK",
                "signal": r["signal"], "symbol": r["symbol"],
                "mom_min": r["mom_min"], "tp": r["tp"], "sl": r["sl"],
                "oos_pf": round(r["oos"]["pf"], 2),
                "oos_net": round(r["oos"]["net"], 1),
                "oos_n": r["oos"]["n"],
                "tr_pf": round(r["train"]["pf"], 2),
                "tr_net": round(r["train"]["net"], 1),
                "score": round(score, 2),
                "source": "phase_C",
            })

    # TIER 1.5: Phase K OOS + adj verified
    if phk:
        for r in phk["results"]:
            if r["verdict"] not in ("🥇 OOS_STRONG", "🥈 OOS_OK"): continue
            adj = r.get("adj_pass", 0)
            pf_clip = min(r["oos"]["pf"], 100) if r["oos"]["pf"] < 1e6 else 50
            score = pf_clip * max(r["oos"]["net"], 1) / 50 * (adj / 27)
            leaderboard.append({
                "tier": "T1.5_STRONG_NEW" if r["verdict"] == "🥇 OOS_STRONG" else "T1.5_OK_NEW",
                "signal": r["signal"], "symbol": r["symbol"],
                "mom_min": r["mom_min"], "tp": r["tp"], "sl": r["sl"],
                "oos_pf": round(pf_clip, 2),
                "oos_net": round(r["oos"]["net"], 1),
                "oos_n": r["oos"]["n"],
                "tr_pf": round(r["train"]["pf"], 2),
                "tr_net": round(r["train"]["net"], 1),
                "adj_pass": adj,
                "score": round(score, 2),
                "source": "phase_I+K",
            })

    leaderboard.sort(key=lambda r: -r["score"])

    print(f"\n{'#':>3} {'tier':<18} {'signal':<16} {'sym':<10} {'mom':>4} {'TP/SL':>9} "
          f"{'oos_pf':>7} {'oos_net':>8} {'oos_n':>5} {'score':>7}")
    for i, r in enumerate(leaderboard):
        tpsl = f"+{r['tp']}/{r['sl']}"
        print(f"{i+1:>3} {r['tier']:<18} {r['signal']:<16} {r['symbol']:<10} "
              f"{r['mom_min']*100:>3.0f}% {tpsl:>9} "
              f"{r['oos_pf']:>7.2f} ${r['oos_net']:>+6.0f} {r['oos_n']:>5} {r['score']:>7.1f}")

    # TIER 2 BOOSTS
    boosts = []
    if phd:
        for r in phd["results"]:
            uplift = r["ens_net"] - r["baseline_net"]
            if uplift > 30 and r["ens_pf"] >= 2.0 and r["ens_wf"] >= 3:
                boosts.append({
                    "kind": "ENSEMBLE", "primary": r["primary"], "secondary": r["secondary"],
                    "op": r["op"], "symbol": r["symbol"], "mom": r["mom_min"],
                    "tp": r["tp"], "sl": r["sl"],
                    "uplift_net": round(uplift, 1),
                    "pf": round(r["ens_pf"], 2), "wf": r["ens_wf"], "n": r["ens_n"],
                })
    if phe:
        for r in phe["results"]:
            if r.get("improved"):
                uplift = r["net"] - r["baseline_net"]
                boosts.append({
                    "kind": "REGIME", "signal": r["signal"], "symbol": r["symbol"],
                    "mom": r["mom_min"], "tp": r["tp"], "sl": r["sl"],
                    "regime": r["regime"], "uplift_net": round(uplift, 1),
                    "pf": round(r["pf"], 2), "wf": r["wf"], "n": r["n"],
                })
    if phh:
        for r in phh["results"]:
            if r.get("improved"):
                uplift = r["net"] - r["baseline_net"]
                boosts.append({
                    "kind": "VOL", "signal": r["signal"], "symbol": r["symbol"],
                    "mom": r["mom_min"], "tp": r["tp"], "sl": r["sl"],
                    "bucket": r["bucket"], "uplift_net": round(uplift, 1),
                    "pf": round(r["pf"], 2), "wf": r["wf"], "n": r["n"],
                })
    if phj:
        for r in phj["results"]:
            if r.get("improved"):
                uplift = r["net"] - r["baseline_net"]
                boosts.append({
                    "kind": "ENTRY", "signal": r["signal"], "symbol": r["symbol"],
                    "mom": r["mom_min"], "tp": r["tp"], "sl": r["sl"],
                    "mode": r["mode"], "uplift_net": round(uplift, 1),
                    "pf": round(r["pf"], 2), "wf": r["wf"], "n": r["n"],
                })
    if phg:
        for r in phg["results"]:
            if r.get("improved"):
                uplift = r["net"] - r["baseline_net"]
                boosts.append({
                    "kind": "TIME", "signal": r["signal"], "symbol": r["symbol"],
                    "mom": r["mom_min"], "tp": r["tp"], "sl": r["sl"],
                    "bucket": r["bucket"], "uplift_net": round(uplift, 1),
                    "pf": round(r["pf"], 2), "wf": r["wf"], "n": r["n"],
                })
    if phf:
        for r in phf["results"]:
            if r.get("improved"):
                uplift = r["net"] - r["baseline_net"]
                boosts.append({
                    "kind": "EXIT", "signal": r["signal"], "symbol": r["symbol"],
                    "mom": r["mom_min"], "tp": r["tp"], "sl": r["sl"],
                    "exit_mode": r["exit_mode"], "uplift_net": round(uplift, 1),
                    "pf": round(r["pf"], 2), "wf": r["wf"], "n": r["n"],
                })

    boosts.sort(key=lambda r: -r["uplift_net"])
    print(f"\n=== TIER 2 BOOSTS (top 25) ===")
    for r in boosts[:25]:
        if r["kind"] == "ENSEMBLE":
            d = f"{r['primary']} {r['op']} {r['secondary']}"
        elif r["kind"] == "REGIME":
            d = f"{r['signal']} regime={r['regime']}"
        elif r["kind"] == "VOL":
            d = f"{r['signal']} vol={r['bucket']}"
        elif r["kind"] == "ENTRY":
            d = f"{r['signal']} entry={r['mode']}"
        elif r["kind"] == "TIME":
            d = f"{r['signal']} hours={r['bucket']}"
        elif r["kind"] == "EXIT":
            d = f"{r['signal']} exit={r['exit_mode']}"
        print(f"  [{r['kind']:>8}] {r['symbol']:<10} {d:<48} +${r['uplift_net']:>5.0f} "
              f"PF={r['pf']:.2f} {r['wf']}/4 n={r['n']}")

    out = {"tier1": leaderboard, "tier2_boosts": boosts}
    with open(ROOT / "leaderboard_consolidated.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n[saved] {ROOT / 'leaderboard_consolidated.json'}")
    print(f"\nTier 1: {len([r for r in leaderboard if r['tier'].endswith('STRONG') or r['tier'].endswith('STRONG_NEW')])} STRONG, "
          f"{len([r for r in leaderboard if 'OK' in r['tier']])} OK")
    print(f"Tier 2 boosts: {len(boosts)} total ({sum(1 for b in boosts if b['kind']=='ENSEMBLE')} ensemble, "
          f"{sum(1 for b in boosts if b['kind']=='REGIME')} regime, "
          f"{sum(1 for b in boosts if b['kind']=='VOL')} vol, "
          f"{sum(1 for b in boosts if b['kind']=='ENTRY')} entry, "
          f"{sum(1 for b in boosts if b['kind']=='TIME')} time, "
          f"{sum(1 for b in boosts if b['kind']=='EXIT')} exit)")


if __name__ == "__main__":
    run()
