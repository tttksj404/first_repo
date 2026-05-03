#!/usr/bin/env python3
"""Phase 26: Confluence + BTC Regime Filter — WF 4-fold 재검증.

기존 ensemble은 WF 1-2/4 (모두 fragile/reject). 3가지 새 변형 시험:

  V_REGIME    : BTC 추세 ON 시에만 ensemble 작동 (1신호 OR)
  V_CONFLUENCE: 3 신호 중 ≥2개 동시 발화 시에만 진입 (regime 무시)
  V_BOTH      : Confluence(≥2) AND BTC 추세 ON

목표: WF >= 3/4 (CLAUDE.md 룰)
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv

# === Bot constants (matched to live paper bot) ===
LEVERAGE = 10
MARGIN = 50.0
COST_RT = 0.0012
FUNDING_8H = 0.0001
SLIPPAGE_BPS = 8
TP_ROE = 500.0
LIQ_ROE = -95.0
SIGNAL_OFF_MIN_ROE = 0.0
COOLDOWN_AFTER_EXIT_H = 12
COOLDOWN_AFTER_LOSS_H = 24


# ===== INDIVIDUAL SIGNALS (same as bot) =====
def vol_expansion_signal(ind, i):
    if i < 30: return False
    return (ind["bb_width_rank"][i] >= 0.7
            and ind["mom24"][i] > 0.03
            and ind["close"][i] > ind["bb_upper"][i]
            and ind["vol_r"][i] >= 1.5)

def momentum_obv_signal(ind, i):
    if i < 25: return False
    return (ind["mom24"][i] > 0.05
            and ind["ema20"][i] > ind["ema50"][i]
            and ind["adx"][i] > 22
            and ind["vol_r"][i] >= 1.3
            and ind["obv_slope"][i] > 0)

def squeeze_release_signal(ind, i):
    if i < 22 or i < 5: return False
    if not all(ind["bb_width_rank"][k] < 0.30 for k in range(i-5, i)):
        return False
    return ind["close"][i] > ind["bb_upper"][i-1] and ind["vol_r"][i] > 1.3


SIG_FNS = [vol_expansion_signal, momentum_obv_signal, squeeze_release_signal]


# ===== BTC REGIME (계산은 동일 1h 데이터에서) =====
def precompute_btc_regime(btc_ind):
    """At each i, regime = (BTC ema20 > ema50) AND (recent volatility expanding).
    Returns boolean array same length as btc_ind['close'].

    'Trending' = BTC 1h ema20 > ema50 over the past N hours (smoothed)
    'Volatile-enough' = BTC ATR(24h) percentile rank >= 0.4 in last 200 bars
    """
    n = len(btc_ind["close"])
    close = btc_ind["close"]; high = btc_ind["high"]; low = btc_ind["low"]
    ema20 = btc_ind["ema20"]; ema50 = btc_ind["ema50"]

    # ATR(24)
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
    atr24 = np.zeros(n)
    for i in range(n):
        s = max(0, i - 23)
        atr24[i] = np.mean(tr[s:i+1])

    # ATR percentile over last 200 bars
    atr_rank = np.zeros(n)
    for i in range(n):
        s = max(0, i - 199)
        seg = atr24[s:i+1]
        atr_rank[i] = (seg <= atr24[i]).mean() if len(seg) else 0.5

    regime = np.zeros(n, dtype=bool)
    for i in range(n):
        regime[i] = (ema20[i] > ema50[i]) and (atr_rank[i] >= 0.4)
    return regime


# ===== ENTRY VARIANTS =====
def entry_regime(ind, i, btc_regime_at_i):
    """Plan B: regime filter + ensemble OR."""
    if not btc_regime_at_i: return False
    return any(fn(ind, i) for fn in SIG_FNS)

def entry_confluence(ind, i, btc_regime_at_i):
    """Plan A: 3 신호 중 ≥2개 동시 발화."""
    n_active = sum(1 for fn in SIG_FNS if fn(ind, i))
    return n_active >= 2

def entry_both(ind, i, btc_regime_at_i):
    """Plan A+B: confluence AND regime."""
    if not btc_regime_at_i: return False
    n_active = sum(1 for fn in SIG_FNS if fn(ind, i))
    return n_active >= 2


VARIANTS = {
    "V_REGIME":     entry_regime,
    "V_CONFLUENCE": entry_confluence,
    "V_BOTH":       entry_both,
}


# ===== SIMULATOR =====
def simulate_fold(ind, btc_regime, entry_fn, start_idx, end_idx):
    """For one symbol over [start, end), with btc_regime aligned by index."""
    trades = []
    in_pos = False
    entry_px = 0.0; entry_idx = 0
    last_exit_i = -1; last_loss_i = -1
    slip = SLIPPAGE_BPS / 10000.0

    for i in range(max(start_idx, 30), end_idx):
        if not in_pos:
            if last_exit_i >= 0 and (i - last_exit_i) < COOLDOWN_AFTER_EXIT_H: continue
            if last_loss_i >= 0 and (i - last_loss_i) < COOLDOWN_AFTER_LOSS_H: continue
            btc_r = bool(btc_regime[i]) if i < len(btc_regime) else False
            if entry_fn(ind, i, btc_r):
                entry_px = ind["close"][i] * (1 + slip)
                entry_idx = i
                in_pos = True
        else:
            hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
            roe_lo = (lo / entry_px - 1) * LEVERAGE * 100
            roe_hi = (hi / entry_px - 1) * LEVERAGE * 100
            roe_cl = (cl / entry_px - 1) * LEVERAGE * 100
            exit_roe = None; reason = None
            if roe_lo <= LIQ_ROE:
                exit_roe = -100.0; reason = "LIQ"
            elif roe_hi >= TP_ROE:
                tp_px = entry_px * (1 + TP_ROE / 100 / LEVERAGE)
                fill = tp_px * (1 - slip)
                exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                reason = "TP"
            else:
                # signal_off uses ANY of the 3 (loose exit)
                sig_now = any(fn(ind, i) for fn in SIG_FNS)
                if (not sig_now) and roe_cl > SIGNAL_OFF_MIN_ROE:
                    fill = cl * (1 - slip)
                    exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                    reason = "SIG_OFF"
            if exit_roe is not None:
                hold_h = i - entry_idx
                notional = MARGIN * LEVERAGE
                fee = notional * COST_RT
                funding = notional * FUNDING_8H * (hold_h / 8)
                if exit_roe <= -100:
                    pnl = -MARGIN - fee
                else:
                    pnl = MARGIN * (exit_roe / 100) - fee - funding
                trades.append({"pnl": pnl, "roe": exit_roe, "hold_h": hold_h, "reason": reason})
                in_pos = False
                last_exit_i = i
                if pnl < 0: last_loss_i = i
    return trades


def fold_metrics(trades):
    if not trades:
        return {"n": 0, "wr": 0, "pf": 0, "ev": 0, "total": 0}
    pnls = np.array([t["pnl"] for t in trades])
    wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() < 0 else 99.99
    return {
        "n": len(trades),
        "wr": float((pnls > 0).mean() * 100),
        "pf": float(pf),
        "ev": float(pnls.mean()),
        "total": float(pnls.sum()),
        "n_liq": int(sum(1 for t in trades if t["reason"] == "LIQ")),
        "n_tp": int(sum(1 for t in trades if t["reason"] == "TP")),
    }


def run():
    universe = ["PEPEUSDT", "WIFUSDT", "DOGEUSDT"]
    print("Loading data + computing indicators...")
    cache = {}
    for sym in universe + ["BTCUSDT"]:
        df = load_1h(sym)
        ind = compute_indicators(df)
        ind = add_extra_features(ind)
        ind = add_obv(ind)
        cache[sym] = ind

    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    pct_trending = btc_regime.mean() * 100
    print(f"BTC regime trending: {pct_trending:.1f}% of bars\n")

    n = min(len(cache[s]["close"]) for s in universe + ["BTCUSDT"])
    fold_size = n // 4
    folds = [(k * fold_size, (k+1) * fold_size if k < 3 else n) for k in range(4)]

    overall = {}

    for vname, vfn in VARIANTS.items():
        print(f"\n━━━ {vname} ━━━")
        sig_passes = 0
        fold_data = {}
        for f_idx, (s, e) in enumerate(folds):
            fold_pnls = []
            for sym in universe:
                trades = simulate_fold(cache[sym], btc_regime, vfn, s, e)
                fold_pnls.extend([t["pnl"] for t in trades])
            if fold_pnls:
                m = fold_metrics([{"pnl": p, "roe": 0, "hold_h": 0, "reason": ""} for p in fold_pnls])
                fold_pass = m["pf"] > 1.0 and m["n"] >= 5
                if fold_pass: sig_passes += 1
                tag = "✅ PASS" if fold_pass else ("❌ FAIL" if m["n"] >= 5 else "⊘ TOO_FEW")
                print(f"  Q{f_idx+1}: n={m['n']:3d}  PF={m['pf']:.2f}  EV=${m['ev']:+.2f}  "
                      f"total=${m['total']:+.1f}  {tag}")
                fold_data[f"Q{f_idx+1}"] = m
            else:
                print(f"  Q{f_idx+1}: 0 trades — SKIP")
                fold_data[f"Q{f_idx+1}"] = {"n": 0}

        verdict = "✅ ROBUST" if sig_passes >= 3 else "⚠️ FRAGILE" if sig_passes == 2 else "❌ REJECT"
        n_total = sum(fd.get("n", 0) for fd in fold_data.values())
        total_pnl = sum(fd.get("total", 0) for fd in fold_data.values())
        print(f"\n  WF SCORE: {sig_passes}/4   verdict: {verdict}")
        print(f"  Year total: n={n_total}  PnL=${total_pnl:+.1f}")
        overall[vname] = {"wf_score": sig_passes, "folds": fold_data,
                          "verdict": verdict, "n_total": n_total,
                          "total_pnl": total_pnl}

    # Save
    out_path = Path("quant_runtime/output/walkforward_phase26.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(overall, f, indent=2, default=str)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"{'Variant':15s} {'WF':>4} {'verdict':12s} {'n/y':>5} {'PnL$/y':>8}")
    for v, r in overall.items():
        print(f"  {v:13s} {r['wf_score']}/4  {r['verdict']:12s} "
              f"{r['n_total']:>5}  ${r['total_pnl']:>+7.1f}")

    # Pick winner
    robust = [v for v,r in overall.items() if r['wf_score'] >= 3]
    if robust:
        winner = max(robust, key=lambda v: overall[v]['total_pnl'])
        print(f"\n🏆 WINNER: {winner} (WF {overall[winner]['wf_score']}/4, "
              f"PnL ${overall[winner]['total_pnl']:+.1f}/y)")
        return winner, overall
    else:
        # No robust strategy — pick least-bad
        best_score = max(r['wf_score'] for r in overall.values())
        candidates = [v for v,r in overall.items() if r['wf_score'] == best_score and r['total_pnl'] > 0]
        if candidates:
            winner = max(candidates, key=lambda v: overall[v]['total_pnl'])
            print(f"\n⚠️ NO ROBUST FOUND. Best fragile: {winner} (WF {best_score}/4)")
            return winner, overall
        print(f"\n🚨 ALL REJECTED. None viable.")
        return None, overall


if __name__ == "__main__":
    run()
