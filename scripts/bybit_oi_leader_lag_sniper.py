#!/usr/bin/env python3
"""Paper-only Bybit OI leader-lag sniper.

This scanner is deliberately orthogonal to the prior candle-breakout family:
it samples Bybit public ticker open interest, price, and account long/short
ratio, converts short-horizon OI/price deltas into OI quadrants, then emits
paper-only candidates for a small hand-picked leader-lag experiment.

No private endpoint is used. No order endpoint is present in this file.
"""

from __future__ import annotations

import argparse
import json
import ssl
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "quant_runtime_paper50" / "bybit_oi_leader_lag_sniper"
BASE_URL = "https://api.bybit.com"

DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "1000PEPEUSDT")
SYMBOL_ALIASES = {"PEPEUSDT": "1000PEPEUSDT"}
LEADER_MAP = {
    "ETHUSDT": ("BTCUSDT",),
    "1000PEPEUSDT": ("BTCUSDT", "ETHUSDT"),
    "DOGEUSDT": ("BTCUSDT",),
}
HORIZONS = (15, 30, 60)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _ret_bps(new: float, old: float) -> float:
    if old <= 0.0:
        return 0.0
    return ((new / old) - 1.0) * 10000.0


def _pct_change(new: float, old: float) -> float:
    if old <= 0.0:
        return 0.0
    return ((new / old) - 1.0) * 100.0


def quadrant(price_delta_bps: float, oi_delta_pct: float) -> str:
    price_up = price_delta_bps > 0.0
    oi_up = oi_delta_pct > 0.0
    if price_up and oi_up:
        return "newLongs"
    if price_up and not oi_up:
        return "shortCover"
    if not price_up and oi_up:
        return "newShorts"
    return "longUnwind"


def direction(price_delta_bps: float, *, neutral_bps: float) -> str:
    if abs(price_delta_bps) <= neutral_bps:
        return "neutral"
    return "up" if price_delta_bps > 0.0 else "down"


def is_bearish(state: "SymbolState", *, neutral_bps: float) -> bool:
    return state.quadrant in {"newShorts", "longUnwind"} and state.direction != "neutral" and abs(state.price_delta_bps) > neutral_bps


def is_weak_or_neutral(state: "SymbolState", *, neutral_bps: float) -> bool:
    return state.direction in {"down", "neutral"} or abs(state.price_delta_bps) <= neutral_bps


@dataclass(frozen=True)
class MetricRow:
    symbol: str
    timestamp: str
    last_price: float
    open_interest: float
    open_interest_value: float
    bid: float
    ask: float
    spread_bps: float
    buy_ratio: float | None
    sell_ratio: float | None
    account_long_short_ratio: float | None
    errors: dict[str, str]


@dataclass(frozen=True)
class SymbolState:
    symbol: str
    timestamp: str
    baseline_timestamp: str
    age_seconds: float
    last_price: float
    open_interest: float
    price_delta_bps: float
    oi_delta_pct: float
    quadrant: str
    direction: str
    buy_ratio: float | None
    sell_ratio: float | None
    account_long_short_ratio: float | None
    spread_bps: float


def _ssl_context(insecure_ssl: bool) -> ssl.SSLContext | None:
    if not insecure_ssl:
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _request_json(path: str, params: dict[str, Any], *, insecure_ssl: bool) -> dict[str, Any]:
    query = urlencode(sorted((key, value) for key, value in params.items() if value is not None))
    url = f"{BASE_URL}{path}?{query}" if query else f"{BASE_URL}{path}"
    req = Request(url=url, method="GET", headers={"User-Agent": "bybit-oi-leader-lag-sniper/1.0"})
    with urlopen(req, timeout=15, context=_ssl_context(insecure_ssl)) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if int(payload.get("retCode", -1)) != 0:
        raise RuntimeError(f"{path} retCode={payload.get('retCode')} retMsg={payload.get('retMsg')}")
    return payload


def _latest_from_list(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("result", {}).get("list", [])
    if not isinstance(rows, list) or not rows:
        return {}
    return rows[0] if isinstance(rows[0], dict) else {}


def _spread_bps(bid: float, ask: float, fallback_price: float) -> float:
    mid = (bid + ask) / 2.0 if bid > 0.0 and ask > 0.0 else fallback_price
    if bid <= 0.0 or ask <= 0.0 or mid <= 0.0:
        return 0.0
    return ((ask - bid) / mid) * 10000.0


def fetch_symbol_metrics(symbol: str, *, insecure_ssl: bool, sleep_seconds: float) -> MetricRow:
    errors: dict[str, str] = {}
    ticker: dict[str, Any] = {}
    ratio: dict[str, Any] = {}

    try:
        ticker = _latest_from_list(
            _request_json(
                "/v5/market/tickers",
                {"category": "linear", "symbol": symbol},
                insecure_ssl=insecure_ssl,
            )
        )
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
        errors["ticker"] = f"{type(exc).__name__}: {exc}"

    if sleep_seconds > 0:
        time.sleep(sleep_seconds)

    try:
        ratio = _latest_from_list(
            _request_json(
                "/v5/market/account-ratio",
                {"category": "linear", "symbol": symbol, "period": "5min", "limit": 1},
                insecure_ssl=insecure_ssl,
            )
        )
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
        errors["account_ratio"] = f"{type(exc).__name__}: {exc}"

    last = _safe_float(ticker.get("lastPrice") or ticker.get("markPrice"))
    bid = _safe_float(ticker.get("bid1Price"))
    ask = _safe_float(ticker.get("ask1Price"))
    buy_ratio = ratio.get("buyRatio")
    sell_ratio = ratio.get("sellRatio")
    buy = _safe_float(buy_ratio, -1.0)
    sell = _safe_float(sell_ratio, -1.0)
    return MetricRow(
        symbol=symbol,
        timestamp=_utc_now().isoformat(),
        last_price=last,
        open_interest=_safe_float(ticker.get("openInterest")),
        open_interest_value=_safe_float(ticker.get("openInterestValue")),
        bid=bid,
        ask=ask,
        spread_bps=round(_spread_bps(bid, ask, last), 6),
        buy_ratio=None if buy < 0.0 else buy,
        sell_ratio=None if sell < 0.0 else sell,
        account_long_short_ratio=None if buy < 0.0 or sell <= 0.0 else round(buy / sell, 6),
        errors=errors,
    )


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"snapshots": {}, "closed_candidate_ids": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"snapshots": {}, "closed_candidate_ids": []}
    payload.setdefault("snapshots", {})
    payload.setdefault("closed_candidate_ids", [])
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def update_snapshots(state: dict[str, Any], metrics: list[MetricRow], *, keep: int) -> None:
    snapshots = state.setdefault("snapshots", {})
    for row in metrics:
        items = list(snapshots.get(row.symbol, []))
        items.append(asdict(row))
        dedup: dict[str, dict[str, Any]] = {}
        for item in items:
            dedup[str(item.get("timestamp"))] = item
        snapshots[row.symbol] = sorted(dedup.values(), key=lambda item: str(item.get("timestamp")))[-keep:]
    state["updated_at"] = _utc_now().isoformat()
    state["paper_only"] = True
    state["public_endpoints_only"] = True
    state["live_orders_disabled"] = True


def _baseline_for(items: list[dict[str, Any]], now: datetime, *, lookback_seconds: int, tolerance_seconds: int) -> dict[str, Any] | None:
    target = now - timedelta(seconds=lookback_seconds)
    candidates: list[tuple[float, dict[str, Any]]] = []
    for item in items:
        try:
            ts = _parse_ts(str(item.get("timestamp")))
        except (TypeError, ValueError):
            continue
        age = (now - ts).total_seconds()
        if age <= 0.0:
            continue
        if abs((target - ts).total_seconds()) <= tolerance_seconds:
            candidates.append((abs((target - ts).total_seconds()), item))
    if not candidates:
        return None
    return sorted(candidates, key=lambda pair: pair[0])[0][1]


def build_states(
    state: dict[str, Any],
    metrics: list[MetricRow],
    *,
    lookback_seconds: int,
    tolerance_seconds: int,
    neutral_bps: float,
) -> dict[str, SymbolState]:
    out: dict[str, SymbolState] = {}
    snapshots = state.get("snapshots", {})
    for row in metrics:
        try:
            now = _parse_ts(row.timestamp)
        except ValueError:
            continue
        baseline = _baseline_for(
            list(snapshots.get(row.symbol, [])),
            now,
            lookback_seconds=lookback_seconds,
            tolerance_seconds=tolerance_seconds,
        )
        if not baseline:
            continue
        base_price = _safe_float(baseline.get("last_price"))
        base_oi = _safe_float(baseline.get("open_interest"))
        if row.last_price <= 0.0 or row.open_interest <= 0.0 or base_price <= 0.0 or base_oi <= 0.0:
            continue
        price_delta = _ret_bps(row.last_price, base_price)
        oi_delta = _pct_change(row.open_interest, base_oi)
        try:
            base_ts = _parse_ts(str(baseline.get("timestamp")))
        except ValueError:
            continue
        out[row.symbol] = SymbolState(
            symbol=row.symbol,
            timestamp=row.timestamp,
            baseline_timestamp=str(baseline.get("timestamp")),
            age_seconds=round((now - base_ts).total_seconds(), 3),
            last_price=row.last_price,
            open_interest=row.open_interest,
            price_delta_bps=round(price_delta, 6),
            oi_delta_pct=round(oi_delta, 8),
            quadrant=quadrant(price_delta, oi_delta),
            direction=direction(price_delta, neutral_bps=neutral_bps),
            buy_ratio=row.buy_ratio,
            sell_ratio=row.sell_ratio,
            account_long_short_ratio=row.account_long_short_ratio,
            spread_bps=row.spread_bps,
        )
    return out


def _move_is_big_enough(st: SymbolState, *, min_price_delta_bps: float, min_oi_delta_pct: float) -> bool:
    return abs(st.price_delta_bps) >= min_price_delta_bps and abs(st.oi_delta_pct) >= min_oi_delta_pct


def _candidate(
    *,
    strategy: str,
    symbol: str,
    side: str,
    score: float,
    state: SymbolState,
    leaders: list[SymbolState],
    reasons: list[str],
    tp_bps: float,
    sl_bps: float,
    time_stop_minutes: int,
) -> dict[str, Any]:
    return {
        "timestamp": state.timestamp,
        "symbol": symbol,
        "strategy": strategy,
        "side": side,
        "score": round(score, 6),
        "reference_price": state.last_price,
        "paper_only": True,
        "public_endpoints_only": True,
        "live_orders_disabled": True,
        "tp_bps": tp_bps,
        "sl_bps": sl_bps,
        "time_stop_minutes": time_stop_minutes,
        "leader_symbols": [leader.symbol for leader in leaders],
        "reasons": reasons,
        "state": asdict(state),
        "leader_states": [asdict(leader) for leader in leaders],
    }


def generate_candidates(
    states: dict[str, SymbolState],
    *,
    profile: str,
    neutral_bps: float,
    min_price_delta_bps: float,
    min_oi_delta_pct: float,
    max_spread_bps: float,
    tp_bps: float,
    sl_bps: float,
    time_stop_minutes: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    btc = states.get("BTCUSDT")
    eth = states.get("ETHUSDT")
    pepe = states.get("1000PEPEUSDT") or states.get("PEPEUSDT")
    doge = states.get("DOGEUSDT")

    if profile == "strict-pepe":
        doge = None

    if profile == "exploratory" and eth and btc and eth.spread_bps <= max_spread_bps and _move_is_big_enough(eth, min_price_delta_bps=min_price_delta_bps, min_oi_delta_pct=min_oi_delta_pct):
        if eth.quadrant == "newLongs" and not is_bearish(btc, neutral_bps=neutral_bps):
            score = 60.0 + max(eth.price_delta_bps, 0.0) * 0.15 + max(eth.oi_delta_pct, 0.0) * 40.0
            out.append(
                _candidate(
                    strategy="eth_new_longs_leader_not_bearish",
                    symbol="ETHUSDT",
                    side="long",
                    score=score,
                    state=eth,
                    leaders=[btc],
                    reasons=["ETH newLongs", "BTC leader not bearish", "paper-only sample collection"],
                    tp_bps=tp_bps,
                    sl_bps=sl_bps,
                    time_stop_minutes=time_stop_minutes,
                )
            )

    if (
        pepe
        and btc
        and eth
        and pepe.spread_bps <= max_spread_bps
        and _move_is_big_enough(pepe, min_price_delta_bps=min_price_delta_bps, min_oi_delta_pct=min_oi_delta_pct)
        and pepe.quadrant == "newLongs"
        and btc.quadrant == "newLongs"
        and eth.quadrant == "newLongs"
    ):
        score = 70.0 + max(pepe.price_delta_bps, 0.0) * 0.12 + max(pepe.oi_delta_pct, 0.0) * 50.0
        out.append(
            _candidate(
                strategy="pepe_new_longs_btc_eth_new_longs",
                symbol=pepe.symbol,
                side="long",
                score=score,
                state=pepe,
                leaders=[btc, eth],
                reasons=["PEPE newLongs", "BTC newLongs", "ETH newLongs", "leader-lag alignment"],
                tp_bps=tp_bps,
                sl_bps=sl_bps,
                time_stop_minutes=time_stop_minutes,
            )
        )

    if profile == "exploratory" and (
        doge
        and btc
        and doge.spread_bps <= max_spread_bps
        and _move_is_big_enough(doge, min_price_delta_bps=min_price_delta_bps, min_oi_delta_pct=min_oi_delta_pct)
        and doge.quadrant == "newShorts"
        and is_weak_or_neutral(btc, neutral_bps=neutral_bps)
    ):
        score = 62.0 + max(-doge.price_delta_bps, 0.0) * 0.14 + max(doge.oi_delta_pct, 0.0) * 45.0
        out.append(
            _candidate(
                strategy="doge_new_shorts_btc_weak_or_neutral",
                symbol="DOGEUSDT",
                side="short",
                score=score,
                state=doge,
                leaders=[btc],
                reasons=["DOGE newShorts", "BTC weak or neutral", "short-side OI expansion"],
                tp_bps=tp_bps,
                sl_bps=sl_bps,
                time_stop_minutes=time_stop_minutes,
            )
        )

    return sorted(out, key=lambda item: float(item["score"]), reverse=True)


def filter_cooldown(
    candidates: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    *,
    cooldown_minutes: int,
) -> list[dict[str, Any]]:
    if cooldown_minutes <= 0:
        return candidates
    latest_by_key: dict[str, datetime] = {}
    for row in existing:
        key = f"{row.get('symbol')}|{row.get('strategy')}|{row.get('side')}"
        try:
            ts = _parse_ts(str(row.get("timestamp")))
        except ValueError:
            continue
        if key not in latest_by_key or ts > latest_by_key[key]:
            latest_by_key[key] = ts

    out: list[dict[str, Any]] = []
    for row in candidates:
        key = f"{row.get('symbol')}|{row.get('strategy')}|{row.get('side')}"
        try:
            ts = _parse_ts(str(row.get("timestamp")))
        except ValueError:
            continue
        latest = latest_by_key.get(key)
        if latest is not None and ts - latest < timedelta(minutes=cooldown_minutes):
            continue
        latest_by_key[key] = ts
        out.append(row)
    return out


def explain_no_entry(
    states: dict[str, SymbolState],
    *,
    profile: str,
    min_price_delta_bps: float,
    min_oi_delta_pct: float,
    max_spread_bps: float,
) -> list[str]:
    if profile != "strict-pepe":
        return ["exploratory_profile_no_primary_signal"]
    reasons: list[str] = []
    btc = states.get("BTCUSDT")
    eth = states.get("ETHUSDT")
    pepe = states.get("1000PEPEUSDT") or states.get("PEPEUSDT")
    if btc is None:
        reasons.append("missing_btc_state")
    if eth is None:
        reasons.append("missing_eth_state")
    if pepe is None:
        reasons.append("missing_1000pepe_state")
    if not btc or not eth or not pepe:
        return reasons
    if pepe.spread_bps > max_spread_bps:
        reasons.append("pepe_spread_too_wide")
    if abs(pepe.price_delta_bps) < min_price_delta_bps:
        reasons.append("pepe_price_delta_too_small")
    if abs(pepe.oi_delta_pct) < min_oi_delta_pct:
        reasons.append("pepe_oi_delta_too_small")
    if pepe.quadrant != "newLongs":
        reasons.append(f"pepe_not_newLongs:{pepe.quadrant}")
    if btc.quadrant != "newLongs":
        reasons.append(f"btc_not_newLongs:{btc.quadrant}")
    if eth.quadrant != "newLongs":
        reasons.append(f"eth_not_newLongs:{eth.quadrant}")
    return reasons or ["eligible_but_filtered_elsewhere"]


def _candidate_id(row: dict[str, Any]) -> str:
    return "|".join([str(row.get("timestamp")), str(row.get("symbol")), str(row.get("strategy")), str(row.get("side"))])


def open_paper_position(candidate: dict[str, Any]) -> dict[str, Any]:
    position = dict(candidate)
    position.update(
        {
            "position_id": _candidate_id(candidate),
            "opened_at": candidate.get("timestamp"),
            "entry_price": candidate.get("reference_price"),
            "status": "open",
            "paper_only": True,
            "public_endpoints_only": True,
            "live_orders_disabled": True,
        }
    )
    return position


def _paper_exit_payload(position: dict[str, Any], *, exit_price: float, exit_reason: str, exit_ts: str) -> dict[str, Any]:
    payload = _exit_payload(position, exit_price, exit_reason, exit_ts)
    payload["position_id"] = position.get("position_id") or _candidate_id(position)
    payload["opened_at"] = position.get("opened_at") or position.get("timestamp")
    return payload


def _current_ret_bps(position: dict[str, Any], price: float) -> float:
    ref = _safe_float(position.get("entry_price") or position.get("reference_price"))
    side = str(position.get("side") or "long")
    sign = -1.0 if side == "short" else 1.0
    return sign * _ret_bps(price, ref)


def _leader_reversed_now(position: dict[str, Any], states: dict[str, SymbolState]) -> tuple[bool, str]:
    side = str(position.get("side") or "long")
    for leader_symbol in [str(item) for item in position.get("leader_symbols", [])]:
        leader = states.get(leader_symbol)
        if leader is None:
            continue
        if side == "long" and leader.quadrant in {"newShorts", "longUnwind"} and leader.direction == "down":
            return True, f"leader_reversal:{leader_symbol}:{leader.quadrant}:{leader.direction}"
        if side == "short" and leader.quadrant in {"newLongs", "shortCover"} and leader.direction == "up":
            return True, f"leader_reversal:{leader_symbol}:{leader.quadrant}:{leader.direction}"
    return False, ""


def monitor_active_position(
    position: dict[str, Any],
    states: dict[str, SymbolState],
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    now = now or _utc_now()
    symbol = str(position.get("symbol") or "")
    current = states.get(symbol)
    base_event = {
        "timestamp": now.isoformat(),
        "position_id": position.get("position_id") or _candidate_id(position),
        "symbol": symbol,
        "strategy": position.get("strategy"),
        "side": position.get("side"),
        "paper_only": True,
        "live_orders_disabled": True,
    }
    if current is None or current.last_price <= 0.0:
        event = {**base_event, "action": "hold", "reason": "current_price_unavailable"}
        return event, None

    ret_bps = _current_ret_bps(position, current.last_price)
    event = {
        **base_event,
        "current_price": current.last_price,
        "unrealized_ret_bps": round(ret_bps, 6),
        "current_state": asdict(current),
    }
    tp_bps = _safe_float(position.get("tp_bps"), 60.0)
    sl_bps = _safe_float(position.get("sl_bps"), 25.0)
    if ret_bps >= tp_bps:
        outcome = _paper_exit_payload(position, exit_price=current.last_price, exit_reason="tp_live_paper", exit_ts=now.isoformat())
        return {**event, "action": "exit", "reason": "tp_live_paper"}, outcome
    if ret_bps <= -sl_bps:
        outcome = _paper_exit_payload(position, exit_price=current.last_price, exit_reason="sl_live_paper", exit_ts=now.isoformat())
        return {**event, "action": "exit", "reason": "sl_live_paper"}, outcome

    reversed_now, reason = _leader_reversed_now(position, states)
    if reversed_now:
        outcome = _paper_exit_payload(position, exit_price=current.last_price, exit_reason=reason, exit_ts=now.isoformat())
        return {**event, "action": "exit", "reason": reason}, outcome

    try:
        opened_at = _parse_ts(str(position.get("opened_at") or position.get("timestamp")))
    except ValueError:
        opened_at = now
    if now >= opened_at + timedelta(minutes=int(position.get("time_stop_minutes") or 60)):
        outcome = _paper_exit_payload(position, exit_price=current.last_price, exit_reason="time_stop_live_paper", exit_ts=now.isoformat())
        return {**event, "action": "exit", "reason": "time_stop_live_paper"}, outcome

    return {**event, "action": "hold", "reason": "no_exit_condition"}, None


def fetch_klines(symbol: str, *, start_ms: int, end_ms: int, insecure_ssl: bool) -> list[dict[str, float]]:
    payload = _request_json(
        "/v5/market/kline",
        {
            "category": "linear",
            "symbol": symbol,
            "interval": "1",
            "start": start_ms,
            "end": end_ms,
            "limit": 200,
        },
        insecure_ssl=insecure_ssl,
    )
    rows = payload.get("result", {}).get("list", [])
    out: list[dict[str, float]] = []
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, list) or len(item) < 5:
            continue
        out.append(
            {
                "open_time": float(item[0]),
                "open": _safe_float(item[1]),
                "high": _safe_float(item[2]),
                "low": _safe_float(item[3]),
                "close": _safe_float(item[4]),
            }
        )
    return sorted(out, key=lambda item: item["open_time"])


def _leader_reversal_exit(
    candidate: dict[str, Any],
    snapshots: dict[str, list[dict[str, Any]]],
    *,
    neutral_bps: float,
) -> tuple[str, float] | None:
    entry_ts = _parse_ts(str(candidate["timestamp"]))
    side = str(candidate.get("side"))
    symbol = str(candidate.get("symbol"))
    target_items = list(snapshots.get(symbol, []))
    leaders = [str(item) for item in candidate.get("leader_symbols", [])]
    if not leaders or not target_items:
        return None

    for leader in leaders:
        items = list(snapshots.get(leader, []))
        items.sort(key=lambda item: str(item.get("timestamp")))
        previous: dict[str, Any] | None = None
        for item in items:
            try:
                ts = _parse_ts(str(item.get("timestamp")))
            except ValueError:
                continue
            if ts <= entry_ts:
                previous = item
                continue
            if previous is None:
                previous = item
                continue
            cur_px = _safe_float(item.get("last_price"))
            prv_px = _safe_float(previous.get("last_price"))
            cur_oi = _safe_float(item.get("open_interest"))
            prv_oi = _safe_float(previous.get("open_interest"))
            if cur_px <= 0.0 or prv_px <= 0.0 or cur_oi <= 0.0 or prv_oi <= 0.0:
                previous = item
                continue
            p_delta = _ret_bps(cur_px, prv_px)
            q = quadrant(p_delta, _pct_change(cur_oi, prv_oi))
            d = direction(p_delta, neutral_bps=neutral_bps)
            reversed_for_long = side == "long" and (q in {"newShorts", "longUnwind"} and d == "down")
            reversed_for_short = side == "short" and (q in {"newLongs", "shortCover"} and d == "up")
            if reversed_for_long or reversed_for_short:
                target_px = _nearest_snapshot_price(target_items, ts)
                if target_px > 0.0:
                    return ts.isoformat(), target_px
            previous = item
    return None


def _nearest_snapshot_price(items: list[dict[str, Any]], ts: datetime) -> float:
    best: tuple[float, float] | None = None
    for item in items:
        try:
            item_ts = _parse_ts(str(item.get("timestamp")))
        except ValueError:
            continue
        delta = abs((item_ts - ts).total_seconds())
        px = _safe_float(item.get("last_price"))
        if px <= 0.0:
            continue
        if best is None or delta < best[0]:
            best = (delta, px)
    return 0.0 if best is None else best[1]


def simulate_exit(
    candidate: dict[str, Any],
    bars: list[dict[str, float]],
    *,
    leader_exit: tuple[str, float] | None = None,
) -> dict[str, Any] | None:
    ref = _safe_float(candidate.get("reference_price"))
    if ref <= 0.0 or not bars:
        return None
    side = str(candidate.get("side") or "long")
    sign = -1.0 if side == "short" else 1.0
    tp_bps = _safe_float(candidate.get("tp_bps"), 45.0)
    sl_bps = _safe_float(candidate.get("sl_bps"), 22.0)
    entry_ts = _parse_ts(str(candidate["timestamp"]))
    time_stop_minutes = int(candidate.get("time_stop_minutes") or 15)
    stop_ts = entry_ts + timedelta(minutes=time_stop_minutes)
    tp = ref * (1.0 + sign * tp_bps / 10000.0)
    sl = ref * (1.0 - sign * sl_bps / 10000.0)

    leader_dt = _parse_ts(leader_exit[0]) if leader_exit else None
    for bar in bars:
        bar_ts = datetime.fromtimestamp(float(bar["open_time"]) / 1000.0, tz=UTC)
        if leader_dt is not None and bar_ts >= leader_dt:
            close = float(leader_exit[1])
            return _exit_payload(candidate, close, "leader_reversal", leader_dt.isoformat())
        high = float(bar["high"])
        low = float(bar["low"])
        if side == "long":
            hit_sl = low <= sl
            hit_tp = high >= tp
        else:
            hit_sl = high >= sl
            hit_tp = low <= tp
        if hit_sl and hit_tp:
            return _exit_payload(candidate, sl, "sl_conservative_same_bar", bar_ts.isoformat())
        if hit_sl:
            return _exit_payload(candidate, sl, "sl", bar_ts.isoformat())
        if hit_tp:
            return _exit_payload(candidate, tp, "tp", bar_ts.isoformat())
        if bar_ts >= stop_ts:
            return _exit_payload(candidate, float(bar["close"]), "time_stop", bar_ts.isoformat())
    return None


def _exit_payload(candidate: dict[str, Any], exit_price: float, reason: str, exit_ts: str) -> dict[str, Any]:
    ref = _safe_float(candidate.get("reference_price"))
    side = str(candidate.get("side") or "long")
    sign = -1.0 if side == "short" else 1.0
    ret = sign * _ret_bps(exit_price, ref)
    leverage = 30.0
    return {
        "candidate_id": _candidate_id(candidate),
        "timestamp": candidate.get("timestamp"),
        "exit_timestamp": exit_ts,
        "symbol": candidate.get("symbol"),
        "strategy": candidate.get("strategy"),
        "side": side,
        "reference_price": ref,
        "exit_price": exit_price,
        "exit_reason": reason,
        "ret_bps": round(ret, 6),
        "roe_bps_30x": round(ret * leverage, 6),
        "paper_only": True,
    }


def evaluate_mature_candidates(output_dir: Path, state: dict[str, Any], *, insecure_ssl: bool, neutral_bps: float) -> list[dict[str, Any]]:
    candidates_path = output_dir / "bybit_oi_sniper_candidates.jsonl"
    rows = _load_jsonl(candidates_path)
    closed_ids = set(str(item) for item in state.get("closed_candidate_ids", []))
    active = state.get("active_position")
    active_id = str(active.get("position_id") or _candidate_id(active)) if isinstance(active, dict) and active.get("status") == "open" else ""
    now = _utc_now()
    outcomes: list[dict[str, Any]] = _load_jsonl(output_dir / "bybit_oi_sniper_outcomes.jsonl")
    known_outcome_ids = {_candidate_id(row) for row in outcomes}
    for row in rows:
        cid = _candidate_id(row)
        if cid == active_id or cid in closed_ids or cid in known_outcome_ids:
            continue
        try:
            ts = _parse_ts(str(row.get("timestamp")))
        except ValueError:
            continue
        if ts > now - timedelta(minutes=int(row.get("time_stop_minutes") or 15)):
            continue
        symbol = str(row.get("symbol") or "")
        start_ms = int(ts.timestamp() * 1000)
        end_ms = int((ts + timedelta(minutes=int(row.get("time_stop_minutes") or 15) + 2)).timestamp() * 1000)
        try:
            bars = fetch_klines(symbol, start_ms=start_ms, end_ms=end_ms, insecure_ssl=insecure_ssl)
        except Exception:
            continue
        leader_exit = _leader_reversal_exit(row, state.get("snapshots", {}), neutral_bps=neutral_bps)
        outcome = simulate_exit(row, bars, leader_exit=leader_exit)
        if outcome:
            _append_jsonl(output_dir / "bybit_oi_sniper_outcomes.jsonl", outcome)
            outcomes.append(outcome)
            closed_ids.add(cid)
    state["closed_candidate_ids"] = sorted(closed_ids)
    return outcomes


def summarize(candidates: list[dict[str, Any]], outcomes: list[dict[str, Any]], states: dict[str, SymbolState]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in outcomes:
        key = f"{row.get('symbol')}|{row.get('strategy')}|{row.get('side')}"
        groups.setdefault(key, []).append(row)
    outcome_summary: dict[str, Any] = {}
    for key, rows in sorted(groups.items()):
        values = [_safe_float(row.get("ret_bps")) for row in rows]
        outcome_summary[key] = {
            "count": len(values),
            "avg_ret_bps": round(sum(values) / len(values), 6) if values else 0.0,
            "win_rate": round(sum(1 for value in values if value > 0.0) / len(values), 6) if values else 0.0,
            "recent5_ret_bps": [round(value, 6) for value in values[-5:]],
            "latest_ret_bps": round(values[-1], 6) if values else None,
        }
    return {
        "generated_at": _utc_now().isoformat(),
        "paper_only": True,
        "public_endpoints_only": True,
        "live_orders_disabled": True,
        "state_count": len(states),
        "candidate_count": len(candidates),
        "mature_outcome_count": len(outcomes),
        "current_states": {symbol: asdict(state) for symbol, state in sorted(states.items())},
        "top_current_candidates": candidates[:10],
        "outcome_summary": outcome_summary,
    }


def _decision_event(
    *,
    action: str,
    reason: str,
    states: dict[str, SymbolState],
    active_position: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "timestamp": _utc_now().isoformat(),
        "action": action,
        "reason": reason,
        "paper_only": True,
        "live_orders_disabled": True,
        "active_position": active_position,
        "candidate_count": len(candidates),
        "top_candidate": candidates[0] if candidates else None,
        "state_symbols": sorted(states),
    }


def run_cycle(
    output_dir: Path,
    *,
    symbols: tuple[str, ...],
    profile: str,
    insecure_ssl: bool,
    sleep_seconds: float,
    lookback_seconds: int,
    tolerance_seconds: int,
    neutral_bps: float,
    min_price_delta_bps: float,
    min_oi_delta_pct: float,
    max_spread_bps: float,
    tp_bps: float,
    sl_bps: float,
    time_stop_minutes: int,
    cooldown_minutes: int,
) -> dict[str, Any]:
    state_path = output_dir / "state.json"
    state = _load_state(state_path)
    metrics = [fetch_symbol_metrics(symbol, insecure_ssl=insecure_ssl, sleep_seconds=sleep_seconds) for symbol in symbols]
    update_snapshots(state, metrics, keep=600)
    states = build_states(
        state,
        metrics,
        lookback_seconds=lookback_seconds,
        tolerance_seconds=tolerance_seconds,
        neutral_bps=neutral_bps,
    )
    now_tag = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    cycle_dir = output_dir / f"cycle_{now_tag}"
    active_position = state.get("active_position")
    candidates: list[dict[str, Any]] = []
    decision: dict[str, Any]

    if isinstance(active_position, dict) and active_position.get("status") == "open":
        event, outcome = monitor_active_position(active_position, states)
        _append_jsonl(output_dir / "paper_position_events.jsonl", event)
        if outcome:
            _append_jsonl(output_dir / "bybit_oi_sniper_outcomes.jsonl", outcome)
            state["active_position"] = None
            state.setdefault("closed_candidate_ids", []).append(str(outcome.get("candidate_id")))
            decision = _decision_event(
                action="paper_exit",
                reason=str(outcome.get("exit_reason")),
                states=states,
                active_position=None,
                candidates=[],
            )
        else:
            decision = _decision_event(
                action="paper_hold",
                reason=str(event.get("reason")),
                states=states,
                active_position=active_position,
                candidates=[],
            )
    else:
        candidates = generate_candidates(
            states,
            profile=profile,
            neutral_bps=neutral_bps,
            min_price_delta_bps=min_price_delta_bps,
            min_oi_delta_pct=min_oi_delta_pct,
            max_spread_bps=max_spread_bps,
            tp_bps=tp_bps,
            sl_bps=sl_bps,
            time_stop_minutes=time_stop_minutes,
        )
        existing_candidates = _load_jsonl(output_dir / "bybit_oi_sniper_candidates.jsonl")
        candidates = filter_cooldown(candidates, existing_candidates, cooldown_minutes=cooldown_minutes)
        if candidates:
            for row in candidates:
                _append_jsonl(output_dir / "bybit_oi_sniper_candidates.jsonl", row)
            position = open_paper_position(candidates[0])
            state["active_position"] = position
            _append_jsonl(
                output_dir / "paper_position_events.jsonl",
                {
                    "timestamp": _utc_now().isoformat(),
                    "action": "open",
                    "reason": "top_candidate",
                    "position": position,
                    "paper_only": True,
                    "live_orders_disabled": True,
                },
            )
            decision = _decision_event(
                action="paper_open",
                reason=str(candidates[0].get("strategy")),
                states=states,
                active_position=position,
                candidates=candidates,
            )
        else:
            no_entry_reasons = explain_no_entry(
                states,
                profile=profile,
                min_price_delta_bps=min_price_delta_bps,
                min_oi_delta_pct=min_oi_delta_pct,
                max_spread_bps=max_spread_bps,
            )
            decision = _decision_event(
                action="no_entry",
                reason=",".join(no_entry_reasons),
                states=states,
                active_position=None,
                candidates=[],
            )

    _write_json(cycle_dir / "metrics.json", {"generated_at": _utc_now().isoformat(), "rows": [asdict(row) for row in metrics]})
    _write_json(cycle_dir / "states.json", {"generated_at": _utc_now().isoformat(), "states": {k: asdict(v) for k, v in states.items()}})
    _write_json(cycle_dir / "candidate_matrix.json", {"generated_at": _utc_now().isoformat(), "candidates": candidates})
    _write_json(cycle_dir / "decision.json", decision)
    _append_jsonl(output_dir / "paper_decisions.jsonl", decision)
    outcomes = evaluate_mature_candidates(output_dir, state, insecure_ssl=insecure_ssl, neutral_bps=neutral_bps)
    summary = summarize(_load_jsonl(output_dir / "bybit_oi_sniper_candidates.jsonl"), outcomes, states)
    summary["profile"] = profile
    summary["active_position"] = state.get("active_position")
    summary["latest_decision"] = decision
    summary["latest_cycle_dir"] = str(cycle_dir)
    _write_json(output_dir / "status.json", summary)
    _write_json(state_path, state)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, default=_json_default), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Bybit OI leader-lag paper-only sniper.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--profile", choices=("strict-pepe", "exploratory"), default="strict-pepe")
    parser.add_argument("--duration-minutes", type=int, default=0)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--lookback-seconds", type=int, default=120)
    parser.add_argument("--tolerance-seconds", type=int, default=75)
    parser.add_argument("--neutral-bps", type=float, default=1.5)
    parser.add_argument("--min-price-delta-bps", type=float, default=1.0)
    parser.add_argument("--min-oi-delta-pct", type=float, default=0.01)
    parser.add_argument("--max-spread-bps", type=float, default=3.0)
    parser.add_argument("--tp-bps", type=float, default=60.0)
    parser.add_argument("--sl-bps", type=float, default=25.0)
    parser.add_argument("--time-stop-minutes", type=int, default=60)
    parser.add_argument("--cooldown-minutes", type=int, default=60)
    parser.add_argument("--request-sleep-seconds", type=float, default=0.05)
    parser.add_argument("--insecure-ssl", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    symbols = tuple(SYMBOL_ALIASES.get(item.strip().upper(), item.strip().upper()) for item in args.symbols.split(",") if item.strip())
    process = {
        "started_at": _utc_now().isoformat(),
        "paper_only": True,
        "public_endpoints_only": True,
        "live_orders_disabled": True,
        "exchange": "bybit",
        "duration_minutes": args.duration_minutes,
        "interval_seconds": args.interval_seconds,
        "symbols": symbols,
        "strategy": "bybit_oi_leader_lag_sniper",
        "profile": args.profile,
    }
    _write_json(output_dir / "process.json", process)
    end_at = _utc_now() + timedelta(minutes=args.duration_minutes) if args.duration_minutes > 0 else None
    while True:
        run_cycle(
            output_dir,
            symbols=symbols,
            profile=args.profile,
            insecure_ssl=args.insecure_ssl,
            sleep_seconds=args.request_sleep_seconds,
            lookback_seconds=args.lookback_seconds,
            tolerance_seconds=args.tolerance_seconds,
            neutral_bps=args.neutral_bps,
            min_price_delta_bps=args.min_price_delta_bps,
            min_oi_delta_pct=args.min_oi_delta_pct,
            max_spread_bps=args.max_spread_bps,
            tp_bps=args.tp_bps,
            sl_bps=args.sl_bps,
            time_stop_minutes=args.time_stop_minutes,
            cooldown_minutes=args.cooldown_minutes,
        )
        if end_at is None or _utc_now() >= end_at:
            break
        time.sleep(min(args.interval_seconds, max(1, int((end_at - _utc_now()).total_seconds()))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
