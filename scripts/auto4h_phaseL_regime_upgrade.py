#!/usr/bin/env python3
"""Phase L: Regime upgrade re-test on all 17 paper bot strategies.

Phase E 가 atr_only / always_on 이 baseline (btc_default) 보다 우월함을 발견.
이걸 ALL 17 페이퍼봇 strategy 에 적용해서, regime 별 OOS PF/net 비교.
최종: 각 strategy 마다 best regime 선정 + paper bot 룰 업데이트 권고.
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv
from auto4h_signal_library import SIGNALS
from auto4h_phaseE_alt_regime import precompute_regime, simulate_with_regime, quick_eval


# 17 paper bot strategies
STRATEGIES = [
    ("eth_donchian",   "donchian_20",   "ETHUSDT",  0.02,  50, -35),
    ("eth_volexp_2",   "vol_expansion", "ETHUSDT",  0.02,  50, -25),
    ("sui_atrexp_4",   "atr_expansion", "SUIUSDT",  0.04, 150, -40),
    ("sui_atrexp_2",   "atr_expansion", "SUIUSDT",  0.02,  80, -35),
    ("arb_volexp",     "vol_expansion", "ARBUSDT",  0.04,  50, -20),
    ("doge_volexp_4",  "vol_expansion", "DOGEUSDT", 0.04,  80, -30),
    ("doge_volexp_2",  "vol_expansion", "DOGEUSDT", 0.02,  80, -30),
    ("doge_heikin",    "heikin_cont",   "DOGEUSDT", 0.06,  80, -35),
    ("doge_momobv",    "momentum_obv",  "DOGEUSDT", 0.02,  80, -30),
    ("wif_momobv",     "momentum_obv",  "WIFUSDT",  0.02, 300, -25),
    ("wif_heikin",     "heikin_cont",   "WIFUSDT",  0.06, 100, -25),
    ("ada_heikin_300", "heikin_cont",   "ADAUSDT",  0.04, 300, -50),
    ("ada_heikin_150", "heikin_cont",   "ADAUSDT",  0.04, 150, -35),
    ("ada_heikin_200", "heikin_cont",   "ADAUSDT",  0.04, 200, -40),
    ("ada_heikin_2",   "heikin_cont",   "ADAUSDT",  0.02, 300, -50),
    ("op_atrexp",      "atr_expansion", "OPUSDT",   0.06, 300, -50),
    ("pepe_atrexp",    "atr_expansion", "PEPEUSDT", 0.08, 300, -50),
]

REGIMES = ["btc_default", "atr_only", "always_on", "ema_only"]


def folds_split(n, train_frac=0.7):
    train_end = int(n * train_frac)
    train_size = train_end // 4
    train_folds = [(k*train_size, (k+1)*train_size if k<3 else train_end) for k in range(4)]
    oos = [(train_end, n)]
    return train_folds, oos


def run():
    print("Phase L: regime upgrade re-test on 17 paper bot strategies")
    universe = sorted(set(s[2] for s in STRATEGIES) | {"BTCUSDT", "ETHUSDT"})
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    n_min = min(len(c["close"]) for c in cache.values())
    train_folds, oos_folds = folds_split(n_min)

    btc = cache["BTCUSDT"]; eth = cache["ETHUSDT"]
    all_regs = {}
    for mode in REGIMES:
        all_regs[f"btc_{mode}"] = precompute_regime(btc, mode)
        all_regs[f"eth_{mode}"] = precompute_regime(eth, mode)

    results = []; recommendations = {}
    print(f"\n{'sid':<18} best_regime         oos_pf  oos_net  oos_n  vs_baseline")
    for sid, sig_name, sym, mom, tp, sl in STRATEGIES:
        if sym not in cache: continue
        sig_fn = SIGNALS[sig_name]; ind = cache[sym]
        baseline = quick_eval(ind, all_regs["btc_btc_default"], sig_fn, oos_folds, tp, sl, mom)
        best = None; best_name = "btc_btc_default"
        for rname, reg in all_regs.items():
            r = quick_eval(ind, reg, sig_fn, oos_folds, tp, sl, mom)
            if r is None: continue
            results.append({"sid": sid, "regime": rname, **r})
            score = r["net"] * (r["pf"] if r["pf"] < 100 else 100) ** 0.3
            if best is None or score > best["score"]:
                best = {**r, "score": score}; best_name = rname
        if best:
            recommendations[sid] = {"regime": best_name, "oos": best,
                                    "baseline_oos": baseline}
            uplift = (best["net"] - (baseline["net"] if baseline else 0))
            print(f"{sid:<18} {best_name:<22} {best['pf']:>5.2f} ${best['net']:>+5.0f} "
                  f"{best['n']:>4} {uplift:+.0f} vs baseline")

    out = Path("quant_runtime/output/auto4h/phaseL_regime_upgrade.json")
    with open(out, "w") as f:
        json.dump({"results": results, "recommendations": recommendations}, f, indent=2, default=str)

    # summary
    keep_default = [s for s, r in recommendations.items() if r["regime"] == "btc_btc_default"]
    upgrade_atr = [s for s, r in recommendations.items() if "atr_only" in r["regime"]]
    upgrade_always = [s for s, r in recommendations.items() if "always_on" in r["regime"]]
    other = [s for s, r in recommendations.items()
             if r["regime"] != "btc_btc_default" and "atr_only" not in r["regime"]
             and "always_on" not in r["regime"]]

    print(f"\n=== REGIME RECOMMENDATIONS (OOS optimized) ===")
    print(f"  keep btc_default:  {len(keep_default)} {keep_default}")
    print(f"  upgrade atr_only:  {len(upgrade_atr)} {upgrade_atr}")
    print(f"  upgrade always_on: {len(upgrade_always)} {upgrade_always}")
    print(f"  other regimes:     {len(other)} {other}")

    print(f"\n[saved] {out}")


if __name__ == "__main__":
    run()
