from __future__ import annotations

from statistics import mean, median, pstdev
from pathlib import Path

from quant_binance.cost_calibration import CostCalibration, load_cost_calibration
from quant_binance.data.state import KlineBar, SymbolMarketState
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.models import FeatureVector
from quant_binance.settings import Settings
from quant_binance.strategy.scorer import compute_predictability_score
from quant_binance.strategy.edge import ConditionalEdgeLookup
from quant_binance.strategy.normalize import clamp


def _pct_returns(bars: list[KlineBar]) -> list[float]:
    returns: list[float] = []
    for prev, curr in zip(bars, bars[1:]):
        if prev.close_price > 0:
            returns.append((curr.close_price / prev.close_price) - 1.0)
    return returns


def _true_ranges(bars: list[KlineBar]) -> list[float]:
    if not bars:
        return []
    ranges: list[float] = []
    prev_close = bars[0].close_price
    for bar in bars[1:]:
        high_low = bar.high_price - bar.low_price
        high_prev = abs(bar.high_price - prev_close)
        low_prev = abs(bar.low_price - prev_close)
        ranges.append(max(high_low, high_prev, low_prev))
        prev_close = bar.close_price
    return ranges


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    ema = values[0]
    for value in values[1:]:
        ema = alpha * value + (1.0 - alpha) * ema
    return ema


def _recent_closed_bars(state: SymbolMarketState, interval: str, limit: int) -> list[KlineBar]:
    bars = [bar for bar in state.klines.get(interval, []) if bar.is_closed]
    return bars[-limit:]


def _intraday_trend_signal(
    *,
    bars_5m: list[KlineBar],
    bars_1m: list[KlineBar],
) -> tuple[int, float]:
    components: list[tuple[int, float]] = []
    closes_5m = [bar.close_price for bar in bars_5m]
    if len(closes_5m) >= 8:
        ema_fast_5m = _ema(closes_5m[-3:], min(3, len(closes_5m[-3:])))
        ema_slow_5m = _ema(closes_5m[-8:], min(8, len(closes_5m[-8:])))
        ret_5m = (closes_5m[-1] / closes_5m[-4] - 1.0) if closes_5m[-4] > 0 else 0.0
        if ema_fast_5m > ema_slow_5m and ret_5m > 0:
            components.append((1, clamp(abs(ret_5m) * 1800.0 + 0.35)))
        elif ema_fast_5m < ema_slow_5m and ret_5m < 0:
            components.append((-1, clamp(abs(ret_5m) * 1800.0 + 0.35)))

    closes_1m = [bar.close_price for bar in bars_1m]
    if len(closes_1m) >= 12:
        ema_fast_1m = _ema(closes_1m[-5:], min(5, len(closes_1m[-5:])))
        ema_slow_1m = _ema(closes_1m[-12:], min(12, len(closes_1m[-12:])))
        ret_1m = (closes_1m[-1] / closes_1m[-6] - 1.0) if closes_1m[-6] > 0 else 0.0
        if ema_fast_1m > ema_slow_1m and ret_1m > 0:
            components.append((1, clamp(abs(ret_1m) * 3200.0 + 0.25)))
        elif ema_fast_1m < ema_slow_1m and ret_1m < 0:
            components.append((-1, clamp(abs(ret_1m) * 3200.0 + 0.25)))

    if not components:
        return 0, 0.0
    signed_strength = sum(direction * strength for direction, strength in components)
    if signed_strength > 0:
        return 1, round(min(abs(signed_strength), 1.0), 6)
    if signed_strength < 0:
        return -1, round(min(abs(signed_strength), 1.0), 6)
    return 0, 0.0


class MarketFeatureExtractor:
    def __init__(
        self,
        settings: Settings,
        edge_lookup: ConditionalEdgeLookup | None = None,
        cost_calibration: CostCalibration | None = None,
    ) -> None:
        self.settings = settings
        self.edge_lookup = edge_lookup
        if cost_calibration is not None:
            self.cost_calibration = cost_calibration
        else:
            calibration_path = Path(__file__).resolve().parents[2] / "quant_runtime" / "artifacts" / "cost_calibration.json"
            self.cost_calibration = load_cost_calibration(calibration_path)

    def build_history_context(self, state: SymbolMarketState) -> FeatureHistoryContext:
        bars_1h = _recent_closed_bars(state, "1h", 120)
        bars_4h = _recent_closed_bars(state, "4h", 120)
        returns_1h = tuple(_pct_returns(bars_1h) or [0.0])
        returns_4h = tuple(_pct_returns(bars_4h) or [0.0])
        quote_volume_5m = tuple(bar.quote_volume for bar in _recent_closed_bars(state, "5m", 120) or [])
        quote_volume_1h = tuple(bar.quote_volume for bar in bars_1h or [])
        realized_vol_1h = tuple(abs(value) for value in returns_1h)
        realized_vol_4h = tuple(abs(value) for value in returns_4h)
        funding_abs = tuple(abs(value) for value in (state.funding_rate_samples or [state.funding_rate]))
        basis_abs = tuple(abs(value) for value in (state.basis_bps_samples or [state.basis_bps]))
        oi_values = state.open_interest_samples or [state.open_interest]
        oi_surge = []
        for index, value in enumerate(oi_values):
            base = mean(oi_values[max(0, index - self.settings.feature_thresholds.oi_ema_hours + 1) : index + 1])
            oi_surge.append(max(value / max(base, 1e-9) - 1.0, 0.0))
        return FeatureHistoryContext(
            returns_1h=returns_1h,
            returns_4h=returns_4h,
            quote_volume_5m=quote_volume_5m or (0.0,),
            quote_volume_1h=quote_volume_1h or (0.0,),
            realized_vol_1h=realized_vol_1h or (0.0,),
            realized_vol_4h=realized_vol_4h or (0.0,),
            funding_abs=funding_abs,
            basis_abs=basis_abs,
            oi_surge=tuple(oi_surge or [0.0]),
        )

    def build_primitive_inputs(self, state: SymbolMarketState) -> PrimitiveInputs:
        bars_1h = _recent_closed_bars(state, "1h", 120)
        bars_4h = _recent_closed_bars(state, "4h", 120)
        bars_5m = _recent_closed_bars(state, "5m", 40)
        bars_1m = _recent_closed_bars(state, "1m", 80)
        if len(bars_1h) < 21:
            raise ValueError("at least 21 closed 1h bars are required for primitive extraction")
        if len(bars_4h) < 2 or len(bars_5m) < 2:
            raise ValueError("insufficient closed bars for primitive extraction")

        returns_1h = _pct_returns(bars_1h)
        returns_4h = _pct_returns(bars_4h)
        closes_1h = [bar.close_price for bar in bars_1h]

        ema_fast = _ema(closes_1h[-20:], min(20, len(closes_1h[-20:])))
        ema_mid = _ema(closes_1h[-50:], min(50, len(closes_1h[-50:])))
        ema_slow = _ema(closes_1h[-100:], min(100, len(closes_1h[-100:])))
        if ema_fast > ema_mid > ema_slow:
            trend_direction = 1
            ema_stack_score = 1.0
        elif ema_fast < ema_mid < ema_slow:
            trend_direction = -1
            ema_stack_score = 1.0
        elif (ema_fast > ema_mid and closes_1h[-1] > ema_slow) or (ema_fast < ema_mid and closes_1h[-1] < ema_slow):
            trend_direction = 1 if closes_1h[-1] > ema_slow else -1
            ema_stack_score = 0.5
        else:
            trend_direction = 0
            ema_stack_score = 0.0

        intraday_bias, intraday_strength = _intraday_trend_signal(
            bars_5m=bars_5m,
            bars_1m=bars_1m,
        )
        if trend_direction == 0 and intraday_bias != 0:
            trend_direction = intraday_bias
            ema_stack_score = max(ema_stack_score, round(0.4 + 0.35 * intraday_strength, 6))
        elif intraday_bias != 0 and intraday_bias == trend_direction:
            ema_stack_score = min(1.0, round(ema_stack_score + 0.25 * intraday_strength, 6))
        elif intraday_bias != 0 and intraday_bias != trend_direction and intraday_strength >= 0.45:
            trend_direction = intraday_bias
            ema_stack_score = max(0.6, round(0.5 + 0.3 * intraday_strength, 6))

        lookback = bars_1h[-21:-1]
        breakout_reference_price = (
            max(bar.high_price for bar in lookback)
            if trend_direction >= 0
            else min(bar.low_price for bar in lookback)
        )
        true_ranges = _true_ranges(bars_1h[-15:])
        atr_14_1h_price = mean(true_ranges[-14:]) if true_ranges else 0.0

        buy_taker_quote = sum(
            trade.price * trade.quantity for trade in state.trades[-100:] if not trade.is_buyer_maker
        )
        sell_taker_quote = sum(
            trade.price * trade.quantity for trade in state.trades[-100:] if trade.is_buyer_maker
        )
        spread_bps = (
            ((state.top_of_book.ask_price - state.top_of_book.bid_price) / state.last_trade_price) * 10000.0
            if state.last_trade_price > 0
            else 0.0
        )
        depth_usd_within_10bps = (
            (state.top_of_book.bid_qty + state.top_of_book.ask_qty) * state.last_trade_price
        )
        order_book_imbalance_std = pstdev(state.order_book_imbalance_samples[-30:]) if len(state.order_book_imbalance_samples) > 1 else 0.0
        realized_vol_1h = pstdev(returns_1h[-20:]) if len(returns_1h) > 1 else 0.0
        realized_vol_4h = pstdev(returns_4h[-20:]) if len(returns_4h) > 1 else 0.0
        median_realized_vol_1h_30d = median(abs(value) for value in returns_1h[-30:]) if returns_1h else 0.0
        open_interest_ema = _ema(state.open_interest_samples[-self.settings.feature_thresholds.oi_ema_hours :], min(self.settings.feature_thresholds.oi_ema_hours, len(state.open_interest_samples[-self.settings.feature_thresholds.oi_ema_hours :]))) if state.open_interest_samples else state.open_interest
        gross_expected_edge_bps = 0.0
        if self.edge_lookup is not None:
            score_hint = 80.0 if trend_direction != 0 else 50.0
            lookup_value = self.edge_lookup.expected_edge_bps(
                symbol=state.symbol,
                mode="futures" if trend_direction != 0 else "spot",
                predictability_score=score_hint,
                trend_direction=trend_direction or 1,
            )
            if lookup_value is not None:
                gross_expected_edge_bps = lookup_value

        return PrimitiveInputs(
            ret_1h=returns_1h[-1],
            ret_4h=returns_4h[-1],
            trend_direction=trend_direction,
            ema_stack_score=ema_stack_score,
            breakout_reference_price=breakout_reference_price,
            last_trade_price=state.last_trade_price,
            atr_14_1h_price=atr_14_1h_price,
            quote_volume_5m=bars_5m[-1].quote_volume,
            quote_volume_1h=bars_1h[-1].quote_volume,
            buy_taker_volume=buy_taker_quote,
            sell_taker_volume=sell_taker_quote,
            spread_bps=spread_bps,
            probe_slippage_bps=spread_bps * 1.5,
            depth_usd_within_10bps=depth_usd_within_10bps,
            order_book_imbalance_std=order_book_imbalance_std,
            realized_vol_1h=realized_vol_1h,
            realized_vol_4h=realized_vol_4h,
            median_realized_vol_1h_30d=median_realized_vol_1h_30d,
            funding_rate=state.funding_rate,
            open_interest=state.open_interest,
            open_interest_ema=open_interest_ema,
            basis_bps=state.basis_bps,
            gross_expected_edge_bps=gross_expected_edge_bps,
            intraday_trend_direction=intraday_bias,
            intraday_trend_strength=intraday_strength,
        )

    def enrich_feature_vector(self, *, state: SymbolMarketState, features: FeatureVector) -> FeatureVector:
        bars_1h = _recent_closed_bars(state, "1h", 120)
        if len(bars_1h) < 50:
            return features
        closes_1h = [bar.close_price for bar in bars_1h]
        ema20 = _ema(closes_1h[-20:], min(20, len(closes_1h[-20:])))
        ema50 = _ema(closes_1h[-50:], min(50, len(closes_1h[-50:])))
        lookback = bars_1h[-21:-1]
        local_low = min(bar.low_price for bar in lookback)
        local_high = max(bar.high_price for bar in lookback)
        range_size = max(local_high - local_low, 1e-9)
        fib50 = local_low + 0.5 * range_size
        fib618 = local_low + 0.618 * range_size

        support_hits = 0
        support_hits += 1 if abs(state.last_trade_price - ema20) / state.last_trade_price <= 0.01 else 0
        support_hits += 1 if fib50 <= state.last_trade_price <= fib618 else 0
        support_hits += 1 if abs(state.last_trade_price - local_low) / state.last_trade_price <= 0.012 else 0
        support_alignment = min(support_hits / 3.0, 1.0)

        resistance_hits = 0
        resistance_hits += 1 if abs(state.last_trade_price - ema50) / state.last_trade_price <= 0.01 else 0
        resistance_hits += 1 if abs(state.last_trade_price - local_high) / state.last_trade_price <= 0.012 else 0
        resistance_penalty = min(resistance_hits / 2.0, 1.0)

        enriched = FeatureVector(
            **{
                **features.as_dict(),
                "support_alignment": round(support_alignment, 6),
                "resistance_penalty": round(resistance_penalty, 6),
            }
        )
        if self.cost_calibration is not None:
            calibration = self.cost_calibration.for_symbol(state.symbol)
            enriched = FeatureVector(
                **{
                    **enriched.as_dict(),
                    "empirical_fee_bps": calibration.empirical_fee_bps,
                    "empirical_entry_slippage_bps": calibration.empirical_entry_slippage_bps,
                    "empirical_exit_slippage_bps": calibration.empirical_exit_slippage_bps,
                }
            )
        score = compute_predictability_score(enriched, self.settings)
        return FeatureVector(**{**enriched.as_dict(), "predictability_score": score})
