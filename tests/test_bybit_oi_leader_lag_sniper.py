from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.bybit_oi_leader_lag_sniper import (
    SymbolState,
    build_states,
    direction,
    explain_no_entry,
    generate_candidates,
    monitor_active_position,
    open_paper_position,
    quadrant,
    simulate_exit,
)


def _state(
    symbol: str,
    quad: str,
    price_delta_bps: float = 5.0,
    oi_delta_pct: float = 0.05,
    last_price: float | None = None,
) -> SymbolState:
    if quad == "newLongs":
        p, oi = abs(price_delta_bps), abs(oi_delta_pct)
    elif quad == "shortCover":
        p, oi = abs(price_delta_bps), -abs(oi_delta_pct)
    elif quad == "newShorts":
        p, oi = -abs(price_delta_bps), abs(oi_delta_pct)
    else:
        p, oi = -abs(price_delta_bps), -abs(oi_delta_pct)
    return SymbolState(
        symbol=symbol,
        timestamp="2026-05-05T00:00:00+00:00",
        baseline_timestamp="2026-05-04T23:58:00+00:00",
        age_seconds=120.0,
        last_price=last_price if last_price is not None else (100.0 if symbol != "PEPEUSDT" else 0.00001),
        open_interest=1000.0,
        price_delta_bps=p,
        oi_delta_pct=oi,
        quadrant=quad,
        direction=direction(p, neutral_bps=1.5),
        buy_ratio=0.52,
        sell_ratio=0.48,
        account_long_short_ratio=1.083333,
        spread_bps=0.5,
    )


def test_quadrant_classification() -> None:
    assert quadrant(3.0, 0.1) == "newLongs"
    assert quadrant(3.0, -0.1) == "shortCover"
    assert quadrant(-3.0, 0.1) == "newShorts"
    assert quadrant(-3.0, -0.1) == "longUnwind"


def test_build_states_uses_local_two_minute_snapshot_delta() -> None:
    now = datetime(2026, 5, 5, tzinfo=UTC)
    baseline = now - timedelta(seconds=120)
    state = {
        "snapshots": {
            "ETHUSDT": [
                {
                    "symbol": "ETHUSDT",
                    "timestamp": baseline.isoformat(),
                    "last_price": 100.0,
                    "open_interest": 1000.0,
                    "spread_bps": 0.5,
                    "buy_ratio": 0.51,
                    "sell_ratio": 0.49,
                    "account_long_short_ratio": 1.040816,
                }
            ]
        }
    }
    metric = type(
        "Metric",
        (),
        {
            "symbol": "ETHUSDT",
            "timestamp": now.isoformat(),
            "last_price": 100.1,
            "open_interest": 1005.0,
            "buy_ratio": 0.52,
            "sell_ratio": 0.48,
            "account_long_short_ratio": 1.083333,
            "spread_bps": 0.4,
        },
    )()

    states = build_states(state, [metric], lookback_seconds=120, tolerance_seconds=10, neutral_bps=1.5)

    assert states["ETHUSDT"].quadrant == "newLongs"
    assert states["ETHUSDT"].price_delta_bps == 10.0
    assert states["ETHUSDT"].oi_delta_pct == 0.5


def test_generate_candidates_matches_three_explicit_profiles() -> None:
    states = {
        "BTCUSDT": _state("BTCUSDT", "newLongs"),
        "ETHUSDT": _state("ETHUSDT", "newLongs"),
        "PEPEUSDT": _state("PEPEUSDT", "newLongs"),
        "DOGEUSDT": _state("DOGEUSDT", "newShorts"),
    }

    rows = generate_candidates(
        states,
        profile="exploratory",
        neutral_bps=1.5,
        min_price_delta_bps=1.0,
        min_oi_delta_pct=0.01,
        max_spread_bps=3.0,
        tp_bps=45.0,
        sl_bps=22.0,
        time_stop_minutes=15,
    )

    strategies = {row["strategy"] for row in rows}
    assert "eth_new_longs_leader_not_bearish" in strategies
    assert "pepe_new_longs_btc_eth_new_longs" in strategies
    assert "doge_new_shorts_btc_weak_or_neutral" not in strategies

    states = {
        "BTCUSDT": _state("BTCUSDT", "longUnwind", price_delta_bps=0.8, oi_delta_pct=0.05),
        "DOGEUSDT": _state("DOGEUSDT", "newShorts"),
    }
    rows = generate_candidates(
        states,
        profile="exploratory",
        neutral_bps=1.5,
        min_price_delta_bps=1.0,
        min_oi_delta_pct=0.01,
        max_spread_bps=3.0,
        tp_bps=45.0,
        sl_bps=22.0,
        time_stop_minutes=15,
    )
    assert {row["strategy"] for row in rows} == {"doge_new_shorts_btc_weak_or_neutral"}


def test_strict_pepe_profile_only_emits_pepe_alignment() -> None:
    states = {
        "BTCUSDT": _state("BTCUSDT", "newLongs"),
        "ETHUSDT": _state("ETHUSDT", "newLongs"),
        "1000PEPEUSDT": _state("1000PEPEUSDT", "newLongs"),
        "DOGEUSDT": _state("DOGEUSDT", "newShorts"),
    }

    rows = generate_candidates(
        states,
        profile="strict-pepe",
        neutral_bps=1.5,
        min_price_delta_bps=1.0,
        min_oi_delta_pct=0.01,
        max_spread_bps=3.0,
        tp_bps=60.0,
        sl_bps=25.0,
        time_stop_minutes=60,
    )

    assert [row["strategy"] for row in rows] == ["pepe_new_longs_btc_eth_new_longs"]
    assert rows[0]["symbol"] == "1000PEPEUSDT"
    assert rows[0]["tp_bps"] == 60.0
    assert rows[0]["sl_bps"] == 25.0
    assert rows[0]["time_stop_minutes"] == 60


def test_explain_no_entry_reports_blocking_alignment_reasons() -> None:
    states = {
        "BTCUSDT": _state("BTCUSDT", "longUnwind"),
        "ETHUSDT": _state("ETHUSDT", "newLongs"),
        "1000PEPEUSDT": _state("1000PEPEUSDT", "newLongs"),
    }

    reasons = explain_no_entry(
        states,
        profile="strict-pepe",
        min_price_delta_bps=1.0,
        min_oi_delta_pct=0.01,
        max_spread_bps=3.0,
    )

    assert "btc_not_newLongs:longUnwind" in reasons


def test_monitor_active_position_exits_on_live_paper_tp() -> None:
    candidate = {
        "timestamp": "2026-05-05T00:00:00+00:00",
        "symbol": "1000PEPEUSDT",
        "strategy": "pepe_new_longs_btc_eth_new_longs",
        "side": "long",
        "reference_price": 100.0,
        "tp_bps": 60.0,
        "sl_bps": 25.0,
        "time_stop_minutes": 60,
        "leader_symbols": ["BTCUSDT", "ETHUSDT"],
    }
    position = open_paper_position(candidate)
    states = {"1000PEPEUSDT": _state("1000PEPEUSDT", "newLongs", last_price=100.7)}

    event, outcome = monitor_active_position(
        position,
        states,
        now=datetime(2026, 5, 5, 0, 5, tzinfo=UTC),
    )

    assert event["action"] == "exit"
    assert event["reason"] == "tp_live_paper"
    assert outcome is not None
    assert outcome["ret_bps"] == 70.0


def test_monitor_active_position_exits_on_leader_reversal() -> None:
    candidate = {
        "timestamp": "2026-05-05T00:00:00+00:00",
        "symbol": "1000PEPEUSDT",
        "strategy": "pepe_new_longs_btc_eth_new_longs",
        "side": "long",
        "reference_price": 100.0,
        "tp_bps": 60.0,
        "sl_bps": 25.0,
        "time_stop_minutes": 60,
        "leader_symbols": ["BTCUSDT", "ETHUSDT"],
    }
    position = open_paper_position(candidate)
    states = {
        "1000PEPEUSDT": _state("1000PEPEUSDT", "newLongs", last_price=100.1),
        "BTCUSDT": _state("BTCUSDT", "longUnwind", price_delta_bps=5.0),
        "ETHUSDT": _state("ETHUSDT", "newLongs"),
    }

    event, outcome = monitor_active_position(
        position,
        states,
        now=datetime(2026, 5, 5, 0, 5, tzinfo=UTC),
    )

    assert event["action"] == "exit"
    assert event["reason"].startswith("leader_reversal:BTCUSDT")
    assert outcome is not None


def test_simulate_exit_prefers_conservative_sl_when_tp_and_sl_same_bar() -> None:
    candidate = {
        "timestamp": "2026-05-05T00:00:00+00:00",
        "symbol": "ETHUSDT",
        "strategy": "eth_new_longs_leader_not_bearish",
        "side": "long",
        "reference_price": 100.0,
        "tp_bps": 45.0,
        "sl_bps": 22.0,
        "time_stop_minutes": 15,
    }
    bars = [
        {
            "open_time": datetime(2026, 5, 5, 0, 1, tzinfo=UTC).timestamp() * 1000,
            "open": 100.0,
            "high": 100.5,
            "low": 99.7,
            "close": 100.1,
        }
    ]

    outcome = simulate_exit(candidate, bars)

    assert outcome is not None
    assert outcome["exit_reason"] == "sl_conservative_same_bar"
    assert outcome["ret_bps"] == -22.0


def test_simulate_exit_short_tp() -> None:
    candidate = {
        "timestamp": "2026-05-05T00:00:00+00:00",
        "symbol": "DOGEUSDT",
        "strategy": "doge_new_shorts_btc_weak_or_neutral",
        "side": "short",
        "reference_price": 100.0,
        "tp_bps": 45.0,
        "sl_bps": 22.0,
        "time_stop_minutes": 15,
    }
    bars = [
        {
            "open_time": datetime(2026, 5, 5, 0, 2, tzinfo=UTC).timestamp() * 1000,
            "open": 100.0,
            "high": 100.1,
            "low": 99.5,
            "close": 99.6,
        }
    ]

    outcome = simulate_exit(candidate, bars)

    assert outcome is not None
    assert outcome["exit_reason"] == "tp"
    assert outcome["ret_bps"] == 45.0
