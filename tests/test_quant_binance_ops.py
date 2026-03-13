from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.router import ExecutionRouter
from quant_binance.observability.report import build_runtime_summary, write_runtime_summary
from quant_binance.observability.runtime_state import read_runtime_state, write_runtime_state
from quant_binance.risk.kill_switch import KillSwitch
from quant_binance.service import PaperTradingService
from quant_binance.self_healing import RuntimeSelfHealing
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


class QuantBinanceOpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def setUp(self) -> None:
        self.summary_path = ROOT / "tests" / "tmp_runtime_summary.json"
        self.state_path = ROOT / "tests" / "tmp_runtime_state.json"
        self.runtime_dir = ROOT / "tests" / "tmp_runtime_reports"

    def tearDown(self) -> None:
        for path in (self.summary_path, self.state_path):
            if path.exists():
                path.unlink()
        if self.runtime_dir.exists():
            shutil.rmtree(self.runtime_dir)

    def _write_report_runtime_files(self, *, summary: dict[str, object], state: dict[str, object]) -> None:
        run_dir = self.runtime_dir / "output" / "paper-live-shell" / "20260313-ops-test"
        run_dir.mkdir(parents=True, exist_ok=True)
        write_runtime_summary(run_dir / "summary.json", summary)
        write_runtime_state(run_dir / "summary.state.json", state)

    def test_kill_switch_status_and_clear(self) -> None:
        kill_switch = KillSwitch()
        kill_switch.arm("STALE_DATA")
        self.assertTrue(kill_switch.armed)
        self.assertIn("STALE_DATA", kill_switch.reasons)
        kill_switch.clear()
        self.assertFalse(kill_switch.armed)

    def test_runtime_summary_and_state_write(self) -> None:
        summary = build_runtime_summary(
            decisions=[],
            tested_orders=[{"symbol": "BTCUSDT"}],
            account_snapshot={"accountType": "SPOT"},
            open_orders_snapshot=[],
            closed_trades=[
                {
                    "symbol": "BTCUSDT",
                    "market": "spot",
                    "exit_reason": "PARTIAL_TAKE_PROFIT",
                    "realized_pnl_usd_estimate": 12.5,
                    "realized_return_bps_estimate": 50.0,
                }
            ],
            open_spot_positions=[
                {
                    "symbol": "ETHUSDT",
                    "unrealized_pnl_usd_estimate": 7.5,
                }
            ],
            kill_switch_status={"armed": False, "reasons": []},
        )
        write_runtime_summary(self.summary_path, summary)
        self.assertTrue(self.summary_path.exists())
        self.assertIn("tested_order_count", self.summary_path.read_text(encoding="utf-8"))
        self.assertEqual(summary["realized_pnl_usd_estimate"], 12.5)
        self.assertEqual(summary["unrealized_pnl_usd_estimate"], 7.5)
        self.assertEqual(summary["exit_reason_counts"], {"PARTIAL_TAKE_PROFIT": 1})

        write_runtime_state(self.state_path, {"mode": "paper-live"})
        payload = read_runtime_state(self.state_path)
        self.assertEqual(payload["mode"], "paper-live")
        self.assertIn("updated_at", payload)

    def test_runtime_summary_reports_matching_exchange_and_paper_futures_positions(self) -> None:
        summary = build_runtime_summary(
            decisions=[],
            open_futures_positions=[
                {"symbol": "BTCUSDT", "market": "futures"},
                {"symbol": "ETHUSDT", "market": "futures"},
            ],
            live_positions=[
                {"symbol": "BTCUSDT", "holdSide": "long", "total": "0.02"},
                {"symbol": "ETHUSDT", "holdSide": "short", "total": "0.50"},
            ],
        )

        self.assertEqual(summary["paper_open_futures_position_count"], 2)
        self.assertEqual(summary["exchange_live_futures_position_count"], 2)
        self.assertFalse(summary["futures_position_mismatch"])
        self.assertEqual(
            summary["futures_position_mismatch_details"],
            {"missing_in_paper": [], "missing_on_exchange": []},
        )

    def test_runtime_summary_reports_count_difference_between_exchange_and_paper_futures_positions(self) -> None:
        summary = build_runtime_summary(
            decisions=[],
            open_futures_positions=[
                {"symbol": "BTCUSDT", "market": "futures"},
            ],
            live_positions=[
                {"symbol": "BTCUSDT", "holdSide": "long", "total": "0.02"},
                {"symbol": "ETHUSDT", "holdSide": "short", "total": "0.50"},
            ],
        )

        self.assertEqual(summary["paper_open_futures_position_count"], 1)
        self.assertEqual(summary["exchange_live_futures_position_count"], 2)
        self.assertTrue(summary["futures_position_mismatch"])

    def test_runtime_summary_populates_futures_position_mismatch_details(self) -> None:
        summary = build_runtime_summary(
            decisions=[],
            open_futures_positions=[
                {"symbol": "BTCUSDT", "market": "futures"},
                {"symbol": "SOLUSDT", "market": "futures"},
            ],
            live_positions=[
                {"symbol": "BTCUSDT", "holdSide": "long", "total": "0.02"},
                {"symbol": "ETHUSDT", "holdSide": "short", "total": "0.50"},
                {"symbol": "XRPUSDT", "holdSide": "long", "total": "0.00"},
            ],
        )

        self.assertEqual(
            summary["futures_position_mismatch_details"],
            {"missing_in_paper": ["ETHUSDT"], "missing_on_exchange": ["SOLUSDT"]},
        )

    def test_runtime_self_healing_escalates_repeated_bitget_compatibility_errors_to_global_guard(self) -> None:
        healing = RuntimeSelfHealing(
            known_error_escalation_count=3,
            live_order_cooldown_seconds=600,
        )
        now = datetime(2026, 3, 13, 4, 0, tzinfo=timezone.utc)
        for minute in range(3):
            healing.record_runtime_error(
                now=now + timedelta(minutes=minute),
                symbol="ETHUSDT",
                error_message='RuntimeError(\'Bitget HTTP 400: {"code":"40774","msg":"The order type for unilateral position must also be the unilateral position type."}\')',
                exchange_id="bitget",
                stage="live_order",
            )

        snapshot = healing.snapshot(
            now=now + timedelta(minutes=2, seconds=1),
            order_error_cooldowns={},
            manual_symbol_cooldowns={},
            mismatch_active=False,
            mismatch_details={"missing_in_paper": [], "missing_on_exchange": []},
        )

        self.assertEqual(snapshot["status"], "guarded")
        self.assertIn("bitget_live_order_compatibility", snapshot["issue_counts"])
        self.assertEqual(snapshot["recent_events"][-1]["action"], "global_live_order_cooldown")
        self.assertTrue(healing.is_live_order_cooldown_active(now=now + timedelta(minutes=2, seconds=1)))

    def test_runtime_self_healing_blocks_repeat_stall_restarts_after_budget(self) -> None:
        healing = RuntimeSelfHealing(
            stall_timeout_seconds=60,
            max_stall_restarts_per_window=1,
            stall_restart_window_seconds=600,
        )
        started = datetime(2026, 3, 13, 4, 0, tzinfo=timezone.utc)
        healing.begin_monitoring(timestamp=started, heartbeat_count=0)

        self.assertTrue(healing.detect_stall(now=started + timedelta(seconds=61)))
        self.assertTrue(healing.register_stall_recovery(now=started + timedelta(seconds=61), heartbeat_count=0))

        healing.begin_monitoring(timestamp=started + timedelta(seconds=62), heartbeat_count=0)
        self.assertTrue(healing.detect_stall(now=started + timedelta(seconds=123)))
        self.assertFalse(healing.register_stall_recovery(now=started + timedelta(seconds=123), heartbeat_count=0))

        snapshot = healing.snapshot(
            now=started + timedelta(seconds=123),
            order_error_cooldowns={},
            manual_symbol_cooldowns={},
            mismatch_active=False,
            mismatch_details={"missing_in_paper": [], "missing_on_exchange": []},
        )

        self.assertEqual(snapshot["status"], "blocked")
        self.assertEqual(snapshot["active_guards"]["stall_restart_budget_remaining"], 0)
        self.assertEqual(snapshot["recent_events"][-1]["status"], "suppressed")

    def test_quant_report_script_prints_split_futures_position_fields_without_legacy_ambiguity(self) -> None:
        summary = build_runtime_summary(
            decisions=[],
            open_futures_positions=[
                {"symbol": "BTCUSDT", "market": "futures"},
            ],
            live_positions=[
                {"symbol": "BTCUSDT", "holdSide": "long", "total": "0.02"},
                {"symbol": "ETHUSDT", "holdSide": "short", "total": "0.50"},
            ],
            self_healing={
                "status": "guarded",
                "active_guards": {"live_order_cooldown_until": "2026-03-13T04:20:00+00:00"},
                "recent_events": [{"category": "bitget_live_order_compatibility", "action": "global_live_order_cooldown"}],
            },
        )
        self._write_report_runtime_files(
            summary=summary,
            state={
                "heartbeat_count": 7,
                "futures_position_mismatch": True,
                "futures_position_mismatch_details": summary["futures_position_mismatch_details"],
            },
        )

        proc = subprocess.run(
            ["sh", "scripts/quant_report.sh", str(self.runtime_dir)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        output = proc.stdout

        self.assertIn("paper_open_futures_position_count: 1", output)
        self.assertIn("paper_open_futures_symbols: ['BTCUSDT']", output)
        self.assertIn("exchange_live_futures_position_count: 2", output)
        self.assertIn("exchange_live_futures_symbols: ['BTCUSDT', 'ETHUSDT']", output)
        self.assertIn("futures_position_warning: {'missing_in_paper': ['ETHUSDT'], 'missing_on_exchange': []}", output)
        self.assertIn("self_healing_status: guarded", output)
        self.assertIn("self_healing_active_guards:", output)
        self.assertNotIn("\nopen_futures_positions:", output)
        self.assertNotIn("\nlive_positions:", output)

    def test_quant_status_script_prints_split_futures_position_fields(self) -> None:
        summary = build_runtime_summary(
            decisions=[],
            open_futures_positions=[
                {"symbol": "BTCUSDT", "market": "futures"},
            ],
            live_positions=[
                {"symbol": "BTCUSDT", "holdSide": "long", "total": "0.02"},
                {"symbol": "ETHUSDT", "holdSide": "short", "total": "0.50"},
            ],
            self_healing={
                "status": "degraded",
                "active_guards": {"mismatch_active": True},
                "recent_events": [{"category": "futures_position_mismatch", "action": "reconcile_positions"}],
            },
        )
        self._write_report_runtime_files(
            summary=summary,
            state={
                "heartbeat_count": 7,
                "paper_open_futures_position_count": summary["paper_open_futures_position_count"],
                "paper_open_futures_positions": summary["paper_open_futures_positions"],
                "exchange_live_futures_position_count": summary["exchange_live_futures_position_count"],
                "exchange_live_futures_positions": summary["exchange_live_futures_positions"],
                "futures_position_mismatch": True,
                "futures_position_mismatch_details": summary["futures_position_mismatch_details"],
                "self_healing": summary["self_healing"],
            },
        )

        proc = subprocess.run(
            ["sh", "scripts/quant_status.sh", str(self.runtime_dir)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        output = proc.stdout

        self.assertIn("paper_open_futures_position_count: 1", output)
        self.assertIn("paper_open_futures_symbols: ['BTCUSDT']", output)
        self.assertIn("exchange_live_futures_position_count: 2", output)
        self.assertIn("exchange_live_futures_symbols: ['BTCUSDT', 'ETHUSDT']", output)
        self.assertIn("futures_position_warning: {'missing_in_paper': ['ETHUSDT'], 'missing_on_exchange': []}", output)
        self.assertIn("self_healing_status: degraded", output)

    def test_live_runtime_respects_kill_switch(self) -> None:
        now = datetime(2026, 3, 8, 12, 5, 0, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol="BTCUSDT",
                top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.2, now - timedelta(seconds=20)),
                last_trade_price=50000.0,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=3.0,
                last_update_time=now - timedelta(seconds=20),
            )
        )
        kill_switch = KillSwitch()
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(store),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
            kill_switch=kill_switch,
        )
        kill_switch.arm("MANUAL_TEST")
        decision = runtime.on_payload(
            {
                "stream": "btcusdt@kline_5m",
                "data": {
                    "s": "BTCUSDT",
                    "k": {
                        "i": "5m",
                        "t": 1772971200000,
                        "T": 1772971500000,
                        "o": "49900",
                        "h": "50100",
                        "l": "49850",
                        "c": "50050",
                        "v": "12",
                        "q": "600000",
                        "x": True
                    }
                }
            },
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        self.assertIsNone(decision)
        self.assertTrue(kill_switch.armed)


if __name__ == "__main__":
    unittest.main()
