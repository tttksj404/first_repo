from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from quant_binance.models import FeatureVector
from quant_binance.strategy.normalize import clamp


@dataclass(frozen=True)
class MacroInputs:
    truflation_yoy: float
    us10y_yield: float
    oil_momentum_pct: float
    tga_drain_score: float
    fed_balance_sheet_30d_pct: float
    mmf_30d_pct: float
    labor_stress_score: float
    us10y_change_30d_bps: float = 0.0
    dxy_change_30d_pct: float = 0.0
    fed_liquidity_score: float = 0.5
    policy_easing_score: float = 0.5
    event_risk_score: float = 0.0
    btc_safe_haven_score: float = 0.5


@dataclass(frozen=True)
class AltcoinGlobalInputs:
    alt_breadth_score: float = 0.5
    alt_liquidity_score: float = 0.5
    stablecoin_flow_score: float = 0.5
    btc_dominance_penalty: float = 0.5


@dataclass(frozen=True)
class AltcoinSymbolInputs:
    smart_money_score: float = 0.5
    fundamental_score: float = 0.5
    category_momentum_score: float = 0.5
    fdv_stress_penalty: float = 0.0
    unlock_risk_penalty: float = 0.0


@dataclass(frozen=True)
class AltcoinInputs:
    global_inputs: AltcoinGlobalInputs
    symbols: dict[str, AltcoinSymbolInputs]


def _load_env_file_value(name: str) -> str:
    direct = os.environ.get(name, "").strip()
    if direct:
        return direct
    repo_root = Path(__file__).resolve().parents[1]
    for candidate in (repo_root / ".env", repo_root / ".env.local"):
        if not candidate.exists():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    return ""


def load_macro_inputs() -> MacroInputs | None:
    path_value = _load_env_file_value("MACRO_INPUTS_PATH")
    json_value = _load_env_file_value("MACRO_INPUTS_JSON")
    payload = None
    if json_value:
        payload = json.loads(json_value)
    elif path_value:
        payload = json.loads(Path(path_value).read_text(encoding="utf-8"))
    if payload is None:
        return None
    return MacroInputs(**payload)


def is_alt_symbol(symbol: str) -> bool:
    return symbol not in {"BTCUSDT", "ETHUSDT"}


def load_altcoin_inputs() -> AltcoinInputs | None:
    path_value = _load_env_file_value("ALTCOIN_INPUTS_PATH")
    json_value = _load_env_file_value("ALTCOIN_INPUTS_JSON")
    payload = None
    if json_value:
        payload = json.loads(json_value)
    elif path_value:
        payload = json.loads(Path(path_value).read_text(encoding="utf-8"))
    if payload is None:
        return None

    global_inputs = AltcoinGlobalInputs(**payload.get("global", {}))
    raw_symbols = payload.get("symbols", {})
    symbols = {
        symbol.upper(): AltcoinSymbolInputs(**values)
        for symbol, values in raw_symbols.items()
    }
    return AltcoinInputs(global_inputs=global_inputs, symbols=symbols)


def apply_macro_overlay(features: FeatureVector, macro_inputs: MacroInputs | None) -> FeatureVector:
    if macro_inputs is None:
        return features

    risk = 0.0
    support = 0.0
    if macro_inputs.us10y_yield >= 4.7:
        risk += 0.25
    if macro_inputs.oil_momentum_pct >= 12.0:
        risk += 0.25
    if macro_inputs.truflation_yoy >= 2.8:
        risk += 0.20
    if macro_inputs.labor_stress_score >= 0.7:
        risk += 0.15
    risk += 0.35 * clamp(macro_inputs.event_risk_score, 0.0, 1.0)
    if macro_inputs.tga_drain_score >= 0.6:
        support += 0.20
    if macro_inputs.fed_balance_sheet_30d_pct > 0:
        support += 0.20
    if macro_inputs.mmf_30d_pct < 0:
        support += 0.10
    if macro_inputs.us10y_change_30d_bps <= -25.0:
        support += 0.15
    if macro_inputs.dxy_change_30d_pct <= -1.5:
        support += 0.15
    support += 0.20 * clamp(macro_inputs.fed_liquidity_score, 0.0, 1.0)
    support += 0.15 * clamp(macro_inputs.policy_easing_score, 0.0, 1.0)
    support += 0.10 * clamp(macro_inputs.btc_safe_haven_score, 0.0, 1.0)

    penalty = clamp(risk - support, 0.0, 1.0)
    support_score = clamp(support, 0.0, 1.0)
    regime = "high_risk" if penalty >= 0.65 else "supportive" if penalty <= 0.25 else "neutral"
    return FeatureVector(
        **{
            **features.as_dict(),
            "macro_regime": regime,
            "macro_risk_penalty": round(penalty, 6),
            "macro_liquidity_support_score": round(support_score, 6),
            "macro_event_risk_score": round(clamp(macro_inputs.event_risk_score, 0.0, 1.0), 6),
        }
    )


def apply_sentiment_overlay(features: FeatureVector) -> FeatureVector:
    score = 0.0
    if features.trend_direction == 1 and features.volume_confirmation >= 0.60 and features.liquidity_score >= 0.60:
        score += 0.40
    if features.support_alignment >= 0.34 and features.resistance_penalty <= 0.50:
        score += 0.30
    if features.volatility_penalty <= 0.40:
        score += 0.15
    else:
        score -= 0.20
    if features.overheat_penalty > 0.60:
        score -= 0.30

    support_score = clamp(0.5 + score, 0.0, 1.0)
    if features.support_alignment >= 0.67 and features.overheat_penalty <= 0.35 and features.volatility_penalty < 0.55:
        regime = "bottoming"
    elif features.trend_direction == 1 and features.volume_confirmation >= 0.65 and features.liquidity_score >= 0.65 and features.overheat_penalty <= 0.35:
        regime = "risk_on"
    elif features.overheat_penalty > 0.60 or features.volatility_penalty > 0.60:
        regime = "caution"
    else:
        regime = "neutral"

    return FeatureVector(
        **{
            **features.as_dict(),
            "sentiment_regime": regime,
            "sentiment_support_score": round(support_score, 6),
        }
    )


def apply_altcoin_overlay(
    features: FeatureVector,
    *,
    symbol: str,
    altcoin_inputs: AltcoinInputs | None,
) -> FeatureVector:
    if altcoin_inputs is None or not is_alt_symbol(symbol):
        return features

    global_inputs = altcoin_inputs.global_inputs
    symbol_inputs = altcoin_inputs.symbols.get(symbol.upper(), AltcoinSymbolInputs())

    breadth = clamp(global_inputs.alt_breadth_score, 0.0, 1.0)
    liquidity_support = clamp(
        0.65 * global_inputs.alt_liquidity_score
        + 0.2 * global_inputs.stablecoin_flow_score
        + 0.15 * symbol_inputs.smart_money_score,
        0.0,
        1.0,
    )
    fundamental = clamp(
        0.55 * symbol_inputs.fundamental_score
        + 0.45 * symbol_inputs.category_momentum_score,
        0.0,
        1.0,
    )
    smart_money = clamp(symbol_inputs.smart_money_score, 0.0, 1.0)
    rotation_penalty = clamp(
        0.45 * global_inputs.btc_dominance_penalty
        + 0.3 * symbol_inputs.fdv_stress_penalty
        + 0.25 * symbol_inputs.unlock_risk_penalty,
        0.0,
        1.0,
    )

    support_score = clamp(
        0.3 * breadth
        + 0.2 * liquidity_support
        + 0.15 * global_inputs.stablecoin_flow_score
        + 0.15 * smart_money
        + 0.1 * fundamental
        + 0.1 * symbol_inputs.category_momentum_score
        - 0.15 * global_inputs.btc_dominance_penalty
        - 0.1 * symbol_inputs.fdv_stress_penalty
        - 0.1 * symbol_inputs.unlock_risk_penalty,
        0.0,
        1.0,
    )
    if support_score >= 0.65 and rotation_penalty <= 0.35:
        regime = "risk_on"
    elif support_score <= 0.35 or rotation_penalty >= 0.65:
        regime = "defensive"
    else:
        regime = "neutral"

    return FeatureVector(
        **{
            **features.as_dict(),
            "alt_market_regime": regime,
            "alt_breadth_score": round(breadth, 6),
            "alt_liquidity_support_score": round(liquidity_support, 6),
            "alt_fundamental_score": round(fundamental, 6),
            "alt_smart_money_score": round(smart_money, 6),
            "alt_rotation_penalty": round(rotation_penalty, 6),
        }
    )
