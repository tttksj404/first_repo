from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FeatureVector:
    ret_rank_1h: float
    ret_rank_4h: float
    breakout_norm: float
    ema_stack_score: float
    vol_z_5m_norm: float
    vol_z_1h_norm: float
    taker_imbalance_norm: float
    spread_bps_norm: float
    probe_slippage_bps_norm: float
    depth_10bps_norm: float
    book_stability_norm: float
    realized_vol_1h_norm: float
    realized_vol_4h_norm: float
    vol_shock_norm: float
    funding_abs_percentile: float
    oi_surge_percentile: float
    basis_stretch_percentile: float
    regime_alignment: float
    trend_direction: int
    trend_strength: float
    volume_confirmation: float
    liquidity_score: float
    volatility_penalty: float
    overheat_penalty: float
    support_alignment: float = 0.0
    resistance_penalty: float = 0.0
    macro_regime: str = "neutral"
    macro_risk_penalty: float = 0.0
    sentiment_regime: str = "neutral"
    sentiment_support_score: float = 0.5
    alt_market_regime: str = "neutral"
    alt_breadth_score: float = 0.5
    alt_liquidity_support_score: float = 0.5
    alt_fundamental_score: float = 0.5
    alt_smart_money_score: float = 0.5
    alt_rotation_penalty: float = 0.0
    predictability_score: float = 0.0
    gross_expected_edge_bps: float = 0.0
    net_expected_edge_bps: float = 0.0
    estimated_round_trip_cost_bps: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MarketSnapshot:
    snapshot_id: str
    config_version: str
    snapshot_schema_version: str
    symbol: str
    decision_time: datetime
    last_trade_price: float
    best_bid: float
    best_ask: float
    funding_rate: float
    open_interest: float
    basis_bps: float
    data_freshness_ms: int
    feature_values: FeatureVector

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decision_time"] = self.decision_time.isoformat()
        return data


@dataclass(frozen=True)
class DecisionIntent:
    decision_id: str
    decision_hash: str
    snapshot_id: str
    config_version: str
    timestamp: datetime
    symbol: str
    candidate_mode: str
    final_mode: str
    side: str
    trend_direction: int
    trend_strength: float
    volume_confirmation: float
    liquidity_score: float
    volatility_penalty: float
    overheat_penalty: float
    predictability_score: float
    gross_expected_edge_bps: float
    net_expected_edge_bps: float
    estimated_round_trip_cost_bps: float
    order_intent_notional_usd: float
    stop_distance_bps: float
    linked_order_ids: tuple[str, ...] = field(default_factory=tuple)
    rejection_reasons: tuple[str, ...] = field(default_factory=tuple)
    exit_reason_code: str = ""
    divergence_code: str = ""

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data
