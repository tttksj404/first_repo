#!/usr/bin/env python3
"""Phase 30b: 메이저 — TP 더 낮추고 per-symbol 분리 + mom_min sweep.

Phase 30a 발견: TP 80~500 다 같음 = 메이저는 +80% ROE도 거의 안 옴.
→ TP {20, 30, 40, 50, 60, 80, 100} 그리드 추가
   per-symbol 분리해서 ETH-only 운영 가능성 보기
   mom_min sweep (2%, 3%, 4%, 5%)
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv

LEVERAGE = 10
MARGIN = 50.0
COST_RT = 0.0012
FUNDING_8H = 0.0001
SLIPPAGE_BPS = 8
LIQ_ROE = -95.0
SIGNAL_OFF_MIN_ROE = 0.0
COOLDOWN_AFTER_EXIT_H = 12
COOLDOWN_AFTER_LOSS_H = 24
REGIME_ATR_MIN = 0.4


def vol_expansion_signal(ind, i):
    if i < 30: return False
    return (ind["bb_width_rank"][i] >= 0.7 and ind["mom24"][i] > 0.03
            and ind["close"][i] > ind["bb_upper"][i] and ind["vol_r"][i] >= 1.5)
def momentum_obv_signal(ind, i):
    if i < 25: return False
    return (ind["mom24"][i] > 0.05 and ind["ema20"][i] > ind["ema50"][i]
            and ind["adx"][i] > 22 and ind["vol_r"][i] >= 1.3 and ind["obv_slope"][i] > 0)
def squeeze_release_signal(ind, i):
    if i < 22 or i < 5: return False
    if not all(ind["bb_width_rank"][k] < 0.30 for k in range(i-5, i)): return False
    return ind["close"][i] > ind["bb_upper"][i-1] and ind["vol_r"][i] > 1.3
SIG_FNS = [vol_expansion_signal, momentum_obv_signal, squeeze_release_signal]


def precompute_btc_regime(btc_ind):
    n = len(btc_ind["close"])
    high = btc_ind["high"]; low = btc_ind["low"]; close = btc_ind["close"]
    ema20 = btc_ind["ema20"]; ema50 = btc_ind["ema50"]
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    atr24 = np.zeros(n)
    for i in range(n):
        s = max(0, i - 23); atr24[i] = np.mean(tr[s:i+1])
    atr_rank = np.zeros(n)
    for i in range(n):
        s = max(0, i - 199); seg = atr24[s:i+1]
        atr_rank[i] = (seg <= atr24[i]).mean() if len(seg) else 0.5
    regime = np.zeros(n, dtype=bool)
    for i in range(n):
        regime[i] = (ema20[i] > ema50[i]) and (atr_rank[i] >= REGIME_ATR_MIN)
    return regime


def entry_v_reg_sym(ind, i, btc_regime_at_i, mom_min):
    if not btc_regime_at_i: return False
    if ind["mom24"][i] < mom_min: return False
    return any(fn(ind, i) for fn in SIG_FNS)


def simulate(ind, btc_regime, start_idx, end_idx, tp_roe, sl_roe, mom_min):
    trades = []
    in_pos = False; entry_px = 0.0; entry_idx = 0
    last_exit_i = -1; last_loss_i = -1
    slip = SLIPPAGE_BPS / 10000.0

    for i in range(max(start_idx, 30), end_idx):
        if not in_pos:
            if last_exit_i >= 0 and (i - last_exit_i) < COOLDOWN_AFTER_EXIT_H: continue
            if last_loss_i >= 0 and (i - last_loss_i) < COOLDOWN_AFTER_LOSS_H: continue
            btc_r = bool(btc_regime[i]) if i < len(btc_regime) else False
            if entry_v_reg_sym(ind, i, btc_r, mom_min):
                entry_px = ind["close"][i] * (1 + slip)
                entry_idx = i; in_pos = True
        else:
            hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
            roe_lo = (lo / entry_px - 1) * LEVERAGE * 100
            roe_hi = (hi / entry_px - 1) * LEVERAGE * 100
            roe_cl = (cl / entry_px - 1) * LEVERAGE * 100
            exit_roe = None; reason = None
            if roe_lo <= LIQ_ROE:
                exit_roe = -100.0; reason = "LIQ"
            elif roe_lo <= sl_roe:
                sl_px = entry_px * (1 + sl_roe/100/LEVERAGE)
                fill = sl_px * (1 - slip)
                exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                reason = "SL"
            elif roe_hi >= tp_roe:
                tp_px = entry_px * (1 + tp_roe/100/LEVERAGE)
                fill = tp_px * (1 - slip)
                exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                reason = "TP"
            else:
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
                trades.append({"pnl": pnl, "roe": exit_roe, "reason": reason, "hold_h": hold_h})
                in_pos = False; last_exit_i = i
                if pnl < 0: last_loss_i = i
    return trades


def per_symbol_grid(cache, btc_regime, folds, sym, tp_levels, sl_levels, mom_min):
    """Returns (matrix, best_cell) for one symbol."""
    matrix = {}
    best = None
    for tp in tp_levels:
        row = {}
        for sl in sl_levels:
            all_pnls = []; total_n = 0; wf_pass = 0
            for s, e in folds:
                fold_pnls = []
                trades = simulate(cache[sym], btc_regime, s, e, tp, sl, mom_min)
                fold_pnls.extend([t["pnl"] for t in trades])
                total_n += len(trades)
                if fold_pnls:
                    pnls = np.array(fold_pnls)
                    wins = pnls[pnls>0]; losses = pnls[pnls<0]
                    pf = wins.sum()/abs(losses.sum()) if losses.sum()<0 else 99
                    if pf > 1.0 and len(pnls) >= 3: wf_pass += 1
                    all_pnls.extend(fold_pnls)
            net = sum(all_pnls)
            row[sl] = {"net": net, "wf": wf_pass, "n": total_n}
            if net > 0 and wf_pass >= 3:
                if best is None or net > best["net"]:
                    best = {"tp": tp, "sl": sl, "net": net, "wf": wf_pass, "n": total_n}
        matrix[tp] = row
    return matrix, best


def run():
    universe = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT"]
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        ind = compute_indicators(df)
        ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    n = min(len(cache[s]["close"]) for s in universe)
    fold_size = n // 4
    folds = [(k*fold_size, (k+1)*fold_size if k<3 else n) for k in range(4)]

    tp_levels = [20, 30, 40, 50, 60, 80, 100, 150, 200]
    sl_levels = [-15, -20, -30, -40]
    mom_levels = [0.02, 0.03, 0.04, 0.05]

    print(f"\n=== Phase 30b: per-symbol fine grid + mom_min sweep ===")
    print(f"Bars: {n}, BTC regime ON: {btc_regime.mean()*100:.1f}%\n")

    summary = {}
    for mom_min in mom_levels:
        print(f"\n━━━ mom_min = {mom_min*100:.0f}% ━━━")
        for sym in universe:
            matrix, best = per_symbol_grid(cache, btc_regime, folds, sym,
                                            tp_levels, sl_levels, mom_min)
            n_robust = sum(1 for tp in tp_levels for sl in sl_levels
                           if matrix[tp][sl]["net"] > 0 and matrix[tp][sl]["wf"] >= 3)
            n_profit = sum(1 for tp in tp_levels for sl in sl_levels
                           if matrix[tp][sl]["net"] > 0)
            tot = len(tp_levels) * len(sl_levels)
            print(f"  {sym[:4]}: profitable={n_profit:>2d}/{tot}  WF-robust={n_robust:>2d}/{tot}  ", end="")
            if best:
                print(f"best=TP{best['tp']}/SL{best['sl']}: ${best['net']:+.0f} WF={best['wf']}/4 n={best['n']}")
            else:
                print("(no robust cell)")
            summary[f"{sym}_mom{int(mom_min*100)}"] = {
                "profitable": n_profit, "wf_robust": n_robust, "best": best
            }

    # also test universe-wide combo — only symbols+mom that show robust cells
    print(f"\n━━━ Combined universe (all 4 symbols, mom_min=3%) — 메이저 묶음 운영 ===")
    matrix_uni = {}
    for tp in tp_levels:
        row = {}
        for sl in sl_levels:
            all_pnls = []; total_n = 0; wf_pass = 0
            for s, e in folds:
                fold_pnls = []
                for sym in universe:
                    trades = simulate(cache[sym], btc_regime, s, e, tp, sl, 0.03)
                    fold_pnls.extend([t["pnl"] for t in trades])
                    total_n += len(trades)
                if fold_pnls:
                    pnls = np.array(fold_pnls)
                    wins = pnls[pnls>0]; losses = pnls[pnls<0]
                    pf = wins.sum()/abs(losses.sum()) if losses.sum()<0 else 99
                    if pf > 1.0 and len(pnls) >= 5: wf_pass += 1
                    all_pnls.extend(fold_pnls)
            net = sum(all_pnls)
            row[sl] = {"net": net, "wf": wf_pass, "n": total_n}
        matrix_uni[tp] = row

    print(f"{'TP\\SL':>8s}", end="")
    for sl in sl_levels: print(f"  {sl:>4d}%".rjust(13), end="")
    print()
    print("-" * 70)
    for tp in tp_levels:
        line = f"{tp:>4d}%   "
        for sl in sl_levels:
            r = matrix_uni[tp][sl]
            tag = "✅" if (r['net'] > 0 and r['wf'] >= 3) else ("⚠️" if r['net'] > 0 else "❌")
            line += f"  ${r['net']:+5.0f}{tag}{r['wf']}/4".rjust(13)
        print(line)

    # save
    out = Path("quant_runtime/output/walkforward_phase30b_majors_finegrid.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as fp:
        json.dump({"summary": summary, "universe_combined_mom3": matrix_uni},
                  fp, indent=2, default=str)
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    run()
