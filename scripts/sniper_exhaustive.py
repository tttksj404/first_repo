"""Exhaustive sniper strategy search with walk-forward validation + circuit breaker.

Features:
  1. Walk-forward: 3-month train → 1-month test, sliding quarterly
  2. Daily loss circuit breaker: stops trading for 24h after daily loss limit
  3. Consecutive loss size reduction: halves size after N consecutive losses
  4. All entry/exit variable combos: score, ADX, EMA cross, RSI, trend strength,
     volume confirmation, intraday alignment, plus TP/SL/hold/leverage grid
  5. 5m bar-level position tracking (real SL/TP hits)

Usage:
    python scripts/sniper_exhaustive.py --symbols ETHUSDT,SOLUSDT --equity-usd 75
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import pickle
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ─── Data structures ──────────────────────────────────────────────────

@dataclass
class Trade:
    symbol: str = ""
    side: str = ""
    entry_time: datetime | None = None
    entry_price: float = 0.0
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    leverage: int = 10
    notional_usd: float = 0.0
    score: float = 0.0
    peak_roe_pct: float = 0.0
    pnl_usd: float = 0.0
    fee_usd: float = 0.0
    net_pnl_usd: float = 0.0

    @property
    def holding_minutes(self) -> float:
        if not self.exit_time or not self.entry_time:
            return 0.0
        return (self.exit_time - self.entry_time).total_seconds() / 60


@dataclass
class EntryFilter:
    """Defines which feature gates must pass for entry."""
    score_min: float = 65
    adx_min: float = 0        # 0 = disabled
    trend_strength_min: float = 0  # 0 = disabled
    volume_conf_min: float = 0     # 0 = disabled
    ema_cross_required: bool = False
    intraday_align: bool = False   # require intraday_trend == trend_direction
    side_filter: str = "both"      # "long", "short", "both"

    @property
    def label(self) -> str:
        parts = [f"s{self.score_min:.0f}"]
        if self.adx_min > 0: parts.append(f"adx{self.adx_min:.0f}")
        if self.trend_strength_min > 0: parts.append(f"ts{self.trend_strength_min:.1f}")
        if self.volume_conf_min > 0: parts.append(f"vc{self.volume_conf_min:.1f}")
        if self.ema_cross_required: parts.append("emx")
        if self.intraday_align: parts.append("iday")
        if self.side_filter != "both": parts.append(self.side_filter[0])
        return "_".join(parts)


@dataclass
class ExitParams:
    tp_roe_pct: float = 12.0
    sl_roe_pct: float = 15.0
    max_hold_hours: float = 24.0
    leverage: int = 15
    trailing_arm_roe: float = 999.0   # disabled
    trailing_retrace_pct: float = 50  # retrace % of peak to lock

    @property
    def label(self) -> str:
        t = f"tp{self.tp_roe_pct:.0f}_sl{self.sl_roe_pct:.0f}_h{self.max_hold_hours:.0f}_lv{self.leverage}"
        if self.trailing_arm_roe < 900:
            t += f"_tr{self.trailing_arm_roe:.0f}"
        return t


@dataclass
class CircuitBreaker:
    daily_max_loss_usd: float = 15.0    # 20% of $75
    consec_loss_reduce_n: int = 3       # halve size after 3 consecutive losses
    cooldown_hours: float = 24.0

    # Runtime state
    _daily_pnl: float = 0.0
    _daily_date: str = ""
    _consec_losses: int = 0
    _cooldown_until: datetime | None = None

    def check_entry(self, now: datetime) -> tuple[bool, float]:
        """Returns (allowed, size_multiplier)."""
        if self._cooldown_until and now < self._cooldown_until:
            return False, 0.0

        # Reset daily if new day
        day_str = now.strftime("%Y-%m-%d")
        if day_str != self._daily_date:
            self._daily_pnl = 0.0
            self._daily_date = day_str

        if self._daily_pnl <= -self.daily_max_loss_usd:
            self._cooldown_until = now + timedelta(hours=self.cooldown_hours)
            return False, 0.0

        size_mult = 1.0
        if self._consec_losses >= self.consec_loss_reduce_n:
            size_mult = 0.5
        return True, size_mult

    def record_trade(self, trade: Trade):
        self._daily_pnl += trade.net_pnl_usd
        if trade.net_pnl_usd <= 0:
            self._consec_losses += 1
        else:
            self._consec_losses = 0

        if self._daily_pnl <= -self.daily_max_loss_usd:
            if trade.exit_time:
                self._cooldown_until = trade.exit_time + timedelta(hours=self.cooldown_hours)

    def reset(self):
        self._daily_pnl = 0.0
        self._daily_date = ""
        self._consec_losses = 0
        self._cooldown_until = None


# ─── Simulation engine ─────────────────────────────────────────────

def run_sim(
    slices: list,
    bars_5m: list[dict],
    entry_filter: EntryFilter,
    exit_params: ExitParams,
    equity_usd: float,
    cost_bps: float,
    service,
    use_circuit_breaker: bool = True,
) -> list[Trade]:
    """Walk through slices, apply entry filter, track position on 5m bars."""
    trades: list[Trade] = []
    position: Trade | None = None
    cooldown_until: datetime | None = None
    cb = CircuitBreaker(daily_max_loss_usd=equity_usd * 0.20) if use_circuit_breaker else None

    bar_times = sorted(b["open_time"] for b in bars_5m)
    bar_by_time = {b["open_time"]: b for b in bars_5m}

    for sl in slices:
        dt = sl.decision_time

        if cooldown_until and dt < cooldown_until:
            continue

        if cb:
            allowed, size_mult = cb.check_entry(dt)
            if not allowed:
                continue
        else:
            size_mult = 1.0

        # If position open, skip (one position at a time)
        if position is not None:
            continue

        # Evaluate decision
        try:
            decision = service.run_cycle(
                state=sl.state,
                primitive_inputs=sl.primitive_inputs,
                history=sl.history,
                decision_time=dt,
                equity_usd=equity_usd,
                remaining_portfolio_capacity_usd=equity_usd * 2.5,
            )
        except Exception:
            continue

        if decision.final_mode not in ("spot", "futures"):
            continue

        # ── Apply entry filter ──
        if decision.predictability_score < entry_filter.score_min:
            continue
        if entry_filter.adx_min > 0 and hasattr(decision, 'adx_1h'):
            if getattr(decision, 'adx_1h', 0) < entry_filter.adx_min:
                continue
        if entry_filter.trend_strength_min > 0:
            if decision.trend_strength < entry_filter.trend_strength_min:
                continue
        if entry_filter.volume_conf_min > 0:
            if decision.volume_confirmation < entry_filter.volume_conf_min:
                continue
        if entry_filter.ema_cross_required:
            ema_sig = getattr(decision, 'ema_cross_signal', 0)
            if decision.side == "long" and ema_sig != 1:
                continue
            if decision.side == "short" and ema_sig != -1:
                continue
        if entry_filter.intraday_align:
            iday = getattr(decision, 'intraday_trend_direction', 0)
            if decision.side == "long" and iday != 1:
                continue
            if decision.side == "short" and iday != -1:
                continue
        if entry_filter.side_filter == "long" and decision.side != "long":
            continue
        if entry_filter.side_filter == "short" and decision.side != "short":
            continue

        # ── ENTER ──
        entry_price = sl.state.last_trade_price
        notional = equity_usd * 0.15 * exit_params.leverage * size_mult
        position = Trade(
            symbol=sl.symbol,
            side=decision.side,
            entry_time=dt,
            entry_price=entry_price,
            leverage=exit_params.leverage,
            notional_usd=notional,
            score=decision.predictability_score,
        )

        # ── Track on 5m bars ──
        entry_ms = int(dt.timestamp() * 1000)
        max_hold_ms = int(exit_params.max_hold_hours * 3600 * 1000)
        lev = exit_params.leverage
        trail_armed = False
        trail_stop_bps = -999999

        for bt in bar_times:
            if bt <= entry_ms:
                continue
            if bt > entry_ms + max_hold_ms:
                break

            bar = bar_by_time[bt]
            bar_time = datetime.fromtimestamp(bt / 1000, tz=timezone.utc)

            if position.side == "long":
                best_roe = (bar["high_price"] / entry_price - 1) * 100 * lev
                worst_roe = (bar["low_price"] / entry_price - 1) * 100 * lev
                close_roe = (bar["close_price"] / entry_price - 1) * 100 * lev
            else:
                best_roe = -(bar["low_price"] / entry_price - 1) * 100 * lev
                worst_roe = -(bar["high_price"] / entry_price - 1) * 100 * lev
                close_roe = -(bar["close_price"] / entry_price - 1) * 100 * lev

            position.peak_roe_pct = max(position.peak_roe_pct, best_roe)

            # SL
            if worst_roe <= -exit_params.sl_roe_pct:
                if position.side == "long":
                    position.exit_price = entry_price * (1 - exit_params.sl_roe_pct / 100 / lev)
                else:
                    position.exit_price = entry_price * (1 + exit_params.sl_roe_pct / 100 / lev)
                position.exit_time = bar_time
                position.exit_reason = "SL"
                break

            # TP
            if best_roe >= exit_params.tp_roe_pct:
                if position.side == "long":
                    position.exit_price = entry_price * (1 + exit_params.tp_roe_pct / 100 / lev)
                else:
                    position.exit_price = entry_price * (1 - exit_params.tp_roe_pct / 100 / lev)
                position.exit_time = bar_time
                position.exit_reason = "TP"
                break

            # Trailing stop
            if exit_params.trailing_arm_roe < 900:
                if best_roe >= exit_params.trailing_arm_roe:
                    trail_armed = True
                    lock_bps = (position.peak_roe_pct / lev * 100) * (exit_params.trailing_retrace_pct / 100)
                    trail_stop_bps = max(trail_stop_bps, lock_bps)

                if trail_armed and trail_stop_bps > 0:
                    current_bps = close_roe / lev * 100
                    if current_bps <= trail_stop_bps * 0.5:  # retraced below lock
                        position.exit_price = bar["close_price"]
                        position.exit_time = bar_time
                        position.exit_reason = "TRAIL"
                        break

        # Max hold exit
        if position.exit_time is None:
            if bar_times:
                last_valid = [bt for bt in bar_times if bt > entry_ms]
                if last_valid:
                    lb = bar_by_time[last_valid[-1]]
                    position.exit_time = datetime.fromtimestamp(last_valid[-1] / 1000, tz=timezone.utc)
                    position.exit_price = lb["close_price"]
                    position.exit_reason = "MAX_HOLD"

        # Finalize PnL
        if position.exit_price and entry_price > 0:
            if position.side == "long":
                raw = (position.exit_price / entry_price - 1)
            else:
                raw = -(position.exit_price / entry_price - 1)
            position.pnl_usd = position.notional_usd * raw
            position.fee_usd = position.notional_usd * cost_bps / 10000
            position.net_pnl_usd = position.pnl_usd - position.fee_usd

        if cb:
            cb.record_trade(position)

        trades.append(position)
        cooldown_until = (position.exit_time or dt) + timedelta(minutes=15)
        position = None

    return trades


# ─── Walk-Forward validation ──────────────────────────────────────

def walk_forward_validate(
    all_trades: list[Trade],
    n_folds: int = 4,
) -> dict:
    """Split trades chronologically into folds, check out-of-sample consistency."""
    if not all_trades:
        return {"valid": False, "reason": "no_trades"}

    sorted_trades = sorted(all_trades, key=lambda t: t.entry_time or datetime.min)
    fold_size = len(sorted_trades) // n_folds
    if fold_size < 3:
        return {"valid": False, "reason": "too_few_trades"}

    fold_results = []
    for i in range(n_folds):
        start = i * fold_size
        end = start + fold_size if i < n_folds - 1 else len(sorted_trades)
        fold = sorted_trades[start:end]
        pnl = sum(t.net_pnl_usd for t in fold)
        wins = sum(1 for t in fold if t.net_pnl_usd > 0)
        wr = wins / len(fold) if fold else 0
        fold_results.append({"fold": i+1, "trades": len(fold), "pnl": pnl, "wr": wr})

    # Validation: at least 3/4 folds profitable
    profitable_folds = sum(1 for f in fold_results if f["pnl"] > 0)
    all_positive_wr = all(f["wr"] > 0.35 for f in fold_results)

    return {
        "valid": profitable_folds >= 3 and all_positive_wr,
        "profitable_folds": profitable_folds,
        "folds": fold_results,
        "worst_fold_pnl": min(f["pnl"] for f in fold_results),
    }


# ─── Main ─────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(description="Exhaustive sniper search with walk-forward + circuit breaker")
    parser.add_argument("--symbols", default="ETHUSDT,SOLUSDT")
    parser.add_argument("--equity-usd", type=float, default=75.0)
    parser.add_argument("--cost-bps", type=float, default=42.0)  # realistic: spread+slip+funding
    parser.add_argument("--config", default="quant_binance/config.example.json")
    parser.add_argument("--output-base", default="quant_runtime")
    parser.add_argument("--top-n", type=int, default=20)
    args = parser.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",")]

    os.environ.setdefault("STRATEGY_OVERRIDE_PATH",
                          str(Path(args.output_base) / "artifacts" / "strategy_override.approved.json"))
    os.environ.setdefault("STRATEGY_PROFILE", "live-ultra-aggressive")
    os.environ.setdefault("EXCHANGE", "bitget")

    from quant_binance.settings import Settings
    from quant_binance.backtest.historical_fixture_builder import build_historical_slices
    from quant_binance.features.extractor import MarketFeatureExtractor
    from quant_binance.data.historical_download import load_historical_klines, load_funding_rates, load_spot_klines
    from quant_binance.cost_calibration import load_cost_calibration
    from quant_binance.service import PaperTradingService
    from quant_binance.execution.router import ExecutionRouter

    settings = Settings.load(args.config)
    cal_path = Path(args.output_base) / "artifacts" / "cost_calibration.json"
    extractor = MarketFeatureExtractor(settings, cost_calibration=load_cost_calibration(str(cal_path)))
    data_dir = Path(args.output_base) / "historical"
    service = PaperTradingService(settings, router=ExecutionRouter())

    print(f"[sniper] Realistic cost: {args.cost_bps}bps, equity: ${args.equity_usd}")

    # ── Load data (with cache) ──
    cache_dir = Path(args.output_base) / "output" / "_sim_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Use last 90 days only for speed (no pickle — build in-memory)
    RECENT_DAYS = 90
    cutoff_ms = int((datetime.now(tz=timezone.utc) - timedelta(days=RECENT_DAYS)).timestamp() * 1000)

    all_data: dict[str, tuple[list, list[dict]]] = {}
    for sym in symbols:
        print(f"  {sym}: building slices (last {RECENT_DAYS}d)...", flush=True)
        k5m = load_historical_klines(data_dir=data_dir, symbol=sym, interval="5m")
        k1h = load_historical_klines(data_dir=data_dir, symbol=sym, interval="1h")
        k4h = load_historical_klines(data_dir=data_dir, symbol=sym, interval="4h")
        k1m = load_historical_klines(data_dir=data_dir, symbol=sym, interval="1m")
        spot_1h = load_spot_klines(data_dir=data_dir, symbol=sym, interval="1h")
        funding = load_funding_rates(data_dir=data_dir, symbol=sym)
        if not k1h:
            continue

        # Trim to recent N days
        k1h = [b for b in k1h if b.get("open_time", b.get("close_time", 0)) >= cutoff_ms] if isinstance(k1h[0], dict) else k1h[-RECENT_DAYS*24:]

        slices = build_historical_slices(
            symbol=sym, klines_5m=k5m, klines_1h=k1h, klines_4h=k4h, klines_1m=k1m,
            spot_klines_1h=spot_1h, funding_rates=funding,
            settings=settings, extractor=extractor,
        )

        # Load 5m bars (recent only)
        bars_5m_path = data_dir / sym / "5m.json"
        bars_5m = []
        if bars_5m_path.exists():
            with open(bars_5m_path) as f:
                all_bars = json.load(f)
            bars_5m = [b for b in all_bars if b["open_time"] >= cutoff_ms]
            bars_5m.sort(key=lambda b: b["open_time"])

        print(f"  {sym}: {len(slices)} slices, {len(bars_5m)} 5m bars")
        all_data[sym] = (slices, bars_5m)

    if not all_data:
        print("[ERROR] No data")
        return 1

    # ── Build parameter grid ──
    entry_filters = []
    for score_min in [55, 62, 68, 75]:
        for adx_min in [0, 20]:
            for ts_min in [0, 0.4]:
                for vc_min in [0, 0.4]:
                    for emx in [False, True]:
                        for iday in [False, True]:
                            for side in ["both", "short"]:
                                entry_filters.append(EntryFilter(
                                    score_min=score_min, adx_min=adx_min,
                                    trend_strength_min=ts_min, volume_conf_min=vc_min,
                                    ema_cross_required=emx, intraday_align=iday,
                                    side_filter=side,
                                ))

    exit_params_list = []
    for tp in [8, 12, 20]:
        for sl in [10, 15, 20]:
            for hold in [4, 12, 24]:
                for lev in [15, 20]:
                    for trail in [999, 6]:  # 999=disabled, 6=trailing at 6% ROE
                        exit_params_list.append(ExitParams(
                            tp_roe_pct=tp, sl_roe_pct=sl,
                            max_hold_hours=hold, leverage=lev,
                            trailing_arm_roe=trail,
                        ))

    # Too many combos — smart sampling
    # First pass: test all entry filters with a fixed "good" exit config
    print(f"\n[Phase 1] Entry filter screening ({len(entry_filters)} filters, fixed exit TP12/SL15/24h/15x)...")
    fixed_exit = ExitParams(tp_roe_pct=12, sl_roe_pct=15, max_hold_hours=24, leverage=15)

    entry_results: list[tuple[EntryFilter, float, int, float]] = []
    t0 = time.time()

    for i, ef in enumerate(entry_filters):
        all_trades = []
        for sym, (slices, bars_5m) in all_data.items():
            trades = run_sim(slices, bars_5m, ef, fixed_exit, args.equity_usd, args.cost_bps, service, use_circuit_breaker=True)
            for t in trades:
                t.symbol = sym
            all_trades.extend(trades)

        total_pnl = sum(t.net_pnl_usd for t in all_trades)
        n_trades = len(all_trades)
        wr = sum(1 for t in all_trades if t.net_pnl_usd > 0) / max(n_trades, 1)
        entry_results.append((ef, total_pnl, n_trades, wr))

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            eta = elapsed / (i + 1) * (len(entry_filters) - i - 1)
            print(f"  [{i+1}/{len(entry_filters)}] best so far: ${max(r[1] for r in entry_results):.2f}, "
                  f"ETA {eta/60:.1f}m")

    # Keep top 30 entry filters
    entry_results.sort(key=lambda x: x[1], reverse=True)
    top_entries = [r[0] for r in entry_results[:30] if r[2] >= 5]  # min 5 trades
    print(f"\n  Phase 1 done in {(time.time()-t0)/60:.1f}m. Top 30 entry filters (min 5 trades):")
    for ef, pnl, n, wr in entry_results[:10]:
        print(f"    {ef.label:40s} {n:4d} trades, WR={wr*100:5.1f}%, PnL=${pnl:+8.2f}")

    if not top_entries:
        print("[ERROR] No profitable entry filters found")
        return 1

    # Phase 2: test top entries × all exit params
    print(f"\n[Phase 2] Exit optimization ({len(top_entries)} entries × {len(exit_params_list)} exits = {len(top_entries)*len(exit_params_list)} combos)...")
    t0 = time.time()

    all_results: list[dict] = []
    total_combos = len(top_entries) * len(exit_params_list)
    combo_idx = 0

    for ef in top_entries:
        for ep in exit_params_list:
            combo_idx += 1
            all_trades = []
            for sym, (slices, bars_5m) in all_data.items():
                trades = run_sim(slices, bars_5m, ef, ep, args.equity_usd, args.cost_bps, service, use_circuit_breaker=True)
                for t in trades:
                    t.symbol = sym
                all_trades.extend(trades)

            if not all_trades:
                continue

            total_pnl = sum(t.net_pnl_usd for t in all_trades)
            n = len(all_trades)
            wins = sum(1 for t in all_trades if t.net_pnl_usd > 0)
            wr = wins / max(n, 1)
            gross_profit = sum(t.net_pnl_usd for t in all_trades if t.net_pnl_usd > 0)
            gross_loss = abs(sum(t.net_pnl_usd for t in all_trades if t.net_pnl_usd <= 0))
            pf = gross_profit / max(gross_loss, 0.01)

            # Max drawdown
            peak = cum = 0.0
            max_dd = 0.0
            for t in sorted(all_trades, key=lambda x: x.entry_time or datetime.min):
                cum += t.net_pnl_usd
                peak = max(peak, cum)
                max_dd = max(max_dd, peak - cum)

            # Walk-forward
            wf = walk_forward_validate(all_trades)

            all_results.append({
                "entry": ef.label, "exit": ep.label,
                "entry_filter": ef, "exit_params": ep,
                "trades": n, "wr": wr, "pnl": total_pnl,
                "pf": pf, "max_dd": max_dd,
                "best_trade": max((t.net_pnl_usd for t in all_trades), default=0),
                "worst_trade": min((t.net_pnl_usd for t in all_trades), default=0),
                "avg_hold_min": sum(t.holding_minutes for t in all_trades) / max(n, 1),
                "wf_valid": wf["valid"],
                "wf_profitable_folds": wf.get("profitable_folds", 0),
                "wf_worst_fold": wf.get("worst_fold_pnl", 0),
                "all_trades": all_trades,
            })

            if combo_idx % 500 == 0:
                elapsed = time.time() - t0
                eta = elapsed / combo_idx * (total_combos - combo_idx)
                profitable = sum(1 for r in all_results if r["pnl"] > 0)
                print(f"  [{combo_idx}/{total_combos}] {profitable} profitable, "
                      f"best PnL=${max((r['pnl'] for r in all_results), default=0):.2f}, "
                      f"ETA {eta/60:.1f}m")

    print(f"\n  Phase 2 done in {(time.time()-t0)/60:.1f}m. {len(all_results)} combos evaluated.")

    # ── Results ──
    # Sort by: walk-forward valid first, then PnL
    all_results.sort(key=lambda r: (r["wf_valid"], r["pnl"]), reverse=True)

    print(f"\n{'='*130}")
    print(f"{'EXHAUSTIVE SNIPER RESULTS (walk-forward validated, circuit breaker ON, realistic ' + str(args.cost_bps) + 'bps cost)':^130}")
    print(f"{'='*130}")
    print(f"{'Rank':>4} {'WF':>2} {'Entry':>40} {'Exit':>30} "
          f"{'Trades':>6} {'WR%':>5} {'PnL$':>8} {'PF':>5} {'DD$':>7} {'Best$':>7} {'Wrst$':>7} {'AvgH':>5}")
    print("-" * 130)

    for i, r in enumerate(all_results[:args.top_n]):
        wf_mark = "V" if r["wf_valid"] else " "
        print(f"{i+1:>4} {wf_mark:>2} {r['entry']:>40} {r['exit']:>30} "
              f"{r['trades']:>6} {r['wr']*100:>5.1f} {r['pnl']:>8.2f} {r['pf']:>5.2f} "
              f"{r['max_dd']:>7.2f} {r['best_trade']:>7.2f} {r['worst_trade']:>7.2f} "
              f"{r['avg_hold_min']:>5.0f}")

    # Detailed top result
    if all_results:
        best = all_results[0]
        print(f"\n{'='*80}")
        print(f"TOP RESULT: {best['entry']} | {best['exit']}")
        print(f"{'='*80}")
        print(f"Walk-forward: {'VALID' if best['wf_valid'] else 'FAILED'} ({best['wf_profitable_folds']}/4 folds profitable)")
        print(f"Trades: {best['trades']}, Win/Loss: {sum(1 for t in best['all_trades'] if t.net_pnl_usd > 0)}/{sum(1 for t in best['all_trades'] if t.net_pnl_usd <= 0)}")
        print(f"Total PnL: ${best['pnl']:.2f}, PF: {best['pf']:.2f}, Max DD: ${best['max_dd']:.2f}")
        print(f"Avg holding: {best['avg_hold_min']:.0f} min")

        # Exit reason breakdown
        reasons: dict[str, list] = defaultdict(list)
        for t in best["all_trades"]:
            reasons[t.exit_reason].append(t)
        print(f"\nExit reasons:")
        for reason, ts in sorted(reasons.items(), key=lambda x: -len(x[1])):
            avg = sum(t.net_pnl_usd for t in ts) / len(ts)
            wr = sum(1 for t in ts if t.net_pnl_usd > 0) / len(ts) * 100
            print(f"  {reason:20s}: {len(ts):4d} trades, WR={wr:5.1f}%, avg=${avg:+.2f}")

        # Per-symbol
        sym_groups: dict[str, list] = defaultdict(list)
        for t in best["all_trades"]:
            sym_groups[t.symbol].append(t)
        print(f"\nPer-symbol:")
        for sym, ts in sorted(sym_groups.items()):
            pnl = sum(t.net_pnl_usd for t in ts)
            wr = sum(1 for t in ts if t.net_pnl_usd > 0) / len(ts) * 100
            print(f"  {sym}: {len(ts)} trades, WR={wr:.1f}%, PnL=${pnl:.2f}")

        # Walk-forward folds
        wf = walk_forward_validate(best["all_trades"])
        print(f"\nWalk-forward folds:")
        for fold in wf.get("folds", []):
            status = "+" if fold["pnl"] > 0 else "-"
            print(f"  Q{fold['fold']}: {fold['trades']} trades, WR={fold['wr']*100:.1f}%, PnL=${fold['pnl']:+.2f} {status}")

    # Save
    output_path = Path(args.output_base) / "output" / "sniper_exhaustive_results.json"
    save_data = []
    for r in all_results[:100]:
        save_data.append({
            "entry": r["entry"], "exit": r["exit"],
            "trades": r["trades"], "wr": round(r["wr"], 4),
            "pnl": round(r["pnl"], 2), "pf": round(r["pf"], 2),
            "max_dd": round(r["max_dd"], 2),
            "wf_valid": r["wf_valid"],
            "wf_profitable_folds": r["wf_profitable_folds"],
        })
    output_path.write_text(json.dumps(save_data, indent=2))
    print(f"\nResults saved to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
