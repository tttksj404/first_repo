#!/usr/bin/env python3
"""Phase 14: Faithful production-gate simulator (path C).

Approximate the rotation_30x_candidate production gates from 1h OHLCV:
  - trend_strength      ≈ ADX/100 (clamped)
  - volume_confirmation ≈ (vol_r - 1) / 2, clamped to [0,1]
  - liquidity_score     ≈ 0.5 hardcoded (1h memes/majors all liquid)
  - edge_to_cost_mult   ≈ expected_move_bps / round_trip_cost_bps
  - predictability_sc   ≈ composite (RSI extremity + MACD cross strength + ADX) → 0..100
  - net_expected_edge   ≈ gross_edge_bps - cost_bps

Then apply tier classification (strong / medium / weak) per production
`is_major_strong_futures_decision` / `is_major_medium_futures_decision`.

Apply high_conviction sizing:
  - strong  → margin_pct = 1.0
  - medium  → margin_pct = 0.35
  - else    → no entry

Apply recent-confirmation gate: prev N bars must include ≥M qualifying long signals.

Apply production exit rules (faithful):
  - Proactive partial TP ladder: ROE [5, 18, 35, 60]% with 0.75 fraction each
  - Profit protection: arm at 18% ROE; if retrace 5% ROE from peak after arm → exit at peak-5%
  - Hard SL at -10% ROE
  - Max hold 48h
  - Long-only (turnaround mode)

Test multiple gate-strength settings to find the sweet spot:
  - strict (production thresholds)
  - normal (60% of production)
  - loose (30% of production)
  - very_loose (10% of production)
"""
from __future__ import annotations

import json, sys, time
from dataclasses import dataclass, field, replace
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import (  # type: ignore
    load_1h, compute_indicators, EQUITY, COST_RT, FUNDING_8H, Trade,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase14_production_sim.json"


# ====================================================================
# Feature engineering — approximate production scores from OHLCV
# ====================================================================

def compute_production_features(ind: dict) -> dict:
    """Add production-style features to indicator dict."""
    n = len(ind["close"])
    close = ind["close"]
    atr = ind["atr"]
    adx = ind["adx"]
    rsi = ind["rsi"]
    macd = ind["macd"]
    macd_sig = ind["macd_sig"]
    vol_r = ind["vol_r"]
    ema20 = ind["ema20"]
    ema50 = ind["ema50"]

    # trend_strength ∈ [0,1]: combine ADX (range strength) + EMA alignment
    trend_strength = np.zeros(n)
    for i in range(n):
        adx_score = min(adx[i] / 50.0, 1.0)  # ADX 50 → 1.0
        ema_align = 0.5 + 0.5 * np.sign(ema20[i] - ema50[i]) * min(abs(ema20[i] - ema50[i]) / max(atr[i], 1e-9), 1.0) if atr[i] > 0 else 0.5
        trend_strength[i] = (adx_score * 0.6 + ema_align * 0.4)

    # volume_confirmation ∈ [0,1]: vol_r (current/MA20)
    vol_conf = np.clip((vol_r - 1.0) / 2.0, 0.0, 1.0)

    # liquidity_score ∈ [0,1]: hardcode 0.5 for memes/majors (no orderbook on 1h)
    liquidity = np.full(n, 0.5)

    # edge_to_cost_multiple: expected move bps / round_trip_cost_bps
    # Expected 1h move ≈ atr (in price). bps = atr/close * 10000
    cost_bps = COST_RT * 10000.0  # 12 bps
    expected_move_bps = np.where(close > 0, atr / close * 10000.0, 0.0)
    edge_to_cost = np.where(cost_bps > 0, expected_move_bps / cost_bps, 0.0)

    # net_expected_edge_bps = gross - cost
    net_edge_bps = expected_move_bps - cost_bps

    # predictability_score 0..100: composite
    pred_score = np.zeros(n)
    for i in range(n):
        # RSI extremity bonus (oversold=long bias, overbought=short bias)
        rsi_extremity = max(0, 30 - rsi[i]) + max(0, rsi[i] - 70)  # 0~30
        # MACD cross strength
        macd_cross_norm = 0.0
        if atr[i] > 0:
            macd_cross_norm = abs(macd[i] - macd_sig[i]) / atr[i] * 10  # rough scale
        macd_cross_norm = min(macd_cross_norm, 30)
        # ADX
        adx_norm = min(adx[i] / 2.0, 25)  # ADX 50 → 25
        # Volume bonus
        vol_bonus = min(vol_conf[i] * 15, 15)
        pred_score[i] = rsi_extremity + macd_cross_norm + adx_norm + vol_bonus

    ind["trend_strength"] = trend_strength
    ind["volume_confirmation"] = vol_conf
    ind["liquidity_score"] = liquidity
    ind["edge_to_cost_multiple"] = edge_to_cost
    ind["net_edge_bps"] = net_edge_bps
    ind["predictability_score"] = pred_score
    return ind


# ====================================================================
# Production-faithful tier classification
# ====================================================================

@dataclass
class GateConfig:
    """Production gate thresholds (from strategy_override.rotation_30x_candidate.json)."""
    name: str = "strict"
    # Strong tier
    strong_pred_score_min: float = 73.0  # futures_score_min(55) + strong_score_buffer(18)
    strong_trend_min: float = 0.64
    strong_vol_conf_min: float = 0.55
    strong_liq_min: float = 0.30
    strong_edge_to_cost_min: float = 1.20
    strong_net_edge_bps_min: float = 8.0
    # Medium tier (pyramid)
    medium_pred_score_min: float = 60.0
    medium_trend_min: float = 0.45
    medium_vol_conf_min: float = 0.35
    medium_liq_min: float = 0.20
    medium_edge_to_cost_min: float = 1.05
    medium_net_edge_bps_min: float = 5.0
    # Recent confirmation gate (within last N bars)
    recent_lookback_bars: int = 2
    recent_min_confirmations: int = 2
    recent_min_trend: float = 0.50
    recent_min_vol_conf: float = 0.40
    recent_min_liq: float = 0.30
    recent_min_edge_to_cost: float = 1.15

    def relax(self, factor: float) -> "GateConfig":
        """Return a relaxed copy. factor=1.0 strict, 0.6 normal, 0.3 loose, 0.1 very_loose."""
        if factor >= 0.99:
            return replace(self)
        return replace(
            self,
            name=self.name,
            strong_pred_score_min=self.strong_pred_score_min * factor,
            strong_trend_min=self.strong_trend_min * factor,
            strong_vol_conf_min=self.strong_vol_conf_min * factor,
            strong_liq_min=self.strong_liq_min * factor,
            strong_edge_to_cost_min=1.0 + (self.strong_edge_to_cost_min - 1.0) * factor,
            strong_net_edge_bps_min=self.strong_net_edge_bps_min * factor,
            medium_pred_score_min=self.medium_pred_score_min * factor,
            medium_trend_min=self.medium_trend_min * factor,
            medium_vol_conf_min=self.medium_vol_conf_min * factor,
            medium_liq_min=self.medium_liq_min * factor,
            medium_edge_to_cost_min=1.0 + (self.medium_edge_to_cost_min - 1.0) * factor,
            medium_net_edge_bps_min=self.medium_net_edge_bps_min * factor,
            recent_min_confirmations=max(1, int(round(self.recent_min_confirmations * factor))),
            recent_min_trend=self.recent_min_trend * factor,
            recent_min_vol_conf=self.recent_min_vol_conf * factor,
            recent_min_liq=self.recent_min_liq * factor,
            recent_min_edge_to_cost=1.0 + (self.recent_min_edge_to_cost - 1.0) * factor,
        )


def classify_tier(ind: dict, i: int, gc: GateConfig) -> str:
    """Return 'strong', 'medium', or 'none'."""
    pred = ind["predictability_score"][i]
    trend = ind["trend_strength"][i]
    vc = ind["volume_confirmation"][i]
    liq = ind["liquidity_score"][i]
    e2c = ind["edge_to_cost_multiple"][i]
    nee = ind["net_edge_bps"][i]
    # Strong
    if (pred >= gc.strong_pred_score_min
        and trend >= gc.strong_trend_min
        and vc >= gc.strong_vol_conf_min
        and liq >= gc.strong_liq_min
        and e2c >= gc.strong_edge_to_cost_min
        and nee >= gc.strong_net_edge_bps_min):
        return "strong"
    # Medium
    if (pred >= gc.medium_pred_score_min
        and trend >= gc.medium_trend_min
        and vc >= gc.medium_vol_conf_min
        and liq >= gc.medium_liq_min
        and e2c >= gc.medium_edge_to_cost_min
        and nee >= gc.medium_net_edge_bps_min):
        return "medium"
    return "none"


def long_signal(ind: dict, i: int) -> bool:
    """A bar shows a long bias signal: RSI<35 + MACD>sig + price up vs prev close."""
    if i < 1:
        return False
    return (ind["rsi"][i] <= 35
            and ind["macd"][i] > ind["macd_sig"][i]
            and ind["close"][i] > ind["close"][i-1])


def recent_confirmation_passes(ind: dict, i: int, gc: GateConfig) -> bool:
    """Within last gc.recent_lookback_bars+1 bars, count qualifying long signals."""
    count = 0
    for k in range(max(0, i - gc.recent_lookback_bars), i + 1):
        if not long_signal(ind, k):
            continue
        if (ind["trend_strength"][k] >= gc.recent_min_trend
            and ind["volume_confirmation"][k] >= gc.recent_min_vol_conf
            and ind["liquidity_score"][k] >= gc.recent_min_liq
            and ind["edge_to_cost_multiple"][k] >= gc.recent_min_edge_to_cost):
            count += 1
    return count >= gc.recent_min_confirmations


# ====================================================================
# Production-faithful exit logic — proactive TP ladder + profit protection
# ====================================================================

@dataclass
class ExitConfig:
    """Production exit ladder."""
    tp_ladder_roe: tuple = (5.0, 18.0, 35.0, 60.0)
    tp_ladder_fraction: float = 0.75  # 75% closed at each rung
    profit_protect_arm_roe: float = 18.0
    profit_protect_retrace_roe: float = 5.0
    sl_roe: float = -10.0
    abort_roe: float = -16.0
    max_hold_h: int = 48
    long_only: bool = True
    cooldown_bars: int = 2  # post-trade


def simulate_trade_exit(ind: dict, entry_idx: int, side: int, lev: float,
                        margin: float, ec: ExitConfig, n: int) -> tuple[float, int, str]:
    """Simulate exit using TP ladder + profit protection. Returns (final_pnl_roe_avg, exit_idx, exit_reason).

    final_pnl_roe_avg = weighted-avg ROE on the position (since partial TPs reduce size).
    """
    entry_px = ind["close"][entry_idx]
    if entry_px <= 0:
        return 0.0, entry_idx + 1, "INVALID_ENTRY"
    end_idx = min(entry_idx + ec.max_hold_h, n - 1)
    remaining_size = 1.0  # fraction of position still open
    realized_roe = 0.0  # weighted by size already exited
    peak_roe = 0.0
    armed = False
    next_rung = 0  # which TP rung hits next
    for k in range(entry_idx + 1, end_idx + 1):
        hi = ind["high"][k]; lo = ind["low"][k]
        # Compute potential ROE at high/low
        if side == 1:
            roe_hi = (hi / entry_px - 1) * lev * 100
            roe_lo = (lo / entry_px - 1) * lev * 100
        else:
            roe_hi = -(lo / entry_px - 1) * lev * 100
            roe_lo = -(hi / entry_px - 1) * lev * 100

        # SL check first (worst-case path)
        if roe_lo <= ec.sl_roe:
            realized_roe += remaining_size * ec.sl_roe
            return realized_roe, k, "SL"

        # TP ladder hits
        while next_rung < len(ec.tp_ladder_roe) and roe_hi >= ec.tp_ladder_roe[next_rung]:
            tp_roe = ec.tp_ladder_roe[next_rung]
            chunk = remaining_size * ec.tp_ladder_fraction
            realized_roe += chunk * tp_roe
            remaining_size -= chunk
            next_rung += 1
            if remaining_size < 0.01:
                return realized_roe, k, f"TP{next_rung}_FULL"

        # Profit protection arm
        if not armed and roe_hi >= ec.profit_protect_arm_roe:
            armed = True
        peak_roe = max(peak_roe, roe_hi)
        # Retrace exit (after armed)
        if armed and roe_lo <= peak_roe - ec.profit_protect_retrace_roe:
            exit_roe = max(peak_roe - ec.profit_protect_retrace_roe, 0.0)
            realized_roe += remaining_size * exit_roe
            return realized_roe, k, "PROFIT_PROTECT"

    # Hold timeout
    final_close = ind["close"][end_idx]
    if side == 1:
        final_roe = (final_close / entry_px - 1) * lev * 100
    else:
        final_roe = -(final_close / entry_px - 1) * lev * 100
    realized_roe += remaining_size * final_roe
    return realized_roe, end_idx, "HOLD_TIMEOUT"


# ====================================================================
# Backtest
# ====================================================================

def production_backtest(priority: list[str], cache: dict, gc: GateConfig,
                         ec: ExitConfig, lev: float = 30.0,
                         hc_strong_margin_pct: float = 1.0,
                         hc_medium_margin_pct: float = 0.35,
                         idx_start: int = 200, idx_end: int | None = None,
                         major_loss_cooldown_h: int = 24,
                         major_general_cooldown_h: int = 12) -> tuple[list[Trade], dict]:
    valid = [s for s in priority if s in cache]
    if not valid:
        return [], {"strong_count": 0, "medium_count": 0, "long_signal_count": 0}
    n = min(len(cache[s]["close"]) for s in valid)
    idx_end = min(idx_end or n, n - ec.max_hold_h - 2)
    trades = []
    diag = {"strong_count": 0, "medium_count": 0, "long_signal_count": 0,
            "tier_blocked_no_recent_conf": 0, "fired_strong": 0, "fired_medium": 0}
    last_loss_exit_h = -1e9
    last_exit_h = -1e9
    i = max(idx_start, 200)
    while i < idx_end:
        # Cooldowns
        if i - last_loss_exit_h < major_loss_cooldown_h:
            i += 1; continue
        if i - last_exit_h < major_general_cooldown_h:
            i += 1; continue
        # Find first symbol with long_signal + tier
        chosen = None; chosen_tier = None; chosen_ind = None
        for s in valid:
            ind = cache[s]
            if not long_signal(ind, i):
                continue
            diag["long_signal_count"] += 1
            tier = classify_tier(ind, i, gc)
            if tier == "none":
                continue
            if not recent_confirmation_passes(ind, i, gc):
                diag["tier_blocked_no_recent_conf"] += 1
                continue
            chosen = s; chosen_tier = tier; chosen_ind = ind
            if tier == "strong":
                diag["strong_count"] += 1
            else:
                diag["medium_count"] += 1
            break
        if chosen is None:
            i += 1; continue
        # High_conviction sizing
        if chosen_tier == "strong":
            margin_pct = hc_strong_margin_pct
            diag["fired_strong"] += 1
        else:  # medium
            margin_pct = hc_medium_margin_pct
            diag["fired_medium"] += 1
        margin = EQUITY * margin_pct
        notional = margin * lev
        fee = notional * COST_RT
        # Simulate exit
        realized_roe, exit_idx, exit_reason = simulate_trade_exit(
            chosen_ind, i, side=1, lev=lev, margin=margin, ec=ec, n=n
        )
        hold_h = max(1, exit_idx - i)
        funding = notional * FUNDING_8H * (hold_h // 8)
        pnl = margin * (realized_roe / 100.0) - fee - funding
        trades.append(Trade(chosen, 1, i, exit_idx, hold_h, pnl, realized_roe))
        # Cooldowns
        if pnl < 0:
            last_loss_exit_h = exit_idx
        last_exit_h = exit_idx
        i = exit_idx + ec.cooldown_bars
    return trades, diag


def aggregate_with_dist(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0}
    roes = np.array([t.roe_pct for t in trades])
    pnls = np.array([t.pnl_usd for t in trades])
    wins = roes > 0
    losses = roes < 0
    return {
        "n": len(trades),
        "wr": float(np.mean(wins)),
        "avg_win_roe": float(np.mean(roes[wins])) if wins.any() else 0,
        "avg_loss_roe": float(np.mean(roes[losses])) if losses.any() else 0,
        "ev_pnl": float(np.mean(pnls)),
        "total_pnl": float(np.sum(pnls)),
        "max_win_roe": float(np.max(roes)),
        "max_win_pnl": float(np.max(pnls)),
        "best3_pnl": float(np.sort(pnls)[-3:].sum()) if len(pnls) >= 3 else float(np.sum(pnls)),
        "p_win_50": float(np.mean(roes >= 50)),
        "p_win_100": float(np.mean(roes >= 100)),
        "p_win_200": float(np.mean(roes >= 200)),
        "p_win_500": float(np.mean(roes >= 500)),
        "first_5_pnl": float(np.sum(pnls[:5])) if len(pnls) >= 5 else float(np.sum(pnls)),
        "first_10_pnl": float(np.sum(pnls[:10])) if len(pnls) >= 10 else float(np.sum(pnls)),
        "max_dd": float(_max_dd(pnls)),
    }


def _max_dd(pnls: np.ndarray) -> float:
    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq) if len(eq) else np.array([0.0])
    dd = peak - eq
    return float(np.max(dd)) if len(dd) else 0.0


# ====================================================================
# Main
# ====================================================================

def main():
    t0 = time.time()
    syms = ["PEPEUSDT", "DOGEUSDT", "WIFUSDT", "ETHUSDT", "SOLUSDT", "BTCUSDT"]
    cache = {}
    for s in syms:
        arr = load_1h(s)
        if arr is None: continue
        ind = compute_indicators(arr)
        cache[s] = compute_production_features(ind)
    n_bars = min(len(v["close"]) for v in cache.values())
    print(f"[load] {len(cache)} syms × {n_bars} bars  ({time.time()-t0:.1f}s)")

    universes = {
        "memes": ["PEPEUSDT", "WIFUSDT", "DOGEUSDT"],
        "memes_first": ["PEPEUSDT", "WIFUSDT", "DOGEUSDT", "SOLUSDT"],
        "rotation_orig": ["PEPEUSDT", "DOGEUSDT", "ETHUSDT", "SOLUSDT"],
        "PEPE_only": ["PEPEUSDT"],
    }

    base_gate = GateConfig(name="strict")
    gate_strengths = {
        "strict_100pct": base_gate.relax(1.00),
        "normal_60pct": replace(base_gate.relax(0.60), name="normal"),
        "loose_30pct": replace(base_gate.relax(0.30), name="loose"),
        "very_loose_10pct": replace(base_gate.relax(0.10), name="very_loose"),
    }

    base_exit = ExitConfig()
    exit_variants = {
        "ladder_protect": base_exit,
        "single_tp30": replace(base_exit, tp_ladder_roe=(30.0, 30.0, 30.0, 30.0), tp_ladder_fraction=1.0, profit_protect_arm_roe=999),
        "single_tp100": replace(base_exit, tp_ladder_roe=(100.0, 100.0, 100.0, 100.0), tp_ladder_fraction=1.0, profit_protect_arm_roe=999),
        "single_tp200": replace(base_exit, tp_ladder_roe=(200.0, 200.0, 200.0, 200.0), tp_ladder_fraction=1.0, profit_protect_arm_roe=999),
        "ladder_only": replace(base_exit, profit_protect_arm_roe=999),
    }

    rows = []
    print(f"\n{'gate':<18s} {'exit':<18s} {'univ':<14s} {'N':>3s} {'fS':>3s} {'fM':>3s} {'WR%':>5s} {'EV$':>7s} {'PnL$':>8s} {'maxR%':>7s} {'p100':>6s} {'p200':>6s} {'p500':>6s} {'B3$':>7s}")
    for univ_name, priority in universes.items():
        if not all(s in cache for s in priority): continue
        for gate_name, gc in gate_strengths.items():
            for exit_name, ec in exit_variants.items():
                trades, diag = production_backtest(priority, cache, gc, ec, lev=30.0)
                agg = aggregate_with_dist(trades)
                if agg["n"] == 0:
                    rows.append({"gate": gate_name, "exit": exit_name, "univ": univ_name,
                                 "n": 0, "diag": diag})
                    print(f"{gate_name:<18s} {exit_name:<18s} {univ_name:<14s} {0:>3d} {diag['fired_strong']:>3d} {diag['fired_medium']:>3d}   -    -      -      -      -      -      -")
                    continue
                row = {"gate": gate_name, "exit": exit_name, "univ": univ_name, **agg, "diag": diag}
                rows.append(row)
                print(f"{gate_name:<18s} {exit_name:<18s} {univ_name:<14s} "
                      f"{agg['n']:>3d} {diag['fired_strong']:>3d} {diag['fired_medium']:>3d} "
                      f"{agg['wr']*100:>4.1f} ${agg['ev_pnl']:>+5.2f} ${agg['total_pnl']:>+6.2f} "
                      f"{agg['max_win_roe']:>6.0f} {agg['p_win_100']*100:>5.1f}% "
                      f"{agg['p_win_200']*100:>5.1f}% {agg['p_win_500']*100:>5.1f}% "
                      f"${agg['best3_pnl']:>+5.2f}")

    OUT.write_text(json.dumps(rows, indent=2, default=str))
    print(f"\n[done] {len(rows)} configs, {time.time()-t0:.1f}s, saved: {OUT}")

    # ===== Top rankings =====
    fired = [r for r in rows if r.get("n", 0) >= 3]
    if fired:
        print(f"\n=== TOP-10 by EV$ per trade (n≥3) ===")
        fired.sort(key=lambda r: -r["ev_pnl"])
        for i, r in enumerate(fired[:10], 1):
            print(f"  {i:>2d} {r['gate']:<18s} {r['exit']:<18s} {r['univ']:<14s} N={r['n']:>2d} "
                  f"WR={r['wr']*100:>4.1f}% EV=${r['ev_pnl']:>+5.2f} PnL=${r['total_pnl']:>+6.2f} "
                  f"maxR={r['max_win_roe']:>5.0f}% B3=${r['best3_pnl']:>+5.2f}")

        print(f"\n=== TOP-10 by best_3_pnl (한탕 잠재력) ===")
        fired.sort(key=lambda r: -r.get("best3_pnl", 0))
        for i, r in enumerate(fired[:10], 1):
            print(f"  {i:>2d} {r['gate']:<18s} {r['exit']:<18s} {r['univ']:<14s} N={r['n']:>2d} "
                  f"WR={r['wr']*100:>4.1f}% maxR={r['max_win_roe']:>5.0f}% "
                  f"p100={r['p_win_100']*100:>4.1f}% p200={r['p_win_200']*100:>4.1f}% "
                  f"B3=${r['best3_pnl']:>+5.2f} PnL=${r['total_pnl']:>+6.2f}")

        print(f"\n=== TOP-10 by p_win_200 (3배+ ROE hit 확률, n≥5) ===")
        fired5 = [r for r in fired if r["n"] >= 5]
        fired5.sort(key=lambda r: -r["p_win_200"])
        for i, r in enumerate(fired5[:10], 1):
            print(f"  {i:>2d} {r['gate']:<18s} {r['exit']:<18s} {r['univ']:<14s} N={r['n']:>2d} "
                  f"p100={r['p_win_100']*100:>4.1f}% p200={r['p_win_200']*100:>4.1f}% "
                  f"p500={r['p_win_500']*100:>4.1f}% maxR={r['max_win_roe']:>5.0f}% PnL=${r['total_pnl']:>+6.2f}")


if __name__ == "__main__":
    main()
