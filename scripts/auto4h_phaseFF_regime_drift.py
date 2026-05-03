#!/usr/bin/env python3
"""Phase FF: Regime drift detector.

Gemini Round 3 비판: Mode B 70/30 fixed → 6+개월 prolonged bull 시 short 30% drag.
해결: rolling 90d bear_frac 측정 → Mode B 비율 동적 조정.

For each rolling 90d window in OOS, compute:
  - bear_frac (bear regime occupancy)
  - Mode B implied long/short split
  - vs baseline 70/30 fixed
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv
from auto4h_phaseQ_short_side import precompute_bear_regime
from auto4h_stage1_matrix import precompute_btc_regime


def run():
    print("Phase FF: regime drift detector — rolling 90d bear_frac")
    btc_df = load_1h("BTCUSDT")
    if btc_df is None:
        print("[err] BTCUSDT not loaded"); return
    ind = compute_indicators(btc_df); ind = add_extra_features(ind); ind = add_obv(ind)
    btc_bull = precompute_btc_regime(ind)
    btc_bear = precompute_bear_regime(ind)
    n = len(btc_bear)
    win = 24*90  # 90d
    print(f"  total bars: {n} (~{n/24:.0f}d), window: {win}h (~90d)")

    # Sample every 7d
    samples = []
    for end in range(win, n, 24*7):
        s = end - win
        bear_frac = float(btc_bear[s:end].mean())
        bull_frac = float(btc_bull[s:end].mean())
        samples.append({"end_idx": end, "bear_frac": bear_frac, "bull_frac": bull_frac})

    bears = [s["bear_frac"] for s in samples]
    bulls = [s["bull_frac"] for s in samples]
    print(f"\n=== bear_frac distribution across {len(samples)} 90d windows ===")
    print(f"  min:    {min(bears)*100:.1f}%")
    print(f"  p10:    {np.percentile(bears, 10)*100:.1f}%")
    print(f"  p25:    {np.percentile(bears, 25)*100:.1f}%")
    print(f"  median: {np.percentile(bears, 50)*100:.1f}%")
    print(f"  p75:    {np.percentile(bears, 75)*100:.1f}%")
    print(f"  p90:    {np.percentile(bears, 90)*100:.1f}%")
    print(f"  max:    {max(bears)*100:.1f}%")

    # Test scenarios
    print(f"\n=== Mode B sizing under extreme regimes ===")
    print(f"  Permanent bull (bear=0%):   long=$50.00 / short=$0")
    print(f"  Observed min (bear={min(bears)*100:.0f}%): "
          f"long=${50*(1-min(bears)):.2f} / short=${50*min(bears):.2f}")
    print(f"  Median (bear={np.percentile(bears,50)*100:.0f}%): "
          f"long=${50*(1-np.percentile(bears,50)):.2f} / short=${50*np.percentile(bears,50):.2f}")
    print(f"  Observed max (bear={max(bears)*100:.0f}%): "
          f"long=${50*(1-max(bears)):.2f} / short=${50*max(bears):.2f}")
    print(f"  Permanent bear (bear=100%): long=$0 / short=$50.00")

    # Volatility of bear_frac (drift risk)
    bear_vol = float(np.std(bears))
    print(f"\n  bear_frac std: {bear_vol*100:.1f}pp → expected weekly drift")
    print(f"  bear_frac range: {(max(bears)-min(bears))*100:.1f}pp")

    # Recommendation
    if max(bears) - min(bears) > 0.30:
        verdict = "DRIFT_HIGH — fixed 70/30 risky, recommend rolling 90d update weekly"
    elif max(bears) - min(bears) > 0.15:
        verdict = "DRIFT_MODERATE — fixed acceptable, rolling 180d safer"
    else:
        verdict = "DRIFT_LOW — fixed 70/30 stable"
    print(f"\n  Verdict: {verdict}")

    out = Path("quant_runtime/output/auto4h/phaseFF_regime_drift.json")
    with open(out, "w") as f:
        json.dump({
            "samples": samples,
            "bear_frac_min": min(bears), "bear_frac_max": max(bears),
            "bear_frac_p50": float(np.percentile(bears, 50)),
            "bear_frac_std": bear_vol,
            "verdict": verdict,
        }, f, indent=2, default=str)
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    run()
