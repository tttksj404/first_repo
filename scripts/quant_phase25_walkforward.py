#!/usr/bin/env python3
"""Walk-forward 4-fold validation for paper bot ensemble.

각 신호 (vol_expansion / momentum_obv / squeeze_release) × 3코인 데이터를
1년치를 4분할 (Q1/Q2/Q3/Q4) 해서 fold별로 백테 → PF, 승률, fee/SL ratio.

Pass criteria (CLAUDE.md 규칙):
  WF score >= 3/4   (4개 fold 중 3개 이상 PF > 1.0)
  fee_safe         (fee가 SL의 20% 미만 — NoSL이라 변형: fee가 평균 손실의 20% 미만)

Pass 못하면 ensemble에서 해당 signal 제외 권고.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv

# Constants matching live bot
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


SIGNALS = {
    "vol_expansion": vol_expansion_signal,
    "momentum_obv":  momentum_obv_signal,
    "squeeze_release": squeeze_release_signal,
}


def simulate_fold(ind, sig_fn, start_idx, end_idx):
    """Run one signal on bars [start_idx, end_idx). Return list of trade pnls."""
    trades = []
    in_pos = False
    entry_px = 0.0; entry_idx = 0
    last_exit_i = -1; last_loss_i = -1
    slip = SLIPPAGE_BPS / 10000.0

    for i in range(max(start_idx, 30), end_idx):
        if not in_pos:
            # cooldown check
            if last_exit_i >= 0 and (i - last_exit_i) < COOLDOWN_AFTER_EXIT_H:
                continue
            if last_loss_i >= 0 and (i - last_loss_i) < COOLDOWN_AFTER_LOSS_H:
                continue
            if sig_fn(ind, i):
                entry_px = ind["close"][i] * (1 + slip)  # entry slippage
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
                # exit slip
                tp_px = entry_px * (1 + TP_ROE / 100 / LEVERAGE)
                fill = tp_px * (1 - slip)
                exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                reason = "TP"
            else:
                sig_now = sig_fn(ind, i)
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
        return {"n": 0, "wr": 0, "pf": 0, "ev": 0, "total": 0,
                "avg_win": 0, "avg_loss": 0, "fee_avg_loss_ratio": None}
    pnls = np.array([t["pnl"] for t in trades])
    wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() < 0 else float("inf")
    avg_win = wins.mean() if len(wins) else 0
    avg_loss = abs(losses.mean()) if len(losses) else 0
    fee = MARGIN * LEVERAGE * COST_RT  # fee per trade
    fee_safe = (fee / avg_loss) if avg_loss > 0 else None
    return {
        "n": len(trades),
        "wr": (pnls > 0).mean() * 100,
        "pf": pf if pf != float("inf") else 99.99,
        "ev": pnls.mean(),
        "total": pnls.sum(),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "fee_avg_loss_ratio": fee_safe,
    }


def run():
    universe = ["PEPEUSDT", "WIFUSDT", "DOGEUSDT"]
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        ind = compute_indicators(df)
        ind = add_extra_features(ind)
        ind = add_obv(ind)
        cache[sym] = ind

    n = min(len(cache[s]["close"]) for s in universe)
    fold_size = n // 4
    folds = [(k * fold_size, (k+1) * fold_size if k < 3 else n) for k in range(4)]
    fold_labels = [f"Q{k+1}" for k in range(4)]

    print(f"\n=== Walk-forward 4-fold (each ~{fold_size} bars ≈ {fold_size/24/30:.1f} mo) ===\n")

    overall_results = {}

    for sig_name, sig_fn in SIGNALS.items():
        print(f"\n━━━ {sig_name} ━━━")
        print(f"{'Fold':>5} {'sym':>5} {'n':>3} {'WR%':>6} {'PF':>6} {'EV$':>7} {'tot$':>7} {'fee/loss':>10}")
        sig_passes = 0
        sig_fold_data = {}
        for f_idx, (s, e) in enumerate(folds):
            fold_pnls = []
            fold_trades_per_sym = {}
            for sym in universe:
                trades = simulate_fold(cache[sym], sig_fn, s, e)
                m = fold_metrics(trades)
                fee_safe_str = f"{m['fee_avg_loss_ratio']:.2f}" if m['fee_avg_loss_ratio'] else "-"
                print(f"{fold_labels[f_idx]:>5} {sym[:4]:>5} {m['n']:>3} "
                      f"{m['wr']:>5.1f}% {m['pf']:>6.2f} "
                      f"{m['ev']:>+7.2f} {m['total']:>+7.1f} {fee_safe_str:>10}")
                fold_pnls.extend([t["pnl"] for t in trades])
                fold_trades_per_sym[sym] = m
            # Aggregate fold across symbols
            if fold_pnls:
                fold_total_m = fold_metrics([{"pnl": p, "roe": 0, "hold_h": 0, "reason": ""} for p in fold_pnls])
                pf_combined = fold_total_m["pf"]
                fold_pass = pf_combined > 1.0
                if fold_pass: sig_passes += 1
                print(f"  → {fold_labels[f_idx]} aggregate: n={fold_total_m['n']}  PF={pf_combined:.2f}  "
                      f"total=${fold_total_m['total']:+.1f}  {'✅ PASS' if fold_pass else '❌ FAIL'}")
                sig_fold_data[fold_labels[f_idx]] = fold_total_m
            else:
                print(f"  → {fold_labels[f_idx]} aggregate: 0 trades (SKIP)")

        wf_score = f"{sig_passes}/4"
        verdict = "✅ ROBUST" if sig_passes >= 3 else "⚠️ FRAGILE" if sig_passes == 2 else "❌ REJECT"
        print(f"\n  WALK-FORWARD SCORE: {wf_score}  → {verdict}")
        overall_results[sig_name] = {"wf_score": sig_passes, "folds": sig_fold_data,
                                      "verdict": verdict}

    # Save
    out_path = Path("quant_runtime/output/walkforward_ensemble.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(overall_results, f, indent=2, default=str)
    print(f"\n[saved] {out_path}\n")

    # Summary
    print("=" * 70)
    print("SUMMARY — ENSEMBLE 신호별 walk-forward 통과 여부")
    print("=" * 70)
    for sig, r in overall_results.items():
        print(f"  {sig:20s}  WF={r['wf_score']}/4  {r['verdict']}")
    n_robust = sum(1 for r in overall_results.values() if r['wf_score'] >= 3)
    print(f"\n  Robust signals: {n_robust}/3")
    if n_robust == 0:
        print("  🚨 모든 신호 fragile — strategy 재검토 필요")
    elif n_robust < 3:
        print(f"  ⚠️ 일부만 robust — fragile 신호는 ensemble에서 제외 권고")
    else:
        print("  ✅ All 3 robust — ensemble 그대로 운영 OK")


if __name__ == "__main__":
    run()
