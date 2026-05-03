#!/usr/bin/env python3
"""Phase 29: V_REG_SYM TP×SL 파라미터 감도 분석.

목표:
  Phase 27이 찾은 winner (TP=+500% / SL=-30%)가 lucky local maximum이
  아니라 *robust neighborhood* 인지 검증.

CLAUDE.md 룰 (확정 전 필수):
  "파라미터 감도: 인접 TP/SL 10+개 조합이 전부 수익이어야 함"

Grid: TP ∈ {300, 400, 500, 600, 700}  ×  SL ∈ {-20, -25, -30, -35, -40}
      = 25 조합

각 조합당 4-fold WF, V_REG_SYM 로직 (BTC regime + sym mom>5% + ensemble OR).
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
SYMBOL_MOM_MIN = 0.05
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
    close = btc_ind["close"]; high = btc_ind["high"]; low = btc_ind["low"]
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


def entry_v_reg_sym(ind, i, btc_regime_at_i):
    if not btc_regime_at_i: return False
    if ind["mom24"][i] < SYMBOL_MOM_MIN: return False
    return any(fn(ind, i) for fn in SIG_FNS)


def simulate(ind, btc_regime, start_idx, end_idx, tp_roe, sl_roe):
    trades = []
    in_pos = False; entry_px = 0.0; entry_idx = 0
    last_exit_i = -1; last_loss_i = -1
    slip = SLIPPAGE_BPS / 10000.0

    for i in range(max(start_idx, 30), end_idx):
        if not in_pos:
            if last_exit_i >= 0 and (i - last_exit_i) < COOLDOWN_AFTER_EXIT_H: continue
            if last_loss_i >= 0 and (i - last_loss_i) < COOLDOWN_AFTER_LOSS_H: continue
            btc_r = bool(btc_regime[i]) if i < len(btc_regime) else False
            if entry_v_reg_sym(ind, i, btc_r):
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


def grid_test():
    universe = ["PEPEUSDT", "WIFUSDT", "DOGEUSDT"]
    cache = {}
    for sym in universe + ["BTCUSDT"]:
        df = load_1h(sym)
        ind = compute_indicators(df)
        ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    n = min(len(cache[s]["close"]) for s in universe + ["BTCUSDT"])
    fold_size = n // 4
    folds = [(k*fold_size, (k+1)*fold_size if k<3 else n) for k in range(4)]

    tp_levels = [300, 400, 500, 600, 700]
    sl_levels = [-20, -25, -30, -35, -40]

    print(f"\n{'TP\\SL':>8s}", end="")
    for sl in sl_levels: print(f"  {sl:>4d}%".rjust(11), end="")
    print()
    print("-" * 80)

    matrix = {}
    profitable_count = 0
    wf_pass_count = 0
    total_count = 0

    for tp in tp_levels:
        row = {}
        line = f"{tp:>4d}%   "
        for sl in sl_levels:
            all_pnls = []; total_n = 0; wf_pass = 0
            for s, e in folds:
                fold_pnls = []
                for sym in universe:
                    trades = simulate(cache[sym], btc_regime, s, e, tp, sl)
                    fold_pnls.extend([t["pnl"] for t in trades])
                    total_n += len(trades)
                if fold_pnls:
                    pnls = np.array(fold_pnls)
                    wins = pnls[pnls>0]; losses = pnls[pnls<0]
                    pf = wins.sum()/abs(losses.sum()) if losses.sum()<0 else 99
                    if pf > 1.0 and len(pnls) >= 5: wf_pass += 1
                    all_pnls.extend(fold_pnls)
            net = sum(all_pnls)
            tag = "✅" if (net > 0 and wf_pass >= 3) else ("⚠️" if net > 0 else "❌")
            line += f"  ${net:+5.0f}{tag}{wf_pass}/4".rjust(11)
            row[sl] = {"net": net, "wf": wf_pass, "n": total_n}
            total_count += 1
            if net > 0: profitable_count += 1
            if net > 0 and wf_pass >= 3: wf_pass_count += 1
        print(line)
        matrix[tp] = row

    print(f"\n총 조합: {total_count}")
    print(f"수익 (>$0): {profitable_count}/{total_count} ({profitable_count/total_count*100:.0f}%)")
    print(f"수익 + WF≥3/4: {wf_pass_count}/{total_count} ({wf_pass_count/total_count*100:.0f}%)")
    print(f"\nLegend: ✅ 수익 + WF≥3/4   ⚠️ 수익만 (WF<3)   ❌ 손실")

    # CLAUDE.md rule
    print(f"\n=== CLAUDE.md 룰: 인접 10+ 조합 전부 수익 ===")
    if profitable_count == total_count:
        print(f"  ✅ PASS — 전 25 조합 수익 (가장 강한 robustness)")
    elif profitable_count >= 20:
        print(f"  ✅ PASS — {profitable_count}/25 수익 (≥20)")
    elif profitable_count >= 15:
        print(f"  ⚠️ MARGINAL — {profitable_count}/25 수익 (15~19)")
    elif profitable_count >= 10:
        print(f"  ⚠️ WEAK — {profitable_count}/25 수익 (10~14)")
    else:
        print(f"  ❌ FAIL — only {profitable_count}/25 수익 (<10) — winner는 lucky")

    # winner 자세히
    base = matrix[500][-30]
    print(f"\n=== Winner (TP+500/SL-30) 상세 ===")
    print(f"  net=${base['net']:+.0f}  WF={base['wf']}/4  trades={base['n']}")

    # 인접 4 셀 (TP±100 × SL±5)
    print(f"\n=== 인접 4 cell (TP±100, SL±5) ===")
    neighbors = [(400,-25), (400,-35), (600,-25), (600,-35)]
    n_pass = 0
    for tp, sl in neighbors:
        r = matrix[tp][sl]
        ok = r['net'] > 0
        if ok: n_pass += 1
        print(f"  TP+{tp}/SL{sl}: net=${r['net']:+5.0f}  WF={r['wf']}/4  {'✅' if ok else '❌'}")
    print(f"  → {n_pass}/4 인접 셀 수익")

    # Save
    out = Path("quant_runtime/output/walkforward_phase29_param_sens.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    serialize = {f"tp{tp}": {f"sl{sl}": matrix[tp][sl] for sl in sl_levels}
                 for tp in tp_levels}
    serialize["_summary"] = {
        "total": total_count,
        "profitable": profitable_count,
        "wf_pass": wf_pass_count,
        "winner_neighbor_pass": n_pass,
    }
    with open(out, "w") as fp:
        json.dump(serialize, fp, indent=2, default=str)
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    grid_test()
