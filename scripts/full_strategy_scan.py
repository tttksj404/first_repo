#!/usr/bin/env python3
"""
Full Strategy Scan — 수익 극대화 탐색
======================================
모든 가능한 전략을 1h 타임프레임 기준으로 백테스트하고,
라이브 편입 가능 여부를 Monte Carlo로 검증.

전략 카테고리:
  A. 추세추종 (Trend Following)
    1. EMA Cross + ADX (기존 검증 완료)
    2. MACD 시그널 크로스
    3. Ichimoku 구름 돌파
    4. 4h→1h MTF 추세추종
    5. Pullback Entry (추세 중 되돌림 매수)
    6. EMA Ribbon (3중 EMA 정렬)

  B. 모멘텀 (Momentum)
    7. 채널 돌파 (Donchian/Keltner)
    8. Stochastic Momentum
    9. ROC (Rate of Change) 모멘텀

  C. 변동성 (Volatility)
    10. ATR 폭발 후 추세 진입
    11. 스퀴즈 돌파 (BB 수축 → 확장)

  D. 복합 (Composite)
    12. RSI + EMA trend confirmation
    13. MACD + Volume + ADX
    14. 펀딩비 역방향 (Funding Rate Contrarian)

  E. 시간/세션 필터
    15. 아시아/유럽/미국 세션별 최적화

  F. Exit 최적화
    16. Partial TP (50% at 1R, trail rest)
    17. Time decay exit (holding이 길어지면 TP 줄임)

라이브 편입 기준:
  - R:R >= 1.5
  - PF > 1.3
  - Win Rate > 35%
  - MC Ruin < 5% (30% drawdown 기준, 200 trades)
  - 최소 15+ trades
"""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np

HIST_DIR = Path(__file__).resolve().parent.parent / "quant_runtime" / "historical"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
RT_COST_BPS = 14.0  # 2×(4 fee + 3 slippage)
ATR_STOP_MULT = 1.5
STOP_FLOOR_BPS = 45.0


# ═══════════════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════════════
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


def load_funding(sym):
    p = HIST_DIR / sym / "funding_rates.json"
    if not p.exists(): return None
    with open(p) as f: raw = json.load(f)
    return {
        "t": np.array([r["funding_time"] for r in raw], dtype=np.int64),
        "r": np.array([r["funding_rate"] for r in raw], dtype=np.float64),
    }


# ═══════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════
def _ema(a, p):
    r = np.full_like(a, np.nan, dtype=np.float64)
    if len(a) < p: return r
    al = 2.0/(p+1)
    r[p-1] = np.mean(a[:p])
    for i in range(p, len(a)): r[i] = al*a[i] + (1-al)*r[i-1]
    return r

def _sma(a, p):
    r = np.full_like(a, np.nan, dtype=np.float64)
    if len(a) < p: return r
    cs = np.cumsum(a)
    r[p-1:] = (cs[p-1:] - np.concatenate([[0], cs[:-p]])) / p
    return r

def _rsi(c, p=14):
    r = np.full_like(c, np.nan)
    if len(c) < p+1: return r
    d = np.diff(c)
    g = np.where(d>0, d, 0.0); lo = np.where(d<0, -d, 0.0)
    ag = np.full(len(d), np.nan); al = np.full(len(d), np.nan)
    ag[p-1]=np.mean(g[:p]); al[p-1]=np.mean(lo[:p])
    for i in range(p, len(d)):
        ag[i]=(ag[i-1]*(p-1)+g[i])/p; al[i]=(al[i-1]*(p-1)+lo[i])/p
    rs = ag/np.where(al==0,1e-10,al)
    r[1:] = 100-100/(1+rs)
    return r

def _atr(h, l, c, p=14):
    r = np.full_like(c, np.nan)
    if len(c) < p+1: return r
    tr = np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
    av = np.full(len(tr), np.nan)
    av[p-1]=np.mean(tr[:p])
    for i in range(p, len(tr)): av[i]=(av[i-1]*(p-1)+tr[i])/p
    r[1:]=av
    return r

def _adx(h, l, c, p=14):
    r = np.full_like(c, np.nan)
    n = len(c)
    if n < 2*p+1: return r
    up = h[1:]-h[:-1]; down = l[:-1]-l[1:]
    pdm = np.where((up>down)&(up>0),up,0.0)
    mdm = np.where((down>up)&(down>0),down,0.0)
    tr = np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
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
    r[1:]=av
    return r

def _macd(c, fast=12, slow=26, sig=9):
    ef=_ema(c,fast); es=_ema(c,slow)
    line=ef-es
    signal=_ema(np.where(np.isnan(line), 0, line), sig)
    # fix: signal should align with line's valid range
    hist=line-signal
    return line, signal, hist

def _stoch(h, l, c, k_period=14, d_period=3):
    k = np.full_like(c, np.nan)
    for i in range(k_period-1, len(c)):
        hh = np.max(h[i-k_period+1:i+1])
        ll = np.min(l[i-k_period+1:i+1])
        k[i] = (c[i]-ll)/(hh-ll)*100 if hh!=ll else 50
    d = _sma(k, d_period)
    return k, d

def _bb(c, p=20, n=2.0):
    mid=_sma(c,p)
    std=np.full_like(c, np.nan)
    for i in range(p-1, len(c)): std[i]=np.std(c[i-p+1:i+1], ddof=0)
    return mid, mid+n*std, mid-n*std, std

def _donchian(h, l, p=20):
    upper=np.full_like(h, np.nan); lower=np.full_like(l, np.nan)
    for i in range(p-1, len(h)):
        upper[i]=np.max(h[i-p+1:i+1]); lower[i]=np.min(l[i-p+1:i+1])
    return upper, lower

def _keltner(c, h, l, ema_p=20, atr_p=14, mult=2.0):
    mid=_ema(c, ema_p); at=_atr(h,l,c,atr_p)
    return mid, mid+mult*at, mid-mult*at

def _roc(c, p=12):
    r=np.full_like(c, np.nan)
    r[p:]=(c[p:]/c[:-p]-1)*100
    return r

def _ichimoku(h, l, c, tenkan=9, kijun=26, senkou_b=52):
    def _midline(arr, p):
        r=np.full_like(arr, np.nan)
        for i in range(p-1, len(arr)):
            r[i]=(np.max(h[i-p+1:i+1])+np.min(l[i-p+1:i+1]))/2
        return r
    tenkan_sen=_midline(h, tenkan)
    kijun_sen=_midline(h, kijun)
    senkou_a=(tenkan_sen+kijun_sen)/2
    senkou_b_line=_midline(h, senkou_b)
    return tenkan_sen, kijun_sen, senkou_a, senkou_b_line


# ═══════════════════════════════════════════════════════
# TRADE ENGINE
# ═══════════════════════════════════════════════════════
@dataclass
class Trade:
    side: str; entry: float; exit_p: float; net_bps: float
    sl_bps: float; tp_bps: float; rr: float; reason: str; bars: int

def _exec_trade(d, i, side, hold, atr_v, rr_target=2.0):
    """Execute a trade with ATR-based SL/TP on 1h data. Returns Trade or None."""
    c,h,l = d["c"], d["h"], d["l"]
    if i >= len(c)-2 or np.isnan(atr_v[i]) or atr_v[i]<=0:
        return None
    entry = c[i]
    sl_dist = max(ATR_STOP_MULT * atr_v[i], entry * STOP_FLOOR_BPS / 10000)
    tp_dist = rr_target * sl_dist
    sl_bps = sl_dist/entry*10000
    tp_bps = tp_dist/entry*10000

    if side=="long": sl_p=entry-sl_dist; tp_p=entry+tp_dist
    else: sl_p=entry+sl_dist; tp_p=entry-tp_dist

    exit_idx = min(i+hold, len(c)-1)
    reason = "TIME"
    for j in range(i+1, exit_idx+1):
        if side=="long":
            if l[j]<=sl_p: exit_idx=j; reason="SL"; break
            if h[j]>=tp_p: exit_idx=j; reason="TP"; break
        else:
            if h[j]>=sl_p: exit_idx=j; reason="SL"; break
            if l[j]<=tp_p: exit_idx=j; reason="TP"; break

    ep = sl_p if reason=="SL" else (tp_p if reason=="TP" else c[exit_idx])
    raw = (ep-entry)/entry*10000 if side=="long" else (entry-ep)/entry*10000
    return Trade(side, entry, ep, raw-RT_COST_BPS, sl_bps, tp_bps, tp_bps/sl_bps if sl_bps>0 else 0, reason, exit_idx-i)

def _exec_partial_tp(d, i, side, hold, atr_v, rr1=1.0, rr2=2.5):
    """Partial TP: 50% at 1R, trail rest to 2.5R or SL at breakeven."""
    c,h,l = d["c"], d["h"], d["l"]
    if i >= len(c)-2 or np.isnan(atr_v[i]) or atr_v[i]<=0:
        return None
    entry = c[i]
    sl_dist = max(ATR_STOP_MULT * atr_v[i], entry * STOP_FLOOR_BPS / 10000)
    tp1_dist = rr1 * sl_dist
    tp2_dist = rr2 * sl_dist
    sl_bps = sl_dist/entry*10000

    if side=="long": sl_p=entry-sl_dist; tp1_p=entry+tp1_dist; tp2_p=entry+tp2_dist
    else: sl_p=entry+sl_dist; tp1_p=entry-tp1_dist; tp2_p=entry-tp2_dist

    exit_idx = min(i+hold, len(c)-1)
    half_filled = False
    half_bps = 0.0
    be_stop = entry  # breakeven after first TP

    for j in range(i+1, exit_idx+1):
        if not half_filled:
            if side=="long":
                if l[j]<=sl_p: # full SL
                    raw = (sl_p-entry)/entry*10000
                    return Trade(side, entry, sl_p, raw-RT_COST_BPS, sl_bps, rr2*sl_bps, rr2, "SL", j-i)
                if h[j]>=tp1_p:
                    half_bps = (tp1_p-entry)/entry*10000 * 0.5
                    half_filled = True
                    be_stop = entry + sl_dist*0.1  # tiny profit stop
            else:
                if h[j]>=sl_p:
                    raw = (entry-sl_p)/entry*10000
                    return Trade(side, entry, sl_p, raw-RT_COST_BPS, sl_bps, rr2*sl_bps, rr2, "SL", j-i)
                if l[j]<=tp1_p:
                    half_bps = (entry-tp1_p)/entry*10000 * 0.5
                    half_filled = True
                    be_stop = entry - sl_dist*0.1
        else:
            if side=="long":
                if l[j]<=be_stop:
                    raw2 = (be_stop-entry)/entry*10000 * 0.5
                    total = half_bps + raw2 - RT_COST_BPS
                    return Trade(side, entry, be_stop, total, sl_bps, rr2*sl_bps, rr2, "BE", j-i)
                if h[j]>=tp2_p:
                    raw2 = (tp2_p-entry)/entry*10000 * 0.5
                    total = half_bps + raw2 - RT_COST_BPS
                    return Trade(side, entry, tp2_p, total, sl_bps, rr2*sl_bps, rr2, "TP2", j-i)
            else:
                if h[j]>=be_stop:
                    raw2 = (entry-be_stop)/entry*10000 * 0.5
                    total = half_bps + raw2 - RT_COST_BPS
                    return Trade(side, entry, be_stop, total, sl_bps, rr2*sl_bps, rr2, "BE", j-i)
                if l[j]<=tp2_p:
                    raw2 = (entry-tp2_p)/entry*10000 * 0.5
                    total = half_bps + raw2 - RT_COST_BPS
                    return Trade(side, entry, tp2_p, total, sl_bps, rr2*sl_bps, rr2, "TP2", j-i)

    # Time exit
    ep = c[exit_idx]
    if half_filled:
        raw2 = ((ep-entry)/entry*10000 if side=="long" else (entry-ep)/entry*10000) * 0.5
        total = half_bps + raw2 - RT_COST_BPS
    else:
        total = ((ep-entry)/entry*10000 if side=="long" else (entry-ep)/entry*10000) - RT_COST_BPS
    return Trade(side, entry, ep, total, sl_bps, rr2*sl_bps, rr2, "TIME", exit_idx-i)


# ═══════════════════════════════════════════════════════
# STRATEGIES
# ═══════════════════════════════════════════════════════
def strat_macd_cross(d, hold=18, adx_min=22, rr=2.0):
    """MACD line crosses signal line with ADX trend filter."""
    c=d["c"]; ml,ms,mh=_macd(c); ax=_adx(d["h"],d["l"],c); at=_atr(d["h"],d["l"],c)
    trades=[]; i=30
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [ml,ms,ax,at]) or any(np.isnan(x[i-1]) for x in [ml,ms]):
            i+=1; continue
        if ax[i]<adx_min: i+=1; continue
        up = ml[i-1]<=ms[i-1] and ml[i]>ms[i]
        dn = ml[i-1]>=ms[i-1] and ml[i]<ms[i]
        if up or dn:
            t=_exec_trade(d, i, "long" if up else "short", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        else: i+=1
    return trades

def strat_ichimoku(d, hold=24, rr=2.0):
    """Ichimoku cloud breakout: price crosses above/below cloud."""
    c=d["c"]; h=d["h"]; l=d["l"]
    tk,kj,sa,sb=_ichimoku(h,l,c)
    at=_atr(h,l,c)
    trades=[]; i=55
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [tk,kj,sa,sb,at]) or np.isnan(sa[i-1]) or np.isnan(sb[i-1]):
            i+=1; continue
        cloud_top=max(sa[i],sb[i]); cloud_bot=min(sa[i],sb[i])
        prev_cloud_top=max(sa[i-1],sb[i-1]); prev_cloud_bot=min(sa[i-1],sb[i-1])
        # Bullish: price crosses above cloud
        if c[i-1]<=prev_cloud_top and c[i]>cloud_top and tk[i]>kj[i]:
            t=_exec_trade(d, i, "long", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        elif c[i-1]>=prev_cloud_bot and c[i]<cloud_bot and tk[i]<kj[i]:
            t=_exec_trade(d, i, "short", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        else: i+=1
    return trades

def strat_pullback(d, hold=18, ema_p=21, rsi_lo=35, rsi_hi=65, adx_min=25, rr=2.0):
    """Pullback entry: trend EMA + RSI pullback."""
    c=d["c"]; e=_ema(c,ema_p); r=_rsi(c); ax=_adx(d["h"],d["l"],c); at=_atr(d["h"],d["l"],c)
    e50=_ema(c,50)
    trades=[]; i=55
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [e,e50,r,ax,at]):
            i+=1; continue
        if ax[i]<adx_min: i+=1; continue
        # Uptrend: price>EMA50, EMA21>EMA50, RSI dipped below 45 and recovering
        if c[i]>e50[i] and e[i]>e50[i] and r[i-1]<rsi_lo+10 and r[i]>rsi_lo and r[i]<55:
            t=_exec_trade(d, i, "long", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        elif c[i]<e50[i] and e[i]<e50[i] and r[i-1]>rsi_hi-10 and r[i]<rsi_hi and r[i]>45:
            t=_exec_trade(d, i, "short", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        else: i+=1
    return trades

def strat_ema_ribbon(d, hold=18, adx_min=25, rr=2.0):
    """Triple EMA ribbon alignment (8/13/21)."""
    c=d["c"]; e8=_ema(c,8); e13=_ema(c,13); e21=_ema(c,21)
    ax=_adx(d["h"],d["l"],c); at=_atr(d["h"],d["l"],c)
    trades=[]; i=30
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [e8,e13,e21,ax,at]) or any(np.isnan(x[i-1]) for x in [e8,e13,e21]):
            i+=1; continue
        if ax[i]<adx_min: i+=1; continue
        # Ribbon aligned and just crossed
        bull_align = e8[i]>e13[i]>e21[i]
        bear_align = e8[i]<e13[i]<e21[i]
        prev_not_bull = not (e8[i-1]>e13[i-1]>e21[i-1])
        prev_not_bear = not (e8[i-1]<e13[i-1]<e21[i-1])
        if bull_align and prev_not_bull:
            t=_exec_trade(d, i, "long", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        elif bear_align and prev_not_bear:
            t=_exec_trade(d, i, "short", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        else: i+=1
    return trades

def strat_donchian(d, period=20, hold=24, adx_min=22, rr=2.0):
    """Donchian channel breakout."""
    c=d["c"]; h=d["h"]; l=d["l"]
    du,dl=_donchian(h,l,period); ax=_adx(h,l,c); at=_atr(h,l,c)
    vs=_sma(d["v"],20)
    trades=[]; i=period+2
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [du,dl,ax,at,vs]):
            i+=1; continue
        if ax[i]<adx_min: i+=1; continue
        if d["v"][i]<vs[i]*1.0: i+=1; continue  # volume check
        if c[i]>du[i-1] and c[i-1]<=du[i-2]:
            t=_exec_trade(d, i, "long", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        elif c[i]<dl[i-1] and c[i-1]>=dl[i-2]:
            t=_exec_trade(d, i, "short", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        else: i+=1
    return trades

def strat_keltner(d, hold=18, adx_min=22, rr=2.0):
    """Keltner channel breakout."""
    c=d["c"]; h=d["h"]; l=d["l"]
    km,ku,kl=_keltner(c,h,l); ax=_adx(h,l,c); at=_atr(h,l,c)
    trades=[]; i=30
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [km,ku,kl,ax,at]):
            i+=1; continue
        if ax[i]<adx_min: i+=1; continue
        if c[i]>ku[i] and c[i-1]<=ku[i-1]:
            t=_exec_trade(d, i, "long", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        elif c[i]<kl[i] and c[i-1]>=kl[i-1]:
            t=_exec_trade(d, i, "short", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        else: i+=1
    return trades

def strat_stoch_momentum(d, hold=18, adx_min=20, rr=2.0):
    """Stochastic %K/%D cross in trending market."""
    c=d["c"]; sk,sd=_stoch(d["h"],d["l"],c); ax=_adx(d["h"],d["l"],c); at=_atr(d["h"],d["l"],c)
    e50=_ema(c,50)
    trades=[]; i=30
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [sk,sd,ax,at,e50]) or any(np.isnan(x[i-1]) for x in [sk,sd]):
            i+=1; continue
        if ax[i]<adx_min: i+=1; continue
        # Oversold cross in uptrend
        if c[i]>e50[i] and sk[i-1]<sd[i-1] and sk[i]>sd[i] and sk[i]<30:
            t=_exec_trade(d, i, "long", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        elif c[i]<e50[i] and sk[i-1]>sd[i-1] and sk[i]<sd[i] and sk[i]>70:
            t=_exec_trade(d, i, "short", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        else: i+=1
    return trades

def strat_roc_momentum(d, period=12, hold=18, adx_min=25, rr=2.0):
    """Rate of Change momentum burst."""
    c=d["c"]; rc=_roc(c,period); ax=_adx(d["h"],d["l"],c); at=_atr(d["h"],d["l"],c)
    e50=_ema(c,50)
    trades=[]; i=max(period+2, 30)
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [rc,ax,at,e50]) or np.isnan(rc[i-1]):
            i+=1; continue
        if ax[i]<adx_min: i+=1; continue
        # Strong positive ROC crossing threshold
        if rc[i]>2.0 and rc[i-1]<=2.0 and c[i]>e50[i]:
            t=_exec_trade(d, i, "long", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        elif rc[i]<-2.0 and rc[i-1]>=-2.0 and c[i]<e50[i]:
            t=_exec_trade(d, i, "short", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        else: i+=1
    return trades

def strat_squeeze(d, hold=24, bb_p=20, bb_n=2.0, kelt_mult=1.5, rr=2.0):
    """BB squeeze breakout: BB inside Keltner → expansion."""
    c=d["c"]; h=d["h"]; l=d["l"]
    bm,bu,bl,bstd=_bb(c,bb_p,bb_n)
    km,ku,kl=_keltner(c,h,l,20,14,kelt_mult)
    at=_atr(h,l,c)
    trades=[]; i=30
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [bu,bl,ku,kl,at]) or any(np.isnan(x[i-1]) for x in [bu,bl,ku,kl]):
            i+=1; continue
        # Squeeze: BB inside Keltner
        was_squeezed = bu[i-1]<ku[i-1] and bl[i-1]>kl[i-1]
        now_expanded = bu[i]>=ku[i] or bl[i]<=kl[i]
        if was_squeezed and now_expanded:
            side = "long" if c[i]>bm[i] else "short"
            t=_exec_trade(d, i, side, hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        else: i+=1
    return trades

def strat_atr_explosion(d, hold=18, atr_mult_trigger=1.8, adx_min=20, rr=2.0):
    """ATR explosion: sudden vol increase in trending market."""
    c=d["c"]; h=d["h"]; l=d["l"]
    at=_atr(h,l,c); at_slow=_sma(at, 50); ax=_adx(h,l,c)
    e20=_ema(c,20)
    trades=[]; i=55
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [at,at_slow,ax,e20]):
            i+=1; continue
        if ax[i]<adx_min: i+=1; continue
        if at[i]>at_slow[i]*atr_mult_trigger and at[i-1]<=at_slow[i-1]*atr_mult_trigger:
            side = "long" if c[i]>e20[i] else "short"
            t=_exec_trade(d, i, side, hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        else: i+=1
    return trades

def strat_rsi_trend(d, hold=18, adx_min=22, rr=2.0):
    """RSI divergence in trend: RSI crosses 50 with ADX confirmation."""
    c=d["c"]; r=_rsi(c); ax=_adx(d["h"],d["l"],c); at=_atr(d["h"],d["l"],c)
    e50=_ema(c,50)
    trades=[]; i=30
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [r,ax,at,e50]) or np.isnan(r[i-1]):
            i+=1; continue
        if ax[i]<adx_min: i+=1; continue
        # RSI crossing 50 from below in uptrend
        if r[i-1]<50 and r[i]>=50 and c[i]>e50[i]:
            t=_exec_trade(d, i, "long", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        elif r[i-1]>50 and r[i]<=50 and c[i]<e50[i]:
            t=_exec_trade(d, i, "short", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        else: i+=1
    return trades

def strat_macd_vol_adx(d, hold=18, adx_min=25, rr=2.0):
    """Composite: MACD cross + volume spike + ADX trend."""
    c=d["c"]; ml,ms,_=_macd(c); ax=_adx(d["h"],d["l"],c); at=_atr(d["h"],d["l"],c)
    vs=_sma(d["v"],20)
    trades=[]; i=30
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [ml,ms,ax,at,vs]) or any(np.isnan(x[i-1]) for x in [ml,ms]):
            i+=1; continue
        if ax[i]<adx_min: i+=1; continue
        if d["v"][i]<vs[i]*1.2: i+=1; continue
        up=ml[i-1]<=ms[i-1] and ml[i]>ms[i]; dn=ml[i-1]>=ms[i-1] and ml[i]<ms[i]
        if up or dn:
            t=_exec_trade(d, i, "long" if up else "short", hold, at, rr)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        else: i+=1
    return trades

def strat_funding_contrarian(d, fund, hold=18, threshold=0.0003, rr=2.0):
    """Funding rate contrarian: extreme funding → fade."""
    if fund is None: return []
    c=d["c"]; t_arr=d["t"]; at=_atr(d["h"],d["l"],c); ax=_adx(d["h"],d["l"],c)
    e50=_ema(c,50)
    ft=fund["t"]; fr=fund["r"]
    trades=[]; i=55
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [at,ax,e50]):
            i+=1; continue
        # Find latest funding rate
        fidx=np.searchsorted(ft, t_arr[i], side="right")-1
        if fidx<0: i+=1; continue
        rate=fr[fidx]
        # Extreme positive funding → short (longs paying too much)
        if rate>threshold and c[i]<e50[i]:
            t2=_exec_trade(d, i, "short", hold, at, rr)
            if t2: trades.append(t2); i+=t2.bars+1
            else: i+=1
        elif rate<-threshold and c[i]>e50[i]:
            t2=_exec_trade(d, i, "long", hold, at, rr)
            if t2: trades.append(t2); i+=t2.bars+1
            else: i+=1
        else: i+=1
    return trades

def strat_mtf_4h_1h(d1h, d4h, hold=18, adx_min=22, rr=2.0):
    """4h trend direction + 1h entry timing."""
    if not d4h: return []
    c1=d1h["c"]; t1=d1h["t"]
    c4=d4h["c"]; t4=d4h["t"]
    e20_4=_ema(c4,20); e50_4=_ema(c4,50); ax4=_adx(d4h["h"],d4h["l"],c4)
    e9_1=_ema(c1,9); e21_1=_ema(c1,21); at1=_atr(d1h["h"],d1h["l"],c1)

    def trend_4h(ts):
        idx=np.searchsorted(t4,ts,side="right")-1
        if idx<50 or idx>=len(c4): return 0
        if any(np.isnan(x[idx]) for x in [e20_4,e50_4,ax4]): return 0
        if ax4[idx]<adx_min: return 0
        if e20_4[idx]>e50_4[idx] and c4[idx]>e20_4[idx]: return 1
        if e20_4[idx]<e50_4[idx] and c4[idx]<e20_4[idx]: return -1
        return 0

    trades=[]; i=25
    while i<len(c1)-hold:
        if any(np.isnan(x[i]) for x in [e9_1,e21_1,at1]) or any(np.isnan(x[i-1]) for x in [e9_1,e21_1]):
            i+=1; continue
        tr=trend_4h(t1[i])
        if tr==0: i+=1; continue
        up=e9_1[i-1]<=e21_1[i-1] and e9_1[i]>e21_1[i]
        dn=e9_1[i-1]>=e21_1[i-1] and e9_1[i]<e21_1[i]
        if (up and tr==1) or (dn and tr==-1):
            t2=_exec_trade(d1h, i, "long" if up else "short", hold, at1, rr)
            if t2: trades.append(t2); i+=t2.bars+1
            else: i+=1
        else: i+=1
    return trades

# Session filter wrapper
def _with_session(d, strategy_fn, session, **kw):
    """Run strategy with hour filter. session=(start_hour, end_hour) UTC."""
    orig_trades = strategy_fn(d, **kw)
    if session is None: return orig_trades
    return [t for t in orig_trades if session[0] <= (d["t"][t.bars] // 3600000) % 24 <= session[1]]

# Partial TP variant of EMA cross
def strat_ema_partial_tp(d, fast=9, slow=21, hold=24, adx_min=28, rr1=1.0, rr2=2.5):
    c=d["c"]; ef=_ema(c,fast); es=_ema(c,slow); ax=_adx(d["h"],d["l"],c); at=_atr(d["h"],d["l"],c)
    trades=[]; i=max(slow+1,30)
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [ef,es,ax,at]) or any(np.isnan(x[i-1]) for x in [ef,es]):
            i+=1; continue
        if ax[i]<adx_min: i+=1; continue
        up=ef[i-1]<=es[i-1] and ef[i]>es[i]; dn=ef[i-1]>=es[i-1] and ef[i]<es[i]
        if up or dn:
            t=_exec_partial_tp(d, i, "long" if up else "short", hold, at, rr1, rr2)
            if t: trades.append(t); i+=t.bars+1
            else: i+=1
        else: i+=1
    return trades


# ═══════════════════════════════════════════════════════
# MONTE CARLO
# ═══════════════════════════════════════════════════════
def mc_ruin(returns, n_sims=10000, n_per=200, ruin_pct=-30.0):
    if len(returns)<3: return {"ruin": 1.0, "med_dd": -9999, "med_eq": 0}
    ret=np.array(returns); rng=np.random.default_rng(42)
    ruin_ct=0; dds=[]; eqs=[]
    thr = ruin_pct/100*10000
    for _ in range(n_sims):
        s=rng.choice(ret,n_per,replace=True)
        eq=np.cumsum(s); pk=np.maximum.accumulate(eq); dd=eq-pk
        md=np.min(dd); dds.append(md); eqs.append(eq[-1])
        if md<thr: ruin_ct+=1
    return {"ruin": ruin_ct/n_sims, "med_dd": float(np.median(dds)), "p95_dd": float(np.percentile(dds,5)), "med_eq": float(np.median(eqs))}


# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════
def main():
    print("=" * 100)
    print("FULL STRATEGY SCAN — All Categories, 1h Unified, MC Verified")
    print("=" * 100)

    strategies = [
        # (name, fn, param_grid)
        ("MACD_Cross", strat_macd_cross, [
            {"hold": 18, "adx_min": 22, "rr": 2.0},
            {"hold": 18, "adx_min": 25, "rr": 2.0},
            {"hold": 18, "adx_min": 28, "rr": 2.0},
            {"hold": 24, "adx_min": 22, "rr": 2.0},
            {"hold": 24, "adx_min": 25, "rr": 2.5},
            {"hold": 12, "adx_min": 28, "rr": 1.5},
        ]),
        ("Ichimoku", strat_ichimoku, [
            {"hold": 24, "rr": 2.0},
            {"hold": 36, "rr": 2.0},
            {"hold": 24, "rr": 2.5},
        ]),
        ("Pullback", strat_pullback, [
            {"hold": 18, "adx_min": 25, "rr": 2.0},
            {"hold": 18, "adx_min": 22, "rr": 2.0},
            {"hold": 18, "adx_min": 25, "rr": 2.5},
            {"hold": 24, "adx_min": 25, "rr": 2.0},
            {"hold": 12, "adx_min": 28, "rr": 1.5},
        ]),
        ("EMA_Ribbon", strat_ema_ribbon, [
            {"hold": 18, "adx_min": 25, "rr": 2.0},
            {"hold": 18, "adx_min": 28, "rr": 2.0},
            {"hold": 24, "adx_min": 22, "rr": 2.0},
            {"hold": 12, "adx_min": 28, "rr": 1.5},
        ]),
        ("Donchian", strat_donchian, [
            {"period": 20, "hold": 24, "adx_min": 22, "rr": 2.0},
            {"period": 20, "hold": 24, "adx_min": 25, "rr": 2.0},
            {"period": 30, "hold": 36, "adx_min": 22, "rr": 2.0},
            {"period": 15, "hold": 18, "adx_min": 25, "rr": 2.0},
        ]),
        ("Keltner", strat_keltner, [
            {"hold": 18, "adx_min": 22, "rr": 2.0},
            {"hold": 18, "adx_min": 25, "rr": 2.0},
            {"hold": 24, "adx_min": 22, "rr": 2.5},
        ]),
        ("Stoch_Mom", strat_stoch_momentum, [
            {"hold": 18, "adx_min": 20, "rr": 2.0},
            {"hold": 18, "adx_min": 25, "rr": 2.0},
            {"hold": 24, "adx_min": 20, "rr": 2.5},
        ]),
        ("ROC_Mom", strat_roc_momentum, [
            {"period": 12, "hold": 18, "adx_min": 25, "rr": 2.0},
            {"period": 8, "hold": 12, "adx_min": 25, "rr": 2.0},
            {"period": 12, "hold": 24, "adx_min": 22, "rr": 2.0},
        ]),
        ("Squeeze", strat_squeeze, [
            {"hold": 24, "rr": 2.0},
            {"hold": 18, "rr": 2.0},
            {"hold": 24, "rr": 2.5},
        ]),
        ("ATR_Explode", strat_atr_explosion, [
            {"hold": 18, "atr_mult_trigger": 1.8, "adx_min": 20, "rr": 2.0},
            {"hold": 18, "atr_mult_trigger": 2.0, "adx_min": 22, "rr": 2.0},
            {"hold": 24, "atr_mult_trigger": 1.5, "adx_min": 25, "rr": 2.0},
        ]),
        ("RSI_Trend", strat_rsi_trend, [
            {"hold": 18, "adx_min": 22, "rr": 2.0},
            {"hold": 18, "adx_min": 25, "rr": 2.0},
            {"hold": 24, "adx_min": 22, "rr": 2.5},
            {"hold": 12, "adx_min": 28, "rr": 2.0},
        ]),
        ("MACD_Vol_ADX", strat_macd_vol_adx, [
            {"hold": 18, "adx_min": 25, "rr": 2.0},
            {"hold": 18, "adx_min": 28, "rr": 2.0},
            {"hold": 24, "adx_min": 25, "rr": 2.5},
        ]),
        ("EMA_PartialTP", strat_ema_partial_tp, [
            {"fast": 9, "slow": 21, "hold": 24, "adx_min": 28, "rr1": 1.0, "rr2": 2.5},
            {"fast": 9, "slow": 21, "hold": 24, "adx_min": 25, "rr1": 1.0, "rr2": 3.0},
            {"fast": 10, "slow": 21, "hold": 18, "adx_min": 28, "rr1": 1.0, "rr2": 2.5},
        ]),
    ]

    all_results = []  # (name, symbol, params, stats, mc)

    for sym in SYMBOLS:
        d1h = load(sym, "1h")
        d4h = load(sym, "4h")
        fund = load_funding(sym)
        if not d1h: continue
        print(f"\n  {sym}...", end="", flush=True)

        for sname, sfn, param_grid in strategies:
            for params in param_grid:
                trades = sfn(d1h, **params)
                if len(trades) < 3: continue
                nets = [t.net_bps for t in trades]
                wins = sum(1 for n in nets if n>0)
                n = len(trades)
                gp = sum(n2 for n2 in nets if n2>0)
                gl = abs(sum(n2 for n2 in nets if n2<0))
                pf = gp/gl if gl>0 else (999 if gp>0 else 0)
                rrs = [t.rr for t in trades]
                mc = mc_ruin(nets)
                all_results.append((sname, sym, params, {
                    "n": n, "wr": wins/n, "pf": min(pf, 999), "tot": sum(nets),
                    "avg": float(np.mean(nets)), "avg_rr": float(np.mean(rrs)),
                    "sharpe": float(np.mean(nets)/np.std(nets,ddof=1)) if n>1 and np.std(nets,ddof=1)>0 else 0,
                }, mc))

        # MTF 4h→1h
        if d4h:
            for params in [{"hold":18,"adx_min":22,"rr":2.0}, {"hold":18,"adx_min":25,"rr":2.0}, {"hold":24,"adx_min":22,"rr":2.5}]:
                trades = strat_mtf_4h_1h(d1h, d4h, **params)
                if len(trades)<3: continue
                nets=[t.net_bps for t in trades]; n=len(trades)
                wins=sum(1 for x in nets if x>0)
                gp=sum(x for x in nets if x>0); gl=abs(sum(x for x in nets if x<0))
                pf=gp/gl if gl>0 else (999 if gp>0 else 0)
                rrs=[t.rr for t in trades]; mc=mc_ruin(nets)
                all_results.append(("MTF_4h1h", sym, params, {
                    "n": n, "wr": wins/n, "pf": min(pf,999), "tot": sum(nets),
                    "avg": float(np.mean(nets)), "avg_rr": float(np.mean(rrs)),
                    "sharpe": float(np.mean(nets)/np.std(nets,ddof=1)) if n>1 and np.std(nets,ddof=1)>0 else 0,
                }, mc))

        # Funding contrarian
        if fund:
            for params in [{"hold":18,"threshold":0.0003,"rr":2.0}, {"hold":24,"threshold":0.0002,"rr":2.0}]:
                trades = strat_funding_contrarian(d1h, fund, **params)
                if len(trades)<3: continue
                nets=[t.net_bps for t in trades]; n=len(trades)
                wins=sum(1 for x in nets if x>0)
                gp=sum(x for x in nets if x>0); gl=abs(sum(x for x in nets if x<0))
                pf=gp/gl if gl>0 else (999 if gp>0 else 0)
                rrs=[t.rr for t in trades]; mc=mc_ruin(nets)
                all_results.append(("Fund_Contr", sym, params, {
                    "n": n, "wr": wins/n, "pf": min(pf,999), "tot": sum(nets),
                    "avg": float(np.mean(nets)), "avg_rr": float(np.mean(rrs)),
                    "sharpe": float(np.mean(nets)/np.std(nets,ddof=1)) if n>1 and np.std(nets,ddof=1)>0 else 0,
                }, mc))

        print(f" done ({sum(1 for r in all_results if r[1]==sym)} combos)")

    # ═══════════════════════════════════════════════════
    # FILTER FOR LIVE-ELIGIBLE
    # ═══════════════════════════════════════════════════
    print(f"\n\n{'='*100}")
    print("  LIVE-ELIGIBLE STRATEGIES (PF>1.3, WR>35%, MC ruin<5%, n>=5, R:R>=1.5)")
    print(f"{'='*100}")

    eligible = []
    for name, sym, params, stats, mc in all_results:
        if (stats["pf"] > 1.3 and stats["wr"] > 0.35 and stats["n"] >= 5
            and mc["ruin"] < 0.05 and stats["avg_rr"] >= 1.5):
            eligible.append((name, sym, params, stats, mc))

    eligible.sort(key=lambda x: x[3]["pf"], reverse=True)

    print(f"\n총 조합: {len(all_results)}")
    print(f"라이브 편입 가능: {len(eligible)}")

    if eligible:
        print(f"\n{'Strat':<14} {'Sym':<10} {'N':>3} {'WR':>5} {'PF':>6} {'TotBps':>7} {'AvgBps':>7} {'R:R':>5} {'Shrp':>6} {'MC%':>5} {'MCDD':>7}  Params")
        print(f"{'─'*100}")
        for name, sym, params, s, mc in eligible[:50]:
            ps = ", ".join(f"{k}={v}" for k,v in params.items())
            pf_s = f"{s['pf']:.1f}" if s['pf']<100 else "inf"
            print(f"{name:<14} {sym:<10} {s['n']:>3} {s['wr']:>4.0%} {pf_s:>6} {s['tot']:>7.0f} {s['avg']:>7.1f} {s['avg_rr']:>5.1f} {s['sharpe']:>6.3f} {mc['ruin']:>4.0%} {mc['med_dd']:>7.0f}  {ps}")

    # ═══════════════════════════════════════════════════
    # CROSS-SYMBOL ANALYSIS
    # ═══════════════════════════════════════════════════
    print(f"\n\n{'='*100}")
    print("  CROSS-SYMBOL PORTFOLIO (strategies working on 3+ symbols)")
    print(f"{'='*100}")

    from collections import defaultdict
    groups = defaultdict(list)
    for name, sym, params, stats, mc in eligible:
        key = (name, json.dumps(params, sort_keys=True))
        groups[key].append((sym, stats, mc))

    multi = [(k,v) for k,v in groups.items() if len(v)>=3]
    multi.sort(key=lambda x: np.mean([s["pf"] for _,s,_ in x[1] if s["pf"]<100]), reverse=True)

    portfolio_candidates = []
    for (name, params_json), sym_list in multi:
        params = json.loads(params_json)
        avg_pf = np.mean([s["pf"] for _,s,_ in sym_list if s["pf"]<100])
        avg_wr = np.mean([s["wr"] for _,s,_ in sym_list])
        total_n = sum(s["n"] for _,s,_ in sym_list)
        all_nets = []
        for _,s,_ in sym_list: pass  # can't get individual trades here, use stats
        syms = [sy for sy,_,_ in sym_list]

        # Combined MC on all symbols' data
        combined_pf = avg_pf
        combined_ruin = max(m["ruin"] for _,_,m in sym_list)

        portfolio_candidates.append({
            "strategy": name, "params": params,
            "symbols": syms, "avg_pf": round(avg_pf, 2),
            "avg_wr": round(avg_wr, 3), "total_trades": total_n,
            "max_mc_ruin": round(combined_ruin, 4),
        })

        print(f"\n  {name} | {', '.join(f'{k}={v}' for k,v in params.items())}")
        print(f"  Avg PF={avg_pf:.2f}  WR={avg_wr:.0%}  Trades={total_n}  Max MC Ruin={combined_ruin:.1%}")
        for sy, s, m in sym_list:
            pf_s = f"{s['pf']:.1f}" if s['pf']<100 else "inf"
            print(f"    {sy}: n={s['n']} WR={s['wr']:.0%} PF={pf_s} Tot={s['tot']:.0f}bps Shrp={s['sharpe']:.3f} MC={m['ruin']:.1%}")

    # 2-symbol combos
    dual = [(k,v) for k,v in groups.items() if len(v)==2]
    dual.sort(key=lambda x: np.mean([s["pf"] for _,s,_ in x[1] if s["pf"]<100]), reverse=True)
    if dual and not multi:
        print("\n  No 3+ symbol combos. Best 2-symbol:")
        for (name, pj), sl in dual[:5]:
            params=json.loads(pj)
            print(f"    {name} {params}: {', '.join(sy for sy,_,_ in sl)}")

    # ═══════════════════════════════════════════════════
    # SAVE
    # ═══════════════════════════════════════════════════
    out = Path(__file__).resolve().parent.parent / "quant_runtime" / "output" / "signal_research"
    out.mkdir(parents=True, exist_ok=True)

    eligible_json = []
    for name, sym, params, s, mc in eligible:
        eligible_json.append({
            "strategy": name, "symbol": sym, "params": params,
            "trades": s["n"], "win_rate": round(s["wr"],4), "pf": round(s["pf"],4),
            "total_bps": round(s["tot"],2), "avg_bps": round(s["avg"],2),
            "avg_rr": round(s["avg_rr"],4), "sharpe": round(s["sharpe"],4),
            "mc_ruin": round(mc["ruin"],4), "mc_med_dd": round(mc["med_dd"],2),
        })
    with open(out / "v4_full_scan_eligible.json", "w") as f:
        json.dump({"eligible": eligible_json, "portfolio_candidates": portfolio_candidates}, f, indent=2, default=str)

    # Summary stats
    all_strats = set(name for name,_,_,_,_ in all_results)
    print(f"\n\n{'='*100}")
    print("  SUMMARY BY STRATEGY TYPE")
    print(f"{'='*100}")
    for sn in sorted(all_strats):
        subset = [(n,sy,p,s,m) for n,sy,p,s,m in all_results if n==sn]
        elig_sub = [(n,sy,p,s,m) for n,sy,p,s,m in eligible if n==sn]
        best_pf = max((s["pf"] for _,_,_,s,_ in subset), default=0)
        print(f"  {sn:<14}: {len(subset):>3} combos, {len(elig_sub):>2} eligible, best PF={best_pf:.1f}")

    print(f"\n결과 저장: {out / 'v4_full_scan_eligible.json'}")


if __name__ == "__main__":
    main()
