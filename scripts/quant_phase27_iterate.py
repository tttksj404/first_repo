#!/usr/bin/env python3
"""Phase 27: V_REGIME 강화 변형 — Q3 출혈 막기 위한 마지막 시도.

V_REGIME 결과: WF 2/4, PnL +$337/y, Q3 -$173 (chop period에서 false breakout 다발)

추가 변형:
  V_REG_SL30  : V_REGIME + SL=-30% (loss cap -$15/회), TP=+500 유지
  V_REG_STRICT: BTC regime을 더 까다롭게 (BTC mom24>2% + atr_rank>=0.5)
  V_REG_SYM   : V_REGIME + symbol mom24>5% 추가 필터 (강한 trend만)
  V_REG_ALL   : 위 3개 모두 결합 (가장 보수적)
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


SIG_FNS = [vol_expansion_signal, momentum_obv_signal, squeeze_release_signal]


def precompute_btc_regime(btc_ind, mom_threshold=0.0, atr_min=0.4):
    """Returns (regime_normal, regime_strict)."""
    n = len(btc_ind["close"])
    close = btc_ind["close"]; high = btc_ind["high"]; low = btc_ind["low"]
    ema20 = btc_ind["ema20"]; ema50 = btc_ind["ema50"]
    mom24 = btc_ind["mom24"]
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
        regime[i] = (ema20[i] > ema50[i]) and (atr_rank[i] >= atr_min) and (mom24[i] > mom_threshold)
    return regime


# ===== ENTRY VARIANTS =====
def entry_reg(ind, i, btc_regime_at_i):
    if not btc_regime_at_i: return False
    return any(fn(ind, i) for fn in SIG_FNS)

def entry_reg_sym(ind, i, btc_regime_at_i):
    """REGIME + symbol mom24>5% 추가."""
    if not btc_regime_at_i: return False
    if ind["mom24"][i] < 0.05: return False
    return any(fn(ind, i) for fn in SIG_FNS)


# ===== SIMULATOR with optional SL =====
def simulate_fold(ind, btc_regime, entry_fn, start_idx, end_idx, sl_roe=None):
    """sl_roe: None = NoSL. -30 = exit at -30% ROE."""
    trades = []
    in_pos = False; entry_px = 0.0; entry_idx = 0
    last_exit_i = -1; last_loss_i = -1
    slip = SLIPPAGE_BPS / 10000.0
    for i in range(max(start_idx, 30), end_idx):
        if not in_pos:
            if last_exit_i >= 0 and (i - last_exit_i) < COOLDOWN_AFTER_EXIT_H: continue
            if last_loss_i >= 0 and (i - last_loss_i) < COOLDOWN_AFTER_LOSS_H: continue
            btc_r = bool(btc_regime[i]) if i < len(btc_regime) else False
            if entry_fn(ind, i, btc_r):
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
            elif sl_roe is not None and roe_lo <= sl_roe:
                # SL hit intra-bar; exit at SL price + slippage
                sl_px = entry_px * (1 + sl_roe/100/LEVERAGE)
                fill = sl_px * (1 - slip)
                exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                reason = "SL"
            elif roe_hi >= TP_ROE:
                tp_px = entry_px * (1 + TP_ROE/100/LEVERAGE)
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
                trades.append({"pnl": pnl, "roe": exit_roe, "hold_h": hold_h, "reason": reason})
                in_pos = False; last_exit_i = i
                if pnl < 0: last_loss_i = i
    return trades


def fold_metrics(trades):
    if not trades: return {"n": 0, "wr": 0, "pf": 0, "ev": 0, "total": 0}
    pnls = np.array([t["pnl"] for t in trades])
    wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() < 0 else 99.99
    return {"n": len(trades), "wr": float((pnls > 0).mean()*100), "pf": float(pf),
            "ev": float(pnls.mean()), "total": float(pnls.sum()),
            "n_liq": int(sum(1 for t in trades if t["reason"]=="LIQ")),
            "n_sl": int(sum(1 for t in trades if t["reason"]=="SL")),
            "n_tp": int(sum(1 for t in trades if t["reason"]=="TP"))}


def run_variant(name, cache, btc_regime, entry_fn, sl_roe, folds, universe):
    sig_passes = 0; fold_data = {}
    for f_idx, (s, e) in enumerate(folds):
        fold_pnls = []
        for sym in universe:
            trades = simulate_fold(cache[sym], btc_regime, entry_fn, s, e, sl_roe)
            fold_pnls.extend([t["pnl"] for t in trades])
        if fold_pnls:
            m = fold_metrics([{"pnl":p,"roe":0,"hold_h":0,"reason":""} for p in fold_pnls])
            fold_pass = m["pf"] > 1.0 and m["n"] >= 5
            if fold_pass: sig_passes += 1
            fold_data[f"Q{f_idx+1}"] = m
        else:
            fold_data[f"Q{f_idx+1}"] = {"n":0}
    n_total = sum(fd.get("n",0) for fd in fold_data.values())
    total_pnl = sum(fd.get("total",0) for fd in fold_data.values())
    verdict = "✅ ROBUST" if sig_passes>=3 else "⚠️ FRAGILE" if sig_passes==2 else "❌ REJECT"
    return {"name": name, "wf": sig_passes, "verdict": verdict,
            "n": n_total, "pnl": total_pnl, "folds": fold_data}


def run():
    universe = ["PEPEUSDT", "WIFUSDT", "DOGEUSDT"]
    cache = {}
    for sym in universe + ["BTCUSDT"]:
        df = load_1h(sym)
        ind = compute_indicators(df)
        ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_norm = precompute_btc_regime(cache["BTCUSDT"], mom_threshold=0.0, atr_min=0.4)
    btc_strict = precompute_btc_regime(cache["BTCUSDT"], mom_threshold=0.02, atr_min=0.5)
    print(f"BTC regime ON: normal={btc_norm.mean()*100:.1f}%  strict={btc_strict.mean()*100:.1f}%")

    n = min(len(cache[s]["close"]) for s in universe + ["BTCUSDT"])
    fold_size = n // 4
    folds = [(k*fold_size, (k+1)*fold_size if k<3 else n) for k in range(4)]

    # === RUN VARIANTS ===
    variants = [
        ("V_REG (baseline)",      btc_norm,   entry_reg,     None),
        ("V_REG_SL30",            btc_norm,   entry_reg,     -30),
        ("V_REG_SL50",            btc_norm,   entry_reg,     -50),
        ("V_REG_STRICT",          btc_strict, entry_reg,     None),
        ("V_REG_STRICT_SL30",     btc_strict, entry_reg,     -30),
        ("V_REG_SYM",             btc_norm,   entry_reg_sym, None),
        ("V_REG_SYM_SL30",        btc_norm,   entry_reg_sym, -30),
        ("V_REG_ALL (strict+sym+SL30)", btc_strict, entry_reg_sym, -30),
    ]

    results = {}
    print(f"\n{'Variant':35s} {'WF':>4} {'verdict':12s} {'n/y':>5} {'PnL$/y':>9}  {'Q1/Q2/Q3/Q4 PnL':>40s}")
    print("=" * 130)
    for name, regime, fn, sl in variants:
        r = run_variant(name, cache, regime, fn, sl, folds, universe)
        q_pnls = " ".join(f"{r['folds'].get(f'Q{k+1}',{}).get('total',0):+6.0f}" for k in range(4))
        print(f"  {name:33s} {r['wf']}/4  {r['verdict']:12s} {r['n']:>5}  ${r['pnl']:>+8.1f}  {q_pnls}")
        results[name] = r

    # Save
    out_path = Path("quant_runtime/output/walkforward_phase27.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # WINNER selection
    print("\n" + "=" * 70)
    robust = [(n,r) for n,r in results.items() if r['wf'] >= 3]
    if robust:
        winner_name, winner = max(robust, key=lambda kv: kv[1]['pnl'])
        print(f"🏆 ROBUST WINNER: {winner_name}")
        print(f"   WF={winner['wf']}/4  PnL=${winner['pnl']:+.1f}/y  n={winner['n']}")
    else:
        # Best fragile (WF==2) with positive PnL
        frag = [(n,r) for n,r in results.items() if r['wf']==2 and r['pnl']>0]
        if frag:
            winner_name, winner = max(frag, key=lambda kv: kv[1]['pnl'])
            print(f"⚠️ NO ROBUST. Best FRAGILE: {winner_name}")
            print(f"   WF={winner['wf']}/4  PnL=${winner['pnl']:+.1f}/y  n={winner['n']}")
        else:
            winner_name = None
            print("🚨 NO VIABLE STRATEGY found")
    return winner_name, results


if __name__ == "__main__":
    run()
