#!/usr/bin/env python3
"""
Profit Maximizer Backtest — 5가지 수익극대화 전략 검증
=====================================================

기준선: EMA 9/21 + ADX≥28 + Partial TP (1R/2.5R), 고정 1.5x 레버리지
각 전략을 기준선 대비 개선 폭으로 측정.

테스트:
1. 동적 레버리지 (ADX 강도에 비례: 1.5x~3x)
2. 엔트리 겹침 해소 (동시 진입 시 최강 신호만)
3. 피라미딩 (1R 이익 구간에서 50% 추가 진입)
4. 세션 필터 (유럽+미국 08-20 UTC vs 전체)
5. 변동성 스케일링 (ATR 대비 사이즈 조절)

각각 + 조합 테스트. MC ruin <5% 통과해야 채택.
"""
from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict

import numpy as np

HIST_DIR = Path(__file__).resolve().parent.parent / "quant_runtime" / "historical"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]  # XRP 제외
BASE_FEE_BPS = 4.0
BASE_SLIP_BPS = 3.0
RT_COST_BPS = 2 * BASE_FEE_BPS + 2 * BASE_SLIP_BPS  # 14
ATR_STOP_MULT = 1.5
STOP_FLOOR_BPS = 45.0
BASE_LEVERAGE = 1.5
EQUITY_USD = 10000.0
RISK_PER_TRADE = 0.0035  # 0.35%


def load(sym, tf):
    p = HIST_DIR / sym / f"{tf}.json"
    if not p.exists(): return {}
    with open(p) as f: raw = json.load(f)
    return {
        "t": np.array([c["open_time"] for c in raw], dtype=np.int64),
        "o": np.array([c["open_price"] for c in raw], dtype=np.float64),
        "h": np.array([c["high_price"] for c in raw], dtype=np.float64),
        "l": np.array([c["low_price"] for c in raw], dtype=np.float64),
        "c": np.array([c["close_price"] for c in raw], dtype=np.float64),
        "v": np.array([c["quote_volume"] for c in raw], dtype=np.float64),
    }


# ── Indicators ────────────────────────────────────────
def _ema(a, p):
    r = np.full_like(a, np.nan, dtype=np.float64)
    if len(a) < p: return r
    al = 2.0/(p+1); r[p-1] = np.mean(a[:p])
    for i in range(p, len(a)): r[i] = al*a[i] + (1-al)*r[i-1]
    return r

def _atr(h, l, c, p=14):
    r = np.full_like(c, np.nan)
    if len(c) < p+1: return r
    tr = np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
    av = np.full(len(tr), np.nan); av[p-1]=np.mean(tr[:p])
    for i in range(p, len(tr)): av[i]=(av[i-1]*(p-1)+tr[i])/p
    r[1:]=av; return r

def _atr_sma(atr_arr, p=50):
    r = np.full_like(atr_arr, np.nan)
    if len(atr_arr) < p: return r
    cs = np.cumsum(np.nan_to_num(atr_arr))
    for i in range(p-1, len(atr_arr)):
        if not np.isnan(atr_arr[i]):
            s = cs[i] - (cs[i-p] if i >= p else 0)
            cnt = sum(1 for j in range(i-p+1, i+1) if not np.isnan(atr_arr[j]))
            r[i] = s / max(cnt, 1)
    return r

def _adx(h, l, c, p=14):
    r = np.full_like(c, np.nan); n = len(c)
    if n < 2*p+1: return r
    up=h[1:]-h[:-1]; down=l[:-1]-l[1:]
    pdm=np.where((up>down)&(up>0),up,0.0); mdm=np.where((down>up)&(down>0),down,0.0)
    tr=np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
    st=np.full(len(tr),np.nan); sp=np.full(len(tr),np.nan); sm=np.full(len(tr),np.nan)
    st[p-1]=np.sum(tr[:p]); sp[p-1]=np.sum(pdm[:p]); sm[p-1]=np.sum(mdm[:p])
    for i in range(p, len(tr)):
        st[i]=st[i-1]-st[i-1]/p+tr[i]; sp[i]=sp[i-1]-sp[i-1]/p+pdm[i]; sm[i]=sm[i-1]-sm[i-1]/p+mdm[i]
    pdi=100*sp/np.where(st==0,1e-10,st); mdi=100*sm/np.where(st==0,1e-10,st)
    dx=100*np.abs(pdi-mdi)/np.where((pdi+mdi)==0,1e-10,pdi+mdi)
    av=np.full(len(dx),np.nan); s2=2*p-1
    if s2<len(dx):
        av[s2]=np.mean(dx[p-1:s2+1])
        for i in range(s2+1, len(dx)): av[i]=(av[i-1]*(p-1)+dx[i])/p
    r[1:]=av; return r


# ── Signal detection ──────────────────────────────────
def detect_signals(d):
    """Return list of (index, side, adx_value, atr_value, atr_sma_value, hour_utc)."""
    c = d["c"]; ef = _ema(c, 9); es = _ema(c, 21)
    ax = _adx(d["h"], d["l"], c); at = _atr(d["h"], d["l"], c)
    at_sma = _atr_sma(at, 50)
    signals = []
    for i in range(30, len(c)):
        if any(np.isnan(x[i]) for x in [ef, es, ax, at]) or any(np.isnan(x[i-1]) for x in [ef, es]):
            continue
        if ax[i] < 28: continue
        up = ef[i-1] <= es[i-1] and ef[i] > es[i]
        dn = ef[i-1] >= es[i-1] and ef[i] < es[i]
        if not (up or dn): continue
        hour = (d["t"][i] // 3600000) % 24
        ats = at_sma[i] if not np.isnan(at_sma[i]) else at[i]
        signals.append({
            "idx": i, "side": "long" if up else "short",
            "adx": ax[i], "atr": at[i], "atr_sma": ats, "hour": hour,
            "ts": int(d["t"][i]), "price": c[i],
        })
    return signals


# ── Trade execution with configurable leverage & sizing ─
def execute_trade(d, sig, *, leverage=1.5, size_mult=1.0, rr1=1.0, rr2=2.5, hold=24):
    """Execute partial TP trade. Returns dict with PnL in USD terms."""
    i = sig["idx"]; c = d["c"]; h = d["h"]; l = d["l"]
    if i >= len(c) - 2: return None
    entry = c[i]; side = sig["side"]; atr_val = sig["atr"]

    sl_dist = max(ATR_STOP_MULT * atr_val, entry * STOP_FLOOR_BPS / 10000)
    tp1_dist = rr1 * sl_dist
    tp2_dist = rr2 * sl_dist
    sl_bps = sl_dist / entry * 10000

    # Position sizing
    risk_usd = EQUITY_USD * RISK_PER_TRADE * size_mult
    notional = risk_usd / (sl_bps / 10000) * leverage
    notional = min(notional, EQUITY_USD * 0.5 * leverage)  # cap at 50% equity * leverage

    if side == "long":
        sl_p = entry - sl_dist; tp1_p = entry + tp1_dist; tp2_p = entry + tp2_dist
    else:
        sl_p = entry + sl_dist; tp1_p = entry - tp1_dist; tp2_p = entry - tp2_dist

    exit_idx = min(i + hold, len(c) - 1)
    half = False; half_pnl = 0.0; be_stop = entry

    for j in range(i + 1, exit_idx + 1):
        if not half:
            if side == "long":
                if l[j] <= sl_p:
                    pnl = notional * (sl_p - entry) / entry - notional * RT_COST_BPS / 10000
                    return {"pnl": pnl, "bps": (sl_p-entry)/entry*10000 - RT_COST_BPS, "reason": "SL", "bars": j-i, "leverage": leverage, "notional": notional, "idx": i}
                if h[j] >= tp1_p:
                    half_pnl = (notional/2) * (tp1_p - entry) / entry
                    half = True; be_stop = entry + sl_dist * 0.1
            else:
                if h[j] >= sl_p:
                    pnl = notional * (entry - sl_p) / entry - notional * RT_COST_BPS / 10000
                    return {"pnl": pnl, "bps": (entry-sl_p)/entry*10000 - RT_COST_BPS, "reason": "SL", "bars": j-i, "leverage": leverage, "notional": notional, "idx": i}
                if l[j] <= tp1_p:
                    half_pnl = (notional/2) * (entry - tp1_p) / entry
                    half = True; be_stop = entry - sl_dist * 0.1
        else:
            if side == "long":
                if l[j] <= be_stop:
                    pnl2 = (notional/2) * (be_stop - entry) / entry
                    total = half_pnl + pnl2 - notional * RT_COST_BPS / 10000
                    return {"pnl": total, "bps": total/notional*10000, "reason": "BE", "bars": j-i, "leverage": leverage, "notional": notional, "idx": i}
                if h[j] >= tp2_p:
                    pnl2 = (notional/2) * (tp2_p - entry) / entry
                    total = half_pnl + pnl2 - notional * RT_COST_BPS / 10000
                    return {"pnl": total, "bps": total/notional*10000, "reason": "TP2", "bars": j-i, "leverage": leverage, "notional": notional, "idx": i}
            else:
                if h[j] >= be_stop:
                    pnl2 = (notional/2) * (entry - be_stop) / entry
                    total = half_pnl + pnl2 - notional * RT_COST_BPS / 10000
                    return {"pnl": total, "bps": total/notional*10000, "reason": "BE", "bars": j-i, "leverage": leverage, "notional": notional, "idx": i}
                if l[j] <= tp2_p:
                    pnl2 = (notional/2) * (entry - tp2_p) / entry
                    total = half_pnl + pnl2 - notional * RT_COST_BPS / 10000
                    return {"pnl": total, "bps": total/notional*10000, "reason": "TP2", "bars": j-i, "leverage": leverage, "notional": notional, "idx": i}

    ep = c[exit_idx]
    if half:
        pnl2 = (notional/2) * ((ep-entry)/entry if side=="long" else (entry-ep)/entry)
        total = half_pnl + pnl2 - notional * RT_COST_BPS / 10000
    else:
        raw = notional * ((ep-entry)/entry if side=="long" else (entry-ep)/entry)
        total = raw - notional * RT_COST_BPS / 10000
    return {"pnl": total, "bps": total/notional*10000 if notional>0 else 0, "reason": "TIME", "bars": exit_idx-i, "leverage": leverage, "notional": notional, "idx": i}


# ── Pyramid add ───────────────────────────────────────
def try_pyramid(d, parent_trade, sig, *, leverage, size_mult=0.5):
    """Check if price hit 1R profit and add position there."""
    i = sig["idx"]; c = d["c"]; h = d["h"]; l = d["l"]
    entry = c[i]; atr_val = sig["atr"]
    sl_dist = max(ATR_STOP_MULT * atr_val, entry * STOP_FLOOR_BPS / 10000)
    tp1_dist = sl_dist  # 1R level

    # Find when 1R was hit
    exit_bar = i + parent_trade["bars"]
    for j in range(i + 1, min(exit_bar, len(c))):
        hit_1r = False
        if sig["side"] == "long" and h[j] >= entry + tp1_dist:
            hit_1r = True; add_entry = entry + tp1_dist
        elif sig["side"] == "short" and l[j] <= entry - tp1_dist:
            hit_1r = True; add_entry = entry - tp1_dist

        if hit_1r:
            # Open pyramid at 1R with tighter stop (0.5R from add entry)
            add_sl_dist = 0.5 * sl_dist
            risk_usd = EQUITY_USD * RISK_PER_TRADE * size_mult
            add_notional = risk_usd / (add_sl_dist / add_entry * 10000 / 10000) * leverage
            add_notional = min(add_notional, EQUITY_USD * 0.25 * leverage)

            # Simulate from add point to parent exit
            remaining_bars = exit_bar - j
            if remaining_bars < 1: return None

            if sig["side"] == "long":
                add_sl = add_entry - add_sl_dist
                # Check if hit SL or ride to parent exit
                for k in range(j + 1, exit_bar + 1):
                    if k >= len(c): break
                    if l[k] <= add_sl:
                        pnl = add_notional * (add_sl - add_entry) / add_entry - add_notional * RT_COST_BPS / 10000
                        return {"pnl": pnl, "type": "pyramid"}
                ep = c[min(exit_bar, len(c)-1)]
                pnl = add_notional * (ep - add_entry) / add_entry - add_notional * RT_COST_BPS / 10000
            else:
                add_sl = add_entry + add_sl_dist
                for k in range(j + 1, exit_bar + 1):
                    if k >= len(c): break
                    if h[k] >= add_sl:
                        pnl = add_notional * (add_entry - add_sl) / add_entry - add_notional * RT_COST_BPS / 10000
                        return {"pnl": pnl, "type": "pyramid"}
                ep = c[min(exit_bar, len(c)-1)]
                pnl = add_notional * (add_entry - ep) / add_entry - add_notional * RT_COST_BPS / 10000

            return {"pnl": pnl, "type": "pyramid"}
    return None


# ── Monte Carlo ───────────────────────────────────────
def mc_ruin(returns, n_sims=10000, n_per=200, ruin_pct=-30.0):
    if len(returns) < 3: return 1.0, -9999, 0
    ret = np.array(returns); rng = np.random.default_rng(42)
    ruin_ct = 0; dds = []; eqs = []
    thr = ruin_pct / 100 * EQUITY_USD
    for _ in range(n_sims):
        s = rng.choice(ret, n_per, replace=True)
        eq = np.cumsum(s); pk = np.maximum.accumulate(eq); dd = eq - pk
        md = np.min(dd); dds.append(md); eqs.append(eq[-1])
        if md < thr: ruin_ct += 1
    return ruin_ct / n_sims, float(np.median(dds)), float(np.median(eqs))


# ── Strategy variants ─────────────────────────────────
def run_baseline(all_signals, all_data):
    """Baseline: fixed 1.5x leverage, no filters."""
    trades = []
    for sym in SYMBOLS:
        d = all_data[sym]; sigs = all_signals[sym]
        i = 0
        while i < len(sigs):
            sig = sigs[i]
            t = execute_trade(d, sig, leverage=BASE_LEVERAGE)
            if t:
                t["sym"] = sym; trades.append(t)
                # Skip overlapping
                end_idx = sig["idx"] + t["bars"]
                i += 1
                while i < len(sigs) and sigs[i]["idx"] < end_idx: i += 1
            else:
                i += 1
    return trades


def run_dynamic_leverage(all_signals, all_data, min_lev=1.5, max_lev=3.0, adx_floor=28, adx_ceil=45):
    """Strategy 1: Leverage scales with ADX strength."""
    trades = []
    for sym in SYMBOLS:
        d = all_data[sym]; sigs = all_signals[sym]
        i = 0
        while i < len(sigs):
            sig = sigs[i]
            # Scale leverage: ADX 28 → 1.5x, ADX 45 → 3x
            adx_norm = min((sig["adx"] - adx_floor) / (adx_ceil - adx_floor), 1.0)
            lev = min_lev + (max_lev - min_lev) * adx_norm
            t = execute_trade(d, sig, leverage=lev)
            if t:
                t["sym"] = sym; trades.append(t)
                end_idx = sig["idx"] + t["bars"]
                i += 1
                while i < len(sigs) and sigs[i]["idx"] < end_idx: i += 1
            else:
                i += 1
    return trades


def run_best_signal_only(all_signals, all_data, window_ms=3*3600*1000):
    """Strategy 2: When multiple symbols signal within window, take strongest ADX only."""
    # Merge all signals with symbol tag
    merged = []
    for sym in SYMBOLS:
        for sig in all_signals[sym]:
            merged.append({**sig, "sym": sym})
    merged.sort(key=lambda x: x["ts"])

    trades = []
    used_until = {sym: 0 for sym in SYMBOLS}

    i = 0
    while i < len(merged):
        sig = merged[i]
        sym = sig["sym"]
        if sig["idx"] < used_until[sym]:
            i += 1; continue

        # Find all signals within window
        group = [sig]
        j = i + 1
        while j < len(merged) and merged[j]["ts"] - sig["ts"] < window_ms:
            if merged[j]["idx"] >= used_until[merged[j]["sym"]]:
                group.append(merged[j])
            j += 1

        # Pick strongest ADX
        best = max(group, key=lambda x: x["adx"])
        d = all_data[best["sym"]]
        t = execute_trade(d, best, leverage=BASE_LEVERAGE)
        if t:
            t["sym"] = best["sym"]; trades.append(t)
            used_until[best["sym"]] = best["idx"] + t["bars"]
            # Block other symbols in this window
            for g in group:
                if g["sym"] != best["sym"]:
                    used_until[g["sym"]] = max(used_until[g["sym"]], best["idx"] + 2)
        i = j if j > i + 1 else i + 1

    return trades


def run_with_pyramid(all_signals, all_data):
    """Strategy 3: Base + pyramid at 1R."""
    trades = []
    for sym in SYMBOLS:
        d = all_data[sym]; sigs = all_signals[sym]
        i = 0
        while i < len(sigs):
            sig = sigs[i]
            t = execute_trade(d, sig, leverage=BASE_LEVERAGE)
            if t:
                t["sym"] = sym; trades.append(t)
                # Try pyramid
                pyr = try_pyramid(d, t, sig, leverage=BASE_LEVERAGE)
                if pyr:
                    pyr["sym"] = sym; trades.append(pyr)
                end_idx = sig["idx"] + t["bars"]
                i += 1
                while i < len(sigs) and sigs[i]["idx"] < end_idx: i += 1
            else:
                i += 1
    return trades


def run_session_filter(all_signals, all_data, start_hour=8, end_hour=20):
    """Strategy 4: Only enter during European+US session."""
    trades = []
    for sym in SYMBOLS:
        d = all_data[sym]
        sigs = [s for s in all_signals[sym] if start_hour <= s["hour"] <= end_hour]
        i = 0
        while i < len(sigs):
            sig = sigs[i]
            t = execute_trade(d, sig, leverage=BASE_LEVERAGE)
            if t:
                t["sym"] = sym; trades.append(t)
                end_idx = sig["idx"] + t["bars"]
                i += 1
                while i < len(sigs) and sigs[i]["idx"] < end_idx: i += 1
            else:
                i += 1
    return trades


def run_vol_scaling(all_signals, all_data, low_mult=0.5, high_mult=1.5):
    """Strategy 5: Scale position size by ATR relative to its 50-bar SMA."""
    trades = []
    for sym in SYMBOLS:
        d = all_data[sym]; sigs = all_signals[sym]
        i = 0
        while i < len(sigs):
            sig = sigs[i]
            ratio = sig["atr"] / sig["atr_sma"] if sig["atr_sma"] > 0 else 1.0
            # High vol (ratio > 1.2) → bigger size, low vol → smaller
            if ratio > 1.2:
                sm = min(high_mult, 0.5 + ratio)
            elif ratio < 0.8:
                sm = max(low_mult, ratio)
            else:
                sm = 1.0
            t = execute_trade(d, sig, leverage=BASE_LEVERAGE, size_mult=sm)
            if t:
                t["sym"] = sym; trades.append(t)
                end_idx = sig["idx"] + t["bars"]
                i += 1
                while i < len(sigs) and sigs[i]["idx"] < end_idx: i += 1
            else:
                i += 1
    return trades


def run_combined_best(all_signals, all_data):
    """Combine the best passing strategies."""
    # Dynamic leverage + best signal only + session filter
    merged = []
    for sym in SYMBOLS:
        for sig in all_signals[sym]:
            if 8 <= sig["hour"] <= 20:  # Session filter
                merged.append({**sig, "sym": sym})
    merged.sort(key=lambda x: x["ts"])

    trades = []
    used_until = {sym: 0 for sym in SYMBOLS}
    window_ms = 3 * 3600 * 1000

    i = 0
    while i < len(merged):
        sig = merged[i]
        sym = sig["sym"]
        if sig["idx"] < used_until[sym]:
            i += 1; continue

        group = [sig]
        j = i + 1
        while j < len(merged) and merged[j]["ts"] - sig["ts"] < window_ms:
            if merged[j]["idx"] >= used_until[merged[j]["sym"]]:
                group.append(merged[j])
            j += 1

        best = max(group, key=lambda x: x["adx"])
        d = all_data[best["sym"]]

        # Dynamic leverage
        adx_norm = min((best["adx"] - 28) / 17.0, 1.0)
        lev = 1.5 + 1.5 * adx_norm

        # Vol scaling
        ratio = best["atr"] / best["atr_sma"] if best["atr_sma"] > 0 else 1.0
        sm = min(1.5, max(0.5, ratio)) if ratio > 1.2 or ratio < 0.8 else 1.0

        t = execute_trade(d, best, leverage=lev, size_mult=sm)
        if t:
            t["sym"] = best["sym"]; trades.append(t)
            used_until[best["sym"]] = best["idx"] + t["bars"]
            for g in group:
                if g["sym"] != best["sym"]:
                    used_until[g["sym"]] = max(used_until[g["sym"]], best["idx"] + 2)
        i = j if j > i + 1 else i + 1

    return trades


# ── Stats ─────────────────────────────────────────────
def calc(trades, label):
    if not trades:
        return {"label": label, "n": 0}
    pnls = [t["pnl"] for t in trades]
    n = len(pnls); wins = sum(1 for p in pnls if p > 0)
    gp = sum(p for p in pnls if p > 0); gl = abs(sum(p for p in pnls if p < 0))
    pf = gp / gl if gl > 0 else 999
    mc_r, mc_dd, mc_eq = mc_ruin(pnls)

    # Max consecutive loss
    mcl = 0; cur = 0
    for p in pnls:
        if p <= 0: cur += 1; mcl = max(mcl, cur)
        else: cur = 0

    # By symbol
    by_sym = defaultdict(list)
    for t in trades: by_sym[t.get("sym", "?")].append(t["pnl"])

    return {
        "label": label, "n": n, "wr": wins/n, "pf": min(pf, 999),
        "total_usd": sum(pnls), "avg_usd": float(np.mean(pnls)),
        "total_pct": sum(pnls) / EQUITY_USD * 100,
        "sharpe": float(np.mean(pnls) / np.std(pnls, ddof=1)) if n > 1 and np.std(pnls, ddof=1) > 0 else 0,
        "mc_ruin": mc_r, "mc_dd": mc_dd, "mc_eq": mc_eq, "max_consec_loss": mcl,
        "by_sym": {sym: {"n": len(ps), "total": sum(ps)} for sym, ps in by_sym.items()},
        "avg_leverage": float(np.mean([t.get("leverage", 1.5) for t in trades])),
        "avg_notional": float(np.mean([t.get("notional", 0) for t in trades])),
    }


def main():
    print("=" * 100)
    print("PROFIT MAXIMIZER BACKTEST — 5 Strategies + Combinations")
    print(f"Equity: ${EQUITY_USD:,.0f} | Symbols: {', '.join(SYMBOLS)} | Baseline: 1.5x leverage")
    print("=" * 100)

    # Load data & signals
    all_data = {}; all_signals = {}
    for sym in SYMBOLS:
        d = load(sym, "1h")
        if not d: print(f"  {sym}: no data"); continue
        all_data[sym] = d
        sigs = detect_signals(d)
        all_signals[sym] = sigs
        print(f"  {sym}: {len(d['c'])} bars, {len(sigs)} signals detected")

    # Run all variants
    variants = [
        ("0_BASELINE", run_baseline(all_signals, all_data)),
        ("1_DYN_LEV_1.5-3x", run_dynamic_leverage(all_signals, all_data, 1.5, 3.0)),
        ("1_DYN_LEV_1.5-2.5x", run_dynamic_leverage(all_signals, all_data, 1.5, 2.5)),
        ("1_DYN_LEV_2-3x", run_dynamic_leverage(all_signals, all_data, 2.0, 3.0)),
        ("2_BEST_SIGNAL", run_best_signal_only(all_signals, all_data)),
        ("2_BEST_SIG_6h", run_best_signal_only(all_signals, all_data, 6*3600*1000)),
        ("3_PYRAMID", run_with_pyramid(all_signals, all_data)),
        ("4_SESSION_8-20", run_session_filter(all_signals, all_data, 8, 20)),
        ("4_SESSION_6-22", run_session_filter(all_signals, all_data, 6, 22)),
        ("4_SESSION_12-22", run_session_filter(all_signals, all_data, 12, 22)),
        ("5_VOL_SCALE", run_vol_scaling(all_signals, all_data)),
        ("5_VOL_SCALE_AGG", run_vol_scaling(all_signals, all_data, 0.3, 2.0)),
        ("6_COMBINED", run_combined_best(all_signals, all_data)),
    ]

    results = []
    for label, trades in variants:
        r = calc(trades, label)
        results.append(r)

    # Print results
    print(f"\n\n{'='*100}")
    print(f"  {'Strategy':<22} {'N':>3} {'WR':>5} {'PF':>6} {'Total$':>8} {'Tot%':>6} {'Avg$':>7} {'Shrp':>6} {'MCR':>5} {'MCDD':>8} {'MCL':>3} {'AvgLev':>6}  {'By Symbol'}")
    print(f"{'='*100}")

    for r in results:
        if r["n"] == 0:
            print(f"  {r['label']:<22} {'NO TRADES':>3}")
            continue
        pf_s = f"{r['pf']:.1f}" if r['pf'] < 100 else "inf"
        mc_s = f"{r['mc_ruin']:.0%}" if r['mc_ruin'] < 1 else "100%"
        sym_s = " | ".join(f"{s}:{d['n']}t ${d['total']:.0f}" for s, d in r["by_sym"].items())
        tag = " <<< PASS" if r["mc_ruin"] < 0.05 and r["pf"] > 1.3 and r["n"] >= 5 else ""
        print(f"  {r['label']:<22} {r['n']:>3} {r['wr']:>4.0%} {pf_s:>6} {r['total_usd']:>8.0f} {r['total_pct']:>5.1f}% {r['avg_usd']:>7.1f} {r['sharpe']:>6.3f} {mc_s:>5} {r['mc_dd']:>8.0f} {r['max_consec_loss']:>3} {r['avg_leverage']:>6.1f}x {sym_s}{tag}")

    # ── Comparison vs baseline ──
    baseline = results[0]
    if baseline["n"] > 0:
        print(f"\n\n{'='*100}")
        print("  IMPROVEMENT vs BASELINE")
        print(f"{'='*100}")
        for r in results[1:]:
            if r["n"] == 0: continue
            delta_usd = r["total_usd"] - baseline["total_usd"]
            delta_pct = delta_usd / EQUITY_USD * 100
            delta_pf = r["pf"] - baseline["pf"]
            eligible = r["mc_ruin"] < 0.05 and r["pf"] > 1.3
            tag = "PASS" if eligible else "FAIL"
            print(f"  [{tag}] {r['label']:<22} PnL: {'+' if delta_usd>=0 else ''}{delta_usd:>7.0f}$ ({'+' if delta_pct>=0 else ''}{delta_pct:.1f}%)  PF: {'+' if delta_pf>=0 else ''}{delta_pf:.2f}  MC: {r['mc_ruin']:.1%}")

    # Save
    out = Path(__file__).resolve().parent.parent / "quant_runtime" / "output" / "signal_research"
    out.mkdir(parents=True, exist_ok=True)
    save = []
    for r in results:
        save.append({k: (round(v, 4) if isinstance(v, float) else v)
                     for k, v in r.items() if k != "by_sym"})
    with open(out / "v6_profit_maximizer.json", "w") as f:
        json.dump(save, f, indent=2, default=str)
    print(f"\n결과 저장: {out / 'v6_profit_maximizer.json'}")


if __name__ == "__main__":
    main()
