#!/usr/bin/env python3
"""Deploy G7835 combined high-WR sleeve paper emulator to Oracle.

G7835 is the portfolio-level paper candidate from:
- G090 hour-filter CH1 long sleeve
- G805740 balanced negative-squeeze funding long
- G827758 balanced positive-follow funding long

Before deploying, this script can disable one active paper service that has
heartbeats but zero open and zero closed trades.
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


ROOT = pathlib.Path(__file__).resolve().parents[3]
DEP_FILE = pathlib.Path(__file__).resolve().with_name("g002_mingogogo_ch1_backtest.py")

SID = "G7835"
SID_LOWER = SID.lower()

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
    "G129183",
    "G7835",
]

CONFIG: dict[str, Any] = {
    "sid": SID,
    "name": "g090_plus_funding_high_wr_combo",
    "engine": "combo_g090_g805740_g827758",
    "paper_only": True,
    "exchange": "bitget",
    "market": "futures",
    "product_type": "USDT-FUTURES",
    "granularity": "1H",
    "kline_interval_ms": 60 * 60 * 1000,
    "kline_limit": 200,
    "kline_base_url": "https://api.bitget.com/api/v2/mix/market/history-candles",
    "funding_url": "https://api.bitget.com/api/v2/mix/market/current-fund-rate",
    "universe": [
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "ADAUSDT",
        "SOLUSDT",
        "DOGEUSDT",
        "DOTUSDT",
        "LINKUSDT",
        "LTCUSDT",
        "AVAXUSDT",
        "NEARUSDT",
        "UNIUSDT",
        "XRPUSDT",
        "OPUSDT",
        "ARBUSDT",
        "APTUSDT",
        "PEPEUSDT",
        "SUIUSDT",
        "WIFUSDT",
    ],
    "equity_usd": 100.0,
    "max_concurrent": 5,
    "cost_bps_round_trip": 24.0,
    "cycle_seconds": 300,
    "g090": {
        "enabled": True,
        "score_min": 80.0,
        "atr_max_pct": 8.0,
        "hours_utc": [1, 3, 0, 2, 21, 20, 4, 23, 6, 19],
        "hold_bars": 24,
        "size_pct_per_trade": 0.10,
        "leverage": 5.0,
        "take_profit_pct": None,
        "stop_loss_pct": None,
    },
    "g805740": {
        "enabled": True,
        "mode": "negative_squeeze_long",
        "fund_abs": 0.0001,
        "move_24h": 0.08,
        "vol_min": None,
        "hours_utc": None,
        "hold_bars": 6,
        "size_pct_per_trade": 0.10,
        "leverage": 5.0,
        "take_profit_pct": 0.015,
        "stop_loss_pct": 0.12,
    },
    "g827758": {
        "enabled": True,
        "mode": "positive_follow_long",
        "fund_abs": 0.0001,
        "move_24h": 0.12,
        "vol_min": 1.8,
        "hours_utc": list(range(8, 16)),
        "hold_bars": 6,
        "size_pct_per_trade": 0.10,
        "leverage": 5.0,
        "take_profit_pct": 0.015,
        "stop_loss_pct": 0.12,
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


STATUS_PROBE = r"""
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
    return (proc.stdout or proc.stderr or "").strip() or "unknown"

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
        "lower": lower,
        "service": service_status(lower),
        "state_exists": state_path.exists(),
        "state_path": str(state_path),
        "cumulative_pnl_usd": None,
        "closed_count": 0,
        "open_count": 0,
        "heartbeats": 0,
        "signals_seen": 0,
        "last_error": None,
        "updated_at": None,
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
            if isinstance(closed, list):
                rec["closed_count"] = len(closed)
            else:
                rec["closed_count"] = int(
                    state.get("closed_count")
                    or state.get("closed_trades_count")
                    or state.get("stats", {}).get("closed_count")
                    or 0
                )
            positions = state.get("positions") or {}
            rec["open_count"] = len(positions) if isinstance(positions, dict) else len(positions or [])
            rec["heartbeats"] = int(state.get("heartbeats") or 0)
            rec["signals_seen"] = int(state.get("signals_seen") or 0)
            rec["last_error"] = state.get("last_error")
            rec["updated_at"] = state.get("updated_at") or state.get("last_heartbeat")
        except Exception as exc:
            rec["last_error"] = repr(exc)
    print(json.dumps(rec, sort_keys=True))
"""


REMOTE_EMULATOR = r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import pandas as pd

from g002_mingogogo_ch1_backtest import atr_pct, compute_ch1_score


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
        "engine": CONFIG["engine"],
        "exchange": CONFIG["exchange"],
        "started_at": now_iso(),
        "updated_at": now_iso(),
        "params": CONFIG,
        "positions": {},
        "closed_trades": [],
        "cumulative_pnl_usd": 0.0,
        "equity_usd": float(CONFIG["equity_usd"]),
        "heartbeats": 0,
        "signals_seen": 0,
        "last_entry_bar_by_symbol": {},
        "fetch_errors": {},
        "last_cycle": None,
        "last_error": None,
    }


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
            state.setdefault("positions", {})
            state.setdefault("closed_trades", [])
            state.setdefault("cumulative_pnl_usd", 0.0)
            state.setdefault("equity_usd", float(CONFIG["equity_usd"]))
            state.setdefault("last_entry_bar_by_symbol", {})
            state.setdefault("fetch_errors", {})
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


def fetch_json(url: str, params: dict, timeout: int = 20) -> dict:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_klines(symbol: str, limit: int | None = None, completed_only: bool = True) -> list[dict]:
    payload = fetch_json(
        CONFIG["kline_base_url"],
        {
            "symbol": symbol,
            "granularity": CONFIG["granularity"],
            "limit": str(limit or int(CONFIG["kline_limit"])),
            "productType": CONFIG["product_type"],
        },
    )
    if not isinstance(payload, dict) or payload.get("code") != "00000":
        raise RuntimeError(f"Bitget kline error for {symbol}: {payload!r}")
    now_ms = int(time.time() * 1000)
    rows = []
    for row in payload.get("data") or []:
        open_time = int(row[0])
        close_time = open_time + int(CONFIG["kline_interval_ms"]) - 1
        if completed_only and close_time >= now_ms:
            continue
        rows.append(
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
    rows.sort(key=lambda item: item["open_time"])
    return rows


def fetch_funding_rate(symbol: str) -> float:
    payload = fetch_json(
        CONFIG["funding_url"],
        {"symbol": symbol, "productType": CONFIG["product_type"]},
    )
    if not isinstance(payload, dict) or payload.get("code") != "00000":
        raise RuntimeError(f"Bitget funding error for {symbol}: {payload!r}")
    data = payload.get("data") or []
    if isinstance(data, list) and data:
        return float(data[0]["fundingRate"])
    if isinstance(data, dict):
        return float(data["fundingRate"])
    raise RuntimeError(f"Bitget funding missing data for {symbol}: {payload!r}")


def to_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "open_time": [r["open_time"] for r in rows],
            "open_price": [r["open"] for r in rows],
            "high_price": [r["high"] for r in rows],
            "low_price": [r["low"] for r in rows],
            "close_price": [r["close"] for r in rows],
            "base_volume": [r["base_volume"] for r in rows],
            "quote_volume": [r["quote_volume"] for r in rows],
        }
    )
    return df


def enriched(symbol: str, rows: list[dict], funding_rate: float) -> dict:
    if len(rows) < 80:
        raise RuntimeError(f"not enough rows for {symbol}: {len(rows)}")
    df = to_frame(rows)
    score, _ = compute_ch1_score(df)
    atr = atr_pct(df["high_price"], df["low_price"], df["close_price"], 14)
    close = float(rows[-1]["close"])
    close_24 = float(rows[-25]["close"]) if len(rows) >= 25 else close
    ret_24h = close / close_24 - 1.0 if close_24 > 0 else 0.0
    vols = [r["quote_volume"] for r in rows]
    prev = vols[-49:-1] if len(vols) >= 49 else vols[:-1]
    med = sorted(prev)[len(prev) // 2] if prev else 0.0
    vol_ratio = float(vols[-1] / med) if med > 0 else 0.0
    bar_ts = int(rows[-1]["open_time"])
    hour = datetime.fromtimestamp(bar_ts / 1000, tz=timezone.utc).hour
    return {
        "symbol": symbol,
        "bar_open_time": bar_ts,
        "bar_close_time": int(rows[-1]["close_time"]),
        "entry_price": close,
        "score": float(score.iloc[-1]),
        "atr_pct": float(atr.iloc[-1]),
        "funding_rate": float(funding_rate),
        "ret_24h": float(ret_24h),
        "vol_ratio": float(vol_ratio),
        "hour_utc": int(hour),
    }


def g090_signal(ctx: dict) -> dict | None:
    cfg = CONFIG["g090"]
    if not cfg["enabled"]:
        return None
    if ctx["score"] < float(cfg["score_min"]):
        return None
    if ctx["atr_pct"] > float(cfg["atr_max_pct"]):
        return None
    if ctx["hour_utc"] not in set(cfg["hours_utc"]):
        return None
    return build_signal(ctx, "g090_hour_filter", cfg, "long", ctx["score"])


def funding_signal(ctx: dict, sleeve: str) -> dict | None:
    cfg = CONFIG[sleeve]
    if not cfg["enabled"]:
        return None
    hours = cfg.get("hours_utc")
    if hours is not None and ctx["hour_utc"] not in set(hours):
        return None
    vol_min = cfg.get("vol_min")
    if vol_min is not None and ctx["vol_ratio"] < float(vol_min):
        return None
    mode = cfg["mode"]
    if mode == "negative_squeeze_long":
        if ctx["funding_rate"] > -float(cfg["fund_abs"]):
            return None
        if ctx["ret_24h"] > -float(cfg["move_24h"]):
            return None
        score = abs(ctx["funding_rate"]) / float(cfg["fund_abs"]) + abs(ctx["ret_24h"]) / float(cfg["move_24h"])
        return build_signal(ctx, sleeve, cfg, "long", score)
    if mode == "positive_follow_long":
        if ctx["funding_rate"] < float(cfg["fund_abs"]):
            return None
        if ctx["ret_24h"] < float(cfg["move_24h"]):
            return None
        score = abs(ctx["funding_rate"]) / float(cfg["fund_abs"]) + abs(ctx["ret_24h"]) / float(cfg["move_24h"]) + ctx["vol_ratio"]
        return build_signal(ctx, sleeve, cfg, "long", score)
    return None


def build_signal(ctx: dict, family: str, cfg: dict, side: str, score: float) -> dict:
    return {
        **ctx,
        "family": family,
        "side": side,
        "signal_score": float(score),
        "hold_bars": int(cfg["hold_bars"]),
        "size_pct_per_trade": float(cfg["size_pct_per_trade"]),
        "leverage": float(cfg["leverage"]),
        "take_profit_pct": cfg.get("take_profit_pct"),
        "stop_loss_pct": cfg.get("stop_loss_pct"),
    }


def update_exits(state: dict) -> None:
    for symbol, pos in list(state["positions"].items()):
        try:
            rows = fetch_klines(symbol, limit=max(int(pos["hold_bars"]) + 8, 80), completed_only=True)
            state["fetch_errors"].pop(symbol, None)
        except Exception as exc:
            state["fetch_errors"][symbol] = {"ts": now_iso(), "stage": "exit", "error": repr(exc)}
            continue
        path = [row for row in rows if row["open_time"] > int(pos["entry_bar_open_time"])]
        if not path:
            continue
        entry = float(pos["entry_price"])
        tp = pos.get("take_profit_pct")
        sl = pos.get("stop_loss_pct")
        take = entry * (1.0 + float(tp)) if tp is not None else None
        stop = entry * (1.0 - float(sl)) if sl is not None else None
        for idx, bar in enumerate(path, start=1):
            if stop is not None and bar["low"] <= stop:
                close_position(state, symbol, pos, stop, "stop_loss", bar)
                break
            if take is not None and bar["high"] >= take:
                close_position(state, symbol, pos, take, "take_profit", bar)
                break
            if idx >= int(pos["hold_bars"]):
                close_position(state, symbol, pos, bar["close"], "time_exit", bar)
                break


def close_position(state: dict, symbol: str, pos: dict, exit_price: float, reason: str, bar: dict) -> None:
    state["positions"].pop(symbol, None)
    entry = float(pos["entry_price"])
    side = pos["side"]
    if side == "short":
        gross = entry / float(exit_price) - 1.0
    else:
        gross = float(exit_price) / entry - 1.0
    margin = float(pos["margin_usd"])
    pnl = margin * ((gross - float(CONFIG["cost_bps_round_trip"]) / 10000.0) * float(pos["leverage"]))
    trade = {
        **pos,
        "exit_ts": now_iso(),
        "exit_bar_open_time": bar["open_time"],
        "exit_price": float(exit_price),
        "exit_reason": reason,
        "pnl_usd": pnl,
    }
    state["closed_trades"].append(trade)
    state["cumulative_pnl_usd"] = round(float(state.get("cumulative_pnl_usd", 0.0)) + pnl, 8)
    state["equity_usd"] = round(float(CONFIG["equity_usd"]) + state["cumulative_pnl_usd"], 8)
    event("exit", trade)


def open_signal(state: dict, signal: dict) -> bool:
    symbol = signal["symbol"]
    if symbol in state["positions"]:
        return False
    if len(state["positions"]) >= int(CONFIG["max_concurrent"]):
        return False
    if state["last_entry_bar_by_symbol"].get(symbol) == signal["bar_open_time"]:
        return False
    margin = float(CONFIG["equity_usd"]) * float(signal["size_pct_per_trade"])
    pos = {
        "symbol": symbol,
        "side": signal["side"],
        "family": signal["family"],
        "entry_ts": now_iso(),
        "entry_bar_open_time": signal["bar_open_time"],
        "entry_bar_close_time": signal["bar_close_time"],
        "entry_price": signal["entry_price"],
        "margin_usd": margin,
        "notional_usd": margin * float(signal["leverage"]),
        "leverage": signal["leverage"],
        "hold_bars": signal["hold_bars"],
        "take_profit_pct": signal["take_profit_pct"],
        "stop_loss_pct": signal["stop_loss_pct"],
        "signal": signal,
    }
    state["positions"][symbol] = pos
    state["last_entry_bar_by_symbol"][symbol] = signal["bar_open_time"]
    event("entry", pos)
    return True


def process_entries(state: dict) -> None:
    signals = []
    checked = 0
    for symbol in UNIVERSE:
        if symbol in state["positions"]:
            continue
        try:
            rows = fetch_klines(symbol, completed_only=True)
            funding = fetch_funding_rate(symbol)
            ctx = enriched(symbol, rows, funding)
            state["fetch_errors"].pop(symbol, None)
        except Exception as exc:
            state["fetch_errors"][symbol] = {"ts": now_iso(), "stage": "entry", "error": repr(exc)}
            continue
        checked += 1
        for sig in [g090_signal(ctx), funding_signal(ctx, "g805740"), funding_signal(ctx, "g827758")]:
            if sig is not None:
                signals.append(sig)
    signals.sort(key=lambda item: (item["signal_score"], item["family"]), reverse=True)
    state["signals_seen"] = int(state.get("signals_seen", 0)) + len(signals)
    opened = 0
    for sig in signals:
        if open_signal(state, sig):
            opened += 1
    state["last_cycle"] = {
        "ts": now_iso(),
        "symbols_checked": checked,
        "candidate_signals": len(signals),
        "opened": opened,
        "positions": len(state["positions"]),
        "fetch_error_count": len(state["fetch_errors"]),
    }


def cycle_once(state: dict) -> None:
    update_exits(state)
    process_entries(state)
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
            event("cycle_error", {"error": repr(exc)})
            save_state(state)
        time.sleep(float(CONFIG["cycle_seconds"]))


if __name__ == "__main__":
    main()
'''


SERVICE_TEMPLATE = """\
[Unit]
Description={sid} paper emulator
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/{sid_lower}
ExecStart=/usr/bin/python3 %h/{sid_lower}/{sid_lower}_combo_emulator.py
Restart=always
RestartSec=20
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""


def run(
    cmd: list[str],
    *,
    input_text: str | None = None,
    timeout: int = 60,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            "command failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout: {proc.stdout}\n"
            f"stderr: {proc.stderr}"
        )
    return proc


def ssh(host: str, remote_cmd: str, *, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["ssh", *SSH_OPTIONS, host, remote_cmd], timeout=timeout, check=check)


def remote_py_write(host: str, remote_path: str, text: str, *, mode: int = 0o644) -> None:
    raw = gzip.compress(text.encode("utf-8"))
    encoded = base64.b64encode(raw).decode("ascii")
    chunks = "\n".join(textwrap.wrap(encoded, 76))
    chmod = oct(mode)[2:]
    cmd = f"""python3 - <<'PY'
import base64, gzip, pathlib
target = pathlib.Path({remote_path!r}).expanduser()
target.parent.mkdir(parents=True, exist_ok=True)
data = base64.b64decode('''{chunks}''')
target.write_text(gzip.decompress(data).decode('utf-8'))
target.chmod(0o{chmod})
PY"""
    ssh(host, cmd, timeout=60)


def build_remote_emulator() -> str:
    return REMOTE_EMULATOR.replace("__CONFIG_JSON__", json.dumps(CONFIG, sort_keys=True))


def fetch_status(host: str) -> list[dict[str, Any]]:
    proc = run(
        ["ssh", *SSH_OPTIONS, host, "python3 -"],
        input_text=STATUS_PROBE % json.dumps(STRATEGIES_TO_COMPARE),
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"status probe failed\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
    rows = []
    for line in proc.stdout.splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def print_status(rows: list[dict[str, Any]]) -> None:
    print("sid      service    hb     open  closed  signals  pnl_usd      updated")
    print("-------  ---------  -----  ----  ------  -------  -----------  ----------------")
    for row in rows:
        pnl = row.get("cumulative_pnl_usd")
        pnl_text = "n/a" if pnl is None else f"{float(pnl):.4f}"
        print(
            f"{row['sid']:<7}  {row.get('service',''):<9}  "
            f"{int(row.get('heartbeats') or 0):>5}  "
            f"{int(row.get('open_count') or 0):>4}  "
            f"{int(row.get('closed_count') or 0):>6}  "
            f"{int(row.get('signals_seen') or 0):>7}  "
            f"{pnl_text:>11}  "
            f"{str(row.get('updated_at') or '')[:16]}"
        )


def choose_no_entry(rows: list[dict[str, Any]], *, min_heartbeats: int) -> dict[str, Any] | None:
    candidates = []
    for row in rows:
        if row["sid"] == SID:
            continue
        if row.get("service") != "active":
            continue
        if int(row.get("open_count") or 0) != 0:
            continue
        if int(row.get("closed_count") or 0) != 0:
            continue
        if int(row.get("heartbeats") or 0) < min_heartbeats:
            continue
        candidates.append(row)
    if not candidates:
        return None
    return max(candidates, key=lambda row: (int(row.get("heartbeats") or 0), -int(row.get("signals_seen") or 0)))


def stop_strategy(host: str, row: dict[str, Any]) -> None:
    lower = row["lower"]
    service = f"{lower}-emulator.service"
    cmd = f"""set -e
systemctl --user disable --now {service} || true
mkdir -p "$HOME/{lower}/runtime"
date -u +%Y-%m-%dT%H:%M:%SZ > "$HOME/{lower}/runtime/paused_by_g7835_deploy.txt"
"""
    ssh(host, cmd, timeout=60)


def deploy(host: str, *, start: bool) -> None:
    if not DEP_FILE.exists():
        raise FileNotFoundError(f"missing dependency: {DEP_FILE}")
    remote_dir = f"~/{SID_LOWER}"
    runtime_dir = f"{remote_dir}/runtime"
    emulator_path = f"{remote_dir}/{SID_LOWER}_combo_emulator.py"
    dep_path = f"{remote_dir}/g002_mingogogo_ch1_backtest.py"
    service_path = f"~/.config/systemd/user/{SID_LOWER}-emulator.service"
    ssh(host, f"mkdir -p {runtime_dir} ~/.config/systemd/user")
    remote_py_write(host, dep_path, DEP_FILE.read_text(encoding="utf-8"), mode=0o644)
    remote_py_write(host, emulator_path, build_remote_emulator(), mode=0o755)
    remote_py_write(host, service_path, SERVICE_TEMPLATE.format(sid=SID, sid_lower=SID_LOWER), mode=0o644)
    ssh(host, f"python3 -m py_compile {emulator_path}")
    ssh(host, "systemctl --user daemon-reload")
    ssh(host, f"systemctl --user enable {SID_LOWER}-emulator.service")
    if start:
        ssh(host, f"systemctl --user restart {SID_LOWER}-emulator.service")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="g185", help="SSH host alias for Oracle")
    parser.add_argument("--status-only", action="store_true", help="Only print remote status")
    parser.add_argument("--no-start", action="store_true", help="Install without starting/restarting")
    parser.add_argument("--no-stop-no-entry", action="store_true", help="Do not disable the active no-entry paper service")
    parser.add_argument("--min-heartbeats", type=int, default=12, help="Minimum heartbeats before a zero-entry service can be stopped")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    rows = fetch_status(args.host)
    print_status(rows)
    if args.status_only:
        return 0
    if not args.no_stop_no_entry:
        target = choose_no_entry(rows, min_heartbeats=args.min_heartbeats)
        if target is None:
            print("\nNo active zero-entry paper service matched the stop rule.")
        else:
            print(f"\nDisabling no-entry paper service: {target['sid']} heartbeats={target.get('heartbeats')}")
            stop_strategy(args.host, target)
    print(f"\nDeploying {SID} paper emulator...")
    deploy(args.host, start=not args.no_start)
    print(f"\n{SID} deploy requested. Refreshed status:")
    print_status(fetch_status(args.host))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
