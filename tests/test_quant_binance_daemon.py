from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import json

from quant_binance.daemon import _bootstrap_decision_time, _build_live_ws_client, run_live_paper_daemon
from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import KlineBar, SymbolMarketState, TopOfBook
from quant_binance.data.bitget_ws import BitgetWebSocketClient
from quant_binance.data.rest_seed import seed_market_store_from_rest
from quant_binance.observability.report import write_runtime_summary
from quant_binance.observability.runtime_state import write_runtime_state
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class FakeRestClient:
    exchange_id = "binance"

    def get_exchange_info(self, *, market):  # type: ignore[no-untyped-def]
        return {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "filters": [{"filterType": "MIN_NOTIONAL", "notional": "100"}],
                },
                {
                    "symbol": "ETHUSDT",
                    "baseAsset": "ETH",
                    "quoteAsset": "USDT",
                    "filters": [{"filterType": "MIN_NOTIONAL", "notional": "20"}],
                },
                {
                    "symbol": "ETHBTC",
                    "baseAsset": "ETH",
                    "quoteAsset": "BTC",
                    "filters": [{"filterType": "MIN_NOTIONAL", "notional": "0.0001"}],
                },
                {
                    "symbol": "SOLUSDT",
                    "baseAsset": "SOL",
                    "quoteAsset": "USDT",
                    "filters": [{"filterType": "MIN_NOTIONAL", "notional": "5"}],
                },
            ]
        }

    def get_book_ticker(self, *, market, symbol):  # type: ignore[no-untyped-def]
        return {"bidPrice": "49999.5", "bidQty": "1.0", "askPrice": "50000.5", "askQty": "1.2"}

    def get_mark_price(self, *, symbol):  # type: ignore[no-untyped-def]
        return {"markPrice": "50000.0", "indexPrice": "49995.0", "lastFundingRate": "0.0001"}

    def get_open_interest(self, *, symbol):  # type: ignore[no-untyped-def]
        return {"openInterest": "1080000.0"}

    def get_klines(self, *, market, symbol, interval, limit):  # type: ignore[no-untyped-def]
        base = int(datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
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


class BootstrapTimingRestClient(FakeRestClient):
    supports_private_reads = False

    def get_klines(self, *, market, symbol, interval, limit):  # type: ignore[no-untyped-def]
        if interval == "5m":
            close_times = (
                datetime(2026, 3, 14, 0, 10, tzinfo=timezone.utc),
                datetime(2026, 3, 14, 0, 15, tzinfo=timezone.utc),
                datetime(2026, 3, 14, 0, 20, tzinfo=timezone.utc),
            )
            rows = []
            for close_time in close_times:
                open_time = int((close_time.timestamp() - 300) * 1000)
                rows.append(
                    [
                        open_time,
                        "50000.0",
                        "50100.0",
                        "49900.0",
                        "50050.0",
                        "10.0",
                        int(close_time.timestamp() * 1000) - 1,
                        "500000.0",
                    ]
                )
            return rows
        return super().get_klines(market=market, symbol=symbol, interval=interval, limit=limit)


class FakeBitgetDaemonClient(FakeRestClient):
    exchange_id = "bitget"
    supports_private_reads = False

    def test_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        return {"status": "PREVIEW", "market": market, "request": dict(order_params)}


class FakeBitgetPartialSeedClient(FakeBitgetDaemonClient):
    def get_exchange_info(self, *, market):  # type: ignore[no-untyped-def]
        symbols = [{"symbol": "BTCUSDT", "filters": [{"filterType": "MIN_NOTIONAL", "notional": "100"}]}]
        if market == "futures":
            symbols.append({"symbol": "STEEMUSDT", "filters": [{"filterType": "MIN_NOTIONAL", "notional": "5"}]})
        return {"symbols": symbols}


class FakePrivateDaemonClient(FakeRestClient):
    supports_private_reads = True

    def __init__(self) -> None:
        self.spot_account = {
            "balances": [
                {"asset": "USDT", "free": "10.0", "locked": "0.0"},
                {"asset": "BTC", "free": "0.01", "locked": "0.0"},
            ]
        }
        self.futures_account = {
            "availableBalance": 40.0,
            "executionAvailableBalance": 5.0,
            "totalWalletBalance": 50.0,
            "totalMarginBalance": 50.0,
        }

    def get_account(self, *, market):  # type: ignore[no-untyped-def]
        if market == "spot":
            return self.spot_account
        return self.futures_account

    def get_open_orders(self, *, market, symbol=None):  # type: ignore[no-untyped-def]
        return {"market": market, "orders": []}


class FailingSeedClient(FakeBitgetDaemonClient):
    def get_exchange_info(self, *, market):  # type: ignore[no-untyped-def]
        raise RuntimeError("seed boom")


class FakeShell:
    def __init__(self, *, ws_client_factory, session, backoff_policy, summary_path, state_path):  # type: ignore[no-untyped-def]
        self.ws_client_factory = ws_client_factory
        self.session = session
        self.backoff_policy = backoff_policy
        self.summary_path = summary_path
        self.state_path = state_path

    async def run(self) -> dict[str, object]:
        client = self.ws_client_factory()
        return {
            "status": "ok",
            "client_types": [type(item).__name__ for item in client.clients],
            "rest_sync_enabled": self.session.rest_client is not None,
        }


class SubscriptionShell(FakeShell):
    async def run(self) -> dict[str, object]:
        client = self.ws_client_factory()
        subscriptions = []
        for child in client.clients:
            if hasattr(child, "subscription_args"):
                subscriptions.extend(child.subscription_args())
        return {
            "status": "ok",
            "subscription_inst_ids": sorted({item["instId"] for item in subscriptions}),
        }


class CapitalReportShell(FakeShell):
    async def run(self) -> dict[str, object]:
        return {
            "status": "ok",
            "capital_report": self.session.capital_report,
            "account_snapshot": self.session.account_snapshot,
        }


class BootstrapContinuationShell(FakeShell):
    async def run(self) -> dict[str, object]:
        open_time = datetime(2026, 3, 14, 0, 20, tzinfo=timezone.utc)
        close_time = datetime(2026, 3, 14, 0, 25, tzinfo=timezone.utc)
        self.session.process_payload(
            {
                "stream": "btcusdt@kline_5m",
                "data": {
                    "s": "BTCUSDT",
                    "k": {
                        "i": "5m",
                        "t": int(open_time.timestamp() * 1000),
                        "T": int(close_time.timestamp() * 1000) - 1,
                        "o": "50000",
                        "h": "50100",
                        "l": "49950",
                        "c": "50080",
                        "v": "18",
                        "q": "900000",
                        "x": True,
                    },
                },
            },
            now=datetime(2026, 3, 14, 0, 25, 1, tzinfo=timezone.utc),
        )
        self.session.flush(summary_path=self.summary_path, state_path=self.state_path)
        return {
            "decision_count": len(self.session.decisions),
            "decision_timestamps": [decision.timestamp.isoformat() for decision in self.session.decisions],
            "btc_decision_timestamps": [
                decision.timestamp.isoformat()
                for decision in self.session.decisions
                if decision.symbol == "BTCUSDT"
            ],
        }


class FixedSeedNow(datetime):
    @classmethod
    def now(cls, tz=None):
        instant = cls(2026, 3, 14, 0, 22, 33, tzinfo=timezone.utc)
        if tz is None:
            return instant.replace(tzinfo=None)
        return instant.astimezone(tz)


class QuantBinanceDaemonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def test_seed_market_store_from_rest(self) -> None:
        store = seed_market_store_from_rest(
            client=FakeRestClient(),  # type: ignore[arg-type]
            symbols=("BTCUSDT",),
            intervals=("5m", "1h", "4h"),
        )
        state = store.get("BTCUSDT")
        assert state is not None
        self.assertEqual(state.last_trade_price, 50000.0)
        self.assertEqual(len(state.klines["5m"]), 100)
        self.assertEqual(len(state.klines["1h"]), 140)
        self.assertEqual(len(state.funding_rate_samples), 1)

    def test_build_live_ws_client_uses_bitget_adapter(self) -> None:
        client = _build_live_ws_client(
            exchange_id="bitget",
            symbols=("BTCUSDT",),
            allow_insecure_ssl=True,
        )

        self.assertEqual(len(client.clients), 2)
        self.assertTrue(all(isinstance(item, BitgetWebSocketClient) for item in client.clients))
        self.assertEqual(client.clients[0].subscription_args()[0], {"instType": "SPOT", "channel": "trade", "instId": "BTCUSDT"})

    def test_build_live_ws_client_shards_bitget_connections_for_large_symbol_sets(self) -> None:
        client = _build_live_ws_client(
            exchange_id="bitget",
            symbols=tuple(f"SYM{index}USDT" for index in range(20)),
            allow_insecure_ssl=True,
        )

        self.assertGreater(len(client.clients), 2)
        self.assertTrue(all(isinstance(item, BitgetWebSocketClient) for item in client.clients))
        for child in client.clients:
            self.assertLessEqual(len(child.subscription_args()), 40)

    def test_run_live_paper_daemon_starts_bitget_without_private_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            with patch("quant_binance.daemon.build_exchange_rest_client", return_value=FakeBitgetDaemonClient()):
                with patch("quant_binance.daemon.LivePaperShell", FakeShell):
                    result = run_live_paper_daemon(
                        config_path=CONFIG_PATH,
                        output_base_dir=output_dir,
                        exchange="bitget",
                        max_retries=1,
                    )

        self.assertEqual(result["summary"]["status"], "ok")
        self.assertEqual(
            result["summary"]["client_types"],
            ["BitgetWebSocketClient", "BitgetWebSocketClient"],
        )
        self.assertFalse(result["summary"]["rest_sync_enabled"])
        self.assertIn("self_healing", result["summary"])
        self.assertIn("status", result["summary"]["self_healing"])

    def test_run_live_paper_daemon_requires_credentials_for_bitget_live_orders(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            with patch("quant_binance.daemon.build_exchange_rest_client", return_value=FakeBitgetDaemonClient()):
                with self.assertRaisesRegex(RuntimeError, "BITGET_API_KEY"):
                    run_live_paper_daemon(
                        config_path=CONFIG_PATH,
                        output_base_dir=output_dir,
                        exchange="bitget",
                        execute_live_orders=True,
                    )

    def test_run_live_paper_daemon_recognizes_non_usdt_spot_assets_for_capital_adequacy(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            with patch("quant_binance.daemon.build_exchange_rest_client", return_value=FakePrivateDaemonClient()):
                with patch("quant_binance.daemon.LivePaperShell", CapitalReportShell):
                    result = run_live_paper_daemon(
                        config_path=CONFIG_PATH,
                        output_base_dir=output_dir,
                        exchange="binance",
                        max_retries=1,
                    )

        capital_report = result["summary"]["capital_report"]
        assert isinstance(capital_report, dict)
        self.assertEqual(float(capital_report["spot_available_balance_usd"]), 10.0)
        self.assertEqual(float(capital_report["spot_recognized_balance_usd"]), 509.995)
        self.assertGreater(
            float(capital_report["spot_recognized_balance_usd"]),
            float(capital_report["spot_available_balance_usd"]),
        )
        self.assertTrue(capital_report["can_trade_spot_any"])

    def test_run_live_paper_daemon_uses_futures_equity_for_adequacy_when_execution_balance_is_lower(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            with patch("quant_binance.daemon.build_exchange_rest_client", return_value=FakePrivateDaemonClient()):
                with patch("quant_binance.daemon.LivePaperShell", CapitalReportShell):
                    result = run_live_paper_daemon(
                        config_path=CONFIG_PATH,
                        output_base_dir=output_dir,
                        exchange="binance",
                        max_retries=1,
                    )

        capital_report = result["summary"]["capital_report"]
        assert isinstance(capital_report, dict)
        self.assertEqual(float(capital_report["futures_available_balance_usd"]), 5.0)
        self.assertEqual(float(capital_report["futures_recognized_balance_usd"]), 50.0)
        self.assertTrue(capital_report["can_trade_futures_any"])
        self.assertEqual(float(capital_report["futures_execution_balance_usd"]), 5.0)

    def test_run_live_paper_daemon_subscribes_only_seeded_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            config_path = Path(output_dir) / "config.json"
            config_payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            config_payload["universe"] = ["BTCUSDT", "STEEMUSDT"]
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            with patch("quant_binance.daemon.build_exchange_rest_client", return_value=FakeBitgetPartialSeedClient()):
                with patch("quant_binance.daemon.LivePaperShell", SubscriptionShell):
                    result = run_live_paper_daemon(
                        config_path=config_path,
                        output_base_dir=output_dir,
                        exchange="bitget",
                        max_retries=1,
                    )

        self.assertEqual(result["summary"]["subscription_inst_ids"], ["BTCUSDT"])

    def test_bootstrap_decision_time_uses_latest_seeded_closed_decision_kline(self) -> None:
        state = SymbolMarketState(
            symbol="BTCUSDT",
            top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.2, datetime(2026, 3, 14, 0, 22, 33, tzinfo=timezone.utc)),
            last_trade_price=50000.0,
            funding_rate=0.0001,
            open_interest=1080000.0,
            basis_bps=3.0,
            last_update_time=datetime(2026, 3, 14, 0, 22, 33, tzinfo=timezone.utc),
            klines={
                "5m": [
                    KlineBar(
                        symbol="BTCUSDT",
                        interval="5m",
                        start_time=datetime(2026, 3, 14, 0, 15, tzinfo=timezone.utc),
                        close_time=datetime(2026, 3, 14, 0, 20, tzinfo=timezone.utc),
                        open_price=50000.0,
                        high_price=50100.0,
                        low_price=49900.0,
                        close_price=50050.0,
                        volume=10.0,
                        quote_volume=500000.0,
                        is_closed=True,
                    )
                ]
            },
        )
        store = MarketStateStore()
        store.put(state)

        bootstrap_time = _bootstrap_decision_time(store=store, interval_minutes=5)

        self.assertEqual(bootstrap_time.isoformat(), "2026-03-14T00:20:00+00:00")

    def test_run_live_paper_daemon_keeps_first_live_close_after_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            config_path = Path(output_dir) / "config.json"
            config_payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            config_payload["universe"] = ["BTCUSDT"]
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            with patch("quant_binance.data.rest_seed.datetime", FixedSeedNow):
                with patch("quant_binance.daemon.build_exchange_rest_client", return_value=BootstrapTimingRestClient()):
                    with patch("quant_binance.daemon.LivePaperShell", BootstrapContinuationShell):
                        result = run_live_paper_daemon(
                            config_path=config_path,
                            output_base_dir=output_dir,
                            exchange="binance",
                            max_retries=1,
                        )

        self.assertEqual(
            result["summary"]["btc_decision_timestamps"],
            ["2026-03-14T00:20:00+00:00", "2026-03-14T00:25:00+00:00"],
        )

    def test_run_live_paper_daemon_persists_startup_failure_state(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            with patch("quant_binance.daemon.build_exchange_rest_client", return_value=FailingSeedClient()):
                with self.assertRaisesRegex(RuntimeError, "seed boom"):
                    run_live_paper_daemon(
                        config_path=CONFIG_PATH,
                        output_base_dir=output_dir,
                        exchange="bitget",
                        max_retries=1,
                    )

            latest_root = Path(output_dir) / "output" / "paper-live-shell" / "latest"
            summary = json.loads((latest_root / "summary.json").read_text(encoding="utf-8"))
            state = json.loads((latest_root / "summary.state.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["status"], "startup_failed")
        self.assertIn("seed boom", summary["error"])
        self.assertEqual(summary["self_healing"]["status"], "startup_failed")
        self.assertEqual(state["status"], "startup_failed")
        self.assertIn("seed boom", state["error"])
        self.assertEqual(state["decision_count"], 0)
        self.assertEqual(state["heartbeat_count"], 0)

    def test_run_live_paper_daemon_keeps_previous_runs_when_startup_fails_before_first_flush(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            config_path = Path(output_dir) / "config.json"
            config_payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            config_payload["housekeeping"]["keep_recent_runs"] = 1
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")

            mode_root = Path(output_dir) / "output" / "paper-live-shell"
            older_run = mode_root / "20260313-older"
            newer_run = mode_root / "20260313-newer"
            older_run.mkdir(parents=True, exist_ok=True)
            newer_run.mkdir(parents=True, exist_ok=True)
            write_runtime_summary(older_run / "summary.json", {"status": "older"})
            write_runtime_state(older_run / "summary.state.json", {"heartbeat_count": 1})
            write_runtime_summary(newer_run / "summary.json", {"status": "newer"})
            write_runtime_state(newer_run / "summary.state.json", {"heartbeat_count": 2})

            with patch("quant_binance.daemon.build_exchange_rest_client", return_value=FailingSeedClient()):
                with self.assertRaisesRegex(RuntimeError, "seed boom"):
                    run_live_paper_daemon(
                        config_path=config_path,
                        output_base_dir=output_dir,
                        exchange="bitget",
                        max_retries=1,
                    )

            self.assertTrue(older_run.exists())
            self.assertTrue(newer_run.exists())


if __name__ == "__main__":
    unittest.main()
