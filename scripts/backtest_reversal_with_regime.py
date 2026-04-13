"""Apply Hurst+HAR-RV regime filter to existing Reversal 15x strategy.

Strategy baseline (from quant_full_ensemble.py):
- BTC regime != crash (r5d > -8%)
- Buy coin that crashed -10% in 3d
- 15x lev, 75% margin, SL 10% ROE, 1w hold
- 154 trades/3yr, WR 29%, PF 7.25, ruin 2.8%

Overlay: require regime filter to pass for entry.
"""
from __future__ import annotations

import json
import os
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/home/user/first_repo")

from quant_binance.features.regime_filter import (
    hurst_dfa,
    har_rv_forecast,
    classify_regime,
    vol_regime,
)

dd = Path("/home/user/first_repo/quant_runtime/historical")
COST_RT = 0.0012
EQUITY = 75.0

# Load 1h data
all_coins = {}
for sym_dir in sorted(dd.iterdir()):
    if not sym_dir.is_dir():
        continue
    sym = sym_dir.name
    p1h = sym_dir / "1h.json"
    if not p1h.exists():
        continue
    b1 = json.load(open(p1h))
    if len(b1) < 5000:
        continue
    all_coins[sym] = [b["close_price"] for b in b1]

btc = all_coins.get("BTCUSDT", [])
print(f"Loaded {len(all_coins)} coins", flush=True)


def mom(c, i, p):
    return (c[i] - c[i - p]) / c[i - p] if i >= p and c[i - p] > 0 else 0


def regime_btc(btc_c, i):
    if i < 720 or i >= len(btc_c):
        return 1
    r5d = (btc_c[i] - btc_c[i - 120]) / btc_c[i - 120] if btc_c[i - 120] > 0 else 0
    if r5d < -0.08:
        return 0
    e20 = sum(btc_c[max(0, i - 20):i + 1]) / min(20, i + 1)
    e50 = sum(btc_c[max(0, i - 50):i + 1]) / min(50, i + 1)
    return 2 if e20 > e50 else 1


# Pre-compute regime filter values for each coin at hourly intervals
print("[regime] Precomputing Hurst + HAR-RV per coin (hourly)...", flush=True)
regime_cache = {}  # (sym, i) → (hurst, rv_fc, rv_median)

for sym, c in all_coins.items():
    print(f"  {sym}...", flush=True)
    # Returns
    rets = []
    for i in range(1, len(c)):
        if c[i - 1] > 0:
            rets.append((c[i] / c[i - 1]) - 1)
        else:
            rets.append(0)

    # Compute at every 24h (daily) since strategy checks daily
    rv_values_temp = []
    cache_pts = []
    for i in range(720, len(c), 24):
        rets_window = rets[i - 500:i]
        rets_full = rets[i - 2016:i] if i >= 2016 else rets[:i]
        if len(rets_window) < 300 or len(rets_full) < 500:
            continue
        h = hurst_dfa(rets_window, min_lag=4, max_lag=64)
        rv_fc, _, _, _ = har_rv_forecast(rets_full)
        cache_pts.append((i, h, rv_fc))
        rv_values_temp.append(rv_fc)

    # Median RV for this coin
    rv_med = statistics.median(rv_values_temp) if rv_values_temp else 0

    for i, h, rv in cache_pts:
        regime_cache[(sym, i)] = (h, rv, rv_med)


def get_regime(sym, i):
    """Get nearest cached regime data."""
    # Round down to nearest multiple of 24
    ii = (i // 24) * 24
    return regime_cache.get((sym, ii))


print(f"  Cache: {len(regime_cache)} points\n", flush=True)


def run_strategy(filter_name, filter_fn):
    """Run reversal strategy with optional regime filter."""
    trades = []
    pos = None
    cd = 0
    lev = 15
    mp = 0.75
    sl_roe = 10
    hold_h = 168  # 1 week

    margin = EQUITY * mp
    notional = margin * lev
    fee = notional * COST_RT

    max_n = max(len(c) for c in all_coins.values())

    for i in range(720, max_n, 24):
        if pos:
            c = all_coins.get(pos["sym"])
            if not c or i >= len(c):
                pos = None
                continue
            pc = (c[i] / pos["bp"] - 1)
            roe = pc * 100 * lev
            hh = i - pos["ei"]
            fd = notional * 0.0001 * (hh // 8)
            if roe <= -sl_roe:
                trades.append(margin * (-sl_roe / 100) - fee - fd)
                pos = None
                cd = i + 48
                continue
            if hh >= hold_h:
                trades.append(margin * (roe / 100) - fee - fd)
                pos = None
                continue
            continue

        if i < cd:
            continue

        reg = regime_btc(btc, i)
        if reg == 0:
            continue

        best_sym = None
        best_score = -999

        for sym, c in all_coins.items():
            if sym == "BTCUSDT" or i >= len(c):
                continue
            r3d = mom(c, i, 72)
            if r3d < -0.10:
                score = -r3d
                if score > best_score:
                    # Apply regime filter
                    rg = get_regime(sym, i)
                    if rg is None:
                        continue
                    if not filter_fn(rg):
                        continue
                    best_score = score
                    best_sym = sym

        if best_sym and best_score > 0:
            c = all_coins[best_sym]
            pos = {"sym": best_sym, "bp": c[i], "ei": i}

    if not trades or len(trades) < 5:
        return None

    w = sum(1 for t in trades if t > 0)
    nt = len(trades)
    total = sum(trades)
    gp = sum(t for t in trades if t > 0)
    gl = abs(sum(t for t in trades if t <= 0))
    pf = gp / max(gl, 0.01)
    wr = w / nt
    aw = gp / max(w, 1)
    al = gl / max(nt - w, 1)
    ev = wr * aw - (1 - wr) * al

    # WF 4-fold
    fs = max(nt // 4, 1)
    wf_folds = []
    for fi in range(4):
        s = fi * fs
        e = (fi + 1) * fs if fi < 3 else nt
        fold_sum = sum(trades[s:e])
        wf_folds.append(fold_sum)
    wf = sum(1 for f in wf_folds if f > 0)

    # Ruin probability
    ruin = 0
    for _ in range(1000):
        bal = 75.0
        for t in random.choices(trades, k=nt):
            bal += t
            if bal <= 0:
                ruin += 1
                break

    return {
        "name": filter_name,
        "trades": nt,
        "wr": round(wr, 4),
        "pf": round(pf, 2),
        "total": round(total, 2),
        "avg_win": round(aw, 2),
        "avg_loss": round(al, 2),
        "ev": round(ev, 2),
        "wf": wf,
        "wf_folds": [round(f, 2) for f in wf_folds],
        "ruin_pct": round(ruin / 10, 2),
    }


# Filter variants
filters = {
    "A_NONE": lambda rg: True,
    "B_HURST_REV": lambda rg: rg[0] < 0.45,  # Require reverting regime
    "C_HURST_NOT_TREND": lambda rg: rg[0] < 0.55,  # Not trending
    "D_VOL_HIGH": lambda rg: rg[1] > 1.5 * rg[2] if rg[2] > 0 else False,
    "E_VOL_NORMAL_UP": lambda rg: rg[1] > 0.5 * rg[2] if rg[2] > 0 else True,
    "F_HURST_REV_VOL_UP": lambda rg: rg[0] < 0.45 and (rg[1] > 0.5 * rg[2] if rg[2] > 0 else True),
    "G_HURST_ANY_VOL_HIGH": lambda rg: rg[0] < 0.55 and (rg[1] > 1.5 * rg[2] if rg[2] > 0 else False),
    "H_STRICT": lambda rg: rg[0] < 0.45 and (rg[1] > 1.5 * rg[2] if rg[2] > 0 else False),
}

print(f"{'=' * 100}")
print(f"  REVERSAL 15x + REGIME FILTER OVERLAY (3yr, 17 coins)")
print(f"{'=' * 100}")
print(f"\n  {'Filter':<25} {'Trades':>7} {'WR':>6} {'PF':>6} {'Total$':>9} {'EV$':>7} {'Ruin%':>7} {'WF':>4}")
print("  " + "-" * 90)

results = {}
for name, fn in filters.items():
    r = run_strategy(name, fn)
    if r is None:
        print(f"  {name:<25} (too few trades)")
        continue
    results[name] = r
    tag = "★" if r["wf"] == 4 else ("●" if r["wf"] == 3 else "")
    print(f"  {r['name']:<25} {r['trades']:>7} {r['wr']*100:>5.1f}% {r['pf']:>5.2f} {r['total']:>+8.2f} {r['ev']:>+6.2f} {r['ruin_pct']:>6.1f}% {r['wf']:>2}/4 {tag}")

# Compare vs baseline
baseline = results.get("A_NONE")
if baseline:
    print(f"\n=== Baseline comparison ===")
    print(f"Baseline: {baseline['trades']} tr, PF {baseline['pf']}, total ${baseline['total']}, ruin {baseline['ruin_pct']}%, WF {baseline['wf']}/4")
    for name, r in results.items():
        if name == "A_NONE":
            continue
        trade_change = r["trades"] - baseline["trades"]
        pf_change = r["pf"] - baseline["pf"]
        total_change = r["total"] - baseline["total"]
        ruin_change = r["ruin_pct"] - baseline["ruin_pct"]
        wf_change = r["wf"] - baseline["wf"]
        print(f"  {name}: Δtr={trade_change:+d} ΔPF={pf_change:+.2f} Δtotal=${total_change:+.2f} Δruin={ruin_change:+.1f}% ΔWF={wf_change:+d}")

# Save
out = Path("/home/user/first_repo/quant_runtime/artifacts/reversal_with_regime.json")

out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\nSaved to {out}")
