from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.binance_rest import BinanceCredentials, BinanceRestClient
from quant_binance.execution.bitget_rest import BitgetRestClient
from quant_binance.execution.router import ExecutionRouter
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.service import PaperTradingService
from quant_binance.session import LivePaperSession
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class QuantBinanceTransferSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def test_binance_builds_universal_transfer_request(self) -> None:
        client = BinanceRestClient(
            credentials=BinanceCredentials(api_key="key", api_secret="secret"),
        )

        request = client.build_asset_transfer_request(
            source_market="spot",
            target_market="futures",
            asset="USDT",
            amount=12.5,
        )

        parsed = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(parsed["type"], ["MAIN_UMFUTURE"])
        self.assertEqual(parsed["asset"], ["USDT"])
        self.assertEqual(parsed["amount"], ["12.50000000"])

    def test_bitget_builds_wallet_transfer_request(self) -> None:
        client = BitgetRestClient(
            credentials=type(
                "Creds",
                (),
                {"api_key": "key", "api_secret": "secret", "api_passphrase": "pass"},
            )(),
        )

        request = client.build_wallet_transfer_request(
            source_market="spot",
            target_market="futures",
            asset="USDT",
            amount=7.5,
            client_oid="transfer-1",
        )

        self.assertEqual(request.full_url, "https://api.bitget.com/api/v2/spot/wallet/transfer")
        assert request.data is not None
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["fromType"], "spot")
        self.assertEqual(payload["toType"], "usdt_futures")
        self.assertEqual(payload["coin"], "USDT")
        self.assertEqual(payload["amount"], "7.50000000")
        self.assertEqual(payload["clientOid"], "transfer-1")

    def test_live_entry_preflight_capacity_rejection_uses_order_cooldown(self) -> None:
        class RejectingLiveExecutor:
            def __init__(self) -> None:
                self.rejection = {
                    "symbol": "BTCUSDT",
                    "market": "futures",
                    "reason": "BITGET_MAX_OPEN_ZERO",
                    "message": "Bitget preflight rejected order because max openable quantity is 0.",
                }

            def _exchange_id(self) -> str:
                return "bitget"

            def execute_decision(self, *, decision, reference_price):  # type: ignore[no-untyped-def]
                return None

            def pop_last_preflight_rejection(self):  # type: ignore[no-untyped-def]
                rejection = dict(self.rejection)
                self.rejection = None
                return rejection

        from quant_binance.models import DecisionIntent

        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(MarketStateStore()),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: None,
            history_provider=lambda symbol, decision_time: None,
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        now = datetime(2026, 3, 16, 0, 5, tzinfo=timezone.utc)
        state = SymbolMarketState(
            symbol="BTCUSDT",
            top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.2, now),
            last_trade_price=50000.0,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=3.0,
            last_update_time=now,
        )
        runtime.dispatcher.store.put(state)
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            live_order_executor=RejectingLiveExecutor(),  # type: ignore[arg-type]
        )
        session.order_tester = None
        session._refresh_account_state_after_live_order_activity = Mock()  # type: ignore[method-assign]

        decision = DecisionIntent(
            decision_id="d-preflight",
            decision_hash="hash-preflight",
            snapshot_id="s-preflight",
            config_version="2026-03-16.v1",
            timestamp=now,
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=86.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=95.0,
            stop_distance_bps=45.0,
        )

        session._record_decision(decision=decision, state=state, timestamp=now)

        self.assertIn("BTCUSDT", session.order_error_cooldowns)
        self.assertNotIn("BTCUSDT", session.manual_symbol_cooldowns)
        session._refresh_account_state_after_live_order_activity.assert_called_once_with(
            symbol="BTCUSDT",
            timestamp=now,
            stage="live_order_preflight",
            reason="preflight_capacity",
        )


if __name__ == "__main__":
    unittest.main()
