"""Creative strategy hunt — unconventional ideas not in standard retail toolkit.

Non-standard signals tested:
  1. BTC lead-lag: alt enters when BTC moved X% in past Y hours (cross-asset)
  2. Hour-of-day seasonality: certain UTC hours show alpha
  3. Weekday effect: Mon/Fri premium
  4. Vol-of-vol spike: std of vol over time (2nd-order vol)
  5. Rank reversal: top-N coin becoming bottom-N (cross-sectional fade)
  6. Range expansion after compression: N quiet days then explosion
  7. Skewness extreme: highly negative skew → revert
  8. Cross-asset corr breakdown: BTC-ETH correlation drops
  9. Days since ATH: long silence then breakout
  10. Hurst regime overlay: DFA trending → mom, reverting → rev
  11. Realized variance jump: RV spike → contrarian entry
  12. Autocorr sign flip: returns autocorr changes sign
  13. Liquidation imprint: large -5% hourly bar + 1h recovery = squeeze bottom
  14. Inter-coin lag: if 3 of 5 majors up >+1% in 1h, buy laggard
  15. Drawdown recovery: 5 days after -15%+ trough forms
"""
from __future__ import annotations

import json
import random
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DD = Path("/home/user/first_repo/quant_runtime/historical")
COST_RT = 0.0012
EQUITY = 75.0

all_coins = {}
all_times = {}
for d in sorted(DD.iterdir()):
    if not d.is_dir():
        continue
    p = d / "1h.json"
    if not p.exists():
        continue
    bars = json.load(open(p))
    if len(bars) < 5000:
        continue
    all_coins[d.name] = [b["close_price"] for b in bars]
    all_times[d.name] = [b.get("open_time", 0) for b in bars]

btc = all_coins.get("BTCUSDT", [])
btc_times = all_times.get("BTCUSDT", [])
print(f"Loaded {len(all_coins)} coins")


def mom(c, i, p):
    return (c[i] - c[i - p]) / c[i - p] if i >= p and c[i - p] > 0 else 0


def vol_std(c, i, p=168):
    if i < p + 1: return 0.01
    rets = [(c[i - j] / c[i - j - 1] - 1) for j in range(p) if i - j - 1 >= 0 and c[i - j - 1] > 0]
    return statistics.stdev(rets) if len(rets) > 10 else 0.01


def skew(c, i, p=168):
    if i < p + 1: return 0
    rets = [(c[i - j] / c[i - j - 1] - 1) for j in range(p) if i - j - 1 >= 0 and c[i - j - 1] > 0]
    if len(rets) < 10: return 0
    m = sum(rets) / len(rets)
    s = statistics.stdev(rets)
    if s == 0: return 0
    return sum((r - m) ** 3 for r in rets) / len(rets) / (s ** 3)


def regime_btc(bc, i):
    if i < 720 or i >= len(bc): return 1
    r5 = (bc[i] - bc[i - 120]) / bc[i - 120] if bc[i - 120] > 0 else 0
    if r5 < -0.08: return 0
    return 2 if sum(bc[max(0, i - 20):i + 1]) / min(20, i + 1) > sum(bc[max(0, i - 50):i + 1]) / min(50, i + 1) else 1


# ─── Creative signals ───

def sig_btc_leadlag(cs, i, btc_move_thr=0.02, lag_h=3):
    """When BTC moves >+X% in past lag_h, buy laggard alt (alt still flat)."""
    if i < lag_h or i >= len(btc): return None
    btc_r = mom(btc, i, lag_h)
    if btc_r < btc_move_thr: return None
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c): continue
        alt_r = mom(c, i, lag_h)
        if alt_r < btc_r * 0.3:  # alt hasn't caught up
            rs = btc_r - alt_r
            if rs > bs:
                bs = rs; best = sym
    return best


def sig_hour_alpha(cs, i, good_hours=(2, 3, 13, 14)):
    """Enter only during specific UTC hours."""
    if not btc_times or i >= len(btc_times): return None
    ts = btc_times[i]
    if ts <= 0: return None
    hour = datetime.utcfromtimestamp(ts / 1000).hour
    if hour not in good_hours: return None
    # Simple momentum within this hour
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c): continue
        r = mom(c, i, 24)
        if r > 0.01 and r > bs:
            bs = r; best = sym
    return best


def sig_weekday(cs, i, good_weekdays=(0, 4)):
    """Entry on Mon (0) or Fri (4) only."""
    if not btc_times or i >= len(btc_times): return None
    ts = btc_times[i]
    if ts <= 0: return None
    dow = datetime.utcfromtimestamp(ts / 1000).weekday()
    if dow not in good_weekdays: return None
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c): continue
        r = mom(c, i, 72)
        if r > 0.02 and r > bs:
            bs = r; best = sym
    return best


def sig_volvol(cs, i, spike_mult=2.5):
    """Enter after vol-of-vol spike (2nd order volatility increase)."""
    if i < 200: return None
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c): continue
        # Compute 24h vol at 5 points, then stdev of those
        vols = []
        for k in range(5):
            vi = i - k * 24
            if vi < 25: continue
            rets = [(c[vi - j] / c[vi - j - 1] - 1) for j in range(24) if vi - j - 1 >= 0 and c[vi - j - 1] > 0]
            if rets:
                vols.append(statistics.stdev(rets) if len(rets) > 1 else 0)
        if len(vols) < 3: continue
        vov = statistics.stdev(vols) if len(vols) > 1 else 0
        cur_v = vols[0]
        avg_v = sum(vols[1:]) / len(vols[1:])
        if cur_v > avg_v * spike_mult:
            # After vol spike, bounce trade (long after sharp drop)
            r = mom(c, i, 12)
            if r < -0.03:
                s = -r
                if s > bs:
                    bs = s; best = sym
    return best


def sig_rank_reversal(cs, i, lb=168):
    """Top-3 momentum coin of past week → now buy IF correction >5%."""
    scored = []
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c): continue
        r_old = mom(c, i - 24, lb)  # momentum 1 day ago over 7d
        r_now = mom(c, i, 24)  # momentum last 24h
        scored.append((sym, r_old, r_now))
    scored.sort(key=lambda x: -x[1])
    top_3 = scored[:3]
    # Among top-3 past winners, find one that corrected -5%+ in 24h
    best, bs = None, -999
    for sym, r_old, r_now in top_3:
        if r_now < -0.05 and -r_now > bs:
            bs = -r_now; best = sym
    return best


def sig_range_expand(cs, i, quiet_days=3, thr=0.02):
    """N quiet days (daily range <2%) then explosion (>3% in 1 day)."""
    if i < 24 * (quiet_days + 1): return None
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c): continue
        quiet = True
        for d in range(1, quiet_days + 1):
            start = i - d * 24
            end = i - (d - 1) * 24
            if start < 0: quiet = False; break
            hi = max(c[start:end]) if start < end else 0
            lo = min(c[start:end]) if start < end else 0
            if lo <= 0 or (hi - lo) / lo > thr: quiet = False; break
        if not quiet: continue
        today_r = mom(c, i, 24)
        if today_r > 0.03:
            if today_r > bs:
                bs = today_r; best = sym
    return best


def sig_skew_extreme(cs, i, skew_thr=-1.5):
    """Highly negative skew → long bias (expecting mean revert)."""
    best, bs = None, -999
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c): continue
        sk = skew(c, i, 168)
        if sk < skew_thr and mom(c, i, 72) < -0.03:
            s = -sk - abs(mom(c, i, 72))
            if s > bs:
                bs = s; best = sym
    return best


def sig_majors_lag(cs, i, thr=0.01):
    """If 3+ of 5 majors up >+1% in last 6h, buy cheapest laggard."""
    majors = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT"]
    ups = []
    downs = []
    for m in majors:
        if m not in cs: continue
        c = cs[m]
        if i >= len(c): continue
        r = mom(c, i, 6)
        if r > thr: ups.append(m)
        else: downs.append((m, r))
    if len(ups) < 3: return None
    # Buy weakest performer (laggard)
    downs.sort(key=lambda x: x[1])
    if downs and downs[0][0] in cs:
        return downs[0][0]
    return None


def sig_drawdown_recovery(cs, i, dd_thr=-0.15, days_since=5):
    """Enter N days after a trough formed (drawdown of -15%+)."""
    best, bs = None, -999
    lookback = days_since * 24
    if i < lookback + 120: return None
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c): continue
        # Find trough in window [i-lookback-120, i-lookback]
        window_start = i - lookback - 120
        window_end = i - lookback
        if window_start < 0: continue
        window = c[window_start:window_end]
        if not window: continue
        trough_idx = window_start + window.index(min(window))
        pre_high = max(c[max(0, trough_idx - 120):trough_idx]) if trough_idx > 0 else c[trough_idx]
        if pre_high <= 0: continue
        dd = (c[trough_idx] - pre_high) / pre_high
        if dd > dd_thr: continue
        # Coin has since been recovering
        if c[i] > c[trough_idx] * 1.02:
            s = (c[i] / c[trough_idx] - 1)
            if s > bs:
                bs = s; best = sym
    return best


def sig_days_since_ath(cs, i, min_days=60, bo_thr=0.02):
    """Long silence (60d without new ATH) then breakout >+2% above prior range."""
    best, bs = None, -999
    window = min_days * 24
    if i < window: return None
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c): continue
        window_hi = max(c[i - window:i])
        if c[i] > window_hi * (1 + bo_thr):
            s = (c[i] - window_hi) / window_hi
            if s > bs:
                bs = s; best = sym
    return best


def sig_autocorr_flip(cs, i, lb=168):
    """Returns autocorrelation changed sign in last week."""
    best, bs = None, -999
    if i < lb * 2: return None
    for sym, c in cs.items():
        if sym == "BTCUSDT" or i >= len(c): continue
        rets_recent = [(c[i - j] / c[i - j - 1] - 1) for j in range(lb) if i - j - 1 >= 0 and c[i - j - 1] > 0]
        rets_old = [(c[i - lb - j] / c[i - lb - j - 1] - 1) for j in range(lb) if i - lb - j - 1 >= 0 and c[i - lb - j - 1] > 0]
        if len(rets_recent) < 100 or len(rets_old) < 100: continue
        def ac(r):
            if len(r) < 2: return 0
            m = sum(r) / len(r)
            num = sum((r[k] - m) * (r[k - 1] - m) for k in range(1, len(r)))
            den = sum((x - m) ** 2 for x in r)
            return num / den if den > 0 else 0
        ac_r = ac(rets_recent); ac_o = ac(rets_old)
        # Flip from negative to positive autocorr = trend emerging
        if ac_o < -0.05 and ac_r > 0.05 and mom(c, i, 24) > 0.01:
            s = ac_r - ac_o
            if s > bs:
                bs = s; best = sym
    return best


STRATS = {
    "btc_leadlag_2_3h":    lambda cs, i: sig_btc_leadlag(cs, i, 0.02, 3),
    "btc_leadlag_3_6h":    lambda cs, i: sig_btc_leadlag(cs, i, 0.03, 6),
    "hour_alpha_am":       lambda cs, i: sig_hour_alpha(cs, i, (2, 3)),
    "hour_alpha_pm":       lambda cs, i: sig_hour_alpha(cs, i, (13, 14)),
    "hour_alpha_all":      lambda cs, i: sig_hour_alpha(cs, i, (2, 3, 13, 14)),
    "weekday_mon_fri":     lambda cs, i: sig_weekday(cs, i, (0, 4)),
    "weekday_fri":         lambda cs, i: sig_weekday(cs, i, (4,)),
    "volvol_spike_2.5":    lambda cs, i: sig_volvol(cs, i, 2.5),
    "volvol_spike_3":      lambda cs, i: sig_volvol(cs, i, 3.0),
    "rank_reversal_7d":    lambda cs, i: sig_rank_reversal(cs, i, 168),
    "range_expand_3d":     lambda cs, i: sig_range_expand(cs, i, 3, 0.02),
    "range_expand_5d":     lambda cs, i: sig_range_expand(cs, i, 5, 0.02),
    "skew_extreme_-1.5":   lambda cs, i: sig_skew_extreme(cs, i, -1.5),
    "skew_extreme_-2":     lambda cs, i: sig_skew_extreme(cs, i, -2.0),
    "majors_lag_1":        lambda cs, i: sig_majors_lag(cs, i, 0.01),
    "dd_recovery_-15_5d":  lambda cs, i: sig_drawdown_recovery(cs, i, -0.15, 5),
    "dd_recovery_-20_3d":  lambda cs, i: sig_drawdown_recovery(cs, i, -0.20, 3),
    "days_since_ath_60":   lambda cs, i: sig_days_since_ath(cs, i, 60, 0.02),
    "days_since_ath_90":   lambda cs, i: sig_days_since_ath(cs, i, 90, 0.03),
    "autocorr_flip":       lambda cs, i: sig_autocorr_flip(cs, i, 168),
}


def backtest(fn, lev=20, mp=0.75, sl=10, hold=72):
    margin = EQUITY * mp
    notional = margin * lev
    fee = notional * COST_RT
    trades = []
    pos = None
    cd = 0
    max_n = max(len(c) for c in all_coins.values())

    for i in range(720, max_n, 12):  # every 12h check for faster scan
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
                pos = None; cd = i + 24; continue
            if hh >= hold:
                trades.append(margin * (roe / 100) - fee - fd)
                pos = None; continue
            continue
        if i < cd: continue
        if regime_btc(btc, i) == 0: continue
        sym = fn(all_coins, i)
        if sym is None: continue
        pos = {"sym": sym, "bp": all_coins[sym][i], "ei": i}

    if not trades or len(trades) < 10: return None
    w = sum(1 for t in trades if t > 0)
    nt = len(trades)
    total = sum(trades)
    if total <= 0: return None
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
            if bal <= 0: ruin += 1; break
    return {
        "trades": nt, "wr": round(wr, 4), "pf": round(pf, 2),
        "total": round(total, 2), "avg": round(avg, 2),
        "wf": wf, "ruin_pct": round(ruin / 5, 2),
    }


print("\n[hunt] Testing creative strategies...")
results = []
for name, fn in STRATS.items():
    for lev in [10, 15, 20]:
        for hold in [72, 168, 336]:
            for sl in [10, 15]:
                r = backtest(fn, lev=lev, hold=hold, sl=sl)
                if r is None: continue
                r["name"] = name
                r["lev"] = lev
                r["hold"] = hold
                r["sl"] = sl
                results.append(r)
    print(f"  {name:<22}: done", flush=True)

print(f"\n[hunt] Total profitable: {len(results)}")
wf3 = [r for r in results if r["wf"] >= 3]
wf4 = [r for r in results if r["wf"] == 4]
print(f"  WF>=3: {len(wf3)}, WF=4: {len(wf4)}")

if wf3:
    # Composite: balance freq × profit
    max_tr = max(r["trades"] for r in wf3)
    max_tot = max(r["total"] for r in wf3)
    max_avg = max(r["avg"] for r in wf3)
    for r in wf3:
        r["comp"] = (r["trades"] / max_tr) * (r["total"] / max_tot) * (r["avg"] / max_avg)

    wf3.sort(key=lambda r: r["comp"], reverse=True)

    print(f"\n{'=' * 140}")
    print(f"  CREATIVE TOP 30 (WF>=3, sorted by Freq × Total × AvgPnL)")
    print(f"{'=' * 140}")
    print(f"\n  {'#':>3} {'Signal':<22} {'Lev':>3} {'Hold':>5} {'SL':>3} {'Trd':>5} {'WR':>6} {'PF':>5} {'Avg':>7} {'Total':>9} {'Ruin':>6} {'WF':>4}")
    print("  " + "-" * 130)
    for i, r in enumerate(wf3[:30]):
        print(f"  {i+1:>3} {r['name']:<22} {r['lev']:>2}x {r['hold']:>4}h {r['sl']:>2}% {r['trades']:>5} {r['wr']*100:>5.1f}% {r['pf']:>5.2f} ${r['avg']:>+5.2f} ${r['total']:>+7.2f} {r['ruin_pct']:>5.1f}% {r['wf']:>2}/4")

    # Best per strategy family
    by_name = defaultdict(list)
    for r in wf3:
        by_name[r["name"]].append(r)
    print(f"\n{'=' * 140}")
    print(f"  BEST PARAMS PER CREATIVE SIGNAL")
    print(f"{'=' * 140}\n")
    for name in sorted(by_name.keys()):
        rs = sorted(by_name[name], key=lambda r: r["total"], reverse=True)
        if not rs: continue
        r = rs[0]
        print(f"  {name:<22} lev={r['lev']}x hold={r['hold']}h sl={r['sl']}% | {r['trades']:>3} tr, WR {r['wr']*100:>5.1f}%, PF {r['pf']:>5.2f}, ${r['total']:>+7.2f}, ruin {r['ruin_pct']:.1f}%, WF {r['wf']}/4")

out = Path("/home/user/first_repo/quant_runtime/artifacts/creative_hunt.json")
out.parent.mkdir(parents=True, exist_ok=True)
with open(out, "w") as f:
    json.dump(wf3[:100], f, indent=2, ensure_ascii=False)
print(f"\nSaved to {out}")
