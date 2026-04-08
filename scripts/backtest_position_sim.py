"""Position-management backtest — simulates actual SL/TP/holding with 5m bars.

Unlike batch_backtest which evaluates each slice independently,
this tracks open positions bar-by-bar using 5m data for precise
SL/TP hit detection between decision points.

Usage:
    python scripts/backtest_position_sim.py \
        --symbols ETHUSDT,SOLUSDT \
        --score-min 55 60 65 68 72 78 \
        --tp-roe 5 8 10 15 \
        --sl-roe 8 12 15 20 \
        --max-hold-hours 4 8 12 24 48 \
        --leverage 10 15 20 \
        --equity-usd 75 \
        --cost-bps 20
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@dataclass
class Trade:
    symbol: str
    side: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    leverage: int = 10
    notional_usd: float = 0.0
    score: float = 0.0
    peak_roe_pct: float = 0.0
    worst_roe_pct: float = 0.0
    pnl_usd: float = 0.0
    fee_usd: float = 0.0
    net_pnl_usd: float = 0.0

    @property
    def holding_minutes(self) -> float:
        if not self.exit_time:
            return 0.0
        return (self.exit_time - self.entry_time).total_seconds() / 60

    @property
    def roe_pct(self) -> float:
        if not self.exit_price or self.entry_price <= 0:
            return 0.0
        raw = (self.exit_price / self.entry_price - 1) * 100
        return raw * self.leverage if self.side == "long" else -raw * self.leverage


@dataclass
class SimConfig:
    score_min: float = 65
    tp_roe_pct: float = 10.0
    sl_roe_pct: float = 15.0
    max_hold_hours: float = 24.0
    leverage: int = 15
    equity_usd: float = 75.0
    cost_bps: float = 20.0
    equity_risk_frac: float = 0.15
    trailing_stop_arm_roe: float = 999.0  # disabled by default
    trailing_stop_retrace_roe: float = 3.0

    @property
    def label(self) -> str:
        return f"s{self.score_min}_tp{self.tp_roe_pct}_sl{self.sl_roe_pct}_h{self.max_hold_hours}_lv{self.leverage}"


@dataclass
class SimResult:
    config: SimConfig
    trades: list[Trade]

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    @property
    def win_count(self) -> int:
        return sum(1 for t in self.trades if t.net_pnl_usd > 0)

    @property
    def loss_count(self) -> int:
        return sum(1 for t in self.trades if t.net_pnl_usd <= 0)

    @property
    def win_rate(self) -> float:
        return self.win_count / max(self.trade_count, 1)

    @property
    def total_pnl_usd(self) -> float:
        return sum(t.net_pnl_usd for t in self.trades)

    @property
    def avg_pnl_per_trade(self) -> float:
        return self.total_pnl_usd / max(self.trade_count, 1)

    @property
    def max_drawdown_usd(self) -> float:
        peak = 0.0
        cumulative = 0.0
        max_dd = 0.0
        for t in self.trades:
            cumulative += t.net_pnl_usd
            peak = max(peak, cumulative)
            dd = peak - cumulative
            max_dd = max(max_dd, dd)
        return max_dd

    @property
    def avg_hold_minutes(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.holding_minutes for t in self.trades) / len(self.trades)

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.net_pnl_usd for t in self.trades if t.net_pnl_usd > 0)
        gross_loss = abs(sum(t.net_pnl_usd for t in self.trades if t.net_pnl_usd <= 0))
        return gross_profit / max(gross_loss, 0.01)

    @property
    def best_trade_usd(self) -> float:
        return max((t.net_pnl_usd for t in self.trades), default=0.0)

    @property
    def worst_trade_usd(self) -> float:
        return min((t.net_pnl_usd for t in self.trades), default=0.0)


def load_5m_bars(data_dir: Path, symbol: str) -> list[dict]:
    """Load 5m bars sorted by open_time."""
    path = data_dir / symbol / "5m.json"
    if not path.exists():
        return []
    with open(path) as f:
        bars = json.load(f)
    bars.sort(key=lambda b: b["open_time"])
    return bars


def run_position_sim(
    slices: list,
    bars_5m: list[dict],
    cfg: SimConfig,
    settings,
    service,
) -> SimResult:
    """Walk through decision slices. On entry signal, track position using 5m bars."""
    trades: list[Trade] = []
    position: Trade | None = None
    cooldown_until: datetime | None = None

    # Build 5m bar index by time for fast lookup
    bar_by_time: dict[int, dict] = {}
    for b in bars_5m:
        bar_by_time[b["open_time"]] = b

    # 5m bars sorted
    bar_times = sorted(bar_by_time.keys())

    for sl in slices:
        decision_time = sl.decision_time

        # Skip if in cooldown
        if cooldown_until and decision_time < cooldown_until:
            continue

        # If position open, check exit on this decision
        if position is not None:
            # Time-based exit
            hold_limit = position.entry_time + timedelta(hours=cfg.max_hold_hours)
            if decision_time >= hold_limit:
                position.exit_time = decision_time
                position.exit_price = sl.state.last_trade_price
                position.exit_reason = "MAX_HOLD_TIME"
                _finalize_trade(position, cfg)
                trades.append(position)
                cooldown_until = decision_time + timedelta(minutes=15)
                position = None
                continue

            # Signal reversal exit
            try:
                decision = service.run_cycle(
                    state=sl.state,
                    primitive_inputs=sl.primitive_inputs,
                    history=sl.history,
                    decision_time=decision_time,
                    equity_usd=cfg.equity_usd,
                    remaining_portfolio_capacity_usd=cfg.equity_usd * 2.5,
                )
                if decision.final_mode == "cash" or decision.side != position.side:
                    # Check if we should exit — only if significantly reversed
                    if decision.final_mode == "cash" and decision.predictability_score < cfg.score_min - 10:
                        position.exit_time = decision_time
                        position.exit_price = sl.state.last_trade_price
                        position.exit_reason = "SIGNAL_REVERSAL"
                        _finalize_trade(position, cfg)
                        trades.append(position)
                        cooldown_until = decision_time + timedelta(minutes=15)
                        position = None
                    elif decision.side != position.side and decision.final_mode in ("futures", "spot"):
                        position.exit_time = decision_time
                        position.exit_price = sl.state.last_trade_price
                        position.exit_reason = "DIRECTION_FLIP"
                        _finalize_trade(position, cfg)
                        trades.append(position)
                        cooldown_until = decision_time + timedelta(minutes=15)
                        position = None
            except Exception:
                pass

            # Skip entry evaluation if position still open
            if position is not None:
                continue

        # No position — evaluate entry
        try:
            decision = service.run_cycle(
                state=sl.state,
                primitive_inputs=sl.primitive_inputs,
                history=sl.history,
                decision_time=decision_time,
                equity_usd=cfg.equity_usd,
                remaining_portfolio_capacity_usd=cfg.equity_usd * 2.5,
            )
        except Exception:
            continue

        if decision.final_mode not in ("spot", "futures"):
            continue

        if decision.predictability_score < cfg.score_min:
            continue

        # ENTER position
        entry_price = sl.state.last_trade_price
        notional = cfg.equity_usd * cfg.equity_risk_frac * cfg.leverage
        position = Trade(
            symbol=sl.symbol,
            side=decision.side,
            entry_time=decision_time,
            entry_price=entry_price,
            leverage=cfg.leverage,
            notional_usd=notional,
            score=decision.predictability_score,
        )

        # --- Track position through 5m bars until exit ---
        entry_ms = int(decision_time.timestamp() * 1000)
        max_hold_ms = int(cfg.max_hold_hours * 3600 * 1000)
        trailing_armed = False
        trailing_stop_price = 0.0

        for bt in bar_times:
            if bt <= entry_ms:
                continue
            if bt > entry_ms + max_hold_ms:
                break

            bar = bar_by_time[bt]
            bar_high = bar["high_price"]
            bar_low = bar["low_price"]
            bar_close = bar["close_price"]
            bar_time = datetime.fromtimestamp(bt / 1000, tz=timezone.utc)

            # Calculate ROE at extremes
            if position.side == "long":
                best_roe = (bar_high / entry_price - 1) * 100 * cfg.leverage
                worst_roe = (bar_low / entry_price - 1) * 100 * cfg.leverage
            else:
                best_roe = -(bar_low / entry_price - 1) * 100 * cfg.leverage
                worst_roe = -(bar_high / entry_price - 1) * 100 * cfg.leverage

            position.peak_roe_pct = max(position.peak_roe_pct, best_roe)
            position.worst_roe_pct = min(position.worst_roe_pct, worst_roe)

            # Check SL hit
            if worst_roe <= -cfg.sl_roe_pct:
                if position.side == "long":
                    position.exit_price = entry_price * (1 - cfg.sl_roe_pct / 100 / cfg.leverage)
                else:
                    position.exit_price = entry_price * (1 + cfg.sl_roe_pct / 100 / cfg.leverage)
                position.exit_time = bar_time
                position.exit_reason = "STOP_LOSS"
                break

            # Check TP hit
            if best_roe >= cfg.tp_roe_pct:
                if position.side == "long":
                    position.exit_price = entry_price * (1 + cfg.tp_roe_pct / 100 / cfg.leverage)
                else:
                    position.exit_price = entry_price * (1 - cfg.tp_roe_pct / 100 / cfg.leverage)
                position.exit_time = bar_time
                position.exit_reason = "TAKE_PROFIT"
                break

            # Trailing stop
            if cfg.trailing_stop_arm_roe < 900:
                if best_roe >= cfg.trailing_stop_arm_roe:
                    trailing_armed = True
                    if position.side == "long":
                        new_stop = bar_high * (1 - cfg.trailing_stop_retrace_roe / 100 / cfg.leverage)
                        trailing_stop_price = max(trailing_stop_price, new_stop)
                    else:
                        new_stop = bar_low * (1 + cfg.trailing_stop_retrace_roe / 100 / cfg.leverage)
                        trailing_stop_price = min(trailing_stop_price, new_stop) if trailing_stop_price > 0 else new_stop

                if trailing_armed:
                    if position.side == "long" and bar_low <= trailing_stop_price:
                        position.exit_price = trailing_stop_price
                        position.exit_time = bar_time
                        position.exit_reason = "TRAILING_STOP"
                        break
                    elif position.side == "short" and bar_high >= trailing_stop_price:
                        position.exit_price = trailing_stop_price
                        position.exit_time = bar_time
                        position.exit_reason = "TRAILING_STOP"
                        break

        # If still open after all 5m bars, close at last bar
        if position.exit_time is None:
            last_bar = bar_by_time[bar_times[-1]]
            position.exit_time = datetime.fromtimestamp(bar_times[-1] / 1000, tz=timezone.utc)
            position.exit_price = last_bar["close_price"]
            position.exit_reason = "MAX_HOLD_TIME"

        _finalize_trade(position, cfg)
        trades.append(position)
        cooldown_until = position.exit_time + timedelta(minutes=15)
        position = None

    return SimResult(config=cfg, trades=trades)


def _finalize_trade(trade: Trade, cfg: SimConfig):
    """Calculate P&L with fees."""
    if trade.exit_price is None or trade.entry_price <= 0:
        return
    if trade.side == "long":
        raw_return = (trade.exit_price / trade.entry_price - 1)
    else:
        raw_return = -(trade.exit_price / trade.entry_price - 1)

    trade.pnl_usd = trade.notional_usd * raw_return
    trade.fee_usd = trade.notional_usd * cfg.cost_bps / 10000
    trade.net_pnl_usd = trade.pnl_usd - trade.fee_usd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Position-management backtest with 5m bar tracking")
    parser.add_argument("--symbols", default="ETHUSDT,SOLUSDT")
    parser.add_argument("--score-min", nargs="+", type=float, default=[55, 62, 68, 72, 78])
    parser.add_argument("--tp-roe", nargs="+", type=float, default=[5, 8, 12, 20])
    parser.add_argument("--sl-roe", nargs="+", type=float, default=[8, 12, 15, 20])
    parser.add_argument("--max-hold-hours", nargs="+", type=float, default=[4, 12, 24, 48])
    parser.add_argument("--leverage", nargs="+", type=int, default=[10, 15])
    parser.add_argument("--equity-usd", type=float, default=75.0)
    parser.add_argument("--cost-bps", type=float, default=20.0)
    parser.add_argument("--config", default="quant_binance/config.example.json")
    parser.add_argument("--output-base", default="quant_runtime")
    parser.add_argument("--top-n", type=int, default=20, help="Show top N results")
    args = parser.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",")]

    # Set env
    os.environ.setdefault("STRATEGY_OVERRIDE_PATH",
                          str(Path(args.output_base) / "artifacts" / "strategy_override.backtest_sniper.json"))
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

    print(f"[sim] Settings: universe={settings.universe} score_min={settings.mode_thresholds.futures_score_min}")

    # Build slices and load 5m bars (with pickle cache for speed)
    import pickle
    cache_dir = Path(args.output_base) / "output" / "_sim_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_data: dict[str, tuple[list, list[dict]]] = {}
    for sym in symbols:
        cache_path = cache_dir / f"{sym}_slices.pkl"
        bars_5m = load_5m_bars(data_dir, sym)

        if cache_path.exists():
            print(f"  {sym}: loading cached slices...", end="", flush=True)
            with open(cache_path, "rb") as f:
                slices = pickle.load(f)
            print(f" {len(slices)} slices, {len(bars_5m)} 5m bars")
        else:
            print(f"  {sym}: building slices (first run, will cache)...", flush=True)
            k5m = load_historical_klines(data_dir=data_dir, symbol=sym, interval="5m")
            k1h = load_historical_klines(data_dir=data_dir, symbol=sym, interval="1h")
            k4h = load_historical_klines(data_dir=data_dir, symbol=sym, interval="4h")
            k1m = load_historical_klines(data_dir=data_dir, symbol=sym, interval="1m")
            spot_1h = load_spot_klines(data_dir=data_dir, symbol=sym, interval="1h")
            funding = load_funding_rates(data_dir=data_dir, symbol=sym)

            if not k1h:
                print(f"  {sym}: no 1h data, skipping")
                continue

            slices = build_historical_slices(
                symbol=sym, klines_5m=k5m, klines_1h=k1h, klines_4h=k4h, klines_1m=k1m,
                spot_klines_1h=spot_1h, funding_rates=funding,
                settings=settings, extractor=extractor,
            )

            if not bars_5m:
                bars_5m = k5m if k5m else []

            # Cache for future runs
            with open(cache_path, "wb") as f:
                pickle.dump(slices, f)
            print(f"  {sym}: {len(slices)} slices, {len(bars_5m)} 5m bars (cached)")

        all_data[sym] = (slices, bars_5m)

    if not all_data:
        print("[ERROR] No data loaded")
        return 1

    # Generate parameter grid
    combos = list(itertools.product(
        args.score_min, args.tp_roe, args.sl_roe, args.max_hold_hours, args.leverage
    ))
    print(f"\n[sim] {len(combos)} parameter combos × {len(all_data)} symbols = {len(combos) * len(all_data)} runs")

    all_results: list[SimResult] = []
    total_runs = len(combos) * len(all_data)
    run_idx = 0

    for score_min, tp, sl, hold_h, lev in combos:
        cfg = SimConfig(
            score_min=score_min,
            tp_roe_pct=tp,
            sl_roe_pct=sl,
            max_hold_hours=hold_h,
            leverage=lev,
            equity_usd=args.equity_usd,
            cost_bps=args.cost_bps,
        )

        for sym, (slices, bars_5m) in all_data.items():
            run_idx += 1
            result = run_position_sim(slices, bars_5m, cfg, settings, service)

            # Add symbol info
            for t in result.trades:
                t.symbol = sym

            all_results.append(result)

            if run_idx % 50 == 0:
                print(f"  [{run_idx}/{total_runs}] {sym} {cfg.label}: "
                      f"{result.trade_count} trades, WR={result.win_rate*100:.0f}%, "
                      f"PnL=${result.total_pnl_usd:.2f}")

    # Merge results by config (across symbols)
    merged: dict[str, SimResult] = {}
    for r in all_results:
        key = r.config.label
        if key not in merged:
            merged[key] = SimResult(config=r.config, trades=[])
        merged[key].trades.extend(r.trades)

    # Sort by total PnL
    ranked = sorted(merged.values(), key=lambda r: r.total_pnl_usd, reverse=True)

    # Print results
    print(f"\n{'='*110}")
    print(f"{'POSITION-MANAGEMENT BACKTEST RESULTS':^110}")
    print(f"{'='*110}")
    print(f"{'Rank':>4} {'Score':>5} {'TP%':>4} {'SL%':>4} {'Hold':>5} {'Lev':>3} "
          f"{'Trades':>6} {'WR%':>5} {'PnL$':>8} {'Avg$':>7} {'PF':>5} "
          f"{'MaxDD$':>7} {'Best$':>7} {'Worst$':>7} {'AvgMin':>6}")
    print("-" * 110)

    for i, r in enumerate(ranked[:args.top_n]):
        c = r.config
        print(f"{i+1:>4} {c.score_min:>5.0f} {c.tp_roe_pct:>4.0f} {c.sl_roe_pct:>4.0f} {c.max_hold_hours:>5.0f} {c.leverage:>3} "
              f"{r.trade_count:>6} {r.win_rate*100:>5.1f} {r.total_pnl_usd:>8.2f} {r.avg_pnl_per_trade:>7.2f} {r.profit_factor:>5.2f} "
              f"{r.max_drawdown_usd:>7.2f} {r.best_trade_usd:>7.2f} {r.worst_trade_usd:>7.2f} {r.avg_hold_minutes:>6.0f}")

    # Show bottom 5 too
    print(f"\n--- Bottom {min(5, len(ranked))} ---")
    for r in ranked[-5:]:
        c = r.config
        print(f"     {c.score_min:>5.0f} {c.tp_roe_pct:>4.0f} {c.sl_roe_pct:>4.0f} {c.max_hold_hours:>5.0f} {c.leverage:>3} "
              f"{r.trade_count:>6} {r.win_rate*100:>5.1f} {r.total_pnl_usd:>8.2f} {r.avg_pnl_per_trade:>7.2f} {r.profit_factor:>5.2f} "
              f"{r.max_drawdown_usd:>7.2f} {r.best_trade_usd:>7.2f} {r.worst_trade_usd:>7.2f} {r.avg_hold_minutes:>6.0f}")

    # Detailed breakdown of top result
    if ranked:
        best = ranked[0]
        print(f"\n{'='*80}")
        print(f"TOP RESULT DETAIL: {best.config.label}")
        print(f"{'='*80}")
        print(f"Total trades: {best.trade_count}")
        print(f"Win/Loss: {best.win_count}/{best.loss_count}")
        print(f"Win rate: {best.win_rate*100:.1f}%")
        print(f"Total Net PnL: ${best.total_pnl_usd:.2f}")
        print(f"Profit Factor: {best.profit_factor:.2f}")
        print(f"Max Drawdown: ${best.max_drawdown_usd:.2f}")
        print(f"Avg holding: {best.avg_hold_minutes:.0f} min")

        # Exit reason breakdown
        reasons: dict[str, int] = {}
        for t in best.trades:
            reasons[t.exit_reason] = reasons.get(t.exit_reason, 0) + 1
        print(f"\nExit reasons:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            subset = [t for t in best.trades if t.exit_reason == reason]
            avg_pnl = sum(t.net_pnl_usd for t in subset) / len(subset)
            wr = sum(1 for t in subset if t.net_pnl_usd > 0) / len(subset) * 100
            print(f"  {reason:20s}: {count:4d} trades, WR={wr:5.1f}%, avg=${avg_pnl:+.2f}")

        # Per-symbol breakdown
        sym_groups: dict[str, list[Trade]] = {}
        for t in best.trades:
            sym_groups.setdefault(t.symbol, []).append(t)
        print(f"\nPer-symbol:")
        for sym, sym_trades in sorted(sym_groups.items()):
            wins = sum(1 for t in sym_trades if t.net_pnl_usd > 0)
            pnl = sum(t.net_pnl_usd for t in sym_trades)
            wr = wins / len(sym_trades) * 100
            print(f"  {sym}: {len(sym_trades)} trades, WR={wr:.1f}%, PnL=${pnl:.2f}")

        # Monthly P&L
        monthly: dict[str, float] = {}
        for t in best.trades:
            if t.entry_time:
                key = t.entry_time.strftime("%Y-%m")
                monthly[key] = monthly.get(key, 0) + t.net_pnl_usd
        print(f"\nMonthly PnL:")
        for m, pnl in sorted(monthly.items()):
            bar = "+" * int(max(pnl, 0) / 2) + "-" * int(max(-pnl, 0) / 2)
            print(f"  {m}: ${pnl:+8.2f}  {bar}")

    # Save results to JSON
    output_path = Path(args.output_base) / "output" / "position_sim_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results_data = []
    for r in ranked[:50]:
        c = r.config
        results_data.append({
            "score_min": c.score_min, "tp_roe": c.tp_roe_pct, "sl_roe": c.sl_roe_pct,
            "max_hold_hours": c.max_hold_hours, "leverage": c.leverage,
            "trades": r.trade_count, "win_rate": round(r.win_rate, 4),
            "total_pnl_usd": round(r.total_pnl_usd, 2),
            "avg_pnl_usd": round(r.avg_pnl_per_trade, 2),
            "profit_factor": round(r.profit_factor, 2),
            "max_drawdown_usd": round(r.max_drawdown_usd, 2),
        })
    output_path.write_text(json.dumps(results_data, indent=2))
    print(f"\nResults saved to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
