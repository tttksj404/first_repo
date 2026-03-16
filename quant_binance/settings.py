from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_binance.env import resolve_strategy_override_path, resolve_strategy_profile, resolve_universe_symbols


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True)
class DecisionEngineConfig:
    decision_interval_minutes: int


@dataclass(frozen=True)
class NormalizationConfig:
    method: str
    rolling_window_days: int


@dataclass(frozen=True)
class WeightConfig:
    trend_strength: float
    volume_confirmation: float
    liquidity_score: float
    regime_alignment: float
    inverse_volatility_penalty: float
    inverse_overheat_penalty: float


@dataclass(frozen=True)
class ModeThresholdConfig:
    futures_score_min: float
    spot_score_min: float
    futures_trend_strength_min: float
    spot_trend_strength_min: float
    futures_liquidity_min: float
    spot_liquidity_min: float
    futures_volatility_penalty_max: float
    spot_volatility_penalty_max: float
    futures_overheat_penalty_max: float


@dataclass(frozen=True)
class FeatureThresholdConfig:
    liquidity_probe_notional_usd: float
    min_expected_edge_observations: int
    spread_bps_ceiling: float
    slippage_bps_ceiling: float
    depth_usd_target: float
    order_book_imbalance_std_ceiling: float
    vol_shock_ceiling: float
    pretrade_slippage_budget_bps: float
    oi_ema_hours: int


@dataclass(frozen=True)
class CostGateConfig:
    edge_to_cost_multiple_min: float


@dataclass(frozen=True)
class FeeConfig:
    account_tier: str
    spot_maker_fee_bps: float
    spot_taker_fee_bps: float
    futures_maker_fee_bps: float
    futures_taker_fee_bps: float


@dataclass(frozen=True)
class ExpectedEdgeConfig:
    futures_horizon_minutes: int
    spot_horizon_minutes: int


@dataclass(frozen=True)
class RiskConfig:
    per_trade_equity_risk: float
    max_symbol_notional_fraction: float
    max_total_notional_fraction: float
    max_futures_leverage: float
    target_futures_leverage: float
    daily_realized_loss_limit: float
    weekly_realized_loss_limit: float
    intraday_drawdown_limit: float
    min_meaningful_futures_notional_usd: float = 0.0
    min_meaningful_spot_notional_usd: float = 0.0
    min_expected_profit_usd_per_trade: float = 0.0


@dataclass(frozen=True)
class SizingConfig:
    atr_multiple_for_stop: float
    stop_floor_bps: float


@dataclass(frozen=True)
class ExitRuleConfig:
    partial_take_profit_r: float
    post_tp_stop_mode: str
    futures_max_holding_minutes: int
    spot_max_holding_minutes: int
    score_drop_exit_buffer: float
    liquidity_drop_exit_buffer: float
    confirmation_cycles_for_exit: int
    futures_profit_protection_arm_roe_percent: float = 8.0
    futures_profit_protection_retrace_roe_percent: float = 3.0
    futures_proactive_take_profit_roe_thresholds_percent: tuple[float, ...] = ()
    futures_proactive_take_profit_fraction: float = 0.25


@dataclass(frozen=True)
class OperationalLimitConfig:
    max_concurrent_futures_symbols: int
    max_concurrent_spot_symbols: int
    stale_data_seconds: int
    stale_data_alarm_sla_seconds: int
    max_order_retries: int


@dataclass(frozen=True)
class ValidationConfig:
    paper_mode_switches_per_symbol_per_day_max: int
    paper_direction_flips_per_symbol_per_hour_max: int
    order_reject_rate_max: float
    order_retry_rate_max: float
    reconciliation_mismatch_rate_max: float
    avg_slippage_error_abs_bps_max: float


@dataclass(frozen=True)
class ModeBehaviorConfig:
    spot_require_positive_trend: bool
    spot_allow_bottoming_reversal: bool = False


@dataclass(frozen=True)
class SpotSupportConfig:
    support_alignment_min: float
    resistance_penalty_max: float
    sentiment_support_min: float
    liquidity_relaxation: float = 0.0
    breakout_resistance_override_min: float = 1.0
    bottoming_support_override_min: float = 1.0
    priority_symbols: tuple[str, ...] = ()
    priority_support_alignment_min: float = 0.0
    priority_resistance_penalty_max: float = 1.0
    priority_sentiment_support_min: float = 0.0
    priority_liquidity_relaxation: float = 0.0
    priority_edge_relaxation_bps: float = 0.0


@dataclass(frozen=True)
class MacroGateConfig:
    futures_block_penalty: float
    spot_block_penalty: float


@dataclass(frozen=True)
class FuturesExposureConfig:
    soft_liquidity_floor: float
    soft_volatility_penalty_max: float
    soft_overheat_penalty_max: float
    reduced_size_multiplier: float
    min_entry_net_edge_bps: float
    reduced_entry_net_edge_bps: float
    strong_score_buffer: float
    strong_trend_strength_min: float
    strong_volume_confirmation_min: float
    strong_liquidity_min: float
    strong_volatility_penalty_max: float
    strong_overheat_penalty_max: float
    strong_edge_to_cost_multiple_min: float
    strong_size_multiplier: float
    macro_support_min: float = 0.7
    macro_score_relaxation: float = 0.0
    macro_liquidity_relaxation: float = 0.0
    macro_overheat_relaxation: float = 0.0
    macro_volatility_relaxation: float = 0.0
    macro_min_entry_net_edge_bps: float = 6.0
    macro_edge_to_cost_multiple_min: float = 1.0
    macro_allow_caution: bool = False
    priority_symbols: tuple[str, ...] = ()
    priority_score_relaxation: float = 0.0
    priority_min_entry_net_edge_bps: float = 0.0
    priority_edge_to_cost_multiple_min: float = 1.0
    priority_volatility_relaxation: float = 0.0
    priority_allow_caution: bool = False
    major_symbols: tuple[str, ...] = ()
    major_size_boost_multiplier: float = 1.0
    major_medium_size_boost_multiplier: float = 1.0
    alt_score_penalty_without_macro: float = 0.0
    alt_liquidity_penalty_without_macro: float = 0.0
    alt_min_entry_net_edge_bps_without_macro: float = 0.0
    alt_reduced_size_multiplier: float = 0.0
    major_reallocation_score_advantage_relaxation: float = 0.0
    major_reallocation_edge_advantage_relaxation_bps: float = 0.0
    major_reallocation_incremental_pnl_relaxation_usd: float = 0.0
    major_min_meaningful_notional_usd: float = 0.0
    major_medium_min_entry_notional_usd: float = 0.0
    major_medium_total_notional_fraction_relaxation: float = 0.0
    major_medium_safety_cap_fraction: float = 0.5
    major_strong_min_entry_notional_usd: float = 0.0
    major_strong_total_notional_fraction_relaxation: float = 0.0
    major_strong_safety_cap_fraction: float = 0.5
    pyramid_enabled: bool = False
    pyramid_major_only: bool = True
    pyramid_min_roe_percent: float = 0.0
    pyramid_min_predictability_score: float = 60.0
    pyramid_min_net_edge_bps: float = 6.0
    pyramid_min_trend_strength: float = 0.55
    pyramid_min_volume_confirmation: float = 0.45
    pyramid_max_adds_per_symbol: int = 1
    pyramid_size_multiplier: float = 0.5


@dataclass(frozen=True)
class CashReserveConfig:
    when_futures_enabled: float
    when_futures_disabled: float


@dataclass(frozen=True)
class AltcoinOverlayConfig:
    breadth_floor: float
    liquidity_floor: float
    smart_money_floor: float
    rotation_block_penalty: float


@dataclass(frozen=True)
class SymbolEligibilityConfig:
    observe_only_liquidity_max: float
    observe_only_alt_liquidity_max: float
    observe_only_cost_bps_min: float


@dataclass(frozen=True)
class LivePositionRiskConfig:
    enabled: bool
    take_profit_roe_percent: float
    stop_loss_roe_percent: float
    margin_ratio_emergency: float
    disable_standard_stop_loss_exits: bool = False
    portfolio_full_exit_only: bool = False
    portfolio_full_exit_profit_ratio: float = 0.0
    turnaround_grace_enabled: bool = True
    soft_stop_roe_percent: float = -10.0
    turnaround_abort_roe_percent: float = -14.0
    turnaround_recovery_roe_points: float = 2.0
    turnaround_predictability_min: float = 55.0
    turnaround_net_edge_min_bps: float = 2.0
    turnaround_volume_confirmation_min: float = 0.4
    turnaround_trend_strength_min: float = 0.55
    turnaround_liquidity_min: float = 0.45
    turnaround_signal_max_age_minutes: int = 20
    major_drawdown_grace_enabled: bool = False
    major_drawdown_grace_minutes: int = 0
    major_drawdown_abort_roe_percent: float = -12.0
    major_drawdown_predictability_min: float = 58.0
    major_drawdown_net_edge_min_bps: float = 4.0
    major_drawdown_liquidity_min: float = 0.45
    major_drawdown_signal_max_age_minutes: int = 30
    profit_flip_fast_take_profit_roe_percent: float = 2.0
    profit_flip_take_profit_fraction: float = 0.25
    position_unrealized_profit_arm_usd: float = 8.0
    position_unrealized_profit_retrace_usd: float = 3.0
    position_unrealized_take_profit_fraction: float = 0.25
    portfolio_unrealized_profit_arm_ratio: float = 0.015
    portfolio_unrealized_profit_retrace_ratio: float = 0.005
    portfolio_profit_lock_take_profit_fraction: float = 0.25
    partial_exit_min_expected_after_fee_usd: float = 0.0
    partial_exit_min_interval_minutes: int = 0
    major_partial_exit_fraction: float = 0.5
    major_profit_protection_arm_roe_percent: float = 12.0
    major_profit_protection_retrace_roe_percent: float = 4.5
    major_low_signal_max_holding_minutes: int = 0
    major_low_signal_min_unrealized_usd: float = 0.0
    major_low_signal_min_roe_percent: float = 0.0
    major_reentry_cooldown_minutes: int = 0
    major_reversal_confirmation_cycles: int = 0
    major_reversal_min_holding_minutes: int = 0
    major_loss_reentry_cooldown_minutes: int = 0
    major_loss_reentry_trigger_usd: float = 0.0
    major_missing_on_exchange_threshold: int = 0
    non_core_soft_stop_roe_percent: float = -2.5
    non_core_take_profit_roe_percent: float = 1.0
    non_core_take_profit_fraction: float = 1.0
    non_core_take_profit_min_usd: float = 1.0


@dataclass(frozen=True)
class LossComboDowngradeConfig:
    enabled: bool = False
    lookback_hours: int = 24
    time_bucket_minutes: int = 240
    prune_loss_usd: float = 0.0
    observe_only_loss_usd: float = 0.0
    cooldown_loss_usd: float = 0.0
    cooldown_minutes: int = 0


@dataclass(frozen=True)
class PortfolioFocusConfig:
    enabled: bool
    spot_top_n: int
    futures_top_n: int
    min_score_advantage_to_replace: float
    min_net_edge_advantage_bps: float = 0.0
    min_incremental_pnl_usd: float = 0.0


@dataclass(frozen=True)
class HousekeepingConfig:
    enabled: bool
    max_log_bytes_per_stream: int
    keep_recent_runs: int


@dataclass(frozen=True)
class Settings:
    config_version: str
    snapshot_schema_version: str
    universe: tuple[str, ...]
    klines: tuple[str, ...]
    decision_engine: DecisionEngineConfig
    normalization: NormalizationConfig
    weights: WeightConfig
    mode_thresholds: ModeThresholdConfig
    feature_thresholds: FeatureThresholdConfig
    cost_gate: CostGateConfig
    fees: FeeConfig
    expected_edge: ExpectedEdgeConfig
    risk: RiskConfig
    sizing: SizingConfig
    exit_rules: ExitRuleConfig
    operational_limits: OperationalLimitConfig
    validation: ValidationConfig
    mode_behavior: ModeBehaviorConfig
    spot_support: SpotSupportConfig
    macro_gates: MacroGateConfig
    futures_exposure: FuturesExposureConfig
    cash_reserve: CashReserveConfig
    altcoin_overlays: AltcoinOverlayConfig
    symbol_eligibility: SymbolEligibilityConfig
    live_position_risk: LivePositionRiskConfig
    loss_combo_downgrade: LossComboDowngradeConfig
    portfolio_focus: PortfolioFocusConfig
    housekeeping: HousekeepingConfig
    strategy_profile: str

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        with Path(path).open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        profile = resolve_strategy_profile() or "conservative"
        raw = _deep_merge(raw, raw.get("strategy_profiles", {}).get(profile, {}))
        override_symbols = resolve_universe_symbols()
        if override_symbols:
            raw["universe"] = list(override_symbols)
        override_path = resolve_strategy_override_path()
        if override_path:
            candidate = Path(override_path)
            if candidate.exists():
                raw = _deep_merge(raw, json.loads(candidate.read_text(encoding="utf-8")))
        raw["strategy_profile"] = profile
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Settings":
        spot_support_raw = dict(raw["spot_support"])
        spot_support_raw["priority_symbols"] = tuple(spot_support_raw.get("priority_symbols", ()))
        futures_exposure_raw = dict(raw["futures_exposure"])
        futures_exposure_raw["priority_symbols"] = tuple(futures_exposure_raw.get("priority_symbols", ()))
        futures_exposure_raw["major_symbols"] = tuple(futures_exposure_raw.get("major_symbols", ()))
        exit_rules_raw = dict(raw["exit_rules"])
        exit_rules_raw["futures_proactive_take_profit_roe_thresholds_percent"] = tuple(
            exit_rules_raw.get("futures_proactive_take_profit_roe_thresholds_percent", ())
        )
        loss_combo_downgrade_raw = {
            "enabled": False,
            "lookback_hours": 24,
            "time_bucket_minutes": 240,
            "prune_loss_usd": 0.0,
            "observe_only_loss_usd": 0.0,
            "cooldown_loss_usd": 0.0,
            "cooldown_minutes": 0,
        }
        loss_combo_downgrade_raw.update(raw.get("loss_combo_downgrade", {}))
        return cls(
            config_version=raw["config_version"],
            snapshot_schema_version=raw["snapshot_schema_version"],
            universe=tuple(raw["universe"]),
            klines=tuple(raw["klines"]),
            decision_engine=DecisionEngineConfig(**raw["decision_engine"]),
            normalization=NormalizationConfig(**raw["normalization"]),
            weights=WeightConfig(**raw["weights"]),
            mode_thresholds=ModeThresholdConfig(**raw["mode_thresholds"]),
            feature_thresholds=FeatureThresholdConfig(**raw["feature_thresholds"]),
            cost_gate=CostGateConfig(**raw["cost_gate"]),
            fees=FeeConfig(**raw["fees"]),
            expected_edge=ExpectedEdgeConfig(**raw["expected_edge"]),
            risk=RiskConfig(**raw["risk"]),
            sizing=SizingConfig(**raw["sizing"]),
            exit_rules=ExitRuleConfig(**exit_rules_raw),
            operational_limits=OperationalLimitConfig(**raw["operational_limits"]),
            validation=ValidationConfig(**raw["validation"]),
            mode_behavior=ModeBehaviorConfig(**raw["mode_behavior"]),
            spot_support=SpotSupportConfig(**spot_support_raw),
            macro_gates=MacroGateConfig(**raw["macro_gates"]),
            futures_exposure=FuturesExposureConfig(**futures_exposure_raw),
            cash_reserve=CashReserveConfig(**raw["cash_reserve"]),
            altcoin_overlays=AltcoinOverlayConfig(**raw["altcoin_overlays"]),
            symbol_eligibility=SymbolEligibilityConfig(**raw["symbol_eligibility"]),
            live_position_risk=LivePositionRiskConfig(**raw["live_position_risk"]),
            loss_combo_downgrade=LossComboDowngradeConfig(**loss_combo_downgrade_raw),
            portfolio_focus=PortfolioFocusConfig(**raw["portfolio_focus"]),
            housekeeping=HousekeepingConfig(**raw["housekeeping"]),
            strategy_profile=raw["strategy_profile"],
        )
