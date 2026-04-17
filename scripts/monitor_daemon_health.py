"""Periodically write daemon health snapshot for the next ~90 minutes.

Captures: latest heartbeat (events/decisions/live_orders/tested_orders),
error counts (45122, websocket, TRAILING_STOP), Bitget account/positions.
Writes to quant_runtime/_monitor_status.json every 60s, appends to
quant_runtime/_monitor_status.log.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path


HEARTBEAT_RE = re.compile(r"events=(\d+) decisions=(\d+) live_orders=(\d+) tested_orders=(\d+)")
ERR_PATTERNS = {
    "45122": re.compile(r"45122"),
    "trailing_stop_failures": re.compile(r"\[TRAILING_STOP\][^\n]*update failed"),
    "websocket_errors": re.compile(r"websocket attempt=\d+ error"),
    "http_4xx_5xx": re.compile(r"HTTP [45]\d\d"),
    "tracebacks": re.compile(r"Traceback \(most recent call last\)"),
}


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _tail(path: Path, n: int = 200) -> list[str]:
    if not path.exists():
        return []
    try:
        data = path.read_text(encoding="utf-8", errors="replace").replace("\x00", "").splitlines()
    except Exception:
        return []
    return data[-n:]


def _scan_heartbeats(lines: list[str]) -> dict[str, int]:
    last = {"events": 0, "decisions": 0, "live_orders": 0, "tested_orders": 0}
    for line in reversed(lines):
        m = HEARTBEAT_RE.search(line)
        if m:
            last["events"] = int(m.group(1))
            last["decisions"] = int(m.group(2))
            last["live_orders"] = int(m.group(3))
            last["tested_orders"] = int(m.group(4))
            break
    return last


def _scan_errors(lines: list[str]) -> dict[str, int]:
    counts = {k: 0 for k in ERR_PATTERNS}
    for line in lines:
        for k, rx in ERR_PATTERNS.items():
            if rx.search(line):
                counts[k] += 1
    return counts


def _plan_protection(client, symbol: str, hold_side: str) -> dict:
    """Return {stopLoss, takeProfit} from live TPSL plan orders for (symbol, hold_side).

    Bitget system-placed protection (presetStopLossPrice / presetStopSurplusPrice)
    lands in the orders-plan-pending endpoint, not the position.stopLoss field.
    Reading only `p.get("stopLoss")` produces false "<none>" alarms on every
    position protected this way.

    Status markers:
      "<none>"          : query succeeded, no matching live plan row → real alarm.
      "<query_failed>"  : plan-order query raised → neutral, don't alarm either way.
      "<unsupported>"   : client lacks the method (shouldn't happen in live).
    """
    if not hasattr(client, "get_futures_pending_plan_orders"):
        return {"stopLoss": "<unsupported>", "takeProfit": "<unsupported>"}
    try:
        pending = client.get_futures_pending_plan_orders(symbol=symbol, plan_type="profit_loss")
    except Exception:
        return {"stopLoss": "<query_failed>", "takeProfit": "<query_failed>"}
    rows = pending.get("orders", []) if isinstance(pending, dict) else []
    sl_price: str | None = None
    tp_price: str | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol", "")) != symbol:
            continue
        row_side = str(row.get("posSide", row.get("holdSide", ""))).lower()
        if row_side != hold_side:
            continue
        if str(row.get("tradeSide", "")).lower() != "close":
            continue
        if str(row.get("planStatus", "")).lower() != "live":
            continue
        plan_type = str(row.get("planType", "")).lower()
        if plan_type == "loss_plan" and sl_price is None:
            sl_price = str(row.get("stopLossTriggerPrice") or row.get("triggerPrice") or "") or None
        elif plan_type == "profit_plan" and tp_price is None:
            tp_price = str(row.get("stopSurplusTriggerPrice") or row.get("triggerPrice") or "") or None
    return {
        "stopLoss": sl_price or "<none>",
        "takeProfit": tp_price or "<none>",
    }


def _bitget_state() -> dict:
    project_root = Path(__file__).resolve().parents[1]
    _load_dotenv(project_root / ".env")
    import sys
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        from quant_binance.execution.client_factory import build_exchange_rest_client
        client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True)
        acct = client.send(client.build_account_request(market="futures"))
        equity = None
        if acct.get("code") == "00000":
            for row in acct.get("data") or []:
                if row.get("marginCoin") == "USDT":
                    equity = float(row.get("usdtEquity") or 0)
                    break
        pos = client.send(client.build_positions_request())
        positions = []
        if pos.get("code") == "00000":
            for p in pos.get("data") or []:
                qty = float(p.get("total") or 0)
                if qty > 0:
                    symbol = str(p.get("symbol") or "")
                    hold_side = str(p.get("holdSide") or "").lower()
                    inline_sl = p.get("stopLoss")
                    inline_tp = p.get("stopSurplus") or p.get("takeProfit")
                    plan = _plan_protection(client, symbol, hold_side) if symbol and hold_side in {"long", "short"} else {"stopLoss": "<none>", "takeProfit": "<none>"}
                    # Prefer inline protection if present; fall back to plan-order protection.
                    sl_effective = inline_sl or (plan["stopLoss"] if plan["stopLoss"] not in {"<none>", "<query_failed>", "<unsupported>"} else plan["stopLoss"])
                    tp_effective = inline_tp or (plan["takeProfit"] if plan["takeProfit"] not in {"<none>", "<query_failed>", "<unsupported>"} else plan["takeProfit"])
                    positions.append({
                        "symbol": symbol,
                        "side": p.get("holdSide"),
                        "qty": qty,
                        "entry": p.get("openPriceAvg"),
                        "mark": p.get("markPrice"),
                        "uPL": p.get("unrealizedPL"),
                        "stopLoss": sl_effective or "<none>",
                        "takeProfit": tp_effective or "<none>",
                        "protection_source": "inline" if inline_sl else ("plan_order" if plan["stopLoss"] not in {"<none>", "<query_failed>", "<unsupported>"} else plan["stopLoss"]),
                    })
        return {"equity_usdt": equity, "positions": positions}
    except Exception as exc:
        return {"error": str(exc)[:200]}


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    runtime = project_root / "quant_runtime"
    log_path = runtime / "_live_auto_trade_live_restart.log"
    err_path = runtime / "_live_auto_trade_live_restart.err.log"
    status_path = runtime / "_monitor_status.json"
    log_out = runtime / "_monitor_status.log"

    duration_minutes = int(os.environ.get("MONITOR_MINUTES", "90"))
    interval_seconds = int(os.environ.get("MONITOR_INTERVAL", "60"))
    end_time = time.time() + duration_minutes * 60

    cycle = 0
    while time.time() < end_time:
        cycle += 1
        lines = _tail(log_path, 400) + _tail(err_path, 400)
        heartbeats = _scan_heartbeats(lines)
        errors = _scan_errors(lines)
        bitget = _bitget_state()
        snapshot = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "cycle": cycle,
            "heartbeats": heartbeats,
            "error_counts_recent": errors,
            "bitget": bitget,
        }
        try:
            status_path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass
        try:
            with log_out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(snapshot, default=str) + "\n")
        except Exception:
            pass
        time.sleep(interval_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
