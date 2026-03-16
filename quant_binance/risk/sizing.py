from __future__ import annotations

import math

from quant_binance.settings import Settings


def _edge_to_cost_multiple(net_expected_edge_bps: float, estimated_round_trip_cost_bps: float) -> float:
    if estimated_round_trip_cost_bps <= 0:
        return float("inf")
    return net_expected_edge_bps / estimated_round_trip_cost_bps


def select_futures_leverage(
    *,
    predictability_score: float,
    trend_strength: float,
    volume_confirmation: float,
    liquidity_score: float,
    volatility_penalty: float,
    overheat_penalty: float,
    net_expected_edge_bps: float,
    estimated_round_trip_cost_bps: float,
    settings: Settings,
) -> int:
    thresholds = settings.mode_thresholds
    exposure = settings.futures_exposure
    risk = settings.risk
    target_leverage = max(1, min(int(math.ceil(risk.target_futures_leverage)), int(math.ceil(risk.max_futures_leverage))))
    max_leverage = max(target_leverage, int(math.ceil(risk.max_futures_leverage)))
    soft_leverage = max(1, target_leverage - 1)
    edge_to_cost_multiple = _edge_to_cost_multiple(
        net_expected_edge_bps=net_expected_edge_bps,
        estimated_round_trip_cost_bps=estimated_round_trip_cost_bps,
    )
    strong_setup = (
        predictability_score >= max(thresholds.futures_score_min + exposure.strong_score_buffer + 12.0, 72.0)
        and trend_strength >= max(exposure.strong_trend_strength_min, 0.8)
        and volume_confirmation >= max(exposure.strong_volume_confirmation_min, 0.72)
        and liquidity_score >= max(exposure.strong_liquidity_min, 0.82)
        and volatility_penalty <= min(exposure.strong_volatility_penalty_max + 0.02, 0.35)
        and overheat_penalty <= min(exposure.strong_overheat_penalty_max + 0.02, 0.3)
        and net_expected_edge_bps >= max(exposure.min_entry_net_edge_bps + 8.0, 12.0)
        and edge_to_cost_multiple >= max(exposure.strong_edge_to_cost_multiple_min, 1.8)
    )
    soft_setup = (
        predictability_score < thresholds.futures_score_min + 2.0
        or trend_strength < thresholds.futures_trend_strength_min + 0.04
        or volume_confirmation < 0.58
        or liquidity_score < thresholds.futures_liquidity_min + 0.02
        or volatility_penalty > thresholds.futures_volatility_penalty_max
        or overheat_penalty > thresholds.futures_overheat_penalty_max
        or net_expected_edge_bps < max(exposure.reduced_entry_net_edge_bps, 4.0)
        or edge_to_cost_multiple < max(1.25, settings.cost_gate.edge_to_cost_multiple_min - 0.1)
    )
    if strong_setup:
        return max_leverage
    if soft_setup:
        return soft_leverage
    return target_leverage


def position_notional_and_stop_bps(
    *,
    last_trade_price: float,
    atr_14_1h_bps: float,
    equity_usd: float,
    remaining_portfolio_capacity_usd: float,
    settings: Settings,
    size_multiplier: float = 1.0,
    leverage_multiplier: float = 1.0,
) -> tuple[float, float]:
    stop_distance_bps = max(
        settings.sizing.atr_multiple_for_stop * atr_14_1h_bps,
        settings.sizing.stop_floor_bps,
    )
    risk_dollars = equity_usd * settings.risk.per_trade_equity_risk
    adjusted_size_multiplier = max(size_multiplier, 0.0)
    adjusted_leverage_multiplier = max(leverage_multiplier, 1.0)
    raw_notional_usd = (
        risk_dollars / (stop_distance_bps / 10000.0) * adjusted_size_multiplier
    )
    symbol_cap_multiplier = max(adjusted_size_multiplier, 1.0)
    capped_notional = min(
        raw_notional_usd,
        equity_usd
        * settings.risk.max_symbol_notional_fraction
        * symbol_cap_multiplier
        * adjusted_leverage_multiplier,
        remaining_portfolio_capacity_usd,
    )
    return round(capped_notional, 6), round(stop_distance_bps, 6)


def quantity_from_notional(notional_usd: float, reference_price: float) -> float:
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")
    return round(notional_usd / reference_price, 8)
