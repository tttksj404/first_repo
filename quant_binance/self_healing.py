from __future__ import annotations

import re
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from quant_binance.observability.log_store import JsonlLogStore


KNOWN_BITGET_COMPATIBILITY_CODES = frozenset({"40762", "40774", "40893"})
KNOWN_CATEGORY_DAEMON_STALLED = "daemon_stalled"
KNOWN_CATEGORY_FUTURES_MISMATCH = "persistent_futures_mismatch"
KNOWN_CATEGORY_BITGET_LIVE_ORDER = "bitget_live_order_compatibility"
KNOWN_CATEGORY_MISSING_MARKET_STATE = "missing_market_state"
UNKNOWN_CATEGORY_RUNTIME_ERROR = "unknown_runtime_error"


def parse_error_code(error_message: str) -> str:
    match = re.search(r'"code":"?([0-9A-Za-z_-]+)"?', error_message)
    if match is None:
        return ""
    return match.group(1)


def is_missing_market_state_error(error_message: str) -> bool:
    normalized = error_message.lower()
    return "missing market state for symbol=" in normalized or "missing symbol state for symbol=" in normalized


def classify_runtime_issue(
    *,
    error_message: str = "",
    exchange_id: str = "",
    stage: str = "",
    mismatch_details: dict[str, Any] | None = None,
    stalled: bool = False,
) -> dict[str, Any]:
    if stalled:
        return {
            "category": KNOWN_CATEGORY_DAEMON_STALLED,
            "known": True,
            "error_code": "",
            "stage": stage or "watchdog",
            "summary": "daemon heartbeat/state stopped advancing",
            "automatic_action": "restart_websocket_loop",
        }
    details = mismatch_details or {}
    if details.get("missing_in_paper") or details.get("missing_on_exchange"):
        return {
            "category": KNOWN_CATEGORY_FUTURES_MISMATCH,
            "known": True,
            "error_code": "",
            "stage": stage or "account_sync",
            "summary": "paper and exchange futures positions stayed out of sync",
            "automatic_action": "reconcile_positions",
        }
    normalized = error_message.lower()
    code = parse_error_code(error_message)
    is_bitget = exchange_id == "bitget" or "bitget" in normalized
    order_mode_marker = (
        "unilateral position" in normalized
        or "one-way position" in normalized
        or "one way position" in normalized
    )
    leverage_marker = "unable to update the leverage factor" in normalized
    if is_bitget and ((code in {"40774", "40762"} and order_mode_marker) or (code == "40893" and leverage_marker)):
        return {
            "category": KNOWN_CATEGORY_BITGET_LIVE_ORDER,
            "known": True,
            "error_code": code,
            "stage": stage or "live_order",
            "summary": "Bitget live-order compatibility error matched a known safe fallback path",
            "automatic_action": "cooldown_and_reuse_test_order_path",
        }
    if is_missing_market_state_error(error_message):
        return {
            "category": KNOWN_CATEGORY_MISSING_MARKET_STATE,
            "known": True,
            "error_code": "",
            "stage": stage or "market_data",
            "summary": "live payload arrived before symbol market state was ready",
            "automatic_action": "skip_payload_until_market_state_ready",
        }
    return {
        "category": UNKNOWN_CATEGORY_RUNTIME_ERROR,
        "known": False,
        "error_code": code,
        "stage": stage or "runtime",
        "summary": "runtime error did not match a known conservative recovery playbook",
        "automatic_action": "report_only",
    }


@dataclass(frozen=True)
class SelfHealingEvent:
    timestamp: datetime
    category: str
    action: str
    automatic_action: str
    status: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def action_status(self) -> str:
        return self.status

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "category": self.category,
            "action": self.action,
            "automatic_action": self.automatic_action,
            "status": self.status,
            "action_status": self.status,
            "summary": self.summary,
            "details": dict(self.details),
        }


class RuntimeSelfHealing:
    def __init__(
        self,
        *,
        stall_timeout_seconds: int = 300,
        max_stall_restarts_per_window: int = 2,
        stall_restart_window_seconds: int = 1800,
        known_error_window_seconds: int = 900,
        known_error_escalation_count: int = 3,
        bitget_issue_tripwire_count: int | None = None,
        live_order_cooldown_seconds: int = 1800,
        log_store: JsonlLogStore | None = None,
    ) -> None:
        self.stall_timeout_seconds = max(int(stall_timeout_seconds), 1)
        self.max_stall_restarts_per_window = max(int(max_stall_restarts_per_window), 1)
        self.stall_restart_window_seconds = max(int(stall_restart_window_seconds), 1)
        self.known_error_window_seconds = max(int(known_error_window_seconds), 1)
        tripwire_count = bitget_issue_tripwire_count if bitget_issue_tripwire_count is not None else known_error_escalation_count
        self.known_error_escalation_count = max(int(tripwire_count), 1)
        self.live_order_cooldown_seconds = max(int(live_order_cooldown_seconds), 60)
        self.log_store = log_store
        self.started_at = datetime.now(tz=timezone.utc)
        self.last_progress_at: datetime | None = None
        self.last_heartbeat_count = 0
        self.monitor_started_at: datetime | None = None
        self.monitor_started_heartbeat_count = 0
        self.live_order_cooldown_until: datetime | None = None
        self._stall_restart_attempts: deque[datetime] = deque()
        self._known_runtime_error_times: deque[datetime] = deque()
        self._recent_events: deque[SelfHealingEvent] = deque(maxlen=20)
        self._issue_counts: Counter[str] = Counter()
        self._recovery_counts: Counter[str] = Counter()
        self._last_stall_signature = ""

    @staticmethod
    def recommended_stall_timeout_seconds(
        *,
        sync_interval_seconds: int,
        decision_interval_minutes: int,
        stale_data_alarm_sla_seconds: int,
    ) -> int:
        return max(
            300,
            int(sync_interval_seconds) * 4,
            int(decision_interval_minutes) * 120,
            int(stale_data_alarm_sla_seconds) * 20,
        )

    def _record_event(self, event: SelfHealingEvent) -> None:
        self._issue_counts[event.category] += 1
        if event.action != "report_only" and event.status in {"applied", "recovered"}:
            self._recovery_counts[event.action] += 1
        self._recent_events.append(event)
        if self.log_store is not None:
            self.log_store.append("self_healing", event.as_dict())

    def _prune(self, *, now: datetime) -> None:
        stall_cutoff = now - timedelta(seconds=self.stall_restart_window_seconds)
        while self._stall_restart_attempts and self._stall_restart_attempts[0] < stall_cutoff:
            self._stall_restart_attempts.popleft()
        error_cutoff = now - timedelta(seconds=self.known_error_window_seconds)
        while self._known_runtime_error_times and self._known_runtime_error_times[0] < error_cutoff:
            self._known_runtime_error_times.popleft()
        if self.live_order_cooldown_until is not None and now >= self.live_order_cooldown_until:
            self.live_order_cooldown_until = None

    def _current_status(self, *, now: datetime, mismatch_active: bool) -> str:
        self._prune(now=now)
        if self.live_order_cooldown_until is not None:
            return "guarded"
        if mismatch_active:
            return "degraded"
        if self._active_missing_market_state_symbols(now=now):
            return "degraded"
        if self._recent_events:
            last = self._recent_events[-1]
            if last.category == "daemon_stalled" and last.status == "suppressed":
                return "blocked"
        return "healthy"

    def _active_missing_market_state_symbols(self, *, now: datetime) -> list[str]:
        cutoff = now - timedelta(seconds=self.known_error_window_seconds)
        active_symbols = {
            str(event.details.get("symbol", ""))
            for event in self._recent_events
            if event.category == KNOWN_CATEGORY_MISSING_MARKET_STATE and event.timestamp >= cutoff
        }
        active_symbols.discard("")
        return sorted(active_symbols)

    def note_progress(self, *, timestamp: datetime, heartbeat_count: int) -> None:
        self.last_progress_at = timestamp
        self.last_heartbeat_count = heartbeat_count
        self._last_stall_signature = ""

    def begin_monitoring(self, *, timestamp: datetime, heartbeat_count: int) -> None:
        self.monitor_started_at = timestamp
        self.monitor_started_heartbeat_count = heartbeat_count
        if self.last_progress_at is None:
            self.last_progress_at = timestamp
        self._last_stall_signature = ""

    @property
    def recent_events(self) -> list[SelfHealingEvent]:
        return list(self._recent_events)

    def detect_stall(self, *, now: datetime) -> bool:
        reference_time = self.last_progress_at or self.monitor_started_at or self.started_at
        age_seconds = (now - reference_time).total_seconds()
        if age_seconds < self.stall_timeout_seconds:
            return False
        signature = "|".join(
            [
                reference_time.isoformat(),
                str(self.last_heartbeat_count),
                str(self.monitor_started_heartbeat_count),
            ]
        )
        if signature == self._last_stall_signature:
            return False
        self._last_stall_signature = signature
        return True

    def register_stall_recovery(self, *, now: datetime, heartbeat_count: int) -> bool:
        self._prune(now=now)
        allowed = len(self._stall_restart_attempts) < self.max_stall_restarts_per_window
        if allowed:
            self._stall_restart_attempts.append(now)
        reference_time = self.last_progress_at or self.monitor_started_at or self.started_at
        age_seconds = max((now - reference_time).total_seconds(), 0.0)
        self._record_event(
            SelfHealingEvent(
                timestamp=now,
                category=KNOWN_CATEGORY_DAEMON_STALLED,
                action="restart_websocket" if allowed else "report_only",
                automatic_action="restart_websocket" if allowed else "report_only",
                status="applied" if allowed else "suppressed",
                summary=(
                    f"Restarted websocket after {int(age_seconds)}s without progress"
                    if allowed
                    else f"Daemon stall detected after {int(age_seconds)}s but restart budget is exhausted"
                ),
                details={
                    "heartbeat_count": heartbeat_count,
                    "stall_timeout_seconds": self.stall_timeout_seconds,
                    "restart_attempts_in_window": len(self._stall_restart_attempts),
                },
            )
        )
        return allowed

    def _is_known_bitget_compatibility_error(self, *, error_message: str, exchange_id: str) -> bool:
        if exchange_id != "bitget":
            return False
        code = parse_error_code(error_message)
        normalized = error_message.lower()
        return (
            code in KNOWN_BITGET_COMPATIBILITY_CODES
            or "unilateral position" in normalized
            or "one-way position" in normalized
            or "one way position" in normalized
            or "unable to update the leverage factor" in normalized
        )

    def record_runtime_error(
        self,
        *,
        now: datetime,
        symbol: str,
        error_message: str,
        exchange_id: str,
        stage: str,
    ) -> dict[str, Any]:
        self._prune(now=now)
        issue = classify_runtime_issue(
            error_message=error_message,
            exchange_id=exchange_id,
            stage=stage,
        )
        code = str(issue.get("error_code", "") or parse_error_code(error_message))
        if issue["category"] == KNOWN_CATEGORY_BITGET_LIVE_ORDER:
            self._known_runtime_error_times.append(now)
            action = "symbol_cooldown"
            summary = f"Applied conservative cooldown for Bitget compatibility issue on {symbol}"
            if len(self._known_runtime_error_times) >= self.known_error_escalation_count:
                cooldown_until = now + timedelta(seconds=self.live_order_cooldown_seconds)
                if self.live_order_cooldown_until is None or cooldown_until > self.live_order_cooldown_until:
                    self.live_order_cooldown_until = cooldown_until
                action = "global_live_order_cooldown"
                summary = f"Paused live orders after repeated Bitget compatibility issues on {symbol}"
            self._record_event(
                SelfHealingEvent(
                    timestamp=now,
                    category=KNOWN_CATEGORY_BITGET_LIVE_ORDER,
                    action=action,
                    automatic_action="pause_live_orders_and_reuse_test_order_path" if action == "global_live_order_cooldown" else "cooldown_and_reuse_test_order_path",
                    status="applied",
                    summary=summary,
                    details={
                        "symbol": symbol,
                        "stage": stage,
                        "code": code,
                        "live_order_cooldown_until": self.live_order_cooldown_until,
                    },
                )
            )
            return {
                "category": KNOWN_CATEGORY_BITGET_LIVE_ORDER,
                "known": True,
                "error_code": code,
                "stage": stage,
                "automatic_action": "cooldown_and_reuse_test_order_path",
            }
        if issue["category"] == KNOWN_CATEGORY_MISSING_MARKET_STATE:
            self._record_event(
                SelfHealingEvent(
                    timestamp=now,
                    category=KNOWN_CATEGORY_MISSING_MARKET_STATE,
                    action="skip_payload",
                    automatic_action="skip_payload_until_market_state_ready",
                    status="applied",
                    summary=f"Skipped live payload for {symbol} because market state was missing",
                    details={
                        "symbol": symbol,
                        "stage": stage,
                        "exchange_id": exchange_id,
                    },
                )
            )
            return {
                "category": KNOWN_CATEGORY_MISSING_MARKET_STATE,
                "known": True,
                "error_code": "",
                "stage": stage,
                "automatic_action": "skip_payload_until_market_state_ready",
            }
        self._record_event(
            SelfHealingEvent(
                timestamp=now,
                category=UNKNOWN_CATEGORY_RUNTIME_ERROR,
                action="report_only",
                automatic_action="report_only",
                status="reported",
                summary=f"Observed unclassified runtime error on {symbol}",
                details={
                    "symbol": symbol,
                    "stage": stage,
                    "exchange_id": exchange_id,
                    "code": code,
                },
            )
        )
        return {
            "category": UNKNOWN_CATEGORY_RUNTIME_ERROR,
            "known": False,
            "error_code": code,
            "stage": stage,
            "automatic_action": "report_only",
        }

    def record_mismatch_recovery(
        self,
        *,
        now: datetime,
        symbol: str,
        action: str,
        persisted_cycles: int,
    ) -> None:
        summaries = {
            "reconcile_missing_in_paper": f"Reconciled missing paper futures position for {symbol}",
            "cleanup_missing_on_exchange": f"Cleaned stale paper futures position for {symbol}",
        }
        self._record_event(
            SelfHealingEvent(
                timestamp=now,
                category=KNOWN_CATEGORY_FUTURES_MISMATCH,
                action="reconcile_positions",
                automatic_action="reconcile_positions",
                status="recovered",
                summary=summaries.get(action, f"Handled futures position mismatch for {symbol}"),
                details={
                    "symbol": symbol,
                    "source_action": action,
                    "persisted_cycles": persisted_cycles,
                },
            )
        )

    def is_live_order_cooldown_active(self, *, now: datetime) -> bool:
        self._prune(now=now)
        return self.live_order_cooldown_until is not None and now < self.live_order_cooldown_until

    def snapshot(
        self,
        *,
        now: datetime,
        order_error_cooldowns: dict[str, datetime],
        manual_symbol_cooldowns: dict[str, datetime],
        mismatch_active: bool,
        mismatch_details: dict[str, Any],
    ) -> dict[str, Any]:
        self._prune(now=now)
        active_order_symbols = sorted(symbol for symbol, until in order_error_cooldowns.items() if until > now)
        active_manual_symbols = sorted(symbol for symbol, until in manual_symbol_cooldowns.items() if until > now)
        missing_market_state_symbols = self._active_missing_market_state_symbols(now=now)
        return {
            "status": self._current_status(now=now, mismatch_active=mismatch_active),
            "active_guards": {
                "live_order_cooldown_until": self.live_order_cooldown_until,
                "symbol_order_cooldowns": active_order_symbols,
                "manual_symbol_cooldowns": active_manual_symbols,
                "missing_market_state_symbols": missing_market_state_symbols,
                "mismatch_active": mismatch_active,
                "mismatch_details": mismatch_details,
                "stall_restart_budget_remaining": max(
                    self.max_stall_restarts_per_window - len(self._stall_restart_attempts),
                    0,
                ),
            },
            "issue_counts": dict(sorted(self._issue_counts.items())),
            "recovery_counts": dict(sorted(self._recovery_counts.items())),
            "recent_events": [event.as_dict() for event in list(self._recent_events)[-5:]],
        }
