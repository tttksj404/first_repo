"""G902-session paper-live emulator — DOGE session momentum (S2 of E5 ensemble).

Rule (Tigro Blanc 2026 inverted clocks):
  At 16:00 UTC each day:
    - eur_ret = (DOGE close at 16:00 / DOGE close at 08:00) - 1
    - p75 = 75th percentile of past 30 days' eur_ret
    - p25 = 25th percentile of past 30 days' eur_ret
    - if eur_ret > p75 -> open DOGE LONG
    - if eur_ret < p25 -> open DOGE SHORT
  At 23:00 UTC: close any open position.

Backtest: 168 trades / year, +$184 PnL, WR 48.8%, MDD -25%, Sharpe 1.14
(verify_btc_timing/h1_h4_results.json - H3 sess DOGEUSDT).

Capital halved (SIZE_PCT 0.1) for 50/50 ensemble with G902 (S1).
"""
import json, time, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import pandas as pd

APP = Path(__file__).parent
OUT = APP / "runtime"; OUT.mkdir(parents=True, exist_ok=True)
TRADES = OUT / "trades.jsonl"
STATE  = OUT / "state.json"
LOG    = OUT / "emulator.log"

SYMBOL = "DOGEUSDT"
EQUITY_USD = 100.0
SIZE_PCT = 0.1
LEVERAGE = 20.0
LOOKBACK_DAYS = 30
P_LONG = 75
P_SHORT = 25
COST_BPS_RT = 16.0
ENTRY_HOUR_UTC = 16
EXIT_HOUR_UTC = 23
CYCLE_SECONDS = 60  # check every minute (cheap)
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"


def log(m):
    line = f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {m}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state():
    if STATE.exists():
        try: return json.loads(STATE.read_text(encoding="utf-8"))
        except: pass
    return {"started_at": datetime.now(timezone.utc).isoformat(),
            "open_position": None, "closed_count": 0, "wins": 0, "losses": 0,
            "cumulative_pnl_usd": 0.0, "last_decision_date": None,
            "last_cycle": None}


def save_state(s):
    s["last_cycle"] = datetime.now(timezone.utc).isoformat()
    STATE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")


def append_trade(e):
    with TRADES.open("a", encoding="utf-8") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")


def fetch_klines(symbol, limit=200):
    url = f"{BINANCE_KLINES}?symbol={symbol}&interval=1h&limit={limit}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            chunk = json.loads(r.read())
    except Exception as e:
        log(f"  fetch {symbol} FAIL: {e}")
        return None
    if not chunk: return None
    bars = [{"open_time": b[0], "open": float(b[1]), "high": float(b[2]),
             "low": float(b[3]), "close": float(b[4])} for b in chunk[:-1]]
    return pd.DataFrame(bars)


def get_session_history(df, lookback_days=LOOKBACK_DAYS):
    """Compute past N days of EUR session (08-16 UTC) returns."""
    df = df.copy()
    df['dt'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    df['date'] = df['dt'].dt.date
    df['hour'] = df['dt'].dt.hour
    rets = []
    for date, grp in df.groupby('date'):
        eur_open = grp[grp['hour'] == 8]['open'].values
        eur_close = grp[grp['hour'] == 16]['open'].values
        if len(eur_open) and len(eur_close) and eur_open[0] > 0:
            rets.append((date, (eur_close[0] / eur_open[0] - 1.0)))
    return rets[-lookback_days:]  # last N days


def cycle(state):
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    # ── EXIT logic: at EXIT_HOUR_UTC or later, close any open ──
    if state["open_position"] and now.hour >= EXIT_HOUR_UTC:
        df = fetch_klines(SYMBOL, limit=2)
        if df is None:
            log(f"  EXIT fetch fail, retry next cycle")
            return
        cur_p = float(df['close'].iloc[-1])
        pos = state["open_position"]
        side = pos["side"]
        ep = pos["entry_close"]
        gp_pct = ((cur_p / ep - 1.0) if side == "long" else (ep / cur_p - 1.0)) * 100
        npp = (gp_pct / 100 - COST_BPS_RT / 10000) * LEVERAGE
        if npp < -0.90: npp = -0.90  # cap at -90% (account preservation)
        pnl = round(EQUITY_USD * SIZE_PCT * npp, 4)
        state["cumulative_pnl_usd"] = round(state["cumulative_pnl_usd"] + pnl, 4)
        state["closed_count"] += 1
        if pnl > 0: state["wins"] += 1
        else: state["losses"] += 1
        append_trade({"type": "EXIT", "symbol": SYMBOL, "side": side,
                      "entry_close": ep, "exit_close": cur_p,
                      "gross_pct": round(gp_pct, 4), "net_pct_levered": round(npp, 4),
                      "pnl_usd": pnl, "exit_ts": now.isoformat()})
        log(f"  EXIT  {side.upper()}: entry={ep:.6f} exit={cur_p:.6f} gross={gp_pct:+.2f}% lev={npp*100:+.2f}% PnL=${pnl:+.2f}")
        state["open_position"] = None
        save_state(state)
        return

    # ── ENTRY logic: at ENTRY_HOUR_UTC, exactly once per day ──
    if now.hour == ENTRY_HOUR_UTC and state["last_decision_date"] != today:
        if state["open_position"]:
            log(f"  ENTRY skipped: position already open from {state['open_position']['entry_ts']}")
            state["last_decision_date"] = today
            save_state(state)
            return

        # need 30+ days of hourly data = 720 bars, fetch 1000 (max per request)
        df = fetch_klines(SYMBOL, limit=1000)
        if df is None or len(df) < LOOKBACK_DAYS * 24:
            log(f"  ENTRY abort: insufficient bars ({0 if df is None else len(df)})")
            state["last_decision_date"] = today
            save_state(state)
            return

        history = get_session_history(df, LOOKBACK_DAYS)
        if len(history) < LOOKBACK_DAYS - 5:
            log(f"  ENTRY abort: only {len(history)} days history (need {LOOKBACK_DAYS})")
            state["last_decision_date"] = today
            save_state(state)
            return

        prev_rets = [r for _, r in history[:-1]] if len(history) > 1 else [r for _, r in history]
        cur_eur_ret = history[-1][1] if history[-1][0] == now.date() else None

        # if current day's eur_ret not yet captured (data lag), compute manually from latest bars
        if cur_eur_ret is None:
            df2 = df.copy()
            df2['dt'] = pd.to_datetime(df2['open_time'], unit='ms', utc=True)
            today_bars = df2[df2['dt'].dt.date == now.date()]
            eur_open_today = today_bars[today_bars['dt'].dt.hour == 8]['open'].values
            eur_close_today = today_bars[today_bars['dt'].dt.hour == 16]['open'].values
            if len(eur_open_today) and len(eur_close_today) and eur_open_today[0] > 0:
                cur_eur_ret = float(eur_close_today[0] / eur_open_today[0] - 1.0)

        if cur_eur_ret is None:
            log(f"  ENTRY abort: cannot compute today's EUR session return")
            state["last_decision_date"] = today
            save_state(state)
            return

        p75 = float(np.percentile(prev_rets, P_LONG))
        p25 = float(np.percentile(prev_rets, P_SHORT))
        log(f"  decision: cur_eur_ret={cur_eur_ret*100:+.3f}%  p75={p75*100:+.3f}%  p25={p25*100:+.3f}%")

        side = None
        if cur_eur_ret > p75: side = "long"
        elif cur_eur_ret < p25: side = "short"

        if side:
            entry_p = float(df['close'].iloc[-1])
            state["open_position"] = {"side": side, "entry_close": entry_p,
                                       "entry_ts": now.isoformat(),
                                       "eur_ret": cur_eur_ret, "p75": p75, "p25": p25}
            append_trade({"type": "ENTRY", "symbol": SYMBOL, "side": side,
                          "entry_close": entry_p, "eur_ret": cur_eur_ret,
                          "p75": p75, "p25": p25, "entry_ts": now.isoformat(),
                          "size_usd_margin": EQUITY_USD * SIZE_PCT,
                          "notional_usd": EQUITY_USD * SIZE_PCT * LEVERAGE})
            log(f"  ENTRY {side.upper()} {SYMBOL} @ {entry_p:.6f}  cur={cur_eur_ret*100:+.2f}% vs p75={p75*100:+.2f}% p25={p25*100:+.2f}%")
        else:
            log(f"  NO_TRADE: {cur_eur_ret*100:+.2f}% within [p25,p75]")

        state["last_decision_date"] = today
        save_state(state)
        return

    # idle heartbeat (every ~5 min)
    if now.minute % 5 == 0:
        op = state.get("open_position")
        log(f"  HEARTBEAT hour={now.hour} pos={'open ' + op['side'] if op else 'none'} closed={state['closed_count']} W/L={state['wins']}/{state['losses']} cumPnL=${state['cumulative_pnl_usd']:+.2f}")
        save_state(state)


def main():
    log(f"=== G902-session emulator START === sym={SYMBOL} lookback={LOOKBACK_DAYS}d entry@{ENTRY_HOUR_UTC}UTC exit@{EXIT_HOUR_UTC}UTC eq=${EQUITY_USD} size={SIZE_PCT} lev={LEVERAGE}x p_long={P_LONG} p_short={P_SHORT}")
    state = load_state()
    while True:
        try: cycle(state)
        except KeyboardInterrupt: log("STOP"); break
        except Exception as e: log(f"CYCLE_ERROR: {type(e).__name__}: {e}")
        time.sleep(CYCLE_SECONDS)


if __name__ == "__main__":
    main()
