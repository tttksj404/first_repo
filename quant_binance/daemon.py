from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from quant_binance.bootstrap import initialize_workspace
from quant_binance.data.bitget_polling_ws import BitgetPollingWebSocketClient
from quant_binance.data.combined_ws import CombinedWebSocketClient
from quant_binance.data.futures_stream import build_futures_streams
from quant_binance.data.rest_seed import seed_market_store_from_rest
from quant_binance.data.spot_stream import build_spot_streams
from quant_binance.data.binance_ws import BinanceWebSocketClient
from quant_binance.execution.client_factory import build_exchange_rest_client
from quant_binance.execution.live_order_adapter import DecisionLiveOrderAdapter
from quant_binance.execution.order_test_adapter import DecisionOrderTestAdapter
from quant_binance.execution.router import ExecutionRouter
from quant_binance.features.extractor import MarketFeatureExtractor
from quant_binance.features.primitive import build_feature_vector_from_primitives
from quant_binance.learning import OnlineEdgeLearner
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.observability.log_store import JsonlLogStore
from quant_binance.paths import prepare_run_paths
from quant_binance.session import BackoffPolicy, LivePaperSession, LivePaperShell
from quant_binance.service import PaperTradingService
from quant_binance.settings import Settings
from quant_binance.risk.capital import build_capital_adequacy_report
from quant_binance.strategy.regime import observe_only_reasons
from quant_binance.strategy.scorer import apply_score_and_costs
from quant_binance.strategy_profile_switch import AutoProfileSwitchPolicy, AutoProfileSwitcher
from quant_binance.exchange import resolve_exchange_id
from quant_binance.overlays import apply_altcoin_overlay, apply_macro_overlay, apply_sentiment_overlay, load_altcoin_inputs, load_macro_inputs


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


def _interval_label(interval_minutes: int) -> str:
    if interval_minutes % (24 * 60) == 0:
        return f"{interval_minutes // (24 * 60)}d"
    if interval_minutes % 60 == 0:
        return f"{interval_minutes // 60}h"
    return f"{interval_minutes}m"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _resolve_symbol_eligibility(
    *,
    settings: Settings,
    extractor: MarketFeatureExtractor,
    store: Any,
    macro_inputs: Any,
    altcoin_inputs: Any,
) -> tuple[list[str], set[str]]:
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
    return observe_only_symbols, eligible_symbols


def _build_auto_profile_switcher(
    *,
    config_path: str | Path,
    settings: Settings,
) -> AutoProfileSwitcher | None:
    if not _env_bool("AUTO_STRATEGY_SWITCH", default=False):
        return None
    policy = AutoProfileSwitchPolicy(
        calm_profile=os.environ.get("AUTO_STRATEGY_CALM_PROFILE", "aggressive_alt").strip().lower(),
        fast_profile=os.environ.get("AUTO_STRATEGY_FAST_PROFILE", "scalp_ultra").strip().lower(),
        min_hold_cycles=max(_env_int("AUTO_STRATEGY_MIN_HOLD_CYCLES", 3), 0),
        fast_on_volatility_penalty=_env_float("AUTO_STRATEGY_FAST_ON_VOLATILITY_PENALTY", 0.62),
        fast_off_volatility_penalty=_env_float("AUTO_STRATEGY_FAST_OFF_VOLATILITY_PENALTY", 0.48),
        fast_on_abs_ret_1h=_env_float("AUTO_STRATEGY_FAST_ON_ABS_RET_1H", 0.018),
        fast_off_abs_ret_1h=_env_float("AUTO_STRATEGY_FAST_OFF_ABS_RET_1H", 0.010),
    )
    return AutoProfileSwitcher(
        config_path=config_path,
        policy=policy,
        runtime_decision_interval_minutes=settings.decision_engine.decision_interval_minutes,
        initial_profile=settings.strategy_profile,
    )


def run_live_paper_daemon(
    *,
    config_path: str | Path,
    output_base_dir: str | Path,
    allow_insecure_ssl: bool = False,
    max_retries: int = 3,
    execute_live_orders: bool = False,
    exchange: str | None = None,
) -> dict[str, object]:
    exchange_id = resolve_exchange_id(exchange)
    settings = Settings.load(config_path)
    auto_profile_switcher = _build_auto_profile_switcher(config_path=config_path, settings=settings)
    if auto_profile_switcher is not None:
        settings = auto_profile_switcher.active_settings
        print(
            f"[PROFILE_SWITCHER] enabled calm={auto_profile_switcher.policy.calm_profile} fast={auto_profile_switcher.policy.fast_profile} active={settings.strategy_profile}",
            flush=True,
        )
    runtime_decision_interval_minutes = settings.decision_engine.decision_interval_minutes
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
    )
    settings_ref: dict[str, Settings] = {"current": settings}
    rest_client.build_capital_report = lambda: build_capital_adequacy_report(  # type: ignore[attr-defined]
        spot_available_balance_usd=float(
            next(
                (
                    item.get("free", 0.0)
                    for item in rest_client.get_account(market="spot").get("balances", [])
                    if item.get("asset") == "USDT"
                ),
                0.0,
            )
        ),
        futures_available_balance_usd=float(
            rest_client.get_account(market="futures").get("availableBalance", 0.0)
        ),
        settings=settings_ref["current"],
        rest_client=rest_client,
    )
    store = seed_market_store_from_rest(
        client=rest_client,
        symbols=settings.universe,
        intervals=("5m", "1h", "4h"),
    )
    learner = OnlineEdgeLearner(
        min_observations=max(20, settings.feature_thresholds.min_expected_edge_observations)
    )
    paper_service = PaperTradingService(
        settings,
        router=ExecutionRouter(),
        edge_lookup=learner.lookup,
    )
    macro_inputs = load_macro_inputs()
    altcoin_inputs = load_altcoin_inputs()
    observe_only_symbols, eligible_symbols = _resolve_symbol_eligibility(
        settings=paper_service.settings,
        extractor=paper_service.feature_extractor,
        store=store,
        macro_inputs=macro_inputs,
        altcoin_inputs=altcoin_inputs,
    )
    decision_context_cache: dict[tuple[str, str], tuple[Any, Any]] = {}
    switch_cycle_seen: dict[str, None] = {}
    runtime_ref: list[LivePaperRuntime | None] = [None]
    session_ref: list[LivePaperSession | None] = [None]

    def _apply_profile_switch(*, switch_reason: str, switch_volatility_penalty: float, switch_abs_ret_1h: float) -> None:
        previous_profile = paper_service.settings.strategy_profile
        paper_service.apply_settings(auto_profile_switcher.active_settings)  # type: ignore[union-attr]
        settings_ref["current"] = paper_service.settings
        if session_ref[0] is not None and session_ref[0].live_order_executor is not None:
            session_ref[0].live_order_executor.settings = paper_service.settings
        refreshed_observe_only, refreshed_eligible = _resolve_symbol_eligibility(
            settings=paper_service.settings,
            extractor=paper_service.feature_extractor,
            store=store,
            macro_inputs=macro_inputs,
            altcoin_inputs=altcoin_inputs,
        )
        if runtime_ref[0] is not None:
            runtime_ref[0].eligible_symbols = refreshed_eligible
        if session_ref[0] is not None:
            session_ref[0].observe_only_symbols = sorted(refreshed_observe_only)
        print(
            "[PROFILE_SWITCH] "
            f"from={previous_profile} to={paper_service.settings.strategy_profile} "
            f"reason={switch_reason} vol_penalty={switch_volatility_penalty:.4f} "
            f"abs_ret_1h={switch_abs_ret_1h:.4f}",
            flush=True,
        )

    def _evaluate_switch_for_cycle(cycle_key: str) -> None:
        if auto_profile_switcher is None:
            return
        if cycle_key in switch_cycle_seen:
            return
        max_abs_ret_1h = 0.0
        max_volatility_penalty = 0.0
        for universe_symbol in paper_service.settings.universe:
            universe_state = store.get(universe_symbol)
            if universe_state is None:
                continue
            universe_primitive = paper_service.feature_extractor.build_primitive_inputs(universe_state)
            universe_history = paper_service.feature_extractor.build_history_context(universe_state)
            universe_features = build_feature_vector_from_primitives(
                inputs=universe_primitive,
                history=universe_history,
                settings=paper_service.settings,
            )
            max_abs_ret_1h = max(max_abs_ret_1h, abs(float(universe_primitive.ret_1h)))
            max_volatility_penalty = max(max_volatility_penalty, float(universe_features.volatility_penalty))
        switch_decision = auto_profile_switcher.evaluate_metrics(
            volatility_penalty=max_volatility_penalty,
            abs_ret_1h=max_abs_ret_1h,
            cycle_key=cycle_key,
        )
        switch_cycle_seen[cycle_key] = None
        if len(switch_cycle_seen) > 256:
            oldest_key = next(iter(switch_cycle_seen))
            switch_cycle_seen.pop(oldest_key, None)
        if switch_decision.changed:
            _apply_profile_switch(
                switch_reason=switch_decision.reason,
                switch_volatility_penalty=switch_decision.volatility_penalty,
                switch_abs_ret_1h=switch_decision.abs_ret_1h,
            )

    def _build_context_for_decision(symbol: str, decision_time: Any) -> tuple[Any, Any]:
        cycle_key = decision_time.isoformat()
        cache_key = (symbol, cycle_key)
        cached = decision_context_cache.get(cache_key)
        if cached is not None:
            return cached
        _evaluate_switch_for_cycle(cycle_key)
        state = store.get(symbol)
        if state is None:
            raise ValueError(f"missing market state for symbol: {symbol}")
        primitive_inputs = paper_service.feature_extractor.build_primitive_inputs(state)
        history = paper_service.feature_extractor.build_history_context(state)
        decision_context_cache[cache_key] = (primitive_inputs, history)
        return primitive_inputs, history

    def _primitive_builder(symbol: str, decision_time: Any) -> Any:
        return _build_context_for_decision(symbol, decision_time)[0]

    def _history_provider(symbol: str, decision_time: Any) -> Any:
        cache_key = (symbol, decision_time.isoformat())
        cached = decision_context_cache.pop(cache_key, None)
        if cached is None:
            cached = _build_context_for_decision(symbol, decision_time)
        return cached[1]

    dispatcher = EventDispatcher(store)
    runtime = LivePaperRuntime(
        dispatcher=dispatcher,
        paper_service=paper_service,
        primitive_builder=_primitive_builder,
        history_provider=_history_provider,
        decision_interval_minutes=runtime_decision_interval_minutes,
        eligible_symbols=eligible_symbols,
    )
    runtime_ref[0] = runtime
    log_store = JsonlLogStore(run_paths.root / "logs")
    session = LivePaperSession(
        runtime=runtime,
        equity_usd=10000.0,
        remaining_portfolio_capacity_usd=5000.0,
        rest_client=rest_client,
        order_tester=DecisionOrderTestAdapter(rest_client),
        live_order_executor=DecisionLiveOrderAdapter(rest_client, paper_service.settings) if execute_live_orders else None,
        learner=learner,
        learner_output_path=run_paths.root / "edge_table.json",
        log_store=log_store,
        verbose=True,
        observe_only_symbols=sorted(observe_only_symbols),
    )
    session_ref[0] = session
    session.sync_account()
    bootstrap_time = _next_decision_boundary(
        next(iter(store._states.values())).last_update_time,
        runtime_decision_interval_minutes,
    )
    for symbol in paper_service.settings.universe:
        if symbol not in eligible_symbols:
            continue
        state = store.get(symbol)
        if state is None:
            continue
        primitive_inputs = paper_service.feature_extractor.build_primitive_inputs(state)
        history = paper_service.feature_extractor.build_history_context(state)
        session.run_bootstrap_cycle(
            state=state,
            primitive_inputs=primitive_inputs,
            history=history,
            decision_time=bootstrap_time,
        )
    decision_interval_stream = _interval_label(runtime_decision_interval_minutes)
    spot_intervals = tuple(dict.fromkeys((decision_interval_stream, "5m", "1h", "4h")))
    futures_intervals = tuple(dict.fromkeys((decision_interval_stream, "5m")))
    spot_streams = []
    futures_streams = []
    for symbol in paper_service.settings.universe:
        spot_streams.extend(build_spot_streams(symbol, spot_intervals))
        futures_streams.extend(build_futures_streams(symbol, futures_intervals))
        futures_streams.append(f"{symbol.lower()}@openInterest")
    if exchange_id == "bitget":
        ws_client_factory = lambda: BitgetPollingWebSocketClient(
            rest_client=rest_client,
            symbols=paper_service.settings.universe,
            decision_interval_minutes=runtime_decision_interval_minutes,
        )
    else:
        ws_client_factory = lambda: CombinedWebSocketClient(
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
    shell = LivePaperShell(
        ws_client_factory=ws_client_factory,
        session=session,
        backoff_policy=BackoffPolicy(max_attempts=max_retries),
        summary_path=run_paths.summary_path,
        state_path=run_paths.state_path,
    )
    summary = asyncio.run(shell.run()) or {}
    return {"run_paths": run_paths, "summary": summary}
