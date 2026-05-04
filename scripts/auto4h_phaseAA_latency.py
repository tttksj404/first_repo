#!/usr/bin/env python3
"""Phase AA: Latency stress test.

실제 라이브 = 봇은 ccxt fetch → signal calc → order place 까지 5~30초 지연.
1m close 시점 시그널 발화하면 entry 는 1m+1bar 로 늦어짐.
1h timeframe 에선 entry 가 다음 bar open 으로 늦춤이 된다.

테스트: entry_idx 를 +1 / +2 / +3 bar 만큼 미루고 OOS PF/net 변화 측정.
+1 = 1h delay (next bar open), +2 = 2h delay, +3 = 3h delay.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv
from auto4h_signal_library import SIGNALS
from auto4h_phaseQ_short_side import (
    SHORT_SIGNALS, precompute_bear_regime,
)
from auto4h_phaseV_extra_shorts import EXTRA_SHORT_SIGNALS
from auto4h_stage1_matrix import precompute_btc_regime

ALL_SHORT_SIGNALS = {**SHORT_SIGNALS, **EXTRA_SHORT_SIGNALS}

LEVERAGE = 10
MARGIN = 50.0
COST_RT = 0.0012
FUNDING_8H = 0.0001
SLIPPAGE_BPS = 8
LIQ_ROE = -95.0
COOLDOWN_EXIT = 12
COOLDOWN_LOSS = 24


def sim_with_delay(ind, gate, sig_fn, start, end, tp, sl, mom, side, delay_bars):
    """Long if side='long', short otherwise. delay_bars = lag between signal and entry."""
    trades = []
    in_pos = False; entry_px = 0; entry_idx = 0
    last_exit = -1; last_loss = -1
    slip = SLIPPAGE_BPS / 10000.0
    for i in range(max(start, 50), end):
        if not in_pos:
            if last_exit >= 0 and (i - last_exit) < COOLDOWN_EXIT: continue
            if last_loss >= 0 and (i - last_loss) < COOLDOWN_LOSS: continue
            # signal evaluated at trigger bar i-delay_bars; entry at bar i
            sig_i = i - delay_bars
            if sig_i < 0: continue
            if sig_i < len(gate) and not gate[sig_i]: continue
            if side == "long":
                if ind["mom24"][sig_i] < mom: continue
            else:
                if ind["mom24"][sig_i] > mom: continue
            if not sig_fn(ind, sig_i): continue
            # enter at current bar's open (proxy: prev close)
            entry_px = ind["close"][i] * (1 + slip if side=="long" else 1 - slip)
            entry_idx = i; in_pos = True
        else:
            hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
            if side == "long":
                roe_lo = (lo / entry_px - 1) * LEVERAGE * 100
                roe_hi = (hi / entry_px - 1) * LEVERAGE * 100
                roe_cl = (cl / entry_px - 1) * LEVERAGE * 100
            else:
                roe_lo = (entry_px / lo - 1) * LEVERAGE * 100
                roe_hi = (entry_px / hi - 1) * LEVERAGE * 100
                roe_cl = (entry_px / cl - 1) * LEVERAGE * 100
            exit_roe = None
            if side == "long":
                if roe_lo <= LIQ_ROE: exit_roe = -100
                elif roe_lo <= sl:
                    sl_px = entry_px * (1 + sl/100/LEVERAGE)
                    exit_roe = (sl_px*(1-slip)/entry_px-1)*LEVERAGE*100
                elif roe_hi >= tp:
                    tp_px = entry_px * (1 + tp/100/LEVERAGE)
                    exit_roe = (tp_px*(1-slip)/entry_px-1)*LEVERAGE*100
                elif (not sig_fn(ind, i)) and roe_cl > 0:
                    exit_roe = (cl*(1-slip)/entry_px-1)*LEVERAGE*100
            else:
                if roe_hi <= LIQ_ROE: exit_roe = -100
                elif roe_hi <= sl:
                    sl_px = entry_px * (1 - sl/100/LEVERAGE)
                    exit_roe = (entry_px/(sl_px*(1+slip))-1)*LEVERAGE*100
                elif roe_lo >= tp:
                    tp_px = entry_px * (1 - tp/100/LEVERAGE)
                    exit_roe = (entry_px/(tp_px*(1+slip))-1)*LEVERAGE*100
                elif (not sig_fn(ind, i)) and roe_cl > 0:
                    exit_roe = (entry_px/(cl*(1+slip))-1)*LEVERAGE*100
            if exit_roe is not None:
                hold = i - entry_idx
                notional = MARGIN * LEVERAGE
                pnl = -MARGIN-notional*COST_RT if exit_roe<=-100 else MARGIN*(exit_roe/100) - notional*COST_RT - notional*FUNDING_8H*(hold/8)
                trades.append({"pnl": pnl})
                in_pos = False; last_exit = i
                if pnl < 0: last_loss = i
    return trades


def folds_split(n, train_frac=0.7):
    train_end = int(n * train_frac)
    return [(train_end, n)]


LONG_SET = [
    ("eth_donchian", "donchian_20", "ETHUSDT", 0.02, 50, -35),
    ("sui_atrexp_2", "atr_expansion", "SUIUSDT", 0.02, 80, -35),
    ("doge_volexp_4", "vol_expansion", "DOGEUSDT", 0.04, 80, -30),
    ("wif_heikin", "heikin_cont", "WIFUSDT", 0.06, 100, -25),
    ("ada_heikin_2", "heikin_cont", "ADAUSDT", 0.02, 300, -50),
    ("pepe_atrexp", "atr_expansion", "PEPEUSDT", 0.08, 300, -50),
    ("op_atrexp", "atr_expansion", "OPUSDT", 0.06, 300, -50),
]
SHORT_SET = [
    ("eth_heikin_S", "short_heikin_cont", "ETHUSDT", -0.04, 80, -30),
    ("near_atrexp_S", "short_atr_expansion", "NEARUSDT", -0.02, 200, -40),
    ("sui_momobv_S", "short_momentum_obv", "SUIUSDT", -0.06, 200, -40),
    ("arb_rsi_S", "short_rsi_breakdown", "ARBUSDT", -0.02, 200, -40),
    ("dot_adx_S", "short_adx_trend_dn", "DOTUSDT", -0.02, 150, -35),
    ("link_adx_S", "short_adx_trend_dn", "LINKUSDT", -0.06, 200, -40),
]


def eval_one(ind, gate, fn, oos, tp, sl, mom, side, delay):
    s, e = oos[0]
    ts = sim_with_delay(ind, gate, fn, s, e, tp, sl, mom, side, delay)
    pnls = [t["pnl"] for t in ts]
    if not pnls: return {"pf": 0, "net": 0, "n": 0}
    a = np.array(pnls)
    pf = a[a>0].sum() / max(abs(a[a<0].sum()), 1e-9)
    return {"pf": float(pf), "net": float(a.sum()), "n": len(a)}


def run():
    print("Phase AA: latency stress (entry delay 0/1/2/3 bars)")
    universe = sorted(set([s[2] for s in LONG_SET] + [s[2] for s in SHORT_SET]) | {"BTCUSDT"})
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_long = precompute_btc_regime(cache["BTCUSDT"])
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())
    oos = folds_split(n_min)

    print(f"\n{'sid':<16} {'side':<5} | {'d=0_pf':>6} {'d=0_net':>7} | "
          f"{'d=1_pf':>6} {'d=1_net':>7} | {'d=2_pf':>6} {'d=2_net':>7} | {'d=3_pf':>6} {'d=3_net':>7}")
    out = []
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache: continue
        ind = cache[sym]; fn = SIGNALS[sig]
        rs = [eval_one(ind, btc_long, fn, oos, tp, sl, mom, "long", d) for d in (0,1,2,3)]
        out.append({"sid": sid, "side": "long", "delays": rs})
        print(f"{sid:<16} long  | {rs[0]['pf']:>6.2f} ${rs[0]['net']:+5.0f} | "
              f"{rs[1]['pf']:>6.2f} ${rs[1]['net']:+5.0f} | "
              f"{rs[2]['pf']:>6.2f} ${rs[2]['net']:+5.0f} | "
              f"{rs[3]['pf']:>6.2f} ${rs[3]['net']:+5.0f}")
    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache: continue
        ind = cache[sym]; fn = ALL_SHORT_SIGNALS[sig]
        rs = [eval_one(ind, btc_bear, fn, oos, tp, sl, mom, "short", d) for d in (0,1,2,3)]
        out.append({"sid": sid, "side": "short", "delays": rs})
        print(f"{sid:<16} short | {rs[0]['pf']:>6.2f} ${rs[0]['net']:+5.0f} | "
              f"{rs[1]['pf']:>6.2f} ${rs[1]['net']:+5.0f} | "
              f"{rs[2]['pf']:>6.2f} ${rs[2]['net']:+5.0f} | "
              f"{rs[3]['pf']:>6.2f} ${rs[3]['net']:+5.0f}")

    # aggregate degradation
    def degr(d):
        b = sum(r["delays"][0]["net"] for r in out)
        x = sum(r["delays"][d]["net"] for r in out)
        return x, (x-b) if b!=0 else 0
    print(f"\n=== Total OOS net by delay ===")
    for d in (0,1,2,3):
        tot = sum(r["delays"][d]["net"] for r in out)
        print(f"  delay={d}h: ${tot:+.0f}")
    out_path = Path("quant_runtime/output/auto4h/phaseAA_latency.json")
    with open(out_path, "w") as f:
        json.dump({"results": out}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
