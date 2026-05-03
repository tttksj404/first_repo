#!/usr/bin/env python3
"""auto4h Paper Multibot: forward-test all 14 STRONG winners simultaneously.

각 (signal, symbol, mom_min, tp, sl) 튜플별로 독립 paper trade.
실시간 ccxt fetch_ohlcv (1h) + Bitget cost/funding 모델.
SL/TP는 실시간 high/low로 체크 (페이퍼만, 실주문 X).

상태 저장 → quant_runtime/paper_multibot_state.json
이벤트 로그 → quant_runtime/paper_multibot_log.jsonl

실행:
  python3 scripts/auto4h_paper_multibot.py

종료: Ctrl+C
"""
from __future__ import annotations
import json, os, sys, time, signal as signal_mod, atexit
from dataclasses import dataclass, asdict, field
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "quant_runtime" / "paper_multibot_state.json"
LOG_PATH = ROOT / "quant_runtime" / "paper_multibot_log.jsonl"

LEVERAGE = 10
MARGIN = 50.0  # default paper margin per strategy (Mode A simulation)
# Phase Z finding: Mode B (static 70/30 long/short by regime occupancy) ROI +6.39
# Set ALLOC_MODE=B at runtime via env var to scale margin into a single $50 pool.
# bear_frac/bull_frac are computed from BTC bear regime over last 90d at startup.
ALLOC_MODE = os.environ.get("ALLOC_MODE", "A").upper()  # A=paper$50each | B=70/30 split
ALLOC_TOTAL_CAPITAL = float(os.environ.get("ALLOC_TOTAL", "50.0"))  # only used for B
COST_RT = 0.0012
FUNDING_8H = 0.00012  # 메메즈 가정 0.012%/8h average
LIQ_ROE = -95.0
SIGNAL_OFF_MIN_ROE = 0.0
COOLDOWN_AFTER_EXIT_H = 12
COOLDOWN_AFTER_LOSS_H = 24
SLIPPAGE_BPS = 10  # paper test sees realistic slip

REGIME_ATR_MIN = 0.4
TIMEFRAME = "1h"
HISTORY_BARS = 300
POLL_SEC = 60
# Phase AA finding: 1h delay → -56% net, 2h → -87%, 3h → negative.
# Skip entry if last-closed-bar age exceeds this threshold (5 min)
LATENCY_MAX_MIN = 5

# Phase GG: per-strategy delay tier (from phaseAA_latency.json analysis).
# ROBUST     = entry up to 2h late still profitable (relax watchdog to 120 min)
# ACCEPTABLE = entry up to 1h late OK (default 5-min watchdog)
# FRAGILE    = strict <5 min — and add bonus alert log when bar_age > 2 min
DELAY_TIER = {
    # FRAGILE — flagship + bot-restart sensitive
    "eth_donchian": "FRAGILE",
    "dot_adx_S":    "FRAGILE",
    "link_adx_S":   "FRAGILE",
    # ROBUST — entry latency-tolerant
    "eth_heikin_S":  "ROBUST",
    "near_atrexp_S": "ROBUST",
    "sui_momobv_S":  "ROBUST",
    # default = ACCEPTABLE (handled by .get fallback)
}
def latency_cap_for(sid: str) -> int:
    """Return max bar-age minutes (above 60 min base) for entry."""
    t = DELAY_TIER.get(sid, "ACCEPTABLE")
    if t == "ROBUST":
        return 120  # 2h post-bar-close OK
    if t == "FRAGILE":
        return 5    # strict 5-min
    return 5        # ACCEPTABLE default same 5-min

# === 14 STRONG STRATEGIES (Stage 3 winners) ===
# tuple: (strat_id, signal_name, symbol, mom_min, tp_roe, sl_roe)
# Tuple format: (sid, signal, symbol, mom_min, tp, sl, regime)
# regime: "btc_default" | "btc_atr_only" | "btc_always_on" | "btc_ema_only"
#         "eth_default" | "eth_atr_only" | "eth_always_on"
# Phase L OOS-optimized regime per strategy.
STRATEGIES = [
    # === TIER 1 STRONG (Stage 3 + Phase C OOS verified) ===
    # safer majors first
    ("eth_donchian",   "donchian_20",   "ETH/USDT:USDT",  0.02,  50, -35, "btc_default"),
    ("eth_volexp_2",   "vol_expansion", "ETH/USDT:USDT",  0.02,  50, -25, "btc_default"),
    # alts — Phase L: SUI/DOGE2/ADA2 prefer eth_default (PF↑)
    ("sui_atrexp_4",   "atr_expansion", "SUI/USDT:USDT",  0.04, 150, -40, "eth_default"),
    ("sui_atrexp_2",   "atr_expansion", "SUI/USDT:USDT",  0.02,  80, -35, "eth_default"),
    # ARB: btc_ema_only (drop ATR filter, keep trend)
    ("arb_volexp",     "vol_expansion", "ARB/USDT:USDT",  0.04,  50, -20, "btc_ema_only"),
    # memes (jackpot) — Phase L massive uplifts on always_on
    ("doge_volexp_4",  "vol_expansion", "DOGE/USDT:USDT", 0.04,  80, -30, "btc_default"),
    ("doge_volexp_2",  "vol_expansion", "DOGE/USDT:USDT", 0.02,  80, -30, "eth_default"),
    ("doge_heikin",    "heikin_cont",   "DOGE/USDT:USDT", 0.06,  80, -35, "btc_always_on"),
    ("doge_momobv",    "momentum_obv",  "DOGE/USDT:USDT", 0.02,  80, -30, "btc_ema_only"),
    ("wif_momobv",     "momentum_obv",  "WIF/USDT:USDT",  0.02, 300, -25, "btc_default"),
    # WIF heikin: btc_ema_only OOS net $+50→$+95 PF=3.35
    ("wif_heikin",     "heikin_cont",   "WIF/USDT:USDT",  0.06, 100, -25, "btc_ema_only"),
    # === TIER 1.5 NEW STRONG (Phase I+K OOS+adj verified) ===
    # ADA heikin_cont mom4% — 3 TP variants all eth_atr_only (PF=∞ in OOS)
    ("ada_heikin_300", "heikin_cont",   "ADA/USDT:USDT",  0.04, 300, -50, "eth_atr_only"),
    ("ada_heikin_150", "heikin_cont",   "ADA/USDT:USDT",  0.04, 150, -35, "eth_atr_only"),
    ("ada_heikin_200", "heikin_cont",   "ADA/USDT:USDT",  0.04, 200, -40, "eth_atr_only"),
    ("ada_heikin_2",   "heikin_cont",   "ADA/USDT:USDT",  0.02, 300, -50, "eth_default"),
    # OP atr_expansion — adj=27/27 perfect, btc_always_on uplifts +$11
    ("op_atrexp",      "atr_expansion", "OP/USDT:USDT",   0.06, 300, -50, "btc_always_on"),
    # PEPE: btc_always_on +$124 OOS uplift!
    ("pepe_atrexp",    "atr_expansion", "PEPE/USDT:USDT", 0.08, 300, -50, "btc_always_on"),
]

# === SHORT STRATEGIES (Phase Q+R OOS verified) ===
# Tuple: (sid, signal, symbol, mom_max (negative!), tp, sl, regime)
# regime "btc_bear" = BTC EMA20<EMA50 + ATR rank≥0.4 (29.7% of bars)
# mom_max means: enter only if mom24 ≤ this value (e.g. -0.04 = enter when momentum is -4% or worse)
SHORT_STRATEGIES = [
    # Phase Q+R validated
    # NOTE: link_atrexp_S DROPPED per Phase Y debate Round 2 (GPT+Gemini both flagged
    # PF=194 with n=5 as artifact). link_adx_S kept (n=6, PF=2.02, more believable).
    ("eth_heikin_S",   "short_heikin_cont",   "ETH/USDT:USDT",  -0.04,  80, -30, "btc_bear"),
    ("near_atrexp_S",  "short_atr_expansion", "NEAR/USDT:USDT", -0.02, 200, -40, "btc_bear"),
    ("sui_momobv_S",   "short_momentum_obv",  "SUI/USDT:USDT",  -0.06, 200, -40, "btc_bear"),
    # Phase V validated (largest sample = ARB n=68, +new coin DOT)
    ("arb_rsi_S",      "short_rsi_breakdown",  "ARB/USDT:USDT",  -0.02, 200, -40, "btc_bear"),
    ("dot_adx_S",      "short_adx_trend_dn",   "DOT/USDT:USDT",  -0.02, 150, -35, "btc_bear"),
    ("link_adx_S",     "short_adx_trend_dn",   "LINK/USDT:USDT", -0.06, 200, -40, "btc_bear"),
]

UNIVERSE = sorted(
    set(s[2] for s in STRATEGIES) | set(s[2] for s in SHORT_STRATEGIES)
    | {"BTC/USDT:USDT", "ETH/USDT:USDT"}
)


# === INDICATORS ===
def ema(arr, period):
    arr = np.asarray(arr, dtype=float)
    out = np.empty_like(arr); out[0] = arr[0]
    alpha = 2.0 / (period + 1.0)
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i-1]
    return out


def true_range(high, low, close):
    high, low, close = np.asarray(high), np.asarray(low), np.asarray(close)
    prev_close = np.concatenate([[close[0]], close[:-1]])
    return np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))


def adx(high, low, close, period=14):
    high = np.asarray(high); low = np.asarray(low); close = np.asarray(close)
    tr = true_range(high, low, close)
    up = np.diff(high, prepend=high[0])
    dn = -np.diff(low, prepend=low[0])
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr_v = ema(tr, period)
    pdi = 100 * ema(pdm, period) / np.maximum(atr_v, 1e-9)
    ndi = 100 * ema(ndm, period) / np.maximum(atr_v, 1e-9)
    dx = 100 * np.abs(pdi - ndi) / np.maximum(pdi + ndi, 1e-9)
    return ema(dx, period)


def bollinger(close, period=20, stdev=2.0):
    close = np.asarray(close); n = len(close)
    upper = np.zeros(n); middle = np.zeros(n); lower = np.zeros(n); width = np.zeros(n)
    for i in range(n):
        s = max(0, i-period+1); seg = close[s:i+1]
        m = np.mean(seg); sd = np.std(seg)
        middle[i] = m; upper[i] = m + stdev*sd; lower[i] = m - stdev*sd
        width[i] = (upper[i] - lower[i]) / max(m, 1e-9)
    rank = np.zeros(n)
    for i in range(n):
        s = max(0, i-99); seg = width[s:i+1]
        rank[i] = (seg <= width[i]).sum() / len(seg)
    return upper, middle, lower, width, rank


def compute_features(klines):
    arr = np.array(klines, dtype=float)
    if len(arr) < 60: return None
    high = arr[:,2]; low = arr[:,3]; close = arr[:,4]; vol = arr[:,5]
    n = len(close)
    mom24 = np.zeros(n)
    for i in range(n):
        if i >= 24: mom24[i] = close[i] / close[i-24] - 1
    vol_ma = np.zeros(n)
    for i in range(n):
        s = max(0, i-19); vol_ma[i] = np.mean(vol[s:i+1])
    vol_r = vol / np.maximum(vol_ma, 1e-9)
    ema20 = ema(close, 20); ema50 = ema(close, 50)
    adx_v = adx(high, low, close, 14)
    bb_u, bb_m, bb_l, bb_w, bb_r = bollinger(close, 20, 2.0)
    obv = np.zeros(n); obv_slope = np.zeros(n)
    for i in range(1, n):
        d = vol_r[i] if close[i] > close[i-1] else (-vol_r[i] if close[i] < close[i-1] else 0)
        obv[i] = obv[i-1] + d
    for i in range(6, n):
        obv_slope[i] = obv[i] - obv[i-6]
    return {"high": high, "low": low, "close": close, "vol": vol,
            "mom24": mom24, "vol_r": vol_r, "ema20": ema20, "ema50": ema50,
            "adx": adx_v, "bb_upper": bb_u, "bb_lower": bb_l,
            "bb_width": bb_w, "bb_width_rank": bb_r,
            "obv": obv, "obv_slope": obv_slope, "ts": arr[:,0]}


# === SIGNALS (subset used by 14 STRONG) ===
def sig_vol_expansion(ind, i):
    if i < 30: return False
    return (ind["bb_width_rank"][i] >= 0.7 and ind["mom24"][i] > 0.03
            and ind["close"][i] > ind["bb_upper"][i] and ind["vol_r"][i] >= 1.5)

def sig_momentum_obv(ind, i):
    if i < 25: return False
    return (ind["mom24"][i] > 0.05 and ind["ema20"][i] > ind["ema50"][i]
            and ind["adx"][i] > 22 and ind["vol_r"][i] >= 1.3 and ind["obv_slope"][i] > 0)

def sig_donchian_20(ind, i):
    if i < 21: return False
    high20 = ind["high"][i-20:i]
    return (ind["close"][i] > np.max(high20) and ind["vol_r"][i] >= 1.5
            and ind["mom24"][i] > 0.02)

def sig_atr_expansion(ind, i):
    if i < 50: return False
    bb_w = ind["bb_width"]
    s = max(0, i-49); bb_w_ma = np.mean(bb_w[s:i+1])
    return (bb_w[i] > bb_w_ma * 1.2 and ind["close"][i] > ind["ema50"][i]
            and ind["close"][i] > ind["close"][i-1] and ind["vol_r"][i] >= 1.3)

def sig_heikin_cont(ind, i):
    if i < 3: return False
    bullish = all(ind["close"][k] > ind["close"][k-1] for k in range(i-2, i+1))
    return bullish and ind["close"][i] > ind["ema20"][i] and ind["vol_r"][i] > 1.4

SIGNAL_FNS = {
    "vol_expansion":  sig_vol_expansion,
    "momentum_obv":   sig_momentum_obv,
    "donchian_20":    sig_donchian_20,
    "atr_expansion":  sig_atr_expansion,
    "heikin_cont":    sig_heikin_cont,
}


# === SHORT SIGNALS (Phase Q+R validated) ===
def sig_short_atr_expansion(ind, i):
    if i < 50: return False
    bb_w = ind["bb_width"]
    s = max(0, i-49); bb_w_ma = np.mean(bb_w[s:i+1])
    return (bb_w[i] > bb_w_ma * 1.2 and ind["close"][i] < ind["ema50"][i]
            and ind["close"][i] < ind["close"][i-1] and ind["vol_r"][i] >= 1.3)


def sig_short_heikin_cont(ind, i):
    if i < 3: return False
    bearish = all(ind["close"][k] < ind["close"][k-1] for k in range(i-2, i+1))
    return bearish and ind["close"][i] < ind["ema20"][i] and ind["vol_r"][i] > 1.4


def sig_short_momentum_obv(ind, i):
    if i < 25: return False
    if "obv_slope" not in ind: return False  # paper bot may lack OBV; skip
    return (ind["mom24"][i] < -0.05 and ind["ema20"][i] < ind["ema50"][i]
            and ind["adx"][i] > 22 and ind["vol_r"][i] >= 1.3
            and ind["obv_slope"][i] < 0)


SIGNAL_FNS["short_atr_expansion"] = sig_short_atr_expansion
SIGNAL_FNS["short_heikin_cont"] = sig_short_heikin_cont
SIGNAL_FNS["short_momentum_obv"] = sig_short_momentum_obv


# === Phase V extra short signals (validated) ===
def sig_short_rsi_breakdown(ind, i):
    if i < 14: return False
    gains = 0; losses = 0
    for k in range(i-13, i+1):
        d = ind["close"][k] - ind["close"][k-1] if k > 0 else 0
        if d > 0: gains += d
        else: losses += -d
    rsi = 100 if losses == 0 else 100 - (100 / (1 + gains/losses))
    bb_mid = (ind["bb_upper"][i] + ind["bb_lower"][i]) / 2
    return rsi < 40 and ind["close"][i] < bb_mid and ind["adx"][i] > 25 and ind["vol_r"][i] > 1.2


def sig_short_adx_trend_dn(ind, i):
    if i < 50: return False
    return (ind["adx"][i] > 30 and ind["ema20"][i] < ind["ema50"][i]
            and ind["close"][i] < ind["ema20"][i] and ind["vol_r"][i] >= 1.2
            and ind["mom24"][i] < -0.03)


SIGNAL_FNS["short_rsi_breakdown"] = sig_short_rsi_breakdown
SIGNAL_FNS["short_adx_trend_dn"] = sig_short_adx_trend_dn


# === REGIME (per-strategy) ===
def regime_state(ind):
    """Return dict of regime mode → bool for this base coin."""
    n = len(ind["close"])
    if n < 200:
        return {"default": False, "atr_only": False,
                "always_on": True, "ema_only": False}
    high = ind["high"]; low = ind["low"]; close = ind["close"]
    tr = true_range(high, low, close)
    atr24 = np.zeros(n)
    for i in range(n):
        s = max(0, i-23); atr24[i] = np.mean(tr[s:i+1])
    i = n - 1
    s = max(0, i-199); seg = atr24[s:i+1]
    atr_rank = (seg <= atr24[i]).mean() if len(seg) else 0.5
    ema_up = ind["ema20"][i] > ind["ema50"][i]
    atr_ok = atr_rank >= REGIME_ATR_MIN
    return {
        "default": bool(ema_up and atr_ok),
        "atr_only": bool(atr_ok),
        "ema_only": bool(ema_up),
        "always_on": True,
        "bear": bool((not ema_up) and atr_ok),  # Phase Q bear mirror
    }


def regime_check(regime_name, btc_state, eth_state):
    """regime_name like 'btc_default' or 'eth_atr_only'."""
    if regime_name.startswith("btc_"):
        mode = regime_name[4:]; state = btc_state
    elif regime_name.startswith("eth_"):
        mode = regime_name[4:]; state = eth_state
    else:
        return True
    return state.get(mode, False)


# Backward compat
def btc_regime_now(ind):
    return regime_state(ind)["default"]


# === STATE ===
@dataclass
class StratState:
    sid: str
    signal: str
    symbol: str
    mom_min: float
    tp: float
    sl: float
    regime: str = "btc_default"
    n_trades: int = 0
    n_wins: int = 0
    n_losses: int = 0
    cum_pnl: float = 0.0
    last_exit_ts: int = 0
    last_loss_ts: int = 0
    open_position: Optional[dict] = None  # {entry_px, entry_ts}
    consec_losses: int = 0
    paused_until_ts: int = 0
    pause_reason: str = ""
    side: str = "long"  # "long" or "short" (Phase U)


# === KILL-SWITCH RULES (Phase S) ===
KS_CONSEC_LOSS_LIMIT = 5      # rule 1
KS_CONSEC_PAUSE_H = 168       # 7d
KS_PER_STRAT_DD_LIMIT = -50.0 # 1 margin equivalent — early warning
KS_PER_STRAT_DD_PAUSE_H = 336 # 14d
KS_PORTFOLIO_7D_DD = -150.0   # rule 3: 3 margin
KS_PORTFOLIO_HALT = -500.0    # rule 4: 10 margin


def kill_switch_check(st: StratState, now_ts: int, port_7d_pnl: float, port_total_pnl: float):
    """Return (allowed: bool, reason: str)."""
    if port_total_pnl < KS_PORTFOLIO_HALT:
        return False, "PORTFOLIO_HALT"
    if port_7d_pnl < KS_PORTFOLIO_7D_DD:
        return False, "PORTFOLIO_24H_PAUSE"
    if st.paused_until_ts > now_ts:
        return False, st.pause_reason
    if st.consec_losses >= KS_CONSEC_LOSS_LIMIT:
        st.paused_until_ts = now_ts + KS_CONSEC_PAUSE_H*3600
        st.pause_reason = f"CONSEC_LOSS_{st.consec_losses}"
        return False, st.pause_reason
    if st.cum_pnl < KS_PER_STRAT_DD_LIMIT:
        st.paused_until_ts = now_ts + KS_PER_STRAT_DD_PAUSE_H*3600
        st.pause_reason = f"DD_${st.cum_pnl:.0f}"
        return False, st.pause_reason
    return True, ""


def init_states():
    states = {}
    for (sid, sig, sym, mom, tp, sl, regime) in STRATEGIES:
        states[sid] = StratState(sid, sig, sym, mom, tp, sl, regime, side="long")
    for (sid, sig, sym, mom, tp, sl, regime) in SHORT_STRATEGIES:
        states[sid] = StratState(sid, sig, sym, mom, tp, sl, regime, side="short")
    return states


_BEAR_FRAC_CACHE = {"value": 0.297, "ts": 0}  # Phase OO: auto-update Mode B


def get_dynamic_bear_frac(btc_ind, now_ts: int) -> float:
    """Phase OO: rolling 90d bear_frac from BTC indicator. Cache 24h.
    Falls back to 0.297 (Phase Z baseline) if data insufficient.
    """
    if now_ts - _BEAR_FRAC_CACHE["ts"] < 24*3600:
        return _BEAR_FRAC_CACHE["value"]
    if btc_ind is None or len(btc_ind.get("close", [])) < 24*90:
        return _BEAR_FRAC_CACHE["value"]
    # Recompute: bear regime = ema20<ema50 + ATR rank ≥ 0.4
    import numpy as np
    n = len(btc_ind["close"])
    ema20 = btc_ind["ema20"]; ema50 = btc_ind["ema50"]
    bear = (ema20 < ema50)
    # ATR rank ≥ 0.4 (rolling 90d percentile of ATR)
    # Simple proxy: use last 24*90 bars
    win = 24*90
    s = max(0, n-win)
    bear_win = bear[s:n]
    if len(bear_win) == 0: return _BEAR_FRAC_CACHE["value"]
    bf = float(bear_win.mean())
    bf = max(0.10, min(0.50, bf))  # clamp 10%~50% safety bound
    _BEAR_FRAC_CACHE["value"] = bf
    _BEAR_FRAC_CACHE["ts"] = now_ts
    return bf


def resolve_margin(side: str, bear_frac: float = 0.297) -> float:
    """Phase Z Mode B: pool $50 across long/short by regime occupancy.
    Phase OO: bear_frac is now passed dynamically from rolling 90d.
    """
    if ALLOC_MODE == "B":
        n_long = len(STRATEGIES); n_short = len(SHORT_STRATEGIES)
        bull_frac = 1 - bear_frac
        if side == "long":
            return ALLOC_TOTAL_CAPITAL * bull_frac / max(1, n_long)
        else:
            return ALLOC_TOTAL_CAPITAL * bear_frac / max(1, n_short)
    return MARGIN  # Mode A default


def save_state(states):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump({sid: asdict(st) for sid, st in states.items()}, f, indent=2)


def compute_rolling_7d_pnl(now_ts: int) -> float:
    """Phase DD GPT-5.4 fix: real rolling 7-day portfolio PnL by scanning JSONL log.
    Returns sum of `pnl` from `exit` events with timestamp ≥ now_ts - 7d.
    Falls back to 0.0 if log unreadable.
    """
    if not LOG_PATH.exists():
        return 0.0
    cutoff = now_ts - 7 * 24 * 3600
    total = 0.0
    try:
        with open(LOG_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("event") != "exit":
                    continue
                # event_ts is written by log_event as Unix seconds in 'ts' field
                ev_ts = ev.get("ts", 0)
                if ev_ts < cutoff:
                    continue
                total += float(ev.get("pnl", 0.0))
    except Exception:
        return 0.0
    return total


# Phase RR: latency_warn aggregator. If too many warnings in last 1h,
# pause portfolio entries to avoid trading during exchange/API degradation.
LATENCY_WARN_1H_THRESHOLD = 30  # >30 latency_warn events / hour (POLL_SEC=60 → 50% of cycles)


def count_latency_warns_1h(now_ts: int) -> int:
    """Count latency_warn events in trailing 60 minutes."""
    if not LOG_PATH.exists():
        return 0
    cutoff = now_ts - 60 * 60
    n = 0
    try:
        with open(LOG_PATH) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try: ev = json.loads(line)
                except Exception: continue
                if ev.get("event") != "latency_warn": continue
                if ev.get("ts", 0) < cutoff: continue
                n += 1
    except Exception:
        return 0
    return n


def portfolio_latency_pause_active(now_ts: int) -> bool:
    """Returns True if portfolio entries should be paused due to latency."""
    return count_latency_warns_1h(now_ts) >= LATENCY_WARN_1H_THRESHOLD


def load_state():
    if not STATE_PATH.exists(): return init_states()
    with open(STATE_PATH) as f: data = json.load(f)
    states = {}
    all_specs = [(*s, "long") for s in STRATEGIES] + [(*s, "short") for s in SHORT_STRATEGIES]
    for sid, sig, sym, mom, tp, sl, regime, side in all_specs:
        if sid in data:
            d = data[sid]
            d.setdefault("regime", regime)
            d.setdefault("side", side)
            # always reapply current regime/side in case of upgrade
            d["regime"] = regime
            d["side"] = side
            try:
                states[sid] = StratState(**d)
            except TypeError:
                states[sid] = StratState(sid, sig, sym, mom, tp, sl, regime, side=side)
        else:
            states[sid] = StratState(sid, sig, sym, mom, tp, sl, regime, side=side)
    return states


def log_event(ev):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ev["ts"] = int(now.timestamp())  # Unix seconds — used by compute_rolling_7d_pnl
    ev["ts_iso"] = now.isoformat()
    with open(LOG_PATH, "a") as f: f.write(json.dumps(ev) + "\n")


# === MAIN LOOP ===
def main():
    import ccxt
    ex = ccxt.bitget({"options": {"defaultType": "swap"}, "enableRateLimit": True})
    print(f"[paper-multibot v4] {len(STRATEGIES)} long + {len(SHORT_STRATEGIES)} short "
          f"= {len(STRATEGIES)+len(SHORT_STRATEGIES)} strategies, universe={len(UNIVERSE)}")
    states = load_state()

    def cleanup(*args):
        save_state(states)
        log_event({"event": "shutdown", "states": {sid: asdict(st) for sid, st in states.items()}})
        print("\n[shutdown] state saved.")
        sys.exit(0)

    signal_mod.signal(signal_mod.SIGINT, cleanup)
    signal_mod.signal(signal_mod.SIGTERM, cleanup)
    atexit.register(save_state, states)

    log_event({"event": "startup", "n_strategies": len(STRATEGIES), "universe": UNIVERSE})

    while True:
        try:
            # 1. fetch klines for all symbols (Phase LL: measure per-fetch latency)
            ind_cache = {}
            fetch_latencies_ms = []
            loop_start = time.time()
            for sym in UNIVERSE:
                try:
                    t0 = time.time()
                    kl = ex.fetch_ohlcv(sym, timeframe=TIMEFRAME, limit=HISTORY_BARS)
                    fetch_latencies_ms.append((sym, int((time.time()-t0)*1000)))
                    ind_cache[sym] = compute_features(kl)
                except Exception as e:
                    log_event({"event": "fetch_err", "sym": sym, "err": str(e)})
            # Phase LL: log latency stats every loop (max + p95 vs degradation threshold)
            if fetch_latencies_ms:
                lats = [l[1] for l in fetch_latencies_ms]
                lats_sorted = sorted(lats)
                p50 = lats_sorted[len(lats_sorted)//2]
                p95 = lats_sorted[int(len(lats_sorted)*0.95)] if len(lats_sorted) >= 5 else max(lats_sorted)
                max_l = max(lats); slow_sym = max(fetch_latencies_ms, key=lambda x: x[1])[0]
                # Phase AA degradation threshold: 1h delay → -56% net.
                # Per fetch, 1h would mean network/exchange truly down.
                # Warn if any single fetch > 5000ms (5s)
                if max_l > 5000:
                    log_event({"event": "latency_warn", "max_ms": max_l, "slow_sym": slow_sym,
                               "p50_ms": p50, "p95_ms": p95})

            btc_ind = ind_cache.get("BTC/USDT:USDT")
            eth_ind = ind_cache.get("ETH/USDT:USDT")
            if btc_ind is None or eth_ind is None:
                time.sleep(POLL_SEC); continue
            btc_state = regime_state(btc_ind)
            eth_state = regime_state(eth_ind)
            btc_on = btc_state["default"]  # legacy display
            now_ts = int(time.time())
            # Phase OO: dynamic bear_frac for Mode B sizing (rolling 90d, cache 24h)
            cur_bear_frac = get_dynamic_bear_frac(btc_ind, now_ts)

            # 2. for each strategy, check entry / exit
            for sid, st in states.items():
                sig_fn = SIGNAL_FNS[st.signal]
                ind = ind_cache.get(st.symbol)
                if ind is None: continue
                i = len(ind["close"]) - 1  # latest closed bar
                cur_px = ind["close"][i]; cur_hi = ind["high"][i]; cur_lo = ind["low"][i]

                if st.open_position is not None:
                    p = st.open_position
                    entry_px = p["entry_px"]; entry_ts = p["entry_ts"]
                    slip = SLIPPAGE_BPS / 10000.0
                    if st.side == "long":
                        roe_lo = (cur_lo / entry_px - 1) * LEVERAGE * 100
                        roe_hi = (cur_hi / entry_px - 1) * LEVERAGE * 100
                        roe_cl = (cur_px / entry_px - 1) * LEVERAGE * 100
                    else:  # short: profit when price falls
                        roe_lo = (entry_px / cur_lo - 1) * LEVERAGE * 100  # max profit
                        roe_hi = (entry_px / cur_hi - 1) * LEVERAGE * 100  # min/loss
                        roe_cl = (entry_px / cur_px - 1) * LEVERAGE * 100
                    exit_roe = None; reason = None
                    if st.side == "long":
                        if roe_lo <= LIQ_ROE:
                            exit_roe = -100.0; reason = "LIQ"
                        elif roe_lo <= st.sl:
                            sl_px = entry_px * (1 + st.sl/100/LEVERAGE)
                            exit_roe = (sl_px*(1-slip)/entry_px - 1)*LEVERAGE*100
                            reason = "SL"
                        elif roe_hi >= st.tp:
                            tp_px = entry_px * (1 + st.tp/100/LEVERAGE)
                            exit_roe = (tp_px*(1-slip)/entry_px - 1)*LEVERAGE*100
                            reason = "TP"
                        else:
                            if (not sig_fn(ind, i)) and roe_cl > SIGNAL_OFF_MIN_ROE:
                                exit_roe = (cur_px*(1-slip)/entry_px - 1)*LEVERAGE*100
                                reason = "SIG_OFF"
                    else:  # SHORT
                        if roe_hi <= LIQ_ROE:
                            exit_roe = -100.0; reason = "LIQ"
                        elif roe_hi <= st.sl:  # price spiked up = loss
                            sl_px = entry_px * (1 - st.sl/100/LEVERAGE)
                            exit_roe = (entry_px/(sl_px*(1+slip)) - 1)*LEVERAGE*100
                            reason = "SL"
                        elif roe_lo >= st.tp:  # price fell = profit
                            tp_px = entry_px * (1 - st.tp/100/LEVERAGE)
                            exit_roe = (entry_px/(tp_px*(1+slip)) - 1)*LEVERAGE*100
                            reason = "TP"
                        else:
                            if (not sig_fn(ind, i)) and roe_cl > SIGNAL_OFF_MIN_ROE:
                                exit_roe = (entry_px/(cur_px*(1+slip)) - 1)*LEVERAGE*100
                                reason = "SIG_OFF"
                    if exit_roe is not None:
                        hold_h = max(1, (now_ts - entry_ts) / 3600)
                        m = resolve_margin(st.side, cur_bear_frac)
                        notional = m * LEVERAGE
                        fee = notional * COST_RT
                        funding = notional * FUNDING_8H * (hold_h / 8)
                        pnl = -m-fee if exit_roe <= -100 else m*(exit_roe/100) - fee - funding
                        st.cum_pnl += pnl; st.n_trades += 1
                        if pnl > 0:
                            st.n_wins += 1; st.consec_losses = 0
                        else:
                            st.n_losses += 1; st.last_loss_ts = now_ts; st.consec_losses += 1
                        st.last_exit_ts = now_ts
                        st.open_position = None
                        log_event({"event": "exit", "sid": sid, "sym": st.symbol,
                                   "reason": reason, "roe": exit_roe, "pnl": pnl,
                                   "hold_h": hold_h, "cum_pnl": st.cum_pnl,
                                   "consec_losses": st.consec_losses})
                else:
                    # entry candidates — kill-switch + per-strategy regime check
                    port_total_pnl = sum(s.cum_pnl for s in states.values())
                    # Phase DD GPT-5.4 fix: real rolling 7d portfolio PnL from JSONL log
                    port_7d_pnl = compute_rolling_7d_pnl(now_ts)
                    # Phase RR: portfolio-wide latency pause (skip if API degraded)
                    if portfolio_latency_pause_active(now_ts):
                        if st.pause_reason != "latency_storm":
                            log_event({"event": "portfolio_pause_latency", "sid": sid,
                                       "warns_1h": count_latency_warns_1h(now_ts)})
                        continue
                    allowed, ks_reason = kill_switch_check(st, now_ts, port_7d_pnl, port_total_pnl)
                    if not allowed:
                        if ks_reason and st.pause_reason != ks_reason:
                            log_event({"event": "kill_switch", "sid": sid, "reason": ks_reason})
                        continue
                    # Phase AA latency guard — skip stale-bar entries (bot restart / network outage)
                    bar_age_min = (now_ts*1000 - int(ind["ts"][i])) / 60000.0
                    cap_min = latency_cap_for(sid)  # Phase GG: per-strategy tier
                    if bar_age_min > 60 + cap_min:
                        # 1h tf: bar timestamp is bar-start; "fresh" close = age in [60, 60+cap]
                        log_event({"event": "latency_skip", "sid": sid,
                                   "bar_age_min": round(bar_age_min, 1),
                                   "cap_min": cap_min,
                                   "tier": DELAY_TIER.get(sid, "ACCEPTABLE")})
                        continue
                    if not regime_check(st.regime, btc_state, eth_state): continue
                    if (now_ts - st.last_exit_ts) < COOLDOWN_AFTER_EXIT_H*3600: continue
                    if (now_ts - st.last_loss_ts) < COOLDOWN_AFTER_LOSS_H*3600: continue
                    if st.side == "long":
                        if ind["mom24"][i] < st.mom_min: continue
                    else:  # short: mom_min is actually mom_MAX (negative threshold)
                        if ind["mom24"][i] > st.mom_min: continue
                    if not sig_fn(ind, i): continue
                    # Phase VV: short cluster cap — corr 0.78 between near/sui/arb/dot/link.
                    # Allow max 4 simultaneous shorts (Worst day -$92 baseline; cap maintains tail).
                    if st.side == "short":
                        shorts_currently_open = sum(
                            1 for s2 in states.values()
                            if s2.side == "short" and s2.open_position is not None
                        )
                        if shorts_currently_open >= 4:
                            log_event({"event": "short_cluster_cap", "sid": sid,
                                       "open_shorts": shorts_currently_open})
                            continue
                    if st.side == "long":
                        entry_px = cur_px * (1 + SLIPPAGE_BPS/10000.0)  # buy = pay slippage up
                    else:
                        entry_px = cur_px * (1 - SLIPPAGE_BPS/10000.0)  # sell-short = get slippage down
                    st.open_position = {"entry_px": entry_px, "entry_ts": now_ts,
                                        "trigger_bar_ts": int(ind["ts"][i])}
                    log_event({"event": "entry", "sid": sid, "sym": st.symbol, "side": st.side,
                               "entry_px": entry_px, "tp": st.tp, "sl": st.sl})

            save_state(states)

            # status snapshot every loop
            opens = sum(1 for st in states.values() if st.open_position is not None)
            tot_pnl = sum(st.cum_pnl for st in states.values())
            tot_trades = sum(st.n_trades for st in states.values())
            n_total = len(STRATEGIES) + len(SHORT_STRATEGIES)
            shorts_open = sum(1 for st in states.values() if st.side=="short" and st.open_position)
            longs_open = opens - shorts_open
            print(f"[{datetime.now().strftime('%H:%M:%S')}] btc_on={btc_on} "
                  f"opens={opens}/{n_total} (L{longs_open}/S{shorts_open}) "
                  f"trades={tot_trades} cum_pnl=${tot_pnl:+.2f}", flush=True)

            time.sleep(POLL_SEC)
        except Exception as e:
            log_event({"event": "loop_err", "err": str(e)})
            time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
