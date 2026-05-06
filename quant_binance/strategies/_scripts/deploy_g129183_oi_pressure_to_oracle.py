#!/usr/bin/env python3
"""Deploy G129183 OI-pressure paper emulator to Oracle.

G129183 is deliberately not a breakout/CH1 runtime.  It trades Bitget futures
paper-only from price + open-interest pressure:

- 6h price move >= 2%
- 6h OI increase >= 4%
- direction follows price move
- hold 12h, TP 8%, SL 5%, 12x, 35% paper size
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import subprocess
import sys
import textwrap
from typing import Any


SID = "G129183"
SID_LOWER = SID.lower()

CONFIG: dict[str, Any] = {
    "sid": SID,
    "name": "oi_pressure_continuation_6h_p2_oi4_hold12_tp8_sl5_lev12",
    "engine": "oi_pressure_continuation",
    "paper_only": True,
    "exchange": "bitget",
    "market": "futures",
    "product_type": "USDT-FUTURES",
    "granularity": "1H",
    "kline_interval_ms": 60 * 60 * 1000,
    "kline_limit": 200,
    "kline_base_url": "https://api.bitget.com/api/v2/mix/market/history-candles",
    "open_interest_url": "https://api.bitget.com/api/v2/mix/market/open-interest",
    "universe": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
    "equity_usd": 100.0,
    "size_pct_per_trade": 0.35,
    "leverage": 12.0,
    "max_concurrent": 4,
    "window_hours": 6,
    "min_abs_price_move": 0.02,
    "min_oi_increase": 0.04,
    "vol_ratio_min": 1.0,
    "hold_bars": 12,
    "take_profit_pct": 0.08,
    "stop_loss_pct": 0.05,
    "cost_bps_round_trip": 24.0,
    "cycle_seconds": 300,
    "oi_warmup_seconds": 6 * 60 * 60,
    "oi_retention_seconds": 7 * 24 * 60 * 60,
    "runtime_note": "Needs 6h of live OI snapshots after first start before entries can trigger.",
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


REMOTE_EMULATOR = r'''#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
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
        "oi_snapshots": {symbol: [] for symbol in UNIVERSE},
        "fetch_errors": {},
        "last_error": None,
        "last_cycle": None,
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
            state.setdefault("oi_snapshots", {symbol: [] for symbol in UNIVERSE})
            state.setdefault("fetch_errors", {})
            for symbol in UNIVERSE:
                state["oi_snapshots"].setdefault(symbol, [])
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
    with urllib.request.urlopen(f"{url}?{query}", timeout=timeout) as resp:
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


def fetch_open_interest(symbol: str) -> dict:
    payload = fetch_json(
        CONFIG["open_interest_url"],
        {"symbol": symbol, "productType": CONFIG["product_type"]},
    )
    if not isinstance(payload, dict) or payload.get("code") != "00000":
        raise RuntimeError(f"Bitget open-interest error for {symbol}: {payload!r}")
    data = payload.get("data") or {}
    items = data.get("openInterestList") or []
    if not items:
        raise RuntimeError(f"Bitget open-interest missing list for {symbol}: {payload!r}")
    return {
        "ts": int(data.get("ts") or payload.get("requestTime") or int(time.time() * 1000)),
        "open_interest": float(items[0]["size"]),
    }


def update_oi_snapshot(state: dict, symbol: str) -> dict:
    rec = fetch_open_interest(symbol)
    snapshots = state["oi_snapshots"].setdefault(symbol, [])
    if not snapshots or int(snapshots[-1]["ts"]) != int(rec["ts"]):
        snapshots.append(rec)
    cutoff = int(time.time() * 1000) - int(CONFIG["oi_retention_seconds"]) * 1000
    state["oi_snapshots"][symbol] = [x for x in snapshots if int(x["ts"]) >= cutoff]
    return rec


def oi_change_for_signal(state: dict, symbol: str, current_oi: dict) -> dict | None:
    target_ts = int(current_oi["ts"]) - int(CONFIG["window_hours"]) * 60 * 60 * 1000
    candidates = [x for x in state["oi_snapshots"].get(symbol, []) if int(x["ts"]) <= target_ts]
    if not candidates:
        return None
    past = max(candidates, key=lambda x: int(x["ts"]))
    past_oi = float(past["open_interest"])
    cur_oi = float(current_oi["open_interest"])
    if past_oi <= 0 or cur_oi <= 0:
        return None
    return {
        "current_ts": int(current_oi["ts"]),
        "past_ts": int(past["ts"]),
        "current_oi": cur_oi,
        "past_oi": past_oi,
        "oi_change": cur_oi / past_oi - 1.0,
    }


def volume_ratio(rows: list[dict], idx: int, period: int = 24) -> float | None:
    if idx < period:
        return None
    vols = [float(r["base_volume"]) for r in rows[idx - period:idx]]
    avg = sum(vols) / len(vols) if vols else 0.0
    if avg <= 0:
        return None
    return float(rows[idx]["base_volume"]) / avg


def signal_for_symbol(state: dict, symbol: str, rows: list[dict], current_oi: dict) -> dict | None:
    window = int(CONFIG["window_hours"])
    idx = len(rows) - 1
    if idx < max(window, 24):
        return None
    bar = rows[idx]
    if state["last_entry_bar_by_symbol"].get(symbol) == bar["open_time"]:
        return None
    last_entry_bar = state["last_entry_bar_by_symbol"].get(symbol)
    if last_entry_bar is not None and bar["open_time"] - int(last_entry_bar) < int(CONFIG["hold_bars"]) * int(CONFIG["kline_interval_ms"]):
        return None
    prev = rows[idx - window]
    if prev["close"] <= 0:
        return None
    price_move = bar["close"] / prev["close"] - 1.0
    if abs(price_move) < float(CONFIG["min_abs_price_move"]):
        return None
    oi = oi_change_for_signal(state, symbol, current_oi)
    if oi is None or float(oi["oi_change"]) < float(CONFIG["min_oi_increase"]):
        return None
    volr = volume_ratio(rows, idx)
    if volr is None or volr < float(CONFIG["vol_ratio_min"]):
        return None
    side = "long" if price_move > 0 else "short"
    score = abs(price_move) * 100.0 + float(oi["oi_change"]) * 100.0 + volr
    return {
        "symbol": symbol,
        "side": side,
        "engine": CONFIG["engine"],
        "bar_open_time": bar["open_time"],
        "bar_close_time": bar["close_time"],
        "entry_price": bar["close"],
        "price_move_6h": price_move,
        "oi_change_6h": float(oi["oi_change"]),
        "oi_current": oi["current_oi"],
        "oi_past": oi["past_oi"],
        "oi_current_ts": oi["current_ts"],
        "oi_past_ts": oi["past_ts"],
        "vol_ratio": volr,
        "score": score,
        "leverage": float(CONFIG["leverage"]),
        "size_pct_per_trade": float(CONFIG["size_pct_per_trade"]),
        "hold_bars": int(CONFIG["hold_bars"]),
        "take_profit_pct": float(CONFIG["take_profit_pct"]),
        "stop_loss_pct": float(CONFIG["stop_loss_pct"]),
    }


def close_position(state: dict, symbol: str, pos: dict, exit_price: float, reason: str, bar: dict) -> None:
    margin = float(pos["margin_usd"])
    leverage = float(pos.get("leverage", CONFIG["leverage"]))
    side_mult = 1.0 if pos.get("side") == "long" else -1.0
    gross_pnl = margin * ((exit_price / float(pos["entry_price"]) - 1.0) * side_mult * leverage)
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
    event("close", {"symbol": symbol, "side": pos.get("side"), "reason": reason, "exit_price": exit_price, "pnl_usd": round(pnl, 6)})


def update_exits(state: dict) -> None:
    for symbol, pos in list(state["positions"].items()):
        try:
            rows = fetch_klines(symbol, limit=max(int(pos.get("hold_bars", 12)) + 8, 80), completed_only=True)
            state["fetch_errors"].pop(symbol, None)
        except Exception as exc:
            state["fetch_errors"][symbol] = {"ts": now_iso(), "stage": "exit", "error": repr(exc)}
            continue
        entry_bar = int(pos["entry_bar_open_time"])
        path = [row for row in rows if row["open_time"] > entry_bar]
        if not path:
            continue
        entry = float(pos["entry_price"])
        side = pos.get("side")
        if side == "short":
            take = entry * (1.0 - float(pos["take_profit_pct"]))
            stop = entry * (1.0 + float(pos["stop_loss_pct"]))
        else:
            take = entry * (1.0 + float(pos["take_profit_pct"]))
            stop = entry * (1.0 - float(pos["stop_loss_pct"]))
        for idx, bar in enumerate(path, start=1):
            if side == "short":
                if bar["high"] >= stop:
                    close_position(state, symbol, pos, stop, "stop_loss", bar)
                    break
                if bar["low"] <= take:
                    close_position(state, symbol, pos, take, "take_profit", bar)
                    break
            else:
                if bar["low"] <= stop:
                    close_position(state, symbol, pos, stop, "stop_loss", bar)
                    break
                if bar["high"] >= take:
                    close_position(state, symbol, pos, take, "take_profit", bar)
                    break
            if idx >= int(pos["hold_bars"]):
                close_position(state, symbol, pos, bar["close"], "time_exit", bar)
                break


def open_signal(state: dict, signal: dict) -> bool:
    symbol = signal["symbol"]
    if symbol in state["positions"]:
        return False
    if len(state["positions"]) >= int(CONFIG["max_concurrent"]):
        return False
    margin = float(CONFIG["equity_usd"]) * float(signal["size_pct_per_trade"])
    pos = {
        "symbol": symbol,
        "side": signal["side"],
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
    event("open", {"symbol": symbol, "side": signal["side"], "entry_price": signal["entry_price"], "signal": signal})
    return True


def process_entries(state: dict) -> None:
    signals = []
    warmed = 0
    for symbol in UNIVERSE:
        if symbol in state["positions"]:
            continue
        try:
            rows = fetch_klines(symbol, completed_only=True)
            current_oi = update_oi_snapshot(state, symbol)
            state["fetch_errors"].pop(symbol, None)
            if oi_change_for_signal(state, symbol, current_oi) is not None:
                warmed += 1
            sig = signal_for_symbol(state, symbol, rows, current_oi)
            if sig:
                signals.append(sig)
        except Exception as exc:
            state["fetch_errors"][symbol] = {"ts": now_iso(), "stage": "entry", "error": repr(exc)}
    signals.sort(key=lambda item: item["score"], reverse=True)
    opened = 0
    for sig in signals:
        if open_signal(state, sig):
            opened += 1
    state["last_cycle"] = {
        "ts": now_iso(),
        "warmed_symbols": warmed,
        "candidate_signals": len(signals),
        "opened": opened,
        "positions": len(state["positions"]),
        "oi_snapshot_counts": {symbol: len(state["oi_snapshots"].get(symbol, [])) for symbol in UNIVERSE},
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
            save_state(state)
            event("error", {"error": repr(exc)})
        time.sleep(float(CONFIG["cycle_seconds"]))


if __name__ == "__main__":
    main()
'''


SERVICE_TEMPLATE = """[Unit]
Description={sid} OI-pressure paper emulator
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/{sid_lower}
ExecStart=/usr/bin/python3 %h/{sid_lower}/{sid_lower}_oi_pressure_emulator.py
Restart=always
RestartSec=20

[Install]
WantedBy=default.target
"""


STATUS_PROBE = r"""
import json
import pathlib
import subprocess

lower = "g129183"
state_path = pathlib.Path.home() / lower / "runtime" / "state.json"
proc = subprocess.run(["systemctl", "--user", "is-active", f"{lower}-emulator.service"], text=True, capture_output=True)
rec = {"service": (proc.stdout or proc.stderr or "").strip(), "state_exists": state_path.exists(), "state_path": str(state_path)}
if state_path.exists():
    state = json.loads(state_path.read_text())
    rec.update({
        "sid": state.get("sid"),
        "engine": state.get("engine"),
        "exchange": state.get("exchange"),
        "last_error": state.get("last_error"),
        "fetch_errors": len(state.get("fetch_errors") or {}),
        "positions": len(state.get("positions") or {}),
        "closed_trades": len(state.get("closed_trades") or []),
        "equity_usd": state.get("equity_usd"),
        "heartbeats": state.get("heartbeats"),
        "last_cycle": state.get("last_cycle"),
    })
print(json.dumps(rec, indent=2, sort_keys=True))
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


def build_remote_emulator() -> str:
    return REMOTE_EMULATOR.replace("__CONFIG_JSON__", json.dumps(CONFIG, sort_keys=True))


def deploy(host: str, *, start: bool) -> None:
    remote_dir = f"~/{SID_LOWER}"
    runtime_dir = f"{remote_dir}/runtime"
    emulator_path = f"{remote_dir}/{SID_LOWER}_oi_pressure_emulator.py"
    service_path = f"~/.config/systemd/user/{SID_LOWER}-emulator.service"
    ssh(host, f"mkdir -p {runtime_dir} ~/.config/systemd/user")
    remote_py_write(host, emulator_path, build_remote_emulator(), mode=0o755)
    remote_py_write(host, service_path, SERVICE_TEMPLATE.format(sid=SID, sid_lower=SID_LOWER), mode=0o644)
    ssh(host, f"python3 -m py_compile {emulator_path}")
    ssh(host, "systemctl --user daemon-reload")
    ssh(host, f"systemctl --user enable {SID_LOWER}-emulator.service")
    if start:
        ssh(host, f"systemctl --user restart {SID_LOWER}-emulator.service")


def status(host: str) -> int:
    proc = run(["ssh", *SSH_OPTIONS, host, "python3 -"], input_text=STATUS_PROBE, check=False)
    return proc.returncode


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="g185", help="SSH host alias for Oracle")
    parser.add_argument("--status-only", action="store_true", help="Only print remote status")
    parser.add_argument("--no-start", action="store_true", help="Install without starting/restarting")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.status_only:
        return status(args.host)
    deploy(args.host, start=not args.no_start)
    return status(args.host)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
