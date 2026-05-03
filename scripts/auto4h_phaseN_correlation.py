#!/usr/bin/env python3
"""Phase N: Strategy correlation matrix.

17 paper bot strategies 의 entry/exit 시점이 너무 겹치면 동시 진입 위험.
각 strategy 의 trade-by-trade pnl + entry timestamp 기준으로 상관관계 측정.
높은 상관 (≥0.7) pair 는 페어링 후보 (둘 중 하나만 운영).
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv
from auto4h_signal_library import SIGNALS
from auto4h_stage1_matrix import precompute_btc_regime, simulate

LEVERAGE = 10
MARGIN = 50.0


# 17 paper bot strategies (sid, sig, sym, mom, tp, sl)
STRATEGIES = [
    ("eth_donchian",   "donchian_20",   "ETHUSDT",  0.02,  50, -35),
    ("eth_volexp_2",   "vol_expansion", "ETHUSDT",  0.02,  50, -25),
    ("sui_atrexp_4",   "atr_expansion", "SUIUSDT",  0.04, 150, -40),
    ("sui_atrexp_2",   "atr_expansion", "SUIUSDT",  0.02,  80, -35),
    ("arb_volexp",     "vol_expansion", "ARBUSDT",  0.04,  50, -20),
    ("doge_volexp_4",  "vol_expansion", "DOGEUSDT", 0.04,  80, -30),
    ("doge_volexp_2",  "vol_expansion", "DOGEUSDT", 0.02,  80, -30),
    ("doge_heikin",    "heikin_cont",   "DOGEUSDT", 0.06,  80, -35),
    ("doge_momobv",    "momentum_obv",  "DOGEUSDT", 0.02,  80, -30),
    ("wif_momobv",     "momentum_obv",  "WIFUSDT",  0.02, 300, -25),
    ("wif_heikin",     "heikin_cont",   "WIFUSDT",  0.06, 100, -25),
    ("ada_heikin_300", "heikin_cont",   "ADAUSDT",  0.04, 300, -50),
    ("ada_heikin_150", "heikin_cont",   "ADAUSDT",  0.04, 150, -35),
    ("ada_heikin_200", "heikin_cont",   "ADAUSDT",  0.04, 200, -40),
    ("ada_heikin_2",   "heikin_cont",   "ADAUSDT",  0.02, 300, -50),
    ("op_atrexp",      "atr_expansion", "OPUSDT",   0.06, 300, -50),
    ("pepe_atrexp",    "atr_expansion", "PEPEUSDT", 0.08, 300, -50),
]


def run():
    print("Phase N: strategy correlation matrix")
    universe = sorted(set(s[2] for s in STRATEGIES) | {"BTCUSDT"})
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())

    # collect all entries per strategy
    entries = {}  # sid → list of (entry_idx, exit_idx, pnl)
    for sid, sig_name, sym, mom, tp, sl in STRATEGIES:
        if sym not in cache: continue
        sig_fn = SIGNALS[sig_name]; ind = cache[sym]
        # full window single fold
        ts_list = simulate(ind, btc_regime, sig_fn, 50, n_min, tp, sl, mom)
        # simulate doesn't return entry/exit idx — re-implement minimally
        # we'll use a custom version
        entries[sid] = ts_list

    # build per-bar position vector for each strategy (1 if in pos, 0 else)
    # Need to re-simulate with idx tracking. Re-implement simple version.
    def sim_with_idx(ind, fn, tp, sl, mom):
        slip = 8/10000.0
        in_pos = False; ent_idx = 0; ent_px = 0.0
        last_exit = -1; last_loss = -1
        out = []
        for i in range(50, n_min):
            if not in_pos:
                if last_exit >= 0 and (i - last_exit) < 12: continue
                if last_loss >= 0 and (i - last_loss) < 24: continue
                if i < len(btc_regime) and not btc_regime[i]: continue
                if ind["mom24"][i] < mom: continue
                if not fn(ind, i): continue
                ent_px = ind["close"][i] * (1+slip); ent_idx = i; in_pos = True
            else:
                hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
                roe_lo = (lo/ent_px - 1)*LEVERAGE*100
                roe_hi = (hi/ent_px - 1)*LEVERAGE*100
                roe_cl = (cl/ent_px - 1)*LEVERAGE*100
                exit_roe = None
                if roe_lo <= -95: exit_roe = -100
                elif roe_lo <= sl:
                    sl_px = ent_px*(1+sl/100/LEVERAGE)
                    exit_roe = (sl_px*(1-slip)/ent_px - 1)*LEVERAGE*100
                elif roe_hi >= tp:
                    tp_px = ent_px*(1+tp/100/LEVERAGE)
                    exit_roe = (tp_px*(1-slip)/ent_px - 1)*LEVERAGE*100
                elif (not fn(ind, i)) and roe_cl > 0:
                    exit_roe = (cl*(1-slip)/ent_px - 1)*LEVERAGE*100
                if exit_roe is not None:
                    hold = i - ent_idx
                    notional = MARGIN*LEVERAGE
                    pnl = -MARGIN-notional*0.0012 if exit_roe<=-100 else MARGIN*(exit_roe/100) - notional*0.0012 - notional*0.0001*(hold/8)
                    out.append((ent_idx, i, pnl))
                    in_pos = False; last_exit = i
                    if pnl < 0: last_loss = i
        return out

    pos_vec = {}  # sid → np.array(n_min) of {0,1}
    pnl_per_bar = {}  # sid → np.array(n_min) of pnl when exit at that bar
    for sid, sig_name, sym, mom, tp, sl in STRATEGIES:
        if sym not in cache: continue
        ind = cache[sym]; fn = SIGNALS[sig_name]
        trades = sim_with_idx(ind, fn, tp, sl, mom)
        v = np.zeros(n_min); pnl_v = np.zeros(n_min)
        for ent, ext, p in trades:
            v[ent:ext+1] = 1
            pnl_v[ext] = p
        pos_vec[sid] = v
        pnl_per_bar[sid] = pnl_v

    sids = list(pos_vec.keys())
    print(f"\n=== Position-overlap correlation ===")
    print(f"{'sid':<18} {'#bars_in_pos':>13} {'#trades':>9} {'sum_pnl':>10}")
    for sid in sids:
        n_in = int(pos_vec[sid].sum())
        n_tr = int(np.sum(pnl_per_bar[sid] != 0))
        sp = float(pnl_per_bar[sid].sum())
        print(f"{sid:<18} {n_in:>13} {n_tr:>9} ${sp:>+8.0f}")

    # pairwise overlap (Jaccard) and pearson(pnl)
    pairs = []
    for i, a in enumerate(sids):
        for j, b in enumerate(sids):
            if j <= i: continue
            va = pos_vec[a]; vb = pos_vec[b]
            inter = float((va * vb).sum())
            union = float(((va + vb) > 0).sum())
            jacc = inter / union if union > 0 else 0
            # daily pnl correlation
            # bin pnl into weekly buckets
            bin_size = 168  # 1 week in 1h bars
            n_bins = n_min // bin_size
            p_a = np.array([pnl_per_bar[a][k*bin_size:(k+1)*bin_size].sum() for k in range(n_bins)])
            p_b = np.array([pnl_per_bar[b][k*bin_size:(k+1)*bin_size].sum() for k in range(n_bins)])
            if p_a.std() > 0 and p_b.std() > 0:
                corr = float(np.corrcoef(p_a, p_b)[0,1])
            else:
                corr = 0.0
            pairs.append({"a": a, "b": b, "jaccard": jacc, "weekly_pnl_corr": corr})

    high_overlap = [p for p in pairs if p["jaccard"] >= 0.4]
    high_corr = [p for p in pairs if p["weekly_pnl_corr"] >= 0.5]
    high_overlap.sort(key=lambda p: -p["jaccard"])
    high_corr.sort(key=lambda p: -p["weekly_pnl_corr"])

    print(f"\n=== HIGH OVERLAP (Jaccard ≥ 0.4) ===")
    for p in high_overlap[:15]:
        print(f"  {p['a']:<18} <-> {p['b']:<18}  Jacc={p['jaccard']:.2f}  Pnl_corr={p['weekly_pnl_corr']:+.2f}")

    print(f"\n=== HIGH PnL CORR (weekly ≥ 0.5) ===")
    for p in high_corr[:15]:
        print(f"  {p['a']:<18} <-> {p['b']:<18}  Pnl_corr={p['weekly_pnl_corr']:+.2f}  Jacc={p['jaccard']:.2f}")

    out = {"strategies": [{"sid": s, "n_in_pos": int(pos_vec[s].sum()),
                            "sum_pnl": float(pnl_per_bar[s].sum())} for s in sids],
           "pairs": pairs}
    out_path = Path("quant_runtime/output/auto4h/phaseN_correlation.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")
    print(f"Pairs: {len(pairs)} total, {len(high_overlap)} high-overlap, {len(high_corr)} high-corr")


if __name__ == "__main__":
    run()
