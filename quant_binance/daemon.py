from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from quant_binance.bootstrap import initialize_workspace
from quant_binance.data.combined_ws import CombinedWebSocketClient
from quant_binance.data.futures_stream import build_futures_streams
from quant_binance.data.rest_seed import seed_market_store_from_rest
from quant_binance.data.spot_stream import build_spot_streams
from quant_binance.data.bitget_ws import BitgetWebSocketClient
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
from quant_binance.paths import prepare_run_paths
from quant_binance.session import BackoffPolicy, LivePaperSession, LivePaperShell
from quant_binance.service import PaperTradingService
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


def _build_live_ws_client(
    *,
    exchange_id: str,
    symbols: tuple[str, ...],
    allow_insecure_ssl: bool,
) -> CombinedWebSocketClient:
    if exchange_id == "bitget":
        return CombinedWebSocketClient(
            [
                BitgetWebSocketClient(
                    market="spot",
                    symbols=symbols,
                    intervals=("5m", "1h", "4h"),
                    allow_insecure_ssl=allow_insecure_ssl,
                    label="spot",
                ),
                BitgetWebSocketClient(
                    market="futures",
                    symbols=symbols,
                    intervals=("5m",),
                    allow_insecure_ssl=allow_insecure_ssl,
                    label="futures",
                ),
            ]
        )
    spot_streams = []
    futures_streams = []
    for symbol in symbols:
        spot_streams.extend(build_spot_streams(symbol, ("5m", "1h", "4h")))
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
    if settings.housekeeping.enabled:
        from quant_binance.housekeeping import prune_old_run_directories

        prune_old_run_directories(
            mode_root=Path(output_base_dir) / "output" / "paper-live-shell",
            keep_recent_runs=settings.housekeeping.keep_recent_runs,
        )
    run_paths = prepare_run_paths(base_dir=Path(output_base_dir) / "output", mode="paper-live-shell")
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
                futures_available_balance_usd=capital_inputs.futures_execution_balance_usd,
                futures_recognized_balance_usd=capital_inputs.futures_recognized_balance_usd,
                settings=settings,
                rest_client=rest_client,
            )

        rest_client.build_capital_report = _build_capital_report  # type: ignore[attr-defined]
    store = seed_market_store_from_rest(
        client=rest_client,
        symbols=settings.universe,
        intervals=("5m", "1h", "4h"),
    )
    learner = OnlineEdgeLearner(
        min_observations=max(20, settings.feature_thresholds.min_expected_edge_observations)
    )
    extractor = MarketFeatureExtractor(settings, edge_lookup=learner.lookup)
    macro_inputs = load_macro_inputs()
    altcoin_inputs = load_altcoin_inputs()
    observe_only_symbols: list[str] = []
    eligible_symbols: set[str] = set()
    for symbol in settings.universe:
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
        paper_service=PaperTradingService(settings, router=ExecutionRouter()),
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
        rest_client=rest_client if supports_private_reads else None,
        order_tester=DecisionOrderTestAdapter(rest_client),
        live_order_executor=DecisionLiveOrderAdapter(rest_client, settings) if execute_live_orders else None,
        learner=learner,
        learner_output_path=run_paths.root / "edge_table.json",
        log_store=log_store,
        verbose=True,
        observe_only_symbols=sorted(observe_only_symbols),
    )
    if supports_private_reads:
        session.sync_account()
    bootstrap_time = _next_decision_boundary(
        next(iter(store._states.values())).last_update_time,
        settings.decision_engine.decision_interval_minutes,
    )
    for symbol in settings.universe:
        if symbol not in eligible_symbols:
            continue
        state = store.get(symbol)
        if state is None:
            continue
        primitive_inputs = extractor.build_primitive_inputs(state)
        history = extractor.build_history_context(state)
        session.run_bootstrap_cycle(
            state=state,
            primitive_inputs=primitive_inputs,
            history=history,
            decision_time=bootstrap_time,
        )
    session.flush(
        summary_path=run_paths.summary_path,
        state_path=run_paths.state_path,
    )
    shell = LivePaperShell(
        ws_client_factory=lambda: _build_live_ws_client(
            exchange_id=exchange_id,
            symbols=settings.universe,
            allow_insecure_ssl=allow_insecure_ssl,
        ),
        session=session,
        backoff_policy=BackoffPolicy(max_attempts=max_retries),
        summary_path=run_paths.summary_path,
        state_path=run_paths.state_path,
    )
    summary = asyncio.run(shell.run()) or {}
    return {"run_paths": run_paths, "summary": summary}
