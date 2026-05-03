"""Unit tests for Session._refresh_cross_coin_dynamic_priority.

Tests the dynamic priority injection: cross-coin top-1 EV signal is written into
Settings.futures_exposure.priority_symbols / spot_support.priority_symbols each
cycle, with static fallback restoration when no signal exists.
"""

from __future__ import annotations

import os
import time
import types
from unittest import mock

import pytest

from quant_binance.cross_coin_scorer import SymbolState
from quant_binance.session import LivePaperSession as Session


def _make_state(sym: str, quad: str = "newLongs", ts_ms: int | None = None) -> SymbolState:
    if ts_ms is None:
        ts_ms = int(time.time() * 1000) - 60_000  # 1 min ago
    if quad == "newLongs":
        oi_d, p_d = +0.5, +5.0
    elif quad == "shortCover":
        oi_d, p_d = -0.5, +5.0
    elif quad == "newShorts":
        oi_d, p_d = +0.5, -5.0
    else:
        oi_d, p_d = -0.5, -5.0
    return SymbolState(
        symbol=sym,
        cycle_ts_ms=ts_ms,
        own_quadrant=quad,
        own_dir="up" if p_d > 0 else "down",
        oi_delta_pct=oi_d,
        price_delta_bps=p_d,
    )


def _build_mock_session(static_priority: tuple[str, ...]) -> object:
    """Build a minimal stand-in for Session with the attributes the refresh method touches."""
    fe = types.SimpleNamespace(priority_symbols=static_priority)
    ss = types.SimpleNamespace(priority_symbols=static_priority)
    settings = types.SimpleNamespace(futures_exposure=fe, spot_support=ss)
    paper_service = types.SimpleNamespace(settings=settings)
    runtime = types.SimpleNamespace(paper_service=paper_service)
    sess = types.SimpleNamespace(runtime=runtime)
    return sess


def _bind_refresh(sess) -> None:
    """Bind the unbound Session method to our SimpleNamespace mock."""
    sess._refresh_cross_coin_dynamic_priority = (
        Session._refresh_cross_coin_dynamic_priority.__get__(sess)
    )
    sess._cross_coin_gate_enabled = Session._cross_coin_gate_enabled.__get__(sess)
    # Constants
    for attr in (
        "_CROSS_COIN_ENV_FLAG",
        "_CROSS_COIN_PRIORITY_REFRESH_SEC",
    ):
        setattr(sess, attr, getattr(Session, attr))


@pytest.fixture
def env_gate_on(monkeypatch):
    monkeypatch.setenv("QUANT_CROSS_COIN_GATE", "1")
    yield


@pytest.fixture
def env_gate_off(monkeypatch):
    monkeypatch.delenv("QUANT_CROSS_COIN_GATE", raising=False)
    yield


def test_refresh_promotes_top_1_to_priority(env_gate_on):
    sess = _build_mock_session(static_priority=("PEPEUSDT",))
    _bind_refresh(sess)
    table = {"ev_threshold_bps": 5.0, "stale_minutes": 15}
    states = {"BTCUSDT": _make_state("BTCUSDT")}
    sess._cross_coin_ev_table_cached = lambda: table
    sess._cross_coin_states_cached = lambda: states
    ranked = [
        types.SimpleNamespace(symbol="BTCUSDT", ev_bps=12.71, winrate=0.83, n=30),
    ]
    with mock.patch(
        "quant_binance.session._cross_coin_rank_candidates", return_value=ranked
    ):
        sess._refresh_cross_coin_dynamic_priority()

    assert sess.runtime.paper_service.settings.futures_exposure.priority_symbols == ("BTCUSDT",)
    assert sess.runtime.paper_service.settings.spot_support.priority_symbols == ("BTCUSDT",)


def test_refresh_restores_static_when_no_signal(env_gate_on):
    sess = _build_mock_session(static_priority=("PEPEUSDT",))
    _bind_refresh(sess)
    table = {"ev_threshold_bps": 5.0, "stale_minutes": 15}
    states = {"BTCUSDT": _make_state("BTCUSDT")}
    sess._cross_coin_ev_table_cached = lambda: table
    sess._cross_coin_states_cached = lambda: states

    # First call with a signal: priority becomes BTC
    ranked_pos = [types.SimpleNamespace(symbol="BTCUSDT", ev_bps=12.71, winrate=0.83, n=30)]
    with mock.patch("quant_binance.session._cross_coin_rank_candidates", return_value=ranked_pos):
        sess._refresh_cross_coin_dynamic_priority()
    assert sess.runtime.paper_service.settings.futures_exposure.priority_symbols == ("BTCUSDT",)

    # Force throttle reset
    sess._cross_coin_priority_refreshed_at = 0.0

    # Second call with no signal: must restore static PEPE
    with mock.patch("quant_binance.session._cross_coin_rank_candidates", return_value=[]):
        sess._refresh_cross_coin_dynamic_priority()
    assert sess.runtime.paper_service.settings.futures_exposure.priority_symbols == ("PEPEUSDT",)
    assert sess.runtime.paper_service.settings.spot_support.priority_symbols == ("PEPEUSDT",)


def test_refresh_throttled_no_double_mutate(env_gate_on):
    sess = _build_mock_session(static_priority=("PEPEUSDT",))
    _bind_refresh(sess)
    table = {"ev_threshold_bps": 5.0, "stale_minutes": 15}
    states = {"BTCUSDT": _make_state("BTCUSDT")}
    sess._cross_coin_ev_table_cached = lambda: table
    sess._cross_coin_states_cached = lambda: states

    call_count = {"n": 0}

    def fake_rank(*a, **kw):
        call_count["n"] += 1
        return [types.SimpleNamespace(symbol="BTCUSDT", ev_bps=12.71, winrate=0.83, n=30)]

    with mock.patch("quant_binance.session._cross_coin_rank_candidates", side_effect=fake_rank):
        sess._refresh_cross_coin_dynamic_priority()  # actual refresh
        sess._refresh_cross_coin_dynamic_priority()  # throttled — must skip
        sess._refresh_cross_coin_dynamic_priority()  # throttled — must skip

    assert call_count["n"] == 1, "Throttle must prevent re-ranking within 60s"


def test_refresh_disabled_when_env_unset(env_gate_off):
    sess = _build_mock_session(static_priority=("PEPEUSDT",))
    _bind_refresh(sess)
    sess._cross_coin_ev_table_cached = lambda: {"ev_threshold_bps": 5.0, "stale_minutes": 15}
    sess._cross_coin_states_cached = lambda: {"BTCUSDT": _make_state("BTCUSDT")}

    with mock.patch(
        "quant_binance.session._cross_coin_rank_candidates",
        return_value=[types.SimpleNamespace(symbol="BTCUSDT", ev_bps=12.71, winrate=0.83, n=30)],
    ):
        sess._refresh_cross_coin_dynamic_priority()

    # Static priority preserved (env flag off → no-op)
    assert sess.runtime.paper_service.settings.futures_exposure.priority_symbols == ("PEPEUSDT",)


def test_refresh_no_op_when_data_missing(env_gate_on):
    sess = _build_mock_session(static_priority=("PEPEUSDT",))
    _bind_refresh(sess)
    # ev table missing
    sess._cross_coin_ev_table_cached = lambda: False
    sess._cross_coin_states_cached = lambda: {}

    with mock.patch("quant_binance.session._cross_coin_rank_candidates") as m:
        sess._refresh_cross_coin_dynamic_priority()
        assert not m.called  # rank never invoked when data missing

    assert sess.runtime.paper_service.settings.futures_exposure.priority_symbols == ("PEPEUSDT",)


def test_refresh_captures_static_fallback_on_first_call(env_gate_on):
    sess = _build_mock_session(static_priority=("PEPEUSDT", "DOGEUSDT"))
    _bind_refresh(sess)
    sess._cross_coin_ev_table_cached = lambda: {"ev_threshold_bps": 5.0, "stale_minutes": 15}
    sess._cross_coin_states_cached = lambda: {"BTCUSDT": _make_state("BTCUSDT")}

    with mock.patch(
        "quant_binance.session._cross_coin_rank_candidates",
        return_value=[types.SimpleNamespace(symbol="BTCUSDT", ev_bps=12.71, winrate=0.83, n=30)],
    ):
        sess._refresh_cross_coin_dynamic_priority()

    # Static captured includes both seeds — restoration must preserve both
    assert sess._cross_coin_static_priority_futures == ("PEPEUSDT", "DOGEUSDT")
    assert sess._cross_coin_static_priority_spot == ("PEPEUSDT", "DOGEUSDT")

    # Force throttle reset, then test no-signal restore
    sess._cross_coin_priority_refreshed_at = 0.0
    with mock.patch("quant_binance.session._cross_coin_rank_candidates", return_value=[]):
        sess._refresh_cross_coin_dynamic_priority()
    assert sess.runtime.paper_service.settings.futures_exposure.priority_symbols == ("PEPEUSDT", "DOGEUSDT")
