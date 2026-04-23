"""Periodically write daemon health snapshots for the active runtime.

Captures: latest heartbeat (events/decisions/live_orders/tested_orders),
error counts (45122, websocket, TRAILING_STOP), Bitget account/positions.
Writes to the selected runtime's `_monitor_status.json` every 60s and appends
JSONL rows to `_monitor_status.log`.
"""
from __future__ import annotations

import json
import os
import re
import sys
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
RUNTIME_ENV_VARS = (
    "MONITOR_OUTPUT_BASE",
    "QUANT_MONITOR_RUNTIME",
    "QUANT_RUNTIME_BASE",
    "QUANT_HEALTH_AUDIT_RUNTIME",
)


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


def _resolve_runtime_dir(project_root: Path, requested: str | None = None) -> Path:
    raw = str(requested or "").strip()
    if not raw:
        for key in RUNTIME_ENV_VARS:
            value = str(os.environ.get(key, "")).strip()
            if value:
                raw = value
                break
    if raw:
        candidate = Path(raw)
        return candidate if candidate.is_absolute() else project_root / candidate

    candidates = [
        project_root / "quant_runtime_paper50",
        project_root / "quant_runtime",
    ]
    best_runtime = project_root / "quant_runtime"
    best_score = 0.0
    for runtime in candidates:
        score = _runtime_freshness(runtime)
        if score > best_score:
            best_runtime = runtime
            best_score = score
    return best_runtime


def _runtime_freshness(runtime: Path) -> float:
    markers = (
        runtime / "_paper50.out.log",
        runtime / "_live_auto_trade_live_restart.log",
        runtime / "live_supervisor.log",
        runtime / "output" / "paper-live-shell" / "latest" / "overview.json",
        runtime / "live_supervisor_health.json",
    )
    score = 0.0
    for path in markers:
        if not path.exists():
            continue
        try:
            score = max(score, path.stat().st_mtime)
        except OSError:
            continue
    return score


def _select_log_paths(runtime: Path) -> tuple[Path, Path]:
    paper_out = runtime / "_paper50.out.log"
    paper_err = runtime / "_paper50.err.log"
    live_out = runtime / "_live_auto_trade_live_restart.log"
    live_err = runtime / "_live_auto_trade_live_restart.err.log"
    supervisor_log = runtime / "live_supervisor.log"
    if paper_out.exists():
        competing_mtime = 0.0
        for candidate in (live_out, supervisor_log):
            if candidate.exists():
                try:
                    competing_mtime = max(competing_mtime, candidate.stat().st_mtime)
                except OSError:
                    continue
        try:
            if paper_out.stat().st_mtime >= competing_mtime:
                return paper_out, paper_err
        except OSError:
            pass
    if live_out.exists():
        return live_out, live_err
    return supervisor_log, live_err


def _read_last_jsonl_row(path: Path) -> dict | None:
    lines = _tail(path, 50)
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _latest_account_sync_path(runtime: Path) -> Path | None:
    candidates = [
        runtime / "forensics" / "account_sync.jsonl",
    ]
    output_root = runtime / "output" / "paper-live-shell"
    if output_root.exists():
        candidates.extend(output_root.rglob("logs/account_sync.jsonl"))

    best_path: Path | None = None
    best_mtime = 0.0
    for path in candidates:
        if not path.exists():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if best_path is None or mtime > best_mtime:
            best_path = path
            best_mtime = mtime
    return best_path


def _latest_runtime_positions(runtime: Path) -> list[dict]:
    overview_path = runtime / "output" / "paper-live-shell" / "latest" / "overview.json"
    if not overview_path.exists():
        return []
    try:
        payload = json.loads(overview_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    positions = payload.get("exchange_live_futures_positions")
    return positions if isinstance(positions, list) else []


def _bitget_state_from_account_sync(runtime: Path, *, error_message: str) -> dict | None:
    account_sync_path = _latest_account_sync_path(runtime)
    if account_sync_path is None:
        return None

    snapshot = _read_last_jsonl_row(account_sync_path)
    if not snapshot:
        return None

    account_snapshot = snapshot.get("account_snapshot") if isinstance(snapshot, dict) else None
    if not isinstance(account_snapshot, dict):
        return None

    accounts = account_snapshot.get("accounts")
    if not isinstance(accounts, list):
        return None

    equity = account_snapshot.get("unionAvailable")
    if equity in (None, ""):
        equity = account_snapshot.get("executionAvailableBalance")
    if equity in (None, ""):
        for row in accounts:
            if isinstance(row, dict) and row.get("marginCoin") == "USDT":
                equity = row.get("usdtEquity") or row.get("available")
                break

    try:
        equity_value = float(equity) if equity not in (None, "") else None
    except (TypeError, ValueError):
        equity_value = None

    return {
        "equity_usdt": equity_value,
        "positions": _latest_runtime_positions(runtime),
        "source": "account_sync_fallback",
        "synced_at": snapshot.get("timestamp"),
        "warning": error_message[:200],
    }


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


def _bitget_state(runtime: Path) -> dict:
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
        return {"equity_usdt": equity, "positions": positions, "source": "direct_probe"}
    except Exception as exc:
        fallback = _bitget_state_from_account_sync(runtime, error_message=str(exc))
        if fallback is not None:
            return fallback
        return {"error": str(exc)[:200]}


def _resolve_monitor_end_time(*, now_ts: float | None = None) -> float | None:
    raw = str(os.environ.get("MONITOR_MINUTES", "0")).strip()
    try:
        duration_minutes = int(raw)
    except ValueError:
        duration_minutes = 0
    if duration_minutes <= 0:
        return None
    base = time.time() if now_ts is None else now_ts
    return base + duration_minutes * 60


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    runtime = _resolve_runtime_dir(project_root, requested=sys.argv[1] if len(sys.argv) > 1 else None)
    log_path, err_path = _select_log_paths(runtime)
    status_path = runtime / "_monitor_status.json"
    log_out = runtime / "_monitor_status.log"

    interval_seconds = int(os.environ.get("MONITOR_INTERVAL", "60"))
    end_time = _resolve_monitor_end_time()

    cycle = 0
    while end_time is None or time.time() < end_time:
        cycle += 1
        lines = _tail(log_path, 400) + _tail(err_path, 400)
        heartbeats = _scan_heartbeats(lines)
        errors = _scan_errors(lines)
        bitget = _bitget_state(runtime)
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
