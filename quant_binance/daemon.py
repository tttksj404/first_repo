from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from quant_binance.bootstrap import initialize_workspace
from quant_binance.data.combined_ws import CombinedWebSocketClient
from quant_binance.data.futures_stream import build_futures_streams
from quant_binance.data.rest_seed import seed_market_store_from_rest
from quant_binance.data.spot_stream import build_spot_streams
from quant_binance.data.bitget_ws import BitgetWebSocketClient
from quant_binance.data.bitget_ws import BITGET_MAX_CHANNELS_PER_CONNECTION
from quant_binance.cost_calibration import load_cost_calibration, refresh_bitget_cost_calibration
from quant_binance.exchange import resolve_exchange_id
from quant_binance.data.binance_ws import BinanceWebSocketClient
from quant_binance.execution.client_factory import build_exchange_rest_client
from quant_binance.execution.live_order_adapter import DecisionLiveOrderAdapter
from quant_binance.execution.order_test_adapter import DecisionOrderTestAdapter
from quant_binance.execution.router import ExecutionRouter
from quant_binance.features.extractor import MarketFeatureExtractor
from quant_binance.learning import OnlineEdgeLearner
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.observability.log_store import JsonlLogStore
from quant_binance.observability.report import build_runtime_summary, write_runtime_summary
from quant_binance.observability.runtime_snapshot import load_latest_runtime_payloads
from quant_binance.observability.runtime_state import write_runtime_state
from quant_binance.paths import prepare_run_paths
from quant_binance.session import BackoffPolicy, LivePaperSession, LivePaperShell
from quant_binance.service import PaperTradingService
from quant_binance.self_healing import RuntimeSelfHealing
from quant_binance.settings import Settings
from quant_binance.risk.capital import build_capital_adequacy_report, extract_account_capital_inputs
from quant_binance.strategy.regime import observe_only_reasons
from quant_binance.strategy.scorer import apply_score_and_costs
from quant_binance.overlays import apply_altcoin_overlay, apply_macro_overlay, apply_sentiment_overlay, load_altcoin_inputs, load_macro_inputs
from quant_binance.features.primitive import build_feature_vector_from_primitives


def _next_decision_boundary(timestamp, interval_minutes: int):
    floored = timestamp.replace(
        minute=(timestamp.minute // interval_minutes) * interval_minutes,
        second=0,
        microsecond=0,
    )
    if floored < timestamp:
        from datetime import timedelta

        return floored + timedelta(minutes=interval_minutes)
    return floored


def _decision_interval_label(interval_minutes: int) -> str:
    if interval_minutes % (24 * 60) == 0:
        return f"{interval_minutes // (24 * 60)}d"
    if interval_minutes % 60 == 0:
        return f"{interval_minutes // 60}h"
    return f"{interval_minutes}m"


def _normalized_closed_decision_time(timestamp: datetime) -> datetime:
    if timestamp.second == 0 and timestamp.microsecond == 0:
        return timestamp
    return timestamp + timedelta(milliseconds=1)


def _bootstrap_decision_time(*, store, interval_minutes: int):
    interval_label = _decision_interval_label(interval_minutes)
    latest_closed = None
    for state in getattr(store, "_states", {}).values():
        klines = state.klines.get(interval_label, ())
        if not klines:
            continue
        close_time = _normalized_closed_decision_time(klines[-1].close_time)
        if latest_closed is None or close_time > latest_closed:
            latest_closed = close_time
    if latest_closed is not None:
        aligned = latest_closed.replace(second=0, microsecond=0)
        if (
            latest_closed.second == 0
            and latest_closed.microsecond == 0
            and latest_closed.minute % interval_minutes == 0
        ):
            return latest_closed
        return _next_decision_boundary(aligned, interval_minutes)
    return _next_decision_boundary(
        next(iter(store._states.values())).last_update_time,
        interval_minutes,
    )


def _build_live_ws_client(
    *,
    exchange_id: str,
    symbols: tuple[str, ...],
    allow_insecure_ssl: bool,
) -> CombinedWebSocketClient:
    if exchange_id == "bitget":
        def _chunk_symbols(symbols_in: tuple[str, ...], *, streams_per_symbol: int) -> list[tuple[str, ...]]:
            max_symbols = max(1, BITGET_MAX_CHANNELS_PER_CONNECTION // max(streams_per_symbol, 1))
            return [
                tuple(symbols_in[index : index + max_symbols])
                for index in range(0, len(symbols_in), max_symbols)
            ]

        clients: list[BitgetWebSocketClient] = []
        for chunk in _chunk_symbols(symbols, streams_per_symbol=6):
            clients.append(
                BitgetWebSocketClient(
                    market="spot",
                    symbols=chunk,
                    intervals=("1m", "5m", "1h", "4h"),
                    allow_insecure_ssl=allow_insecure_ssl,
                    label=f"spot-{chunk[0].lower()}",
                )
            )
        for chunk in _chunk_symbols(symbols, streams_per_symbol=3):
            clients.append(
                BitgetWebSocketClient(
                    market="futures",
                    symbols=chunk,
                    intervals=("5m",),
                    allow_insecure_ssl=allow_insecure_ssl,
                    label=f"futures-{chunk[0].lower()}",
                )
            )
        return CombinedWebSocketClient(
            clients
        )
    spot_streams = []
    futures_streams = []
    for symbol in symbols:
        spot_streams.extend(build_spot_streams(symbol, ("1m", "5m", "1h", "4h")))
        futures_streams.extend(build_futures_streams(symbol, ("5m",)))
        futures_streams.append(f"{symbol.lower()}@openInterest")
    return CombinedWebSocketClient(
        [
            BinanceWebSocketClient(
                market="spot",
                streams=spot_streams,
                allow_insecure_ssl=allow_insecure_ssl,
                label="spot",
            ),
            BinanceWebSocketClient(
                market="futures",
                streams=futures_streams,
                allow_insecure_ssl=allow_insecure_ssl,
                label="futures",
            ),
        ]
    )


def _stateful_runtime_symbols(
    *,
    configured_symbols: tuple[str, ...],
    store,
) -> tuple[str, ...]:
    return tuple(symbol for symbol in configured_symbols if store.get(symbol) is not None)


def run_live_paper_daemon(
    *,
    config_path: str | Path,
    output_base_dir: str | Path,
    allow_insecure_ssl: bool = False,
    max_retries: int = 3,
    execute_live_orders: bool = False,
    exchange: str | None = None,
    sync_interval_seconds: int = 60,
) -> dict[str, object]:
    exchange_id = resolve_exchange_id(exchange)
    settings = Settings.load(config_path)
    initialize_workspace(output_base_dir)
    cost_calibration_path = Path(output_base_dir) / "artifacts" / "cost_calibration.json"
    run_paths = prepare_run_paths(base_dir=Path(output_base_dir) / "output", mode="paper-live-shell")
    try:
        rest_client = build_exchange_rest_client(
            exchange=exchange_id,
            allow_insecure_ssl=allow_insecure_ssl,
            allow_missing_credentials=exchange_id == "bitget" and not execute_live_orders,
        )
        supports_private_reads = bool(getattr(rest_client, "supports_private_reads", True))
        if execute_live_orders and not supports_private_reads:
            raise RuntimeError(
                "Bitget live order daemon requires BITGET_API_KEY, BITGET_API_SECRET, and BITGET_API_PASSPHRASE"
            )
        if supports_private_reads:
            def _build_capital_report():
                spot_account = rest_client.get_account(market="spot")
                futures_account = rest_client.get_account(market="futures")
                capital_inputs = extract_account_capital_inputs(
                    spot_account=spot_account,
                    futures_account=futures_account,
                    rest_client=rest_client,
                )
                return build_capital_adequacy_report(
                    spot_available_balance_usd=capital_inputs.spot_available_balance_usd,
                    spot_recognized_balance_usd=capital_inputs.spot_recognized_balance_usd,
                    spot_funding_assets=capital_inputs.spot_funding_assets,
                    futures_available_balance_usd=capital_inputs.futures_available_balance_usd,
                    futures_execution_balance_usd=capital_inputs.futures_execution_balance_usd,
                    futures_recognized_balance_usd=capital_inputs.futures_recognized_balance_usd,
                    futures_funding_assets=capital_inputs.futures_funding_assets,
                    settings=settings,
                    rest_client=rest_client,
                )

            rest_client.build_capital_report = _build_capital_report  # type: ignore[attr-defined]
            try:
                refresh_bitget_cost_calibration(
                    rest_client=rest_client,
                    base_dir=output_base_dir,
                    output_path=cost_calibration_path,
                )
            except Exception:
                pass
        store = seed_market_store_from_rest(
            client=rest_client,
            symbols=settings.universe,
            intervals=("1m", "5m", "1h", "4h"),
        )
        runtime_symbols = _stateful_runtime_symbols(
            configured_symbols=settings.universe,
            store=store,
        )
        if not runtime_symbols:
            raise RuntimeError("no seeded market states available for the configured live runtime universe")
        learner = OnlineEdgeLearner(
            min_observations=max(20, settings.feature_thresholds.min_expected_edge_observations)
        )
        extractor = MarketFeatureExtractor(
            settings,
            edge_lookup=learner.lookup,
            cost_calibration=load_cost_calibration(cost_calibration_path),
        )
        macro_inputs = load_macro_inputs()
        altcoin_inputs = load_altcoin_inputs()
        observe_only_symbols: list[str] = []
        eligible_symbols: set[str] = set()
        for symbol in runtime_symbols:
            state = store.get(symbol)
            if state is None:
                continue
            history = extractor.build_history_context(state)
            primitives = extractor.build_primitive_inputs(state)
            features = build_feature_vector_from_primitives(
                inputs=primitives,
                history=history,
                settings=settings,
            )
            features = extractor.enrich_feature_vector(state=state, features=features)
            features = apply_macro_overlay(features, macro_inputs)
            features = apply_altcoin_overlay(features, symbol=symbol, altcoin_inputs=altcoin_inputs)
            features = apply_sentiment_overlay(features)
            spot_features = apply_score_and_costs(features, settings, "spot")
            if observe_only_reasons(spot_features, settings, symbol):
                observe_only_symbols.append(symbol)
            else:
                eligible_symbols.add(symbol)
        dispatcher = EventDispatcher(store)
        runtime = LivePaperRuntime(
            dispatcher=dispatcher,
            paper_service=PaperTradingService(settings, router=ExecutionRouter(), feature_extractor=extractor),
            primitive_builder=lambda symbol, decision_time: extractor.build_primitive_inputs(store.get(symbol)),  # type: ignore[arg-type]
            history_provider=lambda symbol, decision_time: extractor.build_history_context(store.get(symbol)),  # type: ignore[arg-type]
            decision_interval_minutes=settings.decision_engine.decision_interval_minutes,
            eligible_symbols=eligible_symbols,
        )
        log_store = JsonlLogStore(
            run_paths.root / "logs",
            max_bytes_per_stream=settings.housekeeping.max_log_bytes_per_stream if settings.housekeeping.enabled else None,
        )
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            sync_interval_seconds=sync_interval_seconds,
            flush_interval_seconds=min(sync_interval_seconds, 15),
            rest_client=rest_client if supports_private_reads else None,
            order_tester=DecisionOrderTestAdapter(rest_client),
            live_order_executor=DecisionLiveOrderAdapter(rest_client, settings) if execute_live_orders else None,
            learner=learner,
            learner_output_path=run_paths.root / "edge_table.json",
            log_store=log_store,
            verbose=True,
            observe_only_symbols=sorted(observe_only_symbols),
        )
        session.self_healing.log_store = log_store
        session.self_healing.stall_timeout_seconds = RuntimeSelfHealing.recommended_stall_timeout_seconds(
            sync_interval_seconds=sync_interval_seconds,
            decision_interval_minutes=settings.decision_engine.decision_interval_minutes,
            stale_data_alarm_sla_seconds=settings.operational_limits.stale_data_alarm_sla_seconds,
        )
        if supports_private_reads:
            session.sync_account()
            previous_state, previous_summary = load_latest_runtime_payloads(output_base_dir)
            session.restore_futures_state_from_runtime(
                state_payload=previous_state,
                summary_payload=previous_summary,
            )
        bootstrap_time = _bootstrap_decision_time(
            store=store,
            interval_minutes=settings.decision_engine.decision_interval_minutes,
        )
        for symbol in runtime_symbols:
            if symbol not in eligible_symbols:
                continue
            state = store.get(symbol)
            if state is None:
                continue
            bootstrap_state = state
            if state.last_update_time > bootstrap_time:
                bootstrap_state = replace(
                    state,
                    last_update_time=bootstrap_time,
                    top_of_book=replace(state.top_of_book, updated_at=bootstrap_time),
                )
            primitive_inputs = extractor.build_primitive_inputs(state)
            history = extractor.build_history_context(state)
            session.run_bootstrap_cycle(
                state=bootstrap_state,
                primitive_inputs=primitive_inputs,
                history=history,
                decision_time=bootstrap_time,
            )
        session.minimum_live_decision_timestamp = bootstrap_time
        session.flush(
            summary_path=run_paths.summary_path,
            state_path=run_paths.state_path,
        )
        if settings.housekeeping.enabled:
            from quant_binance.housekeeping import prune_old_run_directories

            prune_old_run_directories(
                mode_root=Path(output_base_dir) / "output" / "paper-live-shell",
                keep_recent_runs=settings.housekeeping.keep_recent_runs,
            )
        shell = LivePaperShell(
            ws_client_factory=lambda: _build_live_ws_client(
                exchange_id=exchange_id,
                symbols=runtime_symbols,
                allow_insecure_ssl=allow_insecure_ssl,
            ),
            session=session,
            backoff_policy=BackoffPolicy(max_attempts=max_retries),
            summary_path=run_paths.summary_path,
            state_path=run_paths.state_path,
        )
        summary = asyncio.run(shell.run()) or {}
        if "self_healing" not in summary:
            mismatch_active, mismatch_details = session._self_healing_mismatch_snapshot()  # type: ignore[attr-defined]
            summary["self_healing"] = session.self_healing.snapshot(
                now=datetime.now(tz=timezone.utc),
                order_error_cooldowns=session.order_error_cooldowns,
                manual_symbol_cooldowns=session.manual_symbol_cooldowns,
                mismatch_active=mismatch_active,
                mismatch_details=mismatch_details,
            )
        return {"run_paths": run_paths, "summary": summary}
    except Exception as exc:
        failure_event = {
            "category": "startup_failure",
            "action": "report_only",
            "status": "active",
            "summary": str(exc),
        }
        failure_self_healing = {
            "status": "startup_failed",
            "active_guards": {},
            "issue_counts": {"startup_failure": 1},
            "recent_events": [failure_event],
            "recovery_counts": {},
        }
        failure_summary = build_runtime_summary(
            decisions=[],
            self_healing=failure_self_healing,
        )
        failure_summary.update(
            {
                "status": "startup_failed",
                "error": repr(exc),
                "exchange": exchange_id,
                "execute_live_orders": execute_live_orders,
            }
        )
        write_runtime_summary(run_paths.summary_path, failure_summary)
        write_runtime_state(
            run_paths.state_path,
            {
                "status": "startup_failed",
                "error": repr(exc),
                "decision_count": 0,
                "tested_order_count": 0,
                "live_order_count": 0,
                "heartbeat_count": 0,
                "last_event_timestamp": None,
                "last_decision_timestamp": None,
                "live_decision_loop": {},
                "capital_report": {},
                "open_spot_position_count": 0,
                "open_futures_position_count": 0,
                "paper_open_futures_position_count": 0,
                "paper_open_futures_positions": [],
                "exchange_live_futures_position_count": 0,
                "exchange_live_futures_positions": [],
                "futures_position_mismatch": False,
                "futures_position_mismatch_details": {"missing_in_paper": [], "missing_on_exchange": []},
                "futures_missing_in_paper_counts": {},
                "futures_missing_on_exchange_counts": {},
                "self_healing": failure_self_healing,
                "closed_trade_count": 0,
                "kill_switch": {"armed": False, "reasons": []},
            },
        )
        raise
