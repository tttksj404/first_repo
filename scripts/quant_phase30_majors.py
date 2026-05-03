#!/usr/bin/env python3
"""Phase 30: 메이저 (BTC/ETH/XRP/SOL) 백테 + walk-forward.

목표: 메메즈 봇 (Phase 29) 옆에 메이저 봇을 별도 자본으로 병행 운영 가능한가?

차이점 vs 메메즈:
  - 변동성 작아서 TP+500% (=가격+50%) 거의 안 옴 → 더 작은 TP 후보 포함
  - mom24 threshold 낮춤 (5% → 3%)  메이저는 5% 모멘텀 드뭄
  - SL은 동일하게 -20~-50% ROE 그리드

Logic (V_REG_SYM_majors):
  Gate 1: BTC regime ON (ema20>ema50 + ATR rank ≥0.4)  ← 메이저도 BTC 추세에 종속
  Gate 2: symbol mom24 ≥ MOM_MIN
  Gate 3: ensemble OR (vol_expansion / momentum_obv / squeeze_release)
  Gate 4: cooldown (12h after exit, 24h after loss)

Grid:
  TP ∈ {80, 100, 150, 200, 300, 500}  (% ROE)
  SL ∈ {-20, -30, -40, -50}
  MOM_MIN = 0.03 (3% — 메이저용 완화)
  → 24 combo × WF 4-fold

CLAUDE.md 검증:
  fee/SL < 0.20 (10x×$5 margin → fee=$0.06, SL=$1, 0.06 ✅)
  WF ≥ 3/4
  param sensitivity: 인접 10+ 조합 수익
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
MARGIN = 50.0  # 백테 단위 — 라이브와 비례
COST_RT = 0.0012
FUNDING_8H = 0.0001
SLIPPAGE_BPS = 8
LIQ_ROE = -95.0
SIGNAL_OFF_MIN_ROE = 0.0
COOLDOWN_AFTER_EXIT_H = 12
COOLDOWN_AFTER_LOSS_H = 24
SYMBOL_MOM_MIN = 0.03  # 메이저용 완화
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

    print(f"\n=== Phase 30: BTC/ETH/XRP/SOL backtest ===")
    print(f"Bars per symbol: {n}  ({n/24/30:.1f} months)")
    print(f"BTC regime ON: {btc_regime.sum()}/{len(btc_regime)} ({btc_regime.mean()*100:.1f}%)")
    print(f"Mom24 ≥ {SYMBOL_MOM_MIN*100:.0f}% threshold")

    # === per-symbol baseline (TP+200/SL-30 으로 일단) ===
    print(f"\n--- per-symbol breakdown (TP+200/SL-30) ---")
    print(f"{'sym':>5} {'n':>4} {'WR%':>6} {'avg_w':>7} {'avg_l':>7} {'PF':>6} {'NET$':>8}")
    per_sym = {}
    for sym in universe:
        all_trades = []
        for s, e in folds:
            all_trades.extend(simulate(cache[sym], btc_regime, s, e, 200, -30))
        if all_trades:
            pnls = np.array([t["pnl"] for t in all_trades])
            wins = pnls[pnls>0]; losses = pnls[pnls<0]
            wr = (pnls>0).mean()*100
            pf = wins.sum()/abs(losses.sum()) if losses.sum()<0 else 99
            print(f"{sym[:4]:>5} {len(pnls):>4} {wr:>5.1f}% "
                  f"{wins.mean() if len(wins) else 0:>+7.2f} "
                  f"{losses.mean() if len(losses) else 0:>+7.2f} "
                  f"{pf:>6.2f} {pnls.sum():>+8.2f}")
            per_sym[sym] = {"n": len(pnls), "wr": float(wr), "pf": float(pf),
                            "net": float(pnls.sum())}
        else:
            print(f"{sym[:4]:>5} (0 trades)")

    # === TP × SL grid ===
    tp_levels = [80, 100, 150, 200, 300, 500]
    sl_levels = [-20, -30, -40, -50]

    print(f"\n--- TP × SL grid (universe net$ / WF score) ---")
    print(f"{'TP\\SL':>8s}", end="")
    for sl in sl_levels: print(f"  {sl:>4d}%".rjust(13), end="")
    print()
    print("-" * 80)

    matrix = {}
    profitable_count = 0
    wf_pass_count = 0
    total_count = 0
    best_cell = None

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
            line += f"  ${net:+5.0f}{tag}{wf_pass}/4n{total_n}".rjust(13)
            row[sl] = {"net": net, "wf": wf_pass, "n": total_n}
            total_count += 1
            if net > 0: profitable_count += 1
            if net > 0 and wf_pass >= 3:
                wf_pass_count += 1
                if best_cell is None or net > best_cell["net"]:
                    best_cell = {"tp": tp, "sl": sl, "net": net, "wf": wf_pass, "n": total_n}
        print(line)
        matrix[tp] = row

    print(f"\nTotal {total_count} cells   |   profitable={profitable_count}   "
          f"|   WF≥3/4 + profit={wf_pass_count}")
    print(f"Legend: ✅ 수익 + WF≥3/4   ⚠️ 수익만 (WF<3)   ❌ 손실")

    # === verdict ===
    print(f"\n=== 메이저 PHASE 30 판정 ===")
    if wf_pass_count >= 10 and best_cell:
        print(f"  ✅ ROBUST — {wf_pass_count}/{total_count} cells PASS")
        print(f"  Best: TP+{best_cell['tp']}/SL{best_cell['sl']} → "
              f"${best_cell['net']:+.0f}  WF={best_cell['wf']}/4  n={best_cell['n']}")
        # fee/SL check
        fee = MARGIN * LEVERAGE * COST_RT
        sl_dollar = abs(MARGIN * best_cell['sl'] / 100)
        print(f"  fee/SL: ${fee:.2f}/${sl_dollar:.2f} = {fee/sl_dollar:.3f}  "
              f"({'✅ <0.20' if fee/sl_dollar < 0.20 else '❌ ≥0.20'})")
    elif wf_pass_count >= 5 and best_cell:
        print(f"  ⚠️ MARGINAL — only {wf_pass_count}/{total_count} cells WF-robust")
        print(f"  Best: TP+{best_cell['tp']}/SL{best_cell['sl']} → ${best_cell['net']:+.0f}")
    else:
        print(f"  ❌ REJECT — only {wf_pass_count}/{total_count} cells WF-robust")
        if best_cell:
            print(f"  best (still risky): TP+{best_cell['tp']}/SL{best_cell['sl']} → ${best_cell['net']:+.0f}")

    # save
    out = Path("quant_runtime/output/walkforward_phase30_majors.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    serialize = {
        "universe": universe,
        "mom_min": SYMBOL_MOM_MIN,
        "n_bars": int(n),
        "btc_regime_on_pct": float(btc_regime.mean()*100),
        "per_symbol_at_TP200_SL30": per_sym,
        "grid": {f"tp{tp}": {f"sl{sl}": matrix[tp][sl] for sl in sl_levels}
                 for tp in tp_levels},
        "summary": {"total": total_count, "profitable": profitable_count,
                    "wf_pass": wf_pass_count, "best": best_cell},
    }
    with open(out, "w") as fp:
        json.dump(serialize, fp, indent=2, default=str)
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    grid_test()
