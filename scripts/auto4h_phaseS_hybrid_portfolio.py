#!/usr/bin/env python3
"""Phase S: Hybrid long+short portfolio.

Long 10 (Phase O) + Short STRONG/OK (Phase R) → 결합 포트폴리오.
Short 측에서:
  - cluster dedup (Jaccard≥0.7 / 같은 sym+sig 군집은 1개만)
  - 코인당 최대 1개 short
  - long 과의 상관관계 측정
LINK 5 STRONG 중 best (PF=194 +80/-30) 만 채택.
ETH 3 STRONG 중 best (PF=4.38 +80/-30) 만 채택.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv
from auto4h_phaseQ_short_side import (
    SHORT_SIGNALS, simulate_short, precompute_bear_regime,
)


def positions_pnl(ind, btc_bear, sig_fn, tp, sl, mom):
    """Run sim with full-history bounds, return per-bar position bool + pnl event timestamps."""
    n = len(ind["close"])
    in_pos = np.zeros(n, dtype=bool)
    pnl_events = np.zeros(n)  # pnl recorded at exit bar
    # Reuse simulate_short's loop but track pos vector
    # Simpler: re-implement minimally tracking positions
    LEVERAGE=10; MARGIN=50.0; COST_RT=0.0012; FUNDING_8H=0.0001
    SLIPPAGE_BPS=8; LIQ_ROE=-95.0; COOLDOWN_EXIT=12; COOLDOWN_LOSS=24
    slip = SLIPPAGE_BPS/10000.0
    pos = False; entry_px=0; entry_idx=0; last_exit=-1; last_loss=-1
    for i in range(50, n):
        if not pos:
            if last_exit >= 0 and (i-last_exit) < COOLDOWN_EXIT: continue
            if last_loss >= 0 and (i-last_loss) < COOLDOWN_LOSS: continue
            if i < len(btc_bear) and not btc_bear[i]: continue
            if ind["mom24"][i] > mom: continue
            if not sig_fn(ind, i): continue
            entry_px = ind["close"][i]*(1-slip)
            entry_idx=i; pos=True
            in_pos[i]=True
        else:
            in_pos[i]=True
            hi=ind["high"][i]; lo=ind["low"][i]; cl=ind["close"][i]
            roe_lo = (entry_px/lo - 1)*LEVERAGE*100
            roe_hi = (entry_px/hi - 1)*LEVERAGE*100
            roe_cl = (entry_px/cl - 1)*LEVERAGE*100
            exit_roe=None
            if roe_hi <= -95: exit_roe = -100
            elif roe_hi <= sl:
                sl_px = entry_px*(1 - sl/100/LEVERAGE)
                exit_roe = (entry_px/(sl_px*(1+slip))-1)*LEVERAGE*100
            elif roe_lo >= tp:
                tp_px = entry_px*(1 - tp/100/LEVERAGE)
                exit_roe = (entry_px/(tp_px*(1+slip))-1)*LEVERAGE*100
            elif (not sig_fn(ind, i)) and roe_cl > 0:
                exit_roe = (entry_px/(cl*(1+slip))-1)*LEVERAGE*100
            if exit_roe is not None:
                hold = i - entry_idx
                notional = MARGIN*LEVERAGE
                pnl = -MARGIN-notional*COST_RT if exit_roe<=-100 else MARGIN*(exit_roe/100) - notional*COST_RT - notional*FUNDING_8H*(hold/8)
                pnl_events[i] = pnl
                pos=False; last_exit=i
                if pnl < 0: last_loss=i
    return in_pos, pnl_events


def run():
    print("Phase S: build hybrid long+short portfolio")
    long_inp = Path("quant_runtime/output/auto4h/phaseO_portfolio.json")
    short_inp = Path("quant_runtime/output/auto4h/phaseR_validate_short.json")
    if not long_inp.exists() or not short_inp.exists():
        print("  missing inputs"); return
    long_data = json.loads(long_inp.read_text())
    short_data = json.loads(short_inp.read_text())

    longs = long_data.get("portfolio", [])[:10]
    short_strong = [r for r in short_data["results"] if r["verdict"] == "🥇 OOS_STRONG"]
    short_ok = [r for r in short_data["results"] if r["verdict"] == "🥈 OOS_OK"]
    short_pool = short_strong + short_ok
    print(f"  long: {len(longs)} strategies")
    print(f"  short pool: {len(short_strong)} STRONG + {len(short_ok)} OK = {len(short_pool)} total")

    # Cluster dedup short: keep best per (signal, symbol)
    by_key = {}
    for r in short_pool:
        k = (r["signal"], r["symbol"])
        score = r["oos"]["pf"] * max(r["oos"]["net"], 1) / 50
        if k not in by_key or score > by_key[k][0]:
            by_key[k] = (score, r)
    deduped_per_sigsym = [v[1] for v in by_key.values()]
    print(f"\n  after sig+sym dedup: {len(deduped_per_sigsym)} short candidates")
    for r in sorted(deduped_per_sigsym, key=lambda x: -x["oos"]["net"]):
        print(f"    {r['signal']:<22} {r['symbol']:<10} mom{r['mom_max']*100:>+3.0f}% "
              f"TP+{r['tp']}/SL{r['sl']}: OOS PF={r['oos']['pf']:.2f} "
              f"net=${r['oos']['net']:+.0f}")

    # Coin cap: max 1 short per symbol (best score)
    by_sym = {}
    for r in deduped_per_sigsym:
        sym = r["symbol"]
        score = r["oos"]["pf"] * max(r["oos"]["net"], 1) / 50
        if sym not in by_sym or score > by_sym[sym][0]:
            by_sym[sym] = (score, r)
    short_picks = [v[1] for v in by_sym.values()]
    short_picks.sort(key=lambda r: -(r["oos"]["pf"] * max(r["oos"]["net"], 1) / 50))
    print(f"\n  after per-coin cap: {len(short_picks)} final short picks")
    for r in short_picks:
        print(f"    {r['signal']:<22} {r['symbol']:<10} mom{r['mom_max']*100:>+3.0f}% "
              f"TP+{r['tp']}/SL{r['sl']}: OOS PF={r['oos']['pf']:.2f} "
              f"net=${r['oos']['net']:+.0f} adj={r['adj_pass']}/27")

    # Compute corr between short picks and long PnL series
    print("\n  computing long-short correlation...")
    long_syms = sorted(set(s["symbol"] for s in longs))
    short_syms = sorted(set(s["symbol"] for s in short_picks))
    universe = sorted(set(long_syms) | set(short_syms) | {"BTCUSDT"})
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())

    short_pnl_series = {}
    for r in short_picks:
        sym = r["symbol"]; sig = r["signal"]
        if sym not in cache: continue
        fn = SHORT_SIGNALS[sig]
        in_pos, pnl_ev = positions_pnl(cache[sym], btc_bear, fn, r["tp"], r["sl"], r["mom_max"])
        # weekly aggregation
        n = min(len(pnl_ev), n_min)
        per_week = []
        wk = 24*7
        for w in range(0, n, wk):
            per_week.append(pnl_ev[w:w+wk].sum())
        short_pnl_series[f"short_{sig}_{sym}"] = np.array(per_week)
    print(f"    {len(short_pnl_series)} short PnL series built")

    # Final hybrid portfolio: 10 longs + N shorts (N = len(short_picks))
    final = []
    for s in longs:
        final.append({"side": "long", **s})
    for r in short_picks:
        final.append({
            "side": "short",
            "sid": f"{r['symbol'][:3].lower()}_{r['signal'].replace('short_','')}",
            "signal": r["signal"], "symbol": r["symbol"],
            "mom_max": r["mom_max"], "tp": r["tp"], "sl": r["sl"],
            "regime": "btc_bear",
            "oos_pf": r["oos"]["pf"], "oos_net": r["oos"]["net"],
            "adj_pass": r["adj_pass"],
        })
    print(f"\n=== HYBRID PORTFOLIO: {len(longs)} longs + {len(short_picks)} shorts = {len(final)} strategies ===")
    out = Path("quant_runtime/output/auto4h/phaseS_hybrid.json")
    with open(out, "w") as f:
        json.dump({
            "longs": longs,
            "shorts": short_picks,
            "final": final,
            "n_long": len(longs),
            "n_short": len(short_picks),
        }, f, indent=2, default=str)
    print(f"\n[saved] {out}")
    print("\n=== KILL-SWITCH RULES (Phase S design) ===")
    rules = [
        "1. Per-strategy: 5 consecutive losses → pause 7d",
        "2. Per-strategy: 30d rolling PF < 0.8 → pause until PF > 1.2 backtest",
        "3. Portfolio: 7d cumulative PnL < -3*MARGIN ($-150) → all pause 24h",
        "4. Portfolio: 14d cumulative PnL < -10*MARGIN ($-500) → halt all",
        "5. Regime: BTC ATR rank < 0.2 for 5d → reduce all margins to 50%",
        "6. Per-coin: single-coin DD > $200 → pause that coin's strategies 14d",
        "7. Funding spike: 8h funding > 0.05% (5x normal) → skip new entries",
        "8. Slippage drift: realized slip > 15bps avg over 20 trades → pause that strat",
    ]
    for r in rules:
        print(f"  {r}")


if __name__ == "__main__":
    run()
