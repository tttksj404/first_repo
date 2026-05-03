#!/usr/bin/env python3
"""신호 발생 빈도 정량 분석.

사용자 질문: "paper에서 들어가긴 해?"
Goal: vol_expansion이 실제로 얼마나 자주 발화하는지, 최근 언제 떴는지 확인.
다른 시그널들과 비교해서 "더 자주 들어가는" 옵션 제시.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase14_production_sim import compute_production_features
from quant_phase15_signal_library import (
    add_extra_features, entry_breakout_volexp, entry_squeeze_release,
    entry_momentum_continuation,
)
from quant_phase16_robustness import add_obv, entry_momentum_obv
from quant_phase20_10x_jackpot import entry_vol_expansion


def signal_breakout_loose(ind, i, long_only=True):
    """더 느슨한 breakout: BB 상단 돌파만."""
    if i < 25: return 0
    if (ind["close"][i] > ind["bb_upper"][i]
        and ind["mom24"][i] > 0
        and ind["vol_r"][i] >= 1.2):
        return 1
    return 0


def signal_simple_momentum(ind, i, long_only=True):
    """매우 느슨: ema20>ema50 + mom24>2% + ADX>20."""
    if i < 25: return 0
    if (ind["mom24"][i] > 0.02
        and ind["ema20"][i] > ind["ema50"][i]
        and ind["adx"][i] > 20):
        return 1
    return 0


SIGNALS = {
    "vol_expansion (현재 paper bot)": entry_vol_expansion,
    "momentum_obv (Phase17 winner)": entry_momentum_obv,
    "breakout_volexp": entry_breakout_volexp,
    "squeeze_release": entry_squeeze_release,
    "momentum_continuation": entry_momentum_continuation,
    "breakout_loose": signal_breakout_loose,
    "simple_momentum": signal_simple_momentum,
}


def main():
    universe = ["PEPEUSDT", "WIFUSDT", "DOGEUSDT"]
    print(f"Loading 1h data for {universe}...")
    cache = {}
    for sym in universe:
        try:
            df = load_1h(sym)
            ind = compute_indicators(df)
            ind = add_extra_features(ind)
            ind = add_obv(ind)
            ind = compute_production_features(ind)
            cache[sym] = ind
            n_bars = len(ind["close"])
            n_years = n_bars / (24 * 365)
            print(f"  {sym}: {n_bars} bars (~{n_years:.1f} years)")
        except Exception as e:
            print(f"  {sym}: FAIL {e}")
    print()

    print(f"{'Signal':35s} {'PEPE':>15s} {'WIF':>15s} {'DOGE':>15s} {'TOTAL':>12s}  Last fired (per symbol, hours ago)")
    print("=" * 150)

    for sig_name, sig_fn in SIGNALS.items():
        line = f"{sig_name:35s}"
        last_ago_strs = []
        total = 0
        for sym in universe:
            if sym not in cache: continue
            ind = cache[sym]
            n = len(ind["close"])
            count = 0
            last_idx = -1
            for i in range(25, n):
                if sig_fn(ind, i, True) != 0:
                    count += 1
                    last_idx = i
            n_years = n / (24 * 365)
            per_year = count / n_years if n_years > 0 else 0
            line += f"  {count:4d} ({per_year:5.1f}/y)"
            total += count
            if last_idx > 0:
                hours_ago = (n - 1 - last_idx)
                if hours_ago < 24:
                    last_ago_strs.append(f"{sym[:4]}:{hours_ago}h")
                elif hours_ago < 24*30:
                    last_ago_strs.append(f"{sym[:4]}:{hours_ago/24:.0f}d")
                else:
                    last_ago_strs.append(f"{sym[:4]}:{hours_ago/24/30:.0f}mo")
            else:
                last_ago_strs.append(f"{sym[:4]}:never")
        n_yrs_avg = sum(len(cache[s]["close"]) for s in cache) / len(cache) / (24 * 365)
        line += f"  {total:5d} ({total/n_yrs_avg/3:5.1f}/y/sym)"
        line += "   " + " ".join(last_ago_strs)
        print(line)
    print()
    print("Note: '/y/sym' = per year per symbol (avg). Cooldown not applied here.")
    print("With 12h-after-exit + 24h-after-loss cooldown, actual trades ~ 50-70% of raw signals.")


if __name__ == "__main__":
    main()
