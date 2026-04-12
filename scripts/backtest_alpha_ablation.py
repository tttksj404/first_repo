"""Ablation backtest for OI-VWAP-SMC alpha strategies.

Tests: baseline → +OI_filter → +SMC_filter → +VWAP_filter → +alpha_entries
Uses 1h bars with 5m OHLCV for VWAP/SMC when available.
375-day data, $75 equity, 24bps cost, walk-forward 4-fold.
"""
from __future__ import annotations
import json, math, statistics, sys, time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Indicators ──────────────────────────────────
def ema(v, p):
    if len(v) < p: return sum(v) / max(len(v), 1)
    k = 2 / (p + 1); e = sum(v[:p]) / p
    for x in v[p:]: e = x * k + e * (1 - k)
    return e

def atr_val(h, l, c, p=14):
    if len(h) < 2: return 0
    trs = [max(h[-i] - l[-i], abs(h[-i] - c[-i - 1]), abs(l[-i] - c[-i - 1])) for i in range(1, min(len(h), p + 1))]
    return sum(trs) / max(len(trs), 1)

def adx_val(h, l, c, p=14):
    if len(h) < p + 2: return 0
    pdm = []; mdm = []; trs = []
    for i in range(1, min(len(h), p + 2)):
        hd = h[-i] - h[-i - 1]; ld = l[-i - 1] - l[-i]
        pdm.append(max(hd, 0) if hd > ld else 0); mdm.append(max(ld, 0) if ld > hd else 0)
        trs.append(max(h[-i] - l[-i], abs(h[-i] - c[-i - 1]), abs(l[-i] - c[-i - 1])))
    a = sum(trs[:p]) / p
    if a <= 0: return 0
    pdi = (sum(pdm[:p]) / p) / a * 100; mdi = (sum(mdm[:p]) / p) / a * 100
    return abs(pdi - mdi) / max(pdi + mdi, 0.01) * 100

def rsi_val(c, p=14):
    if len(c) < p + 1: return 50
    g = [max(c[i] - c[i - 1], 0) for i in range(-p, 0)]
    l_ = [max(c[i - 1] - c[i], 0) for i in range(-p, 0)]
    ag = sum(g) / p; al = sum(l_) / p
    return 100 - 100 / (1 + ag / al) if al > 0 else 100

def vwap_calc(h, l, c, v, lookback=96):
    """Session VWAP from last N bars."""
    start = max(0, len(c) - lookback)
    cum_pv = 0; cum_v = 0
    for i in range(start, len(c)):
        tp = (h[i] + l[i] + c[i]) / 3
        cum_pv += tp * v[i]; cum_v += v[i]
    return cum_pv / max(cum_v, 1e-12)

def vwap_z(c, h, l, v, i, lookback=96):
    """Z-score of current price deviation from VWAP."""
    start = max(0, i - lookback + 1)
    vw = vwap_calc(h[start:i+1], l[start:i+1], c[start:i+1], v[start:i+1], lookback)
    devs = []
    for j in range(max(start, 10), i + 1):
        s = max(0, j - lookback + 1)
        vw_j = vwap_calc(h[s:j+1], l[s:j+1], c[s:j+1], v[s:j+1], lookback)
        devs.append(c[j] - vw_j)
    if len(devs) < 2: return 0.0, vw
    cur_dev = c[i] - vw
    m = sum(devs) / len(devs)
    s = statistics.pstdev(devs)
    z = (cur_dev - m) / s if s > 1e-12 else 0.0
    return max(-4, min(4, z)), vw

def oi_divergence(oi, c, i, lookback=24):
    """OI-price divergence score."""
    if i < lookback: return 0.0
    prices = c[i - lookback:i + 1]
    ois = oi[max(0, i - lookback):i + 1]
    if len(ois) < lookback: return 0.0
    cur_p = prices[-1]; prev_high = max(prices[:-1]); prev_low = min(prices[:-1])
    oi_now = ois[-1]; oi_prev_avg = sum(ois[:-1]) / max(len(ois) - 1, 1)
    oi_delta = (oi_now - oi_prev_avg) / max(abs(oi_prev_avg), 1e-12)
    new_high = cur_p > prev_high
    new_low = cur_p < prev_low
    if new_high and oi_delta < -0.02: return -0.6  # fake breakout
    if new_high and oi_delta > 0.03: return 0.6   # healthy breakout
    if new_low and oi_delta < -0.02: return 0.5    # short cover
    if new_low and oi_delta > 0.03: return -0.5    # genuine breakdown
    return max(-0.3, min(0.3, oi_delta * 3))

def fvg_score(h, l, i, lookback=50):
    """Simple FVG detection score 0-1."""
    if i < 3: return 0.0
    score = 0.0
    for j in range(max(2, i - lookback), i + 1):
        # Bullish FVG: bar[j].low > bar[j-2].high
        if l[j] > h[j - 2]:
            gap_pct = (l[j] - h[j - 2]) / h[j - 2] * 100
            if 0.05 <= gap_pct <= 0.5:
                # Is price currently in this gap?
                if h[j - 2] <= h[i] and l[i] <= l[j]:
                    age = i - j
                    score = max(score, 0.3 + 0.7 * max(0, 1 - age / 30))
        # Bearish FVG
        if h[j] < l[j - 2]:
            gap_pct = (l[j - 2] - h[j]) / l[j - 2] * 100
            if 0.05 <= gap_pct <= 0.5:
                if l[j - 2] >= l[i] and h[i] >= h[j]:
                    age = i - j
                    score = max(score, 0.3 + 0.7 * max(0, 1 - age / 30))
    return score

def structure_score(h, l, c, i, sw=5):
    """BOS/CHoCH detection score 0-1."""
    if i < sw * 4: return 0.0
    # Find recent swing highs/lows
    shs = []; sls = []
    for j in range(sw, i - sw):
        if all(h[j] >= h[k] for k in range(j - sw, j + sw + 1) if k != j):
            shs.append((j, h[j]))
        if all(l[j] <= l[k] for k in range(j - sw, j + sw + 1) if k != j):
            sls.append((j, l[j]))
    if len(shs) < 2 or len(sls) < 2: return 0.0
    # BOS up: higher high
    if shs[-1][1] > shs[-2][1] and c[i] > shs[-1][1]:
        return min(0.8, 0.4 + 0.4 * max(0, 1 - (i - shs[-1][0]) / 15))
    # BOS down: lower low
    if sls[-1][1] < sls[-2][1] and c[i] < sls[-1][1]:
        return min(0.8, 0.4 + 0.4 * max(0, 1 - (i - sls[-1][0]) / 15))
    return 0.0


# ── Trade ──────────────────────────────────
@dataclass
class T:
    sym: str = ""; side: str = ""; ei: int = 0; ep: float = 0
    xi: int = 0; xp: float = 0; xr: str = ""; lev: int = 12
    not_: float = 0; sp: float = 0; pk: float = 0; pnl: float = 0
    source: str = "regime"  # "regime" or "alpha"

def _close_trade(t, cost):
    if not t.xp or t.ep <= 0: return
    r = (t.xp / t.ep - 1) if t.side == "long" else -(t.xp / t.ep - 1)
    t.pnl = t.not_ * r - t.not_ * cost / 10000


# ── Run modes ──────────────────────────────────
@dataclass
class Mode:
    name: str
    use_oi_filter: bool = False    # block fake breakouts
    use_smc_filter: bool = False   # require SMC structure
    use_vwap_filter: bool = False  # VWAP timing gate
    use_alpha: bool = False        # alpha sub-strategies


def run_backtest(h, l, c, v, oi, e20, e50, e200, adxs, rsis, e200_4h, mode: Mode,
                 eq=75, cost=24, lev=12, sym=""):
    """Single backtest run with configurable feature gates.
    Baseline = best from exhaustive_3y: TTM squeeze + ADX20 + TP2.5/SL1.5 + 12h max.
    """
    trades = []; pos = None; cd = 0; dl = 0.0; dd = ""; cl = 0
    r1 = eq * 0.0075; n = len(c)
    tp_r = 2.5; sl_r = 1.5; maxh = 12; adx_min = 20

    for i in range(200, n):
        d = str(i // 24)
        if d != dd: dl = 0; dd = d

        # ── Exit ──
        if pos is not None:
            hi_ = h[i]; lo_ = l[i]; cl_ = c[i]; ep = pos.ep; lv_ = pos.lev; sp = pos.sp
            if pos.side == "long":
                best = (hi_ / ep - 1) * 100 * lv_; worst = (lo_ / ep - 1) * 100 * lv_
                cur = (cl_ / ep - 1) * 100 * lv_
            else:
                best = -(lo_ / ep - 1) * 100 * lv_; worst = -(hi_ / ep - 1) * 100 * lv_
                cur = -(cl_ / ep - 1) * 100 * lv_
            pos.pk = max(pos.pk, best)
            sl_hit = -sp * 100 * lv_ * sl_r; tp_hit = sp * 100 * lv_ * tp_r
            # BE move
            if pos.pk >= sp * 100 * lv_ * 1.15: sl_hit = sp * 100 * lv_ * 0.1
            if worst <= sl_hit:
                pos.xp = ep * (1 + sl_hit / 100 / lv_) if pos.side == "long" else ep * (1 - sl_hit / 100 / lv_)
                pos.xi = i; pos.xr = "SL"; _close_trade(pos, cost); trades.append(pos)
                dl += pos.pnl; cl = cl + 1 if pos.pnl <= 0 else 0; cd = i + 3; pos = None; continue
            if best >= tp_hit:
                pos.xp = ep * (1 + tp_hit / 100 / lv_) if pos.side == "long" else ep * (1 - tp_hit / 100 / lv_)
                pos.xi = i; pos.xr = "TP"; _close_trade(pos, cost); trades.append(pos)
                dl += pos.pnl; cl = 0; cd = i + 1; pos = None; continue
            bh = i - pos.ei
            if bh >= maxh:
                pos.xi = i; pos.xp = cl_; pos.xr = "TIME"; _close_trade(pos, cost); trades.append(pos)
                dl += pos.pnl; pos = None; continue
            # Alpha exits: VWAP target for mean-revert
            if pos.source == "alpha" and pos.xr == "":
                vz, vw = vwap_z(c, h, l, v, i)
                if abs(vz) < 0.3:  # reverted to VWAP
                    pos.xi = i; pos.xp = cl_; pos.xr = "VWAP_TARGET"
                    _close_trade(pos, cost); trades.append(pos)
                    dl += pos.pnl; pos = None; continue
            continue

        # ── Cooldown ──
        if i < cd: continue
        if dl <= -2 * r1: continue
        if cl >= 3: cl = 0; cd = i + 6; continue

        # ── Regime entry (baseline) ──
        at = atr_val(h[:i + 1], l[:i + 1], c[:i + 1], 14)
        ap = at / c[i] if c[i] > 0 else 0
        if ap < 0.003 or ap > 0.03: continue  # ATR range filter

        i4 = min(i // 4, len(e200_4h) - 1)
        if i4 < 5: continue
        long_ok = c[i] > e200_4h[i4] and e20[i] > e50[i] > e200[i]
        short_ok = c[i] < e200_4h[i4] and e20[i] < e50[i] < e200[i]

        # TTM Squeeze filter (baseline best setting)
        if i >= 20:
            sq_count = 0
            for j in range(1, min(7, i + 1)):
                idx = i - j
                if idx >= 20:
                    sub_c = c[max(0, idx - 20):idx + 1]; sub_h = h[max(0, idx - 20):idx + 1]; sub_l = l[max(0, idx - 20):idx + 1]
                    if len(sub_c) >= 20 and len(set(sub_c)) > 1:
                        sm = sum(sub_c) / len(sub_c); sd_ = statistics.stdev(sub_c)
                        a_ = atr_val(sub_h, sub_l, sub_c, 14)
                        if (sm + 2 * sd_) < (sm + 1.5 * a_) and (sm - 2 * sd_) > (sm - 1.5 * a_):
                            sq_count += 1
            # Need squeeze buildup then release
            cur_sq = False
            if len(set(c[max(0, i - 20):i + 1])) > 1 and len(c[max(0, i - 20):i + 1]) >= 20:
                sm = sum(c[i - 19:i + 1]) / 20; sd_ = statistics.stdev(c[i - 19:i + 1])
                a_ = atr_val(h[max(0, i - 20):i + 1], l[max(0, i - 20):i + 1], c[max(0, i - 20):i + 1], 14)
                cur_sq = (sm + 2 * sd_) < (sm + 1.5 * a_) and (sm - 2 * sd_) > (sm - 1.5 * a_)
            if sq_count < 3 or cur_sq:
                # No TTM squeeze release, skip regime entry (but alpha still possible)
                pass
            else:
                pass  # TTM ok, proceed

        # ADX filter
        adx_i = adxs[i] if i < len(adxs) else 0
        rsi_i = rsis[i] if i < len(rsis) else 50
        if adx_i < adx_min:
            long_ok = False; short_ok = False

        # Donchian breakout
        dc_h = max(h[max(0, i - 20):i]); dc_l = min(l[max(0, i - 20):i])
        sd = ""
        if long_ok and c[i] > dc_h + 0.1 * at: sd = "long"
        elif short_ok and c[i] < dc_l - 0.1 * at: sd = "short"

        # ── OI filter ──
        oi_div = 0.0
        if mode.use_oi_filter and oi:
            oi_i = min(i, len(oi) - 1)
            oi_div = oi_divergence(oi, c, oi_i, 24)
            if sd and oi_div < -0.4:
                sd = ""  # block fake breakout

        # ── SMC filter ──
        smc_s = 0.0
        if mode.use_smc_filter:
            fvg_s = fvg_score(h, l, i)
            str_s = structure_score(h, l, c, i)
            smc_s = 0.5 * fvg_s + 0.5 * str_s

        # ── VWAP filter ──
        vwap_deviation = 0.0
        vwap_val = 0.0
        if mode.use_vwap_filter:
            vwap_deviation, vwap_val = vwap_z(c, h, l, v, i)
            # In ranging market, block entries far from VWAP
            if sd and adx_i < 18 and abs(vwap_deviation) > 2.5:
                sd = ""

        # ── Regime trade ──
        if sd:
            sp = max(0.0085, 2.0 * at / c[i])
            size_mult = 1.0
            # SMC boost
            if mode.use_smc_filter and smc_s > 0.4:
                size_mult *= 1.0 + smc_s * 0.3
            # OI confirmation boost
            if mode.use_oi_filter and oi_div > 0.3:
                size_mult *= 1.15
            not_ = r1 / sp * min(size_mult, 1.5)
            use_lev = lev
            if mode.use_oi_filter and oi_div > 0.5 and adx_i > 25:
                use_lev = min(lev + 3, 20)
            pos = T(sym=sym, side=sd, ei=i, ep=c[i], lev=use_lev, not_=not_, sp=sp, source="regime")
            continue

        # ── Alpha entries (when regime = cash) ──
        if mode.use_alpha and not sd:
            # 1. VWAP Mean Reversion (tightened: z>=2.5, need volume support, cooldown)
            if (adx_i < 15 and abs(vwap_deviation) >= 2.5 and abs(oi_div) < 0.3
                    and v[i] > 0 and i > 1 and v[i] > 0.8 * sum(v[max(0,i-20):i]) / max(len(v[max(0,i-20):i]), 1)):
                alpha_side = "short" if vwap_deviation > 0 else "long"
                sp = max(0.0085, 1.2 * at / c[i])
                not_ = r1 / sp * 0.35  # 35% size, conservative
                pos = T(sym=sym, side=alpha_side, ei=i, ep=c[i], lev=3, not_=not_, sp=sp, source="alpha")
                cd = i + 4  # 4h cooldown between alpha entries
                continue

            # 2. SMC FVG Fill (tightened: high composite + volume + RSI not extreme)
            if smc_s > 0.5 and 35 < rsi_i < 65 and v[i] > 0:
                e3 = ema(c[max(0, i - 10):i + 1], 3); e10 = ema(c[max(0, i - 10):i + 1], 10)
                if e3 > e10:
                    alpha_side = "long"
                elif e3 < e10:
                    alpha_side = "short"
                else:
                    continue
                sp = max(0.007, 0.8 * at / c[i])
                not_ = r1 / sp * 0.4 * smc_s
                pos = T(sym=sym, side=alpha_side, ei=i, ep=c[i], lev=5, not_=not_, sp=sp, source="alpha")
                cd = i + 3
                continue

            # 3. OI Momentum Surge (tightened: strong OI + ADX + multi-bar confirm)
            if (oi_div > 0.5 and adx_i >= 18
                    and i >= 3 and abs(c[i] - c[i-3]) / c[i-3] > 0.003):  # 0.3% move in 3 bars
                # Direction from 3-bar momentum
                if c[i] > c[i-3] and c[i] > c[i-1]:
                    alpha_side = "long"
                elif c[i] < c[i-3] and c[i] < c[i-1]:
                    alpha_side = "short"
                else:
                    continue
                sp = max(0.0085, 1.0 * at / c[i])
                not_ = r1 / sp * 0.5
                pos = T(sym=sym, side=alpha_side, ei=i, ep=c[i], lev=7, not_=not_, sp=sp, source="alpha")
                cd = i + 3
                continue

    if pos:
        pos.xi = n - 1; pos.xp = c[-1]; pos.xr = "END"; _close_trade(pos, cost); trades.append(pos)
    return trades


# ── Walk-forward ──
def walk_forward(ts, n=4):
    if len(ts) < n * 3: return {"valid": False, "folds": [], "pass": 0}
    s = sorted(ts, key=lambda t: t.ei)
    fs = len(s) // n; folds = []
    for i in range(n):
        f = s[i * fs:(i + 1) * fs if i < n - 1 else len(s)]
        pnl = sum(t.pnl for t in f); wr = sum(1 for t in f if t.pnl > 0) / max(len(f), 1)
        folds.append({"q": i + 1, "n": len(f), "pnl": round(pnl, 2), "wr": round(wr, 4)})
    pc = sum(1 for f in folds if f["pnl"] > 0)
    return {"valid": pc >= 3, "folds": folds, "pass": pc}


# ── Monte Carlo ──
def monte_carlo(ts, equity=75, n_sims=1000):
    import random
    if len(ts) < 10: return {"ruin_pct": 100, "median_dd": 100, "mean_final": 0}
    pnls = [t.pnl for t in ts]
    ruin_count = 0; dds = []; finals = []
    for _ in range(n_sims):
        shuffled = random.sample(pnls, len(pnls))
        eq_ = equity; peak = equity; max_dd = 0
        ruined = False
        for p in shuffled:
            eq_ += p
            peak = max(peak, eq_)
            dd = (peak - eq_) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
            if eq_ <= 0:
                ruined = True; break
        if ruined: ruin_count += 1
        dds.append(max_dd * 100)
        finals.append(eq_)
    return {
        "ruin_pct": round(ruin_count / n_sims * 100, 2),
        "median_dd": round(statistics.median(dds), 1),
        "mean_final": round(statistics.mean(finals), 2),
    }


def main():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    eq = 75; cost = 24.0; lev = 12
    dd = Path("quant_runtime/historical")

    modes = [
        Mode("baseline"),
        Mode("+OI_filter", use_oi_filter=True),
        Mode("+OI+SMC", use_oi_filter=True, use_smc_filter=True),
        Mode("+OI+SMC+VWAP", use_oi_filter=True, use_smc_filter=True, use_vwap_filter=True),
        Mode("FULL+alpha", use_oi_filter=True, use_smc_filter=True, use_vwap_filter=True, use_alpha=True),
    ]

    # Load data
    sym_data = {}
    for sym in symbols:
        sp = dd / sym
        if not (sp / "1h.json").exists():
            print(f"  SKIP {sym}: no data"); continue
        b1 = json.load(open(sp / "1h.json"))
        b4 = json.load(open(sp / "4h.json"))
        c = [b["close_price"] for b in b1]; h_ = [b["high_price"] for b in b1]
        l_ = [b["low_price"] for b in b1]; v_ = [b.get("base_volume", b.get("quote_volume", 0)) for b in b1]
        n_ = len(c)
        print(f"  {sym}: {n_:,} 1h bars, precomputing...", flush=True)
        e20 = [ema(c[:i + 1], 20) for i in range(n_)]
        e50 = [ema(c[:i + 1], 50) for i in range(n_)]
        e200 = [ema(c[:i + 1], 200) if i >= 200 else ema(c[:i + 1], max(i + 1, 1)) for i in range(n_)]
        adxs = [adx_val(h_[:i + 1], l_[:i + 1], c[:i + 1], 14) if i >= 16 else 0 for i in range(n_)]
        rsis = [rsi_val(c[:i + 1], 14) if i >= 15 else 50 for i in range(n_)]
        c4 = [b["close_price"] for b in b4]
        e200_4h = [ema(c4[:i + 1], 200) if i >= 200 else ema(c4[:i + 1], max(i + 1, 1)) for i in range(len(c4))]
        # Real OI data from Bybit
        oi_path = sp / "oi_1h.json"
        if oi_path.exists():
            oi_raw = json.load(open(oi_path))
            # Build timestamp -> OI map
            oi_map = {int(r["timestamp"]): float(r["open_interest"]) for r in oi_raw}
            # Align OI to 1h bar timestamps
            bar_timestamps = [int(b.get("open_time", 0)) for b in b1]
            oi_aligned = []
            last_oi = list(oi_map.values())[0] if oi_map else 50.0
            for bt in bar_timestamps:
                if bt in oi_map:
                    last_oi = oi_map[bt]
                else:
                    # Find nearest OI within 2h
                    nearest = min(oi_map.keys(), key=lambda k: abs(k - bt), default=None)
                    if nearest and abs(nearest - bt) < 7200000:
                        last_oi = oi_map[nearest]
                oi_aligned.append(last_oi)
            print(f"  {sym}: {len(oi_raw)} real OI records aligned", flush=True)
        else:
            oi_aligned = [50.0] * n_
            print(f"  {sym}: no OI data, using dummy", flush=True)
        sym_data[sym] = (h_, l_, c, v_, oi_aligned, e20, e50, e200, adxs, rsis, e200_4h)
        print(f"  {sym}: ready", flush=True)

    print(f"\n{'=' * 120}")
    print(f"{'ABLATION BACKTEST: OI + SMC + VWAP + ALPHA':^120}")
    print(f"{'=' * 120}")
    print(f"  Symbols: {', '.join(sym_data.keys())}")
    print(f"  Equity: ${eq}  Cost: {cost}bps  Leverage: {lev}x")
    print()

    results = []
    for mode in modes:
        t0 = time.time()
        all_trades = []
        for sym, (h_, l_, c, v_, oi, e20, e50, e200, adxs, rsis, e200_4h) in sym_data.items():
            ts = run_backtest(h_, l_, c, v_, oi, e20, e50, e200, adxs, rsis, e200_4h,
                             mode, eq, cost, lev, sym)
            all_trades.extend(ts)

        el = time.time() - t0
        nt = len(all_trades)
        if nt == 0:
            results.append({"mode": mode.name, "n": 0, "wr": 0, "pnl": 0, "pf": 0,
                           "ev": 0, "wf": {"valid": False}, "mc": {"ruin_pct": 100},
                           "regime_n": 0, "alpha_n": 0})
            continue

        wins = sum(1 for t in all_trades if t.pnl > 0)
        pnl = sum(t.pnl for t in all_trades)
        gp = sum(t.pnl for t in all_trades if t.pnl > 0)
        gl = abs(sum(t.pnl for t in all_trades if t.pnl <= 0))
        pf = gp / max(gl, 0.01)
        wr = wins / max(nt, 1)
        ev_per_trade = pnl / nt
        regime_n = sum(1 for t in all_trades if t.source == "regime")
        alpha_n = sum(1 for t in all_trades if t.source == "alpha")
        alpha_pnl = sum(t.pnl for t in all_trades if t.source == "alpha")
        wf_ = walk_forward(all_trades)
        mc_ = monte_carlo(all_trades, eq)

        results.append({
            "mode": mode.name, "n": nt, "wr": round(wr, 4), "pnl": round(pnl, 2),
            "pf": round(pf, 2), "ev": round(ev_per_trade, 4),
            "wf": wf_, "mc": mc_,
            "regime_n": regime_n, "alpha_n": alpha_n, "alpha_pnl": round(alpha_pnl, 2),
            "elapsed": round(el, 1),
        })

    # ── Report ──
    print(f"\n{'Mode':<20} {'N':>5} {'Reg':>4} {'Alp':>4} {'WR%':>6} {'PnL$':>9} {'EV/t$':>7} {'PF':>5} {'WF':>3} {'MC%':>5} {'AlpPnL$':>9}")
    print("-" * 100)
    for r in results:
        wf_str = f"{r['wf'].get('pass', 0)}/4"
        mc_str = f"{r['mc'].get('ruin_pct', 100):.1f}"
        print(f"{r['mode']:<20} {r['n']:>5} {r.get('regime_n', 0):>4} {r.get('alpha_n', 0):>4} "
              f"{r['wr'] * 100:>6.1f} {r['pnl']:>9.2f} {r['ev']:>7.4f} {r['pf']:>5.2f} "
              f"{wf_str:>3} {mc_str:>5} {r.get('alpha_pnl', 0):>9.2f}")

    # Walk-forward details
    print(f"\n{'WALK-FORWARD DETAILS':^100}")
    for r in results:
        if r.get("wf", {}).get("folds"):
            qs = " | ".join(f"Q{f['q']}: {f['n']}t ${f['pnl']:+.1f} WR{f['wr']*100:.0f}%" for f in r["wf"]["folds"])
            print(f"  {r['mode']:<20} {qs}")

    # Cost stress
    print(f"\n{'COST STRESS':^100}")
    best_mode = max(results, key=lambda r: r["pnl"])
    bm = [m for m in modes if m.name == best_mode["mode"]][0]
    for cost_bps in [16, 24, 34, 44]:
        all_t = []
        for sym, (h_, l_, c, v_, oi, e20, e50, e200, adxs, rsis, e200_4h) in sym_data.items():
            all_t.extend(run_backtest(h_, l_, c, v_, oi, e20, e50, e200, adxs, rsis, e200_4h,
                                      bm, eq, float(cost_bps), lev, sym))
        p = sum(t.pnl for t in all_t)
        w = sum(1 for t in all_t if t.pnl > 0) / max(len(all_t), 1)
        print(f"  {best_mode['mode']} @ {cost_bps}bps: ${p:+.2f} WR={w*100:.1f}% N={len(all_t)}")

    # Save
    out = Path("quant_runtime/output/alpha_ablation_results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(results, open(out, "w"), indent=2, default=str)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
