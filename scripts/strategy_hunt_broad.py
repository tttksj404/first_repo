"""Broad strategy hunt — 19 families × param grid × 20 coins × 375d.

Tests:
  Reversal variants (5), Momentum (4), Breakout (2),
  Mean Reversion (3), Volatility compression (2),
  Cross-sectional (2), Dual momentum (1)

Filter: WF >= 3, PF > 1, positive total.
Rank by WF × PF × Total.
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from collections import defaultdict
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
print(f"Loaded {len(all_coins)} coins", flush=True)


def mom(c, i, p):
    return (c[i] - c[i - p]) / c[i - p] if i >= p and c[i - p] > 0 else 0


def vol_std(c, i, p=168):
    if i < p + 1:
        return 0.01
    rets = [(c[i - j] / c[i - j - 1] - 1) for j in range(p) if i - j - 1 >= 0 and c[i - j - 1] > 0]
    return statistics.stdev(rets) if len(rets) > 10 else 0.01


def rsi_val(c, i, p=14):
    if i < p + 1:
        return 50
    gains = []
    losses = []
    for j in range(p):
        if i - j - 1 < 0:
            break
        d = c[i - j] - c[i - j - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains) / len(gains) if gains else 0
    al = sum(losses) / len(losses) if losses else 0
    return 100 - 100 / (1 + ag / al) if al > 0 else 100


def zscore(c, i, p=20):
    if i < p:
        return 0
    w = c[i - p + 1:i + 1]
    m = sum(w) / p
    s = statistics.stdev(w) if len(w) > 1 else 1
    return (c[i] - m) / s if s > 0 else 0


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


def _reversal(cs, i, lb, thr):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        r = mom(c, i, lb)
        if r < thr and -r > bs:
            bs = -r; best = sym
    return best


def _reversal_rsi(cs, i, lb, thr, rmax):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        r = mom(c, i, lb)
        if r < thr and rsi_val(c, i) < rmax and -r > bs:
            bs = -r; best = sym
    return best


def _momentum(cs, i, lb, thr):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        r = mom(c, i, lb)
        if r > thr and r > bs:
            bs = r; best = sym
    return best


def _mom_vol_adj(cs, i, lb):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        r = mom(c, i, lb)
        v = vol_std(c, i)
        if r > 0.03 and v > 0:
            s = r / v
            if s > bs:
                bs = s; best = sym
    return best


def _breakout(cs, i, lb):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c) or i < lb:
            continue
        hi = max(c[i - lb:i])
        if c[i] > hi * 1.01:
            s = (c[i] - hi) / hi
            if s > bs:
                bs = s; best = sym
    return best


def _mr_z(cs, i, lb, thr):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        z = zscore(c, i, lb)
        if z < thr and -z > bs:
            bs = -z; best = sym
    return best


def _mr_rsi(cs, i, rmax):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        rv = rsi_val(c, i)
        if rv < rmax and (rmax - rv) > bs:
            bs = rmax - rv; best = sym
    return best


def _vol_squeeze(cs, i, lb, thr):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        bw = bb_width_pct(c, i, lb)
        if bw < thr and mom(c, i, 24) > 0.01 and (thr - bw) > bs:
            bs = thr - bw; best = sym
    return best


def _xsect(cs, i, lb, thr):
    bm = mom(btc, i, lb) if i < len(btc) else 0
    sc = []
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        r = mom(c, i, lb)
        rs = r - bm
        if r > thr and rs > 0:
            sc.append((sym, rs))
    sc.sort(key=lambda x: -x[1])
    return sc[0][0] if sc else None


def _xsect_rev(cs, i, lb, thr):
    sc = []
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        r = mom(c, i, lb)
        if r < thr:
            sc.append((sym, -r))
    sc.sort(key=lambda x: -x[1])
    return sc[0][0] if sc else None


def _dual_mom(cs, i, lb, thr):
    bm = mom(btc, i, lb) if i < len(btc) else 0
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        r = mom(c, i, lb)
        rs = r - bm
        if r > thr and rs > 0:
            s = r * rs
            if s > bs:
                bs = s; best = sym
    return best


STRATS = {
    "rev_3d_-10":     lambda cs, i: _reversal(cs, i, 72, -0.10),
    "rev_5d_-15":     lambda cs, i: _reversal(cs, i, 120, -0.15),
    "rev_7d_-20":     lambda cs, i: _reversal(cs, i, 168, -0.20),
    "rev_1d_-7":      lambda cs, i: _reversal(cs, i, 24, -0.07),
    "rev_rsi":        lambda cs, i: _reversal_rsi(cs, i, 72, -0.05, 25),
    "mom_7d":         lambda cs, i: _momentum(cs, i, 168, 0.05),
    "mom_3d":         lambda cs, i: _momentum(cs, i, 72, 0.03),
    "mom_14d":        lambda cs, i: _momentum(cs, i, 336, 0.08),
    "mom_vol_adj":    lambda cs, i: _mom_vol_adj(cs, i, 168),
    "bo_20d":         lambda cs, i: _breakout(cs, i, 480),
    "bo_5d":          lambda cs, i: _breakout(cs, i, 120),
    "mr_zscore":      lambda cs, i: _mr_z(cs, i, 48, -2.0),
    "mr_rsi25":       lambda cs, i: _mr_rsi(cs, i, 25),
    "mr_rsi20":       lambda cs, i: _mr_rsi(cs, i, 20),
    "vc_squeeze":     lambda cs, i: _vol_squeeze(cs, i, 120, 0.08),
    "vc_squeeze_t":   lambda cs, i: _vol_squeeze(cs, i, 48, 0.04),
    "xsect_mom":      lambda cs, i: _xsect(cs, i, 168, 0.03),
    "xsect_rev":      lambda cs, i: _xsect_rev(cs, i, 72, -0.08),
    "dual_mom":       lambda cs, i: _dual_mom(cs, i, 168, 0.05),
}


def backtest(fn, lev, mp, sl_roe, hold_h):
    margin = EQUITY * mp
    notional = margin * lev
    fee = notional * COST_RT
    trades = []
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
                trades.append(margin * (-sl_roe / 100) - fee - fd)
                pos = None; cd = i + 48
                continue
            if hh >= hold_h:
                trades.append(margin * (roe / 100) - fee - fd)
                pos = None
                continue
            continue

        if i < cd:
            continue
        if regime_btc(btc, i) == 0:
            continue

        sym = fn(all_coins, i)
        if sym is None:
            continue
        c = all_coins[sym]
        pos = {"sym": sym, "bp": c[i], "ei": i}

    if not trades or len(trades) < 5:
        return None

    w = sum(1 for t in trades if t > 0)
    nt = len(trades)
    total = sum(trades)
    if total <= 0:
        return None
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
        "avg_win": round(aw, 2), "avg_loss": round(al, 2),
        "wf": wf, "ruin_pct": round(ruin / 10, 2),
    }


levs = [10, 15, 20]
mps = [0.5, 0.75]
sls = [10, 15, 20]
holds = [72, 168, 336]
total_runs = len(STRATS) * len(levs) * len(mps) * len(sls) * len(holds)
print(f"\n[hunt] {len(STRATS)} strategies × 54 params = {total_runs} runs\n", flush=True)

results = []
cnt = 0
for name, fn in STRATS.items():
    nfound = 0
    for lev in levs:
        for mp in mps:
            for sl in sls:
                for hold in holds:
                    cnt += 1
                    r = backtest(fn, lev, mp, sl, hold)
                    if r is None:
                        continue
                    r["strategy"] = name
                    r["lev"] = lev
                    r["mp"] = mp
                    r["sl_roe"] = sl
                    r["hold_h"] = hold
                    results.append(r)
                    nfound += 1
    print(f"  {name:<18} {nfound:>3} profitable  ({cnt}/{total_runs})", flush=True)

print(f"\n[hunt] Total profitable: {len(results)}")
wf3 = [r for r in results if r["wf"] >= 3]
wf4 = [r for r in results if r["wf"] == 4]
print(f"  WF >= 3: {len(wf3)}")
print(f"  WF = 4: {len(wf4)}")

results.sort(key=lambda r: (r["wf"], r["pf"], r["total"]), reverse=True)
wf3.sort(key=lambda r: (r["wf"], r["pf"], r["total"]), reverse=True)

print(f"\n{'=' * 130}")
print(f"  TOP 30 (WF >= 3, sorted by WF x PF x Total)")
print(f"{'=' * 130}")
print(f"\n  {'#':>3} {'Strategy':<18} {'Lev':>4} {'MP':>5} {'SL':>4} {'Hold':>5} {'Trd':>5} {'WR':>6} {'PF':>6} {'Total$':>9} {'EV$':>7} {'Ruin%':>7} {'WF':>4}")
print("  " + "-" * 120)
for i, r in enumerate(wf3[:30]):
    hh = {72: "3d", 168: "1w", 336: "2w"}.get(r["hold_h"], str(r["hold_h"]))
    tag = "★★" if r["wf"] == 4 and r["pf"] >= 5 else ("★" if r["wf"] == 4 else "●")
    print(f"  {i+1:>3} {r['strategy']:<18} {r['lev']:>3}x {r['mp']*100:>4.0f}% {r['sl_roe']:>3}% {hh:>5} {r['trades']:>5} {r['wr']*100:>5.1f}% {r['pf']:>5.2f} {r['total']:>+8.2f} {r['ev']:>+6.2f} {r['ruin_pct']:>6.1f}% {r['wf']:>2}/4 {tag}")

print(f"\n{'=' * 130}")
print(f"  BEST PARAMS PER STRATEGY FAMILY (WF >= 3, by total)")
print(f"{'=' * 130}\n")
bf = defaultdict(list)
for r in wf3:
    bf[r["strategy"]].append(r)
for name in sorted(bf.keys()):
    rs = sorted(bf[name], key=lambda r: r["total"], reverse=True)
    if not rs:
        continue
    r = rs[0]
    hh = {72: "3d", 168: "1w", 336: "2w"}.get(r["hold_h"], str(r["hold_h"]))
    print(f"  {name:<18} lev={r['lev']:>2}x mp={r['mp']*100:.0f}% sl={r['sl_roe']}% hold={hh:<3} | {r['trades']:>3} tr, WR {r['wr']*100:>5.1f}%, PF {r['pf']:>5.2f}, ${r['total']:>+8.2f}, ruin {r['ruin_pct']:>4.1f}%, WF {r['wf']}/4")

out = Path("/home/user/first_repo/quant_runtime/artifacts/strategy_hunt_broad.json")
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w") as f:
    json.dump(results[:200], f, indent=2, ensure_ascii=False)
print(f"\n[hunt] Saved top 200 to {out}")
