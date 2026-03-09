from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_binance.env import resolve_strategy_profile, resolve_universe_symbols


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


@dataclass(frozen=True)
class MacroGateConfig:
    futures_block_penalty: float
    spot_block_penalty: float


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
    cash_reserve: CashReserveConfig
    altcoin_overlays: AltcoinOverlayConfig
    symbol_eligibility: SymbolEligibilityConfig
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
        raw["strategy_profile"] = profile
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Settings":
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
            exit_rules=ExitRuleConfig(**raw["exit_rules"]),
            operational_limits=OperationalLimitConfig(**raw["operational_limits"]),
            validation=ValidationConfig(**raw["validation"]),
            mode_behavior=ModeBehaviorConfig(**raw["mode_behavior"]),
            spot_support=SpotSupportConfig(**raw["spot_support"]),
            macro_gates=MacroGateConfig(**raw["macro_gates"]),
            cash_reserve=CashReserveConfig(**raw["cash_reserve"]),
            altcoin_overlays=AltcoinOverlayConfig(**raw["altcoin_overlays"]),
            symbol_eligibility=SymbolEligibilityConfig(**raw["symbol_eligibility"]),
            strategy_profile=raw["strategy_profile"],
        )
