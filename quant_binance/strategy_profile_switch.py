from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from quant_binance.features.primitive import (
    FeatureHistoryContext,
    PrimitiveInputs,
    build_feature_vector_from_primitives,
)
from quant_binance.settings import DecisionEngineConfig, Settings


@dataclass(frozen=True)
class AutoProfileSwitchPolicy:
    calm_profile: str = "aggressive_alt"
    fast_profile: str = "scalp_ultra"
    min_hold_cycles: int = 3
    fast_on_volatility_penalty: float = 0.62
    fast_off_volatility_penalty: float = 0.48
    fast_on_abs_ret_1h: float = 0.018
    fast_off_abs_ret_1h: float = 0.010


@dataclass(frozen=True)
class AutoProfileSwitchDecision:
    active_profile: str
    changed: bool
    reason: str
    volatility_penalty: float
    abs_ret_1h: float


class AutoProfileSwitcher:
    def __init__(
        self,
        *,
        config_path: str | Path,
        policy: AutoProfileSwitchPolicy,
        runtime_decision_interval_minutes: int,
        initial_profile: str,
    ) -> None:
        self.policy = policy
        self.runtime_decision_interval_minutes = max(int(runtime_decision_interval_minutes), 1)
        self._settings_by_profile = {
            policy.calm_profile: self._load_profile_settings(config_path, policy.calm_profile),
            policy.fast_profile: self._load_profile_settings(config_path, policy.fast_profile),
        }
        self.active_profile = (
            initial_profile
            if initial_profile in self._settings_by_profile
            else policy.calm_profile
        )
        self._cycles_since_switch = max(int(policy.min_hold_cycles), 0)
        self._last_cycle_key: str | None = None

    @property
    def active_settings(self) -> Settings:
        return self._settings_by_profile[self.active_profile]

    def evaluate(
        self,
        *,
        primitive_inputs: PrimitiveInputs,
        history: FeatureHistoryContext,
        cycle_key: str | None = None,
    ) -> AutoProfileSwitchDecision:
        active_settings = self.active_settings
        features = build_feature_vector_from_primitives(
            inputs=primitive_inputs,
            history=history,
            settings=active_settings,
        )
        return self.evaluate_metrics(
            volatility_penalty=float(features.volatility_penalty),
            abs_ret_1h=abs(float(primitive_inputs.ret_1h)),
            cycle_key=cycle_key,
        )

    def evaluate_metrics(
        self,
        *,
        volatility_penalty: float,
        abs_ret_1h: float,
        cycle_key: str | None = None,
    ) -> AutoProfileSwitchDecision:
        is_new_cycle = True
        if cycle_key is not None:
            is_new_cycle = cycle_key != self._last_cycle_key
            if is_new_cycle:
                self._last_cycle_key = cycle_key
            else:
                return AutoProfileSwitchDecision(
                    active_profile=self.active_profile,
                    changed=False,
                    reason="CYCLE_LOCK",
                    volatility_penalty=volatility_penalty,
                    abs_ret_1h=abs_ret_1h,
                )

        candidate = self.active_profile
        reason = "HOLD"
        if (
            volatility_penalty >= self.policy.fast_on_volatility_penalty
            or abs_ret_1h >= self.policy.fast_on_abs_ret_1h
        ):
            candidate = self.policy.fast_profile
            reason = "FAST_SIGNAL"
        elif (
            volatility_penalty <= self.policy.fast_off_volatility_penalty
            and abs_ret_1h <= self.policy.fast_off_abs_ret_1h
        ):
            candidate = self.policy.calm_profile
            reason = "CALM_SIGNAL"

        if candidate != self.active_profile:
            if self._cycles_since_switch < self.policy.min_hold_cycles:
                if is_new_cycle:
                    self._cycles_since_switch += 1
                return AutoProfileSwitchDecision(
                    active_profile=self.active_profile,
                    changed=False,
                    reason="MIN_HOLD_LOCK",
                    volatility_penalty=volatility_penalty,
                    abs_ret_1h=abs_ret_1h,
                )
            self.active_profile = candidate
            self._cycles_since_switch = 0
            return AutoProfileSwitchDecision(
                active_profile=self.active_profile,
                changed=True,
                reason=reason,
                volatility_penalty=volatility_penalty,
                abs_ret_1h=abs_ret_1h,
            )

        if is_new_cycle:
            self._cycles_since_switch += 1
        return AutoProfileSwitchDecision(
            active_profile=self.active_profile,
            changed=False,
            reason=reason,
            volatility_penalty=volatility_penalty,
            abs_ret_1h=abs_ret_1h,
        )

    def _load_profile_settings(self, config_path: str | Path, profile: str) -> Settings:
        loaded = Settings.load(config_path, strategy_profile=profile)
        if loaded.decision_engine.decision_interval_minutes == self.runtime_decision_interval_minutes:
            return loaded
        return replace(
            loaded,
            decision_engine=DecisionEngineConfig(
                decision_interval_minutes=self.runtime_decision_interval_minutes
            ),
        )
