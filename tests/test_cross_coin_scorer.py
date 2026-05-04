"""Unit tests for cross_coin_scorer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_binance.cross_coin_scorer import (
    CycleSnapshot,
    SymbolState,
    compute_state,
    is_blocked,
    load_ev_table,
    rank_candidates,
    score_symbol,
)


REPO = Path(__file__).resolve().parents[1]
EV_TABLE_PATH = REPO / "quant_runtime_paper50" / "cross_coin_ev_table.json"

NOW_MS = 1_745_625_600_000  # 2026-04-26 00:00:00 UTC, arbitrary anchor
RECENT_MS = NOW_MS - 5 * 60_000   # 5 min ago — fresh
STALE_MS = NOW_MS - 20 * 60_000   # 20 min ago — stale


@pytest.fixture(scope="module")
def ev_table():
    return load_ev_table(EV_TABLE_PATH)


def _state(sym: str, quad: str, ts_ms: int = RECENT_MS) -> SymbolState:
    """Build a SymbolState matching the requested quadrant."""
    if quad == "newLongs":
        oi_d, p_d = +0.5, +5.0
    elif quad == "shortCover":
        oi_d, p_d = -0.5, +5.0
    elif quad == "newShorts":
        oi_d, p_d = +0.5, -5.0
    else:  # longUnwind
        oi_d, p_d = -0.5, -5.0
    return SymbolState(
        symbol=sym,
        cycle_ts_ms=ts_ms,
        own_quadrant=quad,
        own_dir="up" if p_d > 0 else "down",
        oi_delta_pct=oi_d,
        price_delta_bps=p_d,
    )


def test_compute_state_quadrant_classification():
    snaps = [
        CycleSnapshot("BTCUSDT", RECENT_MS - 7 * 60_000, 100.0, 50000.0),
        CycleSnapshot("BTCUSDT", RECENT_MS, 101.0, 50100.0),  # OI↑ price↑
    ]
    s = compute_state(snaps)
    assert s is not None
    assert s.own_quadrant == "newLongs"
    assert s.own_dir == "up"


def test_compute_state_short_cover():
    snaps = [
        CycleSnapshot("PEPEUSDT", RECENT_MS - 7 * 60_000, 200.0, 0.0001),
        CycleSnapshot("PEPEUSDT", RECENT_MS, 198.0, 0.000101),  # OI↓ price↑
    ]
    s = compute_state(snaps)
    assert s.own_quadrant == "shortCover"


def test_compute_state_insufficient_history():
    snaps = [CycleSnapshot("BTCUSDT", RECENT_MS, 100.0, 50000.0)]
    assert compute_state(snaps) is None


def test_compute_state_zero_oi_returns_none():
    snaps = [
        CycleSnapshot("BTCUSDT", RECENT_MS - 7 * 60_000, 0.0, 50000.0),
        CycleSnapshot("BTCUSDT", RECENT_MS, 100.0, 50100.0),
    ]
    assert compute_state(snaps) is None


def test_score_symbol_pepe_newLongs_btc_newLongs_top_signal(ev_table):
    """Conflict 1 verification: most-specific scenario wins."""
    own = _state("PEPEUSDT", "newLongs")
    leader = _state("BTCUSDT", "newLongs")
    score = score_symbol(ev_table, own, leader, now_ms=NOW_MS)
    assert score is not None
    assert score.symbol == "PEPEUSDT"
    assert score.side == "long"
    assert score.rank == 1
    assert score.ev_bps == pytest.approx(12.71, rel=1e-3)
    assert score.matched_scenario["leader_quadrant"] == "newLongs"  # specific match
    assert score.blocker_match is None


def test_score_symbol_pepe_newLongs_btc_up_falls_back_to_dir_match(ev_table):
    """When leader_quadrant doesn't match top scenario, fall back to leader_dir match."""
    own = _state("PEPEUSDT", "newLongs")
    leader = _state("BTCUSDT", "shortCover")  # BTC P↑+OI↓ → also btc_dir=up
    score = score_symbol(ev_table, own, leader, now_ms=NOW_MS)
    assert score is not None
    assert score.rank == 3  # rank 3 is the leader_dir=up scenario
    assert score.ev_bps == pytest.approx(5.06, rel=1e-3)


def test_score_symbol_blocker_pepe_shortCover_btc_up(ev_table):
    """Blocker: PEPE shortCover + BTC up should be blocked."""
    own = _state("PEPEUSDT", "shortCover")
    leader = _state("BTCUSDT", "newLongs")  # btc_dir=up
    score = score_symbol(ev_table, own, leader, now_ms=NOW_MS)
    assert score is not None
    assert score.blocker_match is not None
    assert score.blocker_match["symbol"] == "PEPEUSDT"
    assert "shortCover" in score.blocker_match["own_quadrant"]


def test_score_symbol_eth_newLongs_btc_up_blocked(ev_table):
    """ETH newLongs + BTC up is a blocker (counter-rotation principle)."""
    own = _state("ETHUSDT", "newLongs")
    leader = _state("BTCUSDT", "newLongs")  # btc_dir=up
    score = score_symbol(ev_table, own, leader, now_ms=NOW_MS)
    assert score is not None
    assert score.blocker_match is not None
    assert score.blocker_match["symbol"] == "ETHUSDT"


def test_score_symbol_no_match_returns_none(ev_table):
    """Symbol with no matching scenario or blocker → None."""
    own = _state("BTCUSDT", "longUnwind")  # not in scenarios, not in blockers
    leader = _state("ETHUSDT", "newLongs")
    score = score_symbol(ev_table, own, leader, now_ms=NOW_MS)
    assert score is None


def test_score_symbol_stale_snapshot_marked(ev_table):
    """Conflict 4: stale snapshot is marked but rank_candidates filters it out."""
    own = _state("PEPEUSDT", "newLongs", ts_ms=STALE_MS)
    leader = _state("BTCUSDT", "newLongs", ts_ms=STALE_MS)
    score = score_symbol(ev_table, own, leader, now_ms=NOW_MS)
    assert score is not None
    assert score.stale is True


def test_rank_candidates_filters_stale_and_blocked_and_below_threshold(ev_table):
    """End-to-end ranker: stale + blocker + below-threshold must drop out."""
    states = {
        "PEPEUSDT": _state("PEPEUSDT", "newLongs", ts_ms=RECENT_MS),         # +12.71 (top)
        "BTCUSDT": _state("BTCUSDT", "newLongs", ts_ms=RECENT_MS),           # used as leader
        "ETHUSDT": _state("ETHUSDT", "newLongs", ts_ms=RECENT_MS),           # blocked (BTC up)
        "DOGEUSDT": _state("DOGEUSDT", "shortCover", ts_ms=RECENT_MS),       # blocked
        "SOLUSDT": _state("SOLUSDT", "longUnwind", ts_ms=STALE_MS),          # stale
    }
    ranked = rank_candidates(ev_table, states, now_ms=NOW_MS)
    # PEPE leads. BTC alone with leader=ETH(newLongs); BTC newLongs+ETH newLongs is NOT in scenarios → BTC drops.
    # Verify PEPE on top:
    assert len(ranked) >= 1
    assert ranked[0].symbol == "PEPEUSDT"
    assert ranked[0].ev_bps == pytest.approx(12.71, rel=1e-3)
    # No stale/blocked/below-threshold appears in result
    symbols_returned = {s.symbol for s in ranked}
    assert "ETHUSDT" not in symbols_returned  # blocked
    assert "DOGEUSDT" not in symbols_returned  # blocked
    assert "SOLUSDT" not in symbols_returned   # stale


def test_rank_candidates_threshold_filter(ev_table):
    """SOL longUnwind = +1.68 EV, below 5.0 threshold → dropped."""
    states = {
        "SOLUSDT": _state("SOLUSDT", "longUnwind"),
        "BTCUSDT": _state("BTCUSDT", "longUnwind"),  # leader; doesn't match SOL's blocker either
    }
    ranked = rank_candidates(ev_table, states, now_ms=NOW_MS)
    assert ranked == []  # SOL EV 1.68 < threshold 5.0


def test_rank_candidates_conflict2_takes_top_only(ev_table):
    """Conflict 2: when multiple positive candidates exist, we return them sorted;
    caller takes only the top. Verify ordering is correct."""
    states = {
        "PEPEUSDT": _state("PEPEUSDT", "newLongs"),       # +12.71
        "BTCUSDT": _state("BTCUSDT", "newLongs"),         # leader for PEPE
        "ETHUSDT": _state("ETHUSDT", "newShorts"),        # leader of BTC; BTC own=newLongs + ETH=newShorts → +5.47
    }
    ranked = rank_candidates(ev_table, states, now_ms=NOW_MS)
    # PEPE +12.71 should be #1, BTC +5.47 should be #2
    assert len(ranked) == 2
    assert ranked[0].symbol == "PEPEUSDT"
    assert ranked[1].symbol == "BTCUSDT"
    assert ranked[0].ev_bps > ranked[1].ev_bps


def test_is_blocked_helper_pepe_shortCover_btc_up(ev_table):
    states = {
        "PEPEUSDT": _state("PEPEUSDT", "shortCover"),
        "BTCUSDT": _state("BTCUSDT", "newLongs"),  # BTC up
    }
    blocked, blocker = is_blocked(ev_table, states, "PEPEUSDT", now_ms=NOW_MS)
    assert blocked is True
    assert blocker is not None
    assert blocker["fwd_60m_bps"] < 0


def test_is_blocked_helper_clear_pass(ev_table):
    """PEPE newLongs + BTC newLongs should not be blocked."""
    states = {
        "PEPEUSDT": _state("PEPEUSDT", "newLongs"),
        "BTCUSDT": _state("BTCUSDT", "newLongs"),
    }
    blocked, _ = is_blocked(ev_table, states, "PEPEUSDT", now_ms=NOW_MS)
    assert blocked is False


def test_ev_table_loads_with_required_fields():
    table = load_ev_table(EV_TABLE_PATH)
    assert "scenarios" in table
    assert "blockers" in table
    assert "leader_per_symbol" in table
    assert table["ev_threshold_bps"] >= 0.0
    assert table["stale_minutes"] > 0
    for s in table["scenarios"]:
        for k in ("symbol", "side", "own_quadrant", "ev_bps", "rank"):
            assert k in s
    for b in table["blockers"]:
        for k in ("symbol", "own_quadrant", "fwd_60m_bps"):
            assert k in b
