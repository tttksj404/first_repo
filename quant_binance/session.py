from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

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
    live_error_cooldown_until_by_symbol: dict[str, datetime] = field(default_factory=dict)
    live_error_code_by_symbol: dict[str, str] = field(default_factory=dict)
    live_error_global_cooldown_until: datetime | None = None
    live_error_global_code: str | None = None
    futures_notional_scale_by_symbol: dict[str, float] = field(default_factory=dict)
    spot_min_trade_usdt_by_symbol: dict[str, float] = field(default_factory=dict)
    supported_spot_symbols: set[str] = field(default_factory=set)
    supported_futures_symbols: set[str] = field(default_factory=set)
    _symbol_market_support_loaded: bool = False
    _symbol_market_support_enabled: bool = False
    _margin_transfer_permission_denied: bool = False
    _last_margin_release_at: datetime | None = None
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
        futures_account_snapshot = self.rest_client.get_account(market="futures")
        spot_account_snapshot: dict[str, Any] = {}
        try:
            spot_account_snapshot = self.rest_client.get_account(market="spot")
        except Exception:
            spot_account_snapshot = {}
        self.account_snapshot = {
            "futures": futures_account_snapshot,
            "spot": spot_account_snapshot,
        }
        futures_open_orders = self.rest_client.get_open_orders(market="futures")
        spot_open_orders: dict[str, Any] = {}
        try:
            spot_open_orders = self.rest_client.get_open_orders(market="spot")
        except Exception:
            spot_open_orders = {}
        self.open_orders_snapshot = {
            "futures": futures_open_orders,
            "spot": spot_open_orders,
        }
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

    @staticmethod
    def _extract_exchange_error_code(error: Exception) -> str | None:
        matched = re.search(r"code=(\d+)", str(error))
        if matched is None:
            return None
        return matched.group(1)

    @staticmethod
    def _cooldown_seconds_for_error_code(error_code: str | None) -> int:
        if error_code in {"40762", "45111", "45110", "40774", "400172"}:
            return 300
        if error_code == "429":
            return 120
        return 0

    def _live_order_blocked_by_cooldown(self, *, symbol: str, now: datetime) -> bool:
        until = self.live_error_cooldown_until_by_symbol.get(symbol)
        return until is not None and now < until

    def _live_order_blocked_by_global_cooldown(self, *, now: datetime) -> bool:
        until = self.live_error_global_cooldown_until
        return until is not None and now < until

    @staticmethod
    def _live_quality_gate_reason(decision: DecisionIntent) -> str | None:
        if decision.final_mode not in {"spot", "futures"}:
            return None
        if decision.order_intent_notional_usd <= 0:
            return "ZERO_NOTIONAL"
        if "SPOT_POSITION_LIQUIDATION" in decision.rejection_reasons:
            return None
        net_edge_bps = float(decision.net_expected_edge_bps)
        if net_edge_bps <= 0.0:
            return "NET_EDGE_NON_POSITIVE"
        min_live_edge_bps = 0.6 if decision.final_mode == "futures" else 0.5
        if net_edge_bps + 1e-9 < min_live_edge_bps:
            return "NET_EDGE_TOO_THIN_LIVE"
        round_trip_cost_bps = max(float(decision.estimated_round_trip_cost_bps), 0.0)
        min_edge_to_cost_ratio = 0.1 if decision.final_mode == "futures" else 0.08
        if round_trip_cost_bps > 0 and (net_edge_bps / round_trip_cost_bps) < min_edge_to_cost_ratio:
            return "EDGE_TO_COST_TOO_LOW_LIVE"
        return None

    def _futures_notional_scale(self, *, symbol: str) -> float:
        return max(0.05, min(1.0, self.futures_notional_scale_by_symbol.get(symbol, 1.0)))

    def _tighten_futures_notional_scale(self, *, symbol: str) -> None:
        current = self._futures_notional_scale(symbol=symbol)
        self.futures_notional_scale_by_symbol[symbol] = max(0.05, round(current * 0.2, 4))

    def _relax_futures_notional_scale(self, *, symbol: str) -> None:
        current = self._futures_notional_scale(symbol=symbol)
        if current >= 1.0:
            return
        self.futures_notional_scale_by_symbol[symbol] = min(1.0, round(current + 0.1, 4))

    @staticmethod
    def _base_asset_from_symbol(symbol: str) -> str:
        upper_symbol = symbol.upper()
        if upper_symbol.endswith("USDT"):
            return upper_symbol[:-4]
        return upper_symbol

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _spot_snapshot(self) -> dict[str, Any]:
        spot_snapshot = self.account_snapshot.get("spot")
        if isinstance(spot_snapshot, dict):
            return spot_snapshot
        # Backward compatibility for previous snapshot shape.
        if "balances" in self.account_snapshot:
            return self.account_snapshot
        return {}

    def _spot_available_base_quantity(self, *, symbol: str) -> float:
        base_asset = self._base_asset_from_symbol(symbol)
        spot_snapshot = self._spot_snapshot()
        balances = spot_snapshot.get("balances", [])
        if not isinstance(balances, list):
            return 0.0
        for item in balances:
            if not isinstance(item, dict):
                continue
            asset = str(item.get("asset", "")).upper()
            if asset != base_asset:
                continue
            free_qty = self._safe_float(item.get("free"))
            if free_qty > 0:
                return free_qty
        return 0.0

    def _spot_available_usdt_balance(self) -> float:
        spot_snapshot = self._spot_snapshot()
        balances = spot_snapshot.get("balances", [])
        if not isinstance(balances, list):
            return 0.0
        for item in balances:
            if not isinstance(item, dict):
                continue
            asset = str(item.get("asset", "")).upper()
            if asset != "USDT":
                continue
            free_qty = self._safe_float(item.get("free"))
            if free_qty > 0:
                return free_qty
        return 0.0

    def _spot_balance_rows(self) -> list[dict[str, Any]]:
        spot_snapshot = self._spot_snapshot()
        balances = spot_snapshot.get("balances", [])
        if not isinstance(balances, list):
            return []
        rows: list[dict[str, Any]] = []
        for item in balances:
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def _futures_openable_balance(self) -> float:
        futures_snapshot = self.account_snapshot.get("futures")
        if not isinstance(futures_snapshot, dict):
            return 0.0
        if "effectiveAvailableBalance" in futures_snapshot:
            return max(self._safe_float(futures_snapshot.get("effectiveAvailableBalance")), 0.0)
        if "crossedMaxAvailable" in futures_snapshot:
            return max(self._safe_float(futures_snapshot.get("crossedMaxAvailable")), 0.0)
        return max(self._safe_float(futures_snapshot.get("availableBalance")), 0.0)

    def _required_futures_margin(self, *, decision: DecisionIntent) -> float:
        if decision.final_mode != "futures":
            return 0.0
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
        return max(float(decision.order_intent_notional_usd) / max(float(leverage), 1.0), 0.0)

    def _spot_min_trade_usdt(self, *, symbol: str) -> float:
        symbol = symbol.upper()
        cached = self.spot_min_trade_usdt_by_symbol.get(symbol)
        if cached is not None:
            return max(cached, 0.0)
        default_min_trade = 1.0
        if self.rest_client is None:
            self.spot_min_trade_usdt_by_symbol[symbol] = default_min_trade
            return default_min_trade
        direct_reader = getattr(self.rest_client, "_spot_min_trade_usdt", None)
        if callable(direct_reader):
            try:
                min_trade = max(self._safe_float(direct_reader(symbol=symbol)), 0.0)
            except Exception:
                min_trade = default_min_trade
            self.spot_min_trade_usdt_by_symbol[symbol] = min_trade if min_trade > 0 else default_min_trade
            return self.spot_min_trade_usdt_by_symbol[symbol]
        info_reader = getattr(self.rest_client, "get_exchange_info", None)
        if callable(info_reader):
            try:
                info = info_reader(market="spot")
            except Exception:
                info = {}
            symbols = info.get("symbols", []) if isinstance(info, dict) else []
            if isinstance(symbols, list):
                for row in symbols:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("symbol", "")).upper() != symbol:
                        continue
                    raw = row.get("raw", {})
                    if isinstance(raw, dict):
                        min_trade = max(self._safe_float(raw.get("minTradeUSDT")), 0.0)
                        self.spot_min_trade_usdt_by_symbol[symbol] = min_trade if min_trade > 0 else default_min_trade
                        return self.spot_min_trade_usdt_by_symbol[symbol]
                    break
        self.spot_min_trade_usdt_by_symbol[symbol] = default_min_trade
        return default_min_trade

    def _load_symbol_market_support(self) -> None:
        if self._symbol_market_support_loaded:
            return
        self._symbol_market_support_loaded = True
        if self.rest_client is None:
            return
        info_reader = getattr(self.rest_client, "get_exchange_info", None)
        if not callable(info_reader):
            return
        try:
            spot_info = info_reader(market="spot")
        except Exception:
            spot_info = {}
        try:
            futures_info = info_reader(market="futures")
        except Exception:
            futures_info = {}
        spot_symbols = {
            str(item.get("symbol", "")).upper()
            for item in (spot_info.get("symbols", []) if isinstance(spot_info, dict) else [])
            if isinstance(item, dict)
        }
        futures_symbols = {
            str(item.get("symbol", "")).upper()
            for item in (futures_info.get("symbols", []) if isinstance(futures_info, dict) else [])
            if isinstance(item, dict)
        }
        if not spot_symbols and not futures_symbols:
            return
        self.supported_spot_symbols = spot_symbols
        self.supported_futures_symbols = futures_symbols
        self._symbol_market_support_enabled = True

    def _symbol_market_supported(self, *, symbol: str, market: str) -> bool:
        self._load_symbol_market_support()
        if not self._symbol_market_support_enabled:
            return True
        upper = symbol.upper()
        if market == "spot":
            return upper in self.supported_spot_symbols
        if market == "futures":
            return upper in self.supported_futures_symbols
        return True

    def _normalize_decision_for_symbol_market_support(self, decision: DecisionIntent) -> DecisionIntent:
        if decision.final_mode not in {"spot", "futures"}:
            return decision
        if self._symbol_market_supported(symbol=decision.symbol, market=decision.final_mode):
            return decision
        supports_spot = self._symbol_market_supported(symbol=decision.symbol, market="spot")
        rejection_reasons = tuple(
            sorted(set(decision.rejection_reasons + (f"UNSUPPORTED_{decision.final_mode.upper()}_MARKET",)))
        )
        if decision.final_mode == "futures" and supports_spot and decision.side == "long":
            # Spot-only symbols can still participate in long entries.
            return replace(decision, final_mode="spot", rejection_reasons=rejection_reasons)
        return replace(
            decision,
            final_mode="cash",
            side="flat",
            order_intent_notional_usd=0.0,
            stop_distance_bps=0.0,
            rejection_reasons=rejection_reasons,
        )

    def _attempt_spot_asset_sale_for_usdt(
        self,
        *,
        target_usdt: float,
        timestamp: datetime,
    ) -> float:
        if self.rest_client is None:
            return self._spot_available_usdt_balance()
        place_order = getattr(self.rest_client, "place_order", None)
        get_book_ticker = getattr(self.rest_client, "get_book_ticker", None)
        if not callable(place_order) or not callable(get_book_ticker):
            return self._spot_available_usdt_balance()
        current_usdt = self._spot_available_usdt_balance()
        for row in self._spot_balance_rows():
            if current_usdt >= target_usdt:
                break
            asset = str(row.get("asset", "")).upper()
            if not asset or asset == "USDT":
                continue
            free_qty = self._safe_float(row.get("free"))
            if free_qty <= 0:
                continue
            symbol = f"{asset}USDT"
            try:
                ticker = get_book_ticker(market="spot", symbol=symbol)
            except Exception:
                continue
            bid_price = self._safe_float(ticker.get("bidPrice")) if isinstance(ticker, dict) else 0.0
            if bid_price <= 0:
                continue
            min_trade_usdt = self._spot_min_trade_usdt(symbol=symbol)
            max_sell_notional = free_qty * bid_price
            if max_sell_notional + 1e-9 < (min_trade_usdt * 1.1):
                # Dust position: cannot satisfy exchange minimum trade amount.
                continue
            needed_usdt = max(target_usdt - current_usdt, min_trade_usdt)
            desired_notional = max(needed_usdt * 1.1, min_trade_usdt * 1.02)
            sell_qty = min(free_qty, round(desired_notional / bid_price, 8))
            if sell_qty * bid_price + 1e-9 < (min_trade_usdt * 1.05):
                sell_qty = free_qty
            if sell_qty * bid_price + 1e-9 < (min_trade_usdt * 1.05):
                continue
            if sell_qty <= 0:
                continue
            try:
                place_order(
                    market="spot",
                    order_params={
                        "symbol": symbol,
                        "side": "sell",
                        "orderType": "market",
                        "size": f"{sell_qty:.8f}",
                        "clientOid": f"margin-refill-sell-{uuid4().hex[:12]}",
                    },
                )
                self.sync_account()
            except Exception as exc:
                if self.verbose:
                    print(f"[MARGIN_REFILL_SPOT_SELL_ERROR] {symbol} {exc}", flush=True)
                if self.log_store is not None:
                    self.log_store.append(
                        "order_errors",
                        {
                            "timestamp": timestamp,
                            "symbol": symbol,
                            "market": "spot",
                            "stage": "margin_refill_spot_sell",
                            "error": repr(exc),
                        },
                    )
                continue
            current_usdt = self._spot_available_usdt_balance()
            if self.verbose:
                print(
                    f"[MARGIN_REFILL_SPOT_SELL] {symbol} qty={sell_qty:.8f} usdt_now={current_usdt:.2f}",
                    flush=True,
                )
        return current_usdt

    def _attempt_futures_margin_refill(
        self,
        *,
        decision: DecisionIntent,
        reference_price: float,
        timestamp: datetime,
    ) -> bool:
        if self.rest_client is None or decision.final_mode != "futures":
            return False
        if self._margin_transfer_permission_denied:
            return False
        transfer_method = getattr(self.rest_client, "transfer_spot_to_futures_usdt", None)
        if not callable(transfer_method):
            return False
        spot_usdt = self._spot_available_usdt_balance()
        openable_balance = self._futures_openable_balance()
        required_margin = self._required_futures_margin(decision=decision)
        margin_gap = max(required_margin - openable_balance, 0.0)
        target_refill_usd = max(required_margin * 0.5, margin_gap * 1.2, 10.0)
        target_refill_usd = min(target_refill_usd, 300.0)
        if spot_usdt < 5.0:
            spot_usdt = self._attempt_spot_asset_sale_for_usdt(
                target_usdt=target_refill_usd,
                timestamp=timestamp,
            )
        if spot_usdt < 5.0:
            return False
        transfer_amount = round(min(max(spot_usdt * 0.95, 5.0), target_refill_usd), 2)
        if transfer_amount < 5.0:
            return False
        try:
            transfer_method(amount_usdt=transfer_amount, client_oid=f"margin-refill-{uuid4().hex[:12]}")
            self.sync_account()
        except Exception as exc:
            error_code = self._extract_exchange_error_code(exc)
            if error_code == "40014":
                # API key missing transfer permission; repeated retries will not recover until key permissions are updated.
                self._margin_transfer_permission_denied = True
            if self.verbose:
                print(f"[MARGIN_REFILL_ERROR] {decision.symbol} {exc}", flush=True)
            if self.log_store is not None:
                self.log_store.append(
                    "order_errors",
                    {
                        "timestamp": timestamp,
                        "symbol": decision.symbol,
                        "market": decision.final_mode,
                        "stage": "margin_refill",
                        "error": repr(exc),
                    },
                )
            return False
        if self.verbose:
            print(
                f"[MARGIN_REFILL] {decision.symbol} transferred_usdt={transfer_amount:.2f}",
                flush=True,
            )
        if self.log_store is not None:
            self.log_store.append(
                "account_sync",
                {
                    "timestamp": timestamp,
                    "account_snapshot": self.account_snapshot,
                    "open_orders_snapshot": self.open_orders_snapshot,
                },
            )
        return True

    def _attempt_futures_position_release(
        self,
        *,
        decision: DecisionIntent,
        timestamp: datetime,
    ) -> bool:
        if self.rest_client is None or decision.final_mode != "futures":
            return False
        if self._last_margin_release_at is not None and (timestamp - self._last_margin_release_at) < timedelta(seconds=60):
            return False
        get_positions = getattr(self.rest_client, "get_futures_positions", None)
        place_order = getattr(self.rest_client, "place_order", None)
        if not callable(get_positions) or not callable(place_order):
            return False
        try:
            positions = get_positions()
        except Exception:
            return False
        if not isinstance(positions, list) or not positions:
            return False

        def _priority(row: dict[str, Any]) -> tuple[int, int, float]:
            symbol = str(row.get("symbol", "")).upper()
            hold_side = str(row.get("holdSide", "")).lower()
            same_symbol = int(symbol == decision.symbol.upper())
            opposite_intent = int(
                (decision.side == "long" and hold_side == "short")
                or (decision.side == "short" and hold_side == "long")
            )
            margin_size = self._safe_float(row.get("marginSize"))
            return (same_symbol, opposite_intent, margin_size)

        ranked = sorted(
            (row for row in positions if isinstance(row, dict) and self._safe_float(row.get("available")) > 0),
            key=_priority,
            reverse=True,
        )
        if not ranked:
            return False
        target_openable_usd = 3.0
        released_any = False
        releases_done = 0
        min_trade_reader = getattr(self.rest_client, "_futures_min_trade_usdt", None)
        ticker_reader = getattr(self.rest_client, "get_book_ticker", None)
        for row in ranked:
            if releases_done >= 3:
                break
            symbol = str(row.get("symbol", "")).upper()
            hold_side = str(row.get("holdSide", "")).lower()
            available = self._safe_float(row.get("available"))
            if not symbol or hold_side not in {"long", "short"} or available <= 0:
                continue
            # Bitget hedge close-side semantics:
            # - close long  -> side=buy, tradeSide=close
            # - close short -> side=sell, tradeSide=close
            close_side = "buy" if hold_side == "long" else "sell"
            close_size = round(available, 8)
            if callable(min_trade_reader) and callable(ticker_reader):
                try:
                    min_trade_usdt = max(self._safe_float(min_trade_reader(symbol=symbol)), 0.0)
                except Exception:
                    min_trade_usdt = 0.0
                if min_trade_usdt > 0:
                    try:
                        ticker = ticker_reader(market="futures", symbol=symbol)
                    except Exception:
                        ticker = {}
                    bid_price = self._safe_float(ticker.get("bidPrice")) if isinstance(ticker, dict) else 0.0
                    if bid_price > 0 and (close_size * bid_price + 1e-9) < (min_trade_usdt * 1.02):
                        close_size = round(available, 8)
            if close_size <= 0:
                continue
            try:
                place_order(
                    market="futures",
                    order_params={
                        "symbol": symbol,
                        "productType": "USDT-FUTURES",
                        "marginCoin": "USDT",
                        "marginMode": "crossed",
                        "side": close_side,
                        "orderType": "market",
                        "size": f"{close_size:.8f}",
                        "reduceOnly": "NO",
                        "clientOid": f"margin-release-{uuid4().hex[:12]}",
                    },
                )
                self._last_margin_release_at = timestamp
                self.sync_account()
                released_any = True
                releases_done += 1
                if self.verbose:
                    print(
                        f"[MARGIN_RELEASE] {symbol} hold={hold_side} close_side={close_side} size={close_size:.8f}",
                        flush=True,
                    )
                if self.log_store is not None:
                    self.log_store.append(
                        "account_sync",
                        {
                            "timestamp": timestamp,
                            "account_snapshot": self.account_snapshot,
                            "open_orders_snapshot": self.open_orders_snapshot,
                            "margin_release": {"symbol": symbol, "hold_side": hold_side, "size": close_size},
                        },
                    )
                if self._futures_openable_balance() >= target_openable_usd:
                    return True
            except Exception as exc:
                if self.verbose:
                    print(f"[MARGIN_RELEASE_ERROR] {symbol} {exc}", flush=True)
                if self.log_store is not None:
                    self.log_store.append(
                        "order_errors",
                        {
                            "timestamp": timestamp,
                            "symbol": symbol,
                            "market": "futures",
                            "stage": "margin_release",
                            "error": repr(exc),
                        },
                    )
                continue
        return released_any

    def _spot_liquidation_decision(
        self,
        *,
        decision: DecisionIntent,
        reference_price: float,
    ) -> DecisionIntent:
        if decision.final_mode != "cash" or decision.trend_direction >= 0:
            return decision
        available_qty = self._spot_available_base_quantity(symbol=decision.symbol)
        if available_qty <= 0:
            return decision
        liquidation_notional = round(available_qty * max(reference_price, 0.0), 6)
        if liquidation_notional <= 0:
            return decision
        return replace(
            decision,
            final_mode="spot",
            side="short",
            order_intent_notional_usd=liquidation_notional,
            stop_distance_bps=max(decision.stop_distance_bps, 1.0),
            rejection_reasons=tuple(
                sorted(set(decision.rejection_reasons + ("SPOT_POSITION_LIQUIDATION",)))
            ),
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
            if decision.side == "short" and self._spot_available_base_quantity(symbol=decision.symbol) > 0:
                return True
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
            if decision.side == "short":
                if min_notional > 0.0 and decision.order_intent_notional_usd < min_notional:
                    rejection_code = "INSUFFICIENT_EXECUTION_BALANCE"
                    return replace(
                        decision,
                        final_mode="cash",
                        side="flat",
                        order_intent_notional_usd=0.0,
                        stop_distance_bps=0.0,
                        rejection_reasons=tuple(
                            sorted(set(decision.rejection_reasons + (rejection_code,)))
                        ),
                    )
                return decision
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
            scale = self._futures_notional_scale(symbol=decision.symbol)
            max_notional = max(0.0, available * leverage * (1.0 - reserve_fraction) * scale)
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
        market_supported_decision = self._normalize_decision_for_symbol_market_support(decision)
        if self.live_order_executor is not None and state is not None and self._market_capital_allowed(market_supported_decision):
            liquidation_adjusted = self._spot_liquidation_decision(
                decision=market_supported_decision,
                reference_price=float(state.last_trade_price),
            )
            executable_decision = self._cap_live_order_decision(liquidation_adjusted)
            fingerprint = self._execution_fingerprint(executable_decision)
            last_fingerprint = self.last_executed_fingerprint_by_symbol.get(executable_decision.symbol)
            if last_fingerprint != fingerprint and executable_decision.final_mode in {"spot", "futures"} and executable_decision.order_intent_notional_usd > 0:
                quality_gate_reason = self._live_quality_gate_reason(executable_decision)
                if quality_gate_reason is not None:
                    self.last_executed_fingerprint_by_symbol[executable_decision.symbol] = fingerprint
                    if self.verbose:
                        print(
                            f"[LIVE_ORDER_SKIP] {executable_decision.symbol} reason={quality_gate_reason}",
                            flush=True,
                        )
                    if self.log_store is not None:
                        self.log_store.append(
                            "order_errors",
                            {
                                "timestamp": timestamp,
                                "symbol": executable_decision.symbol,
                                "market": executable_decision.final_mode,
                                "stage": "live_order",
                                "error": f"quality_gate {quality_gate_reason}",
                            },
                        )
                elif self._live_order_blocked_by_global_cooldown(now=timestamp):
                    until = self.live_error_global_cooldown_until
                    error_code = self.live_error_global_code or "UNKNOWN"
                    if self.verbose:
                        print(
                            f"[LIVE_ORDER_SKIP] {executable_decision.symbol} global_cooldown_until={until.isoformat() if until else 'unknown'} code={error_code}",
                            flush=True,
                        )
                    if self.log_store is not None:
                        self.log_store.append(
                            "order_errors",
                            {
                                "timestamp": timestamp,
                                "symbol": executable_decision.symbol,
                                "market": executable_decision.final_mode,
                                "stage": "live_order",
                                "error": f"global_cooldown_active code={error_code}",
                            },
                        )
                elif self._live_order_blocked_by_cooldown(symbol=executable_decision.symbol, now=timestamp):
                    until = self.live_error_cooldown_until_by_symbol.get(executable_decision.symbol)
                    error_code = self.live_error_code_by_symbol.get(executable_decision.symbol, "UNKNOWN")
                    if self.verbose:
                        print(
                            f"[LIVE_ORDER_SKIP] {executable_decision.symbol} cooldown_until={until.isoformat() if until else 'unknown'} code={error_code}",
                            flush=True,
                        )
                    if self.log_store is not None:
                        self.log_store.append(
                            "order_errors",
                            {
                                "timestamp": timestamp,
                                "symbol": executable_decision.symbol,
                                "market": executable_decision.final_mode,
                                "stage": "live_order",
                                "error": f"cooldown_active code={error_code}",
                            },
                        )
                else:
                    if executable_decision.final_mode == "futures":
                        openable_balance = self._futures_openable_balance()
                        required_margin = self._required_futures_margin(decision=executable_decision)
                        if openable_balance <= 0 or (required_margin > 0 and openable_balance < required_margin * 0.7):
                            released = self._attempt_futures_position_release(
                                decision=executable_decision,
                                timestamp=timestamp,
                            )
                            if not released:
                                self._attempt_futures_margin_refill(
                                    decision=executable_decision,
                                    reference_price=float(state.last_trade_price),
                                    timestamp=timestamp,
                                )
                    try:
                        live_result = self.live_order_executor.execute_decision(
                            decision=executable_decision,
                            reference_price=state.last_trade_price,
                        )
                    except Exception as exc:
                        error_code = self._extract_exchange_error_code(exc)
                        recovered = False
                        if error_code == "40762" and executable_decision.final_mode == "futures":
                            release_ok = self._attempt_futures_position_release(
                                decision=executable_decision,
                                timestamp=timestamp,
                            )
                            refill_ok = release_ok or self._attempt_futures_margin_refill(
                                decision=executable_decision,
                                reference_price=float(state.last_trade_price),
                                timestamp=timestamp,
                            )
                            if not refill_ok and self._futures_openable_balance() > 0:
                                # A pre-trade refill may have already increased openable balance; allow one retry.
                                refill_ok = True
                            if refill_ok:
                                try:
                                    recovered_result = self.live_order_executor.execute_decision(
                                        decision=executable_decision,
                                        reference_price=state.last_trade_price,
                                    )
                                except Exception as retry_exc:
                                    exc = retry_exc
                                    error_code = self._extract_exchange_error_code(retry_exc)
                                else:
                                    recovered = True
                                    self.live_error_cooldown_until_by_symbol.pop(executable_decision.symbol, None)
                                    self.live_error_code_by_symbol.pop(executable_decision.symbol, None)
                                    self.live_error_global_cooldown_until = None
                                    self.live_error_global_code = None
                                    self.last_executed_fingerprint_by_symbol[executable_decision.symbol] = fingerprint
                                    if recovered_result.accepted:
                                        self._consume_capital_after_live_order(executable_decision)
                                        if executable_decision.final_mode == "futures":
                                            self._relax_futures_notional_scale(symbol=executable_decision.symbol)
                                    payload = {
                                        "timestamp": timestamp,
                                        "symbol": recovered_result.symbol,
                                        "market": recovered_result.market,
                                        "side": recovered_result.side,
                                        "quantity": recovered_result.quantity,
                                        "accepted": recovered_result.accepted,
                                    }
                                    self.live_orders.append(payload)
                                    if self.verbose:
                                        print(
                                            f"[LIVE_ORDER] {recovered_result.symbol} market={recovered_result.market} side={recovered_result.side} qty={recovered_result.quantity} accepted={recovered_result.accepted}",
                                            flush=True,
                                        )
                                    if self.log_store is not None:
                                        self.log_store.append("live_orders", payload)
                        if not recovered:
                            cooldown_seconds = self._cooldown_seconds_for_error_code(error_code)
                            if error_code in {"40762", "45111", "45110", "40774", "400172"}:
                                # Prevent immediate re-submission of the same failing live intent fingerprint.
                                self.last_executed_fingerprint_by_symbol[executable_decision.symbol] = fingerprint
                            if error_code == "40762" and executable_decision.final_mode == "futures":
                                self._tighten_futures_notional_scale(symbol=executable_decision.symbol)
                            if cooldown_seconds > 0:
                                self.live_error_cooldown_until_by_symbol[executable_decision.symbol] = (
                                    timestamp + timedelta(seconds=cooldown_seconds)
                                )
                                if error_code is not None:
                                    self.live_error_code_by_symbol[executable_decision.symbol] = error_code
                            if error_code in {"45110", "45111", "429"} and cooldown_seconds > 0:
                                self.live_error_global_cooldown_until = timestamp + timedelta(seconds=cooldown_seconds)
                                self.live_error_global_code = error_code
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
                            self.live_error_cooldown_until_by_symbol.pop(executable_decision.symbol, None)
                            self.live_error_code_by_symbol.pop(executable_decision.symbol, None)
                            self.live_error_global_cooldown_until = None
                            self.live_error_global_code = None
                            self.last_executed_fingerprint_by_symbol[executable_decision.symbol] = fingerprint
                            if live_result.accepted:
                                self._consume_capital_after_live_order(executable_decision)
                                if executable_decision.final_mode == "futures":
                                    self._relax_futures_notional_scale(symbol=executable_decision.symbol)
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
        if self.order_tester is not None and state is not None and self._market_capital_allowed(market_supported_decision):
            test_decision = self._cap_live_order_decision(market_supported_decision)
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
