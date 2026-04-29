"""
G041 Paper-Live Daemon — 실시간 Binance 1h klines + G041 룰 + 시뮬 portfolio.

실거래 X. 실시간 가격만 가져와서 G041 신호 발화/exit 시점/PnL 시뮬.
$55 capital, max 3 concurrent, 30% size, 1x perp.

매 시간 1회 실행 (스케줄):
  python paper_live.py

상태 영속: state.json (positions, history, equity)
    이력 영속: trades.jsonl (모든 진입·청산 이벤트)

운용:
  - 첫 실행: warm-up (30일 데이터 fetch + score 계산만, 진입 X)
  - 30일 이후: walk-forward gate 평가 → 조건 만족 시 진입
  - 매 시간 만료된 포지션 청산 시뮬 + recent net 갱신
"""
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

# G041 룰 import (PB001 CH1 score 함수 재사용)
sys.path.insert(0, str(Path(__file__).parent.parent / "_scripts"))
from g002_mingogogo_ch1_backtest import compute_ch1_score, COST_BPS_RT, atr_pct

UNIVERSE_18 = ["DOGEUSDT", "PEPEUSDT", "WIFUSDT", "ARBUSDT", "OPUSDT",
               "AVAXUSDT", "SUIUSDT", "ADAUSDT", "APTUSDT", "BNBUSDT",
               "DOTUSDT", "LINKUSDT", "LTCUSDT", "NEARUSDT", "SOLUSDT",
               "UNIUSDT", "XRPUSDT", "BTCUSDT"]

# === Config (G070 LOTTERY: thr80 + 5x lev + 24h hold) ===
EQUITY_USD = 55.0
SIZE_PCT = 0.30
LEVERAGE = 5.0  # G070: 5x — 사용자 명시 5-10x OK
MAX_CONCURRENT_BASE = 5
USE_DYNAMIC_CONC = False  # G070 단순 max5 (G058 dynamic 비활성)
ATR_VOL_GUARD_PCT = 8.0  # 변동성 너무 크면 skip — 5x liquidation 방지
LEVERAGE = 1.0
ENTRY_THRESHOLD = 80  # G070: thr80 (lottery whale)
HOLD_BARS = 24        # G070: 24h hold (단기 + 5x lev 안전)
LOOKBACK_DAYS = 14    # adaptive gate
TIMEFRAME = "1h"
KLINE_LIMIT = 500  # 500 bars = ~21일 (충분히 indicator warmup)
# Binance public spot klines API (인증 없음, 무료)
BINANCE_BASE = "https://api.binance.com/api/v3/klines"

ROOT = Path(__file__).parent
STATE_PATH = ROOT / "paper_live_state.json"
TRADES_PATH = ROOT / "paper_live_trades.jsonl"
LOG_PATH = ROOT / "paper_live.log"


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def fetch_klines(symbol, tf="1h", limit=500):
    """Binance public klines (인증 X, rate limit 1200 req/min)."""
    url = f"{BINANCE_BASE}?symbol={symbol}&interval={tf}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    df = pd.DataFrame(data, columns=[
        "open_time", "open_price", "high_price", "low_price", "close_price",
        "base_volume", "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])
    for c in ("open_price", "high_price", "low_price", "close_price", "base_volume", "quote_volume"):
        df[c] = df[c].astype(float)
    df["open_time"] = df["open_time"].astype("int64")
    return df[["open_time", "open_price", "high_price", "low_price", "close_price", "base_volume", "quote_volume"]]


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "equity_usd": EQUITY_USD,
        "open_positions": [],   # [{sym, entry_ts, entry_price, exit_ts_planned, size_usd, score}]
        "closed_history": [],   # [{sym, entry_ts, exit_ts, entry_price, exit_price, size_usd, gross_bps, net_bps, score}]
        "cycles_run": 0,
        "warmup_complete": False,
    }


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def append_trade(event):
    with open(TRADES_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def adaptive_gate_active(state, now_ts):
    """직전 30일 net 양수면 진입 허용. warmup 중에는 모두 허용."""
    if not state["warmup_complete"]:
        # warmup: started_at 후 30일 경과 여부
        started = datetime.fromisoformat(state["started_at"]).timestamp() * 1000
        if now_ts - started < LOOKBACK_DAYS * 86400 * 1000:
            return True, "warmup"
        state["warmup_complete"] = True
    cutoff = now_ts - LOOKBACK_DAYS * 86400 * 1000
    recent = [h for h in state["closed_history"] if h["exit_ts"] >= cutoff]
    if not recent:
        return True, "no_recent_history"
    total_net = sum(h["net_bps"] for h in recent)
    return total_net > 0, f"recent_30d_net={total_net:.0f}bps"


def cycle():
    state = load_state()
    state["cycles_run"] += 1
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp() * 1000)
    log(f"=== cycle {state['cycles_run']} @ {now.isoformat()} ===")

    # 1. 만료된 포지션 청산
    still_open = []
    for pos in state["open_positions"]:
        if now_ts >= pos["exit_ts_planned"]:
            # 현 가격 fetch
            try:
                df = fetch_klines(pos["sym"], TIMEFRAME, 5)
                exit_price = float(df["close_price"].iloc[-1])
            except Exception as e:
                log(f"  EXIT fetch failed for {pos['sym']}: {e}, will retry next cycle")
                still_open.append(pos)
                continue
            gross_bps = (exit_price / pos["entry_price"] - 1) * 10000
            net_bps = gross_bps - COST_BPS_RT
            pnl_usd = pos["size_usd"] * net_bps / 10000
            state["equity_usd"] += pnl_usd
            closed = {
                "sym": pos["sym"],
                "entry_ts": pos["entry_ts"],
                "exit_ts": now_ts,
                "entry_price": pos["entry_price"],
                "exit_price": exit_price,
                "size_usd": pos["size_usd"],
                "gross_bps": round(gross_bps, 2),
                "net_bps": round(net_bps, 2),
                "pnl_usd": round(pnl_usd, 4),
                "score": pos.get("score"),
            }
            state["closed_history"].append(closed)
            append_trade({"event": "EXIT", **closed})
            log(f"  EXIT {pos['sym']} @ {exit_price:.6f} → net {net_bps:+.0f}bps PnL ${pnl_usd:+.3f}")
        else:
            still_open.append(pos)
    state["open_positions"] = still_open

    # 2. Adaptive gate 평가
    gate_active, gate_reason = adaptive_gate_active(state, now_ts)
    log(f"  gate: {'ACTIVE' if gate_active else 'PAUSED'} ({gate_reason})")
    if not gate_active:
        save_state(state)
        log(f"  [paused] equity=${state['equity_usd']:.2f}, open={len(state['open_positions'])}, history={len(state['closed_history'])}")
        return

    # 3. 신규 진입 검토
    # G058 dynamic concurrency: 직전 7일 net 기반
    if USE_DYNAMIC_CONC and state["closed_history"]:
        cutoff_7d = now_ts - 7 * 86400 * 1000
        recent_7d = [h for h in state["closed_history"] if h["exit_ts"] >= cutoff_7d]
        recent_7d_sum = sum(h["net_bps"] for h in recent_7d) if recent_7d else 0
        if recent_7d_sum > 2000:
            current_max_conc = 8  # hot regime
        elif recent_7d_sum > 0:
            current_max_conc = MAX_CONCURRENT_BASE  # normal
        else:
            current_max_conc = 3  # cold
        log(f"  G058 dynamic conc: recent_7d_net={recent_7d_sum:+.0f}bps → max_conc={current_max_conc}")
    else:
        current_max_conc = MAX_CONCURRENT_BASE

    open_syms = {p["sym"] for p in state["open_positions"]}
    candidates = []
    for sym in UNIVERSE_18:
        if sym in open_syms: continue
        if len(state["open_positions"]) + len(candidates) >= current_max_conc: break
        try:
            df = fetch_klines(sym, TIMEFRAME, KLINE_LIMIT)
        except Exception as e:
            log(f"  fetch fail {sym}: {e}")
            continue
        if len(df) < 100: continue
        score, _ = compute_ch1_score(df)
        df["score"] = score
        last = df.iloc[-1]
        if pd.isna(last["score"]) or last["score"] < ENTRY_THRESHOLD: continue
        # ATR volatility guard (G070 5x lev liquidation 방지)
        a = atr_pct(df["high_price"], df["low_price"], df["close_price"], 14)
        if not pd.isna(a.iloc[-1]) and a.iloc[-1] > ATR_VOL_GUARD_PCT:
            log(f"  SKIP {sym} score={last['score']:.1f} but atr_pct={a.iloc[-1]:.1f} > {ATR_VOL_GUARD_PCT} — vol too high")
            continue
        candidates.append((sym, float(last["score"]), float(last["close_price"]), int(last["open_time"])))

    # score 기준 내림차순 (최우선)
    candidates.sort(key=lambda x: -x[1])
    for sym, sc, price, ts in candidates:
        if len(state["open_positions"]) >= current_max_conc: break
        # G070: notional = margin × leverage. margin = SIZE_PCT × equity
        margin_usd = state["equity_usd"] * SIZE_PCT
        size_usd = margin_usd * LEVERAGE  # notional
        pos = {
            "sym": sym,
            "entry_ts": ts,
            "entry_price": price,
            "exit_ts_planned": ts + HOLD_BARS * 3600 * 1000,
            "size_usd": round(size_usd, 4),
            "score": round(sc, 1),
        }
        state["open_positions"].append(pos)
        append_trade({"event": "ENTRY", **pos})
        log(f"  ENTRY {sym} @ {price:.6f} score={sc:.1f} size=${size_usd:.2f}")

    # 4. status
    save_state(state)
    closed_n = len(state["closed_history"])
    total_pnl = sum(h["pnl_usd"] for h in state["closed_history"])
    wins = sum(1 for h in state["closed_history"] if h["net_bps"] > 0)
    log(f"  STATUS equity=${state['equity_usd']:.2f} open={len(state['open_positions'])} closed={closed_n} wins={wins} totalPnL=${total_pnl:+.3f}")


def main():
    cycle()


if __name__ == "__main__":
    main()
