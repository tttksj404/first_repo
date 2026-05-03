#!/usr/bin/env python3
"""Phase 23: 실시간 Paper Trading Bot (Bitget perp 1h).

Strategy (검증완료, Phase 22 winner):
  - Entry: vol_expansion (BB width rank ≥0.7 + mom24>3% + close>BB upper + vol_r≥1.5)
  - Exit:  L4_NoSL_TP500_signal (NO SL / TP=ROE+500% / 신호종료시 ROE>0이면 익절)
  - Lev = 10x, mp = 1.0 (margin = working_capital)
  - Capital: V0 (이익 100% safe pocket으로, 마진 항상 $50 고정)
  - Universe: PEPE / WIF / DOGE

Behavior:
  - Polls Bitget every 60s, updates 1h kline cache
  - On new closed 1h bar: re-evaluate signal
  - On entry signal: open virtual position at next bar's open
  - On exit condition: close virtual position
  - Apply V0: all positive PnL → safe pocket; working stays at $50
  - Save state every event to runtime/paper_bot_state.json
  - Log events to runtime/paper_bot_log.jsonl

Run:
    python3 scripts/quant_phase23_paper_bot.py
    # Stop with Ctrl+C — state persists.

Inspect state:
    cat quant_runtime/paper_bot_state.json | jq
"""
from __future__ import annotations

import json, os, sys, time, signal as signal_mod
from dataclasses import dataclass, asdict, field
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import numpy as np
from urllib import request as _urlreq, parse as _urlparse

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "quant_runtime" / "paper_bot_state.json"
LOG_PATH = ROOT / "quant_runtime" / "paper_bot_log.jsonl"

# ===== STRATEGY CONFIG =====
INITIAL_CAPITAL = 50.0   # USD
LEVERAGE = 10
MARGIN_FIXED = 50.0      # V0 fixed margin
COST_RT = 0.0012         # round-trip fee (taker × 2 on Bitget VIP0 perp)
FUNDING_DEFAULT_8H = 0.0001  # fallback if API fetch fails
LIQ_BUFFER_PCT = 95.0    # ROE <= -95% → liquidated (Bitget mmr ~0.5% for tier1)
LIQ_SLIP_PCT = 1.5       # extra slippage on liquidation (insurance fund + book impact)

# === Realism: slippage (per side, applied to entry & exit price) ===
# Bitget meme perp top-of-book: 5-10bps for $500 notional → use 8bps conservative
SLIPPAGE_BPS = 8

UNIVERSE = ["PEPE/USDT:USDT", "WIF/USDT:USDT", "DOGE/USDT:USDT"]
TIMEFRAME = "1h"
HISTORY_BARS = 500       # bars to keep for indicators

# Exit policy params (V_REG_SYM_SL30 — WF 3/4 robust, Phase27)
TP_ROE = 500.0           # +500% ROE = +50% price
SL_ROE = -30.0           # ✅ NEW: SL at -30% ROE (loss cap -$15) — Q2/Q3 chop 출혈 방지
SIGNAL_OFF_MIN_ROE = 0.0 # exit on signal off if ROE > this

# Cooldown
COOLDOWN_AFTER_EXIT_H = 12
COOLDOWN_AFTER_LOSS_H = 24

POLL_SEC = 60

# === Regime filter (Phase27) ===
REGIME_SYMBOL = "BTC/USDT:USDT"     # BTC trend → 메메즈 시즌 판정
REGIME_ATR_MIN = 0.4                # BTC 24h ATR 100bar percentile ≥ 0.4
SYMBOL_MOM_MIN = 0.05               # symbol mom24 > 5% 추가 필터

# === Realism: funding rate cache (refreshed every 8h per symbol) ===
FUNDING_CACHE: dict = {}  # symbol -> (rate_per_8h, fetched_at_ms)
FUNDING_REFRESH_MS = 8 * 3600 * 1000

# === Telegram alerts (optional, configure via env vars) ===
#   export PAPER_BOT_TG_TOKEN="123:abc"
#   export PAPER_BOT_TG_CHAT="987654321"
# 봇 토큰: @BotFather 에서 /newbot 으로 생성.
# Chat ID: 본인 봇에 메시지 한번 보낸 뒤 https://api.telegram.org/bot<TOKEN>/getUpdates 에서 확인.
TG_TOKEN = os.environ.get("PAPER_BOT_TG_TOKEN", "")
TG_CHAT = os.environ.get("PAPER_BOT_TG_CHAT", "")
TG_ENABLED = bool(TG_TOKEN and TG_CHAT)


# ===== INDICATOR COMPUTATION =====
def ema(arr, period):
    arr = np.asarray(arr, dtype=float)
    out = np.empty_like(arr)
    out[0] = arr[0]
    alpha = 2.0 / (period + 1.0)
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def true_range(high, low, close):
    high, low, close = np.asarray(high), np.asarray(low), np.asarray(close)
    prev_close = np.concatenate([[close[0]], close[:-1]])
    return np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))


def adx(high, low, close, period=14):
    high = np.asarray(high); low = np.asarray(low); close = np.asarray(close)
    n = len(close)
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
    close = np.asarray(close)
    n = len(close)
    upper = np.zeros(n); middle = np.zeros(n); lower = np.zeros(n); width = np.zeros(n)
    for i in range(n):
        s = max(0, i - period + 1)
        seg = close[s:i+1]
        m = np.mean(seg)
        sd = np.std(seg)
        middle[i] = m
        upper[i] = m + stdev * sd
        lower[i] = m - stdev * sd
        width[i] = (upper[i] - lower[i]) / max(m, 1e-9)
    # rank: percentile of width over last 100 bars
    rank = np.zeros(n)
    for i in range(n):
        s = max(0, i - 100 + 1)
        seg = width[s:i+1]
        rank[i] = (seg <= width[i]).sum() / len(seg)
    return upper, middle, lower, width, rank


def compute_features(klines):
    """klines: list of [ts, open, high, low, close, volume]."""
    arr = np.array(klines, dtype=float)
    if len(arr) < 30:
        return None
    high = arr[:, 2]; low = arr[:, 3]; close = arr[:, 4]; vol = arr[:, 5]
    n = len(close)
    # mom24
    mom24 = np.zeros(n)
    for i in range(n):
        if i >= 24:
            mom24[i] = close[i] / close[i-24] - 1
    # vol_r: vol / vol_ma20
    vol_ma = np.zeros(n)
    for i in range(n):
        s = max(0, i - 20 + 1)
        vol_ma[i] = np.mean(vol[s:i+1])
    vol_r = vol / np.maximum(vol_ma, 1e-9)
    # ema20, ema50
    ema20 = ema(close, 20)
    ema50 = ema(close, 50)
    # ADX
    adx_v = adx(high, low, close, 14)
    # Bollinger
    bb_u, bb_m, bb_l, bb_w, bb_r = bollinger(close, 20, 2.0)
    # OBV (vol_r-weighted)  [Phase16 robustness]
    obv = np.zeros(n); obv_slope = np.zeros(n)
    for i in range(1, n):
        d = 0
        if close[i] > close[i-1]: d = vol_r[i]
        elif close[i] < close[i-1]: d = -vol_r[i]
        obv[i] = obv[i-1] + d
    for i in range(6, n):
        obv_slope[i] = obv[i] - obv[i-6]
    return {
        "high": high, "low": low, "close": close, "vol": vol,
        "mom24": mom24, "vol_r": vol_r, "ema20": ema20, "ema50": ema50,
        "adx": adx_v, "bb_upper": bb_u, "bb_lower": bb_l,
        "bb_width": bb_w, "bb_width_rank": bb_r,
        "obv": obv, "obv_slope": obv_slope,
        "ts": arr[:, 0],
    }


# ===== ENSEMBLE SIGNALS (Phase 15/16/20 검증) =====
def vol_expansion_signal(ind, i):
    """Phase20 winner: volatility expansion + breakout. Most validated."""
    if i < 30: return False
    return (ind["bb_width_rank"][i] >= 0.7
            and ind["mom24"][i] > 0.03
            and ind["close"][i] > ind["bb_upper"][i]
            and ind["vol_r"][i] >= 1.5)


def momentum_obv_signal(ind, i):
    """Phase17 winner: 24h momentum + OBV up + ADX strong."""
    if i < 25: return False
    return (ind["mom24"][i] > 0.05
            and ind["ema20"][i] > ind["ema50"][i]
            and ind["adx"][i] > 22
            and ind["vol_r"][i] >= 1.3
            and ind["obv_slope"][i] > 0)


def squeeze_release_signal(ind, i):
    """Phase15: BB squeeze (last 5 bars width<30%) → break above upper band."""
    if i < 22: return False
    if i < 5: return False
    recent_squeeze = all(ind["bb_width_rank"][k] < 0.30 for k in range(i-5, i))
    if not recent_squeeze: return False
    return ind["close"][i] > ind["bb_upper"][i-1] and ind["vol_r"][i] > 1.3


# Ensemble: priority order (most validated first)
ENSEMBLE_SIGNALS = [
    ("vol_expansion", vol_expansion_signal),
    ("momentum_obv",  momentum_obv_signal),
    ("squeeze_release", squeeze_release_signal),
]


def any_signal_active(ind, i, signal_name):
    """Used for signal_off check: matches the entry signal."""
    for name, fn in ENSEMBLE_SIGNALS:
        if name == signal_name:
            return fn(ind, i)
    return False


# ===== STATE =====
@dataclass
class Position:
    symbol: str
    side: int  # 1 long
    entry_ts: int  # ms
    entry_price: float
    margin: float
    notional: float
    bars_held: int = 0


@dataclass
class BotState:
    working_capital: float = INITIAL_CAPITAL
    safe_pocket: float = 0.0
    total_invested: float = INITIAL_CAPITAL  # 처음 투입한 돈
    n_trades: int = 0
    n_wins: int = 0
    n_losses: int = 0
    n_liquidations: int = 0
    cum_pnl: float = 0.0
    last_exit_ts: int = 0  # ms
    last_loss_exit_ts: int = 0
    open_position: Optional[dict] = None
    started_at: str = ""
    last_check_at: str = ""
    last_event: str = ""

    def total_wealth(self):
        return self.working_capital + self.safe_pocket


def save_state(state: BotState):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(asdict(state), f, indent=2)


def load_state() -> BotState:
    if not STATE_PATH.exists():
        s = BotState()
        s.started_at = datetime.now(timezone.utc).isoformat()
        return s
    with open(STATE_PATH) as f:
        data = json.load(f)
    return BotState(**data)


def log_event(event: dict):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    event["ts_iso"] = datetime.now(timezone.utc).isoformat()
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(event) + "\n")


# ===== EXCHANGE =====
def init_exchange():
    import ccxt
    return ccxt.bitget({"options": {"defaultType": "swap"}, "enableRateLimit": True})


def fetch_klines(ex, symbol, limit=HISTORY_BARS):
    return ex.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=limit)


def btc_regime_active(ex):
    """Phase27 regime filter: BTC ema20>ema50 AND ATR rank ≥ 0.4.
    Returns True if memes 시즌 (long-bias OK), False if chop (skip entries)."""
    try:
        klines = fetch_klines(ex, REGIME_SYMBOL, 250)
        if not klines or len(klines) < 80:
            return False
        ind = compute_features(klines)
        if ind is None: return False
        i = len(ind["close"]) - 2  # closed bar
        # ATR(24) percentile over last 200 bars
        high = ind["high"]; low = ind["low"]; close = ind["close"]
        n = len(close)
        tr = np.zeros(n)
        for k in range(1, n):
            tr[k] = max(high[k]-low[k], abs(high[k]-close[k-1]), abs(low[k]-close[k-1]))
        s = max(0, i - 23)
        atr_now = float(np.mean(tr[s:i+1]))
        s2 = max(0, i - 199)
        # build atr series for rank
        atr_window = []
        for k in range(s2, i+1):
            sk = max(0, k - 23)
            atr_window.append(float(np.mean(tr[sk:k+1])))
        atr_rank = sum(1 for a in atr_window if a <= atr_now) / max(1, len(atr_window))
        ema_ok = ind["ema20"][i] > ind["ema50"][i]
        atr_ok = atr_rank >= REGIME_ATR_MIN
        return ema_ok and atr_ok
    except Exception as e:
        log_event({"event": "regime_error", "error": str(e)})
        return False


def fetch_ticker_price(ex, symbol):
    """Live mid/last price. Used for realistic entry fill (signal detected on bar
    close, real order fills ~60s later at current ticker)."""
    try:
        t = ex.fetch_ticker(symbol)
        # last is most recent trade; bid/ask if available is more accurate
        bid = t.get("bid"); ask = t.get("ask"); last = t.get("last")
        if bid and ask:
            return (bid + ask) / 2.0
        return float(last) if last else None
    except Exception as e:
        log_event({"event": "ticker_error", "symbol": symbol, "error": str(e)})
        return None


def fetch_mark_price(ex, symbol):
    """Bitget's MARK price — actual liquidation reference (not last/index).
    Mark price = index ± funding-adjusted, smooths spot manipulation.
    Falls back to ticker if mark unavailable."""
    try:
        t = ex.fetch_ticker(symbol)
        info = t.get("info", {})
        # Bitget swap returns markPrice in info
        mp = info.get("markPrice") or info.get("mark_price") or info.get("indexPrice")
        if mp is not None:
            return float(mp)
        # ccxt unified field
        if t.get("markPrice"):
            return float(t["markPrice"])
        return float(t.get("last") or 0) or None
    except Exception as e:
        log_event({"event": "mark_price_error", "symbol": symbol, "error": str(e)})
        return None


def fetch_funding_rate_cached(ex, symbol):
    """Real per-8h funding rate from Bitget. Cached for 8h to reduce API calls."""
    now_ms = int(time.time() * 1000)
    cached = FUNDING_CACHE.get(symbol)
    if cached and (now_ms - cached[1]) < FUNDING_REFRESH_MS:
        return cached[0]
    try:
        fr = ex.fetch_funding_rate(symbol)
        rate = float(fr.get("fundingRate") or FUNDING_DEFAULT_8H)
        FUNDING_CACHE[symbol] = (rate, now_ms)
        log_event({"event": "funding_fetched", "symbol": symbol, "rate_8h": rate})
        return rate
    except Exception as e:
        log_event({"event": "funding_fetch_error", "symbol": symbol, "error": str(e)})
        return FUNDING_DEFAULT_8H


def apply_slippage(price, side, is_entry):
    """Long entry slips up; long exit slips down. Vice versa for short."""
    slip = SLIPPAGE_BPS / 10000.0
    if side == 1:  # long
        return price * (1 + slip) if is_entry else price * (1 - slip)
    else:          # short
        return price * (1 - slip) if is_entry else price * (1 + slip)


def telegram_send(text):
    """Best-effort Telegram alert. Silent if not configured. Non-blocking on error."""
    if not TG_ENABLED:
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        data = _urlparse.urlencode({"chat_id": TG_CHAT, "text": text,
                                     "parse_mode": "HTML"}).encode()
        req = _urlreq.Request(url, data=data)
        _urlreq.urlopen(req, timeout=5)
    except Exception as e:
        # silent fail to not block trading
        log_event({"event": "telegram_error", "error": str(e)})


# ===== BOT LOOP =====
RUN = True
def handle_sigint(*_):
    global RUN
    RUN = False
    print("\n[stop] Got SIGINT, finishing current iteration and exiting.")


def evaluate_entry(ex, state: BotState):
    """Check all symbols; return first vol_expansion match or None."""
    if state.open_position is not None:
        return None
    now_ms = int(time.time() * 1000)
    cooldown_ms = COOLDOWN_AFTER_EXIT_H * 3600 * 1000
    loss_cooldown_ms = COOLDOWN_AFTER_LOSS_H * 3600 * 1000
    if state.last_exit_ts > 0 and (now_ms - state.last_exit_ts) < cooldown_ms:
        return None
    if state.last_loss_exit_ts > 0 and (now_ms - state.last_loss_exit_ts) < loss_cooldown_ms:
        return None

    # === Phase27 regime gate: BTC 추세 ON 이어야 봇 진입 ===
    if not btc_regime_active(ex):
        return None

    # ENSEMBLE: scan all (sym, signal) combos, take FIRST match (priority ordered)
    for sym in UNIVERSE:
        try:
            klines = fetch_klines(ex, sym, HISTORY_BARS)
            if not klines: continue
            ind = compute_features(klines)
            if ind is None: continue
            i = len(ind["close"]) - 2  # latest CLOSED bar
            # === Phase27 symbol mom filter ===
            if ind["mom24"][i] < SYMBOL_MOM_MIN: continue
            # Try each signal in priority order
            for sig_name, sig_fn in ENSEMBLE_SIGNALS:
                if not sig_fn(ind, i): continue
                # === Realistic fill: live ticker + slippage ===
                live_px = fetch_ticker_price(ex, sym)
                if live_px is None:
                    live_px = float(ind["close"][i])
                fill_px = apply_slippage(live_px, side=1, is_entry=True)
                return {
                    "symbol": sym,
                    "signal_name": sig_name,                   # which ensemble member fired
                    "entry_price": fill_px,
                    "entry_ts": int(time.time() * 1000),
                    "signal_bar_close": float(ind["close"][i]),
                    "signal_bar_ts": int(ind["ts"][i]),
                    "ind_snapshot": {
                        "signal": sig_name,
                        "mom24": float(ind["mom24"][i]),
                        "vol_r": float(ind["vol_r"][i]),
                        "bb_width_rank": float(ind["bb_width_rank"][i]),
                        "adx": float(ind["adx"][i]),
                        "obv_slope": float(ind["obv_slope"][i]),
                        "close": float(ind["close"][i]),
                        "bb_upper": float(ind["bb_upper"][i]),
                        "live_ticker": float(live_px),
                        "slip_applied_bps": SLIPPAGE_BPS,
                    },
                }
        except Exception as e:
            log_event({"event": "fetch_error", "symbol": sym, "error": str(e)})
    return None


def evaluate_exit(ex, state: BotState):
    """If position open, check TP/signal_off conditions on latest closed bar.

    All exit prices have slippage applied (long sell slips down).
    Liquidation includes LIQ_SLIP_PCT extra slip (insurance fund + book impact).
    bars_held is computed from real timestamps in close_position, not per-poll.
    """
    if state.open_position is None: return None
    pos = state.open_position
    try:
        klines = fetch_klines(ex, pos["symbol"], HISTORY_BARS)
        if not klines: return None
        ind = compute_features(klines)
        if ind is None: return None
        i = len(ind["close"]) - 2  # latest CLOSED bar
        hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
        ep = pos["entry_price"]
        roe_lo = (lo / ep - 1) * LEVERAGE * 100
        roe_hi = (hi / ep - 1) * LEVERAGE * 100
        roe_cl = (cl / ep - 1) * LEVERAGE * 100

        # === Mark price liquidation check (Bitget의 실제 청산 트리거) ===
        # Mark price는 last/spot보다 안정적이고 Bitget 청산 엔진의 reference price.
        # Intra-bar low가 -95% ROE 찍었는지를 mark price 기준으로도 검증.
        mark_px = fetch_mark_price(ex, pos["symbol"])
        if mark_px is not None:
            roe_mark = (mark_px / ep - 1) * LEVERAGE * 100
            # 만약 현재 mark가 이미 청산선 근처면 그것도 청산으로 간주
            if roe_mark <= -LIQ_BUFFER_PCT:
                roe_lo = min(roe_lo, roe_mark)  # 더 나쁜 쪽 채택

        # liquidation — real fill is worse than mark by LIQ_SLIP_PCT
        if roe_lo <= -LIQ_BUFFER_PCT:
            mark_liq_px = ep * (1 - LIQ_BUFFER_PCT / 100.0 / LEVERAGE)
            real_liq_px = mark_liq_px * (1 - LIQ_SLIP_PCT / 100.0)
            real_liq_roe = (real_liq_px / ep - 1) * LEVERAGE * 100
            return {"reason": "LIQUIDATED", "exit_price": real_liq_px,
                    "exit_roe": max(real_liq_roe, -100.0),  # cap at -100% (cant lose >margin)
                    "exit_ts": int(ind["ts"][i])}
        # === Phase27 SL=-30% (loss cap) ===
        if SL_ROE is not None and roe_lo <= SL_ROE:
            sl_px = ep * (1 + SL_ROE / 100.0 / LEVERAGE)
            fill_px = apply_slippage(sl_px, side=1, is_entry=False)
            fill_roe = (fill_px / ep - 1) * LEVERAGE * 100
            return {"reason": "SL", "exit_price": fill_px,
                    "exit_roe": fill_roe, "exit_ts": int(ind["ts"][i])}
        # TP at +500% ROE — assume limit order fills exactly at TP (no positive slip)
        # but apply small adverse slip to be conservative (2bps for limit fill on rally)
        if roe_hi >= TP_ROE:
            tp_px = ep * (1 + TP_ROE / 100.0 / LEVERAGE)
            fill_px = apply_slippage(tp_px, side=1, is_entry=False)
            fill_roe = (fill_px / ep - 1) * LEVERAGE * 100
            return {"reason": "TP", "exit_price": fill_px,
                    "exit_roe": fill_roe, "exit_ts": int(ind["ts"][i])}
        # Signal off + in profit — uses the SAME signal that triggered entry
        entry_sig = pos.get("signal_name", "vol_expansion")
        sig_now = any_signal_active(ind, i, entry_sig)
        if (not sig_now) and roe_cl > SIGNAL_OFF_MIN_ROE:
            fill_px = apply_slippage(cl, side=1, is_entry=False)
            fill_roe = (fill_px / ep - 1) * LEVERAGE * 100
            return {"reason": "SIGNAL_OFF_INPROFIT", "exit_price": fill_px,
                    "exit_roe": fill_roe, "exit_ts": int(ind["ts"][i])}
        # NOTE: bars_held NOT incremented per poll — computed in close_position from timestamps
    except Exception as e:
        log_event({"event": "exit_check_error", "error": str(e)})
    return None


def open_position(state: BotState, entry: dict):
    margin = MARGIN_FIXED  # V0 fixed margin
    if state.working_capital < margin:
        log_event({"event": "skip_entry_low_capital",
                   "working": state.working_capital, "needed": margin})
        return False
    notional = margin * LEVERAGE
    state.open_position = {
        "symbol": entry["symbol"], "side": 1,
        "signal_name": entry.get("signal_name", "vol_expansion"),
        "entry_price": entry["entry_price"],
        "entry_ts": entry["entry_ts"],
        "margin": margin, "notional": notional,
        "bars_held": 0,
        "ind_snapshot": entry["ind_snapshot"],
    }
    state.last_event = f"OPEN {entry['symbol']} ({entry.get('signal_name','?')}) @ ${entry['entry_price']:.6f}"
    log_event({"event": "OPEN", "position": state.open_position,
               "working_before": state.working_capital, "safe_before": state.safe_pocket})
    telegram_send(
        f"🟢 <b>OPEN</b> {entry['symbol'].split('/')[0]}\n"
        f"signal: {entry.get('signal_name','?')}\n"
        f"price: {entry['entry_price']:.6g}\n"
        f"margin: ${margin:.2f}  notional: ${notional:.2f}\n"
        f"working: ${state.working_capital:.2f}  safe: ${state.safe_pocket:.2f}"
    )
    save_state(state)
    return True


def close_position(state: BotState, exit_info: dict, ex=None):
    pos = state.open_position
    margin = pos["margin"]
    notional = pos["notional"]
    fee = notional * COST_RT
    # === Realistic hold time: from real timestamps, not per-poll counter ===
    hold_ms = max(0, exit_info["exit_ts"] - pos["entry_ts"])
    hold_h = hold_ms / (3600.0 * 1000.0)
    # === Real funding rate from Bitget API (cached 8h) ===
    if ex is not None:
        funding_rate_8h = fetch_funding_rate_cached(ex, pos["symbol"])
    else:
        funding_rate_8h = FUNDING_DEFAULT_8H
    # Funding paid every 8h boundary; over hold period this is ~ rate * (hold_h/8)
    funding = notional * funding_rate_8h * (hold_h / 8.0)
    roe = exit_info["exit_roe"]
    if roe <= -100:
        pnl = -margin - fee
    else:
        pnl = margin * (roe / 100.0) - fee - funding

    # V0+V5 hybrid capital management:
    #   profit → 100% to safe_pocket, working stays at $50
    #   loss   → from working_capital
    #   V5 refill → if working hits 0 AND safe ≥ INITIAL, refill working from safe
    refill_amount = 0.0
    if pnl > 0:
        state.safe_pocket += pnl
        state.working_capital = INITIAL_CAPITAL
    else:
        state.working_capital += pnl
        if state.working_capital < 0:
            deficit = -state.working_capital
            if state.safe_pocket >= deficit:
                state.safe_pocket -= deficit
                state.working_capital = 0
            else:
                state.working_capital = 0
        state.last_loss_exit_ts = exit_info["exit_ts"]
        if exit_info["reason"] == "LIQUIDATED":
            state.n_liquidations += 1
        state.n_losses += 1

        # === V5 REFILL: working=0 → 다음 trade 위해 safe에서 INITIAL만큼 복원 ===
        if state.working_capital == 0 and state.safe_pocket >= INITIAL_CAPITAL:
            refill_amount = INITIAL_CAPITAL
            state.safe_pocket -= refill_amount
            state.working_capital = refill_amount
            log_event({"event": "V5_REFILL", "amount": refill_amount,
                       "safe_after": state.safe_pocket,
                       "working_after": state.working_capital})

    if pnl > 0:
        state.n_wins += 1
    state.n_trades += 1
    state.cum_pnl += pnl
    state.last_exit_ts = exit_info["exit_ts"]
    state.last_event = f"CLOSE {pos['symbol']} {exit_info['reason']} ROE={roe:+.1f}% PnL=${pnl:+.2f}"

    log_event({"event": "CLOSE", "position": pos, "exit": exit_info,
               "pnl": pnl, "hold_h": round(hold_h, 2),
               "fee_paid": round(fee, 4),
               "funding_paid": round(funding, 4),
               "funding_rate_8h": round(funding_rate_8h, 6),
               "slip_bps_per_side": SLIPPAGE_BPS,
               "v5_refill": round(refill_amount, 2),
               "working_after": state.working_capital, "safe_after": state.safe_pocket,
               "total_after": state.total_wealth()})

    # Telegram alert
    emoji = {"TP": "💎", "LIQUIDATED": "💀", "SIGNAL_OFF_INPROFIT": "✅",
             "SL": "🛑"}.get(exit_info["reason"], "⚪")
    refill_line = f"\n♻ V5 refill: ${refill_amount:.2f}" if refill_amount > 0 else ""
    telegram_send(
        f"{emoji} <b>CLOSE</b> {pos['symbol'].split('/')[0]} ({pos.get('signal_name','?')})\n"
        f"reason: {exit_info['reason']}\n"
        f"ROE: {roe:+.1f}%   PnL: ${pnl:+.2f}\n"
        f"hold: {hold_h:.1f}h  fee: ${fee:.2f}  funding: ${funding:.3f}"
        f"{refill_line}\n"
        f"working: ${state.working_capital:.2f}   safe: ${state.safe_pocket:.2f}\n"
        f"trades: {state.n_trades} (W{state.n_wins}/L{state.n_losses}/Liq{state.n_liquidations})"
    )

    state.open_position = None
    save_state(state)


def print_status(state: BotState):
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] "
          f"working=${state.working_capital:.2f} safe=${state.safe_pocket:.2f} "
          f"total=${state.total_wealth():.2f} "
          f"trades={state.n_trades} W{state.n_wins}/L{state.n_losses}/Liq{state.n_liquidations}")
    if state.open_position:
        p = state.open_position
        print(f"  → OPEN: {p['symbol']} @ ${p['entry_price']:.6f} held {p['bars_held']}h")
    if state.last_event:
        print(f"  last: {state.last_event}")


def main():
    signal_mod.signal(signal_mod.SIGINT, handle_sigint)
    print(f"[start] Paper bot starting...")
    print(f"  Strategy: vol_expansion + L4 (NoSL/TP+500/signal_off)")
    print(f"  Leverage: {LEVERAGE}x  |  Margin (V0 fixed): ${MARGIN_FIXED}")
    print(f"  Universe: {UNIVERSE}")
    print(f"  Polling every {POLL_SEC}s")
    print(f"  State: {STATE_PATH}")
    print(f"  Log:   {LOG_PATH}")

    state = load_state()
    if not state.started_at:
        state.started_at = datetime.now(timezone.utc).isoformat()
    save_state(state)

    ex = init_exchange()
    print_status(state)

    while RUN:
        state.last_check_at = datetime.now(timezone.utc).isoformat()
        try:
            # 1) Check exit if position open
            if state.open_position is not None:
                exit_info = evaluate_exit(ex, state)
                if exit_info:
                    close_position(state, exit_info, ex)
                    print_status(state)
            # 2) Check entry if no position
            else:
                entry = evaluate_entry(ex, state)
                if entry:
                    open_position(state, entry)
                    print_status(state)
            save_state(state)
        except Exception as e:
            log_event({"event": "loop_error", "error": str(e)})
            print(f"[error] {e}")
        # sleep with interrupt check
        for _ in range(POLL_SEC):
            if not RUN: break
            time.sleep(1)

    save_state(state)
    print(f"\n[exit] Final state: working=${state.working_capital:.2f} "
          f"safe=${state.safe_pocket:.2f} total=${state.total_wealth():.2f}")


if __name__ == "__main__":
    main()
