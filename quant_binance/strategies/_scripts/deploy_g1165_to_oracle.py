#!/usr/bin/env python3
"""Deploy G1165 paper emulator to Oracle and pause the weakest paper strategy.

This script is intentionally narrow:
1. Read existing Oracle paper strategy state files.
2. Disable the one strategy with the lowest recorded PnL, excluding G1165.
3. Upload and start the G1165 paper emulator.

It assumes the SSH alias `g185` points at the Oracle box.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import pathlib
import shlex
import subprocess
import sys
import textwrap
from typing import Any


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
DEP_FILE = pathlib.Path(__file__).resolve().with_name("g002_mingogogo_ch1_backtest.py")

SID = "G1165"
SID_LOWER = SID.lower()
REMOTE_DIR = f"~/{SID_LOWER}"
REMOTE_RUNTIME = f"{REMOTE_DIR}/runtime"
REMOTE_EMULATOR_PATH = f"{REMOTE_DIR}/{SID_LOWER}_paper_emulator.py"
REMOTE_DEP_PATH = f"{REMOTE_DIR}/g002_mingogogo_ch1_backtest.py"
REMOTE_SERVICE_PATH = f"~/.config/systemd/user/{SID_LOWER}-emulator.service"

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
]

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

def number_from_state(state, keys):
    cur = state
    for key in keys:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    try:
        return float(cur)
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
        "last_error": None,
    }
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            rec["cumulative_pnl_usd"] = (
                number_from_state(state, ["cumulative_pnl_usd"])
                or number_from_state(state, ["total_pnl_usd"])
                or number_from_state(state, ["realized_pnl_usd"])
                or number_from_state(state, ["stats", "cumulative_pnl_usd"])
                or number_from_state(state, ["stats", "total_pnl_usd"])
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
            rec["open_count"] = len(state.get("positions") or {})
            rec["updated_at"] = state.get("updated_at") or state.get("last_heartbeat")
        except Exception as exc:
            rec["last_error"] = repr(exc)
    print(json.dumps(rec, sort_keys=True))
"""


REMOTE_EMULATOR = r'''
#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import pandas as pd

from g002_mingogogo_ch1_backtest import atr_pct, compute_ch1_score


SID = "G1165"
UNIVERSE = [
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

EQUITY_USD = 100.0
SIZE_PCT_PER_TRADE = 0.25
LEVERAGE = 10.0
ENTRY_THRESHOLD = 80.0
HOLD_BARS = 36
MAX_CONCURRENT = 5
ATR_MIN_PCT = 3.0
ATR_MAX_PCT = 8.0
TAKE_PROFIT_PCT = 0.14
STOP_LOSS_PCT = 0.075
COST_BPS_ROUND_TRIP = 24.0
CYCLE_SECONDS = 300

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
        "started_at": now_iso(),
        "updated_at": now_iso(),
        "params": {
            "entry_threshold": ENTRY_THRESHOLD,
            "hold_bars": HOLD_BARS,
            "atr_min_pct": ATR_MIN_PCT,
            "atr_max_pct": ATR_MAX_PCT,
            "take_profit_pct": TAKE_PROFIT_PCT,
            "stop_loss_pct": STOP_LOSS_PCT,
            "same_bar_priority": "stop_loss",
            "leverage": LEVERAGE,
            "size_pct_per_trade": SIZE_PCT_PER_TRADE,
            "max_concurrent": MAX_CONCURRENT,
            "cost_bps_round_trip": COST_BPS_ROUND_TRIP,
        },
        "positions": {},
        "closed_trades": [],
        "cumulative_pnl_usd": 0.0,
        "equity_usd": EQUITY_USD,
        "heartbeats": 0,
        "last_error": None,
    }


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
            state.setdefault("positions", {})
            state.setdefault("closed_trades", [])
            state.setdefault("cumulative_pnl_usd", 0.0)
            return state
        except Exception:
            pass
    return default_state()


def save_state(state: dict) -> None:
    state["updated_at"] = now_iso()
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def event(kind: str, payload: dict) -> None:
    payload = {"ts": now_iso(), "sid": SID, "kind": kind, **payload}
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def fetch_klines(symbol: str, limit: int = 220, completed_only: bool = True) -> pd.DataFrame:
    params = urllib.parse.urlencode(
        {"symbol": symbol, "interval": "1h", "limit": str(limit)}
    )
    url = f"https://api.binance.com/api/v3/klines?{params}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        rows = json.loads(resp.read().decode("utf-8"))

    now_ms = int(time.time() * 1000)
    records = []
    for row in rows:
        close_time = int(row[6])
        if completed_only and close_time > now_ms:
            continue
        records.append(
            {
                "open_time": int(row[0]),
                "open_price": float(row[1]),
                "high_price": float(row[2]),
                "low_price": float(row[3]),
                "close_price": float(row[4]),
                "base_volume": float(row[5]),
                "close_time": close_time,
            }
        )
    return pd.DataFrame(records)


def current_signal(symbol: str) -> dict | None:
    df = fetch_klines(symbol, limit=220, completed_only=True)
    if len(df) < 80:
        return None
    score, _parts = compute_ch1_score(df)
    atr_series = atr_pct(df["high_price"], df["low_price"], df["close_price"])
    return {
        "symbol": symbol,
        "score": float(score.iloc[-1]),
        "atr_pct": float(atr_series.iloc[-1]),
        "entry_price": float(df["close_price"].iloc[-1]),
        "entry_bar_ts": int(df["open_time"].iloc[-1]),
        "bar_close_time": int(df["close_time"].iloc[-1]),
    }


def should_exit(position: dict) -> dict | None:
    df = fetch_klines(position["symbol"], limit=120, completed_only=False)
    if df.empty:
        return None

    entry = float(position["entry_price"])
    stop_price = entry * (1.0 - STOP_LOSS_PCT)
    take_price = entry * (1.0 + TAKE_PROFIT_PCT)
    entry_bar_ts = int(position["entry_bar_ts"])
    time_exit_ts = entry_bar_ts + HOLD_BARS * 3600 * 1000

    path = df[df["open_time"] > entry_bar_ts]
    if path.empty:
        return None

    for _idx, row in path.iterrows():
        low = float(row["low_price"])
        high = float(row["high_price"])
        # Conservative same-bar rule from the backtest: stop wins over take-profit.
        if low <= stop_price:
            return {
                "reason": "stop_loss",
                "exit_price": stop_price,
                "exit_bar_ts": int(row["open_time"]),
            }
        if high >= take_price:
            return {
                "reason": "take_profit",
                "exit_price": take_price,
                "exit_bar_ts": int(row["open_time"]),
            }
        if int(row["open_time"]) >= time_exit_ts:
            return {
                "reason": "time_exit",
                "exit_price": float(row["close_price"]),
                "exit_bar_ts": int(row["open_time"]),
            }
    return None


def close_position(state: dict, symbol: str, exit_info: dict) -> None:
    pos = state["positions"].pop(symbol)
    margin_usd = float(pos["margin_usd"])
    entry = float(pos["entry_price"])
    exit_price = float(exit_info["exit_price"])
    gross_pct = (exit_price / entry - 1.0) * LEVERAGE
    cost_usd = margin_usd * COST_BPS_ROUND_TRIP / 10000.0
    pnl_usd = margin_usd * gross_pct - cost_usd
    trade = {
        **pos,
        **exit_info,
        "exit_ts": now_iso(),
        "gross_pct_on_margin": gross_pct,
        "cost_usd": cost_usd,
        "pnl_usd": pnl_usd,
    }
    state["closed_trades"].append(trade)
    state["cumulative_pnl_usd"] = round(
        float(state.get("cumulative_pnl_usd", 0.0)) + pnl_usd, 8
    )
    state["equity_usd"] = round(EQUITY_USD + state["cumulative_pnl_usd"], 8)
    event("exit", trade)


def open_position(state: dict, signal: dict) -> None:
    margin_usd = EQUITY_USD * SIZE_PCT_PER_TRADE
    pos = {
        "symbol": signal["symbol"],
        "side": "long",
        "entry_ts": now_iso(),
        "entry_bar_ts": signal["entry_bar_ts"],
        "entry_price": signal["entry_price"],
        "score": signal["score"],
        "atr_pct": signal["atr_pct"],
        "margin_usd": margin_usd,
        "notional_usd": margin_usd * LEVERAGE,
        "leverage": LEVERAGE,
    }
    state["positions"][signal["symbol"]] = pos
    event("entry", pos)


def cycle_once() -> None:
    state = load_state()
    try:
        for symbol in list(state["positions"].keys()):
            exit_info = should_exit(state["positions"][symbol])
            if exit_info:
                close_position(state, symbol, exit_info)

        slots = MAX_CONCURRENT - len(state["positions"])
        if slots > 0:
            signals = []
            for symbol in UNIVERSE:
                if symbol in state["positions"]:
                    continue
                try:
                    sig = current_signal(symbol)
                    if not sig:
                        continue
                    if sig["score"] < ENTRY_THRESHOLD:
                        continue
                    if not (ATR_MIN_PCT <= sig["atr_pct"] <= ATR_MAX_PCT):
                        continue
                    signals.append(sig)
                except Exception as exc:
                    event("symbol_error", {"symbol": symbol, "error": repr(exc)})

            signals.sort(key=lambda item: item["score"], reverse=True)
            for sig in signals[:slots]:
                open_position(state, sig)

        state["last_error"] = None
    except Exception as exc:
        state["last_error"] = repr(exc)
        event("cycle_error", {"error": repr(exc)})
    finally:
        state["heartbeats"] = int(state.get("heartbeats", 0)) + 1
        save_state(state)


def main() -> None:
    event("started", {"cycle_seconds": CYCLE_SECONDS})
    while True:
        cycle_once()
        time.sleep(CYCLE_SECONDS)


if __name__ == "__main__":
    main()
'''


SERVICE_UNIT = f"""\
[Unit]
Description=G1165 paper emulator
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/{SID_LOWER}
ExecStart=/usr/bin/python3 %h/{SID_LOWER}/{SID_LOWER}_paper_emulator.py
Restart=always
RestartSec=20
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""


def run(cmd: list[str], *, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
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


def remote_expand(path: str) -> str:
    return path.replace("~", "$HOME", 1)


def upload_text(host: str, remote_path: str, text: str, *, executable: bool = False) -> None:
    raw = gzip.compress(text.encode("utf-8"))
    encoded = base64.b64encode(raw).decode("ascii")
    chunks = "\n".join(textwrap.wrap(encoded, 76))
    target = remote_expand(remote_path)
    parent = str(pathlib.PurePosixPath(target).parent)
    chmod = f"chmod +x {target}" if executable else "true"
    remote_cmd = f"""mkdir -p {parent}
base64 -d <<'EOF' | gzip -dc > {target}
{chunks}
EOF
{chmod}
"""
    ssh(host, remote_cmd, timeout=60)


def fetch_status(host: str) -> list[dict[str, Any]]:
    probe = REMOTE_STATUS_PROBE % json.dumps(STRATEGIES_TO_COMPARE)
    proc = ssh(host, "python3 - <<'PY'\n" + probe + "\nPY", timeout=60)
    rows = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def choose_worst(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = []
    for row in rows:
        if row.get("sid") == SID:
            continue
        pnl = row.get("cumulative_pnl_usd")
        if pnl is None:
            continue
        try:
            row["_pnl_sort"] = float(pnl)
        except (TypeError, ValueError):
            continue
        candidates.append(row)
    if not candidates:
        return None
    return min(candidates, key=lambda item: item["_pnl_sort"])


def stop_strategy(host: str, lower: str) -> None:
    service = f"{lower}-emulator.service"
    remote_cmd = f"""set -e
systemctl --user disable --now {shlex.quote(service)} || true
mkdir -p "$HOME/{shlex.quote(lower)}/runtime"
date -u +%Y-%m-%dT%H:%M:%SZ > "$HOME/{shlex.quote(lower)}/runtime/paused_by_g1165_deploy.txt"
"""
    ssh(host, remote_cmd, timeout=60)


def deploy_g1165(host: str) -> None:
    dep_text = DEP_FILE.read_text(encoding="utf-8")
    ssh(host, f"mkdir -p {remote_expand(REMOTE_RUNTIME)} ~/.config/systemd/user", timeout=60)
    upload_text(host, REMOTE_DEP_PATH, dep_text)
    upload_text(host, REMOTE_EMULATOR_PATH, REMOTE_EMULATOR, executable=True)
    upload_text(host, REMOTE_SERVICE_PATH, SERVICE_UNIT)
    ssh(
        host,
        f"""set -e
loginctl enable-linger "$USER" >/dev/null 2>&1 || true
systemctl --user daemon-reload
systemctl --user enable --now {SID_LOWER}-emulator.service
systemctl --user --no-pager status {SID_LOWER}-emulator.service | sed -n '1,16p'
""",
        timeout=60,
    )


def print_status(rows: list[dict[str, Any]]) -> None:
    print("sid   service    pnl_usd      closed  state")
    print("----  ---------  -----------  ------  -----")
    for row in rows:
        pnl = row.get("cumulative_pnl_usd")
        pnl_text = "n/a" if pnl is None else f"{float(pnl):.4f}"
        print(
            f"{row.get('sid', ''):<4}  "
            f"{row.get('service', ''):<9}  "
            f"{pnl_text:>11}  "
            f"{row.get('closed_count', 0):>6}  "
            f"{'yes' if row.get('state_exists') else 'no'}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-host", default="g185", help="SSH host alias for Oracle")
    parser.add_argument("--status-only", action="store_true", help="Only print existing paper status")
    parser.add_argument("--no-stop-worst", action="store_true", help="Deploy without disabling the weakest paper strategy")
    parser.add_argument("--force", action="store_true", help="Redeploy even when G1165 already appears active")
    args = parser.parse_args()

    if not DEP_FILE.exists():
        raise FileNotFoundError(f"Missing dependency file: {DEP_FILE}")

    rows = fetch_status(args.ssh_host)
    print_status(rows)
    if args.status_only:
        return 0

    g1165 = next((row for row in rows if row.get("sid") == SID), None)
    if (
        not args.force
        and g1165
        and str(g1165.get("service", "")).strip() == "active"
    ):
        print(f"\n{SID} already active on Oracle; skipping redeploy.")
        return 0

    if not args.no_stop_worst:
        worst = choose_worst(rows)
        if worst:
            print(
                f"\nDisabling weakest paper strategy: {worst['sid']} "
                f"(pnl={worst.get('cumulative_pnl_usd')}, service={worst.get('service')})"
            )
            stop_strategy(args.ssh_host, worst["lower"])
        else:
            print("\nNo comparable PnL state found; skipping disable step.")

    print(f"\nDeploying {SID} paper emulator...")
    deploy_g1165(args.ssh_host)

    print(f"\n{SID} deploy requested. Refreshed status:")
    print_status(fetch_status(args.ssh_host))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
