from quant_binance.bitget_entry_overlay import (
    BitgetMarketMetrics,
    apply_tuned_profiles,
    effective_round_trip_cost_bps,
    tune_symbol_profile,
)
from scripts.quant_bitget_long_failure_short_overlay import build_candidate_config


def _profile() -> dict[str, float]:
    return {
        "min_predictability_score": 70.0,
        "min_liquidity_score": 0.5,
        "min_volume_confirmation": 0.55,
        "min_net_edge_bps": 30.0,
        "min_edge_to_cost": 2.8,
        "max_stop_distance_bps": 260.0,
    }


def test_effective_cost_includes_bitget_taker_spread_and_slippage() -> None:
    metrics = BitgetMarketMetrics(
        symbol="DOGEUSDT",
        last_price=0.1,
        quote_volume_24h=50_000_000.0,
        change_24h_pct=1.0,
        spread_bps=1.0,
        funding_pct=-0.01,
        mark_basis_bps=-5.0,
        ema20_60_bps=35.0,
        rv15_bps=30.0,
        taker_buy_ratio_6h=0.54,
    )

    assert effective_round_trip_cost_bps(metrics) > 16.0


def test_pepe_strong_market_relaxes_one_step_but_caps_size() -> None:
    metrics = BitgetMarketMetrics(
        symbol="PEPEUSDT",
        last_price=0.000004,
        quote_volume_24h=45_000_000.0,
        change_24h_pct=1.2,
        spread_bps=0.25,
        funding_pct=-0.02,
        mark_basis_bps=-3.0,
        ema20_60_bps=45.0,
        rv15_bps=40.0,
        taker_error="HTTPError: 400",
    )

    result = tune_symbol_profile(metrics=metrics, baseline_profile=_profile())

    assert result["action"] == "relax_one_step"
    assert result["tuned_profile"]["min_predictability_score"] < 70.0
    assert result["tuned_profile"]["size_multiplier"] == 0.6
    assert "taker_flow_unavailable" in result["warnings"]


def test_doge_sell_dominant_taker_flow_keeps_confirm_only_and_raises_edge() -> None:
    metrics = BitgetMarketMetrics(
        symbol="DOGEUSDT",
        last_price=0.1,
        quote_volume_24h=55_000_000.0,
        change_24h_pct=1.0,
        spread_bps=1.0,
        funding_pct=0.0,
        mark_basis_bps=-4.0,
        ema20_60_bps=35.0,
        rv15_bps=28.0,
        taker_buy_ratio_6h=0.48,
    )

    result = tune_symbol_profile(metrics=metrics, baseline_profile=_profile())

    assert result["action"] == "confirm_only"
    assert result["tuned_profile"]["min_net_edge_bps"] > 30.0
    assert "recent_taker_flow_sell_dominant" in result["warnings"]


def test_apply_tuned_profiles_marks_candidate_paper_only() -> None:
    base = {"symbol_filter_profiles": {"DOGEUSDT": _profile()}}
    tuning = [
        {
            "symbol": "DOGEUSDT",
            "tuned_profile": {**_profile(), "min_predictability_score": 69.5},
        }
    ]

    result = apply_tuned_profiles(base, tuning)

    assert result["symbol_filter_profiles"]["DOGEUSDT"]["min_predictability_score"] == 69.5
    assert result["bitget_entry_overlay"]["paper_only"] is True


def test_long_failure_short_overlay_config_is_paper_only_and_separate() -> None:
    base = {"symbol_filter_profiles": {"BTCUSDT": _profile()}}
    report = {
        "match_window_minutes": 7.5,
        "leg_stats": [
            {
                "symbol": "ETHUSDT",
                "strategy": "oi_exhaustion_reversion",
                "side": "short",
                "matched_count": 2,
                "avg_ret15_bps": 22.9,
                "win15_rate": 1.0,
                "worst_ret15_bps": 21.6,
                "verdict": "paper_short_overlay_watch",
            },
            {
                "symbol": "SOLUSDT",
                "strategy": "crowded_long_unwind",
                "side": "short",
                "matched_count": 1,
                "avg_ret15_bps": -4.0,
                "win15_rate": 0.0,
                "worst_ret15_bps": -4.0,
                "verdict": "reject_or_shadow_only",
            },
        ],
    }

    result = build_candidate_config(base, report)

    overlay = result["long_failure_short_overlay"]
    assert overlay["enabled"] is True
    assert overlay["paper_only"] is True
    assert overlay["no_live_use_without_separate_approval"] is True
    assert overlay["conflict_policy"] == "do_not_open_short_if_long_is_active_or_accepted"
    assert [leg["symbol"] for leg in overlay["legs"]] == ["ETHUSDT"]
    assert result["bitget_entry_overlay"]["long_failure_short_overlay_enabled"] is True
