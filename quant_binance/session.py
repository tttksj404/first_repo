from __future__ import annotations

import re
import time
import asyncio
from contextlib import suppress
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from quant_binance.data.market_store import MissingMarketStateError
from quant_binance.execution.live_order_adapter import DecisionLiveOrderAdapter
from quant_binance.execution.order_test_adapter import DecisionOrderTestAdapter, OrderTestResult
from quant_binance.learning import OnlineEdgeLearner
from quant_binance.live import LivePaperRuntime
from quant_binance.models import DecisionIntent
from quant_binance.observability.log_store import JsonlLogStore
from quant_binance.observability.overview import build_runtime_overview, write_runtime_overview
from quant_binance.observability.report import build_runtime_summary, write_runtime_summary
from quant_binance.observability.runtime_state import write_runtime_state
from quant_binance.risk.capital import CapitalAdequacyReport
from quant_binance.risk.sizing import quantity_from_notional, select_futures_leverage
from quant_binance.self_healing import RuntimeSelfHealing, parse_error_code
from quant_binance.telegram_notify import send_telegram_message, telegram_report_only_enabled


class SupportsAccountSync(Protocol):
    def get_account(self, *, market: str) -> dict[str, Any]:
        ...

    def get_open_orders(self, *, market: str, symbol: str | None = None) -> dict[str, Any]:
        ...

    def build_capital_report(self) -> CapitalAdequacyReport:
        ...

    def get_positions(self) -> dict[str, Any]:
        ...

    def cancel_order(self, *, market: str, symbol: str, order_id: str) -> dict[str, Any]:
        ...


@dataclass
class PaperPosition:
    symbol: str
    market: str
    side: str
    entry_time: datetime
    entry_price: float
    current_price: float
    quantity_opened: float
    quantity_remaining: float
    stop_distance_bps: float
    active_stop_price: float
    best_price: float
    worst_price: float
    entry_predictability_score: float
    entry_liquidity_score: float
    entry_net_expected_edge_bps: float = 0.0
    entry_estimated_round_trip_cost_bps: float = 0.0
    entry_planned_leverage: int = 1
    latest_predictability_score: float = 0.0
    latest_liquidity_score: float = 0.0
    latest_net_expected_edge_bps: float = 0.0
    latest_estimated_round_trip_cost_bps: float = 0.0
    latest_decision_time: datetime | None = None
    partial_take_profit_taken: bool = False
    r_multiple_partial_take_profit_taken: bool = False
    profit_protection_retrace_taken: bool = False
    proactive_take_profit_thresholds_hit: tuple[float, ...] = ()
    exit_confirmation_count: int = 0
    last_exit_signal_reason: str = ""
    peak_roe_percent: float = 0.0
    exchange_synced: bool = False
    confirmation_pending: bool = False
    confirmation_pending_since: datetime | None = None

    def unrealized_pnl_usd_estimate(self) -> float:
        if self.side == "short":
            return round((self.entry_price - self.current_price) * self.quantity_remaining, 6)
        return round((self.current_price - self.entry_price) * self.quantity_remaining, 6)

    def current_notional_usd_estimate(self) -> float:
        return round(self.current_price * self.quantity_remaining, 6)

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "market": self.market,
            "side": self.side,
            "entry_time": self.entry_time,
            "entry_price": round(self.entry_price, 6),
            "current_price": round(self.current_price, 6),
            "quantity_opened": round(self.quantity_opened, 8),
            "quantity_remaining": round(self.quantity_remaining, 8),
            "current_notional_usd_estimate": self.current_notional_usd_estimate(),
            "unrealized_pnl_usd_estimate": self.unrealized_pnl_usd_estimate(),
            "stop_distance_bps": round(self.stop_distance_bps, 6),
            "active_stop_price": round(self.active_stop_price, 6),
            "best_price": round(self.best_price, 6),
            "worst_price": round(self.worst_price, 6),
            "partial_take_profit_taken": self.partial_take_profit_taken,
            "r_multiple_partial_take_profit_taken": self.r_multiple_partial_take_profit_taken,
            "profit_protection_retrace_taken": self.profit_protection_retrace_taken,
            "proactive_take_profit_thresholds_hit": list(self.proactive_take_profit_thresholds_hit),
            "entry_predictability_score": round(self.entry_predictability_score, 6),
            "entry_liquidity_score": round(self.entry_liquidity_score, 6),
            "entry_net_expected_edge_bps": round(self.entry_net_expected_edge_bps, 6),
            "entry_estimated_round_trip_cost_bps": round(self.entry_estimated_round_trip_cost_bps, 6),
            "entry_planned_leverage": int(max(self.entry_planned_leverage, 1)),
            "latest_predictability_score": round(self.latest_predictability_score or self.entry_predictability_score, 6),
            "latest_liquidity_score": round(self.latest_liquidity_score or self.entry_liquidity_score, 6),
            "latest_net_expected_edge_bps": round(self.latest_net_expected_edge_bps or self.entry_net_expected_edge_bps, 6),
            "latest_estimated_round_trip_cost_bps": round(
                self.latest_estimated_round_trip_cost_bps or self.entry_estimated_round_trip_cost_bps,
                6,
            ),
            "latest_decision_time": self.latest_decision_time,
            "exit_confirmation_count": self.exit_confirmation_count,
            "last_exit_signal_reason": self.last_exit_signal_reason,
            "peak_roe_percent": round(self.peak_roe_percent, 6),
            "exchange_synced": self.exchange_synced,
            "confirmation_pending": self.confirmation_pending,
            "confirmation_pending_since": self.confirmation_pending_since,
        }


@dataclass
class LivePaperSession:
    runtime: LivePaperRuntime
    equity_usd: float
    remaining_portfolio_capacity_usd: float
    max_portfolio_capacity_usd: float | None = None
    rest_client: SupportsAccountSync | None = None
    order_tester: DecisionOrderTestAdapter | None = None
    live_order_executor: DecisionLiveOrderAdapter | None = None
    learner: OnlineEdgeLearner | None = None
    learner_output_path: str | Path | None = None
    log_store: JsonlLogStore | None = None
    verbose: bool = False
    sync_interval_seconds: int = 60
    flush_interval_seconds: int = 15
    decisions: list[DecisionIntent] = field(default_factory=list)
    tested_orders: list[dict[str, object]] = field(default_factory=list)
    account_snapshot: dict[str, object] = field(default_factory=dict)
    open_orders_snapshot: dict[str, object] = field(default_factory=dict)
    capital_report: dict[str, object] = field(default_factory=dict)
    live_orders: list[dict[str, object]] = field(default_factory=list)
    observe_only_symbols: list[str] = field(default_factory=list)
    last_executed_fingerprint_by_symbol: dict[str, str] = field(default_factory=dict)
    paper_positions: dict[str, PaperPosition] = field(default_factory=dict)
    closed_trades: list[dict[str, object]] = field(default_factory=list)
    telegram_alerts: list[dict[str, object]] = field(default_factory=list)
    sent_alert_keys: set[str] = field(default_factory=set)
    live_positions_snapshot: list[dict[str, object]] = field(default_factory=list)
    live_proactive_take_profit_keys: set[str] = field(default_factory=set)
    live_profit_protection_keys: set[str] = field(default_factory=set)
    live_peak_roe_by_identity: dict[str, float] = field(default_factory=dict)
    live_worst_roe_by_identity: dict[str, float] = field(default_factory=dict)
    live_turnaround_take_profit_keys: set[str] = field(default_factory=set)
    live_peak_unrealized_pnl_by_identity: dict[str, float] = field(default_factory=dict)
    live_unrealized_take_profit_keys: set[str] = field(default_factory=set)
    live_partial_exit_last_at_by_identity: dict[str, datetime] = field(default_factory=dict)
    live_partial_exit_mode_by_identity: dict[str, str] = field(default_factory=dict)
    live_major_drawdown_grace_started_at_by_identity: dict[str, datetime] = field(default_factory=dict)
    live_entry_starvation_attempts_by_symbol: dict[str, int] = field(default_factory=dict)
    live_entry_starvation_last_at_by_symbol: dict[str, datetime] = field(default_factory=dict)
    live_portfolio_peak_unrealized_ratio: float = 0.0
    live_portfolio_profit_lock_taken: bool = False
    live_portfolio_full_exit_taken: bool = False
    futures_pyramid_add_counts: dict[str, int] = field(default_factory=dict)
    order_error_cooldowns: dict[str, datetime] = field(default_factory=dict)
    manual_symbol_cooldowns: dict[str, datetime] = field(default_factory=dict)
    loss_combo_cooldowns: dict[str, datetime] = field(default_factory=dict)
    futures_missing_in_paper_counts: dict[str, int] = field(default_factory=dict)
    futures_missing_on_exchange_counts: dict[str, int] = field(default_factory=dict)
    futures_reallocation_cooldown_until: datetime | None = None
    self_healing: RuntimeSelfHealing = field(default_factory=RuntimeSelfHealing)
    heartbeat_count: int = 0
    last_event_timestamp: datetime | None = None
    last_decision_timestamp: datetime | None = None
    last_decision_emitted_at: datetime | None = None
    next_scheduled_decision_at: datetime | None = None
    last_recorded_decision_time_by_symbol: dict[str, datetime] = field(default_factory=dict)
    minimum_live_decision_timestamp: datetime | None = None
    _last_sync_at: datetime | None = None
    _last_flush_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.max_portfolio_capacity_usd is None:
            self.max_portfolio_capacity_usd = self.remaining_portfolio_capacity_usd

    def process_payload(self, payload: dict[str, Any], *, now: datetime | None = None) -> DecisionIntent | None:
        timestamp = now or datetime.now(tz=timezone.utc)
        self.heartbeat_count += 1
        self.last_event_timestamp = timestamp
        self.self_healing.note_progress(timestamp=timestamp, heartbeat_count=self.heartbeat_count)
        if self._should_sync(timestamp):
            self.sync_account()
            self._last_sync_at = timestamp
            if self.verbose:
                print(f"[SYNC] {timestamp.isoformat()} account/open-order snapshot refreshed", flush=True)
            if self.log_store is not None:
                self.log_store.append(
                    "account_sync",
                    {
                        "timestamp": timestamp,
                        "account_snapshot": self.account_snapshot,
                        "open_orders_snapshot": self.open_orders_snapshot,
                    },
                )
        event_payload: dict[str, Any] = {"timestamp": timestamp, "payload": payload}
        try:
            decision = self.runtime.on_payload(
                payload,
                equity_usd=self.equity_usd,
                remaining_portfolio_capacity_usd=self.remaining_portfolio_capacity_usd,
            )
        except MissingMarketStateError as exc:
            issue = self.self_healing.record_runtime_error(
                now=timestamp,
                symbol=exc.symbol,
                error_message=str(exc),
                exchange_id=getattr(self.rest_client, "exchange_id", "binance"),
                stage="market_data",
            )
            event_payload["self_healing"] = issue
            event_payload["status"] = "skipped_known_runtime_issue"
            if self.verbose:
                print(f"[SELF_HEAL] skipped payload due to missing market state for {exc.symbol}", flush=True)
            if self.log_store is not None:
                self.log_store.append("events", event_payload)
            return None
        if self.log_store is not None:
            self.log_store.append("events", event_payload)
        if self.verbose and self.heartbeat_count % 25 == 0:
            print(
                f"[HEARTBEAT] events={self.heartbeat_count} decisions={len(self.decisions)} live_orders={len(self.live_orders)} tested_orders={len(self.tested_orders)}",
                flush=True,
            )
        if decision is not None:
            state = self.runtime.dispatcher.store.get(decision.symbol)
            self._record_decision(decision=decision, state=state, timestamp=timestamp)
        self._maybe_run_scheduled_decision_cycle(timestamp)
        return decision

    def run_bootstrap_cycle(
        self,
        *,
        state: Any,
        primitive_inputs: Any,
        history: Any,
        decision_time: datetime,
    ) -> DecisionIntent:
        decision = self.runtime.paper_service.run_cycle(
            state=state,
            primitive_inputs=primitive_inputs,
            history=history,
            decision_time=decision_time,
            equity_usd=self.equity_usd,
            remaining_portfolio_capacity_usd=self.remaining_portfolio_capacity_usd,
            cash_reserve_fraction=self._cash_reserve_fraction(),
        )
        self._record_decision(decision=decision, state=state, timestamp=decision_time, bootstrap=True)
        return decision

    def _build_capital_report_snapshot(self) -> None:
        if self.rest_client is None or not hasattr(self.rest_client, "build_capital_report"):
            return
        report = self.rest_client.build_capital_report()
        self.capital_report = {
            "spot_available_balance_usd": report.spot_available_balance_usd,
            "spot_recognized_balance_usd": report.spot_recognized_balance_usd,
            "spot_funding_assets": [item.__dict__ for item in report.spot_funding_assets],
            "spot_execution_routes": [item.__dict__ for item in report.spot_execution_routes],
            "capital_transfer_routes": [item.__dict__ for item in report.capital_transfer_routes],
            "futures_available_balance_usd": report.futures_available_balance_usd,
            "futures_recognized_balance_usd": report.futures_recognized_balance_usd,
            "futures_execution_balance_usd": float(
                self.account_snapshot.get("executionAvailableBalance", report.futures_available_balance_usd)
            ),
            "minimum_operational_balance_usd": report.minimum_operational_balance_usd,
            "minimum_full_universe_balance_usd": report.minimum_full_universe_balance_usd,
            "recommended_balance_usd": report.recommended_balance_usd,
            "can_trade_any": report.can_trade_any,
            "can_trade_spot_any": report.can_trade_spot_any,
            "can_trade_futures_any": report.can_trade_futures_any,
            "max_spot_to_futures_transfer_usd": report.max_spot_to_futures_transfer_usd,
            "max_futures_to_spot_transfer_usd": report.max_futures_to_spot_transfer_usd,
            "spot_requirements": [r.__dict__ for r in report.spot_requirements],
            "futures_requirements": [r.__dict__ for r in report.futures_requirements],
            "pending_symbols": list(report.pending_symbols),
            "note": report.note,
        }
        if not report.can_trade_any:
            self.runtime.kill_switch.arm("INSUFFICIENT_CAPITAL")

    def _refresh_account_state(self, *, evaluate_live_positions: bool) -> None:
        if self.rest_client is None:
            return
        previous_account_snapshot = dict(self.account_snapshot)
        previous_live_positions = list(self.live_positions_snapshot)
        self.account_snapshot = self.rest_client.get_account(market="futures")
        self.open_orders_snapshot = self.rest_client.get_open_orders(market="futures")
        if hasattr(self.rest_client, "get_positions"):
            positions_payload = self.rest_client.get_positions()
            self.live_positions_snapshot = positions_payload.get("positions", [])
        self._reconcile_manual_live_closes(
            previous_live_positions=previous_live_positions,
            previous_account_snapshot=previous_account_snapshot,
        )
        self._reconcile_persistent_futures_position_mismatch()
        self._build_capital_report_snapshot()
        if evaluate_live_positions:
            self._evaluate_live_positions()
        self._last_sync_at = datetime.now(tz=timezone.utc)

    def sync_account(self) -> None:
        self._refresh_account_state(evaluate_live_positions=True)

    def flush(self, *, summary_path: str | Path, state_path: str | Path) -> dict[str, object]:
        open_spot_positions = self._open_positions_for_market("spot")
        open_futures_positions = self._open_positions_for_market("futures")
        mismatch_active, mismatch_details = self._self_healing_mismatch_snapshot()
        self_healing_status = self.self_healing.snapshot(
            now=datetime.now(tz=timezone.utc),
            order_error_cooldowns=self.order_error_cooldowns,
            manual_symbol_cooldowns=self.manual_symbol_cooldowns,
            mismatch_active=mismatch_active,
            mismatch_details=mismatch_details,
        )
        summary = build_runtime_summary(
            decisions=self.decisions,
            tested_orders=self.tested_orders,
            live_orders=self.live_orders,
            account_snapshot=self.account_snapshot,
            open_orders_snapshot=self.open_orders_snapshot,
            capital_report=self.capital_report,
            kill_switch_status=self.runtime.kill_switch.status(),
            observe_only_symbols=self.observe_only_symbols,
            open_spot_positions=open_spot_positions,
            open_futures_positions=open_futures_positions,
            closed_trades=self.closed_trades,
            telegram_alerts=self.telegram_alerts,
            live_positions=self.live_positions_snapshot,
            self_healing=self_healing_status,
        )
        write_runtime_summary(summary_path, summary)
        write_runtime_state(
            state_path,
            {
                "decision_count": len(self.decisions),
                "tested_order_count": len(self.tested_orders),
                "live_order_count": len(self.live_orders),
                "heartbeat_count": self.heartbeat_count,
                "last_event_timestamp": self.last_event_timestamp,
                "last_decision_timestamp": self.last_decision_timestamp,
                "last_decision_emitted_at": self.last_decision_emitted_at,
                "live_decision_loop": self.runtime.loop_stats.as_dict(),
                "capital_report": self.capital_report,
                "open_spot_position_count": len(open_spot_positions),
                "open_futures_position_count": len(open_futures_positions),
                "paper_open_futures_position_count": summary["paper_open_futures_position_count"],
                "paper_open_futures_positions": summary["paper_open_futures_positions"],
                "exchange_live_futures_position_count": summary["exchange_live_futures_position_count"],
                "exchange_live_futures_positions": summary["exchange_live_futures_positions"],
                "futures_position_mismatch": summary["futures_position_mismatch"],
                "futures_position_mismatch_details": summary["futures_position_mismatch_details"],
                "futures_missing_in_paper_counts": dict(sorted(self.futures_missing_in_paper_counts.items())),
                "futures_missing_on_exchange_counts": dict(sorted(self.futures_missing_on_exchange_counts.items())),
                "self_healing": self_healing_status,
                "closed_trade_count": len(self.closed_trades),
                "kill_switch": self.runtime.kill_switch.status(),
            },
        )
        overview_path = Path(summary_path).with_name("overview.json")
        overview = build_runtime_overview(
            summary=summary,
            state={
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
                "decision_count": len(self.decisions),
                "heartbeat_count": self.heartbeat_count,
                "last_event_timestamp": self.last_event_timestamp,
                "last_decision_timestamp": self.last_decision_timestamp,
                "last_decision_emitted_at": self.last_decision_emitted_at,
                "live_order_count": len(self.live_orders),
                "tested_order_count": len(self.tested_orders),
                "exchange_live_futures_position_count": summary["exchange_live_futures_position_count"],
                "exchange_live_futures_positions": summary["exchange_live_futures_positions"],
                "capital_report": self.capital_report,
                "self_healing": self_healing_status,
                "kill_switch": self.runtime.kill_switch.status(),
            },
        )
        write_runtime_overview(overview_path, overview)
        if self.learner is not None and self.learner_output_path is not None:
            self.learner.export(self.learner_output_path)
        return summary

    def _self_healing_mismatch_snapshot(self) -> tuple[bool, dict[str, list[str]]]:
        if self.rest_client is None and not self.live_positions_snapshot:
            return False, {"missing_in_paper": [], "missing_on_exchange": []}
        details = {
            "missing_in_paper": sorted(
                symbol
                for symbol, count in self.futures_missing_in_paper_counts.items()
                if count >= self._missing_in_paper_threshold()
            ),
            "missing_on_exchange": sorted(
                symbol
                for symbol, count in self.futures_missing_on_exchange_counts.items()
                if count >= self._missing_on_exchange_threshold()
            ),
        }
        return bool(details["missing_in_paper"] or details["missing_on_exchange"]), details

    def maybe_flush(
        self,
        *,
        summary_path: str | Path,
        state_path: str | Path,
        now: datetime | None = None,
    ) -> dict[str, object] | None:
        timestamp = now or datetime.now(tz=timezone.utc)
        if not self._should_flush(timestamp):
            return None
        self._last_flush_at = timestamp
        return self.flush(summary_path=summary_path, state_path=state_path)

    def _should_sync(self, now: datetime) -> bool:
        if self.rest_client is None:
            return False
        if self._last_sync_at is None:
            return True
        return (now - self._last_sync_at) >= timedelta(seconds=self.sync_interval_seconds)

    def _should_flush(self, now: datetime) -> bool:
        if self._last_flush_at is None:
            return True
        return (now - self._last_flush_at) >= timedelta(seconds=self.flush_interval_seconds)

    def _execution_fingerprint(self, decision: DecisionIntent) -> str:
        return "|".join(
            [
                decision.symbol,
                decision.final_mode,
                decision.side,
                str(decision.trend_direction),
                f"{decision.order_intent_notional_usd:.2f}",
                f"{decision.predictability_score:.2f}",
            ]
        )

    def _market_capital_allowed(self, decision: DecisionIntent) -> bool:
        if not self.capital_report:
            return True
        if decision.final_mode == "spot":
            return bool(self.capital_report.get("can_trade_spot_any", False))
        if decision.final_mode == "futures":
            return bool(self.capital_report.get("can_trade_futures_any", False))
        return True

    def _cash_reserve_fraction(self) -> float:
        if self.capital_report.get("can_trade_futures_any", False):
            return self.runtime.paper_service.settings.cash_reserve.when_futures_enabled
        return self.runtime.paper_service.settings.cash_reserve.when_futures_disabled

    def _market_min_quantity(self, *, market: str, symbol: str) -> float:
        if not self.capital_report:
            return 0.0
        requirements_key = "spot_requirements" if market == "spot" else "futures_requirements"
        for item in self.capital_report.get(requirements_key, []):
            if item.get("symbol") == symbol:
                return float(item.get("min_quantity", 0.0) or 0.0)
        return 0.0

    def _select_spot_execution_route(self, decision: DecisionIntent, *, reserve_fraction: float) -> dict[str, Any] | None:
        if decision.final_mode != "spot" or decision.side != "long":
            return None
        raw_routes = self.capital_report.get("spot_execution_routes", [])
        if not isinstance(raw_routes, list):
            return None
        candidate_routes = [
            item
            for item in raw_routes
            if isinstance(item, dict)
            and str(item.get("target_symbol", "")) == decision.symbol
            and float(item.get("free_balance_usd", 0.0)) > 0.0
        ]
        if not candidate_routes:
            return None
        return max(
            candidate_routes,
            key=lambda item: (
                float(item.get("free_balance_usd", 0.0)) * (1.0 - reserve_fraction) >= decision.order_intent_notional_usd,
                float(item.get("free_balance_usd", 0.0)) * (1.0 - reserve_fraction),
                item.get("route_type") == "direct",
            ),
        )

    def _cap_live_order_decision(
        self,
        decision: DecisionIntent,
        *,
        reference_price: float | None = None,
        extra_futures_execution_balance_usd: float = 0.0,
    ) -> DecisionIntent:
        if not self.capital_report:
            return decision
        is_major_strong_futures_decision = self._is_major_strong_futures_decision(decision)
        is_major_medium_futures_decision = self._is_major_medium_futures_decision(decision)
        if decision.final_mode == "futures":
            live_position = self._find_live_futures_position(decision.symbol)
            if live_position is not None:
                live_side = self._normalize_live_position_side(live_position)
                if live_side != decision.side:
                    return replace(
                        decision,
                        final_mode="cash",
                        side="flat",
                        order_intent_notional_usd=0.0,
                        stop_distance_bps=0.0,
                        rejection_reasons=tuple(sorted(set(decision.rejection_reasons + ("LIVE_POSITION_CONFLICT",)))),
                    )
        reserve_fraction = self._cash_reserve_fraction()
        requirements_key = "spot_requirements" if decision.final_mode == "spot" else "futures_requirements"
        min_notional = 0.0
        min_quantity = 0.0
        for item in self.capital_report.get(requirements_key, []):
            if item.get("symbol") == decision.symbol:
                min_notional = float(item.get("min_notional_usd", 0.0))
                min_quantity = float(item.get("min_quantity", 0.0))
                break
        if decision.final_mode == "spot":
            selected_route = self._select_spot_execution_route(decision, reserve_fraction=reserve_fraction)
            if selected_route is not None:
                available = float(selected_route.get("free_balance_usd", 0.0))
                min_notional = float(selected_route.get("min_notional_usd", min_notional))
                min_quantity = float(selected_route.get("min_quantity", min_quantity))
                decision = replace(
                    decision,
                    execution_symbol=str(selected_route.get("execution_symbol", decision.symbol)),
                    spot_base_asset=str(selected_route.get("base_asset", "")),
                    spot_quote_asset=str(selected_route.get("quote_asset", "")),
                    spot_funding_asset=str(selected_route.get("funding_asset", "")),
                    spot_quote_asset_usd_price=float(selected_route.get("quote_asset_usd_price", 0.0) or 0.0),
                )
            else:
                available = float(self.capital_report.get("spot_available_balance_usd", 0.0))
                decision = replace(
                    decision,
                    execution_symbol=decision.symbol,
                    spot_quote_asset="USDT" if decision.symbol.endswith("USDT") else "",
                    spot_funding_asset="USDT" if decision.symbol.endswith("USDT") else "",
                    spot_quote_asset_usd_price=1.0 if decision.symbol.endswith("USDT") else 0.0,
                )
            max_notional = max(0.0, available * (1.0 - reserve_fraction))
        elif decision.final_mode == "futures":
            available = float(
                self.capital_report.get(
                    "futures_execution_balance_usd",
                    self.capital_report.get("futures_available_balance_usd", 0.0),
                )
            )
            available += max(extra_futures_execution_balance_usd, 0.0)
            leverage = select_futures_leverage(
                predictability_score=decision.predictability_score,
                trend_strength=decision.trend_strength,
                volume_confirmation=decision.volume_confirmation,
                liquidity_score=decision.liquidity_score,
                volatility_penalty=decision.volatility_penalty,
                overheat_penalty=decision.overheat_penalty,
                net_expected_edge_bps=decision.net_expected_edge_bps,
                estimated_round_trip_cost_bps=decision.estimated_round_trip_cost_bps,
                settings=self.runtime.paper_service.settings,
            )
            execution_headroom = max(0.0, available * (1.0 - reserve_fraction))
            max_notional = max(0.0, execution_headroom * leverage)
            current_futures_notional = sum(
                position.current_notional_usd_estimate()
                for position in self.paper_positions.values()
                if position is not None
                and position.market == "futures"
                and position.quantity_remaining > 0
                and position.exchange_synced
            )
            if current_futures_notional > 0.0:
                total_notional_fraction = self.runtime.paper_service.settings.risk.max_total_notional_fraction
                if is_major_medium_futures_decision:
                    total_notional_fraction = min(
                        total_notional_fraction
                        + self.runtime.paper_service.settings.futures_exposure.major_medium_total_notional_fraction_relaxation,
                        1.0,
                    )
                if is_major_strong_futures_decision:
                    total_notional_fraction = min(
                        total_notional_fraction
                        + self.runtime.paper_service.settings.futures_exposure.major_strong_total_notional_fraction_relaxation,
                        1.0,
                    )
                total_notional_cap = self.equity_usd * total_notional_fraction
                remaining_total_notional = max(total_notional_cap - current_futures_notional, 0.0)
                if remaining_total_notional <= 0.0:
                    max_notional = 0.0
                else:
                    max_notional = min(max_notional, remaining_total_notional)
                safety_cap_fraction = 0.5
                if is_major_medium_futures_decision:
                    safety_cap_fraction = max(
                        self.runtime.paper_service.settings.futures_exposure.major_medium_safety_cap_fraction,
                        safety_cap_fraction,
                    )
                if is_major_strong_futures_decision:
                    safety_cap_fraction = max(
                        self.runtime.paper_service.settings.futures_exposure.major_strong_safety_cap_fraction,
                        safety_cap_fraction,
                    )
                safety_cap = execution_headroom * safety_cap_fraction
                max_notional = min(max_notional, safety_cap)
        else:
            return decision
        rejection_code = "INSUFFICIENT_EXECUTION_BALANCE"
        meaningful_notional_floor = (
            self.runtime.paper_service.settings.risk.min_meaningful_spot_notional_usd
            if decision.final_mode == "spot"
            else self.runtime.paper_service.settings.risk.min_meaningful_futures_notional_usd
        )
        major_medium_entry_floor = 0.0
        major_strong_entry_floor = 0.0
        if (
            decision.final_mode == "futures"
            and self._is_major_futures_symbol(decision.symbol)
            and decision.predictability_score >= self.runtime.paper_service.settings.futures_exposure.pyramid_min_predictability_score
        ):
            meaningful_notional_floor = max(
                meaningful_notional_floor,
                self.runtime.paper_service.settings.futures_exposure.major_min_meaningful_notional_usd,
            )
        if is_major_medium_futures_decision:
            major_medium_entry_floor = max(
                0.0,
                self.runtime.paper_service.settings.futures_exposure.major_medium_min_entry_notional_usd,
            )
            meaningful_notional_floor = max(meaningful_notional_floor, major_medium_entry_floor)
        if is_major_strong_futures_decision:
            major_strong_entry_floor = max(
                0.0,
                self.runtime.paper_service.settings.futures_exposure.major_strong_min_entry_notional_usd,
            )
            meaningful_notional_floor = max(meaningful_notional_floor, major_strong_entry_floor)
        if max_notional <= 0.0 or (min_notional > 0.0 and max_notional < min_notional):
            rejection_reasons = list(decision.rejection_reasons + (rejection_code,))
            if decision.final_mode == "futures" and float(self.capital_report.get("max_spot_to_futures_transfer_usd", 0.0) or 0.0) > 0.0:
                rejection_reasons.append("TRANSFER_REQUIRED_SPOT_TO_FUTURES")
            if decision.final_mode == "spot" and float(self.capital_report.get("max_futures_to_spot_transfer_usd", 0.0) or 0.0) > 0.0:
                rejection_reasons.append("TRANSFER_REQUIRED_FUTURES_TO_SPOT")
            return replace(decision, final_mode="cash", side="flat", order_intent_notional_usd=0.0, stop_distance_bps=0.0, rejection_reasons=tuple(sorted(set(rejection_reasons))))
        if decision.order_intent_notional_usd < major_medium_entry_floor:
            if max_notional < major_medium_entry_floor:
                return replace(
                    decision,
                    final_mode="cash",
                    side="flat",
                    order_intent_notional_usd=0.0,
                    stop_distance_bps=0.0,
                    rejection_reasons=tuple(sorted(set(decision.rejection_reasons + ("MIN_MEANINGFUL_NOTIONAL",)))),
                )
            decision = replace(decision, order_intent_notional_usd=round(major_medium_entry_floor, 6))
        if decision.order_intent_notional_usd < major_strong_entry_floor:
            if max_notional < major_strong_entry_floor:
                return replace(
                    decision,
                    final_mode="cash",
                    side="flat",
                    order_intent_notional_usd=0.0,
                    stop_distance_bps=0.0,
                    rejection_reasons=tuple(sorted(set(decision.rejection_reasons + ("MIN_MEANINGFUL_NOTIONAL",)))),
                )
            decision = replace(decision, order_intent_notional_usd=round(major_strong_entry_floor, 6))
        expected_profit_usd = decision.order_intent_notional_usd * max(decision.net_expected_edge_bps, 0.0) / 10000.0
        if decision.order_intent_notional_usd < meaningful_notional_floor:
            return replace(
                decision,
                final_mode="cash",
                side="flat",
                order_intent_notional_usd=0.0,
                stop_distance_bps=0.0,
                rejection_reasons=tuple(sorted(set(decision.rejection_reasons + ("MIN_MEANINGFUL_NOTIONAL",)))),
            )
        if expected_profit_usd < self.runtime.paper_service.settings.risk.min_expected_profit_usd_per_trade:
            return replace(
                decision,
                final_mode="cash",
                side="flat",
                order_intent_notional_usd=0.0,
                stop_distance_bps=0.0,
                rejection_reasons=tuple(sorted(set(decision.rejection_reasons + ("EXPECTED_PROFIT_TOO_SMALL",)))),
            )
        if decision.order_intent_notional_usd <= max_notional:
            candidate = decision
        else:
            floored_notional = round(max_notional, 6)
            candidate = replace(decision, order_intent_notional_usd=floored_notional)
        if reference_price is not None and min_quantity > 0.0:
            quantity_reference_price = reference_price
            if candidate.final_mode == "spot" and (candidate.spot_quote_asset or "USDT") != "USDT":
                quote_asset_usd_price = float(candidate.spot_quote_asset_usd_price or 0.0)
                if quote_asset_usd_price > 0.0:
                    quantity_reference_price = reference_price * quote_asset_usd_price
            quantity = quantity_from_notional(candidate.order_intent_notional_usd, quantity_reference_price)
            if quantity < min_quantity:
                return replace(
                    candidate,
                    final_mode="cash",
                    side="flat",
                    order_intent_notional_usd=0.0,
                    stop_distance_bps=0.0,
                    rejection_reasons=tuple(sorted(set(candidate.rejection_reasons + ("MIN_ORDER_QUANTITY",)))),
                )
        return candidate

    def _normalize_live_position_side(self, position: dict[str, Any]) -> str:
        hold_side = str(position.get("holdSide") or position.get("posSide") or "").lower()
        if hold_side in {"long", "buy"}:
            return "long"
        if hold_side in {"short", "sell"}:
            return "short"
        side = str(position.get("side") or "").lower()
        if side in {"buy", "long"}:
            return "long"
        return "short"

    def _find_live_futures_position(self, symbol: str) -> dict[str, Any] | None:
        for position in self.live_positions_snapshot:
            if str(position.get("symbol", "")) != symbol:
                continue
            total = self._live_position_quantity(position)
            if total > 0.0:
                return position
        return None

    def _live_position_quantity(self, position: dict[str, Any]) -> float:
        return float(position.get("total") or position.get("available") or 0.0)

    def _active_live_futures_positions_by_symbol(self) -> dict[str, dict[str, Any]]:
        positions: dict[str, dict[str, Any]] = {}
        for position in self.live_positions_snapshot:
            symbol = str(position.get("symbol", ""))
            if not symbol:
                continue
            if self._live_position_quantity(position) <= 0.0:
                continue
            positions[symbol] = position
        return positions

    def _open_paper_futures_positions_by_symbol(self) -> dict[str, PaperPosition]:
        return {
            symbol: position
            for symbol, position in self.paper_positions.items()
            if position.market == "futures" and position.quantity_remaining > 0.0
        }

    def _is_major_futures_symbol(self, symbol: str) -> bool:
        return symbol in set(self.runtime.paper_service.settings.futures_exposure.major_symbols)

    def _is_major_strong_futures_decision(self, decision: DecisionIntent) -> bool:
        if decision.final_mode != "futures" or not self._is_major_futures_symbol(decision.symbol):
            return False
        exposure = self.runtime.paper_service.settings.futures_exposure
        thresholds = self.runtime.paper_service.settings.mode_thresholds
        edge_to_cost_multiple = (
            float("inf")
            if decision.estimated_round_trip_cost_bps <= 0.0
            else decision.gross_expected_edge_bps / decision.estimated_round_trip_cost_bps
        )
        return (
            decision.predictability_score >= thresholds.futures_score_min + exposure.strong_score_buffer
            and decision.trend_strength >= exposure.strong_trend_strength_min
            and decision.volume_confirmation >= exposure.strong_volume_confirmation_min
            and decision.liquidity_score >= exposure.strong_liquidity_min
            and decision.volatility_penalty <= exposure.strong_volatility_penalty_max
            and decision.overheat_penalty <= exposure.strong_overheat_penalty_max
            and edge_to_cost_multiple >= exposure.strong_edge_to_cost_multiple_min
        )

    def _is_major_medium_futures_decision(self, decision: DecisionIntent) -> bool:
        if decision.final_mode != "futures" or not self._is_major_futures_symbol(decision.symbol):
            return False
        if self._is_major_strong_futures_decision(decision):
            return False
        exposure = self.runtime.paper_service.settings.futures_exposure
        edge_to_cost_multiple = (
            float("inf")
            if decision.estimated_round_trip_cost_bps <= 0.0
            else decision.gross_expected_edge_bps / decision.estimated_round_trip_cost_bps
        )
        return (
            decision.predictability_score >= exposure.pyramid_min_predictability_score
            and decision.trend_strength >= exposure.pyramid_min_trend_strength
            and decision.volume_confirmation >= exposure.pyramid_min_volume_confirmation
            and decision.liquidity_score >= exposure.soft_liquidity_floor
            and decision.net_expected_edge_bps >= max(exposure.min_entry_net_edge_bps, exposure.pyramid_min_net_edge_bps - 2.0)
            and edge_to_cost_multiple >= max(exposure.priority_edge_to_cost_multiple_min, 1.0)
        )

    def _open_positions_for_market(self, market: str) -> list[dict[str, object]]:
        return [
            position.as_dict()
            for position in self.paper_positions.values()
            if position.market == market and position.quantity_remaining > 0
        ]

    def _market_price(self, *, state: Any, fallback: float) -> float:
        if state is None:
            return fallback
        price = float(getattr(state, "last_trade_price", 0.0) or 0.0)
        return price if price > 0 else fallback

    def _position_stop_price(self, *, entry_price: float, stop_distance_bps: float, side: str) -> float:
        if stop_distance_bps <= 0:
            return entry_price
        stop_fraction = stop_distance_bps / 10000.0
        if side == "short":
            return entry_price * (1.0 + stop_fraction)
        return entry_price * (1.0 - stop_fraction)

    def _reward_bps(self, *, position: PaperPosition, price: float) -> float:
        if position.entry_price <= 0:
            return 0.0
        if position.side == "short":
            return (position.entry_price - price) / position.entry_price * 10000.0
        return (price - position.entry_price) / position.entry_price * 10000.0

    def _paper_position_roe_percent(self, *, position: PaperPosition, reward_bps: float) -> float:
        if position.market != "futures":
            return 0.0
        leverage = max(int(position.entry_planned_leverage), 1)
        return (reward_bps / 100.0) * leverage

    def _futures_proactive_take_profit_thresholds(self) -> tuple[float, ...]:
        exit_rules = self.runtime.paper_service.settings.exit_rules
        raw_thresholds = getattr(exit_rules, "futures_proactive_take_profit_roe_thresholds_percent", ())
        normalized = sorted({round(float(threshold), 6) for threshold in raw_thresholds if float(threshold) > 0.0})
        return tuple(normalized)

    def _futures_proactive_take_profit_fraction(self) -> float:
        exit_rules = self.runtime.paper_service.settings.exit_rules
        fraction = float(getattr(exit_rules, "futures_proactive_take_profit_fraction", 0.0) or 0.0)
        return max(0.0, min(fraction, 1.0))

    def _pending_proactive_take_profit_threshold(
        self,
        *,
        current_roe_percent: float,
        thresholds_hit: tuple[float, ...],
    ) -> float | None:
        if current_roe_percent <= 0.0:
            return None
        hit = {round(float(threshold), 6) for threshold in thresholds_hit}
        reached = [
            threshold
            for threshold in self._futures_proactive_take_profit_thresholds()
            if threshold not in hit and current_roe_percent >= threshold
        ]
        if not reached:
            return None
        return reached[-1]

    def _live_proactive_take_profit_key(self, *, identity: str, threshold: float) -> str:
        return f"{identity}:{threshold:.6f}"

    def _profit_protection_partial_triggered(
        self,
        *,
        peak_roe_percent: float,
        current_roe_percent: float,
        retrace_taken: bool,
        arm_threshold: float | None = None,
        retrace_threshold: float | None = None,
    ) -> bool:
        exit_rules = self.runtime.paper_service.settings.exit_rules
        if retrace_taken or current_roe_percent <= 0.0:
            return False
        effective_arm = (
            exit_rules.futures_profit_protection_arm_roe_percent
            if arm_threshold is None
            else arm_threshold
        )
        effective_retrace = (
            exit_rules.futures_profit_protection_retrace_roe_percent
            if retrace_threshold is None
            else retrace_threshold
        )
        if peak_roe_percent < effective_arm:
            return False
        drawdown = peak_roe_percent - current_roe_percent
        return drawdown >= effective_retrace

    def _position_stop_hit(self, *, position: PaperPosition, price: float) -> bool:
        if position.side == "short":
            return price >= position.active_stop_price
        return price <= position.active_stop_price

    def _record_closed_trade(
        self,
        *,
        position: PaperPosition,
        exit_price: float,
        quantity_closed: float,
        exit_time: datetime,
        exit_reason: str,
    ) -> None:
        if quantity_closed <= 0:
            return
        if position.side == "short":
            realized = (position.entry_price - exit_price) * quantity_closed
            return_bps = (position.entry_price - exit_price) / position.entry_price * 10000.0 if position.entry_price > 0 else 0.0
        else:
            realized = (exit_price - position.entry_price) * quantity_closed
            return_bps = (exit_price - position.entry_price) / position.entry_price * 10000.0 if position.entry_price > 0 else 0.0
        loss_combo_bucket_start = self._loss_combo_bucket_start(position.entry_time)
        loss_combo_key = self._loss_combo_key(
            symbol=position.symbol,
            side=position.side,
            timestamp=position.entry_time,
        )
        trade = {
            "symbol": position.symbol,
            "market": position.market,
            "side": position.side,
            "entry_time": position.entry_time,
            "exit_time": exit_time,
            "entry_price": round(position.entry_price, 6),
            "exit_price": round(exit_price, 6),
            "quantity": round(quantity_closed, 8),
            "realized_pnl_usd_estimate": round(realized, 6),
            "realized_return_bps_estimate": round(return_bps, 6),
            "exit_reason": exit_reason,
            "partial_exit": quantity_closed < position.quantity_opened,
            "loss_combo_key": loss_combo_key,
            "loss_combo_time_bucket_utc": loss_combo_bucket_start.strftime("%H:%M"),
        }
        self.closed_trades.append(trade)
        self._update_loss_combo_downgrade_state(
            combo_key=loss_combo_key,
            exit_time=exit_time,
            realized_pnl_usd=float(trade["realized_pnl_usd_estimate"]),
        )
        self._release_portfolio_capacity(exit_notional_usd=exit_price * quantity_closed)
        if self.log_store is not None:
            self.log_store.append("closed_trades", trade)
        self._send_trade_alert(trade)
        self._enforce_risk_limits(exit_time)

    def _send_telegram_alert(self, *, key: str, text: str) -> None:
        if key in self.sent_alert_keys:
            return
        if telegram_report_only_enabled():
            result = {"sent": False, "reason": "report_only_mode"}
        else:
            try:
                result = send_telegram_message(text)
            except Exception as exc:  # pragma: no cover
                result = {"sent": False, "error": repr(exc)}
        self.sent_alert_keys.add(key)
        payload = {"key": key, "text": text, "result": result}
        self.telegram_alerts.append(payload)
        if self.log_store is not None:
            self.log_store.append("telegram_alerts", payload)

    def _send_trade_alert(self, trade: dict[str, object]) -> None:
        reason = str(trade.get("exit_reason", ""))
        if reason not in {
            "PARTIAL_TAKE_PROFIT",
            "PROACTIVE_PARTIAL_TAKE_PROFIT",
            "PROFIT_PROTECTION_PARTIAL_TAKE_PROFIT",
            "BREAKEVEN_STOP",
            "STOP_LOSS",
        }:
            return
        symbol = str(trade.get("symbol", ""))
        pnl = float(trade.get("realized_pnl_usd_estimate", 0.0))
        bps = float(trade.get("realized_return_bps_estimate", 0.0))
        text = (
            f"[{reason}] {symbol}\n"
            f"realized_pnl_usd_estimate={pnl:.2f}\n"
            f"realized_return_bps_estimate={bps:.2f}"
        )
        self._send_telegram_alert(
            key=f"trade:{trade.get('exit_time')}:{symbol}:{reason}:{trade.get('quantity')}",
            text=text,
        )

    def _send_live_entry_alert(self, live_order: dict[str, object]) -> None:
        if not bool(live_order.get("accepted", False)):
            return
        symbol = str(live_order.get("symbol", ""))
        side = str(live_order.get("side", "")).upper()
        market = str(live_order.get("market", ""))
        quantity = float(live_order.get("quantity", 0.0))
        order_id = str(live_order.get("order_id", ""))
        reference_price = float(live_order.get("reference_price", 0.0))
        text = (
            f"[LIVE_ENTRY] {symbol}\n"
            f"market={market}\n"
            f"side={side}\n"
            f"quantity={quantity:.8f}\n"
            f"reference_price={reference_price:.4f}\n"
            f"order_id={order_id or 'unknown'}"
        )
        self._send_telegram_alert(
            key=f"live-entry:{order_id or live_order.get('client_oid') or symbol}:{live_order.get('timestamp')}",
            text=text,
        )

    def _parse_order_error_code(self, error_message: str) -> str:
        return parse_error_code(error_message)

    def _clear_live_entry_starvation(self, *, symbol: str) -> None:
        self.live_entry_starvation_attempts_by_symbol.pop(symbol, None)
        self.live_entry_starvation_last_at_by_symbol.pop(symbol, None)

    def _note_live_entry_starvation(
        self,
        *,
        symbol: str,
        timestamp: datetime,
        reason: str,
        fingerprint: str,
    ) -> None:
        reset_window_seconds = max(self.runtime.decision_interval_minutes * 180, 900)
        last_seen = self.live_entry_starvation_last_at_by_symbol.get(symbol)
        attempts = self.live_entry_starvation_attempts_by_symbol.get(symbol, 0)
        if last_seen is None or (timestamp - last_seen).total_seconds() > reset_window_seconds:
            attempts = 0
        attempts += 1
        self.live_entry_starvation_attempts_by_symbol[symbol] = attempts
        self.live_entry_starvation_last_at_by_symbol[symbol] = timestamp
        self.last_executed_fingerprint_by_symbol.pop(symbol, None)
        if attempts >= 2:
            self._refresh_account_state_after_live_order_activity(
                symbol=symbol,
                timestamp=timestamp,
                stage="live_entry_watchdog",
                reason=reason,
            )
        if attempts >= 3:
            self._apply_preflight_symbol_cooldown(
                symbol=symbol,
                timestamp=timestamp,
                seconds=max(self.runtime.decision_interval_minutes * 120, 300),
            )
            self._send_telegram_alert(
                key=f"live-entry-watchdog:{symbol}:{timestamp.isoformat()}",
                text=(
                    f"[LIVE_ENTRY_WATCHDOG] {symbol}\n"
                    f"reason={reason}\n"
                    f"attempt_count={attempts}\n"
                    f"last_fingerprint={fingerprint}"
                ),
            )
        self.self_healing.record_entry_starvation(
            now=timestamp,
            symbol=symbol,
            attempt_count=attempts,
            reason=reason,
            details={
                "fingerprint": fingerprint,
            },
        )

    def _cooldown_seconds_for_error_code(self, code: str) -> int:
        if code == "429":
            return 300
        if code in {"40774", "40893", "45110", "45111"}:
            return 900
        return 120

    def _apply_order_error_cooldown(
        self,
        *,
        symbol: str,
        error_message: str,
        timestamp: datetime,
        stage: str = "live_order",
        exchange_id: str | None = None,
    ) -> None:
        code = self._parse_order_error_code(error_message)
        cooldown_seconds = self._cooldown_seconds_for_error_code(code)
        until = timestamp + timedelta(seconds=cooldown_seconds)
        current = self.order_error_cooldowns.get(symbol)
        if current is None or until > current:
            self.order_error_cooldowns[symbol] = until
        self.self_healing.record_runtime_error(
            now=timestamp,
            symbol=symbol,
            error_message=error_message,
            exchange_id=exchange_id or (getattr(self.live_order_executor, "_exchange_id", lambda: "binance")() if self.live_order_executor is not None else "binance"),
            stage=stage,
        )
        self._send_telegram_alert(
            key=f"order-cooldown:{symbol}:{code}:{timestamp.isoformat()}",
            text=f"[ORDER_COOLDOWN] {symbol}\ncode={code or 'unknown'}\nuntil={until.isoformat()}",
        )

    def _refresh_account_state_after_live_order_activity(
        self,
        *,
        symbol: str,
        timestamp: datetime,
        stage: str,
        reason: str,
    ) -> None:
        if self.rest_client is None:
            return
        try:
            self._refresh_account_state(evaluate_live_positions=False)
        except Exception as exc:
            if self.log_store is not None:
                self.log_store.append(
                    "account_sync",
                    {
                        "timestamp": timestamp,
                        "symbol": symbol,
                        "stage": stage,
                        "reason": reason,
                        "status": "failed",
                        "error": repr(exc),
                    },
                )
            return
        if self.log_store is not None:
            self.log_store.append(
                "account_sync",
                {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "stage": stage,
                    "reason": reason,
                    "status": "refreshed",
                },
            )

    def _is_order_cooldown_active(self, symbol: str, timestamp: datetime) -> bool:
        until = self.order_error_cooldowns.get(symbol)
        if until is None:
            return False
        if timestamp >= until:
            self.order_error_cooldowns.pop(symbol, None)
            return False
        return True

    def _manual_reentry_cooldown_until(self, timestamp: datetime) -> datetime:
        seconds = max(60, self.runtime.decision_interval_minutes * 60)
        return timestamp + timedelta(seconds=seconds)

    def _loss_combo_bucket_start(self, timestamp: datetime) -> datetime:
        cfg = self.runtime.paper_service.settings.loss_combo_downgrade
        bucket_minutes = max(int(cfg.time_bucket_minutes), int(self.runtime.decision_interval_minutes), 1)
        utc_timestamp = timestamp.astimezone(timezone.utc)
        day_start = utc_timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        minutes_since_midnight = utc_timestamp.hour * 60 + utc_timestamp.minute
        bucket_start_minutes = (minutes_since_midnight // bucket_minutes) * bucket_minutes
        return day_start + timedelta(minutes=bucket_start_minutes)

    def _loss_combo_key(self, *, symbol: str, side: str, timestamp: datetime) -> str:
        bucket_start = self._loss_combo_bucket_start(timestamp)
        return f"{symbol}|{side}|{bucket_start.strftime('%H:%M')}"

    def _loss_combo_realized_loss_usd(self, *, combo_key: str, now: datetime) -> float:
        cfg = self.runtime.paper_service.settings.loss_combo_downgrade
        if not cfg.enabled or not combo_key:
            return 0.0
        cutoff = now - timedelta(hours=max(int(cfg.lookback_hours), 1))
        realized_loss = 0.0
        for trade in self.closed_trades:
            if str(trade.get("loss_combo_key", "")) != combo_key:
                continue
            if bool(trade.get("partial_exit", False)):
                continue
            exit_time = self._parse_runtime_datetime(trade.get("exit_time"))
            if exit_time is None or exit_time < cutoff:
                continue
            pnl = float(trade.get("realized_pnl_usd_estimate", 0.0))
            if pnl < 0.0:
                realized_loss += abs(pnl)
        return round(realized_loss, 6)

    def _loss_combo_stage(self, *, realized_loss_usd: float) -> str | None:
        cfg = self.runtime.paper_service.settings.loss_combo_downgrade
        if not cfg.enabled or realized_loss_usd <= 0.0:
            return None
        if cfg.cooldown_loss_usd > 0.0 and realized_loss_usd >= cfg.cooldown_loss_usd:
            return "cooldown"
        if cfg.observe_only_loss_usd > 0.0 and realized_loss_usd >= cfg.observe_only_loss_usd:
            return "observe_only"
        if cfg.prune_loss_usd > 0.0 and realized_loss_usd >= cfg.prune_loss_usd:
            return "prune"
        return None

    def _apply_loss_combo_cooldown(self, *, combo_key: str, timestamp: datetime) -> None:
        cfg = self.runtime.paper_service.settings.loss_combo_downgrade
        if not cfg.enabled or not combo_key or cfg.cooldown_minutes <= 0:
            return
        until = timestamp + timedelta(minutes=max(int(cfg.cooldown_minutes), 1))
        current = self.loss_combo_cooldowns.get(combo_key)
        if current is None or until > current:
            self.loss_combo_cooldowns[combo_key] = until

    def _is_loss_combo_cooldown_active(self, *, combo_key: str, timestamp: datetime) -> bool:
        until = self.loss_combo_cooldowns.get(combo_key)
        if until is None:
            return False
        if timestamp >= until:
            self.loss_combo_cooldowns.pop(combo_key, None)
            return False
        return True

    def _update_loss_combo_downgrade_state(self, *, combo_key: str, exit_time: datetime, realized_pnl_usd: float) -> None:
        if realized_pnl_usd >= 0.0:
            return
        realized_loss_usd = self._loss_combo_realized_loss_usd(combo_key=combo_key, now=exit_time)
        if self._loss_combo_stage(realized_loss_usd=realized_loss_usd) == "cooldown":
            self._apply_loss_combo_cooldown(combo_key=combo_key, timestamp=exit_time)

    def _apply_loss_combo_downgrade(self, *, decision: DecisionIntent) -> DecisionIntent:
        cfg = self.runtime.paper_service.settings.loss_combo_downgrade
        if (
            not cfg.enabled
            or decision.final_mode not in {"spot", "futures"}
            or decision.side not in {"long", "short"}
            or decision.order_intent_notional_usd <= 0.0
        ):
            return decision
        combo_key = self._loss_combo_key(
            symbol=decision.symbol,
            side=decision.side,
            timestamp=decision.timestamp,
        )
        if self._is_loss_combo_cooldown_active(combo_key=combo_key, timestamp=decision.timestamp):
            reasons = tuple(sorted(set(decision.rejection_reasons + ("LOSS_COMBO_COOLDOWN",))))
            return replace(
                decision,
                final_mode="cash",
                side="flat",
                order_intent_notional_usd=0.0,
                stop_distance_bps=0.0,
                rejection_reasons=reasons,
            )
        realized_loss_usd = self._loss_combo_realized_loss_usd(combo_key=combo_key, now=decision.timestamp)
        stage = None
        if cfg.observe_only_loss_usd > 0.0 and realized_loss_usd >= cfg.observe_only_loss_usd:
            stage = "observe_only"
        elif cfg.prune_loss_usd > 0.0 and realized_loss_usd >= cfg.prune_loss_usd:
            stage = "prune"
        if stage is None:
            return decision
        stage_reason = {
            "prune": ("LOSS_COMBO_PRUNE",),
            "observe_only": ("LOSS_COMBO_OBSERVE_ONLY", "OBSERVE_ONLY_SYMBOL"),
        }.get(stage)
        if stage_reason is None:
            return decision
        reasons = tuple(sorted(set(decision.rejection_reasons + stage_reason)))
        return replace(
            decision,
            final_mode="cash",
            side="flat",
            order_intent_notional_usd=0.0,
            stop_distance_bps=0.0,
            rejection_reasons=reasons,
        )

    def _apply_preflight_symbol_cooldown(self, *, symbol: str, timestamp: datetime, seconds: int = 120) -> None:
        until = timestamp + timedelta(seconds=max(seconds, 60))
        current = self.manual_symbol_cooldowns.get(symbol)
        if current is None or until > current:
            self.manual_symbol_cooldowns[symbol] = until

    def _futures_reallocation_cooldown_window(self) -> timedelta:
        seconds = max(60, self.runtime.decision_interval_minutes * 120)
        return timedelta(seconds=seconds)

    def _futures_reallocation_cooldown_for_timestamp(self, timestamp: datetime) -> datetime:
        return timestamp + self._futures_reallocation_cooldown_window()

    def _is_futures_reallocation_cooldown_active(self, timestamp: datetime) -> bool:
        until = self.futures_reallocation_cooldown_until
        if until is None:
            return False
        if timestamp >= until:
            self.futures_reallocation_cooldown_until = None
            return False
        return True

    def _is_manual_symbol_cooldown_active(self, symbol: str, timestamp: datetime) -> bool:
        until = self.manual_symbol_cooldowns.get(symbol)
        if until is None:
            return False
        if timestamp >= until:
            self.manual_symbol_cooldowns.pop(symbol, None)
            return False
        return True

    def _cancel_symbol_open_orders(self, *, symbol: str) -> None:
        if self.rest_client is None or not hasattr(self.rest_client, "cancel_order"):
            return
        orders_payload = self.open_orders_snapshot.get("orders", [])
        if isinstance(orders_payload, dict):
            candidate_orders = orders_payload.get("entrustedList") or orders_payload.get("list") or []
        else:
            candidate_orders = orders_payload or []
        for order in candidate_orders:
            if str(order.get("symbol", "")) != symbol:
                continue
            order_id = str(order.get("orderId") or order.get("id") or order.get("clientOid") or "")
            if not order_id:
                continue
            try:
                response = self.rest_client.cancel_order(market="futures", symbol=symbol, order_id=order_id)
            except Exception as exc:
                if self.log_store is not None:
                    self.log_store.append(
                        "order_errors",
                        {
                            "timestamp": datetime.now(tz=timezone.utc),
                            "symbol": symbol,
                            "market": "futures",
                            "stage": "manual_close_cancel_order",
                            "order_id": order_id,
                            "error": repr(exc),
                        },
                    )
                continue
            if self.log_store is not None:
                self.log_store.append(
                    "manual_close_order_cleanup",
                    {
                        "timestamp": datetime.now(tz=timezone.utc),
                        "symbol": symbol,
                        "order_id": order_id,
                        "response": response,
                    },
                )

    def _account_execution_balance_usd(self, snapshot: dict[str, Any]) -> float | None:
        raw_value = snapshot.get("executionAvailableBalance", snapshot.get("availableBalance"))
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return None

    def _estimated_position_margin_release_usd(
        self,
        *,
        previous_live_position: dict[str, Any],
        paper_position: PaperPosition,
    ) -> float:
        margin_size = float(previous_live_position.get("marginSize") or 0.0)
        if margin_size > 0.0:
            return margin_size
        quantity = self._live_position_quantity(previous_live_position)
        if quantity <= 0.0:
            quantity = paper_position.quantity_remaining
        price = 0.0
        for key in ("markPrice", "breakEvenPrice", "openPriceAvg"):
            try:
                price = float(previous_live_position.get(key) or 0.0)
            except (TypeError, ValueError):
                price = 0.0
            if price > 0.0:
                break
        if price <= 0.0:
            price = paper_position.current_price if paper_position.current_price > 0.0 else paper_position.entry_price
        leverage = max(
            int(
                float(
                    previous_live_position.get("leverage")
                    or previous_live_position.get("marginLeverage")
                    or paper_position.entry_planned_leverage
                    or 1.0
                )
            ),
            1,
        )
        return max((price * quantity) / leverage, 0.0)

    def _manual_close_is_confirmed(
        self,
        *,
        symbol: str,
        previous_live_position: dict[str, Any],
        previous_account_snapshot: dict[str, Any],
    ) -> bool:
        paper_position = self.paper_positions.get(symbol)
        if paper_position is None or paper_position.market != "futures" or paper_position.quantity_remaining <= 0.0:
            return False
        previous_balance = self._account_execution_balance_usd(previous_account_snapshot)
        current_balance = self._account_execution_balance_usd(self.account_snapshot)
        if previous_balance is None or current_balance is None or current_balance <= previous_balance:
            return False
        estimated_margin_release = self._estimated_position_margin_release_usd(
            previous_live_position=previous_live_position,
            paper_position=paper_position,
        )
        if estimated_margin_release <= 0.0:
            return False
        balance_released = current_balance - previous_balance
        required_release = max(estimated_margin_release * 0.5, 1.0)
        return balance_released >= required_release

    def _reconcile_manual_live_closes(
        self,
        *,
        previous_live_positions: list[dict[str, Any]],
        previous_account_snapshot: dict[str, Any],
    ) -> None:
        previous_positions_by_symbol: dict[str, dict[str, Any]] = {}
        for position in previous_live_positions:
            symbol = str(position.get("symbol", ""))
            if not symbol or self._live_position_quantity(position) <= 0.0:
                continue
            previous_positions_by_symbol[symbol] = position
        if not previous_positions_by_symbol:
            return
        active_symbols = set(self._active_live_futures_positions_by_symbol())
        now = datetime.now(tz=timezone.utc)
        for symbol, previous_live_position in previous_positions_by_symbol.items():
            if symbol in active_symbols:
                continue
            if not self._manual_close_is_confirmed(
                symbol=symbol,
                previous_live_position=previous_live_position,
                previous_account_snapshot=previous_account_snapshot,
            ):
                continue
            self._cleanup_missing_on_exchange_position(symbol=symbol, now=now, reason="MANUAL_CLOSE_SYNCED")
            self.futures_missing_on_exchange_counts.pop(symbol, None)

    def _consecutive_mismatch_threshold(self) -> int:
        return 2

    def _missing_in_paper_threshold(self) -> int:
        return self._consecutive_mismatch_threshold()

    def _missing_on_exchange_threshold(self) -> int:
        return max(self._consecutive_mismatch_threshold(), 4)

    def _missing_on_exchange_threshold_for_symbol(self, symbol: str) -> int:
        threshold = self._missing_on_exchange_threshold()
        if self._is_major_futures_symbol(symbol):
            major_threshold = int(self.runtime.paper_service.settings.live_position_risk.major_missing_on_exchange_threshold or 0)
            if major_threshold > 0:
                return max(threshold, major_threshold)
        return threshold

    def _update_consecutive_mismatch_counts(self, *, counts: dict[str, int], active_symbols: set[str]) -> None:
        for symbol in list(counts):
            if symbol not in active_symbols:
                counts.pop(symbol, None)
        for symbol in active_symbols:
            counts[symbol] = counts.get(symbol, 0) + 1

    def _parse_live_position_timestamp(self, position: dict[str, Any]) -> datetime | None:
        for key in ("cTime", "uTime"):
            raw_value = position.get(key)
            if raw_value in (None, ""):
                continue
            try:
                parsed = float(raw_value)
            except (TypeError, ValueError):
                continue
            if parsed <= 0.0:
                continue
            if parsed >= 1_000_000_000_000:
                parsed /= 1000.0
            try:
                return datetime.fromtimestamp(parsed, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                continue
        return None

    def _parse_runtime_datetime(self, raw_value: Any) -> datetime | None:
        if isinstance(raw_value, datetime):
            return raw_value if raw_value.tzinfo is not None else raw_value.replace(tzinfo=timezone.utc)
        if raw_value in (None, "") or not isinstance(raw_value, str):
            return None
        try:
            parsed = datetime.fromisoformat(raw_value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    def _live_position_reference_price(self, *, symbol: str, position: dict[str, Any]) -> float:
        state = self.runtime.dispatcher.store.get(symbol)
        market_price = self._market_price(state=state, fallback=0.0)
        if market_price > 0.0:
            return market_price
        for key in ("markPrice", "breakEvenPrice", "openPriceAvg"):
            value = float(position.get(key) or 0.0)
            if value > 0.0:
                return value
        return 0.0

    def _live_position_break_even_price(self, *, position: dict[str, Any]) -> float:
        for key in ("breakEvenPrice", "openPriceAvg"):
            value = float(position.get(key) or 0.0)
            if value > 0.0:
                return value
        return self._live_position_reference_price(symbol=str(position.get("symbol", "")), position=position)

    def _live_position_exit_fee_bps(self, *, symbol: str) -> float:
        fee_bps = float(self.runtime.paper_service.settings.fees.futures_taker_fee_bps)
        extractor = getattr(self.runtime.paper_service, "feature_extractor", None)
        calibration = getattr(extractor, "cost_calibration", None)
        if calibration is not None:
            fee_bps = max(fee_bps, float(calibration.for_symbol(symbol).empirical_fee_bps))
        return fee_bps

    def _is_fee_sensitive_partial_exit_reason(self, reason: str) -> bool:
        return reason in {
            "LIVE_POSITION_NON_CORE_PROFIT_EXIT",
            "LIVE_POSITION_PROACTIVE_PARTIAL_TAKE_PROFIT",
            "LIVE_POSITION_PROFIT_PROTECTION",
            "LIVE_POSITION_TURNAROUND_TAKE_PROFIT",
            "LIVE_POSITION_UNREALIZED_TAKE_PROFIT",
            "LIVE_POSITION_PARTIAL_TAKE_PROFIT",
            "LIVE_PORTFOLIO_PROFIT_LOCK",
        }

    def _live_partial_exit_mode(self, reason: str) -> str:
        if reason in {
            "LIVE_POSITION_PROACTIVE_PARTIAL_TAKE_PROFIT",
            "LIVE_POSITION_PARTIAL_TAKE_PROFIT",
        }:
            return "take_profit"
        if reason in {
            "LIVE_POSITION_PROFIT_PROTECTION",
            "LIVE_POSITION_UNREALIZED_TAKE_PROFIT",
            "LIVE_PORTFOLIO_PROFIT_LOCK",
        }:
            return "protection"
        if reason in {
            "LIVE_POSITION_TURNAROUND_TAKE_PROFIT",
            "LIVE_POSITION_NON_CORE_PROFIT_EXIT",
        }:
            return "turnaround"
        return ""

    def _can_trigger_live_partial_exit(self, *, identity: str, reason: str, now: datetime) -> bool:
        mode = self._live_partial_exit_mode(reason)
        if not mode:
            return True
        cfg = self.runtime.paper_service.settings.live_position_risk
        last_at = self.live_partial_exit_last_at_by_identity.get(identity)
        if (
            last_at is not None
            and cfg.partial_exit_min_interval_minutes > 0
            and (now - last_at).total_seconds() / 60.0 < cfg.partial_exit_min_interval_minutes
        ):
            return False
        active_mode = self.live_partial_exit_mode_by_identity.get(identity)
        if active_mode and active_mode != mode:
            return False
        return True

    def _effective_live_partial_exit_fraction(
        self,
        *,
        position: dict[str, Any],
        reason: str,
        fraction: float,
    ) -> float:
        effective = max(min(fraction, 1.0), 0.0)
        if effective >= 0.999 or not self._is_fee_sensitive_partial_exit_reason(reason):
            return effective
        if self._is_major_futures_symbol(str(position.get("symbol", ""))):
            effective = max(effective, self.runtime.paper_service.settings.live_position_risk.major_partial_exit_fraction)
        return min(effective, 1.0)

    def _expected_live_partial_exit_after_fee_usd(
        self,
        *,
        position: dict[str, Any],
        quantity: float,
    ) -> float:
        symbol = str(position.get("symbol", ""))
        reference_price = self._live_position_reference_price(symbol=symbol, position=position)
        break_even_price = self._live_position_break_even_price(position=position)
        if reference_price <= 0.0 or break_even_price <= 0.0 or quantity <= 0.0:
            return 0.0
        hold_side = self._normalize_live_position_side(position)
        if hold_side == "short":
            gross_pnl = (break_even_price - reference_price) * quantity
        else:
            gross_pnl = (reference_price - break_even_price) * quantity
        exit_fee = reference_price * quantity * (self._live_position_exit_fee_bps(symbol=symbol) / 10000.0)
        return gross_pnl - exit_fee

    def _live_position_paper_context(self, symbol: str) -> PaperPosition | None:
        position = self.paper_positions.get(symbol)
        if position is None or position.market != "futures":
            return None
        return position

    def _live_turnaround_grace_applies(
        self,
        *,
        position: dict[str, Any],
        identity: str,
        roe_percent: float,
        now: datetime,
    ) -> bool:
        cfg = self.runtime.paper_service.settings.live_position_risk
        if not cfg.turnaround_grace_enabled:
            return False
        if roe_percent > cfg.soft_stop_roe_percent or roe_percent <= cfg.turnaround_abort_roe_percent:
            return False
        paper_position = self._live_position_paper_context(str(position.get("symbol", "")))
        if paper_position is None:
            return False
        last_decision_time = paper_position.latest_decision_time
        if last_decision_time is None:
            return False
        if (now - last_decision_time).total_seconds() > cfg.turnaround_signal_max_age_minutes * 60:
            return False
        if paper_position.side != self._normalize_live_position_side(position):
            return False
        worst_roe = self.live_worst_roe_by_identity.get(identity, roe_percent)
        recovery = roe_percent - worst_roe
        if recovery < cfg.turnaround_recovery_roe_points:
            return False
        return (
            paper_position.latest_predictability_score >= cfg.turnaround_predictability_min
            and paper_position.latest_net_expected_edge_bps >= cfg.turnaround_net_edge_min_bps
            and paper_position.latest_liquidity_score >= cfg.turnaround_liquidity_min
            and paper_position.latest_predictability_score >= cfg.turnaround_predictability_min
        )

    def _major_drawdown_grace_applies(
        self,
        *,
        position: dict[str, Any],
        identity: str,
        roe_percent: float,
        holding_minutes: float,
        now: datetime,
    ) -> bool:
        cfg = self.runtime.paper_service.settings.live_position_risk
        if not cfg.major_drawdown_grace_enabled:
            self.live_major_drawdown_grace_started_at_by_identity.pop(identity, None)
            return False
        if not self._is_major_futures_symbol(str(position.get("symbol", ""))):
            self.live_major_drawdown_grace_started_at_by_identity.pop(identity, None)
            return False
        if roe_percent > cfg.soft_stop_roe_percent:
            self.live_major_drawdown_grace_started_at_by_identity.pop(identity, None)
            return False
        if roe_percent <= cfg.major_drawdown_abort_roe_percent:
            self.live_major_drawdown_grace_started_at_by_identity.pop(identity, None)
            return False
        paper_position = self._live_position_paper_context(str(position.get("symbol", "")))
        if paper_position is None:
            self.live_major_drawdown_grace_started_at_by_identity.pop(identity, None)
            return False
        if paper_position.side != self._normalize_live_position_side(position):
            self.live_major_drawdown_grace_started_at_by_identity.pop(identity, None)
            return False
        last_decision_time = paper_position.latest_decision_time
        if last_decision_time is None:
            self.live_major_drawdown_grace_started_at_by_identity.pop(identity, None)
            return False
        if (now - last_decision_time).total_seconds() > cfg.major_drawdown_signal_max_age_minutes * 60:
            self.live_major_drawdown_grace_started_at_by_identity.pop(identity, None)
            return False
        if (
            paper_position.latest_predictability_score < cfg.major_drawdown_predictability_min
            or paper_position.latest_net_expected_edge_bps < cfg.major_drawdown_net_edge_min_bps
            or paper_position.latest_liquidity_score < cfg.major_drawdown_liquidity_min
        ):
            self.live_major_drawdown_grace_started_at_by_identity.pop(identity, None)
            return False
        started_at = self.live_major_drawdown_grace_started_at_by_identity.get(identity)
        if started_at is None:
            self.live_major_drawdown_grace_started_at_by_identity[identity] = now
            return True
        if (now - started_at).total_seconds() / 60.0 > cfg.major_drawdown_grace_minutes:
            self.live_major_drawdown_grace_started_at_by_identity.pop(identity, None)
            return False
        return True

    def _build_reconciled_paper_position(self, *, position: dict[str, Any]) -> PaperPosition | None:
        symbol = str(position.get("symbol", ""))
        if not symbol:
            return None
        quantity = self._live_position_quantity(position)
        if quantity <= 0.0:
            return None
        current_price = self._live_position_reference_price(symbol=symbol, position=position)
        if current_price <= 0.0:
            return None
        entry_price = float(position.get("openPriceAvg") or position.get("breakEvenPrice") or 0.0)
        if entry_price <= 0.0:
            entry_price = current_price
        side = self._normalize_live_position_side(position)
        leverage = max(int(float(position.get("leverage") or 1.0)), 1)
        entry_time = self._parse_live_position_timestamp(position) or datetime.now(tz=timezone.utc)
        best_price = max(entry_price, current_price)
        worst_price = min(entry_price, current_price)
        return PaperPosition(
            symbol=symbol,
            market="futures",
            side=side,
            entry_time=entry_time,
            entry_price=entry_price,
            current_price=current_price,
            quantity_opened=quantity,
            quantity_remaining=quantity,
            stop_distance_bps=0.0,
            active_stop_price=entry_price,
            best_price=best_price,
            worst_price=worst_price,
            entry_predictability_score=0.0,
            entry_liquidity_score=0.0,
            entry_net_expected_edge_bps=0.0,
            entry_estimated_round_trip_cost_bps=0.0,
            entry_planned_leverage=leverage,
            latest_predictability_score=0.0,
            latest_liquidity_score=0.0,
            latest_net_expected_edge_bps=0.0,
            latest_estimated_round_trip_cost_bps=0.0,
            exchange_synced=True,
        )

    def _reserve_capacity_for_reconciled_position(self, position: PaperPosition) -> None:
        self.remaining_portfolio_capacity_usd = max(
            0.0,
            self.remaining_portfolio_capacity_usd - position.current_notional_usd_estimate(),
        )

    def _paper_position_from_runtime_payload(self, payload: dict[str, Any]) -> PaperPosition | None:
        symbol = str(payload.get("symbol", ""))
        market = str(payload.get("market", ""))
        side = str(payload.get("side", ""))
        quantity_remaining = float(payload.get("quantity_remaining") or 0.0)
        if not symbol or market != "futures" or side not in {"long", "short"} or quantity_remaining <= 0.0:
            return None
        current_price = float(payload.get("current_price") or payload.get("entry_price") or 0.0)
        entry_price = float(payload.get("entry_price") or current_price or 0.0)
        if current_price <= 0.0 or entry_price <= 0.0:
            return None
        quantity_opened = max(float(payload.get("quantity_opened") or quantity_remaining), quantity_remaining)
        exchange_synced = bool(payload.get("exchange_synced", False))
        if not exchange_synced:
            exchange_synced = (
                float(payload.get("stop_distance_bps") or 0.0) <= 0.0
                and float(payload.get("entry_predictability_score") or 0.0) == 0.0
                and float(payload.get("entry_liquidity_score") or 0.0) == 0.0
                and float(payload.get("entry_net_expected_edge_bps") or 0.0) == 0.0
                and float(payload.get("entry_estimated_round_trip_cost_bps") or 0.0) == 0.0
            )
        r_multiple_partial_take_profit_taken = bool(payload.get("r_multiple_partial_take_profit_taken", False))
        profit_protection_retrace_taken = bool(payload.get("profit_protection_retrace_taken", False))
        proactive_take_profit_thresholds_hit = tuple(
            round(float(threshold), 6)
            for threshold in payload.get("proactive_take_profit_thresholds_hit", ())
            if float(threshold) > 0.0
        )
        partial_take_profit_taken = bool(payload.get("partial_take_profit_taken", False))
        partial_take_profit_taken = partial_take_profit_taken or r_multiple_partial_take_profit_taken
        partial_take_profit_taken = partial_take_profit_taken or profit_protection_retrace_taken
        partial_take_profit_taken = partial_take_profit_taken or bool(proactive_take_profit_thresholds_hit)
        return PaperPosition(
            symbol=symbol,
            market=market,
            side=side,
            entry_time=self._parse_runtime_datetime(payload.get("entry_time")) or datetime.now(tz=timezone.utc),
            entry_price=entry_price,
            current_price=current_price,
            quantity_opened=quantity_opened,
            quantity_remaining=quantity_remaining,
            stop_distance_bps=float(payload.get("stop_distance_bps") or 0.0),
            active_stop_price=float(payload.get("active_stop_price") or entry_price),
            best_price=float(payload.get("best_price") or max(entry_price, current_price)),
            worst_price=float(payload.get("worst_price") or min(entry_price, current_price)),
            entry_predictability_score=float(payload.get("entry_predictability_score") or 0.0),
            entry_liquidity_score=float(payload.get("entry_liquidity_score") or 0.0),
            entry_net_expected_edge_bps=float(payload.get("entry_net_expected_edge_bps") or 0.0),
            entry_estimated_round_trip_cost_bps=float(payload.get("entry_estimated_round_trip_cost_bps") or 0.0),
            entry_planned_leverage=max(int(float(payload.get("entry_planned_leverage") or 1.0)), 1),
            latest_predictability_score=float(
                payload.get("latest_predictability_score")
                if payload.get("latest_predictability_score") is not None
                else payload.get("entry_predictability_score") or 0.0
            ),
            latest_liquidity_score=float(
                payload.get("latest_liquidity_score")
                if payload.get("latest_liquidity_score") is not None
                else payload.get("entry_liquidity_score") or 0.0
            ),
            latest_net_expected_edge_bps=float(
                payload.get("latest_net_expected_edge_bps")
                if payload.get("latest_net_expected_edge_bps") is not None
                else payload.get("entry_net_expected_edge_bps") or 0.0
            ),
            latest_estimated_round_trip_cost_bps=float(
                payload.get("latest_estimated_round_trip_cost_bps")
                if payload.get("latest_estimated_round_trip_cost_bps") is not None
                else payload.get("entry_estimated_round_trip_cost_bps") or 0.0
            ),
            latest_decision_time=self._parse_runtime_datetime(payload.get("latest_decision_time")),
            partial_take_profit_taken=partial_take_profit_taken,
            r_multiple_partial_take_profit_taken=r_multiple_partial_take_profit_taken,
            profit_protection_retrace_taken=profit_protection_retrace_taken,
            proactive_take_profit_thresholds_hit=proactive_take_profit_thresholds_hit,
            exit_confirmation_count=int(payload.get("exit_confirmation_count") or 0),
            last_exit_signal_reason=str(payload.get("last_exit_signal_reason") or ""),
            peak_roe_percent=float(payload.get("peak_roe_percent") or 0.0),
            exchange_synced=exchange_synced,
            confirmation_pending=bool(payload.get("confirmation_pending", False)),
            confirmation_pending_since=self._parse_runtime_datetime(payload.get("confirmation_pending_since")),
        )

    def restore_futures_state_from_runtime(
        self,
        *,
        state_payload: dict[str, Any],
        summary_payload: dict[str, Any] | None = None,
    ) -> int:
        live_positions_by_symbol = self._active_live_futures_positions_by_symbol()
        live_symbols = set(live_positions_by_symbol)
        if not live_symbols:
            self.futures_missing_in_paper_counts = {}
            self.futures_missing_on_exchange_counts = {}
            return 0
        summary = summary_payload or {}
        candidate_positions = (
            state_payload.get("paper_open_futures_positions")
            or summary.get("paper_open_futures_positions")
            or summary.get("open_futures_positions")
            or []
        )
        restored = 0
        for item in candidate_positions:
            if not isinstance(item, dict):
                continue
            position = self._paper_position_from_runtime_payload(item)
            if position is None or position.symbol not in live_symbols or position.symbol in self.paper_positions:
                continue
            self.paper_positions[position.symbol] = position
            self._reserve_capacity_for_reconciled_position(position)
            restored += 1
        active_paper_symbols = set(self._open_paper_futures_positions_by_symbol())
        for symbol in sorted(live_symbols - active_paper_symbols):
            self._reconcile_missing_in_paper_position(
                position=live_positions_by_symbol[symbol],
                persisted_cycles=0,
            )
            restored += 1
        active_paper_symbols = set(self._open_paper_futures_positions_by_symbol())
        self.futures_missing_in_paper_counts = {
            str(symbol): int(count)
            for symbol, count in (state_payload.get("futures_missing_in_paper_counts") or {}).items()
            if symbol in (live_symbols - active_paper_symbols)
        }
        self.futures_missing_on_exchange_counts = {
            str(symbol): int(count)
            for symbol, count in (state_payload.get("futures_missing_on_exchange_counts") or {}).items()
            if symbol in (active_paper_symbols - live_symbols)
        }
        return restored

    def _reconcile_missing_in_paper_position(self, *, position: dict[str, Any], persisted_cycles: int) -> None:
        paper_position = self._build_reconciled_paper_position(position=position)
        if paper_position is None:
            return
        existing = self.paper_positions.get(paper_position.symbol)
        if existing is not None:
            return
        self.paper_positions[paper_position.symbol] = paper_position
        self._reserve_capacity_for_reconciled_position(paper_position)
        self.self_healing.record_mismatch_recovery(
            now=datetime.now(tz=timezone.utc),
            symbol=paper_position.symbol,
            action="reconcile_missing_in_paper",
            persisted_cycles=persisted_cycles,
        )
        if self.log_store is not None:
            self.log_store.append(
                "futures_position_reconciliation",
                {
                    "timestamp": datetime.now(tz=timezone.utc),
                    "symbol": paper_position.symbol,
                    "action": "SYNC_MISSING_IN_PAPER",
                    "persisted_cycles": persisted_cycles,
                    "side": paper_position.side,
                    "entry_price": paper_position.entry_price,
                    "current_price": paper_position.current_price,
                    "quantity_remaining": paper_position.quantity_remaining,
                    "entry_planned_leverage": paper_position.entry_planned_leverage,
                },
            )

    def _cleanup_missing_on_exchange_position(self, *, symbol: str, now: datetime, reason: str) -> None:
        paper_position = self.paper_positions.pop(symbol, None)
        if paper_position is not None and paper_position.quantity_remaining > 0:
            self._record_closed_trade(
                position=paper_position,
                exit_price=paper_position.current_price,
                quantity_closed=paper_position.quantity_remaining,
                exit_time=now,
                exit_reason=reason,
            )
        self._cancel_symbol_open_orders(symbol=symbol)
        cooldown_until = self._manual_reentry_cooldown_until(now)
        current = self.manual_symbol_cooldowns.get(symbol)
        if current is None or cooldown_until > current:
            self.manual_symbol_cooldowns[symbol] = cooldown_until
        self.self_healing.record_mismatch_recovery(
            now=now,
            symbol=symbol,
            action="cleanup_missing_on_exchange",
            persisted_cycles=self._missing_on_exchange_threshold_for_symbol(symbol),
        )
        self._send_telegram_alert(
            key=f"manual-close:{symbol}:{now.isoformat()}",
            text=(
                f"[{reason}] {symbol}\n"
                f"reentry_block_until={cooldown_until.isoformat()}"
            ),
        )
        if self.log_store is not None:
            self.log_store.append(
                "manual_close_sync",
                {
                    "timestamp": now,
                    "symbol": symbol,
                    "cooldown_until": cooldown_until,
                    "reason": reason,
                },
            )

    def _reconcile_persistent_futures_position_mismatch(self) -> None:
        live_positions_by_symbol = self._active_live_futures_positions_by_symbol()
        paper_positions_by_symbol = self._open_paper_futures_positions_by_symbol()
        missing_in_paper = set(live_positions_by_symbol) - set(paper_positions_by_symbol)
        missing_on_exchange = set(paper_positions_by_symbol) - set(live_positions_by_symbol)
        self._update_consecutive_mismatch_counts(
            counts=self.futures_missing_in_paper_counts,
            active_symbols=missing_in_paper,
        )
        self._update_consecutive_mismatch_counts(
            counts=self.futures_missing_on_exchange_counts,
            active_symbols=missing_on_exchange,
        )
        for symbol in sorted(missing_in_paper):
            cycles = self.futures_missing_in_paper_counts.get(symbol, 0)
            if cycles < self._missing_in_paper_threshold():
                continue
            self._reconcile_missing_in_paper_position(
                position=live_positions_by_symbol[symbol],
                persisted_cycles=cycles,
            )
            self.futures_missing_in_paper_counts.pop(symbol, None)
        now = datetime.now(tz=timezone.utc)
        for symbol in sorted(missing_on_exchange):
            cycles = self.futures_missing_on_exchange_counts.get(symbol, 0)
            threshold = self._missing_on_exchange_threshold_for_symbol(symbol)
            if cycles < threshold:
                continue
            self._cleanup_missing_on_exchange_position(symbol=symbol, now=now, reason="MANUAL_CLOSE_SYNCED")
            self.futures_missing_on_exchange_counts.pop(symbol, None)

    def _position_roe_percent(self, position: dict[str, Any]) -> float:
        margin = float(position.get("marginSize") or 0.0)
        if margin <= 0.0:
            return 0.0
        unrealized = float(position.get("unrealizedPL") or 0.0)
        return (unrealized / margin) * 100.0

    def _position_unrealized_pnl_usd(self, position: dict[str, Any]) -> float:
        return float(position.get("unrealizedPL") or 0.0)

    def _live_position_identity(self, position: dict[str, Any]) -> str:
        return "|".join(
            [
                str(position.get("symbol", "")),
                str(position.get("holdSide") or position.get("posSide") or ""),
                str(position.get("cTime") or position.get("uTime") or ""),
            ]
        )

    def _live_position_holding_minutes(self, *, position: dict[str, Any], now: datetime) -> float:
        opened_at = self._parse_live_position_timestamp(position)
        if opened_at is None:
            return 0.0
        return max((now - opened_at).total_seconds() / 60.0, 0.0)

    def _live_client_oid(
        self,
        *,
        position: dict[str, Any],
        reason: str,
        suffix: str,
    ) -> str:
        symbol = str(position.get("symbol", "")).upper()[:12]
        hold_side = str(position.get("holdSide") or position.get("posSide") or "").lower()[:5]
        position_token = str(position.get("uTime") or position.get("cTime") or "")[-6:]
        timestamp_token = str(time.time_ns())[-8:]
        normalized_reason = re.sub(r"[^a-z0-9]+", "", reason.lower())[:12]
        oid = f"{symbol}-{hold_side}-{normalized_reason}-{suffix}-{position_token}-{timestamp_token}"
        return oid[:64]

    def _reset_live_position_breakeven_protection(self, *, position: dict[str, Any]) -> None:
        if self.rest_client is None or not hasattr(self.rest_client, "place_futures_position_tpsl"):
            return
        symbol = str(position.get("symbol", ""))
        hold_side = str(position.get("holdSide", "")).lower()
        if not symbol or hold_side not in {"long", "short"}:
            return
        breakeven_price = float(position.get("breakEvenPrice") or position.get("openPriceAvg") or 0.0)
        if breakeven_price <= 0.0:
            return
        adapter = self.live_order_executor or DecisionLiveOrderAdapter(
            self.rest_client,
            self.runtime.paper_service.settings,
        )
        self._reconcile_live_position_plan_orders(
            position=position,
            hold_side=hold_side,
        )
        payload = {
            "marginCoin": "USDT",
            "productType": "USDT-FUTURES",
            "symbol": symbol,
            "holdSide": hold_side,
            "stopLossTriggerPrice": adapter.format_trigger_price(
                value=breakeven_price,
                market="futures",
                symbol=symbol,
            ),
            "stopLossTriggerType": "mark_price",
            "stopLossClientOid": self._live_client_oid(
                position=position,
                reason="breakeven",
                suffix="sl",
            ),
        }
        response = self.rest_client.place_futures_position_tpsl(order_params=payload)
        if self.log_store is not None:
            self.log_store.append(
                "live_position_actions",
                {
                    "timestamp": datetime.now(tz=timezone.utc),
                    "symbol": symbol,
                    "market": "futures",
                    "action": "RESET_BREAKEVEN_PROTECTION",
                    "payload": payload,
                    "response": response,
                },
            )

    def _reconcile_live_position_plan_orders(self, *, position: dict[str, Any], hold_side: str) -> None:
        if (
            self.rest_client is None
            or not hasattr(self.rest_client, "get_futures_pending_plan_orders")
            or not hasattr(self.rest_client, "cancel_futures_plan_orders")
            or not getattr(self.rest_client, "supports_private_reads", True)
        ):
            return
        symbol = str(position.get("symbol", ""))
        if not symbol or hold_side not in {"long", "short"}:
            return
        try:
            pending = self.rest_client.get_futures_pending_plan_orders(symbol=symbol, plan_type="profit_loss")
        except Exception:
            return
        rows = pending.get("orders", []) if isinstance(pending, dict) else []
        relevant = [
            row
            for row in rows
            if isinstance(row, dict)
            and str(row.get("symbol", "")) == symbol
            and str(row.get("posSide", row.get("holdSide", ""))).lower() == hold_side
            and str(row.get("tradeSide", "")).lower() == "close"
            and str(row.get("planStatus", "")).lower() == "live"
        ]
        if len(relevant) <= 2:
            return
        relevant.sort(key=lambda row: float(row.get("uTime") or row.get("cTime") or 0.0), reverse=True)
        keep: set[str] = set()
        for plan_type in ("profit_plan", "loss_plan"):
            for row in relevant:
                if str(row.get("planType", "")).lower() == plan_type:
                    order_id = str(row.get("orderId", "")).strip()
                    if order_id:
                        keep.add(order_id)
                    break
        cancel_groups: dict[str, list[dict[str, str]]] = {}
        for row in relevant:
            order_id = str(row.get("orderId", "")).strip()
            client_oid = str(row.get("clientOid", "")).strip()
            plan_type = str(row.get("planType", "")).strip().lower()
            if not order_id or order_id in keep:
                continue
            cancel_groups.setdefault(plan_type, []).append({"orderId": order_id, "clientOid": client_oid})
        if not cancel_groups:
            return
        responses = []
        cancelled_count = 0
        for plan_type, cancel_rows in cancel_groups.items():
            response = self.rest_client.cancel_futures_plan_orders(
                symbol=symbol,
                order_id_list=cancel_rows,
                plan_type=plan_type or None,
            )
            responses.append({"plan_type": plan_type, "response": response})
            cancelled_count += len(cancel_rows)
        if self.log_store is not None:
            self.log_store.append(
                "live_position_actions",
                {
                    "timestamp": datetime.now(tz=timezone.utc),
                    "symbol": symbol,
                    "market": "futures",
                    "action": "RECONCILE_POSITION_TPSL",
                    "hold_side": hold_side,
                    "cancelled_order_count": cancelled_count,
                    "responses": responses,
                },
            )

    def _live_portfolio_unrealized_ratio(self) -> float:
        total_unrealized = sum(self._position_unrealized_pnl_usd(position) for position in self.live_positions_snapshot)
        return total_unrealized / max(self.equity_usd, 1e-9)

    def _realized_pnl_total(self) -> float:
        return round(
            sum(float(trade.get("realized_pnl_usd_estimate", 0.0)) for trade in self.closed_trades),
            6,
        )

    def _live_portfolio_profit_ratio(self) -> float:
        total_unrealized = sum(self._position_unrealized_pnl_usd(position) for position in self.live_positions_snapshot)
        return (self._realized_pnl_total() + total_unrealized) / max(self.equity_usd, 1e-9)

    def _standard_stop_loss_exits_enabled(self) -> bool:
        return not self.runtime.paper_service.settings.live_position_risk.disable_standard_stop_loss_exits

    def _select_live_portfolio_profit_lock_target(self) -> dict[str, Any] | None:
        profitable_positions = [
            position
            for position in self.live_positions_snapshot
            if self._position_unrealized_pnl_usd(position) > 0.0 and self._live_position_quantity(position) > 0.0
        ]
        if not profitable_positions:
            return None
        profitable_positions.sort(
            key=lambda position: (
                self._position_unrealized_pnl_usd(position),
                self._position_roe_percent(position),
            ),
            reverse=True,
        )
        return profitable_positions[0]

    def _bitget_live_position_mode(self, position: dict[str, Any]) -> str:
        raw_mode = str(position.get("posMode") or position.get("positionMode") or "").strip().lower()
        if "hedge" in raw_mode or "double" in raw_mode:
            return "hedge"
        if "one_way" in raw_mode or "one-way" in raw_mode or "unilateral" in raw_mode or "single" in raw_mode:
            return "one_way"
        return "unknown"

    def _bitget_close_order_candidates(
        self,
        *,
        position: dict[str, Any],
        quantity: float,
        reason: str,
    ) -> tuple[dict[str, Any], ...]:
        symbol = str(position.get("symbol", ""))
        adapter = self.live_order_executor or DecisionLiveOrderAdapter(
            self.rest_client,
            self.runtime.paper_service.settings,
        )
        position_side = self._normalize_live_position_side(position)
        one_way_side = "sell" if position_side == "long" else "buy"
        hedge_side = "buy" if position_side == "long" else "sell"
        base_payload: dict[str, Any] = {
            "symbol": symbol,
            "productType": "USDT-FUTURES",
            "marginCoin": "USDT",
            "marginMode": "crossed",
            "orderType": "market",
            "size": adapter.format_quantity(
                market="futures",
                symbol=symbol,
                quantity=quantity,
            ),
            "clientOid": self._live_client_oid(
                position=position,
                reason=reason,
                suffix="close",
            ),
        }
        one_way_close = dict(base_payload)
        one_way_close["side"] = one_way_side
        one_way_close["reduceOnly"] = "YES"

        hedge_close = dict(base_payload)
        hedge_close["side"] = hedge_side
        hedge_close["tradeSide"] = "close"

        one_way_without_reduce_only = dict(base_payload)
        one_way_without_reduce_only["side"] = one_way_side

        mode = self._bitget_live_position_mode(position)
        if mode == "hedge":
            return (hedge_close, one_way_close, one_way_without_reduce_only)
        if mode == "one_way":
            return (one_way_close, hedge_close, one_way_without_reduce_only)
        return (one_way_close, hedge_close, one_way_without_reduce_only)

    def _close_live_position(self, *, position: dict[str, Any], reason: str, fraction: float = 1.0) -> None:
        if self.rest_client is None or not hasattr(self.rest_client, "build_order_params") or not hasattr(self.rest_client, "place_order"):
            return
        symbol = str(position.get("symbol", ""))
        hold_side = str(position.get("holdSide", "")).lower()
        total_quantity = float(position.get("total") or position.get("available") or 0.0)
        fraction = self._effective_live_partial_exit_fraction(
            position=position,
            reason=reason,
            fraction=fraction,
        )
        quantity = total_quantity * max(min(fraction, 1.0), 0.0)
        if not symbol or quantity <= 0.0:
            return
        adapter = self.live_order_executor or DecisionLiveOrderAdapter(
            self.rest_client,
            self.runtime.paper_service.settings,
        )
        total_quantity = adapter.normalize_quantity(market="futures", symbol=symbol, quantity=total_quantity)
        quantity = adapter.normalize_quantity(market="futures", symbol=symbol, quantity=quantity)
        min_quantity = self._market_min_quantity(market="futures", symbol=symbol)
        if min_quantity > 0.0 and quantity < min_quantity and total_quantity >= min_quantity:
            quantity = total_quantity
            fraction = 1.0
        if (
            fraction < 0.999
            and self._is_fee_sensitive_partial_exit_reason(reason)
            and self.runtime.paper_service.settings.live_position_risk.partial_exit_min_expected_after_fee_usd > 0.0
        ):
            expected_after_fee = self._expected_live_partial_exit_after_fee_usd(
                position=position,
                quantity=quantity,
            )
            if expected_after_fee < self.runtime.paper_service.settings.live_position_risk.partial_exit_min_expected_after_fee_usd:
                if self.log_store is not None:
                    self.log_store.append(
                        "live_position_actions",
                        {
                            "timestamp": datetime.now(tz=timezone.utc),
                            "symbol": symbol,
                            "market": "futures",
                            "accepted": False,
                            "reason": f"{reason}_SKIPPED_FEE",
                            "quantity": quantity,
                            "expected_after_fee_usd": round(expected_after_fee, 6),
                        },
                    )
                return
        side = "SELL" if hold_side == "long" else "BUY"
        u_time = str(position.get("uTime", ""))
        alert_key = f"live-position-close:{symbol}:{u_time}:{reason}:{fraction:.4f}"
        if alert_key in self.sent_alert_keys:
            return
        exchange_id = getattr(self.rest_client, "exchange_id", "")
        is_bitget_close = exchange_id == "bitget"
        if is_bitget_close:
            order_candidates = self._bitget_close_order_candidates(
                position=position,
                quantity=quantity,
                reason=reason,
            )
            order_params = dict(order_candidates[0])
        else:
            order_candidates = ()
            order_params = self.rest_client.build_order_params(
                market="futures",
                symbol=symbol,
                side=side,
                order_type="MARKET",
                quantity=quantity,
                reduce_only=True,
                client_oid=self._live_client_oid(
                    position=position,
                    reason=reason,
                    suffix="close",
                ),
            )
        attempted_order_params = dict(order_params)

        def _record_already_closed(exc: Exception) -> None:
            if self.log_store is not None:
                self.log_store.append(
                    "live_position_actions",
                    {
                        "timestamp": datetime.now(tz=timezone.utc),
                        "symbol": symbol,
                        "market": "futures",
                        "side": str(attempted_order_params.get("side", side)).lower(),
                        "quantity": quantity,
                        "accepted": False,
                        "reason": f"{reason}_ALREADY_CLOSED",
                        "response": {"error": repr(exc)},
                    },
                )

        def _record_close_size_error(exc: Exception) -> None:
            error_payload = {
                "timestamp": datetime.now(tz=timezone.utc),
                "symbol": symbol,
                "market": "futures",
                "stage": "live_position_close",
                "error": repr(exc),
                "reason": reason,
                "fraction": fraction,
            }
            if self.log_store is not None:
                self.log_store.append("order_errors", error_payload)
            self.self_healing.record_runtime_error(
                now=datetime.now(tz=timezone.utc),
                symbol=symbol,
                error_message=repr(exc),
                exchange_id=getattr(self.rest_client, "exchange_id", "bitget"),
                stage="live_position_close",
            )

        try:
            attempted_order_params = dict(order_params)
            response = self.rest_client.place_order(market="futures", order_params=order_params)
        except Exception as exc:
            message = str(exc)
            can_retry_bitget_close = (
                is_bitget_close
                and (
                    adapter._is_bitget_unilateral_error(message)
                    or "22002" in message
                    or "No position to close" in message
                )
            )
            if can_retry_bitget_close:
                retry_error = exc
                alternates = order_candidates[1:] or adapter._bitget_alternate_futures_params(order_params)
                for alternate_params in alternates:
                    try:
                        attempted_order_params = dict(alternate_params)
                        response = self.rest_client.place_order(market="futures", order_params=alternate_params)
                    except Exception as retry_exc:
                        retry_error = retry_exc
                        retry_message = str(retry_exc)
                        if not (
                            adapter._is_bitget_unilateral_error(retry_message)
                            or "22002" in retry_message
                            or "No position to close" in retry_message
                        ):
                            raise
                        continue
                    order_params = alternate_params
                    break
                else:
                    if "22002" in str(retry_error) or "No position to close" in str(retry_error):
                        _record_already_closed(retry_error)
                        return
                    raise retry_error
            else:
                if ("45111" in message or "40017" in message) and fraction < 0.999 and total_quantity > quantity:
                    try:
                        full_order_candidates = self._bitget_close_order_candidates(
                            position=position,
                            quantity=total_quantity,
                            reason=reason,
                        ) if is_bitget_close else ()
                        if is_bitget_close:
                            attempted_order_params = dict(full_order_candidates[0])
                            response = self.rest_client.place_order(market="futures", order_params=full_order_candidates[0])
                            order_params = full_order_candidates[0]
                            quantity = total_quantity
                            fraction = 1.0
                        else:
                            raise RuntimeError(message)
                    except Exception as retry_exc:
                        _record_close_size_error(retry_exc)
                        return
                elif "45111" in message or "40017" in message:
                    _record_close_size_error(exc)
                    return
                if "22002" in message or "No position to close" in message:
                    _record_already_closed(exc)
                    return
                raise
        payload = {
            "timestamp": datetime.now(tz=timezone.utc),
            "symbol": symbol,
            "market": "futures",
            "side": str(order_params.get("side", side)).lower(),
            "quantity": quantity,
            "accepted": str(response.get("status", "")).upper() not in {"REJECTED", "EXPIRED", "ERROR"},
            "reason": reason,
            "partial_exit": fraction < 0.999,
            "response": response,
        }
        self.live_orders.append(payload)
        if self.log_store is not None:
            self.log_store.append("live_position_actions", payload)
        if fraction < 0.999:
            identity = self._live_position_identity(position)
            mode = self._live_partial_exit_mode(reason)
            if mode:
                self.live_partial_exit_last_at_by_identity[identity] = datetime.now(tz=timezone.utc)
                self.live_partial_exit_mode_by_identity[identity] = mode
        roe = self._position_roe_percent(position)
        self._send_telegram_alert(
            key=alert_key,
            text=f"[{reason}] {symbol}\nroe_percent={roe:.2f}\nunrealized_pl={float(position.get('unrealizedPL') or 0.0):.2f}",
        )
        if fraction < 0.999:
            self._reset_live_position_breakeven_protection(position=position)

    def _evaluate_live_positions(self) -> None:
        cfg = self.runtime.paper_service.settings.live_position_risk
        if not cfg.enabled or not self.live_positions_snapshot:
            self.live_portfolio_peak_unrealized_ratio = 0.0
            self.live_portfolio_profit_lock_taken = False
            self.live_portfolio_full_exit_taken = False
            return
        proactive_fraction = self._futures_proactive_take_profit_fraction()
        now = datetime.now(tz=timezone.utc)
        portfolio_unrealized_ratio = self._live_portfolio_unrealized_ratio()
        portfolio_profit_ratio = self._live_portfolio_profit_ratio()
        self.live_portfolio_peak_unrealized_ratio = max(
            self.live_portfolio_peak_unrealized_ratio,
            portfolio_unrealized_ratio,
        )
        if portfolio_unrealized_ratio <= 0.0:
            self.live_portfolio_peak_unrealized_ratio = 0.0
            self.live_portfolio_profit_lock_taken = False
        if (
            cfg.portfolio_full_exit_only
            and cfg.portfolio_full_exit_profit_ratio > 0.0
            and portfolio_profit_ratio >= cfg.portfolio_full_exit_profit_ratio
            and not self.live_portfolio_full_exit_taken
        ):
            self.live_portfolio_full_exit_taken = True
            for position in list(self.live_positions_snapshot):
                self._close_live_position(position=position, reason="LIVE_PORTFOLIO_FULL_EXIT", fraction=1.0)
            return
        for position in self.live_positions_snapshot:
            symbol = str(position.get("symbol", ""))
            in_core_universe = symbol in set(self.runtime.paper_service.settings.universe)
            is_major_symbol = self._is_major_futures_symbol(symbol)
            hold_side = str(position.get("holdSide") or position.get("posSide") or "").lower()
            self._reconcile_live_position_plan_orders(position=position, hold_side=hold_side)
            roe = self._position_roe_percent(position)
            unrealized_pnl = self._position_unrealized_pnl_usd(position)
            holding_minutes = self._live_position_holding_minutes(position=position, now=now)
            margin_ratio = float(position.get("marginRatio") or 0.0)
            identity = self._live_position_identity(position)
            peak_roe = self.live_peak_roe_by_identity.get(identity, roe)
            peak_roe = max(peak_roe, roe)
            self.live_peak_roe_by_identity[identity] = peak_roe
            worst_roe = self.live_worst_roe_by_identity.get(identity, roe)
            worst_roe = min(worst_roe, roe)
            self.live_worst_roe_by_identity[identity] = worst_roe
            peak_unrealized_pnl = self.live_peak_unrealized_pnl_by_identity.get(identity, unrealized_pnl)
            peak_unrealized_pnl = max(peak_unrealized_pnl, unrealized_pnl)
            self.live_peak_unrealized_pnl_by_identity[identity] = peak_unrealized_pnl
            if self._standard_stop_loss_exits_enabled() and roe <= cfg.stop_loss_roe_percent:
                self._close_live_position(position=position, reason="LIVE_POSITION_STOP_LOSS")
                continue
            if margin_ratio >= cfg.margin_ratio_emergency:
                self._close_live_position(position=position, reason="LIVE_POSITION_MARGIN_RISK")
                continue
            if not in_core_universe:
                if self._standard_stop_loss_exits_enabled() and roe <= cfg.non_core_soft_stop_roe_percent:
                    self._close_live_position(position=position, reason="LIVE_POSITION_NON_CORE_SOFT_STOP_LOSS")
                    continue
                if (
                    not cfg.portfolio_full_exit_only
                    and
                    roe >= cfg.non_core_take_profit_roe_percent
                    and unrealized_pnl >= cfg.non_core_take_profit_min_usd
                ):
                    self._close_live_position(
                        position=position,
                        reason="LIVE_POSITION_NON_CORE_PROFIT_EXIT",
                        fraction=cfg.non_core_take_profit_fraction,
                    )
                    continue
            if (
                in_core_universe
                and is_major_symbol
                and cfg.major_low_signal_max_holding_minutes > 0
                and cfg.major_low_signal_min_unrealized_usd > 0.0
                and holding_minutes >= cfg.major_low_signal_max_holding_minutes
                and unrealized_pnl <= cfg.major_low_signal_min_unrealized_usd
                and peak_roe < max(
                    cfg.major_low_signal_min_roe_percent,
                    cfg.major_profit_protection_arm_roe_percent,
                )
                and worst_roe > cfg.soft_stop_roe_percent
            ):
                self._close_live_position(position=position, reason="LIVE_POSITION_MAJOR_LOW_SIGNAL_EXIT")
                continue
            turnaround_grace = self._live_turnaround_grace_applies(
                position=position,
                identity=identity,
                roe_percent=roe,
                now=now,
            )
            major_drawdown_grace = self._major_drawdown_grace_applies(
                position=position,
                identity=identity,
                roe_percent=roe,
                holding_minutes=holding_minutes,
                now=now,
            )
            if (
                self._standard_stop_loss_exits_enabled()
                and roe <= cfg.soft_stop_roe_percent
                and not turnaround_grace
                and not major_drawdown_grace
            ):
                self._close_live_position(position=position, reason="LIVE_POSITION_SOFT_STOP_LOSS")
                continue
            if cfg.portfolio_full_exit_only:
                continue
            proactive_threshold = self._pending_proactive_take_profit_threshold(
                current_roe_percent=roe,
                thresholds_hit=tuple(
                    threshold
                    for threshold in self._futures_proactive_take_profit_thresholds()
                    if self._live_proactive_take_profit_key(identity=identity, threshold=threshold)
                    in self.live_proactive_take_profit_keys
                ),
            )
            if proactive_threshold is not None and proactive_fraction > 0.0:
                if not self._can_trigger_live_partial_exit(identity=identity, reason="LIVE_POSITION_PROACTIVE_PARTIAL_TAKE_PROFIT", now=now):
                    continue
                for threshold in self._futures_proactive_take_profit_thresholds():
                    if threshold <= proactive_threshold:
                        self.live_proactive_take_profit_keys.add(
                            self._live_proactive_take_profit_key(identity=identity, threshold=threshold)
                        )
                self._close_live_position(
                    position=position,
                    reason="LIVE_POSITION_PROACTIVE_PARTIAL_TAKE_PROFIT",
                    fraction=proactive_fraction,
                )
                continue
            if self._profit_protection_partial_triggered(
                peak_roe_percent=peak_roe,
                current_roe_percent=roe,
                retrace_taken=identity in self.live_profit_protection_keys,
                arm_threshold=cfg.major_profit_protection_arm_roe_percent if is_major_symbol else None,
                retrace_threshold=cfg.major_profit_protection_retrace_roe_percent if is_major_symbol else None,
            ):
                if not self._can_trigger_live_partial_exit(identity=identity, reason="LIVE_POSITION_PROFIT_PROTECTION", now=now):
                    continue
                self.live_profit_protection_keys.add(identity)
                self._close_live_position(
                    position=position,
                    reason="LIVE_POSITION_PROFIT_PROTECTION",
                    fraction=0.5,
                )
                continue
            if (
                cfg.turnaround_grace_enabled
                and worst_roe <= cfg.soft_stop_roe_percent
                and roe >= cfg.profit_flip_fast_take_profit_roe_percent
                and identity not in self.live_turnaround_take_profit_keys
            ):
                if not self._can_trigger_live_partial_exit(identity=identity, reason="LIVE_POSITION_TURNAROUND_TAKE_PROFIT", now=now):
                    continue
                self.live_turnaround_take_profit_keys.add(identity)
                self._close_live_position(
                    position=position,
                    reason="LIVE_POSITION_TURNAROUND_TAKE_PROFIT",
                    fraction=cfg.profit_flip_take_profit_fraction,
                )
                continue
            if (
                peak_unrealized_pnl >= cfg.position_unrealized_profit_arm_usd
                and (peak_unrealized_pnl - unrealized_pnl) >= cfg.position_unrealized_profit_retrace_usd
                and identity not in self.live_unrealized_take_profit_keys
            ):
                if not self._can_trigger_live_partial_exit(identity=identity, reason="LIVE_POSITION_UNREALIZED_TAKE_PROFIT", now=now):
                    continue
                self.live_unrealized_take_profit_keys.add(identity)
                self._close_live_position(
                    position=position,
                    reason="LIVE_POSITION_UNREALIZED_TAKE_PROFIT",
                    fraction=cfg.position_unrealized_take_profit_fraction,
                )
                continue
            if not self._futures_proactive_take_profit_thresholds() and peak_roe >= cfg.take_profit_roe_percent:
                legacy_key = self._live_proactive_take_profit_key(identity=identity, threshold=cfg.take_profit_roe_percent)
                if legacy_key not in self.live_proactive_take_profit_keys:
                    drawdown = peak_roe - roe
                    if drawdown >= 2.0 or roe >= cfg.take_profit_roe_percent + 2.0:
                        if not self._can_trigger_live_partial_exit(identity=identity, reason="LIVE_POSITION_PARTIAL_TAKE_PROFIT", now=now):
                            continue
                        self.live_proactive_take_profit_keys.add(legacy_key)
                        self._close_live_position(
                            position=position,
                            reason="LIVE_POSITION_PARTIAL_TAKE_PROFIT",
                            fraction=0.5,
                        )
        portfolio_drawdown_ratio = self.live_portfolio_peak_unrealized_ratio - portfolio_unrealized_ratio
        if (
            not self.live_portfolio_profit_lock_taken
            and self.live_portfolio_peak_unrealized_ratio >= cfg.portfolio_unrealized_profit_arm_ratio
            and portfolio_drawdown_ratio >= cfg.portfolio_unrealized_profit_retrace_ratio
        ):
            target = self._select_live_portfolio_profit_lock_target()
            if target is not None:
                target_identity = self._live_position_identity(target)
                if not self._can_trigger_live_partial_exit(identity=target_identity, reason="LIVE_PORTFOLIO_PROFIT_LOCK", now=now):
                    return
                self.live_portfolio_profit_lock_taken = True
                self._close_live_position(
                    position=target,
                    reason="LIVE_PORTFOLIO_PROFIT_LOCK",
                    fraction=cfg.portfolio_profit_lock_take_profit_fraction,
                )

    def _current_unrealized_total(self) -> float:
        return round(sum(position.unrealized_pnl_usd_estimate() for position in self.paper_positions.values()), 6)

    def _paper_portfolio_profit_ratio(self) -> float:
        return (self._realized_pnl_total() + self._current_unrealized_total()) / max(self.equity_usd, 1e-9)

    def _realized_loss_ratio(self, *, now: datetime, scope: str) -> float:
        realized_loss = 0.0
        iso_year, iso_week, _ = now.isocalendar()
        for trade in self.closed_trades:
            exit_time = trade.get("exit_time")
            if not isinstance(exit_time, datetime):
                continue
            same_scope = False
            if scope == "daily":
                same_scope = exit_time.date() == now.date()
            elif scope == "weekly":
                year, week, _ = exit_time.isocalendar()
                same_scope = (year, week) == (iso_year, iso_week)
            if not same_scope:
                continue
            pnl = float(trade.get("realized_pnl_usd_estimate", 0.0))
            if pnl < 0:
                realized_loss += abs(pnl)
        return realized_loss / max(self.equity_usd, 1e-9)

    def _intraday_drawdown_ratio(self, *, now: datetime) -> float:
        realized_today = 0.0
        for trade in self.closed_trades:
            exit_time = trade.get("exit_time")
            if not isinstance(exit_time, datetime) or exit_time.date() != now.date():
                continue
            realized_today += float(trade.get("realized_pnl_usd_estimate", 0.0))
        combined = realized_today + self._current_unrealized_total()
        return abs(min(combined, 0.0)) / max(self.equity_usd, 1e-9)

    def _enforce_risk_limits(self, now: datetime) -> None:
        risk = self.runtime.paper_service.settings.risk
        checks = (
            ("DAILY_REALIZED_LOSS_LIMIT", self._realized_loss_ratio(now=now, scope="daily"), risk.daily_realized_loss_limit),
            ("WEEKLY_REALIZED_LOSS_LIMIT", self._realized_loss_ratio(now=now, scope="weekly"), risk.weekly_realized_loss_limit),
            ("INTRADAY_DRAWDOWN_LIMIT", self._intraday_drawdown_ratio(now=now), risk.intraday_drawdown_limit),
        )
        for code, ratio, limit in checks:
            if ratio < limit:
                continue
            if not self.runtime.kill_switch.armed or code not in self.runtime.kill_switch.reasons:
                self.runtime.kill_switch.arm(code)
                self._send_telegram_alert(
                    key=f"risk:{code}:{now.date().isoformat()}",
                    text=f"[{code}] ratio={ratio:.4f} limit={limit:.4f}",
                )

    def _apply_post_take_profit_stop(self, *, position: PaperPosition, current_price: float) -> None:
        mode = self.runtime.paper_service.settings.exit_rules.post_tp_stop_mode.strip().lower()
        if mode == "breakeven":
            position.active_stop_price = position.entry_price
            return
        if "trail" in mode:
            stop_fraction = max(position.stop_distance_bps / 10000.0, 0.0025)
            if position.side == "short":
                position.active_stop_price = min(position.active_stop_price, current_price * (1.0 + stop_fraction))
            else:
                position.active_stop_price = max(position.active_stop_price, current_price * (1.0 - stop_fraction))
            return
        position.active_stop_price = position.entry_price

    def _take_partial_paper_profit(
        self,
        *,
        position: PaperPosition,
        exit_price: float,
        timestamp: datetime,
        fraction: float,
        exit_reason: str,
    ) -> bool:
        partial_fraction = max(0.0, min(fraction, 1.0))
        if partial_fraction <= 0.0 or position.quantity_remaining <= 0.0:
            return False
        quantity_to_close = position.quantity_remaining * partial_fraction
        if quantity_to_close <= 0.0:
            return False
        self._record_closed_trade(
            position=position,
            exit_price=exit_price,
            quantity_closed=quantity_to_close,
            exit_time=timestamp,
            exit_reason=exit_reason,
        )
        position.quantity_remaining = max(position.quantity_remaining - quantity_to_close, 0.0)
        position.partial_take_profit_taken = True
        position.exit_confirmation_count = 0
        position.last_exit_signal_reason = ""
        self._apply_post_take_profit_stop(position=position, current_price=exit_price)
        if position.quantity_remaining <= 0.0:
            self.paper_positions.pop(position.symbol, None)
            self.futures_pyramid_add_counts.pop(position.symbol, None)
        return True

    def _should_pyramid_futures_position(
        self,
        *,
        position: PaperPosition,
        decision: DecisionIntent,
        price: float,
    ) -> bool:
        exposure = self.runtime.paper_service.settings.futures_exposure
        if not exposure.pyramid_enabled:
            return False
        if position.market != "futures" or decision.final_mode != "futures":
            return False
        if position.symbol != decision.symbol or position.side != decision.side:
            return False
        if exposure.pyramid_major_only and not self._is_major_futures_symbol(position.symbol):
            return False
        if self.futures_pyramid_add_counts.get(position.symbol, 0) >= max(int(exposure.pyramid_max_adds_per_symbol), 0):
            return False
        reward_bps = self._reward_bps(position=position, price=price)
        current_roe_percent = self._paper_position_roe_percent(position=position, reward_bps=reward_bps)
        if current_roe_percent < exposure.pyramid_min_roe_percent:
            return False
        return (
            decision.predictability_score >= exposure.pyramid_min_predictability_score
            and decision.net_expected_edge_bps >= exposure.pyramid_min_net_edge_bps
            and decision.trend_strength >= exposure.pyramid_min_trend_strength
            and decision.volume_confirmation >= exposure.pyramid_min_volume_confirmation
        )

    def _apply_pyramid_fill_to_position(
        self,
        *,
        position: PaperPosition,
        decision: DecisionIntent,
        price: float,
    ) -> None:
        exposure = self.runtime.paper_service.settings.futures_exposure
        if decision.order_intent_notional_usd <= 0 or price <= 0:
            return
        added_notional = decision.order_intent_notional_usd * max(exposure.pyramid_size_multiplier, 0.0)
        if added_notional <= 0.0:
            return
        added_quantity = added_notional / price
        if added_quantity <= 0.0:
            return
        previous_quantity_opened = position.quantity_opened
        new_quantity_opened = previous_quantity_opened + added_quantity
        weighted_entry = (
            (position.entry_price * previous_quantity_opened) + (price * added_quantity)
        ) / max(new_quantity_opened, 1e-9)
        position.entry_price = weighted_entry
        position.quantity_opened = new_quantity_opened
        position.quantity_remaining += added_quantity
        position.current_price = price
        position.best_price = max(position.best_price, price)
        position.worst_price = min(position.worst_price, price)
        position.latest_predictability_score = decision.predictability_score
        position.latest_liquidity_score = decision.liquidity_score
        position.latest_net_expected_edge_bps = decision.net_expected_edge_bps
        position.latest_estimated_round_trip_cost_bps = decision.estimated_round_trip_cost_bps
        position.latest_decision_time = decision.timestamp
        self.remaining_portfolio_capacity_usd = max(
            0.0,
            self.remaining_portfolio_capacity_usd - added_notional,
        )
        self.futures_pyramid_add_counts[position.symbol] = self.futures_pyramid_add_counts.get(position.symbol, 0) + 1

    def _open_paper_position(self, *, decision: DecisionIntent, price: float) -> bool:
        if decision.final_mode not in {"spot", "futures"} or decision.side not in {"long", "short"}:
            return False
        if price <= 0 or decision.order_intent_notional_usd <= 0:
            return False
        quantity = decision.order_intent_notional_usd / price
        leverage = 1
        if decision.final_mode == "futures":
            leverage = select_futures_leverage(
                predictability_score=decision.predictability_score,
                trend_strength=decision.trend_strength,
                volume_confirmation=decision.volume_confirmation,
                liquidity_score=decision.liquidity_score,
                volatility_penalty=decision.volatility_penalty,
                overheat_penalty=decision.overheat_penalty,
                net_expected_edge_bps=decision.net_expected_edge_bps,
                estimated_round_trip_cost_bps=decision.estimated_round_trip_cost_bps,
                settings=self.runtime.paper_service.settings,
            )
        self.remaining_portfolio_capacity_usd = max(
            0.0,
            self.remaining_portfolio_capacity_usd - decision.order_intent_notional_usd,
        )
        self.paper_positions[decision.symbol] = PaperPosition(
            symbol=decision.symbol,
            market=decision.final_mode,
            side=decision.side,
            entry_time=decision.timestamp,
            entry_price=price,
            current_price=price,
            quantity_opened=quantity,
            quantity_remaining=quantity,
            stop_distance_bps=max(decision.stop_distance_bps, 0.0),
            active_stop_price=self._position_stop_price(
                entry_price=price,
                stop_distance_bps=max(decision.stop_distance_bps, 0.0),
                side=decision.side,
            ),
            best_price=price,
            worst_price=price,
            entry_predictability_score=decision.predictability_score,
            entry_liquidity_score=decision.liquidity_score,
            entry_net_expected_edge_bps=decision.net_expected_edge_bps,
            entry_estimated_round_trip_cost_bps=decision.estimated_round_trip_cost_bps,
            entry_planned_leverage=max(int(leverage), 1),
            latest_predictability_score=decision.predictability_score,
            latest_liquidity_score=decision.liquidity_score,
            latest_net_expected_edge_bps=decision.net_expected_edge_bps,
            latest_estimated_round_trip_cost_bps=decision.estimated_round_trip_cost_bps,
            latest_decision_time=decision.timestamp,
            confirmation_pending=(decision.divergence_code == "ENTRY_CONFIRMATION_REQUIRED"),
            confirmation_pending_since=decision.timestamp if decision.divergence_code == "ENTRY_CONFIRMATION_REQUIRED" else None,
        )
        return True

    def _release_portfolio_capacity(self, *, exit_notional_usd: float) -> None:
        cap = self.max_portfolio_capacity_usd
        if cap is None:
            return
        self.remaining_portfolio_capacity_usd = min(
            cap,
            self.remaining_portfolio_capacity_usd + max(0.0, exit_notional_usd),
        )

    def _close_position(self, *, position: PaperPosition, exit_price: float, timestamp: datetime, exit_reason: str) -> None:
        self._record_closed_trade(
            position=position,
            exit_price=exit_price,
            quantity_closed=position.quantity_remaining,
            exit_time=timestamp,
            exit_reason=exit_reason,
        )
        if (
            position.market == "futures"
            and self._is_major_futures_symbol(position.symbol)
            and exit_reason in {"SIGNAL_REVERSAL", "SCORE_DROP_EXIT", "ENTRY_CONFIRMATION_FAILED"}
            and self.runtime.paper_service.settings.live_position_risk.major_reentry_cooldown_minutes > 0
        ):
            cooldown_until = timestamp + timedelta(
                minutes=self.runtime.paper_service.settings.live_position_risk.major_reentry_cooldown_minutes
            )
            current = self.manual_symbol_cooldowns.get(position.symbol)
            if current is None or cooldown_until > current:
                self.manual_symbol_cooldowns[position.symbol] = cooldown_until
        if (
            position.market == "futures"
            and self._is_major_futures_symbol(position.symbol)
            and self.runtime.paper_service.settings.live_position_risk.major_loss_reentry_cooldown_minutes > 0
            and self.runtime.paper_service.settings.live_position_risk.major_loss_reentry_trigger_usd > 0.0
            and self.closed_trades
            and float(self.closed_trades[-1].get("realized_pnl_usd_estimate", 0.0)) <= -self.runtime.paper_service.settings.live_position_risk.major_loss_reentry_trigger_usd
        ):
            cooldown_until = timestamp + timedelta(
                minutes=self.runtime.paper_service.settings.live_position_risk.major_loss_reentry_cooldown_minutes
            )
            current = self.manual_symbol_cooldowns.get(position.symbol)
            if current is None or cooldown_until > current:
                self.manual_symbol_cooldowns[position.symbol] = cooldown_until
        self.paper_positions.pop(position.symbol, None)

    def _update_paper_position(
        self,
        *,
        position: PaperPosition,
        decision: DecisionIntent,
        price: float,
        timestamp: datetime,
    ) -> None:
        position.current_price = price
        position.best_price = max(position.best_price, price)
        position.worst_price = min(position.worst_price, price)
        position.latest_predictability_score = decision.predictability_score
        position.latest_liquidity_score = decision.liquidity_score
        position.latest_net_expected_edge_bps = decision.net_expected_edge_bps
        position.latest_estimated_round_trip_cost_bps = decision.estimated_round_trip_cost_bps
        position.latest_decision_time = timestamp
        reward_bps = self._reward_bps(position=position, price=price)
        current_roe_percent = self._paper_position_roe_percent(position=position, reward_bps=reward_bps)
        position.peak_roe_percent = max(position.peak_roe_percent, current_roe_percent)
        if position.exchange_synced:
            position.exit_confirmation_count = 0
            position.last_exit_signal_reason = ""
            return
        if position.confirmation_pending:
            confirmed = (
                decision.final_mode == position.market
                and decision.side == position.side
                and decision.net_expected_edge_bps > 0.0
                and decision.liquidity_score >= max(position.entry_liquidity_score - 0.05, 0.45)
            )
            if not confirmed:
                self._close_position(
                    position=position,
                    exit_price=price,
                    timestamp=timestamp,
                    exit_reason="ENTRY_CONFIRMATION_FAILED",
                )
                return
            position.confirmation_pending = False
            position.confirmation_pending_since = None
        exit_rules = self.runtime.paper_service.settings.exit_rules
        live_risk = self.runtime.paper_service.settings.live_position_risk
        partial_action_taken = False

        if (
            live_risk.portfolio_full_exit_only
            and live_risk.portfolio_full_exit_profit_ratio > 0.0
            and self._paper_portfolio_profit_ratio() >= live_risk.portfolio_full_exit_profit_ratio
        ):
            self._close_position(
                position=position,
                exit_price=price,
                timestamp=timestamp,
                exit_reason="PORTFOLIO_FULL_EXIT",
            )
            return

        if (
            not live_risk.portfolio_full_exit_only
            and
            not partial_action_taken
            and not position.r_multiple_partial_take_profit_taken
            and position.stop_distance_bps > 0
            and reward_bps >= position.stop_distance_bps * exit_rules.partial_take_profit_r
        ):
            position.r_multiple_partial_take_profit_taken = self._take_partial_paper_profit(
                position=position,
                exit_price=price,
                timestamp=timestamp,
                fraction=0.5,
                exit_reason="PARTIAL_TAKE_PROFIT",
            )
            partial_action_taken = position.r_multiple_partial_take_profit_taken
            if position.symbol not in self.paper_positions:
                return

        if (
            not live_risk.portfolio_full_exit_only
            and
            not partial_action_taken
            and position.market == "futures"
            and not position.r_multiple_partial_take_profit_taken
        ):
            proactive_threshold = self._pending_proactive_take_profit_threshold(
                current_roe_percent=current_roe_percent,
                thresholds_hit=position.proactive_take_profit_thresholds_hit,
            )
            if proactive_threshold is not None and self._take_partial_paper_profit(
                position=position,
                exit_price=price,
                timestamp=timestamp,
                fraction=self._futures_proactive_take_profit_fraction(),
                exit_reason="PROACTIVE_PARTIAL_TAKE_PROFIT",
            ):
                existing_thresholds = set(position.proactive_take_profit_thresholds_hit)
                position.proactive_take_profit_thresholds_hit = tuple(
                    threshold
                    for threshold in self._futures_proactive_take_profit_thresholds()
                    if threshold in existing_thresholds or threshold <= proactive_threshold
                )
                partial_action_taken = True
                if position.symbol not in self.paper_positions:
                    return

        if (
            not live_risk.portfolio_full_exit_only
            and
            not partial_action_taken
            and position.market == "futures"
            and self._profit_protection_partial_triggered(
                peak_roe_percent=position.peak_roe_percent,
                current_roe_percent=current_roe_percent,
                retrace_taken=position.profit_protection_retrace_taken,
            )
        ):
            position.profit_protection_retrace_taken = self._take_partial_paper_profit(
                position=position,
                exit_price=price,
                timestamp=timestamp,
                fraction=0.5,
                exit_reason="PROFIT_PROTECTION_PARTIAL_TAKE_PROFIT",
            )
            partial_action_taken = position.profit_protection_retrace_taken
            if position.symbol not in self.paper_positions:
                return

        if position.partial_take_profit_taken and "trail" in exit_rules.post_tp_stop_mode.strip().lower():
            self._apply_post_take_profit_stop(position=position, current_price=price)

        if self._standard_stop_loss_exits_enabled() and self._position_stop_hit(position=position, price=price):
            exit_reason = "BREAKEVEN_STOP" if position.partial_take_profit_taken else "STOP_LOSS"
            self._close_position(position=position, exit_price=price, timestamp=timestamp, exit_reason=exit_reason)
            return

        holding_minutes = (timestamp - position.entry_time).total_seconds() / 60.0
        max_holding_minutes = (
            exit_rules.futures_max_holding_minutes if position.market == "futures" else exit_rules.spot_max_holding_minutes
        )
        if holding_minutes >= max_holding_minutes:
            self._close_position(position=position, exit_price=price, timestamp=timestamp, exit_reason="MAX_HOLDING_TIME")
            return

        exit_reason = ""
        if decision.final_mode == "cash" or decision.final_mode != position.market or decision.side != position.side:
            exit_reason = "SIGNAL_REVERSAL"
        elif decision.predictability_score <= position.entry_predictability_score - exit_rules.score_drop_exit_buffer:
            exit_reason = "SCORE_DROP_EXIT"
        elif decision.liquidity_score <= position.entry_liquidity_score - exit_rules.liquidity_drop_exit_buffer:
            exit_reason = "LIQUIDITY_DROP_EXIT"

        if exit_reason:
            required_confirmation_cycles = max(1, exit_rules.confirmation_cycles_for_exit)
            if (
                position.market == "futures"
                and self._is_major_futures_symbol(position.symbol)
                and exit_reason in {"SIGNAL_REVERSAL", "SCORE_DROP_EXIT"}
            ):
                if holding_minutes < self.runtime.paper_service.settings.live_position_risk.major_reversal_min_holding_minutes:
                    return
                required_confirmation_cycles = max(
                    required_confirmation_cycles,
                    self.runtime.paper_service.settings.live_position_risk.major_reversal_confirmation_cycles,
                )
            if position.last_exit_signal_reason == exit_reason:
                position.exit_confirmation_count += 1
            else:
                position.last_exit_signal_reason = exit_reason
                position.exit_confirmation_count = 1
            if position.exit_confirmation_count >= required_confirmation_cycles:
                self._close_position(position=position, exit_price=price, timestamp=timestamp, exit_reason=exit_reason)
            return

        position.exit_confirmation_count = 0
        position.last_exit_signal_reason = ""

    def _apply_paper_trade_management(
        self,
        *,
        decision: DecisionIntent,
        state: Any,
        timestamp: datetime,
    ) -> tuple[bool, bool]:
        position = self.paper_positions.get(decision.symbol)
        fallback_price = 0.0
        if position is not None:
            fallback_price = position.current_price if position.current_price > 0 else position.entry_price
        price = self._market_price(state=state, fallback=fallback_price)
        if position is None:
            return self._open_paper_position(decision=decision, price=price), False
        self._update_paper_position(position=position, decision=decision, price=price, timestamp=timestamp)
        pyramid_requested = self._should_pyramid_futures_position(
            position=position,
            decision=decision,
            price=price,
        )
        return pyramid_requested, pyramid_requested

    def _futures_slot_limit(self) -> int:
        settings = self.runtime.paper_service.settings
        limits = [max(int(settings.operational_limits.max_concurrent_futures_symbols), 0)]
        if settings.portfolio_focus.enabled:
            limits.append(max(int(settings.portfolio_focus.futures_top_n), 0))
        positive_limits = [limit for limit in limits if limit > 0]
        if not positive_limits:
            return 0
        return min(positive_limits)

    def _is_strong_reallocation_candidate(self, decision: DecisionIntent) -> bool:
        settings = self.runtime.paper_service.settings
        focus = settings.portfolio_focus
        exposure = settings.futures_exposure
        if not focus.enabled or decision.final_mode != "futures" or decision.side not in {"long", "short"}:
            return False
        score_floor = settings.mode_thresholds.futures_score_min + max(focus.min_score_advantage_to_replace, 0.0)
        edge_floor = max(
            settings.futures_exposure.min_entry_net_edge_bps,
            focus.min_net_edge_advantage_bps + (decision.estimated_round_trip_cost_bps * 2.0),
        )
        if self._is_major_futures_symbol(decision.symbol):
            score_floor = max(score_floor - exposure.major_reallocation_score_advantage_relaxation, settings.mode_thresholds.futures_score_min)
            edge_floor = max(edge_floor - exposure.major_reallocation_edge_advantage_relaxation_bps, exposure.min_entry_net_edge_bps)
        if decision.predictability_score < score_floor:
            return False
        if decision.net_expected_edge_bps < edge_floor:
            return False
        if decision.estimated_round_trip_cost_bps > 0:
            edge_to_cost = decision.net_expected_edge_bps / decision.estimated_round_trip_cost_bps
            if edge_to_cost < max(settings.cost_gate.edge_to_cost_multiple_min + 0.25, 1.75):
                return False
        return True

    def _blocked_futures_reallocation_reason(
        self,
        decision: DecisionIntent,
        *,
        reference_price: float,
    ) -> tuple[str | None, DecisionIntent]:
        if decision.final_mode != "futures" or decision.side not in {"long", "short"}:
            return None, decision
        if decision.symbol in self.paper_positions:
            return None, decision
        futures_positions = [
            position
            for position in self.paper_positions.values()
            if position.market == "futures" and position.quantity_remaining > 0 and position.symbol != decision.symbol
        ]
        slot_limit = self._futures_slot_limit()
        if slot_limit > 0 and len(futures_positions) >= slot_limit:
            return "MAX_CONCURRENT_FUTURES", decision
        if decision.order_intent_notional_usd <= 0:
            return "PORTFOLIO_CAPACITY", decision
        if not self.capital_report or not self._market_capital_allowed(decision):
            return None, decision
        capped = self._cap_live_order_decision(decision, reference_price=reference_price)
        if capped.final_mode != "futures" or capped.order_intent_notional_usd <= 0:
            if "INSUFFICIENT_EXECUTION_BALANCE" in capped.rejection_reasons:
                return "INSUFFICIENT_EXECUTION_BALANCE", capped
            if "MIN_ORDER_QUANTITY" in capped.rejection_reasons:
                return "MIN_ORDER_QUANTITY", capped
        return None, capped

    def _recomputed_futures_notional(
        self,
        decision: DecisionIntent,
        *,
        additional_capacity_usd: float,
    ) -> float:
        if decision.stop_distance_bps <= 0:
            return 0.0
        settings = self.runtime.paper_service.settings
        leverage = select_futures_leverage(
            predictability_score=decision.predictability_score,
            trend_strength=decision.trend_strength,
            volume_confirmation=decision.volume_confirmation,
            liquidity_score=decision.liquidity_score,
            volatility_penalty=decision.volatility_penalty,
            overheat_penalty=decision.overheat_penalty,
            net_expected_edge_bps=decision.net_expected_edge_bps,
            estimated_round_trip_cost_bps=decision.estimated_round_trip_cost_bps,
            settings=settings,
        )
        risk_dollars = self.equity_usd * settings.risk.per_trade_equity_risk
        raw_notional = risk_dollars / (decision.stop_distance_bps / 10000.0)
        restored_capacity = max(self.remaining_portfolio_capacity_usd + additional_capacity_usd, 0.0)
        capped = min(
            raw_notional,
            self.equity_usd * settings.risk.max_symbol_notional_fraction * max(float(leverage), 1.0),
            restored_capacity,
        )
        return round(max(capped, 0.0), 6)

    def _futures_reallocation_target_state(
        self,
        position: PaperPosition,
    ) -> tuple[float, float, float, datetime]:
        current_score = min(
            position.entry_predictability_score,
            position.latest_predictability_score or position.entry_predictability_score,
        )
        current_edge = min(
            position.entry_net_expected_edge_bps,
            position.latest_net_expected_edge_bps or position.entry_net_expected_edge_bps,
        )
        pnl = position.unrealized_pnl_usd_estimate()
        return current_score, current_edge, pnl, position.entry_time

    def _exchange_synced_reallocation_loss_floor_usd(
        self,
        *,
        position: PaperPosition,
        incoming_decision: DecisionIntent,
    ) -> float:
        focus = self.runtime.paper_service.settings.portfolio_focus
        max_cost_bps = max(
            incoming_decision.estimated_round_trip_cost_bps,
            position.entry_estimated_round_trip_cost_bps,
            position.latest_estimated_round_trip_cost_bps or position.entry_estimated_round_trip_cost_bps,
        )
        cost_floor = position.current_notional_usd_estimate() * max(max_cost_bps, 0.0) * 4.0 / 10000.0
        return round(max(focus.min_incremental_pnl_usd * 4.0, cost_floor), 6)

    def _futures_reallocation_target_assessments(
        self,
        *,
        incoming_decision: DecisionIntent,
        timestamp: datetime,
    ) -> list[dict[str, Any]]:
        settings = self.runtime.paper_service.settings
        focus = settings.portfolio_focus
        incoming_major = self._is_major_futures_symbol(incoming_decision.symbol)
        weakest: list[dict[str, Any]] = []
        for position in self.paper_positions.values():
            if position.market != "futures" or position.quantity_remaining <= 0 or position.symbol == incoming_decision.symbol:
                continue
            current_score, current_edge, pnl, _ = self._futures_reallocation_target_state(position)
            score_erosion = position.entry_predictability_score - current_score
            edge_erosion = position.entry_net_expected_edge_bps - current_edge
            weakness_flags: list[str] = []
            if score_erosion >= settings.exit_rules.score_drop_exit_buffer:
                weakness_flags.append("score_drop")
            if edge_erosion >= max(focus.min_net_edge_advantage_bps, 0.0):
                weakness_flags.append("edge_drop")
            if pnl <= -max(focus.min_incremental_pnl_usd, 0.0):
                weakness_flags.append("negative_pnl")
            if incoming_major and not self._is_major_futures_symbol(position.symbol):
                if pnl <= 0.0 or current_edge < incoming_decision.net_expected_edge_bps:
                    weakness_flags.append("major_preemptible")
            weakness_detected = bool(weakness_flags)
            protected_reason: str | None = None
            exchange_synced_exception = False
            exchange_synced_age_minutes: float | None = None
            exchange_synced_loss_floor_usd: float | None = None
            if position.exchange_synced:
                exchange_synced_age_minutes = round(
                    max((timestamp - position.entry_time).total_seconds(), 0.0) / 60.0,
                    6,
                )
                exchange_synced_loss_floor_usd = self._exchange_synced_reallocation_loss_floor_usd(
                    position=position,
                    incoming_decision=incoming_decision,
                )
                if exchange_synced_age_minutes < (self._futures_reallocation_cooldown_window().total_seconds() / 60.0):
                    protected_reason = "EXCHANGE_SYNCED_RECENCY_GUARD"
                elif pnl > -exchange_synced_loss_floor_usd:
                    protected_reason = "EXCHANGE_SYNCED_LOSS_GUARD"
                else:
                    exchange_synced_exception = True
            elif not weakness_detected:
                protected_reason = "TARGET_NOT_WEAK_ENOUGH"
            eligible = weakness_detected and protected_reason is None
            weakest.append(
                {
                    "position": position,
                    "sort_key": self._futures_reallocation_target_state(position),
                    "symbol": position.symbol,
                    "score": round(current_score, 6),
                    "edge_bps": round(current_edge, 6),
                    "pnl_usd": round(pnl, 6),
                    "score_erosion": round(score_erosion, 6),
                    "edge_erosion_bps": round(edge_erosion, 6),
                    "weakness_flags": weakness_flags,
                    "eligible": eligible,
                    "exchange_synced": position.exchange_synced,
                    "protected_reason": protected_reason,
                    "exchange_synced_exception": exchange_synced_exception,
                    "exchange_synced_age_minutes": exchange_synced_age_minutes,
                    "exchange_synced_loss_floor_usd": exchange_synced_loss_floor_usd,
                }
            )
        weakest.sort(
            key=lambda item: (
                0 if incoming_major and not self._is_major_futures_symbol(item["symbol"]) else 1,
                item["sort_key"],
            )
        )
        return weakest

    def _weak_futures_reallocation_targets(
        self,
        *,
        incoming_decision: DecisionIntent,
        timestamp: datetime,
    ) -> list[PaperPosition]:
        assessments = self._futures_reallocation_target_assessments(
            incoming_decision=incoming_decision,
            timestamp=timestamp,
        )
        return [item["position"] for item in assessments if item["eligible"]]

    def _compact_futures_reallocation_targets(
        self,
        assessments: list[dict[str, Any]],
        *,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in assessments[:limit]:
            row: dict[str, Any] = {
                "symbol": item["symbol"],
                "score": item["score"],
                "edge_bps": item["edge_bps"],
                "pnl_usd": item["pnl_usd"],
                "weakness_flags": list(item["weakness_flags"]),
                "eligible": item["eligible"],
                "exchange_synced": item["exchange_synced"],
                "protected_reason": item["protected_reason"],
                "exchange_synced_exception": item["exchange_synced_exception"],
            }
            if item["exchange_synced"]:
                row["exchange_synced_age_minutes"] = item["exchange_synced_age_minutes"]
                row["exchange_synced_loss_floor_usd"] = item["exchange_synced_loss_floor_usd"]
            rows.append(row)
        return rows

    def _log_futures_reallocation_event(
        self,
        *,
        timestamp: datetime,
        decision: DecisionIntent,
        blocked_reason: str,
        status: str,
        skip_reason: str | None = None,
        cooldown_until: datetime | None = None,
        target_assessments: list[dict[str, Any]] | None = None,
        selected_targets: list[PaperPosition] | None = None,
        override_reason: str | None = None,
        score_advantage: float | None = None,
        edge_advantage_after_costs_bps: float | None = None,
        aggregate_switching_cost_bps: float | None = None,
        incremental_pnl_usd_estimate: float | None = None,
    ) -> None:
        if self.log_store is None:
            return
        payload: dict[str, Any] = {
            "timestamp": timestamp,
            "status": status,
            "blocked_reason": blocked_reason,
            "incoming_symbol": decision.symbol,
            "candidate_strength": {
                "score": round(decision.predictability_score, 6),
                "net_edge_bps": round(decision.net_expected_edge_bps, 6),
                "estimated_round_trip_cost_bps": round(decision.estimated_round_trip_cost_bps, 6),
                "requested_notional_usd": round(decision.order_intent_notional_usd, 6),
            },
            "cooldown_until": cooldown_until,
            "max_replacements": self._max_futures_reallocation_replacements(),
        }
        if skip_reason is not None:
            payload["skip_reason"] = skip_reason
        if override_reason is not None:
            payload["override_reason"] = override_reason
        if target_assessments is not None:
            payload["targets"] = self._compact_futures_reallocation_targets(target_assessments)
            payload["protected_symbols"] = [
                item["symbol"]
                for item in target_assessments
                if item["protected_reason"] is not None
            ]
        if selected_targets:
            payload["replaced_symbol"] = selected_targets[0].symbol
            payload["replaced_symbols"] = [target.symbol for target in selected_targets]
            payload["replaced_count"] = len(selected_targets)
        if score_advantage is not None:
            payload["score_advantage"] = round(score_advantage, 6)
        if edge_advantage_after_costs_bps is not None:
            payload["edge_advantage_after_costs_bps"] = round(edge_advantage_after_costs_bps, 6)
        if aggregate_switching_cost_bps is not None:
            payload["aggregate_switching_cost_bps"] = round(aggregate_switching_cost_bps, 6)
        if incremental_pnl_usd_estimate is not None:
            payload["incremental_pnl_usd_estimate"] = round(incremental_pnl_usd_estimate, 6)
        self.log_store.append("futures_reallocation", payload)

    def _max_futures_reallocation_replacements(self) -> int:
        return 2

    def _fallback_blocked_futures_decision(
        self,
        *,
        decision: DecisionIntent,
        blocked_reason: str,
        blocked_decision: DecisionIntent,
    ) -> DecisionIntent:
        if blocked_reason == "MAX_CONCURRENT_FUTURES":
            return replace(
                decision,
                final_mode="cash",
                side="flat",
                order_intent_notional_usd=0.0,
                stop_distance_bps=0.0,
                rejection_reasons=tuple(sorted(set(decision.rejection_reasons + ("MAX_CONCURRENT_FUTURES",)))),
            )
        if blocked_reason in {"INSUFFICIENT_EXECUTION_BALANCE", "MIN_ORDER_QUANTITY"}:
            return blocked_decision
        return decision

    def _maybe_reallocate_futures_entry(
        self,
        *,
        decision: DecisionIntent,
        state: Any,
        timestamp: datetime,
    ) -> DecisionIntent:
        price = self._market_price(state=state, fallback=0.0)
        if price <= 0:
            return decision
        blocked_reason, capped_decision = self._blocked_futures_reallocation_reason(
            decision,
            reference_price=price,
        )
        if blocked_reason is None:
            return capped_decision
        target_assessments = self._futures_reallocation_target_assessments(
            incoming_decision=decision,
            timestamp=timestamp,
        )
        fallback = self._fallback_blocked_futures_decision(
            decision=decision,
            blocked_reason=blocked_reason,
            blocked_decision=capped_decision,
        )
        if not self._is_strong_reallocation_candidate(decision):
            self._log_futures_reallocation_event(
                timestamp=timestamp,
                decision=decision,
                blocked_reason=blocked_reason,
                status="skipped",
                skip_reason="CANDIDATE_NOT_STRONG_ENOUGH",
                cooldown_until=self.futures_reallocation_cooldown_until,
                target_assessments=target_assessments,
            )
            return fallback
        if self._is_futures_reallocation_cooldown_active(timestamp):
            self._log_futures_reallocation_event(
                timestamp=timestamp,
                decision=decision,
                blocked_reason=blocked_reason,
                status="skipped",
                skip_reason="REALLOCATION_COOLDOWN_ACTIVE",
                cooldown_until=self.futures_reallocation_cooldown_until,
                target_assessments=target_assessments,
            )
            return fallback
        futures_positions = [
            position
            for position in self.paper_positions.values()
            if position.market == "futures" and position.quantity_remaining > 0 and position.symbol != decision.symbol
        ]
        slot_limit = self._futures_slot_limit()
        selected_targets: list[PaperPosition] = []
        candidate: DecisionIntent | None = None
        released_capacity_usd = 0.0
        released_execution_balance_usd = 0.0
        weak_targets = [item["position"] for item in target_assessments if item["eligible"]]
        if not weak_targets:
            self._log_futures_reallocation_event(
                timestamp=timestamp,
                decision=decision,
                blocked_reason=blocked_reason,
                status="skipped",
                skip_reason="NO_ELIGIBLE_TARGETS",
                cooldown_until=self.futures_reallocation_cooldown_until,
                target_assessments=target_assessments,
            )
            return fallback
        for target in weak_targets[: self._max_futures_reallocation_replacements()]:
            selected_targets.append(target)
            target_notional = target.current_notional_usd_estimate()
            released_capacity_usd += target_notional
            released_execution_balance_usd += target_notional / max(float(target.entry_planned_leverage), 1.0)
            candidate_notional = decision.order_intent_notional_usd
            if candidate_notional <= 0:
                candidate_notional = self._recomputed_futures_notional(
                    decision,
                    additional_capacity_usd=released_capacity_usd,
                )
            if candidate_notional <= 0:
                continue
            candidate_option = replace(decision, order_intent_notional_usd=candidate_notional)
            if self.capital_report and self._market_capital_allowed(candidate_option):
                candidate_option = self._cap_live_order_decision(
                    candidate_option,
                    reference_price=price,
                    extra_futures_execution_balance_usd=released_execution_balance_usd,
                )
                if (
                    any(target.exchange_synced for target in selected_targets)
                    and any(item.get("exchange_synced_exception") for item in target_assessments)
                ):
                    candidate_option = replace(decision, order_intent_notional_usd=candidate_notional)
            slot_unlocked = slot_limit <= 0 or (len(futures_positions) - len(selected_targets)) < slot_limit
            if candidate_option.final_mode == "futures" and candidate_option.order_intent_notional_usd > 0 and slot_unlocked:
                candidate = candidate_option
                break
        if candidate is None:
            self._log_futures_reallocation_event(
                timestamp=timestamp,
                decision=decision,
                blocked_reason=blocked_reason,
                status="skipped",
                skip_reason="REPLACEMENT_CANDIDATE_STILL_BLOCKED_AFTER_RELEASE",
                cooldown_until=self.futures_reallocation_cooldown_until,
                target_assessments=target_assessments,
                selected_targets=selected_targets,
            )
            return fallback
        replaced_scores: list[float] = []
        replaced_edges: list[float] = []
        switching_cost_bps = 0.0
        for target in selected_targets:
            current_score, current_edge, _, _ = self._futures_reallocation_target_state(target)
            replaced_scores.append(current_score)
            replaced_edges.append(current_edge)
            switching_cost_bps += max(
                target.entry_estimated_round_trip_cost_bps,
                target.latest_estimated_round_trip_cost_bps or target.entry_estimated_round_trip_cost_bps,
                candidate.estimated_round_trip_cost_bps,
            ) * 2.0
        score_advantage = candidate.predictability_score - max(replaced_scores)
        edge_advantage_after_costs = candidate.net_expected_edge_bps - max(replaced_edges) - switching_cost_bps
        incremental_pnl_usd = edge_advantage_after_costs * candidate.order_intent_notional_usd / 10000.0
        focus = self.runtime.paper_service.settings.portfolio_focus
        exposure = self.runtime.paper_service.settings.futures_exposure
        major_reallocation = self._is_major_futures_symbol(decision.symbol) and any(
            not self._is_major_futures_symbol(target.symbol) for target in selected_targets
        )
        required_score_advantage = max(
            focus.min_score_advantage_to_replace - (exposure.major_reallocation_score_advantage_relaxation if major_reallocation else 0.0),
            0.0,
        )
        required_edge_advantage = max(
            focus.min_net_edge_advantage_bps - (exposure.major_reallocation_edge_advantage_relaxation_bps if major_reallocation else 0.0),
            0.0,
        )
        required_incremental_pnl = max(
            focus.min_incremental_pnl_usd - (exposure.major_reallocation_incremental_pnl_relaxation_usd if major_reallocation else 0.0),
            0.0,
        )
        if score_advantage < required_score_advantage:
            self._log_futures_reallocation_event(
                timestamp=timestamp,
                decision=decision,
                blocked_reason=blocked_reason,
                status="skipped",
                skip_reason="SCORE_ADVANTAGE_BELOW_FLOOR",
                cooldown_until=self.futures_reallocation_cooldown_until,
                target_assessments=target_assessments,
                selected_targets=selected_targets,
                score_advantage=score_advantage,
                edge_advantage_after_costs_bps=edge_advantage_after_costs,
                aggregate_switching_cost_bps=switching_cost_bps,
                incremental_pnl_usd_estimate=incremental_pnl_usd,
            )
            return fallback
        if edge_advantage_after_costs < required_edge_advantage:
            self._log_futures_reallocation_event(
                timestamp=timestamp,
                decision=decision,
                blocked_reason=blocked_reason,
                status="skipped",
                skip_reason="EDGE_ADVANTAGE_BELOW_FLOOR",
                cooldown_until=self.futures_reallocation_cooldown_until,
                target_assessments=target_assessments,
                selected_targets=selected_targets,
                score_advantage=score_advantage,
                edge_advantage_after_costs_bps=edge_advantage_after_costs,
                aggregate_switching_cost_bps=switching_cost_bps,
                incremental_pnl_usd_estimate=incremental_pnl_usd,
            )
            return fallback
        if incremental_pnl_usd < required_incremental_pnl:
            if any(item.get("exchange_synced_exception") for item in target_assessments):
                override_reason = "STRICT_EXCHANGE_SYNCED_EXCEPTION"
            else:
                self._log_futures_reallocation_event(
                    timestamp=timestamp,
                    decision=decision,
                    blocked_reason=blocked_reason,
                    status="skipped",
                    skip_reason="INCREMENTAL_PNL_BELOW_FLOOR",
                    cooldown_until=self.futures_reallocation_cooldown_until,
                    target_assessments=target_assessments,
                    selected_targets=selected_targets,
                    score_advantage=score_advantage,
                    edge_advantage_after_costs_bps=edge_advantage_after_costs,
                    aggregate_switching_cost_bps=switching_cost_bps,
                    incremental_pnl_usd_estimate=incremental_pnl_usd,
                )
                return fallback
        if self.live_order_executor is not None:
            live_targets = [self._find_live_futures_position(target.symbol) for target in selected_targets]
            if any(target is None for target in live_targets):
                self._log_futures_reallocation_event(
                    timestamp=timestamp,
                    decision=decision,
                    blocked_reason=blocked_reason,
                    status="skipped",
                    skip_reason="LIVE_EXCHANGE_TARGET_NOT_FOUND",
                    cooldown_until=self.futures_reallocation_cooldown_until,
                    target_assessments=target_assessments,
                    selected_targets=selected_targets,
                    score_advantage=score_advantage,
                    edge_advantage_after_costs_bps=edge_advantage_after_costs,
                    aggregate_switching_cost_bps=switching_cost_bps,
                    incremental_pnl_usd_estimate=incremental_pnl_usd,
                )
                return fallback
            for live_target in live_targets:
                assert live_target is not None
                self._close_live_position(position=live_target, reason="CAPITAL_REALLOCATION")
        for target in selected_targets:
            self._cancel_symbol_open_orders(symbol=target.symbol)
            self._close_position(
                position=target,
                exit_price=target.current_price,
                timestamp=timestamp,
                exit_reason="CAPITAL_REALLOCATION",
            )
        self.futures_reallocation_cooldown_until = self._futures_reallocation_cooldown_for_timestamp(timestamp)
        override_reason = None
        if any(target.exchange_synced for target in selected_targets):
            override_reason = "STRICT_EXCHANGE_SYNCED_EXCEPTION"
        self._log_futures_reallocation_event(
            timestamp=timestamp,
            decision=candidate,
            blocked_reason=blocked_reason,
            status="executed",
            cooldown_until=self.futures_reallocation_cooldown_until,
            target_assessments=target_assessments,
            selected_targets=selected_targets,
            override_reason=override_reason,
            score_advantage=score_advantage,
            edge_advantage_after_costs_bps=edge_advantage_after_costs,
            aggregate_switching_cost_bps=switching_cost_bps,
            incremental_pnl_usd_estimate=incremental_pnl_usd,
        )
        return candidate

    def _record_decision(
        self,
        *,
        decision: DecisionIntent,
        state: Any,
        timestamp: datetime,
        bootstrap: bool = False,
    ) -> None:
        if (
            self.minimum_live_decision_timestamp is not None
            and decision.timestamp < self.minimum_live_decision_timestamp
        ):
            return
        last_recorded = self.last_recorded_decision_time_by_symbol.get(decision.symbol)
        if last_recorded == decision.timestamp:
            return
        managed_decision = self._apply_loss_combo_downgrade(decision=decision)
        emitted_at = datetime.now(tz=timezone.utc)
        self.decisions.append(managed_decision)
        self.last_recorded_decision_time_by_symbol[managed_decision.symbol] = managed_decision.timestamp
        self.last_decision_timestamp = managed_decision.timestamp
        self.last_decision_emitted_at = emitted_at
        self.self_healing.note_decision(
            timestamp=max(emitted_at, managed_decision.timestamp),
            decision_count=len(self.decisions),
            heartbeat_count=self.heartbeat_count,
        )
        if self.verbose:
            print(
                f"[DECISION] {managed_decision.timestamp.isoformat()} {managed_decision.symbol} mode={managed_decision.final_mode} side={managed_decision.side} score={managed_decision.predictability_score:.2f}",
                flush=True,
            )
        if self.learner is not None:
            self.learner.ingest_decisions((managed_decision,))
        if self.log_store is not None:
            self.log_store.append("decisions", managed_decision.as_dict())
        if bootstrap:
            return
        if state is not None:
            managed_decision = self._maybe_reallocate_futures_entry(
                decision=managed_decision,
                state=state,
                timestamp=timestamp,
            )
        order_cooldown_active = self._is_order_cooldown_active(managed_decision.symbol, timestamp)
        manual_symbol_cooldown_active = self._is_manual_symbol_cooldown_active(managed_decision.symbol, timestamp)
        live_orders_allowed = not self.self_healing.is_live_order_cooldown_active(now=timestamp)
        existing_paper_position = self.paper_positions.get(managed_decision.symbol)
        allow_new_submission = False
        pyramid_requested = False
        can_open_new_paper_position = True
        if (
            existing_paper_position is None
            and (
                order_cooldown_active
                or manual_symbol_cooldown_active
                or (self.live_order_executor is not None and not live_orders_allowed)
            )
        ):
            can_open_new_paper_position = False
        if state is not None and can_open_new_paper_position:
            if existing_paper_position is None:
                allow_new_submission = (
                    managed_decision.final_mode in {"spot", "futures"}
                    and managed_decision.side in {"long", "short"}
                    and managed_decision.order_intent_notional_usd > 0.0
                )
            else:
                allow_new_submission, pyramid_requested = self._apply_paper_trade_management(
                    decision=managed_decision,
                    state=state,
                    timestamp=timestamp,
                )
        if order_cooldown_active:
            allow_new_submission = False
        if manual_symbol_cooldown_active:
            allow_new_submission = False
        if (
            self.live_order_executor is not None
            and state is not None
            and allow_new_submission
            and live_orders_allowed
            and self._market_capital_allowed(managed_decision)
        ):
            executable_decision = self._cap_live_order_decision(managed_decision, reference_price=state.last_trade_price)
            fingerprint = self._execution_fingerprint(executable_decision)
            last_fingerprint = self.last_executed_fingerprint_by_symbol.get(executable_decision.symbol)
            if executable_decision.final_mode not in {"spot", "futures"} or executable_decision.order_intent_notional_usd <= 0:
                self._clear_live_entry_starvation(symbol=executable_decision.symbol)
            if last_fingerprint != fingerprint and executable_decision.final_mode in {"spot", "futures"} and executable_decision.order_intent_notional_usd > 0:
                try:
                    live_result = self.live_order_executor.execute_decision(
                        decision=executable_decision,
                        reference_price=state.last_trade_price,
                    )
                except Exception as exc:
                    payload = {
                        "timestamp": timestamp,
                        "symbol": executable_decision.symbol,
                        "market": executable_decision.final_mode,
                        "stage": "live_order",
                        "error": repr(exc),
                    }
                    if self.verbose:
                        print(f"[LIVE_ORDER_ERROR] {executable_decision.symbol} {exc}", flush=True)
                    self._apply_order_error_cooldown(
                        symbol=executable_decision.symbol,
                        error_message=repr(exc),
                        timestamp=timestamp,
                        stage="live_order",
                        exchange_id=self.live_order_executor._exchange_id(),
                    )
                    if (
                        self.live_order_executor._exchange_id() == "bitget"
                        and self._parse_order_error_code(repr(exc)) == "40762"
                    ):
                        self._refresh_account_state_after_live_order_activity(
                            symbol=executable_decision.symbol,
                            timestamp=timestamp,
                            stage="live_order",
                            reason="balance_error",
                        )
                    if self.log_store is not None:
                        self.log_store.append("order_errors", payload)
                else:
                    if live_result is not None:
                        self.last_executed_fingerprint_by_symbol[executable_decision.symbol] = fingerprint
                        payload = {
                            "timestamp": timestamp,
                            "symbol": live_result.symbol,
                            "market": live_result.market,
                            "side": live_result.side,
                            "quantity": live_result.quantity,
                            "accepted": live_result.accepted,
                            "order_id": str(live_result.response.get("orderId", "")),
                            "client_oid": str(live_result.response.get("clientOid", executable_decision.decision_id)),
                            "reference_price": state.last_trade_price,
                            "estimated_round_trip_cost_bps": executable_decision.estimated_round_trip_cost_bps,
                            "protection_orders": list(live_result.protection_orders),
                            "protection_error": live_result.protection_error,
                            "response": live_result.response,
                        }
                        self.live_orders.append(payload)
                        if self.verbose:
                            print(
                                f"[LIVE_ORDER] {live_result.symbol} market={live_result.market} side={live_result.side} qty={live_result.quantity} accepted={live_result.accepted}",
                                flush=True,
                            )
                        if self.log_store is not None:
                            self.log_store.append("live_orders", payload)
                        if live_result.protection_error and self.log_store is not None:
                            self.log_store.append(
                                "order_errors",
                                {
                                    "timestamp": timestamp,
                                    "symbol": live_result.symbol,
                                    "market": live_result.market,
                                    "stage": "protection_order",
                                    "error": live_result.protection_error,
                                },
                            )
                            self._apply_order_error_cooldown(
                                symbol=live_result.symbol,
                                error_message=live_result.protection_error,
                                timestamp=timestamp,
                                stage="protection_order",
                                exchange_id=self.live_order_executor._exchange_id(),
                            )
                        if live_result.accepted:
                            self._clear_live_entry_starvation(symbol=live_result.symbol)
                            self._send_live_entry_alert(payload)
                            if existing_paper_position is None and not pyramid_requested:
                                self._open_paper_position(
                                    decision=executable_decision,
                                    price=state.last_trade_price,
                                )
                            if pyramid_requested:
                                paper_position = self.paper_positions.get(executable_decision.symbol)
                                if paper_position is not None:
                                    self._apply_pyramid_fill_to_position(
                                        position=paper_position,
                                        decision=executable_decision,
                                        price=state.last_trade_price,
                                    )
                            self._refresh_account_state_after_live_order_activity(
                                symbol=live_result.symbol,
                                timestamp=timestamp,
                                stage="live_order",
                                reason="accepted_live_order",
                            )
                    else:
                        preflight_rejection = self.live_order_executor.pop_last_preflight_rejection()
                        if preflight_rejection is not None:
                            symbol = str(preflight_rejection.get("symbol", executable_decision.symbol))
                            message = str(
                                preflight_rejection.get(
                                    "message",
                                    preflight_rejection.get("reason", "preflight_rejected"),
                                )
                            )
                            self._apply_preflight_symbol_cooldown(symbol=symbol, timestamp=timestamp)
                            self.self_healing.record_runtime_error(
                                now=timestamp,
                                symbol=symbol,
                                error_message=message,
                                exchange_id=self.live_order_executor._exchange_id(),
                                stage="live_order_preflight",
                            )
                            if self.log_store is not None:
                                self.log_store.append(
                                    "order_errors",
                                    {
                                        "timestamp": timestamp,
                                        "symbol": symbol,
                                        "market": str(preflight_rejection.get("market", executable_decision.final_mode)),
                                        "stage": "live_order_preflight",
                                        "error": message,
                                        "reason": str(preflight_rejection.get("reason", "")),
                                    },
                                )
                        elif existing_paper_position is None and self._find_live_futures_position(executable_decision.symbol) is None:
                            self._note_live_entry_starvation(
                                symbol=executable_decision.symbol,
                                timestamp=timestamp,
                                reason="LIVE_ORDER_NO_RESULT",
                                fingerprint=fingerprint,
                            )
            elif (
                existing_paper_position is None
                and executable_decision.final_mode in {"spot", "futures"}
                and executable_decision.order_intent_notional_usd > 0
                and self._find_live_futures_position(executable_decision.symbol) is None
            ):
                self._note_live_entry_starvation(
                    symbol=executable_decision.symbol,
                    timestamp=timestamp,
                    reason="STALE_FINGERPRINT_SUPPRESSION",
                    fingerprint=fingerprint,
                )
        if self.order_tester is not None and state is not None and allow_new_submission and self._market_capital_allowed(managed_decision):
            test_decision = self._cap_live_order_decision(managed_decision, reference_price=state.last_trade_price)
            if test_decision.final_mode in {"spot", "futures"} and test_decision.order_intent_notional_usd > 0:
                try:
                    test_result = self.order_tester.test_decision(
                        decision=test_decision,
                        reference_price=state.last_trade_price,
                    )
                except Exception as exc:
                    payload = {
                        "timestamp": timestamp,
                        "symbol": test_decision.symbol,
                        "market": test_decision.final_mode,
                        "stage": "test_order",
                        "error": repr(exc),
                    }
                    if self.verbose:
                        print(f"[TEST_ORDER_ERROR] {test_decision.symbol} {exc}", flush=True)
                    self._apply_order_error_cooldown(
                        symbol=test_decision.symbol,
                        error_message=repr(exc),
                        timestamp=timestamp,
                        stage="test_order",
                        exchange_id=getattr(self.order_tester.client, "exchange_id", "binance"),
                    )
                    if self.log_store is not None:
                        self.log_store.append("order_errors", payload)
                else:
                    if test_result is not None:
                        if (
                            self.live_order_executor is None
                            and existing_paper_position is None
                            and test_result.accepted
                            and not pyramid_requested
                        ):
                            self._open_paper_position(
                                decision=test_decision,
                                price=state.last_trade_price,
                            )
                        if pyramid_requested:
                            paper_position = self.paper_positions.get(test_result.symbol)
                            if paper_position is not None:
                                self._apply_pyramid_fill_to_position(
                                    position=paper_position,
                                    decision=test_decision,
                                    price=state.last_trade_price,
                                )
                        self.tested_orders.append(
                            {
                                "symbol": test_result.symbol,
                                "market": test_result.market,
                                "side": test_result.side,
                                "quantity": test_result.quantity,
                                "accepted": test_result.accepted,
                            }
                        )
                        if self.verbose:
                            print(
                                f"[TEST_ORDER] {test_result.symbol} market={test_result.market} side={test_result.side} qty={test_result.quantity} accepted={test_result.accepted}",
                                flush=True,
                            )
                        if self.log_store is not None:
                            self.log_store.append(
                                "tested_orders",
                                {
                                    "timestamp": timestamp,
                                    "symbol": test_result.symbol,
                                    "market": test_result.market,
                                    "side": test_result.side,
                                    "quantity": test_result.quantity,
                                    "accepted": test_result.accepted,
                                },
                            )

    def _scheduled_decision_boundary_after(self, timestamp: datetime) -> datetime:
        interval = max(int(self.runtime.decision_interval_minutes), 1)
        floored = timestamp.replace(
            minute=(timestamp.minute // interval) * interval,
            second=0,
            microsecond=0,
        )
        if floored <= timestamp:
            floored += timedelta(minutes=interval)
        return floored

    def _scheduled_decision_catchup_cutoff(self, now: datetime) -> datetime:
        interval = max(int(self.runtime.decision_interval_minutes), 1)
        return now - timedelta(minutes=interval)

    def _iter_schedulable_symbols(self) -> list[str]:
        store_symbols = sorted(getattr(self.runtime.dispatcher.store, "_states", {}).keys())
        if self.runtime.eligible_symbols is None:
            return store_symbols
        return [symbol for symbol in store_symbols if symbol in self.runtime.eligible_symbols]

    def _run_scheduled_decision_boundary(self, decision_time: datetime) -> None:
        for symbol in self._iter_schedulable_symbols():
            state = self.runtime.dispatcher.store.get(symbol)
            if state is None:
                continue
            stale_ms = state.freshness_ms(decision_time)
            if stale_ms > self.runtime.paper_service.settings.operational_limits.stale_data_alarm_sla_seconds * 1000:
                continue
            evaluation_state = state
            if stale_ms < 0:
                evaluation_state = replace(
                    state,
                    last_update_time=decision_time,
                    top_of_book=replace(state.top_of_book, updated_at=decision_time),
                )
            primitive_inputs = self.runtime.primitive_builder(symbol, decision_time)
            history = self.runtime.history_provider(symbol, decision_time)
            decision = self.runtime.paper_service.run_cycle(
                state=evaluation_state,
                primitive_inputs=primitive_inputs,
                history=history,
                decision_time=decision_time,
                equity_usd=self.equity_usd,
                remaining_portfolio_capacity_usd=self.remaining_portfolio_capacity_usd,
                cash_reserve_fraction=self._cash_reserve_fraction(),
            )
            self.runtime.loop_stats.note_emitted_decision(symbol=symbol, decision_time=decision_time)
            self._record_decision(decision=decision, state=evaluation_state, timestamp=decision_time)

    def _maybe_run_scheduled_decision_cycle(self, now: datetime) -> None:
        if self.runtime.kill_switch.armed:
            return
        if self.next_scheduled_decision_at is None:
            anchor = self.last_decision_timestamp or now
            if anchor < self._scheduled_decision_catchup_cutoff(now):
                anchor = now
            self.next_scheduled_decision_at = self._scheduled_decision_boundary_after(anchor)
        if self.next_scheduled_decision_at < self._scheduled_decision_catchup_cutoff(now):
            self.next_scheduled_decision_at = self._scheduled_decision_boundary_after(now)
        while self.next_scheduled_decision_at is not None and now >= self.next_scheduled_decision_at:
            boundary = self.next_scheduled_decision_at
            self._run_scheduled_decision_boundary(boundary)
            self.next_scheduled_decision_at = self._scheduled_decision_boundary_after(boundary)


@dataclass(frozen=True)
class BackoffPolicy:
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    multiplier: float = 2.0
    max_attempts: int = 5

    def delay_for_attempt(self, attempt: int) -> float:
        if attempt <= 1:
            return 0.0
        raw = self.initial_delay_seconds * (self.multiplier ** (attempt - 2))
        return min(raw, self.max_delay_seconds)


class AsyncLivePaperRunner:
    def __init__(self, ws_client: Any, session: LivePaperSession) -> None:
        self.ws_client = ws_client
        self.session = session

    async def run(
        self,
        *,
        summary_path: str | Path | None = None,
        state_path: str | Path | None = None,
    ) -> None:
        async def handler(payload: dict[str, Any]) -> None:
            self.session.process_payload(payload)
            if summary_path is not None and state_path is not None:
                self.session.maybe_flush(
                    summary_path=summary_path,
                    state_path=state_path,
                )

        await self.ws_client.run(handler)


class LivePaperShell:
    def __init__(
        self,
        *,
        ws_client_factory: Callable[[], Any],
        session: LivePaperSession,
        backoff_policy: BackoffPolicy | None = None,
        summary_path: str | Path | None = None,
        state_path: str | Path | None = None,
    ) -> None:
        self.ws_client_factory = ws_client_factory
        self.session = session
        self.backoff_policy = backoff_policy or BackoffPolicy()
        self.summary_path = summary_path
        self.state_path = state_path

    async def _run_with_monitor(self, runner: AsyncLivePaperRunner) -> None:
        task = asyncio.create_task(
            runner.run(
                summary_path=self.summary_path,
                state_path=self.state_path,
            )
        )
        self.session.self_healing.begin_monitoring(
            timestamp=datetime.now(tz=timezone.utc),
            heartbeat_count=self.session.heartbeat_count,
            decision_count=len(self.session.decisions),
        )
        poll_seconds = max(1.0, min(5.0, self.session.self_healing.stall_timeout_seconds / 6.0))
        try:
            while not task.done():
                await asyncio.sleep(poll_seconds)
                if task.done():
                    break
                now = datetime.now(tz=timezone.utc)
                self.session._maybe_run_scheduled_decision_cycle(now)
                if not self.session.self_healing.detect_stall(now=now):
                    continue
                allowed = self.session.self_healing.register_stall_recovery(
                    now=now,
                    heartbeat_count=self.session.heartbeat_count,
                )
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                if not allowed:
                    raise RuntimeError("STALL_RECOVERY_LIMIT_EXCEEDED")
                raise RuntimeError("SELF_HEAL_STALL_RESTART")
            await task
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def run(self) -> dict[str, object] | None:
        last_error: Exception | None = None
        for attempt in range(1, self.backoff_policy.max_attempts + 1):
            delay = self.backoff_policy.delay_for_attempt(attempt)
            if delay > 0:
                print(f"[RETRY] attempt={attempt} sleeping={delay:.2f}s", flush=True)
                await asyncio.sleep(delay)
            try:
                print(f"[CONNECT] websocket attempt={attempt}", flush=True)
                runner = AsyncLivePaperRunner(self.ws_client_factory(), self.session)
                await self._run_with_monitor(runner)
                break
            except Exception as exc:  # pragma: no cover - exercised in tests
                last_error = exc
                if self.summary_path is not None and self.state_path is not None:
                    self.session.flush(
                        summary_path=self.summary_path,
                        state_path=self.state_path,
                    )
                print(f"[ERROR] websocket attempt={attempt} error={exc}", flush=True)
                if str(exc) == "STALL_RECOVERY_LIMIT_EXCEEDED":
                    raise
                if attempt >= self.backoff_policy.max_attempts:
                    raise
        if self.summary_path is not None and self.state_path is not None:
            return self.session.flush(
                summary_path=self.summary_path,
                state_path=self.state_path,
            )
        if last_error is not None:
            raise last_error
        return None
