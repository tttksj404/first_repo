from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from quant_binance.daemon import run_live_paper_daemon
from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.router import ExecutionRouter
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.observability.report import build_runtime_summary, write_runtime_summary
from quant_binance.observability.runtime_state import write_runtime_state
from quant_binance.self_healing import (
    KNOWN_CATEGORY_BITGET_LIVE_ORDER,
    KNOWN_CATEGORY_DAEMON_STALLED,
    KNOWN_CATEGORY_MISSING_MARKET_STATE,
    UNKNOWN_CATEGORY_RUNTIME_ERROR,
    RuntimeSelfHealing,
    classify_runtime_issue,
)
from quant_binance.service import PaperTradingService
from quant_binance.session import BackoffPolicy, LivePaperSession, LivePaperShell
from quant_binance.settings import Settings
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


def make_history() -> FeatureHistoryContext:
    return FeatureHistoryContext(
        returns_1h=(0.01, 0.02, 0.03, 0.04, 0.05),
        returns_4h=(0.02, 0.03, 0.04, 0.05, 0.06),
        quote_volume_5m=(1000, 1100, 1200, 1300, 1400),
        quote_volume_1h=(10000, 10500, 11000, 11500, 12000),
        realized_vol_1h=(0.1, 0.12, 0.14, 0.16, 0.18),
        realized_vol_4h=(0.15, 0.17, 0.19, 0.21, 0.23),
        funding_abs=(0.0001, 0.0002, 0.0003, 0.0004, 0.0005),
        basis_abs=(2.0, 3.0, 4.0, 5.0, 6.0),
        oi_surge=(0.05, 0.1, 0.15, 0.2, 0.25),
    )


def make_primitive() -> PrimitiveInputs:
    return PrimitiveInputs(
        ret_1h=0.05,
        ret_4h=0.06,
        trend_direction=1,
        ema_stack_score=1.0,
        breakout_reference_price=49500.0,
        last_trade_price=50000.0,
        atr_14_1h_price=200.0,
        quote_volume_5m=1600.0,
        quote_volume_1h=13000.0,
        buy_taker_volume=70.0,
        sell_taker_volume=30.0,
        spread_bps=2.0,
        probe_slippage_bps=3.0,
        depth_usd_within_10bps=300000.0,
        order_book_imbalance_std=0.1,
        realized_vol_1h=0.12,
        realized_vol_4h=0.17,
        median_realized_vol_1h_30d=0.12,
        funding_rate=0.0001,
        open_interest=1080000.0,
        open_interest_ema=1000000.0,
        basis_bps=3.0,
        gross_expected_edge_bps=30.0,
    )


class FakeRestClient:
    exchange_id = "binance"
    supports_private_reads = False

    def get_exchange_info(self, *, market):  # type: ignore[no-untyped-def]
        return {
            "symbols": [
                {"symbol": "BTCUSDT", "filters": [{"filterType": "MIN_NOTIONAL", "notional": "100"}]},
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


class FakeShellWithoutSelfHealing:
    def __init__(self, *, ws_client_factory, session, backoff_policy, summary_path, state_path):  # type: ignore[no-untyped-def]
        self.session = session

    async def run(self) -> dict[str, object]:
        return {"status": "ok"}


class StalledWebSocketClient:
    async def run(self, handler) -> None:  # type: ignore[no-untyped-def]
        await asyncio.sleep(3)


class CompletingWebSocketClient:
    async def run(self, handler) -> None:  # type: ignore[no-untyped-def]
        return None


class QuantBinanceSelfHealingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def setUp(self) -> None:
        self.runtime_dir = ROOT / "tests" / "tmp_self_healing_runtime"
        self.summary_path = ROOT / "tests" / "tmp_self_healing_summary.json"
        self.state_path = ROOT / "tests" / "tmp_self_healing_state.json"

    def tearDown(self) -> None:
        if self.runtime_dir.exists():
            shutil.rmtree(self.runtime_dir)
        for path in (self.summary_path, self.state_path):
            if path.exists():
                path.unlink()

    def _build_session(self) -> LivePaperSession:
        now = datetime(2026, 3, 13, 4, 0, tzinfo=timezone.utc)
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
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        return LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )

    def _write_report_runtime_files(self, *, summary: dict[str, object], state: dict[str, object]) -> None:
        run_dir = self.runtime_dir / "output" / "paper-live-shell" / "20260313-self-healing"
        run_dir.mkdir(parents=True, exist_ok=True)
        write_runtime_summary(run_dir / "summary.json", summary)
        write_runtime_state(run_dir / "summary.state.json", state)

    def test_classify_runtime_issue_knows_bitget_live_order_mode_errors(self) -> None:
        issue = classify_runtime_issue(
            error_message='RuntimeError(\'Bitget HTTP 400: {"code":"40774","msg":"The order type for unilateral position must also be the unilateral position type."}\')',
            exchange_id="bitget",
            stage="live_order",
        )

        self.assertEqual(issue["category"], KNOWN_CATEGORY_BITGET_LIVE_ORDER)
        self.assertTrue(issue["known"])
        self.assertEqual(issue["automatic_action"], "cooldown_and_reuse_test_order_path")

    def test_classify_runtime_issue_knows_missing_market_state_errors(self) -> None:
        issue = classify_runtime_issue(
            error_message="KeyError('missing market state for symbol=STEEMUSDT')",
            exchange_id="binance",
            stage="market_data",
        )

        self.assertEqual(issue["category"], KNOWN_CATEGORY_MISSING_MARKET_STATE)
        self.assertTrue(issue["known"])
        self.assertEqual(issue["automatic_action"], "skip_payload_until_market_state_ready")

    def test_runtime_self_healing_activates_global_live_order_cooldown_after_tripwire(self) -> None:
        healing = RuntimeSelfHealing(known_error_escalation_count=3, live_order_cooldown_seconds=600)
        now = datetime(2026, 3, 13, 4, 0, tzinfo=timezone.utc)

        healing.record_runtime_error(
            now=now,
            symbol="BTCUSDT",
            error_message='RuntimeError(\'Bitget HTTP 400: {"code":"40774","msg":"The order type for unilateral position must also be the unilateral position type."}\')',
            exchange_id="bitget",
            stage="live_order",
        )
        healing.record_runtime_error(
            now=now + timedelta(minutes=1),
            symbol="ETHUSDT",
            error_message='RuntimeError(\'Bitget HTTP 400: {"code":"40762","msg":"The order type for one-way position must match the one-way position mode."}\')',
            exchange_id="bitget",
            stage="live_order",
        )
        healing.record_runtime_error(
            now=now + timedelta(minutes=2),
            symbol="SOLUSDT",
            error_message='RuntimeError(\'Bitget HTTP 400: {"code":"40774","msg":"The order type for unilateral position must also be the unilateral position type."}\')',
            exchange_id="bitget",
            stage="live_order",
        )

        self.assertTrue(healing.is_live_order_cooldown_active(now=now + timedelta(minutes=2)))
        last_event = healing.recent_events[-1].as_dict()
        self.assertEqual(last_event["action"], "global_live_order_cooldown")

    def test_runtime_self_healing_marks_unknown_error_as_report_only(self) -> None:
        healing = RuntimeSelfHealing()
        now = datetime(2026, 3, 13, 4, 0, tzinfo=timezone.utc)

        issue = healing.record_runtime_error(
            now=now,
            symbol="BTCUSDT",
            error_message="RuntimeError('socket exploded in an unfamiliar way')",
            exchange_id="bitget",
            stage="live_order",
        )

        self.assertEqual(issue["category"], UNKNOWN_CATEGORY_RUNTIME_ERROR)
        self.assertFalse(issue["known"])
        self.assertFalse(healing.is_live_order_cooldown_active(now=now))
        self.assertEqual(healing._recent_events[-1].status, "reported")

    def test_runtime_self_healing_tracks_missing_market_state_in_snapshot(self) -> None:
        healing = RuntimeSelfHealing()
        now = datetime(2026, 3, 13, 4, 0, tzinfo=timezone.utc)

        issue = healing.record_runtime_error(
            now=now,
            symbol="STEEMUSDT",
            error_message="KeyError('missing market state for symbol=STEEMUSDT')",
            exchange_id="binance",
            stage="market_data",
        )

        snapshot = healing.snapshot(
            now=now,
            order_error_cooldowns={},
            manual_symbol_cooldowns={},
            mismatch_active=False,
            mismatch_details={},
        )

        self.assertEqual(issue["category"], KNOWN_CATEGORY_MISSING_MARKET_STATE)
        self.assertTrue(issue["known"])
        self.assertEqual(snapshot["status"], "degraded")
        self.assertEqual(snapshot["active_guards"]["missing_market_state_symbols"], ["STEEMUSDT"])
        self.assertEqual(snapshot["recent_events"][-1]["category"], KNOWN_CATEGORY_MISSING_MARKET_STATE)

    def test_live_paper_shell_restarts_once_on_stall_and_records_event(self) -> None:
        session = self._build_session()
        session.self_healing.stall_timeout_seconds = 1
        session.self_healing.max_stall_restarts_per_window = 2
        clients = [StalledWebSocketClient(), CompletingWebSocketClient()]

        def factory():
            return clients.pop(0)

        shell = LivePaperShell(
            ws_client_factory=factory,
            session=session,
            backoff_policy=BackoffPolicy(initial_delay_seconds=0.0, max_delay_seconds=0.0, multiplier=1.0, max_attempts=2),
            summary_path=self.summary_path,
            state_path=self.state_path,
        )

        summary = asyncio.run(shell.run())

        assert summary is not None
        self.assertTrue(self.summary_path.exists())
        self.assertEqual(summary["self_healing"]["recent_events"][-1]["category"], KNOWN_CATEGORY_DAEMON_STALLED)
        self.assertEqual(summary["self_healing"]["recent_events"][-1]["status"], "applied")

    def test_runtime_self_healing_detects_decision_stall_while_heartbeats_continue(self) -> None:
        healing = RuntimeSelfHealing(
            stall_timeout_seconds=60,
            max_stall_restarts_per_window=1,
            stall_restart_window_seconds=600,
        )
        started = datetime(2026, 3, 13, 4, 0, tzinfo=timezone.utc)
        healing.begin_monitoring(timestamp=started, heartbeat_count=0, decision_count=1)
        healing.note_decision(timestamp=started, decision_count=1, heartbeat_count=0)
        healing.note_progress(timestamp=started + timedelta(seconds=30), heartbeat_count=5)

        self.assertTrue(healing.detect_stall(now=started + timedelta(seconds=61)))
        self.assertTrue(healing.register_stall_recovery(now=started + timedelta(seconds=61), heartbeat_count=5))

        snapshot = healing.snapshot(
            now=started + timedelta(seconds=61),
            order_error_cooldowns={},
            manual_symbol_cooldowns={},
            mismatch_active=False,
            mismatch_details={"missing_in_paper": [], "missing_on_exchange": []},
        )

        self.assertEqual(snapshot["recent_events"][-1]["details"]["stall_kind"], "decision_progress")

    def test_runtime_self_healing_blocks_second_stall_restart_when_budget_is_exhausted(self) -> None:
        healing = RuntimeSelfHealing(max_stall_restarts_per_window=1)
        now = datetime(2026, 3, 13, 4, 0, tzinfo=timezone.utc)

        self.assertTrue(healing.register_stall_recovery(now=now, heartbeat_count=0))
        self.assertFalse(healing.register_stall_recovery(now=now + timedelta(minutes=1), heartbeat_count=0))
        snapshot = healing.snapshot(
            now=now + timedelta(minutes=1),
            order_error_cooldowns={},
            manual_symbol_cooldowns={},
            mismatch_active=False,
            mismatch_details={},
        )

        self.assertEqual(snapshot["active_guards"]["stall_restart_budget_remaining"], 0)
        self.assertEqual(snapshot["recent_events"][-1]["status"], "suppressed")

    def test_run_live_paper_daemon_injects_self_healing_status_when_shell_omits_it(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            with patch("quant_binance.daemon.build_exchange_rest_client", return_value=FakeRestClient()):
                with patch("quant_binance.daemon.LivePaperShell", FakeShellWithoutSelfHealing):
                    result = run_live_paper_daemon(
                        config_path=CONFIG_PATH,
                        output_base_dir=output_dir,
                        exchange="binance",
                        max_retries=1,
                    )

        self.assertIn("self_healing", result["summary"])
        self.assertEqual(result["summary"]["self_healing"]["status"], "healthy")

    def test_quant_report_and_status_scripts_print_self_healing_section(self) -> None:
        summary = build_runtime_summary(
            decisions=[],
            self_healing={
                "status": "active",
                "active_guards": [{"type": "global_live_order_cooldown", "until": "2026-03-13T04:15:00+00:00"}],
                "recent_events": [
                    {
                        "category": KNOWN_CATEGORY_BITGET_LIVE_ORDER,
                        "automatic_action": "pause_live_orders_and_reuse_test_order_path",
                        "action_status": "applied",
                    }
                ],
            },
        )
        self._write_report_runtime_files(
            summary=summary,
            state={
                "heartbeat_count": 7,
                "self_healing": summary["self_healing"],
            },
        )

        report_proc = subprocess.run(
            ["sh", "scripts/quant_report.sh", str(self.runtime_dir)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        status_proc = subprocess.run(
            ["sh", "scripts/quant_status.sh", str(self.runtime_dir)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertIn("self_healing_status: active", report_proc.stdout)
        self.assertIn("self_healing_active_guards:", report_proc.stdout)
        self.assertIn("pause_live_orders_and_reuse_test_order_path", report_proc.stdout)
        self.assertIn("self_healing_status: active", status_proc.stdout)
        self.assertIn("self_healing_recent_events:", status_proc.stdout)


if __name__ == "__main__":
    unittest.main()
