#!/usr/bin/env python3
"""Phase 29: 실거래 봇 (Bitget perpetual, 1h V_REG_SYM_SL30 strategy).

Phase 23 paper bot과 동일한 신호/리짐/지표/엑싯 로직.
차이: 가상 PnL 업데이트 → 실주문 placement (CCXT bitget swap).

=== 안전장치 ===
1. DRY_RUN 디폴트 ON. `BITGET_LIVE=1` env 명시해야 실주문 발주.
2. Entry 직후 SL + TP를 conditional reduce-only 주문으로 즉시 등록
   → 봇 죽어도 거래소 자체에서 청산/익절 처리.
3. Kill switch: SIGTERM/SIGINT 받으면 (a) 모든 plan order 취소
   (b) 열린 포지션 시장가 reduce-only 청산.
4. 시작시 state reconcile: 거래소 실제 포지션 = source of truth.
   로컬 상태가 어긋나면 거래소 기준으로 정정.
5. MARGIN_FIXED env 오버라이드 가능 → micro test 쉽게 ($5).
6. POSITION_LIMIT=1: 동시 포지션 1개 (multi-trade 동시 진행 금지).

=== 환경 변수 ===
  BITGET_API_KEY        : API key
  BITGET_API_SECRET     : Secret
  BITGET_API_PASSPHRASE : passphrase (Bitget 필수)
  BITGET_LIVE           : "1" 이어야 실주문 (그 외엔 DRY_RUN)
  LIVE_BOT_MARGIN       : margin USD (디폴트 50)
  LIVE_BOT_TG_TOKEN     : Telegram bot token (옵션)
  LIVE_BOT_TG_CHAT      : Telegram chat id (옵션)

=== 실행 ===
  # DRY-run (디폴트):
  python3 scripts/quant_phase29_live_bot.py

  # 실거래 micro ($5 margin = $50 notional):
  BITGET_API_KEY=xxx BITGET_API_SECRET=yyy BITGET_API_PASSPHRASE=zzz \\
  BITGET_LIVE=1 LIVE_BOT_MARGIN=5 \\
  python3 scripts/quant_phase29_live_bot.py

=== 종료 / 긴급 정지 ===
  Ctrl+C 또는 `kill -TERM <pid>` → 자동으로 모든 포지션/주문 cleanup 후 exit.
"""
from __future__ import annotations

import json, os, sys, time, signal as signal_mod, atexit
from dataclasses import dataclass, asdict, field
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import numpy as np
from urllib import request as _urlreq, parse as _urlparse

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "quant_runtime" / "live_bot_state.json"
LOG_PATH = ROOT / "quant_runtime" / "live_bot_log.jsonl"

# ===== STRATEGY (matches Phase23 paper / Phase27 winner) =====
LEVERAGE = 10
MARGIN_FIXED = float(os.environ.get("LIVE_BOT_MARGIN", "50"))
COST_RT = 0.0012
SLIPPAGE_BPS = 8
LIQ_BUFFER_PCT = 95.0

UNIVERSE = ["PEPE/USDT:USDT", "WIF/USDT:USDT", "DOGE/USDT:USDT"]
TIMEFRAME = "1h"
HISTORY_BARS = 500

TP_ROE = 500.0
SL_ROE = -30.0
SIGNAL_OFF_MIN_ROE = 0.0

COOLDOWN_AFTER_EXIT_H = 12
COOLDOWN_AFTER_LOSS_H = 24

POLL_SEC = 60

REGIME_SYMBOL = "BTC/USDT:USDT"
REGIME_ATR_MIN = 0.4
SYMBOL_MOM_MIN = 0.05

# ===== LIVE / DRY-RUN =====
LIVE = os.environ.get("BITGET_LIVE", "0") == "1"
API_KEY = os.environ.get("BITGET_API_KEY", "")
API_SECRET = os.environ.get("BITGET_API_SECRET", "")
API_PASS = os.environ.get("BITGET_API_PASSPHRASE", "")

# ===== Telegram =====
TG_TOKEN = os.environ.get("LIVE_BOT_TG_TOKEN", "")
TG_CHAT = os.environ.get("LIVE_BOT_TG_CHAT", "")
TG_ENABLED = bool(TG_TOKEN and TG_CHAT)


# ===== INDICATORS (copied verbatim from paper bot) =====
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
        s = max(0, i - period + 1); seg = close[s:i+1]
        m = np.mean(seg); sd = np.std(seg)
        middle[i] = m
        upper[i] = m + stdev * sd
        lower[i] = m - stdev * sd
        width[i] = (upper[i] - lower[i]) / max(m, 1e-9)
    rank = np.zeros(n)
    for i in range(n):
        s = max(0, i - 100 + 1); seg = width[s:i+1]
        rank[i] = (seg <= width[i]).sum() / len(seg)
    return upper, middle, lower, width, rank


def compute_features(klines):
    arr = np.array(klines, dtype=float)
    if len(arr) < 30:
        return None
    high = arr[:, 2]; low = arr[:, 3]; close = arr[:, 4]; vol = arr[:, 5]
    n = len(close)
    mom24 = np.zeros(n)
    for i in range(n):
        if i >= 24: mom24[i] = close[i] / close[i-24] - 1
    vol_ma = np.zeros(n)
    for i in range(n):
        s = max(0, i - 19); vol_ma[i] = np.mean(vol[s:i+1])
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
            "obv": obv, "obv_slope": obv_slope, "ts": arr[:, 0]}


# ===== SIGNALS =====
def vol_expansion_signal(ind, i):
    if i < 30: return False
    return (ind["bb_width_rank"][i] >= 0.7 and ind["mom24"][i] > 0.03
            and ind["close"][i] > ind["bb_upper"][i] and ind["vol_r"][i] >= 1.5)


def momentum_obv_signal(ind, i):
    if i < 25: return False
    return (ind["mom24"][i] > 0.05 and ind["ema20"][i] > ind["ema50"][i]
            and ind["adx"][i] > 22 and ind["vol_r"][i] >= 1.3 and ind["obv_slope"][i] > 0)


def squeeze_release_signal(ind, i):
    if i < 22 or i < 5: return False
    if not all(ind["bb_width_rank"][k] < 0.30 for k in range(i-5, i)): return False
    return ind["close"][i] > ind["bb_upper"][i-1] and ind["vol_r"][i] > 1.3


ENSEMBLE_SIGNALS = [
    ("vol_expansion", vol_expansion_signal),
    ("momentum_obv",  momentum_obv_signal),
    ("squeeze_release", squeeze_release_signal),
]


def any_signal_active(ind, i, signal_name):
    for name, fn in ENSEMBLE_SIGNALS:
        if name == signal_name: return fn(ind, i)
    return False


# ===== STATE =====
@dataclass
class BotState:
    n_trades: int = 0
    n_wins: int = 0
    n_losses: int = 0
    n_liquidations: int = 0
    cum_pnl: float = 0.0
    last_exit_ts: int = 0
    last_loss_exit_ts: int = 0
    open_position: Optional[dict] = None
    open_orders: list = field(default_factory=list)  # SL/TP order ids
    started_at: str = ""
    last_check_at: str = ""
    last_event: str = ""
    live_mode: bool = False  # True = real orders, False = DRY_RUN


def save_state(state: BotState):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(asdict(state), f, indent=2)


def load_state() -> BotState:
    if not STATE_PATH.exists():
        s = BotState()
        s.started_at = datetime.now(timezone.utc).isoformat()
        return s
    with open(STATE_PATH) as f: data = json.load(f)
    return BotState(**data)


def log_event(event: dict):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    event["ts_iso"] = datetime.now(timezone.utc).isoformat()
    with open(LOG_PATH, "a") as f: f.write(json.dumps(event) + "\n")


# ===== EXCHANGE =====
def init_exchange():
    import ccxt
    cfg = {"options": {"defaultType": "swap"}, "enableRateLimit": True}
    if LIVE:
        if not (API_KEY and API_SECRET and API_PASS):
            raise SystemExit("BITGET_LIVE=1 인데 API 키 미설정. "
                             "BITGET_API_KEY / BITGET_API_SECRET / BITGET_API_PASSPHRASE 필요.")
        cfg["apiKey"] = API_KEY
        cfg["secret"] = API_SECRET
        cfg["password"] = API_PASS
    return ccxt.bitget(cfg)


def setup_account(ex):
    """Set leverage = 10x, margin mode = isolated for all symbols in universe."""
    if not LIVE:
        log_event({"event": "dry_run_skip_setup"})
        return
    for sym in UNIVERSE:
        try:
            ex.set_margin_mode("isolated", sym)
        except Exception as e:
            log_event({"event": "set_margin_mode_warn", "symbol": sym, "error": str(e)})
        try:
            ex.set_leverage(LEVERAGE, sym, params={"marginMode": "isolated"})
        except Exception as e:
            log_event({"event": "set_leverage_warn", "symbol": sym, "error": str(e)})


def fetch_klines(ex, symbol, limit=HISTORY_BARS):
    return ex.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=limit)


def fetch_ticker_price(ex, symbol):
    try:
        t = ex.fetch_ticker(symbol)
        bid = t.get("bid"); ask = t.get("ask"); last = t.get("last")
        if bid and ask: return (bid + ask) / 2.0
        return float(last) if last else None
    except Exception as e:
        log_event({"event": "ticker_error", "symbol": symbol, "error": str(e)})
        return None


def fetch_mark_price(ex, symbol):
    try:
        t = ex.fetch_ticker(symbol)
        info = t.get("info", {})
        mp = info.get("markPrice") or info.get("mark_price") or info.get("indexPrice")
        if mp is not None: return float(mp)
        if t.get("markPrice"): return float(t["markPrice"])
        return float(t.get("last") or 0) or None
    except Exception as e:
        log_event({"event": "mark_price_error", "symbol": symbol, "error": str(e)})
        return None


def fetch_position_real(ex, symbol):
    """Returns dict with size, entry, etc OR None if no open position."""
    if not LIVE: return None
    try:
        positions = ex.fetch_positions([symbol])
        for p in positions:
            sz = float(p.get("contracts") or p.get("contractSize") or 0)
            if sz > 0:
                return {"symbol": symbol,
                        "size": sz,
                        "entry": float(p.get("entryPrice") or 0),
                        "side": p.get("side", "long"),
                        "raw": p}
        return None
    except Exception as e:
        log_event({"event": "fetch_position_error", "symbol": symbol, "error": str(e)})
        return None


def btc_regime_active(ex):
    try:
        klines = fetch_klines(ex, REGIME_SYMBOL, 250)
        if not klines or len(klines) < 80: return False
        ind = compute_features(klines)
        if ind is None: return False
        i = len(ind["close"]) - 2
        high = ind["high"]; low = ind["low"]; close = ind["close"]
        n = len(close); tr = np.zeros(n)
        for k in range(1, n):
            tr[k] = max(high[k]-low[k], abs(high[k]-close[k-1]), abs(low[k]-close[k-1]))
        s = max(0, i - 23); atr_now = float(np.mean(tr[s:i+1]))
        s2 = max(0, i - 199); atr_window = []
        for k in range(s2, i+1):
            sk = max(0, k - 23); atr_window.append(float(np.mean(tr[sk:k+1])))
        atr_rank = sum(1 for a in atr_window if a <= atr_now) / max(1, len(atr_window))
        return (ind["ema20"][i] > ind["ema50"][i]) and (atr_rank >= REGIME_ATR_MIN)
    except Exception as e:
        log_event({"event": "regime_error", "error": str(e)})
        return False


def telegram_send(text):
    if not TG_ENABLED: return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        data = _urlparse.urlencode({"chat_id": TG_CHAT, "text": text,
                                     "parse_mode": "HTML"}).encode()
        _urlreq.urlopen(_urlreq.Request(url, data=data), timeout=5)
    except Exception as e:
        log_event({"event": "telegram_error", "error": str(e)})


# ===== ORDER PLACEMENT =====
def place_market_long(ex, symbol, notional_usd, mark_px):
    """Open long position with market order. Returns dict with order id + filled details.

    notional_usd: $500 (margin × lev) — total exposure size in USD.
    """
    base_amount = notional_usd / mark_px  # how many coins
    if not LIVE:
        log_event({"event": "DRY_OPEN", "symbol": symbol,
                   "notional": notional_usd, "amount": base_amount, "mark": mark_px})
        return {"id": "DRY_RUN", "amount": base_amount, "avg_price": mark_px,
                "dry_run": True}
    try:
        order = ex.create_market_buy_order(
            symbol, base_amount,
            params={"timeInForce": "IOC"}
        )
        # market orders fill immediately; refetch to get avg price
        time.sleep(0.5)
        positions = ex.fetch_positions([symbol])
        avg = mark_px
        actual_amt = base_amount
        for p in positions:
            if float(p.get("contracts") or 0) > 0:
                avg = float(p.get("entryPrice") or mark_px)
                actual_amt = float(p.get("contracts"))
                break
        return {"id": order.get("id"), "amount": actual_amt,
                "avg_price": avg, "raw": order, "dry_run": False}
    except Exception as e:
        log_event({"event": "place_long_error", "symbol": symbol, "error": str(e)})
        raise


def place_sl_tp_orders(ex, symbol, base_amount, entry_px):
    """Place stop-loss and take-profit reduce-only conditional orders.

    Returns list of order ids (for cancellation later).
    """
    sl_px = entry_px * (1 + SL_ROE / 100.0 / LEVERAGE)
    tp_px = entry_px * (1 + TP_ROE / 100.0 / LEVERAGE)

    if not LIVE:
        log_event({"event": "DRY_SL_TP", "symbol": symbol,
                   "sl": sl_px, "tp": tp_px, "amount": base_amount})
        return ["DRY_SL", "DRY_TP"]

    ids = []
    try:
        # Stop-loss: ccxt unified — trigger market sell at sl_px (reduce-only)
        sl_order = ex.create_stop_loss_order(
            symbol, "market", "sell", base_amount,
            triggerPrice=sl_px,
            params={"reduceOnly": True}
        )
        ids.append(sl_order.get("id"))
        log_event({"event": "SL_PLACED", "symbol": symbol, "sl_px": sl_px,
                   "order_id": sl_order.get("id")})
    except Exception as e:
        log_event({"event": "place_sl_error", "symbol": symbol, "error": str(e)})
        # fallback to generic create_order
        try:
            sl_order = ex.create_order(
                symbol, "market", "sell", base_amount, None,
                {"stopLossPrice": sl_px, "reduceOnly": True})
            ids.append(sl_order.get("id"))
            log_event({"event": "SL_PLACED_FALLBACK", "order_id": sl_order.get("id")})
        except Exception as e2:
            log_event({"event": "place_sl_fallback_error", "error": str(e2)})

    try:
        # Take-profit: ccxt unified — trigger limit sell at tp_px (reduce-only)
        tp_order = ex.create_take_profit_order(
            symbol, "limit", "sell", base_amount, price=tp_px,
            triggerPrice=tp_px,
            params={"reduceOnly": True}
        )
        ids.append(tp_order.get("id"))
        log_event({"event": "TP_PLACED", "symbol": symbol, "tp_px": tp_px,
                   "order_id": tp_order.get("id")})
    except Exception as e:
        log_event({"event": "place_tp_error", "symbol": symbol, "error": str(e)})
        try:
            tp_order = ex.create_order(
                symbol, "limit", "sell", base_amount, tp_px,
                {"takeProfitPrice": tp_px, "reduceOnly": True})
            ids.append(tp_order.get("id"))
            log_event({"event": "TP_PLACED_FALLBACK", "order_id": tp_order.get("id")})
        except Exception as e2:
            log_event({"event": "place_tp_fallback_error", "error": str(e2)})

    return ids


def cancel_all_orders(ex, symbol):
    if not LIVE:
        log_event({"event": "DRY_CANCEL_ALL", "symbol": symbol})
        return
    try:
        # cancel both regular + plan/trigger orders
        ex.cancel_all_orders(symbol)
    except Exception as e:
        log_event({"event": "cancel_all_error", "symbol": symbol, "error": str(e)})
    # bitget plan orders may need separate cancellation
    try:
        plans = ex.fetch_open_orders(symbol, params={"stop": True})
        for o in plans:
            try: ex.cancel_order(o["id"], symbol, params={"stop": True})
            except Exception: pass
    except Exception:
        pass


def close_position_market(ex, symbol, base_amount):
    """Reduce-only market sell to close long. Returns avg fill price."""
    if not LIVE:
        log_event({"event": "DRY_CLOSE", "symbol": symbol, "amount": base_amount})
        return None
    try:
        order = ex.create_order(
            symbol, "market", "sell", base_amount, None,
            {"reduceOnly": True}
        )
        time.sleep(0.5)
        # try to get fill price
        try:
            o2 = ex.fetch_order(order["id"], symbol)
            return float(o2.get("average") or o2.get("price") or 0) or None
        except Exception:
            return None
    except Exception as e:
        log_event({"event": "close_position_error", "symbol": symbol, "error": str(e)})
        return None


# ===== ENTRY / EXIT LOGIC =====
def evaluate_entry(ex, state: BotState):
    if state.open_position is not None: return None
    now_ms = int(time.time() * 1000)
    if state.last_exit_ts > 0 and (now_ms - state.last_exit_ts) < COOLDOWN_AFTER_EXIT_H * 3600 * 1000:
        return None
    if state.last_loss_exit_ts > 0 and (now_ms - state.last_loss_exit_ts) < COOLDOWN_AFTER_LOSS_H * 3600 * 1000:
        return None
    if not btc_regime_active(ex): return None

    for sym in UNIVERSE:
        try:
            klines = fetch_klines(ex, sym, HISTORY_BARS)
            if not klines: continue
            ind = compute_features(klines)
            if ind is None: continue
            i = len(ind["close"]) - 2
            if ind["mom24"][i] < SYMBOL_MOM_MIN: continue
            for sig_name, sig_fn in ENSEMBLE_SIGNALS:
                if not sig_fn(ind, i): continue
                live_px = fetch_ticker_price(ex, sym) or float(ind["close"][i])
                return {
                    "symbol": sym, "signal_name": sig_name,
                    "live_price": float(live_px),
                    "signal_bar_close": float(ind["close"][i]),
                    "signal_bar_ts": int(ind["ts"][i]),
                    "ind_snapshot": {
                        "signal": sig_name,
                        "mom24": float(ind["mom24"][i]),
                        "vol_r": float(ind["vol_r"][i]),
                        "bb_width_rank": float(ind["bb_width_rank"][i]),
                        "adx": float(ind["adx"][i]),
                        "live_ticker": float(live_px),
                    },
                }
        except Exception as e:
            log_event({"event": "fetch_error", "symbol": sym, "error": str(e)})
    return None


def evaluate_signal_off_exit(ex, state: BotState):
    """Only checked on each poll for SIGNAL_OFF + profit case.
    SL/TP는 거래소에 등록된 conditional order가 자동 처리.
    Liquidation도 거래소가 처리.
    """
    if state.open_position is None: return None
    pos = state.open_position
    try:
        klines = fetch_klines(ex, pos["symbol"], HISTORY_BARS)
        if not klines: return None
        ind = compute_features(klines)
        if ind is None: return None
        i = len(ind["close"]) - 2
        cl = ind["close"][i]; ep = pos["entry_price"]
        roe_cl = (cl / ep - 1) * LEVERAGE * 100
        entry_sig = pos.get("signal_name", "vol_expansion")
        sig_now = any_signal_active(ind, i, entry_sig)
        if (not sig_now) and roe_cl > SIGNAL_OFF_MIN_ROE:
            return {"reason": "SIGNAL_OFF_INPROFIT", "exit_ts": int(ind["ts"][i]),
                    "roe_at_signal": roe_cl}
    except Exception as e:
        log_event({"event": "exit_check_error", "error": str(e)})
    return None


def open_position(ex, state: BotState, entry: dict):
    sym = entry["symbol"]
    mark = fetch_mark_price(ex, sym) or entry["live_price"]
    notional = MARGIN_FIXED * LEVERAGE

    fill = place_market_long(ex, sym, notional, mark)
    entry_price = fill["avg_price"]
    base_amount = fill["amount"]

    # immediately register SL + TP at exchange
    order_ids = place_sl_tp_orders(ex, sym, base_amount, entry_price)

    state.open_position = {
        "symbol": sym, "side": 1,
        "signal_name": entry["signal_name"],
        "entry_price": entry_price,
        "entry_ts": int(time.time() * 1000),
        "margin": MARGIN_FIXED, "notional": notional,
        "base_amount": base_amount,
        "ind_snapshot": entry["ind_snapshot"],
        "live_mode": LIVE,
    }
    state.open_orders = order_ids
    state.last_event = (f"OPEN {sym} ({entry['signal_name']}) @ ${entry_price:.6f} "
                       f"size={base_amount:.4g} {'[LIVE]' if LIVE else '[DRY]'}")
    log_event({"event": "OPEN", "live": LIVE, "position": state.open_position,
               "fill": fill, "sl_tp_ids": order_ids})
    telegram_send(
        f"{'🟢 [LIVE]' if LIVE else '🟡 [DRY]'} <b>OPEN</b> {sym.split('/')[0]}\n"
        f"signal: {entry['signal_name']}\n"
        f"price: {entry_price:.6g}  size: {base_amount:.4g}\n"
        f"margin: ${MARGIN_FIXED:.2f}  notional: ${notional:.2f}\n"
        f"SL=-30% TP=+500% (exchange-managed)"
    )
    save_state(state)


def close_position(ex, state: BotState, reason: str, exit_ts: int):
    """Manual close (signal_off or kill switch). Cancels SL/TP first."""
    pos = state.open_position
    if pos is None: return
    sym = pos["symbol"]
    base_amount = pos["base_amount"]

    # cancel pending SL/TP orders so close goes through cleanly
    cancel_all_orders(ex, sym)

    # market close
    fill_px = close_position_market(ex, sym, base_amount)
    if fill_px is None:
        # DRY-RUN or fetch failed: estimate from current ticker
        fill_px = fetch_ticker_price(ex, sym) or pos["entry_price"]

    ep = pos["entry_price"]
    raw_roe = (fill_px / ep - 1) * LEVERAGE * 100
    notional = pos["notional"]
    fee = notional * COST_RT
    hold_h = max(0, exit_ts - pos["entry_ts"]) / 3600000.0
    funding = notional * 0.0001 * (hold_h / 8.0)  # rough; real funding settled by exchange

    if raw_roe <= -100:
        pnl = -pos["margin"] - fee
    else:
        pnl = pos["margin"] * (raw_roe / 100.0) - fee - funding

    if pnl > 0: state.n_wins += 1
    else:
        state.n_losses += 1
        state.last_loss_exit_ts = exit_ts
        if reason == "LIQUIDATED": state.n_liquidations += 1
    state.n_trades += 1
    state.cum_pnl += pnl
    state.last_exit_ts = exit_ts
    state.last_event = f"CLOSE {sym} {reason} ROE={raw_roe:+.1f}% PnL=${pnl:+.2f}"

    log_event({"event": "CLOSE", "live": LIVE, "position": pos,
               "reason": reason, "exit_price": fill_px,
               "exit_roe": raw_roe, "exit_ts": exit_ts,
               "pnl": pnl, "fee": fee, "funding": funding,
               "hold_h": round(hold_h, 2)})

    emoji = {"TP": "💎", "LIQUIDATED": "💀", "SIGNAL_OFF_INPROFIT": "✅",
             "SL": "🛑", "KILL_SWITCH": "🛑"}.get(reason, "⚪")
    telegram_send(
        f"{emoji} {'[LIVE]' if LIVE else '[DRY]'} <b>CLOSE</b> {sym.split('/')[0]}\n"
        f"reason: {reason}\n"
        f"ROE: {raw_roe:+.1f}%   PnL: ${pnl:+.2f}\n"
        f"hold: {hold_h:.1f}h  fee: ${fee:.2f}\n"
        f"trades: {state.n_trades} (W{state.n_wins}/L{state.n_losses}/Liq{state.n_liquidations})  "
        f"cum: ${state.cum_pnl:+.2f}"
    )

    state.open_position = None
    state.open_orders = []
    save_state(state)


def reconcile_with_exchange(ex, state: BotState):
    """On startup: check exchange truth vs local state. Exchange wins."""
    if not LIVE:
        log_event({"event": "skip_reconcile_dry"})
        return
    real_positions = []
    for sym in UNIVERSE:
        rp = fetch_position_real(ex, sym)
        if rp: real_positions.append(rp)

    if state.open_position and not real_positions:
        # local says open, exchange says no → likely SL/TP triggered while bot was down
        log_event({"event": "RECONCILE_close_state",
                   "stale_pos": state.open_position})
        telegram_send(f"⚠️ Reconcile: local 포지션 {state.open_position['symbol']} 인데 "
                      f"거래소엔 없음 → state 청산 처리. SL/TP 발동 가능성.")
        state.open_position = None
        state.open_orders = []
        state.last_exit_ts = int(time.time() * 1000)
        save_state(state)
    elif state.open_position is None and real_positions:
        # exchange has position, local doesn't → adopt exchange position
        rp = real_positions[0]
        log_event({"event": "RECONCILE_adopt_exchange", "real": rp})
        telegram_send(f"⚠️ Reconcile: 거래소에 미등록 포지션 {rp['symbol']} 발견 → state에 등록")
        state.open_position = {
            "symbol": rp["symbol"], "side": 1,
            "signal_name": "unknown",  # original signal lost
            "entry_price": rp["entry"],
            "entry_ts": int(time.time() * 1000),  # estimate
            "margin": MARGIN_FIXED,
            "notional": MARGIN_FIXED * LEVERAGE,
            "base_amount": rp["size"],
            "ind_snapshot": {},
            "live_mode": True,
        }
        save_state(state)


# ===== KILL SWITCH =====
RUN = True
_KILL_DONE = False
_EX = None
_STATE = None


def emergency_cleanup():
    """Cancel all orders, close any open position. Called on SIGINT/SIGTERM and atexit."""
    global _KILL_DONE
    if _KILL_DONE: return
    _KILL_DONE = True
    if _EX is None or _STATE is None: return
    try:
        if _STATE.open_position is not None:
            log_event({"event": "KILL_SWITCH_TRIGGERED",
                       "symbol": _STATE.open_position["symbol"]})
            print("\n[KILL] Closing open position + cancelling orders...")
            telegram_send(f"🛑 Kill switch: {_STATE.open_position['symbol']} 포지션 시장가 청산 중...")
            close_position(_EX, _STATE, "KILL_SWITCH", int(time.time() * 1000))
        else:
            # still cancel all orders defensively
            for sym in UNIVERSE:
                cancel_all_orders(_EX, sym)
    except Exception as e:
        log_event({"event": "cleanup_error", "error": str(e)})
        print(f"[KILL] cleanup error: {e}")


def handle_signal(*_):
    global RUN
    RUN = False
    print("\n[stop] Signal received → cleanup + exit")
    emergency_cleanup()
    sys.exit(0)


atexit.register(emergency_cleanup)


# ===== MAIN =====
def main():
    global _EX, _STATE
    signal_mod.signal(signal_mod.SIGINT, handle_signal)
    signal_mod.signal(signal_mod.SIGTERM, handle_signal)

    print(f"[start] LIVE bot starting...")
    print(f"  Mode: {'🔴 LIVE (REAL ORDERS)' if LIVE else '🟡 DRY-RUN (no orders)'}")
    print(f"  Strategy: V_REG_SYM_SL30 (TP+500/SL-30/signal_off)")
    print(f"  Leverage: {LEVERAGE}x  |  Margin: ${MARGIN_FIXED}")
    print(f"  Universe: {UNIVERSE}")
    print(f"  Polling every {POLL_SEC}s")
    if LIVE:
        print(f"  ⚠️  실거래 모드. SL=-30% / TP=+500% 가 진입 즉시 거래소에 등록됨.")
        print(f"     봇 죽어도 거래소에서 SL/TP 자동 처리.")
        print(f"     Ctrl+C / kill -TERM <pid>로 안전 종료 (포지션 시장가 청산).")

    state = load_state()
    state.live_mode = LIVE
    if not state.started_at:
        state.started_at = datetime.now(timezone.utc).isoformat()
    save_state(state)
    _STATE = state

    ex = init_exchange()
    _EX = ex
    setup_account(ex)
    reconcile_with_exchange(ex, state)

    while RUN:
        state.last_check_at = datetime.now(timezone.utc).isoformat()
        try:
            if state.open_position is not None:
                # exchange handles SL/TP/LIQ; we only check for SIGNAL_OFF + profit
                # but also reconcile periodically (every loop):
                if LIVE:
                    rp = fetch_position_real(ex, state.open_position["symbol"])
                    if rp is None:
                        # position closed by exchange (SL/TP/liq) - mark closed in state
                        log_event({"event": "EXCHANGE_CLOSED_POSITION",
                                   "symbol": state.open_position["symbol"]})
                        # we don't know exact reason; assume SL/TP fired
                        # let post-mortem be done by user via Bitget UI
                        state.last_exit_ts = int(time.time() * 1000)
                        sym = state.open_position["symbol"]
                        cancel_all_orders(ex, sym)
                        # rough record (real PnL must be reconciled from Bitget statement)
                        state.n_trades += 1
                        state.last_event = f"CLOSE {sym} BY_EXCHANGE (SL/TP/LIQ)"
                        telegram_send(
                            f"⚪ <b>CLOSE</b> {sym.split('/')[0]} (거래소 자동처리)\n"
                            f"이유: SL/TP/청산 중 하나. Bitget 화면 확인 필요.\n"
                            f"trades: {state.n_trades}"
                        )
                        state.open_position = None
                        state.open_orders = []
                        save_state(state)
                    else:
                        exit_info = evaluate_signal_off_exit(ex, state)
                        if exit_info:
                            close_position(ex, state, exit_info["reason"], exit_info["exit_ts"])
                else:
                    # DRY-RUN
                    exit_info = evaluate_signal_off_exit(ex, state)
                    if exit_info:
                        close_position(ex, state, exit_info["reason"], exit_info["exit_ts"])
            else:
                entry = evaluate_entry(ex, state)
                if entry:
                    open_position(ex, state, entry)
            save_state(state)
        except Exception as e:
            log_event({"event": "loop_error", "error": str(e)})
            print(f"[error] {e}")

        # status print every 5 min
        if int(time.time()) % 300 < POLL_SEC:
            mode = "LIVE" if LIVE else "DRY"
            pos_str = f"OPEN {state.open_position['symbol']}" if state.open_position else "no pos"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {mode} | {pos_str} | "
                  f"trades={state.n_trades} W{state.n_wins}/L{state.n_losses}/Liq{state.n_liquidations} "
                  f"cumPnL=${state.cum_pnl:+.2f}")

        for _ in range(POLL_SEC):
            if not RUN: break
            time.sleep(1)

    save_state(state)
    print(f"\n[exit] trades={state.n_trades} cum=${state.cum_pnl:+.2f}")


if __name__ == "__main__":
    main()
