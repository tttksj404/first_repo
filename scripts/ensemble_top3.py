"""Ensemble backtest: vc_squeeze_t + mom_3d + rev_rsi.

Tests:
  - Sequential (each strategy trades with 1/3 equity allocation)
  - Parallel (all 3 can hold simultaneously with shared equity)
  - Signal correlation: how often do they pick same coin/direction

Configs:
  A) vc_squeeze_t: BB squeeze (48bar, <0.04) + 1d upward bias, 20x, 75% margin, SL 10%, hold 3d
  B) mom_3d:       3d momentum > 3%, 20x, 75% margin, SL 10%, hold 3d
  C) rev_rsi:      3d crash < -5% + RSI < 25, 20x, 75% margin, SL 10%, hold 3d
"""
from __future__ import annotations

import json
import random
import statistics
from pathlib import Path

DD = Path("/home/user/first_repo/quant_runtime/historical")
COST_RT = 0.0012
EQUITY = 75.0
MIN_BARS = 5000

all_coins = {}
for d in sorted(DD.iterdir()):
    if not d.is_dir():
        continue
    p = d / "1h.json"
    if not p.exists():
        continue
    bars = json.load(open(p))
    if len(bars) < MIN_BARS:
        continue
    all_coins[d.name] = [b["close_price"] for b in bars]

btc = all_coins.get("BTCUSDT", [])
print(f"Loaded {len(all_coins)} coins")


def mom(c, i, p):
    return (c[i] - c[i - p]) / c[i - p] if i >= p and c[i - p] > 0 else 0


def rsi_val(c, i, p=14):
    if i < p + 1:
        return 50
    gains, losses = [], []
    for j in range(p):
        if i - j - 1 < 0:
            break
        d = c[i - j] - c[i - j - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains) / len(gains) if gains else 0
    al = sum(losses) / len(losses) if losses else 0
    return 100 - 100 / (1 + ag / al) if al > 0 else 100


def bb_width_pct(c, i, p=20):
    if i < p:
        return 1
    w = c[i - p + 1:i + 1]
    m = sum(w) / p
    s = statistics.stdev(w) if len(w) > 1 else 0
    return (2 * s) / m if m > 0 else 1


def regime_btc(btc_c, i):
    if i < 720 or i >= len(btc_c):
        return 1
    r5d = (btc_c[i] - btc_c[i - 120]) / btc_c[i - 120] if btc_c[i - 120] > 0 else 0
    if r5d < -0.08:
        return 0
    e20 = sum(btc_c[max(0, i - 20):i + 1]) / min(20, i + 1)
    e50 = sum(btc_c[max(0, i - 50):i + 1]) / min(50, i + 1)
    return 2 if e20 > e50 else 1


def sig_vc_squeeze_t(cs, i):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        bw = bb_width_pct(c, i, 48)
        if bw < 0.04 and mom(c, i, 24) > 0.01 and (0.04 - bw) > bs:
            bs = 0.04 - bw
            best = sym
    return best


def sig_mom_3d(cs, i):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        r = mom(c, i, 72)
        if r > 0.03 and r > bs:
            bs = r
            best = sym
    return best


def sig_rev_rsi(cs, i):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        r = mom(c, i, 72)
        rv = rsi_val(c, i)
        if r < -0.05 and rv < 25 and -r > bs:
            bs = -r
            best = sym
    return best


STRATS = {"A_vc_squeeze_t": sig_vc_squeeze_t, "B_mom_3d": sig_mom_3d, "C_rev_rsi": sig_rev_rsi}


def run_single(strat_fn, equity_share=1.0, lev=20, mp=0.75, sl_roe=10, hold_h=72):
    margin = EQUITY * equity_share * mp
    notional = margin * lev
    fee = notional * COST_RT
    trades = []
    trade_log = []  # for correlation check
    pos = None
    cd = 0
    max_n = max(len(c) for c in all_coins.values())

    for i in range(720, max_n, 24):
        if pos:
            c = all_coins.get(pos["sym"])
            if not c or i >= len(c):
                pos = None
                continue
            pc = c[i] / pos["bp"] - 1
            roe = pc * 100 * lev
            hh = i - pos["ei"]
            fd = notional * 0.0001 * (hh // 8)
            if roe <= -sl_roe:
                pnl = margin * (-sl_roe / 100) - fee - fd
                trades.append(pnl)
                trade_log.append({"i": i, "sym": pos["sym"], "pnl": pnl, "exit": "SL"})
                pos = None
                cd = i + 48
                continue
            if hh >= hold_h:
                pnl = margin * (roe / 100) - fee - fd
                trades.append(pnl)
                trade_log.append({"i": i, "sym": pos["sym"], "pnl": pnl, "exit": "TIME"})
                pos = None
                continue
            continue

        if i < cd:
            continue
        if regime_btc(btc, i) == 0:
            continue

        sym = strat_fn(all_coins, i)
        if sym is None:
            continue
        pos = {"sym": sym, "bp": all_coins[sym][i], "ei": i}

    return trades, trade_log


def stats(trades):
    if not trades or len(trades) < 5:
        return None
    w = sum(1 for t in trades if t > 0)
    nt = len(trades)
    total = sum(trades)
    gp = sum(t for t in trades if t > 0)
    gl = abs(sum(t for t in trades if t <= 0))
    pf = gp / max(gl, 0.01)
    wr = w / nt
    aw = gp / max(w, 1)
    al = gl / max(nt - w, 1)
    ev = wr * aw - (1 - wr) * al

    fs = max(nt // 4, 1)
    wf = sum(1 for fi in range(4) if sum(trades[fi * fs:(fi + 1) * fs if fi < 3 else nt]) > 0)

    ruin = 0
    for _ in range(1000):
        bal = EQUITY
        for t in random.choices(trades, k=nt):
            bal += t
            if bal <= 0:
                ruin += 1
                break

    return {
        "trades": nt, "wr": round(wr, 4), "pf": round(pf, 2),
        "total": round(total, 2), "ev": round(ev, 2),
        "wf": wf, "ruin_pct": round(ruin / 10, 2),
    }


# Individual runs
print(f"\n{'=' * 100}")
print(f"  INDIVIDUAL RESULTS (full equity, no split)")
print(f"{'=' * 100}")
print(f"\n  {'Strategy':<18} {'Trades':>7} {'WR':>6} {'PF':>6} {'Total$':>9} {'EV$':>7} {'Ruin%':>7} {'WF':>4}")
print("  " + "-" * 80)

indv_trades = {}
indv_logs = {}
for name, fn in STRATS.items():
    t, log = run_single(fn, equity_share=1.0)
    indv_trades[name] = t
    indv_logs[name] = log
    s = stats(t)
    if s:
        print(f"  {name:<18} {s['trades']:>7} {s['wr']*100:>5.1f}% {s['pf']:>5.2f} {s['total']:>+8.2f} {s['ev']:>+6.2f} {s['ruin_pct']:>6.1f}% {s['wf']:>2}/4")

# Correlation check: same coin/i picked?
print(f"\n{'=' * 100}")
print(f"  SIGNAL OVERLAP (do strategies pick same coin?)")
print(f"{'=' * 100}")
logs_by_i = {}  # i → {name: sym}
for name, log in indv_logs.items():
    for entry in log:
        i = entry["i"]
        if i not in logs_by_i:
            logs_by_i[i] = {}
        logs_by_i[i][name] = entry["sym"]

overlaps = {"AB": 0, "AC": 0, "BC": 0, "ABC": 0}
for i, picks in logs_by_i.items():
    if len(picks) < 2:
        continue
    have = set(picks.keys())
    if "A_vc_squeeze_t" in have and "B_mom_3d" in have:
        if picks["A_vc_squeeze_t"] == picks["B_mom_3d"]:
            overlaps["AB"] += 1
    if "A_vc_squeeze_t" in have and "C_rev_rsi" in have:
        if picks["A_vc_squeeze_t"] == picks["C_rev_rsi"]:
            overlaps["AC"] += 1
    if "B_mom_3d" in have and "C_rev_rsi" in have:
        if picks["B_mom_3d"] == picks["C_rev_rsi"]:
            overlaps["BC"] += 1
print(f"  A-B same coin at same time: {overlaps['AB']}")
print(f"  A-C same coin at same time: {overlaps['AC']}")
print(f"  B-C same coin at same time: {overlaps['BC']}")

# ENSEMBLE: split equity 1/3 each, parallel operation
print(f"\n{'=' * 100}")
print(f"  ENSEMBLE RESULTS (1/3 equity each, parallel)")
print(f"{'=' * 100}")

# Split 1/3 each
share = 1.0 / 3
t_a, _ = run_single(STRATS["A_vc_squeeze_t"], equity_share=share)
t_b, _ = run_single(STRATS["B_mom_3d"], equity_share=share)
t_c, _ = run_single(STRATS["C_rev_rsi"], equity_share=share)

# Concatenate all trades (pooled)
all_trades = t_a + t_b + t_c

s_ens = stats(all_trades)
print(f"\n  {'Strategy':<18} {'Trades':>7} {'WR':>6} {'PF':>6} {'Total$':>9} {'EV$':>7} {'Ruin%':>7} {'WF':>4}")
print("  " + "-" * 80)
if s_ens:
    print(f"  ENSEMBLE 1/3 each  {s_ens['trades']:>7} {s_ens['wr']*100:>5.1f}% {s_ens['pf']:>5.2f} {s_ens['total']:>+8.2f} {s_ens['ev']:>+6.2f} {s_ens['ruin_pct']:>6.1f}% {s_ens['wf']:>2}/4")

# Individual with 1/3 equity for comparison
s_a_split = stats(t_a)
s_b_split = stats(t_b)
s_c_split = stats(t_c)
if s_a_split:
    print(f"  → A only (1/3)     {s_a_split['trades']:>7} {s_a_split['wr']*100:>5.1f}% {s_a_split['pf']:>5.2f} {s_a_split['total']:>+8.2f}")
if s_b_split:
    print(f"  → B only (1/3)     {s_b_split['trades']:>7} {s_b_split['wr']*100:>5.1f}% {s_b_split['pf']:>5.2f} {s_b_split['total']:>+8.2f}")
if s_c_split:
    print(f"  → C only (1/3)     {s_c_split['trades']:>7} {s_c_split['wr']*100:>5.1f}% {s_c_split['pf']:>5.2f} {s_c_split['total']:>+8.2f}")

# Summary: vs baseline (single best)
best_single = max(
    (stats(indv_trades[n]) for n in STRATS if stats(indv_trades[n]) is not None),
    key=lambda s: s["total"],
)
print(f"\n  Best SINGLE (100% equity): {best_single['total']:+.2f} PF {best_single['pf']} WF {best_single['wf']}/4")
if s_ens:
    print(f"  ENSEMBLE (split 1/3):      {s_ens['total']:+.2f} PF {s_ens['pf']} WF {s_ens['wf']}/4")
    ratio = s_ens['total'] / best_single['total']
    print(f"  Ensemble/Best ratio: {ratio:.2f}× ({'better' if ratio > 1 else 'worse'} than best single)")

# Save
out = Path("/home/user/first_repo/quant_runtime/artifacts/ensemble_top3.json")
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w") as f:
    json.dump({
        "individuals": {n: stats(indv_trades[n]) for n in STRATS},
        "overlaps": overlaps,
        "ensemble": s_ens,
        "individual_split": {"A": s_a_split, "B": s_b_split, "C": s_c_split},
    }, f, indent=2, ensure_ascii=False)
print(f"\nSaved to {out}")
