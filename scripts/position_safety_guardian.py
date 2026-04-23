"""Guardian: ensures every open Bitget futures position has an exchange-side stopLoss.

Runs as a sibling to the daemon. Detects gaps where a position has no SL on the
exchange (e.g., adopted unprotected positions, daemon-down windows, swallowed
protection_error during entry) and registers an emergency SL within seconds.

Closes the gap demonstrated by the 2026-04-15 PEPE incident (daemon down, no
exchange-side SL, position bleeding unprotected for ~3 minutes).

Behavior:
  - Polls Bitget positions every GUARDIAN_INTERVAL (default 20s).
  - Waits GUARDIAN_GRACE_SECONDS (default 60s) after first seeing a missing SL
    before taking action, giving the daemon/order adapter time to arm TPSL.
  - By default only acts on unmanaged/adopted/manual positions. Strategy-managed
    positions are left to the daemon unless GUARDIAN_UNMANAGED_ONLY=0.
  - For each open position with stopLoss empty/missing, registers an emergency SL
    using the same ROE/leverage rules the daemon uses (loaded from
    strategy_override.approved.json).
  - Logs every gap event to quant_runtime/_safety_alerts.log so it is easy to
    audit how often the daemon-side path is failing.
  - Per-key 60s backoff after a failed placement to avoid hammering the API.

Stop with: touch scripts/_safety_guardian_stop
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _log(msg: str, log_path: Path, alert: bool = False) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if alert:
        try:
            alert_path = log_path.parent / "_safety_alerts.log"
            with alert_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def _load_override(project_root: Path) -> dict:
    p = project_root / "quant_runtime" / "artifacts" / "strategy_override.approved.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_latest_runtime_state(project_root: Path) -> dict:
    base = project_root / "quant_runtime" / "output" / "paper-live-shell"
    candidates = [base / "latest" / "summary.state.json"]
    try:
        candidates.extend(
            sorted(
                base.glob("*/summary.state.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        )
    except Exception:
        pass
    for path in candidates:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return {}


def _position_side(value: object) -> str:
    side = str(value or "").strip().lower()
    if side in {"buy", "long"}:
        return "long"
    if side in {"sell", "short"}:
        return "short"
    return side


def _position_key(symbol: object, side: object) -> str:
    normalized_symbol = str(symbol or "").strip().upper()
    normalized_side = _position_side(side)
    if not normalized_symbol or normalized_side not in {"long", "short"}:
        return ""
    return f"{normalized_symbol}:{normalized_side}"


def _runtime_position_key(row: dict) -> str:
    side = row.get("side", row.get("holdSide", row.get("posSide", "")))
    return _position_key(row.get("symbol", ""), side)


def _is_strategy_managed_runtime_position(row: dict) -> bool:
    origin = str(row.get("origin", "strategy") or "strategy").strip().lower()
    if origin == "adopted":
        return False
    if row.get("adopted_at") is not None:
        return False
    if str(row.get("adoption_source", "") or "").strip():
        return False
    return True


def _strategy_managed_position_keys(runtime_state: dict) -> set[str]:
    keys: set[str] = set()
    for row in runtime_state.get("paper_open_futures_positions", []) or []:
        if not isinstance(row, dict):
            continue
        if not _is_strategy_managed_runtime_position(row):
            continue
        key = _runtime_position_key(row)
        if key:
            keys.add(key)
    return keys


def _stop_fraction(override: dict) -> float:
    """Return SL distance as a price fraction, derived from ROE% / leverage."""
    risk = override.get("risk", {}) or {}
    leverage = float(risk.get("target_futures_leverage", 20.0)) or 20.0
    pos_risk = override.get("live_position_risk", {}) or {}
    sl_roe = abs(float(pos_risk.get("stop_loss_roe_percent", -10.0)))  # -10 -> 10
    return (sl_roe / leverage) / 100.0  # percent -> fraction


def _format_price(adapter, symbol: str, value: float) -> str:
    try:
        return adapter.format_trigger_price(value=value, market="futures", symbol=symbol)
    except Exception:
        return f"{value:.8g}"


def _build_sl_payload(symbol: str, hold_side: str, sl_price_str: str, oid: str) -> dict:
    return {
        "marginCoin": "USDT",
        "productType": "USDT-FUTURES",
        "symbol": symbol,
        "stopLossTriggerPrice": sl_price_str,
        "stopLossTriggerType": "mark_price",
        "holdSide": hold_side,
        "stopLossClientOid": oid,
    }


def _plan_order_stop_loss(client, *, symbol: str, hold_side: str) -> str | None:
    """Return live loss-plan stop price for (symbol, hold_side) if present."""
    if not hasattr(client, "get_futures_pending_plan_orders"):
        return None
    try:
        pending = client.get_futures_pending_plan_orders(symbol=symbol, plan_type="profit_loss")
    except Exception:
        return None
    rows = pending.get("orders", []) if isinstance(pending, dict) else []
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
        if str(row.get("planType", "")).lower() != "loss_plan":
            continue
        value = str(row.get("stopLossTriggerPrice") or row.get("triggerPrice") or "").strip()
        if value:
            return value
    return None


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    runtime = project_root / "quant_runtime"
    log_path = runtime / "_safety_guardian.log"
    stop_file = project_root / "scripts" / "_safety_guardian_stop"

    _load_dotenv(project_root / ".env")
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    interval = int(os.environ.get("GUARDIAN_INTERVAL", "20"))
    grace_seconds = int(os.environ.get("GUARDIAN_GRACE_SECONDS", "60"))
    unmanaged_only = os.environ.get("GUARDIAN_UNMANAGED_ONLY", "1").strip().lower() not in {"0", "false", "no", "off"}

    from quant_binance.execution.client_factory import build_exchange_rest_client
    from quant_binance.execution.live_order_adapter import DecisionLiveOrderAdapter

    client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True)
    adapter = DecisionLiveOrderAdapter(client, None)

    _log(
        f"guardian starting; interval={interval}s grace={grace_seconds}s unmanaged_only={unmanaged_only}",
        log_path,
    )

    fail_counts: dict[str, int] = {}
    last_attempt: dict[str, float] = {}
    gap_first_seen: dict[str, float] = {}
    backoff_seconds = 60

    while True:
        if stop_file.exists():
            _log("stop file present; exiting", log_path)
            return 0

        override = _load_override(project_root)
        stop_fraction = _stop_fraction(override)
        runtime_state = _load_latest_runtime_state(project_root) if unmanaged_only else {}
        managed_keys = _strategy_managed_position_keys(runtime_state) if unmanaged_only else set()
        try:
            pos_resp = client.send(client.build_positions_request())
        except Exception as exc:
            _log(f"positions fetch failed: {exc!r}", log_path)
            time.sleep(interval)
            continue

        if pos_resp.get("code") != "00000":
            _log(f"positions resp non-OK: {str(pos_resp)[:200]}", log_path)
            time.sleep(interval)
            continue

        for p in pos_resp.get("data") or []:
            try:
                qty = float(p.get("total") or 0)
            except Exception:
                qty = 0.0
            if qty <= 0:
                continue
            symbol = p.get("symbol")
            hold_side = (p.get("holdSide") or "").lower()
            entry_str = p.get("openPriceAvg") or p.get("averageOpenPrice")
            mark_str = p.get("markPrice")
            sl_field = p.get("stopLoss") or ""
            try:
                entry = float(entry_str)
                mark = float(mark_str)
            except Exception:
                continue
            try:
                sl_set = float(sl_field) if sl_field else 0.0
            except Exception:
                sl_set = 0.0
            key = f"{symbol}:{hold_side}"

            if sl_set > 0:
                if key in fail_counts:
                    _log(f"OK {key} now has SL={sl_set}", log_path)
                fail_counts.pop(key, None)
                last_attempt.pop(key, None)
                gap_first_seen.pop(key, None)
                continue

            # Bitget commonly stores protection as TPSL plan orders instead of
            # inline position.stopLoss. Treat live loss_plan as protected state.
            plan_sl = _plan_order_stop_loss(client, symbol=symbol, hold_side=hold_side)
            if plan_sl:
                fail_counts.pop(key, None)
                last_attempt.pop(key, None)
                gap_first_seen.pop(key, None)
                continue

            now_s = time.time()
            first_seen = gap_first_seen.setdefault(key, now_s)
            elapsed = now_s - first_seen
            if elapsed < grace_seconds:
                # Give daemon/order pipeline time to register protection before
                # guardian intervenes (prevents SL overwrite loops).
                continue
            if unmanaged_only and key.upper() in {item.upper() for item in managed_keys}:
                # The daemon owns protection and exits for strategy positions.
                # Guardian remains a backstop for manual/adopted/unmanaged gaps.
                continue
            if key in last_attempt and (now_s - last_attempt[key]) < backoff_seconds:
                continue

            if hold_side == "long":
                sl_price = entry * (1.0 - stop_fraction)
                if sl_price >= mark:
                    sl_price = mark * (1.0 - stop_fraction)
            elif hold_side == "short":
                sl_price = entry * (1.0 + stop_fraction)
                if sl_price <= mark:
                    sl_price = mark * (1.0 + stop_fraction)
            else:
                continue

            sl_price_str = _format_price(adapter, symbol, sl_price)
            oid = f"guardian-{symbol[:10]}-{hold_side}-{uuid.uuid4().hex[:8]}"
            payload = _build_sl_payload(symbol, hold_side, sl_price_str, oid)

            _log(
                f"GAP {key} qty={qty} entry={entry} mark={mark} stop_fraction={stop_fraction:.6f} "
                f"-> registering SL={sl_price_str} (oid={oid})",
                log_path,
                alert=True,
            )
            try:
                result = client.place_futures_position_tpsl(order_params=payload)
                _log(f"SL placed for {key}: {str(result)[:200]}", log_path)
                fail_counts.pop(key, None)
                last_attempt.pop(key, None)
            except Exception as exc:
                fail_counts[key] = fail_counts.get(key, 0) + 1
                last_attempt[key] = now_s
                _log(
                    f"SL placement FAILED for {key} (count={fail_counts[key]}): {exc!r}",
                    log_path,
                    alert=True,
                )

        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
