"""Hunt for HIGH FREQUENCY + HIGH PROFIT strategies.

Optimization target: total_pnl × (trades / max_trades) — balance freq and profit.

Test relaxed variants of winners to find more entries without losing profit.
"""
from __future__ import annotations

import json
import random
import statistics
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
print(f"Loaded {len(all_coins)} coins")


def mom(c, i, p):
    return (c[i] - c[i - p]) / c[i - p] if i >= p and c[i - p] > 0 else 0


def rsi_val(c, i, p=14):
    if i < p + 1:
        return 50
    g, l = [], []
    for j in range(p):
        if i - j - 1 < 0:
            break
        d = c[i - j] - c[i - j - 1]
        g.append(max(d, 0))
        l.append(max(-d, 0))
    ag = sum(g) / len(g) if g else 0
    al = sum(l) / len(l) if l else 0
    return 100 - 100 / (1 + ag / al) if al > 0 else 100


def bb_w(c, i, p=20):
    if i < p:
        return 1
    w = c[i - p + 1:i + 1]
    m = sum(w) / p
    s = statistics.stdev(w) if len(w) > 1 else 0
    return (2 * s) / m if m > 0 else 1


def zscore(c, i, p=20):
    if i < p:
        return 0
    w = c[i - p + 1:i + 1]
    m = sum(w) / p
    s = statistics.stdev(w) if len(w) > 1 else 1
    return (c[i] - m) / s if s > 0 else 0


def regime_btc(bc, i):
    if i < 720 or i >= len(bc):
        return 1
    r5 = (bc[i] - bc[i - 120]) / bc[i - 120] if bc[i - 120] > 0 else 0
    if r5 < -0.08:
        return 0
    return 2 if sum(bc[max(0, i - 20):i + 1]) / min(20, i + 1) > sum(bc[max(0, i - 50):i + 1]) / min(50, i + 1) else 1


# Relaxed variants generators
def gen_mom_variants():
    out = {}
    for lb in [24, 48, 72, 120, 168, 336]:
        for thr in [0.01, 0.02, 0.03, 0.05, 0.08]:
            out[f"mom_{lb}h_{int(thr*100)}"] = (lb, thr)
    return out


def gen_rev_variants():
    out = {}
    for lb in [24, 48, 72, 120, 168, 336]:
        for thr in [-0.03, -0.05, -0.08, -0.10, -0.15, -0.20]:
            out[f"rev_{lb}h_{int(abs(thr)*100)}"] = (lb, thr)
    return out


def gen_rsi_variants():
    out = {}
    for lb in [48, 72, 120]:
        for mthr in [-0.03, -0.05, -0.08]:
            for rmax in [20, 25, 30, 35]:
                out[f"rvrsi_{lb}h_{int(abs(mthr)*100)}_r{rmax}"] = (lb, mthr, rmax)
    return out


def gen_vcsqz_variants():
    out = {}
    for lb in [20, 48, 96]:
        for thr in [0.03, 0.04, 0.06, 0.08, 0.12]:
            for mom_bias in [0, 0.005, 0.01, 0.02]:
                out[f"vcsqz_{lb}_{int(thr*100)}_b{int(mom_bias*1000)}"] = (lb, thr, mom_bias)
    return out


def _mom(cs, i, lb, thr):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        r = mom(c, i, lb)
        if r > thr and r > bs:
            bs = r; best = sym
    return best


def _rev(cs, i, lb, thr):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        r = mom(c, i, lb)
        if r < thr and -r > bs:
            bs = -r; best = sym
    return best


def _rvrsi(cs, i, lb, mthr, rmax):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        r = mom(c, i, lb)
        if r < mthr and rsi_val(c, i) < rmax and -r > bs:
            bs = -r; best = sym
    return best


def _vcsqz(cs, i, lb, thr, mb):
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c):
            continue
        bw = bb_w(c, i, lb)
        if bw < thr and mom(c, i, 24) > mb and (thr - bw) > bs:
            bs = thr - bw; best = sym
    return best


def backtest(fn, lev=20, mp=0.75, sl=10, hold=72):
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
                pos = None; continue
            pc = c[i] / pos["bp"] - 1
            roe = pc * 100 * lev
            hh = i - pos["ei"]
            fd = notional * 0.0001 * (hh // 8)
            if roe <= -sl:
                trades.append(margin * (-sl / 100) - fee - fd)
                pos = None; cd = i + 48; continue
            if hh >= hold:
                trades.append(margin * (roe / 100) - fee - fd)
                pos = None; continue
            continue
        if i < cd:
            continue
        if regime_btc(btc, i) == 0:
            continue
        sym = fn(all_coins, i)
        if sym is None:
            continue
        pos = {"sym": sym, "bp": all_coins[sym][i], "ei": i}

    if not trades or len(trades) < 10:
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
    avg = total / nt

    fs = max(nt // 4, 1)
    wf = sum(1 for fi in range(4) if sum(trades[fi * fs:(fi + 1) * fs if fi < 3 else nt]) > 0)

    ruin = 0
    for _ in range(500):
        bal = EQUITY
        for t in random.choices(trades, k=nt):
            bal += t
            if bal <= 0:
                ruin += 1; break

    return {
        "trades": nt, "wr": round(wr, 4), "pf": round(pf, 2),
        "total": round(total, 2), "avg": round(avg, 2),
        "wf": wf, "ruin_pct": round(ruin / 5, 2),
    }


# Run all
print("\n[hunt] Testing all variants...")
results = []

for name, (lb, thr) in gen_mom_variants().items():
    r = backtest(lambda cs, i, lb=lb, thr=thr: _mom(cs, i, lb, thr))
    if r: r["name"] = name; r["type"] = "mom"; results.append(r)

for name, (lb, thr) in gen_rev_variants().items():
    r = backtest(lambda cs, i, lb=lb, thr=thr: _rev(cs, i, lb, thr))
    if r: r["name"] = name; r["type"] = "rev"; results.append(r)

for name, (lb, m, rm) in gen_rsi_variants().items():
    r = backtest(lambda cs, i, lb=lb, m=m, rm=rm: _rvrsi(cs, i, lb, m, rm))
    if r: r["name"] = name; r["type"] = "rvrsi"; results.append(r)

for name, (lb, thr, mb) in gen_vcsqz_variants().items():
    r = backtest(lambda cs, i, lb=lb, thr=thr, mb=mb: _vcsqz(cs, i, lb, thr, mb))
    if r: r["name"] = name; r["type"] = "vcsqz"; results.append(r)

print(f"[hunt] Profitable: {len(results)}")
wf3 = [r for r in results if r["wf"] >= 3]
print(f"  WF>=3: {len(wf3)}")

# Score: frequency × profit
# Normalize: trades/500 * avg/max_avg * total/max_total
max_tr = max(r["trades"] for r in wf3) if wf3 else 1
max_tot = max(r["total"] for r in wf3) if wf3 else 1
max_avg = max(r["avg"] for r in wf3) if wf3 else 1
for r in wf3:
    r["freq_score"] = r["trades"] / max_tr
    r["profit_score"] = r["total"] / max_tot
    r["per_trade_score"] = r["avg"] / max_avg
    # Composite: freq × profit × per_trade
    r["composite"] = r["freq_score"] * r["profit_score"] * r["per_trade_score"]

wf3.sort(key=lambda r: r["composite"], reverse=True)

print(f"\n{'=' * 140}")
print(f"  HIGH FREQ + HIGH PROFIT RANKING (top 30, composite = freq × total × per_trade)")
print(f"{'=' * 140}")
print(f"\n  {'#':>3} {'Name':<22} {'Type':<7} {'Trades':>7} {'WR':>6} {'PF':>6} {'Avg':>7} {'Total':>9} {'Ruin':>6} {'WF':>4} {'Composite':>9}")
print("  " + "-" * 130)

for i, r in enumerate(wf3[:30]):
    print(f"  {i+1:>3} {r['name']:<22} {r['type']:<7} {r['trades']:>7} {r['wr']*100:>5.1f}% {r['pf']:>5.2f} ${r['avg']:>+5.2f} ${r['total']:>+7.2f} {r['ruin_pct']:>5.1f}% {r['wf']:>2}/4 {r['composite']:>9.4f}")

# Also: top by total (max wealth)
by_total = sorted(wf3, key=lambda r: r["total"], reverse=True)
print(f"\n{'=' * 140}")
print(f"  TOP 10 BY TOTAL PROFIT")
print(f"{'=' * 140}")
for i, r in enumerate(by_total[:10]):
    print(f"  {i+1:>3} {r['name']:<22} {r['type']:<7} {r['trades']:>7} {r['wr']*100:>5.1f}% {r['pf']:>5.2f} ${r['avg']:>+5.2f} ${r['total']:>+7.2f} {r['ruin_pct']:>5.1f}% {r['wf']:>2}/4")

# Also: top by trades
by_tr = sorted(wf3, key=lambda r: r["trades"], reverse=True)
print(f"\n{'=' * 140}")
print(f"  TOP 10 BY FREQUENCY (most trades, still WF>=3)")
print(f"{'=' * 140}")
for i, r in enumerate(by_tr[:10]):
    print(f"  {i+1:>3} {r['name']:<22} {r['type']:<7} {r['trades']:>7} {r['wr']*100:>5.1f}% {r['pf']:>5.2f} ${r['avg']:>+5.2f} ${r['total']:>+7.2f} {r['ruin_pct']:>5.1f}% {r['wf']:>2}/4")

out = Path("/home/user/first_repo/quant_runtime/artifacts/freq_profit_hunt.json")
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w") as f:
    json.dump(wf3[:100], f, indent=2, ensure_ascii=False)
print(f"\nSaved to {out}")
