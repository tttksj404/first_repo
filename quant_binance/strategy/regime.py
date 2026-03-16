from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from quant_binance.models import DecisionIntent, FeatureVector, MarketSnapshot
from quant_binance.observability.decision_log import hash_decision_payload
from quant_binance.risk.sizing import position_notional_and_stop_bps, select_futures_leverage
from quant_binance.overlays import is_alt_symbol
from quant_binance.settings import Settings
from quant_binance.strategy.scorer import apply_score_and_costs, passes_cost_gate


FUTURES_SOFT_RISK_REASONS = {"SCORE_TOO_LOW", "LIQUIDITY_TOO_WEAK", "VOL_TOO_HIGH", "FUTURES_OVERHEAT", "EDGE_BELOW_COST", "SENTIMENT_CAUTION"}


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


def _edge_to_cost_multiple(features: FeatureVector) -> float:
    if features.estimated_round_trip_cost_bps <= 0:
        return float("inf")
    return features.gross_expected_edge_bps / features.estimated_round_trip_cost_bps


def _macro_risk_off(features: FeatureVector) -> bool:
    return features.macro_event_risk_score >= 0.6 or features.macro_risk_penalty >= 0.55 or features.macro_regime == "high_risk"


def _macro_event_halt(features: FeatureVector) -> bool:
    return features.macro_trade_restraint == "halt_high_impact_window" or features.macro_event_risk_score >= 0.85


def _macro_symbol_bias_reasons(features: FeatureVector, *, symbol: str) -> list[str]:
    if not is_alt_symbol(symbol):
        return []
    if _macro_event_halt(features):
        return ["MACRO_EVENT_WINDOW", "MACRO_MAJORS_ONLY"]
    if _macro_risk_off(features):
        return ["MACRO_MAJORS_ONLY"]
    return []


def _macro_futures_risk_controls(features: FeatureVector, *, symbol: str) -> tuple[bool, list[str], float, int]:
    reasons = _macro_symbol_bias_reasons(features, symbol=symbol)
    size_multiplier = max(features.macro_size_multiplier, 0.0)
    leverage_cap = max(int(features.macro_leverage_cap), 0)
    if _macro_event_halt(features):
        if is_alt_symbol(symbol):
            return False, reasons, 0.0, max(leverage_cap, 1)
        return True, [], min(size_multiplier if size_multiplier > 0.0 else 0.35, 0.35), max(leverage_cap, 1)
    if _macro_risk_off(features):
        if is_alt_symbol(symbol):
            return False, reasons, 0.0, max(leverage_cap, 2)
        return True, [], min(size_multiplier if size_multiplier > 0.0 else 0.7, 0.7), max(leverage_cap, 2)
    return True, [], size_multiplier if size_multiplier > 0.0 else 1.0, leverage_cap


def _macro_spot_risk_reasons(features: FeatureVector, *, symbol: str) -> list[str]:
    reasons = _macro_symbol_bias_reasons(features, symbol=symbol)
    if _macro_event_halt(features) and symbol not in {"BTCUSDT", "ETHUSDT"}:
        return reasons or ["MACRO_EVENT_WINDOW"]
    return reasons


def _is_objectively_strong_futures_setup(
    features: FeatureVector,
    settings: Settings,
) -> bool:
    thresholds = settings.mode_thresholds
    exposure = settings.futures_exposure
    return (
        features.predictability_score >= thresholds.futures_score_min + exposure.strong_score_buffer
        and features.trend_strength >= exposure.strong_trend_strength_min
        and features.volume_confirmation >= exposure.strong_volume_confirmation_min
        and features.liquidity_score >= exposure.strong_liquidity_min
        and features.volatility_penalty <= exposure.strong_volatility_penalty_max
        and features.overheat_penalty <= exposure.strong_overheat_penalty_max
        and features.macro_risk_penalty < settings.macro_gates.futures_block_penalty
        and features.sentiment_regime != "caution"
        and _edge_to_cost_multiple(features) >= exposure.strong_edge_to_cost_multiple_min
    )


def _is_objectively_medium_major_futures_setup(
    features: FeatureVector,
    settings: Settings,
    *,
    symbol: str,
) -> bool:
    exposure = settings.futures_exposure
    if symbol not in set(exposure.major_symbols):
        return False
    if _is_objectively_strong_futures_setup(features, settings):
        return False
    return (
        features.predictability_score >= exposure.pyramid_min_predictability_score
        and features.trend_strength >= exposure.pyramid_min_trend_strength
        and features.volume_confirmation >= exposure.pyramid_min_volume_confirmation
        and features.liquidity_score >= exposure.soft_liquidity_floor
        and features.net_expected_edge_bps >= max(exposure.min_entry_net_edge_bps, exposure.pyramid_min_net_edge_bps - 2.0)
        and _edge_to_cost_multiple(features) >= max(exposure.priority_edge_to_cost_multiple_min, 1.0)
    )


def _strong_futures_size_multiplier(
    features: FeatureVector,
    settings: Settings,
) -> float:
    thresholds = settings.mode_thresholds
    exposure = settings.futures_exposure

    def _normalized(value: float, floor: float, span: float) -> float:
        if span <= 0:
            return 1.0
        return max(0.0, min((value - floor) / span, 1.0))

    score_strength = _normalized(
        features.predictability_score,
        thresholds.futures_score_min + exposure.strong_score_buffer,
        18.0,
    )
    trend_strength = _normalized(
        features.trend_strength,
        exposure.strong_trend_strength_min,
        0.25,
    )
    volume_strength = _normalized(
        features.volume_confirmation,
        exposure.strong_volume_confirmation_min,
        0.3,
    )
    liquidity_strength = _normalized(
        features.liquidity_score,
        exposure.strong_liquidity_min,
        0.35,
    )
    edge_strength = _normalized(
        _edge_to_cost_multiple(features),
        exposure.strong_edge_to_cost_multiple_min,
        1.5,
    )
    composite = (
        score_strength
        + trend_strength
        + volume_strength
        + liquidity_strength
        + edge_strength
    ) / 5.0
    strong_ceiling = max(float(exposure.strong_size_multiplier), 1.0)
    return round(1.0 + ((strong_ceiling - 1.0) * composite), 6)


def _futures_soft_entry_allowed(
    features: FeatureVector,
    settings: Settings,
    *,
    futures_score_min: float,
    priority_symbol: bool,
    supportive_macro: bool,
) -> bool:
    thresholds = settings.mode_thresholds
    exposure = settings.futures_exposure
    bearish_relief = 3.0 if features.trend_direction < 0 else 0.0
    soft_score_floor = max(futures_score_min - 2.0 - bearish_relief, thresholds.spot_score_min - bearish_relief)
    soft_trend_floor = max(
        thresholds.futures_trend_strength_min - (0.08 if features.trend_direction < 0 else 0.04),
        thresholds.spot_trend_strength_min,
    )
    edge_to_cost_multiple_min = exposure.macro_edge_to_cost_multiple_min
    if priority_symbol and supportive_macro:
        edge_to_cost_multiple_min = min(
            edge_to_cost_multiple_min,
            exposure.priority_edge_to_cost_multiple_min,
        )
    return (
        features.predictability_score >= soft_score_floor
        and features.trend_direction in {1, -1}
        and features.trend_strength >= soft_trend_floor
        and features.volume_confirmation >= (0.28 if features.trend_direction < 0 else 0.35)
        and features.liquidity_score >= (exposure.soft_liquidity_floor - (0.05 if features.trend_direction < 0 else 0.0))
        and features.volatility_penalty <= (exposure.soft_volatility_penalty_max + 0.05)
        and features.overheat_penalty <= (exposure.soft_overheat_penalty_max + 0.05)
        and features.net_expected_edge_bps >= (exposure.reduced_entry_net_edge_bps - (1.0 if features.trend_direction < 0 else 0.0))
        and _edge_to_cost_multiple(features) >= edge_to_cost_multiple_min
    )


def _futures_entry_plan(
    features: FeatureVector,
    settings: Settings,
    symbol: str,
) -> tuple[bool, list[str], float]:
    thresholds = settings.mode_thresholds
    macro_gates = settings.macro_gates
    exposure = settings.futures_exposure
    reasons: list[str] = []
    size_multiplier = 1.0
    reduced_size = False
    priority_symbol = symbol in set(exposure.priority_symbols)
    major_symbol = symbol in set(exposure.major_symbols)
    alt_symbol = is_alt_symbol(symbol)
    supportive_macro = (
        features.macro_liquidity_support_score >= exposure.macro_support_min
        and features.macro_event_risk_score <= 0.45
        and features.macro_risk_penalty < macro_gates.futures_block_penalty
    )
    macro_allowed, macro_reasons, macro_size_multiplier, _macro_leverage_cap = _macro_futures_risk_controls(features, symbol=symbol)
    if not macro_allowed:
        return False, macro_reasons, 0.0
    if macro_reasons:
        reasons.extend(macro_reasons)
        return False, reasons, 0.0
    size_multiplier = min(size_multiplier, macro_size_multiplier) if macro_size_multiplier > 0.0 else size_multiplier
    bearish_trend = features.trend_direction < 0
    futures_score_min = thresholds.futures_score_min - (
        exposure.macro_score_relaxation if supportive_macro else 0.0
    )
    if alt_symbol and not supportive_macro:
        futures_score_min += exposure.alt_score_penalty_without_macro
    if bearish_trend:
        futures_score_min -= 3.0
    if priority_symbol and supportive_macro:
        futures_score_min -= exposure.priority_score_relaxation
    futures_liquidity_min = thresholds.futures_liquidity_min - (
        exposure.macro_liquidity_relaxation if supportive_macro else 0.0
    )
    if alt_symbol and not supportive_macro:
        futures_liquidity_min += exposure.alt_liquidity_penalty_without_macro
    if bearish_trend:
        futures_liquidity_min -= 0.06
    futures_overheat_penalty_max = thresholds.futures_overheat_penalty_max + (
        exposure.macro_overheat_relaxation if supportive_macro else 0.0
    )
    if bearish_trend:
        futures_overheat_penalty_max += 0.05
    futures_volatility_penalty_max = thresholds.futures_volatility_penalty_max + (
        exposure.macro_volatility_relaxation if supportive_macro else 0.0
    )
    if bearish_trend:
        futures_volatility_penalty_max += 0.06
    if priority_symbol and supportive_macro:
        futures_volatility_penalty_max += exposure.priority_volatility_relaxation
    soft_entry_allowed = _futures_soft_entry_allowed(
        features,
        settings,
        futures_score_min=futures_score_min,
        priority_symbol=priority_symbol,
        supportive_macro=supportive_macro,
    )
    if features.predictability_score < futures_score_min:
        reasons.append("SCORE_TOO_LOW")
    if abs(features.trend_direction) != 1:
        reasons.append("DIRECTION_CONFLICT")
    if features.trend_strength < thresholds.futures_trend_strength_min - (0.06 if bearish_trend else 0.0):
        reasons.append("SCORE_TOO_LOW")
    if features.liquidity_score < futures_liquidity_min:
        if features.liquidity_score < exposure.soft_liquidity_floor:
            reasons.append("LIQUIDITY_TOO_WEAK")
        else:
            reduced_size = True
            size_multiplier = min(size_multiplier, exposure.reduced_size_multiplier)
    if features.volatility_penalty > futures_volatility_penalty_max:
        if features.volatility_penalty > exposure.soft_volatility_penalty_max:
            reasons.append("VOL_TOO_HIGH")
        else:
            reduced_size = True
            size_multiplier = min(size_multiplier, exposure.reduced_size_multiplier)
    if features.overheat_penalty > futures_overheat_penalty_max:
        if features.overheat_penalty > exposure.soft_overheat_penalty_max:
            reasons.append("FUTURES_OVERHEAT")
        else:
            reduced_size = True
            size_multiplier = min(size_multiplier, exposure.reduced_size_multiplier)
    if features.macro_risk_penalty >= macro_gates.futures_block_penalty:
        reasons.append("MACRO_RISK_HIGH")
    bearish_caution_override = (
        features.trend_direction < 0
        and features.predictability_score >= futures_score_min + 2.0
        and features.trend_strength >= thresholds.futures_trend_strength_min + 0.04
        and features.volume_confirmation >= 0.58
        and features.liquidity_score >= max(futures_liquidity_min, exposure.soft_liquidity_floor)
        and features.net_expected_edge_bps >= max(exposure.reduced_entry_net_edge_bps, exposure.min_entry_net_edge_bps)
        and _edge_to_cost_multiple(features) >= max(settings.cost_gate.edge_to_cost_multiple_min, 1.15)
        and features.volatility_penalty <= exposure.soft_volatility_penalty_max
        and features.overheat_penalty <= exposure.soft_overheat_penalty_max
    )
    priority_caution_override = (
        priority_symbol
        and exposure.priority_allow_caution
        and features.predictability_score >= max(futures_score_min, thresholds.futures_score_min)
        and features.net_expected_edge_bps > 0.0
        and features.volume_confirmation >= 0.7
        and features.liquidity_score >= exposure.soft_liquidity_floor
    )
    if features.sentiment_regime == "caution" and not (
        (supportive_macro and exposure.macro_allow_caution and features.volume_confirmation >= 0.62)
        or priority_caution_override
        or bearish_caution_override
    ):
        if soft_entry_allowed:
            reduced_size = True
            size_multiplier = min(size_multiplier, exposure.reduced_size_multiplier)
        else:
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
    cost_gate_pass = passes_cost_gate(features, settings)
    macro_cost_multiple_min = exposure.macro_edge_to_cost_multiple_min
    if priority_symbol and supportive_macro:
        macro_cost_multiple_min = min(macro_cost_multiple_min, exposure.priority_edge_to_cost_multiple_min)
    if not cost_gate_pass and not (
        supportive_macro and _edge_to_cost_multiple(features) >= macro_cost_multiple_min
    ):
        if soft_entry_allowed:
            reduced_size = True
            size_multiplier = min(size_multiplier, exposure.reduced_size_multiplier)
        else:
            reasons.append("EDGE_BELOW_COST")
    min_entry_net_edge_bps = (
        exposure.macro_min_entry_net_edge_bps if supportive_macro else exposure.min_entry_net_edge_bps
    )
    if alt_symbol and not supportive_macro:
        min_entry_net_edge_bps += exposure.alt_min_entry_net_edge_bps_without_macro
    if priority_symbol and supportive_macro:
        min_entry_net_edge_bps = min(min_entry_net_edge_bps, exposure.priority_min_entry_net_edge_bps)
    if (
        alt_symbol
        and not supportive_macro
        and features.liquidity_score < futures_liquidity_min
        and features.net_expected_edge_bps <= (min_entry_net_edge_bps + 1.0)
    ):
        reasons.append("ALT_FUTURES_NOT_READY")
    if features.net_expected_edge_bps < min_entry_net_edge_bps:
        if soft_entry_allowed:
            reduced_size = True
            size_multiplier = min(size_multiplier, exposure.reduced_size_multiplier)
        else:
            reasons.append("EDGE_TOO_THIN")
    if reasons:
        return False, reasons, 0.0
    if reduced_size and features.net_expected_edge_bps < exposure.reduced_entry_net_edge_bps:
        return False, ["EDGE_TOO_THIN"], 0.0
    if reduced_size and alt_symbol and exposure.alt_reduced_size_multiplier > 0.0:
        size_multiplier = min(size_multiplier, exposure.alt_reduced_size_multiplier)
    strong_setup = _is_objectively_strong_futures_setup(features, settings)
    if not reduced_size and strong_setup:
        size_multiplier = max(size_multiplier, _strong_futures_size_multiplier(features, settings))
    if (
        major_symbol
        and not reduced_size
        and not strong_setup
        and _is_objectively_medium_major_futures_setup(features, settings, symbol=symbol)
    ):
        size_multiplier = max(size_multiplier, exposure.major_medium_size_boost_multiplier)
    if major_symbol and size_multiplier > 1.0:
        size_multiplier = round(size_multiplier * max(exposure.major_size_boost_multiplier, 1.0), 6)
    return True, reasons, size_multiplier


def _spot_passes(features: FeatureVector, settings: Settings, symbol: str) -> tuple[bool, list[str]]:
    thresholds = settings.mode_thresholds
    macro_gates = settings.macro_gates
    support_cfg = settings.spot_support
    mode_behavior = settings.mode_behavior
    reasons: list[str] = []
    priority_symbol = symbol in set(support_cfg.priority_symbols)
    support_alignment_min = support_cfg.priority_support_alignment_min if priority_symbol else support_cfg.support_alignment_min
    resistance_penalty_max = support_cfg.priority_resistance_penalty_max if priority_symbol else support_cfg.resistance_penalty_max
    sentiment_support_min = support_cfg.priority_sentiment_support_min if priority_symbol else support_cfg.sentiment_support_min
    liquidity_relaxation = support_cfg.priority_liquidity_relaxation if priority_symbol else support_cfg.liquidity_relaxation

    macro_reasons = _macro_spot_risk_reasons(features, symbol=symbol)
    if macro_reasons:
        reasons.extend(macro_reasons)

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
        features.liquidity_score >= thresholds.spot_liquidity_min - liquidity_relaxation
        and (
            features.net_expected_edge_bps >= -support_cfg.priority_edge_relaxation_bps
            if priority_symbol
            else features.net_expected_edge_bps > 0.0
        )
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
    if features.support_alignment < support_alignment_min:
        reasons.append("SUPPORT_NOT_CONFIRMED")
    resistance_override = (
        features.breakout_norm >= support_cfg.breakout_resistance_override_min
        and features.volume_confirmation >= 0.6
        and (
            features.net_expected_edge_bps >= -support_cfg.priority_edge_relaxation_bps
            if priority_symbol
            else features.net_expected_edge_bps > 0.0
        )
        and features.trend_direction >= 0
    )
    if features.resistance_penalty > resistance_penalty_max and not resistance_override:
        reasons.append("BUYING_INTO_RESISTANCE")
    if features.macro_risk_penalty >= macro_gates.spot_block_penalty:
        reasons.append("MACRO_RISK_HIGH")
    if features.sentiment_support_score < sentiment_support_min:
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
        features.support_alignment >= max(support_alignment_min, 0.12)
        and features.resistance_penalty <= min(resistance_penalty_max, 0.5 if priority_symbol else 0.35)
        and features.sentiment_support_score >= max(sentiment_support_min, 0.2 if priority_symbol else 0.35)
        and features.macro_risk_penalty < macro_gates.spot_block_penalty
        and features.net_expected_edge_bps > (-8.0 if priority_symbol else -5.0)
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
    thresholds = settings.mode_thresholds
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
            macro_regime=spot_features.macro_regime,
            macro_trade_restraint=spot_features.macro_trade_restraint,
            macro_size_multiplier=spot_features.macro_size_multiplier,
            macro_leverage_cap=spot_features.macro_leverage_cap,
            macro_symbol_bias=spot_features.macro_symbol_bias,
            rejection_reasons=cash_reasons,
        )

    futures_ok, futures_reasons, futures_size_multiplier = _futures_entry_plan(
        futures_features,
        settings,
        snapshot.symbol,
    )
    if futures_ok:
        planned_leverage = select_futures_leverage(
            predictability_score=futures_features.predictability_score,
            trend_strength=futures_features.trend_strength,
            volume_confirmation=futures_features.volume_confirmation,
            liquidity_score=futures_features.liquidity_score,
            volatility_penalty=futures_features.volatility_penalty,
            overheat_penalty=futures_features.overheat_penalty,
            net_expected_edge_bps=futures_features.net_expected_edge_bps,
            estimated_round_trip_cost_bps=futures_features.estimated_round_trip_cost_bps,
            settings=settings,
        )
        if futures_features.macro_leverage_cap > 0:
            planned_leverage = min(planned_leverage, futures_features.macro_leverage_cap)
        notional, stop_distance_bps = position_notional_and_stop_bps(
            last_trade_price=snapshot.last_trade_price,
            atr_14_1h_bps=snapshot.feature_values.realized_vol_1h_norm * 100.0,
            equity_usd=equity_usd,
            remaining_portfolio_capacity_usd=remaining_portfolio_capacity_usd,
            settings=settings,
            size_multiplier=futures_size_multiplier,
            leverage_multiplier=planned_leverage,
        )
        required_margin_usd = notional / max(float(planned_leverage), 1.0)
        if equity_usd > 0 and (equity_usd - required_margin_usd) / equity_usd < cash_reserve_fraction:
            futures_ok = False
            futures_reasons.append("CASH_RESERVE_BLOCK")
        payload = {
            "snapshot_id": snapshot.snapshot_id,
            "config_version": settings.config_version,
            "final_mode": "futures",
            "side": "long" if futures_features.trend_direction > 0 else "short",
            "predictability_score": futures_features.predictability_score,
        }
        confirmation_required = (
            futures_size_multiplier < 1.0
            or futures_features.intraday_trend_strength < 0.5
            or (
                futures_features.intraday_trend_direction != 0
                and futures_features.intraday_trend_direction != futures_features.trend_direction
            )
        )
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
            macro_regime=futures_features.macro_regime,
            macro_trade_restraint=futures_features.macro_trade_restraint,
            macro_size_multiplier=futures_features.macro_size_multiplier,
            macro_leverage_cap=futures_features.macro_leverage_cap,
            macro_symbol_bias=futures_features.macro_symbol_bias,
            divergence_code="ENTRY_CONFIRMATION_REQUIRED" if confirmation_required else "",
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
        confirmation_required = (
            spot_features.support_alignment < 0.25
            or spot_features.resistance_penalty > 0.3
            or spot_features.liquidity_score < thresholds.spot_liquidity_min
            or spot_features.intraday_trend_strength < 0.45
        )
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
            macro_regime=spot_features.macro_regime,
            macro_trade_restraint=spot_features.macro_trade_restraint,
            macro_size_multiplier=spot_features.macro_size_multiplier,
            macro_leverage_cap=spot_features.macro_leverage_cap,
            macro_symbol_bias=spot_features.macro_symbol_bias,
            rejection_reasons=tuple(sorted(set(futures_reasons))),
            divergence_code="ENTRY_CONFIRMATION_REQUIRED" if confirmation_required else "",
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
        macro_regime=spot_features.macro_regime,
        macro_trade_restraint=spot_features.macro_trade_restraint,
        macro_size_multiplier=spot_features.macro_size_multiplier,
        macro_leverage_cap=spot_features.macro_leverage_cap,
        macro_symbol_bias=spot_features.macro_symbol_bias,
        rejection_reasons=cash_reasons,
    )
