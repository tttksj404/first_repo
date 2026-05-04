#!/usr/bin/env python3
"""Phase 28: V_REG_SYM_SL30 수수료 / 슬리피지 스트레스 테스트.

CLAUDE.md 룰:
  1. fee/sl_dollar < 0.20  (수수료가 SL의 20% 미만)
  2. 슬리피지 0/5/10/15/20bps에서 5bps까지 수익이면 PASS
  3. fee 0.12% (현재) / 0.15% / 0.18% / 0.20%  민감도

전략 = WF 3/4 통과한 V_REG_SYM_SL30 (Phase27 winner)
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
FUNDING_8H = 0.0001
TP_ROE = 500.0
SL_ROE = -30.0
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


def simulate(ind, btc_regime, start_idx, end_idx, slip_bps, fee_rt):
    """Return list of trades and total cost breakdown."""
    trades = []
    in_pos = False; entry_px = 0.0; entry_idx = 0
    last_exit_i = -1; last_loss_i = -1
    slip = slip_bps / 10000.0
    total_fee = 0.0; total_slip_dollars = 0.0; total_funding = 0.0

    for i in range(max(start_idx, 30), end_idx):
        if not in_pos:
            if last_exit_i >= 0 and (i - last_exit_i) < COOLDOWN_AFTER_EXIT_H: continue
            if last_loss_i >= 0 and (i - last_loss_i) < COOLDOWN_AFTER_LOSS_H: continue
            btc_r = bool(btc_regime[i]) if i < len(btc_regime) else False
            if entry_v_reg_sym(ind, i, btc_r):
                clean_px = ind["close"][i]
                entry_px = clean_px * (1 + slip)
                # accumulate slip cost in dollars
                total_slip_dollars += MARGIN * LEVERAGE * slip
                entry_idx = i; in_pos = True
        else:
            hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
            roe_lo = (lo / entry_px - 1) * LEVERAGE * 100
            roe_hi = (hi / entry_px - 1) * LEVERAGE * 100
            roe_cl = (cl / entry_px - 1) * LEVERAGE * 100
            exit_roe = None; reason = None
            exit_clean_px = None
            if roe_lo <= LIQ_ROE:
                exit_roe = -100.0; reason = "LIQ"
            elif roe_lo <= SL_ROE:
                sl_px = entry_px * (1 + SL_ROE/100/LEVERAGE)
                exit_clean_px = sl_px
                fill = sl_px * (1 - slip)
                exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                reason = "SL"
            elif roe_hi >= TP_ROE:
                tp_px = entry_px * (1 + TP_ROE/100/LEVERAGE)
                exit_clean_px = tp_px
                fill = tp_px * (1 - slip)
                exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                reason = "TP"
            else:
                sig_now = any(fn(ind, i) for fn in SIG_FNS)
                if (not sig_now) and roe_cl > SIGNAL_OFF_MIN_ROE:
                    exit_clean_px = cl
                    fill = cl * (1 - slip)
                    exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                    reason = "SIG_OFF"
            if exit_roe is not None:
                if reason != "LIQ":
                    total_slip_dollars += MARGIN * LEVERAGE * slip
                hold_h = i - entry_idx
                notional = MARGIN * LEVERAGE
                fee = notional * fee_rt
                funding = notional * FUNDING_8H * (hold_h / 8)
                total_fee += fee; total_funding += funding
                if exit_roe <= -100:
                    pnl = -MARGIN - fee
                else:
                    pnl = MARGIN * (exit_roe / 100) - fee - funding
                trades.append({"pnl": pnl, "roe": exit_roe, "reason": reason, "hold_h": hold_h})
                in_pos = False; last_exit_i = i
                if pnl < 0: last_loss_i = i
    return trades, {"fee": total_fee, "slip$": total_slip_dollars, "funding": total_funding}


def stress_test():
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

    # === Slippage × Fee 매트릭스 ===
    slip_levels = [0, 5, 8, 10, 15, 20]   # bps per side
    fee_levels  = [0.0008, 0.0012, 0.0015, 0.0018, 0.0020]  # round-trip

    print(f"\n{'Slip\\Fee':>10s}", end="")
    for fee in fee_levels: print(f"  {fee*100:.2f}%RT".rjust(10), end="")
    print()
    print("-" * 70)

    matrix = {}
    for slip in slip_levels:
        row = {}
        line = f"{slip:>4d}bps    "
        for fee in fee_levels:
            all_pnls = []; total_costs = {"fee":0,"slip$":0,"funding":0}; total_n = 0
            wf_pass = 0
            for s, e in folds:
                fold_pnls = []
                for sym in universe:
                    trades, costs = simulate(cache[sym], btc_regime, s, e, slip, fee)
                    fold_pnls.extend([t["pnl"] for t in trades])
                    for k in costs: total_costs[k] += costs[k]
                    total_n += len(trades)
                if fold_pnls:
                    pnls = np.array(fold_pnls)
                    wins = pnls[pnls>0]; losses = pnls[pnls<0]
                    pf = wins.sum()/abs(losses.sum()) if losses.sum()<0 else 99
                    if pf > 1.0 and len(pnls) >= 5: wf_pass += 1
                    all_pnls.extend(fold_pnls)
            net = sum(all_pnls)
            tag = "✅" if wf_pass >= 3 else ("⚠️" if wf_pass == 2 else "❌")
            line += f"  ${net:+6.0f}{tag}".rjust(10)
            row[fee] = {"net": net, "wf": wf_pass, "n": total_n,
                        "costs": total_costs}
        print(line)
        matrix[slip] = row

    print("\nLegend: ✅ WF≥3/4 robust   ⚠️ WF=2/4 fragile   ❌ WF≤1/4 reject")

    # === 비용 분석: baseline (8bps + 0.12%) ===
    base = matrix[8][0.0012]
    print(f"\n=== 비용 분석 (baseline: 8bps slip + 0.12% RT fee) ===")
    print(f"연 trade 수: {base['n']}")
    print(f"수수료 총액: ${base['costs']['fee']:.2f}")
    print(f"슬리피지 총액: ${base['costs']['slip$']:.2f}")
    print(f"펀딩비 총액: ${base['costs']['funding']:.2f}")
    total_cost = base['costs']['fee'] + base['costs']['slip$'] + base['costs']['funding']
    gross = base['net'] + total_cost
    print(f"총 비용 합계: ${total_cost:.2f}")
    print(f"GROSS PnL (비용 전): ${gross:+.2f}")
    print(f"NET PnL (비용 후): ${base['net']:+.2f}")
    cost_pct = total_cost / gross * 100 if gross > 0 else 0
    print(f"비용이 GROSS에서 차지하는 비율: {cost_pct:.1f}%")
    fee_per_trade = base['costs']['fee'] / base['n']
    sl_dollar = abs(MARGIN * SL_ROE / 100)  # $15
    print(f"\nfee/SL 체크: ${fee_per_trade:.2f} / ${sl_dollar:.2f} = {fee_per_trade/sl_dollar:.3f}  "
          f"({'✅ < 0.20' if fee_per_trade/sl_dollar < 0.20 else '❌ ≥ 0.20'})")

    # === 5bps slip 통과 여부 (CLAUDE.md 룰) ===
    s5 = matrix[5][0.0012]
    print(f"\n5bps slip 통과: net=${s5['net']:+.0f}  WF={s5['wf']}/4  "
          f"{'✅ PASS (CLAUDE.md 통과)' if s5['net'] > 0 and s5['wf'] >= 3 else '❌ FAIL'}")

    # Save
    out = Path("quant_runtime/output/walkforward_phase28_fees.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    serialize = {f"slip{s}": {f"fee{int(f*10000)}": {k: v for k,v in matrix[s][f].items() if k!='costs'}
                              | {"costs": matrix[s][f]['costs']} for f in fee_levels}
                 for s in slip_levels}
    with open(out, "w") as fp:
        json.dump(serialize, fp, indent=2, default=str)
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    stress_test()
