from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from quant_binance.backtest.fixtures import load_snapshot_fixture
from quant_binance.backtest.paper_live_fixtures import load_paper_live_cycles
from quant_binance.backtest.replay import run_replay
from quant_binance.daemon import run_live_paper_daemon
from quant_binance.exchange import resolve_exchange_id, runtime_readiness
from quant_binance.execution.client_factory import build_exchange_rest_client
from quant_binance.execution.order_test_adapter import DecisionOrderTestAdapter
from quant_binance.execution.router import ExecutionRouter
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.observability.report import build_runtime_summary, write_runtime_summary
from quant_binance.observability.runtime_state import write_runtime_state
from quant_binance.risk.kill_switch import KillSwitch
from quant_binance.service import PaperTradingService
from quant_binance.session import BackoffPolicy, LivePaperSession, LivePaperShell
from quant_binance.settings import Settings


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bitget-first quant runtime entrypoint")
    parser.add_argument(
        "--mode",
        choices=("replay", "paper-live", "paper-live-test-order", "paper-live-shell", "live-paper-daemon", "live-auto-trade-daemon", "env-check"),
        required=True,
    )
    parser.add_argument("--config", default="quant_binance/config.example.json")
    parser.add_argument("--fixture", default="")
    parser.add_argument("--equity-usd", type=float, default=10000.0)
    parser.add_argument("--capacity-usd", type=float, default=5000.0)
    parser.add_argument("--output", default="")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--insecure-ssl", action="store_true")
    parser.add_argument("--output-base", default="quant_runtime")
    parser.add_argument("--ack-live-risk", default="")
    parser.add_argument("--exchange", default="")
    return parser


def run_replay_mode(*, config_path: str | Path, fixture_path: str | Path, equity_usd: float, capacity_usd: float) -> dict[str, object]:
    settings = Settings.load(config_path)
    snapshots = load_snapshot_fixture(fixture_path)
    result = run_replay(
        snapshots=snapshots,
        settings=settings,
        equity_usd=equity_usd,
        remaining_portfolio_capacity_usd=capacity_usd,
        router=ExecutionRouter(),
    )
    return {
        "decision_count": len(result.decisions),
        "order_count": result.order_count,
        "modes": [decision.final_mode for decision in result.decisions],
    }


def run_paper_live_mode(
    *,
    config_path: str | Path,
    fixture_path: str | Path,
    equity_usd: float,
    capacity_usd: float,
) -> dict[str, object]:
    settings = Settings.load(config_path)
    cycles = load_paper_live_cycles(fixture_path)
    service = PaperTradingService(settings, router=ExecutionRouter())
    decisions = [
        service.run_cycle(
            state=cycle.state,
            primitive_inputs=cycle.primitive_inputs,
            history=cycle.history,
            decision_time=cycle.decision_time,
            equity_usd=equity_usd,
            remaining_portfolio_capacity_usd=capacity_usd,
        )
        for cycle in cycles
    ]
    return {
        "cycle_count": len(cycles),
        "decision_count": len(decisions),
        "modes": [decision.final_mode for decision in decisions],
    }


def run_paper_live_test_order_mode(
    *,
    config_path: str | Path,
    fixture_path: str | Path,
    equity_usd: float,
    capacity_usd: float,
    client=None,
    allow_insecure_ssl: bool = False,
    exchange: str | None = None,
) -> dict[str, object]:
    settings = Settings.load(config_path)
    cycles = load_paper_live_cycles(fixture_path)
    service = PaperTradingService(settings, router=ExecutionRouter())
    exchange_id = resolve_exchange_id(exchange)
    rest_client = client or build_exchange_rest_client(
        exchange=exchange_id,
        allow_insecure_ssl=allow_insecure_ssl,
        allow_missing_credentials=exchange_id == "bitget",
    )
    adapter = DecisionOrderTestAdapter(rest_client)
    tested_orders: list[dict[str, object]] = []
    decisions = []
    for cycle in cycles:
        decision = service.run_cycle(
            state=cycle.state,
            primitive_inputs=cycle.primitive_inputs,
            history=cycle.history,
            decision_time=cycle.decision_time,
            equity_usd=equity_usd,
            remaining_portfolio_capacity_usd=capacity_usd,
        )
        decisions.append(decision)
        result = adapter.test_decision(
            decision=decision,
            reference_price=cycle.state.last_trade_price,
        )
        if result is not None:
            tested_orders.append(
                {
                    "symbol": result.symbol,
                    "market": result.market,
                    "side": result.side,
                    "quantity": result.quantity,
                    "accepted": result.accepted,
                }
            )
    supports_private_reads = bool(getattr(rest_client, "supports_private_reads", True))
    account_snapshot = {}
    open_orders_snapshot = {}
    if supports_private_reads and hasattr(rest_client, "get_account"):
        account_snapshot = rest_client.get_account(market="futures")
    if supports_private_reads and hasattr(rest_client, "get_open_orders"):
        open_orders_snapshot = rest_client.get_open_orders(market="futures")
    kill_switch = KillSwitch()
    summary = build_runtime_summary(
        decisions=decisions,
        tested_orders=tested_orders,
        account_snapshot=account_snapshot,
        open_orders_snapshot=open_orders_snapshot,
        kill_switch_status=kill_switch.status(),
    )
    summary["cycle_count"] = len(cycles)
    summary["exchange"] = exchange_id
    return summary


class FixturePayloadWebSocketClient:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = payloads

    async def run(self, handler) -> None:  # type: ignore[no-untyped-def]
        for payload in self.payloads:
            await handler(payload)


def run_paper_live_shell_mode(
    *,
    config_path: str | Path,
    fixture_path: str | Path,
    equity_usd: float,
    capacity_usd: float,
    output_path: str | Path | None = None,
    max_retries: int = 3,
) -> dict[str, object]:
    settings = Settings.load(config_path)
    cycles = load_paper_live_cycles(fixture_path)
    by_key = {
        (cycle.symbol, cycle.decision_time.isoformat()): cycle
        for cycle in cycles
    }
    store = __import__("quant_binance.data.market_store", fromlist=["MarketStateStore"]).MarketStateStore()
    for cycle in cycles:
        if store.get(cycle.symbol) is None:
            store.put(cycle.state)
    dispatcher_mod = __import__("quant_binance.live", fromlist=["EventDispatcher", "LivePaperRuntime"])
    dispatcher = dispatcher_mod.EventDispatcher(store)
    paper_service = PaperTradingService(settings, router=ExecutionRouter())
    runtime = dispatcher_mod.LivePaperRuntime(
        dispatcher=dispatcher,
        paper_service=paper_service,
        primitive_builder=lambda symbol, decision_time: by_key[(symbol, decision_time.isoformat())].primitive_inputs,
        history_provider=lambda symbol, decision_time: by_key[(symbol, decision_time.isoformat())].history,
        decision_interval_minutes=settings.decision_engine.decision_interval_minutes,
    )
    payloads: list[dict[str, object]] = []
    for cycle in cycles:
        decision_time_ms = int(cycle.decision_time.timestamp() * 1000)
        payloads.append(
            {
                "stream": f"{cycle.symbol.lower()}@kline_5m",
                "data": {
                    "s": cycle.symbol,
                    "k": {
                        "i": "5m",
                        "t": decision_time_ms - 300000,
                        "T": decision_time_ms,
                        "o": str(cycle.state.last_trade_price),
                        "h": str(cycle.state.last_trade_price),
                        "l": str(cycle.state.last_trade_price),
                        "c": str(cycle.state.last_trade_price),
                        "v": "0",
                        "q": "0",
                        "x": True,
                    },
                },
            }
        )
    session = LivePaperSession(
        runtime=runtime,
        equity_usd=equity_usd,
        remaining_portfolio_capacity_usd=capacity_usd,
    )
    summary_path = Path(output_path) if output_path else None
    state_path = summary_path.with_suffix(".state.json") if summary_path else None
    shell = LivePaperShell(
        ws_client_factory=lambda: FixturePayloadWebSocketClient(payloads),
        session=session,
        backoff_policy=BackoffPolicy(max_attempts=max_retries, initial_delay_seconds=0.0, max_delay_seconds=0.0),
        summary_path=summary_path,
        state_path=state_path,
    )
    summary = asyncio.run(shell.run()) or build_runtime_summary(decisions=session.decisions)
    summary["cycle_count"] = len(cycles)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.mode == "replay":
        if not args.fixture:
            parser.error("--fixture is required for replay mode")
        summary = run_replay_mode(
            config_path=args.config,
            fixture_path=args.fixture,
            equity_usd=args.equity_usd,
            capacity_usd=args.capacity_usd,
        )
        if args.output:
            write_runtime_summary(args.output, summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.mode == "paper-live":
        if not args.fixture:
            parser.error("--fixture is required for paper-live mode")
        summary = run_paper_live_mode(
            config_path=args.config,
            fixture_path=args.fixture,
            equity_usd=args.equity_usd,
            capacity_usd=args.capacity_usd,
        )
        if args.output:
            write_runtime_summary(args.output, summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.mode == "paper-live-test-order":
        if not args.fixture:
            parser.error("--fixture is required for paper-live-test-order mode")
        summary = run_paper_live_test_order_mode(
            config_path=args.config,
            fixture_path=args.fixture,
            equity_usd=args.equity_usd,
            capacity_usd=args.capacity_usd,
            allow_insecure_ssl=args.insecure_ssl,
            exchange=args.exchange or None,
        )
        if args.output:
            write_runtime_summary(args.output, summary)
            write_runtime_state(
                Path(args.output).with_suffix(".state.json"),
                {
                    "mode": "paper-live-test-order",
                    "decision_count": summary["decision_count"],
                    "tested_order_count": summary["tested_order_count"],
                },
            )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.mode == "paper-live-shell":
        if not args.fixture:
            parser.error("--fixture is required for paper-live-shell mode")
        summary = run_paper_live_shell_mode(
            config_path=args.config,
            fixture_path=args.fixture,
            equity_usd=args.equity_usd,
            capacity_usd=args.capacity_usd,
            output_path=args.output or None,
            max_retries=args.max_retries,
        )
        if args.output:
            write_runtime_summary(args.output, summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.mode == "live-paper-daemon":
        result = run_live_paper_daemon(
            config_path=args.config,
            output_base_dir=args.output_base,
            allow_insecure_ssl=args.insecure_ssl,
            max_retries=args.max_retries,
            execute_live_orders=False,
            exchange=args.exchange or None,
        )
        print(
            json.dumps(
                {
                    "summary": result["summary"],
                    "run_root": str(result["run_paths"].root),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.mode == "live-auto-trade-daemon":
        if args.ack_live_risk != "I_UNDERSTAND_LIVE_TRADING":
            parser.error("--ack-live-risk I_UNDERSTAND_LIVE_TRADING is required for live-auto-trade-daemon")
        result = run_live_paper_daemon(
            config_path=args.config,
            output_base_dir=args.output_base,
            allow_insecure_ssl=args.insecure_ssl,
            max_retries=args.max_retries,
            execute_live_orders=True,
            exchange=args.exchange or None,
        )
        print(
            json.dumps(
                {
                    "summary": result["summary"],
                    "run_root": str(result["run_paths"].root),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.mode == "env-check":
        readiness = runtime_readiness(args.exchange or None)
        print(
            json.dumps(
                {
                    "exchange": readiness.exchange_id,
                    "has_api_key": readiness.has_api_key,
                    "has_api_secret": readiness.has_api_secret,
                    "has_api_passphrase": readiness.has_api_passphrase,
                    "is_ready": readiness.is_ready,
                    "required_env_vars": list(readiness.required_env_vars),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    parser.error(f"unsupported mode: {args.mode}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
