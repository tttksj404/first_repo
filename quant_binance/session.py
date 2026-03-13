from __future__ import annotations

import asyncio
from contextlib import suppress
import re
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
from quant_binance.observability.report import build_runtime_summary, write_runtime_summary
from quant_binance.observability.runtime_state import write_runtime_state
from quant_binance.risk.capital import CapitalAdequacyReport
from quant_binance.risk.sizing import quantity_from_notional, select_futures_leverage
from quant_binance.self_healing import RuntimeSelfHealing, parse_error_code
from quant_binance.telegram_notify import send_telegram_message


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
    flush_interval_seconds: int = 60
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
    order_error_cooldowns: dict[str, datetime] = field(default_factory=dict)
    manual_symbol_cooldowns: dict[str, datetime] = field(default_factory=dict)
    futures_missing_in_paper_counts: dict[str, int] = field(default_factory=dict)
    futures_missing_on_exchange_counts: dict[str, int] = field(default_factory=dict)
    futures_reallocation_cooldown_until: datetime | None = None
    self_healing: RuntimeSelfHealing = field(default_factory=RuntimeSelfHealing)
    heartbeat_count: int = 0
    last_event_timestamp: datetime | None = None
    last_decision_timestamp: datetime | None = None
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
        self._record_decision(decision=decision, state=state, timestamp=decision_time)
        return decision

    def sync_account(self) -> None:
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
        if hasattr(self.rest_client, "build_capital_report"):
            report = self.rest_client.build_capital_report()
            self.capital_report = {
                "spot_available_balance_usd": report.spot_available_balance_usd,
                "spot_recognized_balance_usd": report.spot_recognized_balance_usd,
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
                "spot_requirements": [r.__dict__ for r in report.spot_requirements],
                "futures_requirements": [r.__dict__ for r in report.futures_requirements],
                "pending_symbols": list(report.pending_symbols),
                "note": report.note,
            }
            if not report.can_trade_any:
                self.runtime.kill_switch.arm("INSUFFICIENT_CAPITAL")
        self._evaluate_live_positions()

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

    def _cap_live_order_decision(
        self,
        decision: DecisionIntent,
        *,
        reference_price: float | None = None,
        extra_futures_execution_balance_usd: float = 0.0,
    ) -> DecisionIntent:
        if not self.capital_report:
            return decision
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
            available = float(self.capital_report.get("spot_available_balance_usd", 0.0))
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
            max_notional = max(0.0, available * leverage * (1.0 - reserve_fraction))
        else:
            return decision
        rejection_code = "INSUFFICIENT_EXECUTION_BALANCE"
        if max_notional <= 0.0 or (min_notional > 0.0 and max_notional < min_notional):
            return replace(decision, final_mode="cash", side="flat", order_intent_notional_usd=0.0, stop_distance_bps=0.0, rejection_reasons=tuple(sorted(set(decision.rejection_reasons + (rejection_code,)))))
        if decision.order_intent_notional_usd <= max_notional:
            candidate = decision
        else:
            floored_notional = round(max_notional, 6)
            candidate = replace(decision, order_intent_notional_usd=floored_notional)
        if reference_price is not None and min_quantity > 0.0:
            quantity = quantity_from_notional(candidate.order_intent_notional_usd, reference_price)
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
    ) -> bool:
        exit_rules = self.runtime.paper_service.settings.exit_rules
        if retrace_taken or current_roe_percent <= 0.0:
            return False
        if peak_roe_percent < exit_rules.futures_profit_protection_arm_roe_percent:
            return False
        drawdown = peak_roe_percent - current_roe_percent
        return drawdown >= exit_rules.futures_profit_protection_retrace_roe_percent

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
        }
        self.closed_trades.append(trade)
        self._release_portfolio_capacity(exit_notional_usd=exit_price * quantity_closed)
        if self.log_store is not None:
            self.log_store.append("closed_trades", trade)
        self._send_trade_alert(trade)
        self._enforce_risk_limits(exit_time)

    def _send_telegram_alert(self, *, key: str, text: str) -> None:
        if key in self.sent_alert_keys:
            return
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

    def _parse_order_error_code(self, error_message: str) -> str:
        return parse_error_code(error_message)

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
            persisted_cycles=self._missing_on_exchange_threshold(),
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
            if cycles < self._missing_on_exchange_threshold():
                continue
            self._cleanup_missing_on_exchange_position(symbol=symbol, now=now, reason="MANUAL_CLOSE_SYNCED")
            self.futures_missing_on_exchange_counts.pop(symbol, None)

    def _position_roe_percent(self, position: dict[str, Any]) -> float:
        margin = float(position.get("marginSize") or 0.0)
        if margin <= 0.0:
            return 0.0
        unrealized = float(position.get("unrealizedPL") or 0.0)
        return (unrealized / margin) * 100.0

    def _live_position_identity(self, position: dict[str, Any]) -> str:
        return "|".join(
            [
                str(position.get("symbol", "")),
                str(position.get("holdSide") or position.get("posSide") or ""),
                str(position.get("cTime") or position.get("uTime") or ""),
            ]
        )

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
        payload = {
            "marginCoin": "USDT",
            "productType": "USDT-FUTURES",
            "symbol": symbol,
            "holdSide": "buy" if hold_side == "long" else "sell",
            "stopLossTriggerPrice": f"{breakeven_price:.8f}",
            "stopLossTriggerType": "mark_price",
            "stopLossExecutePrice": "0",
            "stopLossClientOid": f"{symbol}-breakeven",
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

    def _close_live_position(self, *, position: dict[str, Any], reason: str, fraction: float = 1.0) -> None:
        if self.rest_client is None or not hasattr(self.rest_client, "build_order_params") or not hasattr(self.rest_client, "place_order"):
            return
        symbol = str(position.get("symbol", ""))
        hold_side = str(position.get("holdSide", "")).lower()
        total_quantity = float(position.get("total") or position.get("available") or 0.0)
        quantity = total_quantity * max(min(fraction, 1.0), 0.0)
        if not symbol or quantity <= 0.0:
            return
        side = "SELL" if hold_side == "long" else "BUY"
        u_time = str(position.get("uTime", ""))
        alert_key = f"live-position-close:{symbol}:{u_time}:{reason}:{fraction:.4f}"
        if alert_key in self.sent_alert_keys:
            return
        order_params = self.rest_client.build_order_params(
            market="futures",
            symbol=symbol,
            side=side,
            order_type="MARKET",
            quantity=quantity,
            reduce_only=True,
            client_oid=f"{symbol}-{reason.lower()}",
        )
        try:
            response = self.rest_client.place_order(market="futures", order_params=order_params)
        except Exception as exc:
            message = str(exc)
            if "22002" in message or "No position to close" in message:
                if self.log_store is not None:
                    self.log_store.append(
                        "live_position_actions",
                        {
                            "timestamp": datetime.now(tz=timezone.utc),
                            "symbol": symbol,
                            "market": "futures",
                            "side": side.lower(),
                            "quantity": quantity,
                            "accepted": False,
                            "reason": f"{reason}_ALREADY_CLOSED",
                            "response": {"error": repr(exc)},
                        },
                    )
                return
            raise
        payload = {
            "timestamp": datetime.now(tz=timezone.utc),
            "symbol": symbol,
            "market": "futures",
            "side": side.lower(),
            "quantity": quantity,
            "accepted": str(response.get("status", "")).upper() not in {"REJECTED", "EXPIRED", "ERROR"},
            "reason": reason,
            "partial_exit": fraction < 0.999,
            "response": response,
        }
        self.live_orders.append(payload)
        if self.log_store is not None:
            self.log_store.append("live_position_actions", payload)
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
            return
        proactive_fraction = self._futures_proactive_take_profit_fraction()
        for position in self.live_positions_snapshot:
            roe = self._position_roe_percent(position)
            margin_ratio = float(position.get("marginRatio") or 0.0)
            identity = self._live_position_identity(position)
            peak_roe = self.live_peak_roe_by_identity.get(identity, roe)
            peak_roe = max(peak_roe, roe)
            self.live_peak_roe_by_identity[identity] = peak_roe
            if roe <= cfg.stop_loss_roe_percent:
                self._close_live_position(position=position, reason="LIVE_POSITION_STOP_LOSS")
                continue
            if margin_ratio >= cfg.margin_ratio_emergency:
                self._close_live_position(position=position, reason="LIVE_POSITION_MARGIN_RISK")
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
            ):
                self.live_profit_protection_keys.add(identity)
                self._close_live_position(
                    position=position,
                    reason="LIVE_POSITION_PROFIT_PROTECTION",
                    fraction=0.5,
                )
                continue
            if not self._futures_proactive_take_profit_thresholds() and peak_roe >= cfg.take_profit_roe_percent:
                legacy_key = self._live_proactive_take_profit_key(identity=identity, threshold=cfg.take_profit_roe_percent)
                if legacy_key not in self.live_proactive_take_profit_keys:
                    drawdown = peak_roe - roe
                    if drawdown >= 2.0 or roe >= cfg.take_profit_roe_percent + 2.0:
                        self.live_proactive_take_profit_keys.add(legacy_key)
                        self._close_live_position(
                            position=position,
                            reason="LIVE_POSITION_PARTIAL_TAKE_PROFIT",
                            fraction=0.5,
                        )

    def _current_unrealized_total(self) -> float:
        return round(sum(position.unrealized_pnl_usd_estimate() for position in self.paper_positions.values()), 6)

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
        return True

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
        exit_rules = self.runtime.paper_service.settings.exit_rules
        partial_action_taken = False

        if (
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

        if self._position_stop_hit(position=position, price=price):
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
            if position.last_exit_signal_reason == exit_reason:
                position.exit_confirmation_count += 1
            else:
                position.last_exit_signal_reason = exit_reason
                position.exit_confirmation_count = 1
            if position.exit_confirmation_count >= max(1, exit_rules.confirmation_cycles_for_exit):
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
    ) -> bool:
        position = self.paper_positions.get(decision.symbol)
        fallback_price = 0.0
        if position is not None:
            fallback_price = position.current_price if position.current_price > 0 else position.entry_price
        price = self._market_price(state=state, fallback=fallback_price)
        if position is None:
            return self._open_paper_position(decision=decision, price=price)
        self._update_paper_position(position=position, decision=decision, price=price, timestamp=timestamp)
        return False

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
        if not focus.enabled or decision.final_mode != "futures" or decision.side not in {"long", "short"}:
            return False
        score_floor = settings.mode_thresholds.futures_score_min + max(focus.min_score_advantage_to_replace, 0.0)
        edge_floor = max(
            settings.futures_exposure.min_entry_net_edge_bps,
            focus.min_net_edge_advantage_bps + (decision.estimated_round_trip_cost_bps * 2.0),
        )
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
        return round(max(focus.min_incremental_pnl_usd * 4.0, cost_floor, 10.0), 6)

    def _futures_reallocation_target_assessments(
        self,
        *,
        incoming_decision: DecisionIntent,
        timestamp: datetime,
    ) -> list[dict[str, Any]]:
        settings = self.runtime.paper_service.settings
        focus = settings.portfolio_focus
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
        weakest.sort(key=lambda item: item["sort_key"])
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
        if score_advantage < focus.min_score_advantage_to_replace:
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
        if edge_advantage_after_costs < focus.min_net_edge_advantage_bps:
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
        if incremental_pnl_usd < focus.min_incremental_pnl_usd:
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
    ) -> None:
        self.decisions.append(decision)
        self.last_decision_timestamp = timestamp
        if self.verbose:
            print(
                f"[DECISION] {decision.timestamp.isoformat()} {decision.symbol} mode={decision.final_mode} side={decision.side} score={decision.predictability_score:.2f}",
                flush=True,
            )
        if self.learner is not None:
            self.learner.ingest_decisions((decision,))
        if self.log_store is not None:
            self.log_store.append("decisions", decision.as_dict())
        managed_decision = decision
        if state is not None:
            managed_decision = self._maybe_reallocate_futures_entry(
                decision=decision,
                state=state,
                timestamp=timestamp,
            )
        allow_new_submission = False
        if state is not None:
            allow_new_submission = self._apply_paper_trade_management(
                decision=managed_decision,
                state=state,
                timestamp=timestamp,
            )
        if self._is_order_cooldown_active(managed_decision.symbol, timestamp):
            allow_new_submission = False
        if self._is_manual_symbol_cooldown_active(managed_decision.symbol, timestamp):
            allow_new_submission = False
        live_orders_allowed = not self.self_healing.is_live_order_cooldown_active(now=timestamp)
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
                            "protection_orders": list(live_result.protection_orders),
                            "protection_error": live_result.protection_error,
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
        )
        poll_seconds = max(1.0, min(5.0, self.session.self_healing.stall_timeout_seconds / 6.0))
        try:
            while not task.done():
                await asyncio.sleep(poll_seconds)
                if task.done():
                    break
                now = datetime.now(tz=timezone.utc)
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
