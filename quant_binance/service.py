from __future__ import annotations

from datetime import datetime

from quant_binance.data.snapshot_builder import SnapshotBuilder
from quant_binance.data.state import SymbolMarketState
from quant_binance.execution.router import ExecutionRouter
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs, build_feature_vector_from_primitives
from quant_binance.features.extractor import MarketFeatureExtractor
from quant_binance.models import DecisionIntent
from quant_binance.overlays import (
    apply_altcoin_overlay,
    apply_macro_overlay,
    apply_sentiment_overlay,
    load_altcoin_inputs,
    load_macro_inputs,
)
from quant_binance.settings import Settings
from quant_binance.strategy.edge import ConditionalEdgeLookup
from quant_binance.strategy.regime import evaluate_snapshot


class PaperTradingService:
    def __init__(
        self,
        settings: Settings,
        router: ExecutionRouter | None = None,
        edge_lookup: ConditionalEdgeLookup | None = None,
    ) -> None:
        self.edge_lookup = edge_lookup
        self.settings = settings
        self.snapshot_builder = SnapshotBuilder(settings)
        self.router = router or ExecutionRouter()
        self.feature_extractor = MarketFeatureExtractor(settings, edge_lookup=edge_lookup)

    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.snapshot_builder = SnapshotBuilder(settings)
        self.feature_extractor = MarketFeatureExtractor(settings, edge_lookup=self.edge_lookup)

    def run_cycle(
        self,
        *,
        state: SymbolMarketState,
        primitive_inputs: PrimitiveInputs,
        history: FeatureHistoryContext,
        decision_time: datetime,
        equity_usd: float,
        remaining_portfolio_capacity_usd: float,
        cash_reserve_fraction: float = 0.0,
    ) -> DecisionIntent:
        features = build_feature_vector_from_primitives(
            inputs=primitive_inputs,
            history=history,
            settings=self.settings,
        )
        features = self.feature_extractor.enrich_feature_vector(
            state=state,
            features=features,
        )
        features = apply_macro_overlay(features, load_macro_inputs())
        features = apply_altcoin_overlay(
            features,
            symbol=state.symbol,
            altcoin_inputs=load_altcoin_inputs(),
        )
        features = apply_sentiment_overlay(features)
        snapshot = self.snapshot_builder.build(state, features, decision_time)
        decision = evaluate_snapshot(
            snapshot,
            settings=self.settings,
            equity_usd=equity_usd,
            remaining_portfolio_capacity_usd=remaining_portfolio_capacity_usd,
            cash_reserve_fraction=cash_reserve_fraction,
        )
        self.router.route(decision)
        return decision
