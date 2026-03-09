from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from quant_binance.models import DecisionIntent, FeatureVector, MarketSnapshot
from quant_binance.observability.decision_log import hash_decision_payload
from quant_binance.risk.sizing import position_notional_and_stop_bps
from quant_binance.overlays import is_alt_symbol
from quant_binance.settings import Settings
from quant_binance.strategy.scorer import apply_score_and_costs, passes_cost_gate


def _candidate_mode(features: FeatureVector, settings: Settings) -> str:
    if features.predictability_score >= settings.mode_thresholds.futures_score_min:
        return "futures"
    if features.predictability_score >= settings.mode_thresholds.spot_score_min:
        return "spot"
    return "cash"


def _observe_only_reasons(features: FeatureVector, settings: Settings, symbol: str) -> tuple[bool, list[str]]:
    if not is_alt_symbol(symbol):
        return False, []
    rules = settings.symbol_eligibility
    if (
        features.estimated_round_trip_cost_bps >= rules.observe_only_cost_bps_min
        and (
            features.liquidity_score <= rules.observe_only_liquidity_max
            or features.alt_liquidity_support_score <= rules.observe_only_alt_liquidity_max
        )
    ):
        return True, ["OBSERVE_ONLY_SYMBOL", "LIQUIDITY_TOO_WEAK"]
    return False, []


def observe_only_reasons(features: FeatureVector, settings: Settings, symbol: str) -> tuple[str, ...]:
    observe_only, reasons = _observe_only_reasons(features, settings, symbol)
    if not observe_only:
        return ()
    return tuple(reasons)


def _futures_passes(features: FeatureVector, settings: Settings, symbol: str) -> tuple[bool, list[str]]:
    thresholds = settings.mode_thresholds
    macro_gates = settings.macro_gates
    reasons: list[str] = []
    if features.predictability_score < thresholds.futures_score_min:
        reasons.append("SCORE_TOO_LOW")
    if abs(features.trend_direction) != 1:
        reasons.append("DIRECTION_CONFLICT")
    if features.trend_strength < thresholds.futures_trend_strength_min:
        reasons.append("SCORE_TOO_LOW")
    if features.liquidity_score < thresholds.futures_liquidity_min:
        reasons.append("LIQUIDITY_TOO_WEAK")
    if features.volatility_penalty > thresholds.futures_volatility_penalty_max:
        reasons.append("VOL_TOO_HIGH")
    if features.overheat_penalty > thresholds.futures_overheat_penalty_max:
        reasons.append("FUTURES_OVERHEAT")
    if features.macro_risk_penalty >= macro_gates.futures_block_penalty:
        reasons.append("MACRO_RISK_HIGH")
    if features.sentiment_regime == "caution":
        reasons.append("SENTIMENT_CAUTION")
    if is_alt_symbol(symbol):
        if features.alt_market_regime == "defensive":
            reasons.append("ALT_REGIME_DEFENSIVE")
        if features.alt_liquidity_support_score < settings.altcoin_overlays.liquidity_floor:
            reasons.append("ALT_LIQUIDITY_WEAK")
        if features.alt_smart_money_score < settings.altcoin_overlays.smart_money_floor:
            reasons.append("ALT_FLOW_WEAK")
        if features.alt_rotation_penalty >= settings.altcoin_overlays.rotation_block_penalty:
            reasons.append("ALT_ROTATION_HEADWIND")
    if not passes_cost_gate(features, settings):
        reasons.append("EDGE_BELOW_COST")
    return not reasons, reasons


def _spot_passes(features: FeatureVector, settings: Settings, symbol: str) -> tuple[bool, list[str]]:
    thresholds = settings.mode_thresholds
    macro_gates = settings.macro_gates
    support_cfg = settings.spot_support
    mode_behavior = settings.mode_behavior
    reasons: list[str] = []

    can_bottom_fish = (
        mode_behavior.spot_allow_bottoming_reversal
        and features.sentiment_regime == "bottoming"
        and features.support_alignment >= support_cfg.bottoming_support_override_min
        and features.macro_risk_penalty < macro_gates.spot_block_penalty
        and features.alt_rotation_penalty < settings.altcoin_overlays.rotation_block_penalty
    )

    if features.predictability_score < thresholds.spot_score_min:
        reasons.append("SCORE_TOO_LOW")
    if mode_behavior.spot_require_positive_trend:
        if features.trend_direction != 1:
            reasons.append("DIRECTION_CONFLICT")
    elif features.trend_direction == -1:
        if not can_bottom_fish:
            reasons.append("DIRECTION_CONFLICT")
    if features.trend_strength < thresholds.spot_trend_strength_min:
        reasons.append("SCORE_TOO_LOW")
    liquidity_override = (
        features.liquidity_score >= thresholds.spot_liquidity_min - support_cfg.liquidity_relaxation
        and features.net_expected_edge_bps > 0.0
        and (
            features.alt_liquidity_support_score >= 0.5
            or features.sentiment_support_score >= 0.55
            or symbol in {"BTCUSDT", "ETHUSDT"}
        )
    )
    if features.liquidity_score < thresholds.spot_liquidity_min and not liquidity_override:
        reasons.append("LIQUIDITY_TOO_WEAK")
    if features.volatility_penalty > thresholds.spot_volatility_penalty_max:
        reasons.append("VOL_TOO_HIGH")
    if features.support_alignment < support_cfg.support_alignment_min:
        reasons.append("SUPPORT_NOT_CONFIRMED")
    resistance_override = (
        features.breakout_norm >= support_cfg.breakout_resistance_override_min
        and features.volume_confirmation >= 0.6
        and features.net_expected_edge_bps > 0.0
        and features.trend_direction >= 0
    )
    if features.resistance_penalty > support_cfg.resistance_penalty_max and not resistance_override:
        reasons.append("BUYING_INTO_RESISTANCE")
    if features.macro_risk_penalty >= macro_gates.spot_block_penalty:
        reasons.append("MACRO_RISK_HIGH")
    if features.sentiment_support_score < support_cfg.sentiment_support_min:
        reasons.append("SENTIMENT_TOO_WEAK")
    if is_alt_symbol(symbol):
        if features.alt_market_regime == "defensive":
            reasons.append("ALT_REGIME_DEFENSIVE")
        if features.alt_breadth_score < settings.altcoin_overlays.breadth_floor:
            reasons.append("ALT_BREADTH_WEAK")
        if features.alt_liquidity_support_score < settings.altcoin_overlays.liquidity_floor:
            reasons.append("ALT_LIQUIDITY_WEAK")
        if features.alt_rotation_penalty >= settings.altcoin_overlays.rotation_block_penalty:
            reasons.append("ALT_ROTATION_HEADWIND")
    edge_gate_failed = not passes_cost_gate(features, settings)
    spot_accumulation_override = (
        features.support_alignment >= max(support_cfg.support_alignment_min, 0.34)
        and features.resistance_penalty <= min(support_cfg.resistance_penalty_max, 0.35)
        and features.sentiment_support_score >= max(support_cfg.sentiment_support_min, 0.35)
        and features.macro_risk_penalty < macro_gates.spot_block_penalty
        and features.net_expected_edge_bps > -5.0
    )
    if edge_gate_failed and not spot_accumulation_override:
        reasons.append("EDGE_BELOW_COST")
    return not reasons, reasons


def evaluate_snapshot(
    snapshot: MarketSnapshot,
    settings: Settings,
    equity_usd: float,
    remaining_portfolio_capacity_usd: float,
    expected_funding_drag_bps: float = 0.0,
    cash_reserve_fraction: float = 0.0,
) -> DecisionIntent:
    futures_features = apply_score_and_costs(
        snapshot.feature_values,
        settings=settings,
        mode="futures",
        expected_funding_drag_bps=expected_funding_drag_bps,
    )
    spot_features = apply_score_and_costs(
        snapshot.feature_values,
        settings=settings,
        mode="spot",
    )
    candidate_mode = _candidate_mode(futures_features, settings)
    now = snapshot.decision_time

    observe_only, observe_reasons = _observe_only_reasons(spot_features, settings, snapshot.symbol)
    if observe_only:
        cash_reasons = tuple(sorted(set(observe_reasons)))
        payload = {
            "snapshot_id": snapshot.snapshot_id,
            "config_version": settings.config_version,
            "final_mode": "cash",
            "side": "flat",
            "predictability_score": spot_features.predictability_score,
            "reasons": cash_reasons,
        }
        return DecisionIntent(
            decision_id=str(uuid4()),
            decision_hash=hash_decision_payload(payload),
            snapshot_id=snapshot.snapshot_id,
            config_version=settings.config_version,
            timestamp=now,
            symbol=snapshot.symbol,
            candidate_mode=candidate_mode,
            final_mode="cash",
            side="flat",
            trend_direction=spot_features.trend_direction,
            trend_strength=spot_features.trend_strength,
            volume_confirmation=spot_features.volume_confirmation,
            liquidity_score=spot_features.liquidity_score,
            volatility_penalty=spot_features.volatility_penalty,
            overheat_penalty=spot_features.overheat_penalty,
            predictability_score=spot_features.predictability_score,
            gross_expected_edge_bps=spot_features.gross_expected_edge_bps,
            net_expected_edge_bps=spot_features.net_expected_edge_bps,
            estimated_round_trip_cost_bps=spot_features.estimated_round_trip_cost_bps,
            order_intent_notional_usd=0.0,
            stop_distance_bps=0.0,
            rejection_reasons=cash_reasons,
        )

    futures_ok, futures_reasons = _futures_passes(futures_features, settings, snapshot.symbol)
    if futures_ok:
        notional, stop_distance_bps = position_notional_and_stop_bps(
            last_trade_price=snapshot.last_trade_price,
            atr_14_1h_bps=snapshot.feature_values.realized_vol_1h_norm * 100.0,
            equity_usd=equity_usd,
            remaining_portfolio_capacity_usd=remaining_portfolio_capacity_usd,
            settings=settings,
        )
        if equity_usd > 0 and (equity_usd - notional) / equity_usd < cash_reserve_fraction:
            futures_ok = False
            futures_reasons.append("CASH_RESERVE_BLOCK")
        payload = {
            "snapshot_id": snapshot.snapshot_id,
            "config_version": settings.config_version,
            "final_mode": "futures",
            "side": "long" if futures_features.trend_direction > 0 else "short",
            "predictability_score": futures_features.predictability_score,
        }
        return DecisionIntent(
            decision_id=str(uuid4()),
            decision_hash=hash_decision_payload(payload),
            snapshot_id=snapshot.snapshot_id,
            config_version=settings.config_version,
            timestamp=now,
            symbol=snapshot.symbol,
            candidate_mode=candidate_mode,
            final_mode="futures",
            side="long" if futures_features.trend_direction > 0 else "short",
            trend_direction=futures_features.trend_direction,
            trend_strength=futures_features.trend_strength,
            volume_confirmation=futures_features.volume_confirmation,
            liquidity_score=futures_features.liquidity_score,
            volatility_penalty=futures_features.volatility_penalty,
            overheat_penalty=futures_features.overheat_penalty,
            predictability_score=futures_features.predictability_score,
            gross_expected_edge_bps=futures_features.gross_expected_edge_bps,
            net_expected_edge_bps=futures_features.net_expected_edge_bps,
            estimated_round_trip_cost_bps=futures_features.estimated_round_trip_cost_bps,
            order_intent_notional_usd=notional,
            stop_distance_bps=stop_distance_bps,
        )

    spot_ok, spot_reasons = _spot_passes(spot_features, settings, snapshot.symbol)
    if spot_ok:
        notional, stop_distance_bps = position_notional_and_stop_bps(
            last_trade_price=snapshot.last_trade_price,
            atr_14_1h_bps=snapshot.feature_values.realized_vol_1h_norm * 100.0,
            equity_usd=equity_usd,
            remaining_portfolio_capacity_usd=remaining_portfolio_capacity_usd,
            settings=settings,
        )
        if equity_usd > 0 and (equity_usd - notional) / equity_usd < cash_reserve_fraction:
            spot_ok = False
            spot_reasons.append("CASH_RESERVE_BLOCK")
    if spot_ok:
        payload = {
            "snapshot_id": snapshot.snapshot_id,
            "config_version": settings.config_version,
            "final_mode": "spot",
            "side": "long",
            "predictability_score": spot_features.predictability_score,
        }
        return DecisionIntent(
            decision_id=str(uuid4()),
            decision_hash=hash_decision_payload(payload),
            snapshot_id=snapshot.snapshot_id,
            config_version=settings.config_version,
            timestamp=now,
            symbol=snapshot.symbol,
            candidate_mode=candidate_mode,
            final_mode="spot",
            side="long",
            trend_direction=spot_features.trend_direction,
            trend_strength=spot_features.trend_strength,
            volume_confirmation=spot_features.volume_confirmation,
            liquidity_score=spot_features.liquidity_score,
            volatility_penalty=spot_features.volatility_penalty,
            overheat_penalty=spot_features.overheat_penalty,
            predictability_score=spot_features.predictability_score,
            gross_expected_edge_bps=spot_features.gross_expected_edge_bps,
            net_expected_edge_bps=spot_features.net_expected_edge_bps,
            estimated_round_trip_cost_bps=spot_features.estimated_round_trip_cost_bps,
            order_intent_notional_usd=notional,
            stop_distance_bps=stop_distance_bps,
            rejection_reasons=tuple(sorted(set(futures_reasons))),
        )

    cash_reasons = tuple(sorted(set(futures_reasons + spot_reasons))) or ("SCORE_TOO_LOW",)
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "config_version": settings.config_version,
        "final_mode": "cash",
        "side": "flat",
        "predictability_score": spot_features.predictability_score,
        "reasons": cash_reasons,
    }
    return DecisionIntent(
        decision_id=str(uuid4()),
        decision_hash=hash_decision_payload(payload),
        snapshot_id=snapshot.snapshot_id,
        config_version=settings.config_version,
        timestamp=now,
        symbol=snapshot.symbol,
        candidate_mode=candidate_mode,
        final_mode="cash",
        side="flat",
        trend_direction=spot_features.trend_direction,
        trend_strength=spot_features.trend_strength,
        volume_confirmation=spot_features.volume_confirmation,
        liquidity_score=spot_features.liquidity_score,
        volatility_penalty=spot_features.volatility_penalty,
        overheat_penalty=spot_features.overheat_penalty,
        predictability_score=spot_features.predictability_score,
        gross_expected_edge_bps=spot_features.gross_expected_edge_bps,
        net_expected_edge_bps=spot_features.net_expected_edge_bps,
        estimated_round_trip_cost_bps=spot_features.estimated_round_trip_cost_bps,
        order_intent_notional_usd=0.0,
        stop_distance_bps=0.0,
        rejection_reasons=cash_reasons,
    )
