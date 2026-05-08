#!/usr/bin/env python3
"""Deploy non-CH1 breakout paper emulators to Oracle.

This is intentionally separate from the CH1/Mingogogo deploy scripts. G4006 and
G4007 use a 24h-high breakout signal, so reusing a CH1 runtime would create
strategy-to-runtime drift.

Default SSH alias: g185.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import pathlib
import subprocess
import sys
import textwrap
from typing import Any


STRATEGIES_TO_COMPARE = [
    "G185",
    "G186",
    "G187",
    "G188",
    "G189",
    "G190",
    "G191",
    "G192",
    "G210",
    "G220",
    "G801",
    "G802",
    "G914",
    "G1165",
    "G1995",
    "G4006",
    "G4007",
    "G4692",
]

NO_DEAD_RUNTIME_UNIVERSE = [
    "DOGEUSDT",
    "PEPEUSDT",
    "ARBUSDT",
    "OPUSDT",
    "AVAXUSDT",
    "SUIUSDT",
    "ADAUSDT",
    "APTUSDT",
    "BNBUSDT",
    "DOTUSDT",
    "LINKUSDT",
    "NEARUSDT",
    "SOLUSDT",
    "UNIUSDT",
    "XRPUSDT",
]

G4007_TOP8_LATEST = [
    "AVAXUSDT",
    "DOTUSDT",
    "ETHUSDT",
    "MATICUSDT",
    "NEARUSDT",
    "SOLUSDT",
    "SUIUSDT",
    "XRPUSDT",
]

COMMON_PARAMS: dict[str, Any] = {
    "equity_usd": 100.0,
    "leverage": 8.0,
    "size_pct_per_trade": 0.20,
    "max_concurrent": 5,
    "hold_bars": 36,
    "breakout_lookback_bars": 24,
    "break_bps": 50.0,
    "min_ret_24h": 0.10,
    "min_vol_ratio": 3.0,
    "atr_period": 14,
    "atr_min_pct": 0.0,
    "atr_max_pct": 8.0,
    "take_profit_pct": 0.06,
    "stop_loss_pct": 0.08,
    "cost_bps_round_trip": 24.0,
    "cycle_seconds": 300,
    "kline_limit": 200,
    "exchange": "bitget",
    "market": "futures",
    "product_type": "USDT-FUTURES",
    "granularity": "1H",
    "kline_interval_ms": 60 * 60 * 1000,
    "kline_base_url": "https://api.bitget.com/api/v2/mix/market/history-candles",
}

STRATEGY_CONFIGS: dict[str, dict[str, Any]] = {
    "G4006": {
        **COMMON_PARAMS,
        "sid": "G4006",
        "name": "breakout_long_raw",
        "paper_only": True,
        "universe": NO_DEAD_RUNTIME_UNIVERSE,
        "symbol_filter": "none",
    },
    "G4007": {
        **COMMON_PARAMS,
        "sid": "G4007",
        "name": "breakout_long_top8_symbols",
        "paper_only": True,
        "universe": G4007_TOP8_LATEST,
        "symbol_filter": "latest_walk_forward_top8",
        "runtime_note": "Skip exchange-unavailable symbols and record fetch_errors.",
    },
    "G4692": {
        **COMMON_PARAMS,
        "sid": "G4692",
        "name": "watch_confirm_breakout_mid",
        "paper_only": True,
        "strategy_type": "watch_confirm_breakout",
        "universe": NO_DEAD_RUNTIME_UNIVERSE,
        "symbol_filter": "none",
        "strict_immediate": {
            "breakout_lookback_bars": 24,
            "break_bps": 50.0,
            "min_ret_24h": 0.10,
            "min_vol_ratio": 3.0,
            "atr_min_pct": 0.0,
            "atr_max_pct": 8.0,
            "hold_bars": 36,
            "leverage": 8.0,
            "size_pct_per_trade": 0.20,
            "take_profit_pct": 0.06,
            "stop_loss_pct": 0.08,
        },
        "watch_state": {
            "breakout_lookback_bars": 24,
            "break_bps": 30.0,
            "min_ret_24h": 0.08,
            "min_vol_ratio": 2.5,
            "atr_min_pct": 0.0,
            "atr_max_pct": 8.0,
        },
        "confirmation_entry": {
            "max_lag_bars": 1,
            "confirm_break_bps": 50.0,
            "min_follow_bps": 0.0,
            "min_ret_24h": 0.10,
            "min_vol_ratio": 3.0,
            "failure_bps": 0.0,
            "hold_bars": 24,
            "leverage": 7.0,
            "size_pct_per_trade": 0.16,
            "take_profit_pct": 0.05,
            "stop_loss_pct": 0.065,
        },
    },
}

SSH_OPTIONS = [
    "-o",
    "ControlMaster=no",
    "-o",
    "ControlPath=none",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=20",
]


REMOTE_STATUS_PROBE = r"""
import json
import pathlib
import subprocess

strategies = %s
home = pathlib.Path.home()

def service_status(lower):
    proc = subprocess.run(
        ["systemctl", "--user", "is-active", f"{lower}-emulator.service"],
        text=True,
        capture_output=True,
    )
    out = (proc.stdout or proc.stderr or "").strip()
    return out or "unknown"

def as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

for sid in strategies:
    lower = sid.lower()
    state_path = home / lower / "runtime" / "state.json"
    rec = {
        "sid": sid,
        "service": service_status(lower),
        "state_exists": state_path.exists(),
        "state_path": str(state_path),
        "cumulative_pnl_usd": None,
        "closed_count": 0,
        "open_count": 0,
        "last_error": None,
    }
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            rec["cumulative_pnl_usd"] = as_float(
                state.get("cumulative_pnl_usd")
                or state.get("total_pnl_usd")
                or state.get("realized_pnl_usd")
                or state.get("stats", {}).get("cumulative_pnl_usd")
                or state.get("stats", {}).get("total_pnl_usd")
            )
            closed = state.get("closed_trades")
            rec["closed_count"] = len(closed) if isinstance(closed, list) else int(
                state.get("closed_count") or state.get("closed_trades_count") or 0
            )
            rec["open_count"] = len(state.get("positions") or {})
            rec["updated_at"] = state.get("updated_at") or state.get("last_heartbeat")
            rec["last_error"] = state.get("last_error")
        except Exception as exc:
            rec["last_error"] = repr(exc)
    print(json.dumps(rec, sort_keys=True))
"""


REMOTE_EMULATOR_TEMPLATE = r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import pathlib
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone


CONFIG = json.loads("""__CONFIG_JSON__""")
SID = CONFIG["sid"]
UNIVERSE = CONFIG["universe"]

BASE_DIR = pathlib.Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / "runtime"
STATE_PATH = RUNTIME_DIR / "state.json"
LOG_PATH = RUNTIME_DIR / "events.jsonl"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state() -> dict:
    return {
        "sid": SID,
        "mode": "paper",
        "paper_only": True,
        "engine": "breakout_long",
        "started_at": now_iso(),
        "updated_at": now_iso(),
        "params": CONFIG,
        "positions": {},
        "closed_trades": [],
        "last_entry_bar_by_symbol": {},
        "fetch_errors": {},
        "signals_seen": 0,
        "cumulative_pnl_usd": 0.0,
        "equity_usd": CONFIG["equity_usd"],
        "heartbeats": 0,
        "last_error": None,
    }


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
            state.setdefault("positions", {})
            state.setdefault("closed_trades", [])
            state.setdefault("last_entry_bar_by_symbol", {})
            state.setdefault("fetch_errors", {})
            state.setdefault("signals_seen", 0)
            state.setdefault("cumulative_pnl_usd", 0.0)
            state.setdefault("equity_usd", CONFIG["equity_usd"])
            return state
        except Exception:
            pass
    return default_state()


def save_state(state: dict) -> None:
    state["updated_at"] = now_iso()
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def event(kind: str, payload: dict) -> None:
    rec = {"ts": now_iso(), "sid": SID, "kind": kind, **payload}
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def fetch_klines(symbol: str, limit: int | None = None, completed_only: bool = True) -> list[dict]:
    limit = limit or int(CONFIG["kline_limit"])
    params = urllib.parse.urlencode(
        {
            "symbol": symbol,
            "granularity": CONFIG["granularity"],
            "limit": str(limit),
            "productType": CONFIG["product_type"],
        }
    )
    url = f'{CONFIG["kline_base_url"]}?{params}'
    with urllib.request.urlopen(url, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("code") != "00000":
        raise RuntimeError(f"Bitget kline error for {symbol}: {payload!r}")
    rows = payload.get("data") or []

    now_ms = int(time.time() * 1000)
    out = []
    for row in rows:
        open_time = int(row[0])
        close_time = open_time + int(CONFIG["kline_interval_ms"]) - 1
        if completed_only and close_time >= now_ms:
            continue
        out.append(
            {
                "open_time": open_time,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "base_volume": float(row[5]),
                "quote_volume": float(row[6]),
                "close_time": close_time,
            }
        )
    out.sort(key=lambda item: item["open_time"])
    return out


def atr_pct(rows: list[dict], period: int) -> float | None:
    if len(rows) < period + 1:
        return None
    trs = []
    for idx in range(1, len(rows)):
        cur = rows[idx]
        prev = rows[idx - 1]
        tr = max(
            cur["high"] - cur["low"],
            abs(cur["high"] - prev["close"]),
            abs(cur["low"] - prev["close"]),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    atr = sum(trs[-period:]) / period
    close = rows[-1]["close"]
    if close <= 0:
        return None
    return atr / close * 100.0


def breakout_signal(symbol: str, rows: list[dict]) -> dict | None:
    lookback = int(CONFIG["breakout_lookback_bars"])
    if len(rows) < max(lookback + 25, 55):
        return None

    latest = rows[-1]
    previous_window = rows[-lookback - 1 : -1]
    previous_high = max(row["high"] for row in previous_window)
    close = latest["close"]
    breakout_level = previous_high * (1.0 + float(CONFIG["break_bps"]) / 10000.0)
    ret_24h = close / rows[-25]["close"] - 1.0
    prior_vols = [row["quote_volume"] for row in rows[-49:-1] if row["quote_volume"] > 0]
    if not prior_vols:
        return None
    median_vol = statistics.median(prior_vols)
    vol_ratio = latest["quote_volume"] / median_vol if median_vol > 0 else 0.0
    atr = atr_pct(rows, int(CONFIG["atr_period"]))
    if atr is None:
        return None

    if close <= breakout_level:
        return None
    if ret_24h < float(CONFIG["min_ret_24h"]):
        return None
    if vol_ratio < float(CONFIG["min_vol_ratio"]):
        return None
    if atr < float(CONFIG["atr_min_pct"]) or atr > float(CONFIG["atr_max_pct"]):
        return None

    strength = (close / breakout_level - 1.0) * 10000.0
    score = strength + ret_24h * 100.0 + math.log(max(vol_ratio, 1.0)) * 10.0
    return {
        "symbol": symbol,
        "bar_open_time": latest["open_time"],
        "bar_close_time": latest["close_time"],
        "entry_price": close,
        "previous_high": previous_high,
        "breakout_level": breakout_level,
        "ret_24h": ret_24h,
        "vol_ratio": vol_ratio,
        "atr_pct": atr,
        "score": score,
    }


def close_position(state: dict, symbol: str, pos: dict, exit_price: float, reason: str, bar: dict) -> None:
    margin = float(pos["margin_usd"])
    gross_pnl = margin * ((exit_price / float(pos["entry_price"]) - 1.0) * float(CONFIG["leverage"]))
    cost = margin * float(CONFIG["cost_bps_round_trip"]) / 10000.0
    pnl = gross_pnl - cost
    rec = {
        **pos,
        "exit_ts": now_iso(),
        "exit_bar_open_time": bar["open_time"],
        "exit_price": exit_price,
        "exit_reason": reason,
        "gross_pnl_usd": round(gross_pnl, 6),
        "cost_usd": round(cost, 6),
        "pnl_usd": round(pnl, 6),
    }
    state["closed_trades"].append(rec)
    state["cumulative_pnl_usd"] = round(float(state.get("cumulative_pnl_usd", 0.0)) + pnl, 6)
    state["equity_usd"] = round(float(state.get("equity_usd", CONFIG["equity_usd"])) + pnl, 6)
    state["positions"].pop(symbol, None)
    event("close", {"symbol": symbol, "reason": reason, "exit_price": exit_price, "pnl_usd": round(pnl, 6)})


def update_exits(state: dict) -> None:
    for symbol, pos in list(state["positions"].items()):
        try:
            rows = fetch_klines(symbol, limit=max(int(CONFIG["hold_bars"]) + 8, 80), completed_only=True)
        except Exception as exc:
            state["fetch_errors"][symbol] = {"ts": now_iso(), "stage": "exit", "error": repr(exc)}
            continue
        entry_bar = int(pos["entry_bar_open_time"])
        path = [row for row in rows if row["open_time"] > entry_bar]
        if not path:
            continue

        entry = float(pos["entry_price"])
        take = entry * (1.0 + float(CONFIG["take_profit_pct"]))
        stop = entry * (1.0 - float(CONFIG["stop_loss_pct"]))
        for idx, bar in enumerate(path, start=1):
            if bar["low"] <= stop:
                close_position(state, symbol, pos, stop, "stop_loss", bar)
                break
            if bar["high"] >= take:
                close_position(state, symbol, pos, take, "take_profit", bar)
                break
            if idx >= int(CONFIG["hold_bars"]):
                close_position(state, symbol, pos, bar["close"], "time_exit", bar)
                break


def open_positions(state: dict) -> None:
    open_slots = int(CONFIG["max_concurrent"]) - len(state["positions"])
    if open_slots <= 0:
        return

    signals = []
    for symbol in UNIVERSE:
        if symbol in state["positions"]:
            continue
        try:
            rows = fetch_klines(symbol, completed_only=True)
            signal = breakout_signal(symbol, rows)
        except Exception as exc:
            state["fetch_errors"][symbol] = {"ts": now_iso(), "stage": "signal", "error": repr(exc)}
            continue
        if not signal:
            continue
        last_entry_bar = state["last_entry_bar_by_symbol"].get(symbol)
        if last_entry_bar == signal["bar_open_time"]:
            continue
        signals.append(signal)

    signals.sort(key=lambda item: item["score"], reverse=True)
    state["signals_seen"] = int(state.get("signals_seen", 0)) + len(signals)
    for signal in signals[:open_slots]:
        symbol = signal["symbol"]
        margin = float(CONFIG["equity_usd"]) * float(CONFIG["size_pct_per_trade"])
        pos = {
            "symbol": symbol,
            "side": "long",
            "entry_ts": now_iso(),
            "entry_bar_open_time": signal["bar_open_time"],
            "entry_bar_close_time": signal["bar_close_time"],
            "entry_price": signal["entry_price"],
            "margin_usd": margin,
            "notional_usd": margin * float(CONFIG["leverage"]),
            "leverage": float(CONFIG["leverage"]),
            "signal": signal,
        }
        state["positions"][symbol] = pos
        state["last_entry_bar_by_symbol"][symbol] = signal["bar_open_time"]
        event("open", {"symbol": symbol, "entry_price": signal["entry_price"], "signal": signal})


def cycle_once(state: dict) -> None:
    update_exits(state)
    open_positions(state)
    state["heartbeats"] = int(state.get("heartbeats", 0)) + 1
    state["last_error"] = None
    save_state(state)


def main() -> None:
    state = load_state()
    event("startup", {"config": CONFIG})
    while True:
        try:
            cycle_once(state)
        except Exception as exc:
            state["last_error"] = repr(exc)
            save_state(state)
            event("error", {"error": repr(exc)})
        time.sleep(float(CONFIG["cycle_seconds"]))


if __name__ == "__main__":
    main()
'''


REMOTE_WATCH_CONFIRM_TEMPLATE = r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import pathlib
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone


CONFIG = json.loads("""__CONFIG_JSON__""")
SID = CONFIG["sid"]
UNIVERSE = CONFIG["universe"]

BASE_DIR = pathlib.Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / "runtime"
STATE_PATH = RUNTIME_DIR / "state.json"
LOG_PATH = RUNTIME_DIR / "events.jsonl"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state() -> dict:
    return {
        "sid": SID,
        "mode": "paper",
        "paper_only": True,
        "engine": "watch_confirm_breakout",
        "started_at": now_iso(),
        "updated_at": now_iso(),
        "params": CONFIG,
        "positions": {},
        "closed_trades": [],
        "watch_states": {},
        "last_entry_bar_by_symbol": {},
        "last_watch_bar_by_symbol": {},
        "fetch_errors": {},
        "signals_seen": 0,
        "watches_seen": 0,
        "confirmations_seen": 0,
        "cumulative_pnl_usd": 0.0,
        "equity_usd": CONFIG["equity_usd"],
        "heartbeats": 0,
        "last_error": None,
    }


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
            state.setdefault("positions", {})
            state.setdefault("closed_trades", [])
            state.setdefault("watch_states", {})
            state.setdefault("last_entry_bar_by_symbol", {})
            state.setdefault("last_watch_bar_by_symbol", {})
            state.setdefault("fetch_errors", {})
            state.setdefault("signals_seen", 0)
            state.setdefault("watches_seen", 0)
            state.setdefault("confirmations_seen", 0)
            state.setdefault("cumulative_pnl_usd", 0.0)
            state.setdefault("equity_usd", CONFIG["equity_usd"])
            return state
        except Exception:
            pass
    return default_state()


def save_state(state: dict) -> None:
    state["updated_at"] = now_iso()
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def event(kind: str, payload: dict) -> None:
    rec = {"ts": now_iso(), "sid": SID, "kind": kind, **payload}
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def fetch_klines(symbol: str, limit: int | None = None, completed_only: bool = True) -> list[dict]:
    limit = limit or int(CONFIG["kline_limit"])
    params = urllib.parse.urlencode(
        {
            "symbol": symbol,
            "granularity": CONFIG["granularity"],
            "limit": str(limit),
            "productType": CONFIG["product_type"],
        }
    )
    url = f'{CONFIG["kline_base_url"]}?{params}'
    with urllib.request.urlopen(url, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("code") != "00000":
        raise RuntimeError(f"Bitget kline error for {symbol}: {payload!r}")
    rows = payload.get("data") or []

    now_ms = int(time.time() * 1000)
    out = []
    for row in rows:
        open_time = int(row[0])
        close_time = open_time + int(CONFIG["kline_interval_ms"]) - 1
        if completed_only and close_time >= now_ms:
            continue
        out.append(
            {
                "open_time": open_time,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "base_volume": float(row[5]),
                "quote_volume": float(row[6]),
                "close_time": close_time,
            }
        )
    out.sort(key=lambda item: item["open_time"])
    return out


def atr_pct_at(rows: list[dict], idx: int, period: int) -> float | None:
    if idx < period:
        return None
    trs = []
    for cur_idx in range(max(1, idx - period + 1), idx + 1):
        cur = rows[cur_idx]
        prev = rows[cur_idx - 1]
        trs.append(
            max(
                cur["high"] - cur["low"],
                abs(cur["high"] - prev["close"]),
                abs(cur["low"] - prev["close"]),
            )
        )
    if len(trs) < period:
        return None
    close = rows[idx]["close"]
    return (sum(trs[-period:]) / period) / close * 100.0 if close > 0 else None


def metrics_at(rows: list[dict], idx: int, lookback: int) -> dict | None:
    if idx < max(lookback + 1, 49):
        return None
    row = rows[idx]
    prev_window = rows[idx - lookback : idx]
    previous_high = max(item["high"] for item in prev_window)
    ret_24h = row["close"] / rows[idx - 24]["close"] - 1.0
    prior_vols = [item["quote_volume"] for item in rows[idx - 48 : idx] if item["quote_volume"] > 0]
    if not prior_vols:
        return None
    median_vol = statistics.median(prior_vols)
    vol_ratio = row["quote_volume"] / median_vol if median_vol > 0 else 0.0
    atr = atr_pct_at(rows, idx, int(CONFIG["atr_period"]))
    if atr is None:
        return None
    return {
        "symbol_bar_open_time": row["open_time"],
        "bar_close_time": row["close_time"],
        "open": row["open"],
        "high": row["high"],
        "low": row["low"],
        "close": row["close"],
        "previous_high": previous_high,
        "ret_24h": ret_24h,
        "vol_ratio": vol_ratio,
        "atr_pct": atr,
    }


def passes_breakout(metrics: dict, cfg: dict) -> bool:
    level = metrics["previous_high"] * (1.0 + float(cfg["break_bps"]) / 10000.0)
    return (
        metrics["close"] > level
        and metrics["ret_24h"] >= float(cfg["min_ret_24h"])
        and metrics["vol_ratio"] >= float(cfg["min_vol_ratio"])
        and float(cfg["atr_min_pct"]) <= metrics["atr_pct"] <= float(cfg["atr_max_pct"])
    )


def strict_signal(symbol: str, rows: list[dict], idx: int) -> dict | None:
    cfg = CONFIG["strict_immediate"]
    metrics = metrics_at(rows, idx, int(cfg["breakout_lookback_bars"]))
    if not metrics or not passes_breakout(metrics, cfg):
        return None
    level = metrics["previous_high"] * (1.0 + float(cfg["break_bps"]) / 10000.0)
    strength = (metrics["close"] / level - 1.0) * 10000.0
    score = strength + metrics["ret_24h"] * 100.0 + math.log(max(metrics["vol_ratio"], 1.0)) * 10.0
    return {
        "symbol": symbol,
        "engine": "strict_breakout",
        "bar_open_time": metrics["symbol_bar_open_time"],
        "bar_close_time": metrics["bar_close_time"],
        "entry_price": metrics["close"],
        "previous_high": metrics["previous_high"],
        "breakout_level": level,
        "ret_24h": metrics["ret_24h"],
        "vol_ratio": metrics["vol_ratio"],
        "atr_pct": metrics["atr_pct"],
        "score": score,
        "hold_bars": int(cfg["hold_bars"]),
        "leverage": float(cfg["leverage"]),
        "size_pct_per_trade": float(cfg["size_pct_per_trade"]),
        "take_profit_pct": float(cfg["take_profit_pct"]),
        "stop_loss_pct": float(cfg["stop_loss_pct"]),
    }


def watch_signal(symbol: str, rows: list[dict], idx: int) -> dict | None:
    cfg = CONFIG["watch_state"]
    metrics = metrics_at(rows, idx, int(cfg["breakout_lookback_bars"]))
    if not metrics or not passes_breakout(metrics, cfg):
        return None
    if strict_signal(symbol, rows, idx) is not None:
        return None
    level = metrics["previous_high"] * (1.0 + float(cfg["break_bps"]) / 10000.0)
    failure_level = metrics["previous_high"] * (
        1.0 + float(CONFIG["confirmation_entry"]["failure_bps"]) / 10000.0
    )
    return {
        "symbol": symbol,
        "watch_ts": now_iso(),
        "watch_bar_open_time": metrics["symbol_bar_open_time"],
        "watch_bar_close_time": metrics["bar_close_time"],
        "watch_close": metrics["close"],
        "previous_high": metrics["previous_high"],
        "watch_level": level,
        "failure_level": failure_level,
        "ret_24h": metrics["ret_24h"],
        "vol_ratio": metrics["vol_ratio"],
        "atr_pct": metrics["atr_pct"],
        "expires_after_bar_open_time": metrics["symbol_bar_open_time"]
        + int(CONFIG["confirmation_entry"]["max_lag_bars"]) * int(CONFIG["kline_interval_ms"]),
    }


def confirmation_signal(symbol: str, watch: dict, rows: list[dict]) -> tuple[dict | None, str | None]:
    cfg = CONFIG["confirmation_entry"]
    watch_bar = int(watch["watch_bar_open_time"])
    candidates = [idx for idx, row in enumerate(rows) if row["open_time"] > watch_bar]
    if not candidates:
        return None, None
    max_lag = int(cfg["max_lag_bars"])
    for lag, idx in enumerate(candidates[:max_lag], start=1):
        metrics = metrics_at(rows, idx, int(CONFIG["strict_immediate"]["breakout_lookback_bars"]))
        if metrics is None:
            continue
        if metrics["close"] < float(watch["failure_level"]):
            return None, "failed"
        target = float(watch["previous_high"]) * (1.0 + float(cfg["confirm_break_bps"]) / 10000.0)
        follow = float(watch["watch_close"]) * (1.0 + float(cfg["min_follow_bps"]) / 10000.0)
        ok = (
            metrics["close"] > target
            and metrics["close"] >= follow
            and metrics["ret_24h"] >= float(cfg["min_ret_24h"])
            and metrics["vol_ratio"] >= float(cfg["min_vol_ratio"])
            and float(CONFIG["strict_immediate"]["atr_min_pct"]) <= metrics["atr_pct"] <= float(CONFIG["strict_immediate"]["atr_max_pct"])
        )
        if ok:
            strength = (metrics["close"] / max(target, follow) - 1.0) * 10000.0
            score = strength + metrics["ret_24h"] * 100.0 + math.log(max(metrics["vol_ratio"], 1.0)) * 10.0
            return {
                "symbol": symbol,
                "engine": "watch_confirm",
                "watch": watch,
                "confirm_lag": lag,
                "bar_open_time": metrics["symbol_bar_open_time"],
                "bar_close_time": metrics["bar_close_time"],
                "entry_price": metrics["close"],
                "previous_high": metrics["previous_high"],
                "breakout_level": target,
                "ret_24h": metrics["ret_24h"],
                "vol_ratio": metrics["vol_ratio"],
                "atr_pct": metrics["atr_pct"],
                "score": score,
                "hold_bars": int(cfg["hold_bars"]),
                "leverage": float(cfg["leverage"]),
                "size_pct_per_trade": float(cfg["size_pct_per_trade"]),
                "take_profit_pct": float(cfg["take_profit_pct"]),
                "stop_loss_pct": float(cfg["stop_loss_pct"]),
            }, None
    latest_bar = rows[-1]["open_time"] if rows else 0
    if latest_bar > int(watch["expires_after_bar_open_time"]):
        return None, "expired"
    return None, None


def close_position(state: dict, symbol: str, pos: dict, exit_price: float, reason: str, bar: dict) -> None:
    margin = float(pos["margin_usd"])
    leverage = float(pos.get("leverage", CONFIG["leverage"]))
    gross_pnl = margin * ((exit_price / float(pos["entry_price"]) - 1.0) * leverage)
    cost = margin * float(CONFIG["cost_bps_round_trip"]) / 10000.0
    pnl = gross_pnl - cost
    rec = {
        **pos,
        "exit_ts": now_iso(),
        "exit_bar_open_time": bar["open_time"],
        "exit_price": exit_price,
        "exit_reason": reason,
        "gross_pnl_usd": round(gross_pnl, 6),
        "cost_usd": round(cost, 6),
        "pnl_usd": round(pnl, 6),
    }
    state["closed_trades"].append(rec)
    state["cumulative_pnl_usd"] = round(float(state.get("cumulative_pnl_usd", 0.0)) + pnl, 6)
    state["equity_usd"] = round(float(state.get("equity_usd", CONFIG["equity_usd"])) + pnl, 6)
    state["positions"].pop(symbol, None)
    event("close", {"symbol": symbol, "reason": reason, "exit_price": exit_price, "pnl_usd": round(pnl, 6)})


def update_exits(state: dict) -> None:
    for symbol, pos in list(state["positions"].items()):
        try:
            rows = fetch_klines(symbol, limit=max(int(pos.get("hold_bars", 36)) + 8, 80), completed_only=True)
            state["fetch_errors"].pop(symbol, None)
        except Exception as exc:
            state["fetch_errors"][symbol] = {"ts": now_iso(), "stage": "exit", "error": repr(exc)}
            continue
        entry_bar = int(pos["entry_bar_open_time"])
        path = [row for row in rows if row["open_time"] > entry_bar]
        if not path:
            continue

        entry = float(pos["entry_price"])
        take = entry * (1.0 + float(pos["take_profit_pct"]))
        stop = entry * (1.0 - float(pos["stop_loss_pct"]))
        for idx, bar in enumerate(path, start=1):
            if bar["low"] <= stop:
                close_position(state, symbol, pos, stop, "stop_loss", bar)
                break
            if bar["high"] >= take:
                close_position(state, symbol, pos, take, "take_profit", bar)
                break
            if idx >= int(pos["hold_bars"]):
                close_position(state, symbol, pos, bar["close"], "time_exit", bar)
                break


def open_signal(state: dict, signal: dict) -> None:
    symbol = signal["symbol"]
    if symbol in state["positions"]:
        return
    if state["last_entry_bar_by_symbol"].get(symbol) == signal["bar_open_time"]:
        return
    margin = float(CONFIG["equity_usd"]) * float(signal["size_pct_per_trade"])
    pos = {
        "symbol": symbol,
        "side": "long",
        "engine": signal["engine"],
        "entry_ts": now_iso(),
        "entry_bar_open_time": signal["bar_open_time"],
        "entry_bar_close_time": signal["bar_close_time"],
        "entry_price": signal["entry_price"],
        "margin_usd": margin,
        "notional_usd": margin * float(signal["leverage"]),
        "leverage": float(signal["leverage"]),
        "hold_bars": int(signal["hold_bars"]),
        "take_profit_pct": float(signal["take_profit_pct"]),
        "stop_loss_pct": float(signal["stop_loss_pct"]),
        "signal": signal,
    }
    state["positions"][symbol] = pos
    state["last_entry_bar_by_symbol"][symbol] = signal["bar_open_time"]
    state["signals_seen"] = int(state.get("signals_seen", 0)) + 1
    if signal["engine"] == "watch_confirm":
        state["confirmations_seen"] = int(state.get("confirmations_seen", 0)) + 1
        state["watch_states"].pop(symbol, None)
    event("open", {"symbol": symbol, "entry_price": signal["entry_price"], "engine": signal["engine"], "signal": signal})


def process_confirmations(state: dict, rows_by_symbol: dict[str, list[dict]], slots: int) -> int:
    signals = []
    for symbol, watch in list(state["watch_states"].items()):
        rows = rows_by_symbol.get(symbol)
        if not rows:
            continue
        signal, terminal = confirmation_signal(symbol, watch, rows)
        if terminal:
            state["watch_states"].pop(symbol, None)
            event("watch_" + terminal, {"symbol": symbol, "watch": watch})
        if signal:
            signals.append(signal)
    signals.sort(key=lambda item: item["score"], reverse=True)
    opened = 0
    for signal in signals[:slots]:
        before = len(state["positions"])
        open_signal(state, signal)
        opened += int(len(state["positions"]) > before)
    return opened


def process_entries_and_watches(state: dict) -> None:
    rows_by_symbol: dict[str, list[dict]] = {}
    for symbol in UNIVERSE:
        try:
            rows_by_symbol[symbol] = fetch_klines(symbol, completed_only=True)
            state["fetch_errors"].pop(symbol, None)
        except Exception as exc:
            state["fetch_errors"][symbol] = {"ts": now_iso(), "stage": "fetch", "error": repr(exc)}

    slots = int(CONFIG["max_concurrent"]) - len(state["positions"])
    if slots > 0:
        opened = process_confirmations(state, rows_by_symbol, slots)
        slots -= opened
    if slots <= 0:
        return

    strict_signals = []
    new_watches = []
    for symbol, rows in rows_by_symbol.items():
        if len(rows) < 60 or symbol in state["positions"]:
            continue
        idx = len(rows) - 1
        sig = strict_signal(symbol, rows, idx)
        if sig and state["last_entry_bar_by_symbol"].get(symbol) != sig["bar_open_time"]:
            strict_signals.append(sig)
            continue
        watch = watch_signal(symbol, rows, idx)
        if watch and state["last_watch_bar_by_symbol"].get(symbol) != watch["watch_bar_open_time"]:
            new_watches.append(watch)

    strict_signals.sort(key=lambda item: item["score"], reverse=True)
    for signal in strict_signals[:slots]:
        before = len(state["positions"])
        open_signal(state, signal)
        slots -= int(len(state["positions"]) > before)
        if slots <= 0:
            break

    for watch in new_watches:
        symbol = watch["symbol"]
        state["watch_states"][symbol] = watch
        state["last_watch_bar_by_symbol"][symbol] = watch["watch_bar_open_time"]
        state["watches_seen"] = int(state.get("watches_seen", 0)) + 1
        event("watch_open", {"symbol": symbol, "watch": watch})


def cycle_once(state: dict) -> None:
    update_exits(state)
    process_entries_and_watches(state)
    state["heartbeats"] = int(state.get("heartbeats", 0)) + 1
    state["last_error"] = None
    save_state(state)


def main() -> None:
    state = load_state()
    event("startup", {"config": CONFIG})
    while True:
        try:
            cycle_once(state)
        except Exception as exc:
            state["last_error"] = repr(exc)
            save_state(state)
            event("error", {"error": repr(exc)})
        time.sleep(float(CONFIG["cycle_seconds"]))


if __name__ == "__main__":
    main()
'''


SERVICE_TEMPLATE = """[Unit]
Description={sid} breakout paper emulator
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/{sid_lower}
ExecStart=/usr/bin/python3 %h/{sid_lower}/{sid_lower}_breakout_emulator.py
Restart=always
RestartSec=20

[Install]
WantedBy=default.target
"""


def run(cmd: list[str], *, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd, input=input_text, text=True, check=check)


def ssh(host: str, remote_cmd: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["ssh", *SSH_OPTIONS, host, remote_cmd], check=check)


def remote_py_write(host: str, path: str, text: str, *, mode: int = 0o644) -> None:
    encoded = base64.b64encode(gzip.compress(text.encode("utf-8"))).decode("ascii")
    script = textwrap.dedent(
        f"""
        import base64
        import gzip
        import os
        import pathlib

        path = pathlib.Path({path!r}).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = gzip.decompress(base64.b64decode({encoded!r})).decode("utf-8")
        path.write_text(payload)
        os.chmod(path, {mode})
        """
    )
    ssh(host, "python3 - <<'PY'\n" + script + "PY")


def build_remote_emulator(config: dict[str, Any]) -> str:
    config_json = json.dumps(config, sort_keys=True)
    if config.get("strategy_type") == "watch_confirm_breakout":
        return REMOTE_WATCH_CONFIRM_TEMPLATE.replace("__CONFIG_JSON__", config_json)
    return REMOTE_EMULATOR_TEMPLATE.replace("__CONFIG_JSON__", config_json)


def status(host: str) -> int:
    probe = REMOTE_STATUS_PROBE % json.dumps(STRATEGIES_TO_COMPARE)
    proc = run(
        ["ssh", *SSH_OPTIONS, host, "python3 -"],
        input_text=probe,
        check=False,
    )
    return proc.returncode


def deploy_one(host: str, sid: str, *, start: bool) -> None:
    config = STRATEGY_CONFIGS[sid]
    lower = sid.lower()
    remote_dir = f"~/{lower}"
    runtime_dir = f"{remote_dir}/runtime"
    emulator_path = f"{remote_dir}/{lower}_breakout_emulator.py"
    service_path = f"~/.config/systemd/user/{lower}-emulator.service"

    ssh(host, f"mkdir -p {runtime_dir} ~/.config/systemd/user")
    remote_py_write(host, emulator_path, build_remote_emulator(config), mode=0o755)
    service = SERVICE_TEMPLATE.format(sid=sid, sid_lower=lower)
    remote_py_write(host, service_path, service, mode=0o644)

    ssh(host, "systemctl --user daemon-reload")
    ssh(host, f"systemctl --user enable {lower}-emulator.service")
    if start:
        ssh(host, f"systemctl --user restart {lower}-emulator.service")
    print(f"deployed {sid} to {host}:{remote_dir}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "strategy_ids",
        nargs="*",
        choices=sorted(STRATEGY_CONFIGS),
        default=sorted(STRATEGY_CONFIGS),
        help="Strategy IDs to deploy. Defaults to all breakout strategies.",
    )
    parser.add_argument("--host", default="g185", help="SSH host alias for Oracle.")
    parser.add_argument("--status-only", action="store_true", help="Only print remote paper-service status.")
    parser.add_argument("--no-start", action="store_true", help="Install files and service units without restart/start.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.status_only:
        return status(args.host)

    for sid in args.strategy_ids:
        deploy_one(args.host, sid, start=not args.no_start)
    return status(args.host)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
