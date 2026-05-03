#!/usr/bin/env python3
"""5m high-upside paper bot for small leveraged crypto sleeves.

This module is deliberately paper-only. It fetches public Bitget swap candles,
simulates virtual 5x long/short positions, writes local state/log/report files,
and never places, tests, cancels, or modifies exchange orders.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal as signal_mod
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "quant_runtime" / "jackpot_paper_bot_v1_state.json"
LOG_PATH = ROOT / "quant_runtime" / "jackpot_paper_bot_v1_log.jsonl"
REPORT_PATH = ROOT / "quant_runtime" / "jackpot_paper_bot_v1_report.json"

UNIVERSE = ("BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "DOGE/USDT:USDT")
TIMEFRAME = "5m"
HISTORY_BARS = 240
POLL_SEC = 60

PAPER_MARGIN_USD = 10.0
ROUND_TRIP_COST_BPS = 8.0
SLIPPAGE_BPS = 5.0
LEVERAGE = 5.0
LEVERAGE_PROFILES = (
    {
        "profile_id": "balanced_3x",
        "leverage": 3.0,
        "tp_roe_pct": 4.5,
        "runner_tp_roe_pct": 9.0,
        "min_sl_roe_pct": 1.8,
        "max_sl_roe_pct": 4.0,
        "trail_after_roe_pct": 3.8,
        "trail_giveback_roe_pct": 1.5,
    },
    {
        "profile_id": "jackpot_5x",
        "leverage": 5.0,
        "tp_roe_pct": 6.0,
        "runner_tp_roe_pct": 12.0,
        "min_sl_roe_pct": 2.5,
        "max_sl_roe_pct": 6.0,
        "trail_after_roe_pct": 5.0,
        "trail_giveback_roe_pct": 2.0,
    },
)
DEFAULT_PROFILE = LEVERAGE_PROFILES[-1]
TP_ROE_PCT = float(DEFAULT_PROFILE["tp_roe_pct"])
RUNNER_TP_ROE_PCT = float(DEFAULT_PROFILE["runner_tp_roe_pct"])
SL_ROE_PCT = -float(DEFAULT_PROFILE["min_sl_roe_pct"])
TRAIL_AFTER_ROE_PCT = float(DEFAULT_PROFILE["trail_after_roe_pct"])
TRAIL_GIVEBACK_ROE_PCT = float(DEFAULT_PROFILE["trail_giveback_roe_pct"])
TIME_EXIT_MINUTES = 45
DAILY_MAX_ENTRIES = 4
MIN_SCORE = 10.0
BREAKOUT_LOOKBACK_BARS = 12


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts_iso": _iso(), **payload}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def ema(values: np.ndarray, period: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    out = np.empty_like(arr)
    out[0] = arr[0]
    alpha = 2.0 / (period + 1.0)
    for idx in range(1, len(arr)):
        out[idx] = alpha * arr[idx] + (1.0 - alpha) * out[idx - 1]
    return out


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev_close = np.concatenate([[close[0]], close[:-1]])
    return np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))


def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    tr = true_range(high, low, close)
    up = np.diff(high, prepend=high[0])
    down = -np.diff(low, prepend=low[0])
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    atr_v = ema(tr, period)
    plus_di = 100.0 * ema(plus_dm, period) / np.maximum(atr_v, 1e-9)
    minus_di = 100.0 * ema(minus_dm, period) / np.maximum(atr_v, 1e-9)
    dx = 100.0 * np.abs(plus_di - minus_di) / np.maximum(plus_di + minus_di, 1e-9)
    return ema(dx, period)


def bollinger_width_rank(close: np.ndarray, period: int = 20) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    upper = np.zeros(len(close))
    lower = np.zeros(len(close))
    width = np.zeros(len(close))
    rank = np.zeros(len(close))
    for idx in range(len(close)):
        start = max(0, idx - period + 1)
        segment = close[start : idx + 1]
        middle = float(np.mean(segment))
        stdev = float(np.std(segment))
        upper[idx] = middle + 2.0 * stdev
        lower[idx] = middle - 2.0 * stdev
        width[idx] = (upper[idx] - lower[idx]) / max(middle, 1e-9)
        rank_start = max(0, idx - 99)
        rank_segment = width[rank_start : idx + 1]
        rank[idx] = float(np.sum(rank_segment <= width[idx]) / max(len(rank_segment), 1))
    return upper, lower, rank


def compute_features(klines: list[list[float]]) -> dict[str, np.ndarray] | None:
    arr = np.asarray(klines, dtype=float)
    if len(arr) < 80:
        return None
    open_ = arr[:, 1]
    high = arr[:, 2]
    low = arr[:, 3]
    close = arr[:, 4]
    volume = arr[:, 5]
    vol_ma = np.zeros(len(close))
    for idx in range(len(close)):
        start = max(0, idx - 19)
        vol_ma[idx] = float(np.mean(volume[start : idx + 1]))
    vol_r = volume / np.maximum(vol_ma, 1e-9)
    ema20 = ema(close, 20)
    ema50 = ema(close, 50)
    bb_upper, bb_lower, bb_rank = bollinger_width_rank(close)
    atr_v = ema(true_range(high, low, close), 14)
    atr_pct = atr_v / np.maximum(close, 1e-9)
    adx_v = adx(high, low, close)
    ret3 = np.zeros(len(close))
    ret6 = np.zeros(len(close))
    for idx in range(len(close)):
        if idx >= 3:
            ret3[idx] = close[idx] / close[idx - 3] - 1.0
        if idx >= 6:
            ret6[idx] = close[idx] / close[idx - 6] - 1.0
    return {
        "ts": arr[:, 0],
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "vol_r": vol_r,
        "ema20": ema20,
        "ema50": ema50,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_width_rank": bb_rank,
        "atr_pct": atr_pct,
        "adx": adx_v,
        "ret3": ret3,
        "ret6": ret6,
    }


def side_roe_pct(side: str, entry_price: float, price: float, leverage: float = LEVERAGE) -> float:
    if side == "long":
        return (price / entry_price - 1.0) * leverage * 100.0
    return (entry_price / price - 1.0) * leverage * 100.0


def apply_slippage(price: float, side: str, *, is_entry: bool) -> float:
    slip = SLIPPAGE_BPS / 10000.0
    if side == "long":
        return price * (1.0 + slip) if is_entry else price * (1.0 - slip)
    return price * (1.0 - slip) if is_entry else price * (1.0 + slip)


def _daily_key(ts: datetime | None = None) -> str:
    return (ts or _now()).date().isoformat()


@dataclass
class PaperPosition:
    symbol: str
    side: str
    entry_price: float
    entry_ts_ms: int
    entry_iso: str
    margin_usd: float
    leverage: float
    score: float
    signal: str
    profile_id: str = "jackpot_5x"
    tp_roe_pct: float = TP_ROE_PCT
    runner_tp_roe_pct: float = RUNNER_TP_ROE_PCT
    sl_roe_pct: float = SL_ROE_PCT
    trail_after_roe_pct: float = TRAIL_AFTER_ROE_PCT
    trail_giveback_roe_pct: float = TRAIL_GIVEBACK_ROE_PCT
    time_exit_minutes: int = TIME_EXIT_MINUTES
    tp1_taken: bool = False
    peak_roe_pct: float = 0.0
    snapshot: dict[str, float] = field(default_factory=dict)


@dataclass
class JackpotState:
    started_at: str = field(default_factory=_iso)
    last_check_at: str = ""
    last_event: str = "initialized"
    open_position: dict[str, Any] | None = None
    open_positions: dict[str, dict[str, Any]] = field(default_factory=dict)
    closed_trades: list[dict[str, Any]] = field(default_factory=list)
    daily_entry_count: dict[str, int] = field(default_factory=dict)
    total_entries: int = 0
    total_closed: int = 0
    wins: int = 0
    losses: int = 0
    cum_pnl_usd: float = 0.0
    paper_only: bool = True
    live_order_count: int = 0
    tested_order_count: int = 0


def load_state(path: Path = STATE_PATH) -> JackpotState:
    if not path.exists():
        return JackpotState()
    data = json.loads(path.read_text(encoding="utf-8"))
    return JackpotState(**data)


def save_state(state: JackpotState, path: Path = STATE_PATH) -> None:
    _write_json(path, asdict(state))


def build_entry_signal(
    symbol: str,
    ind: dict[str, np.ndarray],
    *,
    btc_features: dict[str, np.ndarray] | None = None,
    min_score: float = MIN_SCORE,
) -> dict[str, Any] | None:
    idx = len(ind["close"]) - 2
    close = float(ind["close"][idx])
    ret3 = float(ind["ret3"][idx])
    ret6 = float(ind["ret6"][idx])
    vol_r = float(ind["vol_r"][idx])
    bb_rank = float(ind["bb_width_rank"][idx])
    atr_pct = float(ind["atr_pct"][idx])
    adx_now = float(ind["adx"][idx])
    ema20_now = float(ind["ema20"][idx])
    ema50_now = float(ind["ema50"][idx])
    trend_up = close > ema20_now > ema50_now
    trend_down = close < ema20_now < ema50_now
    lookback_start = max(0, idx - BREAKOUT_LOOKBACK_BARS)
    previous_high = float(np.max(ind["high"][lookback_start:idx])) if idx > lookback_start else close
    previous_low = float(np.min(ind["low"][lookback_start:idx])) if idx > lookback_start else close
    long_breakout_bps = (close / max(previous_high, 1e-9) - 1.0) * 10000.0
    short_breakout_bps = (previous_low / max(close, 1e-9) - 1.0) * 10000.0
    long_structure = close >= previous_high * 0.9995 and long_breakout_bps >= -5.0
    short_structure = close <= previous_low * 1.0005 and short_breakout_bps >= -5.0
    volatility_ok = atr_pct >= 0.0015
    trend_ok_long = trend_up or close > ema20_now
    trend_ok_short = trend_down or close < ema20_now
    long_base = (
        long_structure
        and trend_ok_long
        and ret3 >= 0.002
        and ret6 >= 0.0035
        and vol_r >= 1.4
        and volatility_ok
        and adx_now >= 15.0
    )
    short_base = (
        short_structure
        and trend_ok_short
        and ret3 <= -0.002
        and ret6 <= -0.0035
        and vol_r >= 1.4
        and volatility_ok
        and adx_now >= 15.0
    )

    btc_gate = "neutral"
    if btc_features is not None and not symbol.startswith("BTC/"):
        bidx = len(btc_features["close"]) - 2
        btc_ret6 = float(btc_features["ret6"][bidx])
        btc_up = float(btc_features["ema20"][bidx]) >= float(btc_features["ema50"][bidx])
        btc_down = float(btc_features["ema20"][bidx]) <= float(btc_features["ema50"][bidx])
        if long_base and not (btc_up or btc_ret6 > -0.003):
            btc_gate = "blocked_long_risk_off"
            long_base = False
        elif short_base and not (btc_down or btc_ret6 < 0.003):
            btc_gate = "blocked_short_risk_on"
            short_base = False
        else:
            btc_gate = "pass"

    if not long_base and not short_base:
        return None

    side = "long" if long_base else "short"
    breakout_bps = long_breakout_bps if side == "long" else short_breakout_bps
    momentum = abs(ret3) * 700.0 + abs(ret6) * 450.0
    structure_score = max(breakout_bps, 0.0) * 0.45
    volume_score = max(vol_r - 1.0, 0.0) * 5.0
    volatility_score = min(atr_pct * 10000.0, 80.0) / 15.0
    confirmation_score = bb_rank * 1.5 + min(adx_now, 35.0) / 20.0
    score = momentum + structure_score + volume_score + volatility_score + confirmation_score
    if score < min_score:
        return None
    return {
        "symbol": symbol,
        "side": side,
        "signal": "5m_momentum_burst",
        "score": round(score, 6),
        "bar_ts_ms": int(ind["ts"][idx]),
        "bar_close": close,
        "snapshot": {
            "ret3": round(ret3, 8),
            "ret6": round(ret6, 8),
            "vol_r": round(vol_r, 6),
            "bb_width_rank": round(bb_rank, 6),
            "atr_pct": round(atr_pct, 8),
            "adx": round(adx_now, 6),
            "ema20": round(ema20_now, 8),
            "ema50": round(ema50_now, 8),
            "previous_high": round(previous_high, 8),
            "previous_low": round(previous_low, 8),
            "breakout_bps": round(breakout_bps, 6),
            "btc_gate": btc_gate,
        },
    }


def choose_best_signal(signals: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not signals:
        return None
    return sorted(signals, key=lambda row: (_safe_float(row.get("score")), row.get("symbol", "")), reverse=True)[0]


def _profile_by_id(profile_id: str) -> dict[str, Any]:
    for profile in LEVERAGE_PROFILES:
        if profile["profile_id"] == profile_id:
            return dict(profile)
    return dict(DEFAULT_PROFILE)


def _dynamic_sl_roe_pct(profile: dict[str, Any], entry: dict[str, Any]) -> float:
    atr_pct = _safe_float(dict(entry.get("snapshot") or {}).get("atr_pct"), 0.002)
    leverage = _safe_float(profile.get("leverage"), LEVERAGE)
    atr_roe = atr_pct * leverage * 100.0
    min_sl = _safe_float(profile.get("min_sl_roe_pct"), abs(SL_ROE_PCT))
    max_sl = _safe_float(profile.get("max_sl_roe_pct"), max(min_sl, abs(SL_ROE_PCT)))
    return -round(min(max(atr_roe * 1.15, min_sl), max_sl), 6)


def build_position(
    entry: dict[str, Any],
    fill_price: float,
    now_ms: int | None = None,
    *,
    profile: dict[str, Any] | None = None,
) -> PaperPosition:
    side = str(entry["side"])
    selected_profile = dict(profile or DEFAULT_PROFILE)
    leverage = _safe_float(selected_profile.get("leverage"), LEVERAGE)
    return PaperPosition(
        symbol=str(entry["symbol"]),
        side=side,
        entry_price=apply_slippage(fill_price, side, is_entry=True),
        entry_ts_ms=now_ms if now_ms is not None else int(time.time() * 1000),
        entry_iso=_iso(),
        margin_usd=PAPER_MARGIN_USD,
        leverage=leverage,
        score=_safe_float(entry.get("score")),
        signal=str(entry.get("signal") or "5m_momentum_burst"),
        profile_id=str(selected_profile.get("profile_id") or "jackpot_5x"),
        tp_roe_pct=_safe_float(selected_profile.get("tp_roe_pct"), TP_ROE_PCT),
        runner_tp_roe_pct=_safe_float(selected_profile.get("runner_tp_roe_pct"), RUNNER_TP_ROE_PCT),
        sl_roe_pct=_dynamic_sl_roe_pct(selected_profile, entry),
        trail_after_roe_pct=_safe_float(selected_profile.get("trail_after_roe_pct"), TRAIL_AFTER_ROE_PCT),
        trail_giveback_roe_pct=_safe_float(selected_profile.get("trail_giveback_roe_pct"), TRAIL_GIVEBACK_ROE_PCT),
        time_exit_minutes=TIME_EXIT_MINUTES,
        snapshot=dict(entry.get("snapshot") or {}),
    )


def evaluate_exit(
    position: PaperPosition,
    ind: dict[str, np.ndarray],
    *,
    now_ms: int | None = None,
) -> dict[str, Any] | None:
    idx = len(ind["close"]) - 2
    high = float(ind["high"][idx])
    low = float(ind["low"][idx])
    close = float(ind["close"][idx])
    ts_ms = int(ind["ts"][idx])
    current_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    hold_minutes = max(0.0, (current_ms - position.entry_ts_ms) / 60000.0)
    best_price = high if position.side == "long" else low
    worst_price = low if position.side == "long" else high
    best_roe = side_roe_pct(position.side, position.entry_price, best_price, position.leverage)
    worst_roe = side_roe_pct(position.side, position.entry_price, worst_price, position.leverage)
    close_roe = side_roe_pct(position.side, position.entry_price, close, position.leverage)
    position.peak_roe_pct = max(position.peak_roe_pct, best_roe)

    if worst_roe <= position.sl_roe_pct:
        exit_price = position.entry_price * (1.0 + (position.sl_roe_pct / 100.0 / position.leverage))
        if position.side == "short":
            exit_price = position.entry_price / (1.0 + (position.sl_roe_pct / 100.0 / position.leverage))
        exit_price = apply_slippage(exit_price, position.side, is_entry=False)
        return {"reason": "SL", "exit_price": exit_price, "exit_ts_ms": ts_ms}
    if best_roe >= position.runner_tp_roe_pct:
        exit_price = position.entry_price * (1.0 + (position.runner_tp_roe_pct / 100.0 / position.leverage))
        if position.side == "short":
            exit_price = position.entry_price / (1.0 + (position.runner_tp_roe_pct / 100.0 / position.leverage))
        exit_price = apply_slippage(exit_price, position.side, is_entry=False)
        return {"reason": "RUNNER_TP", "exit_price": exit_price, "exit_ts_ms": ts_ms}
    if best_roe >= position.tp_roe_pct:
        position.tp1_taken = True
    if position.tp1_taken and position.peak_roe_pct - close_roe >= position.trail_giveback_roe_pct and close_roe >= 0.0:
        return {"reason": "TRAIL_AFTER_TP1", "exit_price": apply_slippage(close, position.side, is_entry=False), "exit_ts_ms": ts_ms}
    if position.peak_roe_pct >= position.trail_after_roe_pct and position.peak_roe_pct - close_roe >= position.trail_giveback_roe_pct:
        return {"reason": "TRAIL", "exit_price": apply_slippage(close, position.side, is_entry=False), "exit_ts_ms": ts_ms}
    if hold_minutes >= position.time_exit_minutes:
        return {"reason": "TIME_EXIT", "exit_price": apply_slippage(close, position.side, is_entry=False), "exit_ts_ms": ts_ms}
    return None


def close_position(state: JackpotState, position: PaperPosition, exit_info: dict[str, Any]) -> dict[str, Any]:
    roe = side_roe_pct(position.side, position.entry_price, _safe_float(exit_info["exit_price"]), position.leverage)
    fee_usd = position.margin_usd * position.leverage * ROUND_TRIP_COST_BPS / 10000.0
    pnl_usd = position.margin_usd * roe / 100.0 - fee_usd
    trade = {
        "symbol": position.symbol,
        "side": position.side,
        "entry_price": round(position.entry_price, 10),
        "exit_price": round(_safe_float(exit_info["exit_price"]), 10),
        "entry_ts_ms": position.entry_ts_ms,
        "exit_ts_ms": int(exit_info["exit_ts_ms"]),
        "entry_iso": position.entry_iso,
        "exit_iso": _iso(),
        "reason": exit_info["reason"],
        "roe_pct": round(roe, 6),
        "pnl_usd": round(pnl_usd, 6),
        "fee_usd": round(fee_usd, 6),
        "score": round(position.score, 6),
        "signal": position.signal,
        "profile_id": position.profile_id,
        "leverage": position.leverage,
        "sl_roe_pct": position.sl_roe_pct,
        "tp_roe_pct": position.tp_roe_pct,
        "runner_tp_roe_pct": position.runner_tp_roe_pct,
        "paper_only": True,
    }
    state.closed_trades.append(trade)
    state.closed_trades = state.closed_trades[-200:]
    state.total_closed += 1
    state.wins += int(pnl_usd > 0.0)
    state.losses += int(pnl_usd <= 0.0)
    state.cum_pnl_usd = round(state.cum_pnl_usd + pnl_usd, 6)
    state.open_position = None
    state.last_event = f"CLOSE {position.symbol} {position.side} {exit_info['reason']} roe={roe:.2f}%"
    return trade


def summarize_state(state: JackpotState) -> dict[str, Any]:
    trades = state.closed_trades
    win_rate = round(state.wins / state.total_closed, 6) if state.total_closed else None
    avg_roe = round(sum(_safe_float(row.get("roe_pct")) for row in trades) / len(trades), 6) if trades else None
    by_reason: dict[str, int] = {}
    by_profile: dict[str, dict[str, Any]] = {}
    for row in trades:
        reason = str(row.get("reason") or "unknown")
        by_reason[reason] = by_reason.get(reason, 0) + 1
        profile_id = str(row.get("profile_id") or "unknown")
        profile = by_profile.setdefault(
            profile_id,
            {"closed": 0, "wins": 0, "losses": 0, "cum_pnl_usd": 0.0, "roe_sum": 0.0},
        )
        profile["closed"] += 1
        profile["wins"] += int(_safe_float(row.get("pnl_usd")) > 0.0)
        profile["losses"] += int(_safe_float(row.get("pnl_usd")) <= 0.0)
        profile["cum_pnl_usd"] = round(_safe_float(profile["cum_pnl_usd"]) + _safe_float(row.get("pnl_usd")), 6)
        profile["roe_sum"] = _safe_float(profile["roe_sum"]) + _safe_float(row.get("roe_pct"))
    for profile in by_profile.values():
        closed = int(profile["closed"])
        profile["win_rate"] = round(int(profile["wins"]) / closed, 6) if closed else None
        profile["avg_roe_pct"] = round(_safe_float(profile.pop("roe_sum")) / closed, 6) if closed else None
    return {
        "mode": "jackpot_paper_bot_v1",
        "updated_at": _iso(),
        "paper_only": True,
        "live_ready": False,
        "no_order_side_effects": True,
        "live_order_count": state.live_order_count,
        "tested_order_count": state.tested_order_count,
        "universe": list(UNIVERSE),
        "timeframe": TIMEFRAME,
        "leverage": LEVERAGE,
        "leverage_profiles": list(LEVERAGE_PROFILES),
        "paper_margin_usd": PAPER_MARGIN_USD,
        "tp_roe_pct": TP_ROE_PCT,
        "runner_tp_roe_pct": RUNNER_TP_ROE_PCT,
        "sl_roe_pct": SL_ROE_PCT,
        "time_exit_minutes": TIME_EXIT_MINUTES,
        "daily_max_entries": DAILY_MAX_ENTRIES,
        "open_position": state.open_position,
        "open_positions": state.open_positions,
        "total_entries": state.total_entries,
        "total_closed": state.total_closed,
        "wins": state.wins,
        "losses": state.losses,
        "win_rate": win_rate,
        "avg_roe_pct": avg_roe,
        "cum_pnl_usd": state.cum_pnl_usd,
        "close_reasons": by_reason,
        "profiles": by_profile,
        "last_event": state.last_event,
    }


def fetch_klines(exchange: Any, symbol: str, limit: int = HISTORY_BARS) -> list[list[float]]:
    return exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=limit)


def fetch_mid_or_last(exchange: Any, symbol: str, fallback: float) -> float:
    ticker = exchange.fetch_ticker(symbol)
    bid = ticker.get("bid")
    ask = ticker.get("ask")
    last = ticker.get("last")
    if bid and ask:
        return (float(bid) + float(ask)) / 2.0
    return float(last or fallback)


def init_exchange() -> Any:
    import ccxt

    return ccxt.bitget({"options": {"defaultType": "swap"}, "enableRateLimit": True})


def run_cycle(exchange: Any, state: JackpotState) -> dict[str, Any]:
    if state.open_position is not None and not state.open_positions:
        legacy_position = PaperPosition(**state.open_position)
        state.open_positions = {legacy_position.profile_id: asdict(legacy_position)}
        state.open_position = None

    features: dict[str, dict[str, np.ndarray]] = {}
    fetch_errors: dict[str, str] = {}
    for symbol in UNIVERSE:
        try:
            ind = compute_features(fetch_klines(exchange, symbol))
            if ind is not None:
                features[symbol] = ind
        except Exception as exc:  # pragma: no cover - network dependent
            fetch_errors[symbol] = str(exc)

    if state.open_positions:
        still_open: dict[str, dict[str, Any]] = {}
        closed: list[dict[str, Any]] = []
        for profile_id, raw_position in sorted(state.open_positions.items()):
            position = PaperPosition(**raw_position)
            ind = features.get(position.symbol)
            if ind is None:
                still_open[profile_id] = asdict(position)
                continue
            exit_info = evaluate_exit(position, ind)
            if exit_info is None:
                still_open[profile_id] = asdict(position)
                continue
            trade = close_position(state, position, exit_info)
            closed.append(trade)
            _append_jsonl(LOG_PATH, {"event": "CLOSE", "trade": trade})
        state.open_positions = still_open
        state.open_position = next(iter(still_open.values()), None)
        if closed:
            state.last_event = "CLOSE " + ",".join(f"{row['profile_id']}:{row['reason']}" for row in closed)
        state.last_check_at = _iso()
        save_state(state)
        report = summarize_state(state)
        report["fetch_errors"] = fetch_errors
        _write_json(REPORT_PATH, report)
        return report

    day_key = _daily_key()
    entries_today = int(state.daily_entry_count.get(day_key, 0))
    signals: list[dict[str, Any]] = []
    if entries_today < DAILY_MAX_ENTRIES:
        btc = features.get("BTC/USDT:USDT")
        for symbol, ind in features.items():
            signal = build_entry_signal(symbol, ind, btc_features=btc)
            if signal:
                signals.append(signal)
    best = choose_best_signal(signals)
    if best is not None:
        fill = fetch_mid_or_last(exchange, str(best["symbol"]), _safe_float(best["bar_close"]))
        positions = {
            str(profile["profile_id"]): asdict(build_position(best, fill, profile=profile))
            for profile in LEVERAGE_PROFILES
        }
        state.open_positions = positions
        state.open_position = positions.get(str(DEFAULT_PROFILE["profile_id"])) or next(iter(positions.values()), None)
        state.total_entries += 1
        state.daily_entry_count[day_key] = entries_today + 1
        state.last_event = f"OPEN {best['symbol']} {best['side']} profiles={len(positions)} score={_safe_float(best['score']):.2f}"
        _append_jsonl(LOG_PATH, {"event": "OPEN", "positions": positions})
    else:
        state.last_event = "NO_ENTRY"

    state.last_check_at = _iso()
    save_state(state)
    report = summarize_state(state)
    report["signals_seen"] = signals
    report["fetch_errors"] = fetch_errors
    _write_json(REPORT_PATH, report)
    return report


RUN = True


def _stop(*_: object) -> None:
    global RUN
    RUN = False


def main() -> int:
    global STATE_PATH, REPORT_PATH, LOG_PATH

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run one paper-only cycle and exit.")
    parser.add_argument("--state-path", default=str(STATE_PATH))
    parser.add_argument("--report-path", default=str(REPORT_PATH))
    parser.add_argument("--log-path", default=str(LOG_PATH))
    parser.add_argument("--poll-sec", type=int, default=int(os.environ.get("JACKPOT_PAPER_POLL_SEC", POLL_SEC)))
    args = parser.parse_args()

    STATE_PATH = Path(args.state_path)
    REPORT_PATH = Path(args.report_path)
    LOG_PATH = Path(args.log_path)

    signal_mod.signal(signal_mod.SIGINT, _stop)
    signal_mod.signal(signal_mod.SIGTERM, _stop)

    exchange = init_exchange()
    state = load_state(STATE_PATH)
    _append_jsonl(LOG_PATH, {"event": "START", "paper_only": True, "no_order_side_effects": True})
    if args.once:
        report = run_cycle(exchange, state)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0

    while RUN:
        report = run_cycle(exchange, state)
        print(json.dumps({"updated_at": report["updated_at"], "last_event": report["last_event"]}, ensure_ascii=False))
        time.sleep(max(5, args.poll_sec))
        state = load_state(STATE_PATH)
    _append_jsonl(LOG_PATH, {"event": "STOP"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
