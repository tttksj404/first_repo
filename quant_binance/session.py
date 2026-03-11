from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from quant_binance.execution.live_order_adapter import DecisionLiveOrderAdapter
from quant_binance.execution.order_test_adapter import DecisionOrderTestAdapter, OrderTestResult
from quant_binance.learning import OnlineEdgeLearner
from quant_binance.live import LivePaperRuntime
from quant_binance.models import DecisionIntent
from quant_binance.observability.log_store import JsonlLogStore
from quant_binance.observability.report import build_runtime_summary, write_runtime_summary
from quant_binance.observability.runtime_state import write_runtime_state
from quant_binance.risk.capital import CapitalAdequacyReport
from quant_binance.risk.sizing import select_futures_leverage


class SupportsAccountSync(Protocol):
    def get_account(self, *, market: str) -> dict[str, Any]:
        ...

    def get_open_orders(self, *, market: str, symbol: str | None = None) -> dict[str, Any]:
        ...

    def build_capital_report(self) -> CapitalAdequacyReport:
        ...


@dataclass
class LivePaperSession:
    runtime: LivePaperRuntime
    equity_usd: float
    remaining_portfolio_capacity_usd: float
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
    heartbeat_count: int = 0
    last_event_timestamp: datetime | None = None
    last_decision_timestamp: datetime | None = None
    _last_sync_at: datetime | None = None
    _last_flush_at: datetime | None = None

    def process_payload(self, payload: dict[str, Any], *, now: datetime | None = None) -> DecisionIntent | None:
        timestamp = now or datetime.now(tz=timezone.utc)
        self.heartbeat_count += 1
        self.last_event_timestamp = timestamp
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
        decision = self.runtime.on_payload(
            payload,
            equity_usd=self.equity_usd,
            remaining_portfolio_capacity_usd=self.remaining_portfolio_capacity_usd,
        )
        if self.log_store is not None:
            self.log_store.append("events", {"timestamp": timestamp, "payload": payload})
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
        self.account_snapshot = self.rest_client.get_account(market="futures")
        self.open_orders_snapshot = self.rest_client.get_open_orders(market="futures")
        if hasattr(self.rest_client, "build_capital_report"):
            report = self.rest_client.build_capital_report()
            self.capital_report = {
                "spot_available_balance_usd": report.spot_available_balance_usd,
                "futures_available_balance_usd": report.futures_available_balance_usd,
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

    def flush(self, *, summary_path: str | Path, state_path: str | Path) -> dict[str, object]:
        summary = build_runtime_summary(
            decisions=self.decisions,
            tested_orders=self.tested_orders,
            live_orders=self.live_orders,
            account_snapshot=self.account_snapshot,
            open_orders_snapshot=self.open_orders_snapshot,
            capital_report=self.capital_report,
            kill_switch_status=self.runtime.kill_switch.status(),
            observe_only_symbols=self.observe_only_symbols,
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
                "kill_switch": self.runtime.kill_switch.status(),
            },
        )
        if self.learner is not None and self.learner_output_path is not None:
            self.learner.export(self.learner_output_path)
        return summary

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

    def _consume_capital_after_live_order(self, decision: DecisionIntent) -> None:
        if not self.capital_report:
            return
        if decision.final_mode == "spot":
            available = float(self.capital_report.get("spot_available_balance_usd", 0.0))
            self.capital_report["spot_available_balance_usd"] = max(
                0.0,
                available - float(decision.order_intent_notional_usd),
            )
            return
        if decision.final_mode == "futures":
            available = float(self.capital_report.get("futures_available_balance_usd", 0.0))
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
            margin_used = float(decision.order_intent_notional_usd) / max(float(leverage), 1.0)
            self.capital_report["futures_available_balance_usd"] = max(0.0, available - margin_used)

    def _market_capital_allowed(self, decision: DecisionIntent) -> bool:
        if not self.capital_report:
            return True
        if decision.final_mode == "spot":
            if bool(self.capital_report.get("can_trade_spot_any", False)):
                return True
            return float(self.capital_report.get("spot_available_balance_usd", 0.0)) > 0.0
        if decision.final_mode == "futures":
            if bool(self.capital_report.get("can_trade_futures_any", False)):
                return True
            return float(self.capital_report.get("futures_available_balance_usd", 0.0)) > 0.0
        return True

    def _cash_reserve_fraction(self) -> float:
        if self.capital_report.get("can_trade_futures_any", False):
            return self.runtime.paper_service.settings.cash_reserve.when_futures_enabled
        return self.runtime.paper_service.settings.cash_reserve.when_futures_disabled

    def _cap_live_order_decision(self, decision: DecisionIntent) -> DecisionIntent:
        if not self.capital_report:
            return decision
        reserve_fraction = self._cash_reserve_fraction()
        requirements_key = "spot_requirements" if decision.final_mode == "spot" else "futures_requirements"
        min_notional = 0.0
        for item in self.capital_report.get(requirements_key, []):
            if item.get("symbol") == decision.symbol:
                min_notional = float(item.get("min_notional_usd", 0.0))
                break
        if decision.final_mode == "spot":
            available = float(self.capital_report.get("spot_available_balance_usd", 0.0))
            max_notional = max(0.0, available * (1.0 - reserve_fraction))
        elif decision.final_mode == "futures":
            available = float(self.capital_report.get("futures_available_balance_usd", 0.0))
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
            return decision
        floored_notional = round(max_notional, 6)
        return replace(decision, order_intent_notional_usd=floored_notional)

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
        if self.live_order_executor is not None and state is not None and self._market_capital_allowed(decision):
            executable_decision = self._cap_live_order_decision(decision)
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
                    if self.log_store is not None:
                        self.log_store.append("order_errors", payload)
                else:
                    if live_result is not None:
                        self.last_executed_fingerprint_by_symbol[executable_decision.symbol] = fingerprint
                        if live_result.accepted:
                            self._consume_capital_after_live_order(executable_decision)
                        payload = {
                            "timestamp": timestamp,
                            "symbol": live_result.symbol,
                            "market": live_result.market,
                            "side": live_result.side,
                            "quantity": live_result.quantity,
                            "accepted": live_result.accepted,
                        }
                        self.live_orders.append(payload)
                        if self.verbose:
                            print(
                                f"[LIVE_ORDER] {live_result.symbol} market={live_result.market} side={live_result.side} qty={live_result.quantity} accepted={live_result.accepted}",
                                flush=True,
                            )
                        if self.log_store is not None:
                            self.log_store.append("live_orders", payload)
        if self.order_tester is not None and state is not None and self._market_capital_allowed(decision):
            test_decision = self._cap_live_order_decision(decision)
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
                await runner.run(
                    summary_path=self.summary_path,
                    state_path=self.state_path,
                )
                break
            except Exception as exc:  # pragma: no cover - exercised in tests
                last_error = exc
                print(f"[ERROR] websocket attempt={attempt} error={exc}", flush=True)
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
