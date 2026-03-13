from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from quant_binance.daemon import run_live_paper_daemon
from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.router import ExecutionRouter
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.observability.report import build_runtime_summary, write_runtime_summary
from quant_binance.observability.runtime_state import write_runtime_state
from quant_binance.service import PaperTradingService
from quant_binance.session import LivePaperSession
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class FakeRuntimeRestClient:
    def get_account(self, *, market: str) -> dict[str, object]:
        return {"market": market, "balance": 1000}

    def get_open_orders(self, *, market: str, symbol: str | None = None) -> dict[str, object]:
        return {"market": market, "orders": []}

    def get_positions(self) -> dict[str, object]:
        return {
            "positions": [
                {
                    "symbol": "ETHUSDT",
                    "holdSide": "short",
                    "total": "0.50",
                    "available": "0.50",
                    "openPriceAvg": "2100.0",
                    "markPrice": "2110.0",
                    "leverage": "5",
                    "cTime": "1772971200000",
                }
            ]
        }


class FakeDaemonClient:
    exchange_id = "binance"
    supports_private_reads = True

    def __init__(self) -> None:
        self.spot_account = {
            "balances": [
                {"asset": "USDT", "free": "10.0", "locked": "0.0"},
            ]
        }
        self.futures_account = {
            "availableBalance": 40.0,
            "executionAvailableBalance": 5.0,
            "totalWalletBalance": 50.0,
            "totalMarginBalance": 50.0,
        }

    def get_exchange_info(self, *, market):  # type: ignore[no-untyped-def]
        return {
            "symbols": [
                {"symbol": "BTCUSDT", "filters": [{"filterType": "MIN_NOTIONAL", "notional": "100"}]},
                {"symbol": "ETHUSDT", "filters": [{"filterType": "MIN_NOTIONAL", "notional": "20"}]},
                {"symbol": "SOLUSDT", "filters": [{"filterType": "MIN_NOTIONAL", "notional": "5"}]},
            ]
        }

    def get_book_ticker(self, *, market, symbol):  # type: ignore[no-untyped-def]
        return {"bidPrice": "49999.5", "bidQty": "1.0", "askPrice": "50000.5", "askQty": "1.2"}

    def get_mark_price(self, *, symbol):  # type: ignore[no-untyped-def]
        return {"markPrice": "50000.0", "indexPrice": "49995.0", "lastFundingRate": "0.0001"}

    def get_open_interest(self, *, symbol):  # type: ignore[no-untyped-def]
        return {"openInterest": "1080000.0"}

    def get_klines(self, *, market, symbol, interval, limit):  # type: ignore[no-untyped-def]
        base = 1700000000000
        rows = []
        for idx in range(limit):
            open_time = base + idx * 300000
            close_time = open_time + 299999
            rows.append(
                [
                    open_time,
                    "50000.0",
                    "50100.0",
                    "49900.0",
                    "50050.0",
                    "10.0",
                    close_time,
                    "500000.0",
                ]
            )
        return rows

    def get_account(self, *, market):  # type: ignore[no-untyped-def]
        if market == "spot":
            return self.spot_account
        return self.futures_account

    def get_open_orders(self, *, market, symbol=None):  # type: ignore[no-untyped-def]
        return {"market": market, "orders": []}

    def get_positions(self) -> dict[str, object]:
        return {
            "positions": [
                {
                    "symbol": "ADAUSDT",
                    "holdSide": "short",
                    "total": "0.50",
                    "available": "0.50",
                    "openPriceAvg": "0.65",
                    "markPrice": "0.66",
                    "leverage": "5",
                    "cTime": "1772971200000",
                }
            ]
        }


class RestoredPositionsShell:
    def __init__(self, *, ws_client_factory, session, backoff_policy, summary_path, state_path):  # type: ignore[no-untyped-def]
        self.session = session

    async def run(self) -> dict[str, object]:
        return {
            "status": "ok",
            "paper_symbols": sorted(self.session.paper_positions),
            "missing_in_paper_counts": dict(self.session.futures_missing_in_paper_counts),
        }


class RuntimeRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def _build_session(self) -> LivePaperSession:
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol="BTCUSDT",
                top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.2, now),
                last_trade_price=50000.0,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=3.0,
                last_update_time=now,
            )
        )
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(store),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: None,
            history_provider=lambda symbol, decision_time: None,
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        return LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            rest_client=FakeRuntimeRestClient(),
        )

    def test_status_and_report_scripts_prefer_latest_runtime_snapshot(self) -> None:
        runtime_dir = ROOT / "tests" / "tmp_runtime_recovery_reports"
        if runtime_dir.exists():
            shutil.rmtree(runtime_dir)
        try:
            legacy_run = runtime_dir / "output" / "paper-live-shell" / "20260313-legacy"
            legacy_run.mkdir(parents=True, exist_ok=True)
            write_runtime_summary(legacy_run / "summary.json", build_runtime_summary(decisions=[]))
            write_runtime_state(legacy_run / "summary.state.json", {"heartbeat_count": 1})

            latest_run = runtime_dir / "output" / "paper-live-shell" / "20260313-current"
            latest_run.mkdir(parents=True, exist_ok=True)
            latest_summary = build_runtime_summary(
                decisions=[],
                self_healing={
                    "status": "guarded",
                    "active_guards": {"live_order_cooldown_until": "2026-03-13T04:20:00+00:00"},
                    "recent_events": [{"category": "bitget_live_order_compatibility"}],
                },
            )
            write_runtime_summary(latest_run / "summary.json", latest_summary)
            write_runtime_state(
                latest_run / "summary.state.json",
                {"heartbeat_count": 7, "self_healing": latest_summary["self_healing"]},
            )

            report_proc = subprocess.run(
                ["sh", "scripts/quant_report.sh", str(runtime_dir)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            status_proc = subprocess.run(
                ["sh", "scripts/quant_status.sh", str(runtime_dir)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
        finally:
            if runtime_dir.exists():
                shutil.rmtree(runtime_dir)

        self.assertIn("/latest/summary.json", report_proc.stdout)
        self.assertIn("/latest/summary.state.json", status_proc.stdout)
        self.assertIn("self_healing_status: guarded", report_proc.stdout)
        self.assertIn("self_healing_status: guarded", status_proc.stdout)

    def test_restore_futures_state_from_runtime_rehydrates_live_positions(self) -> None:
        session = self._build_session()
        session.sync_account()

        self.assertEqual(session.futures_missing_in_paper_counts, {"ETHUSDT": 1})
        self.assertNotIn("ETHUSDT", session.paper_positions)

        restored = session.restore_futures_state_from_runtime(
            state_payload={
                "paper_open_futures_positions": [
                    {
                        "symbol": "ETHUSDT",
                        "market": "futures",
                        "side": "short",
                        "entry_time": "2026-03-08T12:00:00+00:00",
                        "entry_price": 2100.0,
                        "current_price": 2110.0,
                        "quantity_opened": 0.5,
                        "quantity_remaining": 0.5,
                        "entry_planned_leverage": 5,
                    }
                ],
                "futures_missing_in_paper_counts": {"ETHUSDT": 1},
            },
        )

        self.assertEqual(restored, 1)
        self.assertIn("ETHUSDT", session.paper_positions)
        self.assertEqual(session.paper_positions["ETHUSDT"].entry_time.isoformat(), "2026-03-08T12:00:00+00:00")
        self.assertEqual(session.paper_positions["ETHUSDT"].entry_planned_leverage, 5)
        self.assertEqual(session.futures_missing_in_paper_counts, {})

    def test_restore_futures_state_from_runtime_immediately_adopts_live_positions_missing_from_snapshot(self) -> None:
        session = self._build_session()
        session.sync_account()

        restored = session.restore_futures_state_from_runtime(state_payload={})

        self.assertEqual(restored, 1)
        self.assertIn("ETHUSDT", session.paper_positions)
        self.assertTrue(session.paper_positions["ETHUSDT"].exchange_synced)
        self.assertEqual(session.futures_missing_in_paper_counts, {})

    def test_run_live_paper_daemon_restores_latest_paper_futures_state_before_shell_run(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            previous_run = Path(output_dir) / "output" / "paper-live-shell" / "20260313-previous"
            previous_run.mkdir(parents=True, exist_ok=True)
            previous_summary = build_runtime_summary(
                decisions=[],
                open_futures_positions=[
                    {
                        "symbol": "ADAUSDT",
                        "market": "futures",
                        "side": "short",
                        "entry_time": "2026-03-08T12:00:00+00:00",
                        "entry_price": 0.65,
                        "current_price": 0.66,
                        "quantity_opened": 0.5,
                        "quantity_remaining": 0.5,
                        "entry_planned_leverage": 5,
                    }
                ],
            )
            write_runtime_summary(previous_run / "summary.json", previous_summary)
            write_runtime_state(
                previous_run / "summary.state.json",
                {
                    "paper_open_futures_positions": previous_summary["paper_open_futures_positions"],
                    "futures_missing_in_paper_counts": {"ADAUSDT": 1},
                },
            )

            with patch("quant_binance.daemon.build_exchange_rest_client", return_value=FakeDaemonClient()):
                with patch("quant_binance.daemon.LivePaperShell", RestoredPositionsShell):
                    result = run_live_paper_daemon(
                        config_path=CONFIG_PATH,
                        output_base_dir=output_dir,
                        exchange="binance",
                        max_retries=1,
                    )

        self.assertIn("ADAUSDT", result["summary"]["paper_symbols"])
        self.assertEqual(result["summary"]["missing_in_paper_counts"], {})

    def test_run_live_paper_daemon_immediately_adopts_live_positions_missing_from_previous_runtime_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            previous_run = Path(output_dir) / "output" / "paper-live-shell" / "20260313-previous"
            previous_run.mkdir(parents=True, exist_ok=True)
            previous_summary = build_runtime_summary(decisions=[])
            write_runtime_summary(previous_run / "summary.json", previous_summary)
            write_runtime_state(previous_run / "summary.state.json", {})

            with patch("quant_binance.daemon.build_exchange_rest_client", return_value=FakeDaemonClient()):
                with patch("quant_binance.daemon.LivePaperShell", RestoredPositionsShell):
                    result = run_live_paper_daemon(
                        config_path=CONFIG_PATH,
                        output_base_dir=output_dir,
                        exchange="binance",
                        max_retries=1,
                    )

        self.assertIn("ADAUSDT", result["summary"]["paper_symbols"])
        self.assertEqual(result["summary"]["missing_in_paper_counts"], {})


if __name__ == "__main__":
    unittest.main()
