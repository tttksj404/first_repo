from __future__ import annotations

from dataclasses import replace

from quant_binance.models import FeatureVector
from quant_binance.settings import Settings


def _directional_flow_alignment(features: FeatureVector) -> float:
    if features.trend_direction == 0:
        return 0.0
    return max(features.trend_direction * (features.taker_imbalance_norm - 0.5), 0.0) * 2.0


def compute_predictability_score(features: FeatureVector, settings: Settings) -> float:
    weights = settings.weights
    score = 100.0 * (
        weights.trend_strength * features.trend_strength
        + weights.volume_confirmation * features.volume_confirmation
        + weights.liquidity_score * features.liquidity_score
        + weights.regime_alignment * features.regime_alignment
        + weights.inverse_volatility_penalty * (1.0 - features.volatility_penalty)
        + weights.inverse_overheat_penalty * (1.0 - features.overheat_penalty)
    )
    if features.intraday_trend_direction != 0 and features.intraday_trend_direction == features.trend_direction:
        score += 8.0 * features.intraday_trend_strength
    return round(score, 6)


def estimate_round_trip_cost_bps(
    mode: str,
    settings: Settings,
    expected_entry_slippage_bps: float,
    expected_exit_slippage_bps: float,
    expected_funding_drag_bps: float = 0.0,
    empirical_fee_bps: float = 0.0,
) -> float:
    fees = settings.fees
    if mode == "futures":
        entry_fee_bps = max(fees.futures_taker_fee_bps, empirical_fee_bps)
        exit_fee_bps = max(fees.futures_taker_fee_bps, empirical_fee_bps)
        funding_drag_bps = expected_funding_drag_bps
    elif mode == "spot":
        entry_fee_bps = max(fees.spot_taker_fee_bps, empirical_fee_bps)
        exit_fee_bps = max(fees.spot_taker_fee_bps, empirical_fee_bps)
        funding_drag_bps = 0.0
    else:
        return 0.0

    total = (
        entry_fee_bps
        + exit_fee_bps
        + expected_entry_slippage_bps
        + expected_exit_slippage_bps
        + funding_drag_bps
    )
    return round(total, 6)


def estimate_live_fallback_edge_bps(
    *,
    features: FeatureVector,
    settings: Settings,
    mode: str,
) -> float:
    entry_threshold = (
        settings.mode_thresholds.futures_score_min
        if mode == "futures"
        else settings.mode_thresholds.spot_score_min
    )
    score = compute_predictability_score(features, settings)
    excess_score = max(score - entry_threshold, 0.0)

    quality_base = (
        0.8 * excess_score
        + 8.0 * features.trend_strength
        + 7.0 * features.volume_confirmation
        + 8.0 * features.liquidity_score
        + 4.0 * features.regime_alignment
    )
    structure_bonus = (
        4.0 * features.breakout_norm
        + 4.0 * features.ema_stack_score
        + 3.0 * features.taker_imbalance_norm
        + 5.0 * features.support_alignment
        + 4.0 * features.sentiment_support_score
        + 8.0 * max(features.alt_breadth_score - 0.5, 0.0)
        + 7.0 * max(features.alt_liquidity_support_score - 0.5, 0.0)
        + 6.0 * max(features.alt_fundamental_score - 0.5, 0.0)
        + 7.0 * max(features.alt_smart_money_score - 0.5, 0.0)
    )
    risk_penalty = (
        8.0 * features.volatility_penalty
        + 10.0 * features.overheat_penalty
        + 4.0 * features.resistance_penalty
        + 8.0 * features.macro_risk_penalty
        + 5.0 * features.macro_event_risk_score
        + 10.0 * features.alt_rotation_penalty
    )

    if mode == "futures":
        directional_flow_alignment = _directional_flow_alignment(features)
        raw = (
            quality_base
            + 2.0 * features.breakout_norm
            + 10.0 * directional_flow_alignment
            + 6.0 * features.intraday_trend_strength
            + 8.0 * max(features.macro_liquidity_support_score - 0.5, 0.0)
            - risk_penalty
        )
    else:
        spot_accumulation_bonus = (
            6.0 * features.support_alignment
            + 4.0 * max(features.sentiment_support_score - 0.5, 0.0) * 2.0
            + 3.0 * max(1.0 - features.overheat_penalty, 0.0)
            + 4.0 * max(features.macro_liquidity_support_score - 0.5, 0.0)
        )
        raw = (
            quality_base
            + structure_bonus
            + spot_accumulation_bonus
            - 0.75 * risk_penalty
        )
    if mode == "futures" and features.trend_direction == 0:
        raw = 0.0
    if mode == "spot" and features.trend_direction < 0:
        raw = 0.0
    return round(max(raw, 0.0), 6)


def apply_score_and_costs(
    features: FeatureVector,
    settings: Settings,
    mode: str,
    expected_entry_slippage_bps: float | None = None,
    expected_exit_slippage_bps: float | None = None,
    expected_funding_drag_bps: float = 0.0,
) -> FeatureVector:
    fallback_gross_edge = estimate_live_fallback_edge_bps(
        features=features,
        settings=settings,
        mode=mode,
    )
    learned_gross_edge = features.gross_expected_edge_bps if features.gross_expected_edge_bps > 0 else 0.0
    gross_edge = round(max(learned_gross_edge, fallback_gross_edge), 6)

    if features.estimated_round_trip_cost_bps > 0:
        score = compute_predictability_score(features, settings)
        return replace(
            features,
            predictability_score=score,
            gross_expected_edge_bps=gross_edge,
            net_expected_edge_bps=round(
                gross_edge - features.estimated_round_trip_cost_bps,
                6,
            ),
        )

    entry_slippage = (
        expected_entry_slippage_bps
        if expected_entry_slippage_bps is not None
        else features.probe_slippage_bps_norm * settings.feature_thresholds.slippage_bps_ceiling
    )
    entry_slippage = max(entry_slippage, features.empirical_entry_slippage_bps)
    exit_slippage = (
        expected_exit_slippage_bps
        if expected_exit_slippage_bps is not None
        else entry_slippage
    )
    exit_slippage = max(exit_slippage, features.empirical_exit_slippage_bps)
    score = compute_predictability_score(features, settings)
    round_trip_cost = estimate_round_trip_cost_bps(
        mode=mode,
        settings=settings,
        expected_entry_slippage_bps=entry_slippage,
        expected_exit_slippage_bps=exit_slippage,
        expected_funding_drag_bps=expected_funding_drag_bps,
        empirical_fee_bps=features.empirical_fee_bps,
    )
    return replace(
        features,
        predictability_score=score,
        gross_expected_edge_bps=gross_edge,
        estimated_round_trip_cost_bps=round_trip_cost,
        net_expected_edge_bps=round(gross_edge - round_trip_cost, 6),
    )


def passes_cost_gate(features: FeatureVector, settings: Settings) -> bool:
    return (
        features.gross_expected_edge_bps
        >= settings.cost_gate.edge_to_cost_multiple_min
        * features.estimated_round_trip_cost_bps
    )
