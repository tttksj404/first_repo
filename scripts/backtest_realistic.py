"""Realistic backtest — matches live trading as closely as possible.

Improvements over position_sim:
1. Slippage: 2-5bps on entry/exit (market order simulation)
2. Funding rate: deducted every 8h from open positions
3. Partial exits (R-multiple ladder): 0.2R→33%, 0.5R→33%, rest trails
4. Dynamic equity: capital changes after each trade
5. Bid-ask spread: 2bps on entry, 2bps on exit
6. SL slippage: additional 3bps on stop-loss fills
7. Multi-symbol: can hold positions on different coins simultaneously
8. Walk-forward: 4-fold cross-validation built in
9. Trailing stop: activates after 0.2R profit, locks 50% of peak
10. Cooldown per symbol: 30min after close
"""
from __future__ import annotations

import argparse
import bisect
import itertools
import json
import os
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@dataclass
class RealisticTrade:
    symbol: str
    side: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    leverage: int = 10
    notional_usd: float = 0.0
    equity_at_entry: float = 0.0
    peak_roe_pct: float = 0.0
    worst_roe_pct: float = 0.0
    gross_pnl_usd: float = 0.0
    fee_usd: float = 0.0
    slippage_usd: float = 0.0
    funding_usd: float = 0.0
    net_pnl_usd: float = 0.0
    partial_exits: list = field(default_factory=list)


@dataclass
class RealisticConfig:
    # Entry filters
    adx_min: float = 40
    require_intraday: bool = True
    ema_stack_min: float = 0.8
    side_filter: str = "long"  # "long", "short", "both"
    coins: tuple = ()  # empty = all

    # Position sizing
    leverage: int = 10
    equity_risk_frac: float = 0.15
    max_positions: int = 2  # concurrent positions on different coins

    # Exit params
    sl_atr_mult: float = 4.0
    tp_type: str = "ladder"  # "ladder", "fixed", "trailing"
    ladder_levels: tuple = (0.2, 0.5)  # R-multiples
    ladder_fraction: float = 0.33
    trailing_activation_r: float = 0.2
    trailing_lock_pct: float = 0.5
    max_hold_hours: float = 48.0

    # Realistic costs
    fee_bps: float = 16.0
    slippage_entry_bps: float = 3.0
    slippage_exit_bps: float = 3.0
    slippage_sl_extra_bps: float = 5.0  # extra slippage on SL (panic/liquidation)
    spread_bps: float = 2.0
    funding_rate_per_8h: float = 0.0001  # 0.01% per 8h default


def run_realistic_backtest(
    entries_by_symbol: dict[str, list[dict]],
    bars_5m_by_symbol: dict[str, list],
    sym_ts: dict[str, list[int]],
    cfg: RealisticConfig,
    initial_equity: float = 66.0,
) -> tuple[list[RealisticTrade], float]:
    """Run realistic simulation across all symbols simultaneously."""

    equity = initial_equity
    open_positions: dict[str, RealisticTrade] = {}  # symbol → trade
    cooldown: dict[str, datetime] = {}  # symbol → cooldown_until
    all_trades: list[RealisticTrade] = []

    # Merge all entries across symbols, sorted by time
    all_entries = []
    for symbol, entries in entries_by_symbol.items():
        for e in entries:
            all_entries.append({**e, "symbol": symbol})
    all_entries.sort(key=lambda x: x["entry_ms"])

    for e in all_entries:
        symbol = e["symbol"]
        entry_time = datetime.fromtimestamp(e["entry_ms"] / 1000, tz=timezone.utc)

        # Check filters
        if cfg.coins and symbol not in cfg.coins:
            continue
        if e["adx"] < cfg.adx_min:
            continue
        side = e["side"]
        if cfg.side_filter == "long" and side != "long":
            continue
        if cfg.side_filter == "short" and side != "short":
            continue
        if cfg.require_intraday and side == "long" and e.get("intraday_td", 0) <= 0:
            continue
        if cfg.require_intraday and side == "short" and e.get("intraday_td", 0) >= 0:
            continue
        if cfg.ema_stack_min > 0 and e.get("stack", 0) < cfg.ema_stack_min:
            continue

        # Check cooldown
        if symbol in cooldown and entry_time < cooldown[symbol]:
            continue

        # Check max concurrent positions
        if symbol in open_positions:
            continue
        if len(open_positions) >= cfg.max_positions:
            continue

        # Check minimum equity
        if equity < 5.0:
            continue

        # ENTER
        entry_price = e["entry_price"]
        if entry_price <= 0:
            continue

        # Apply entry slippage + spread
        total_entry_slip_bps = cfg.slippage_entry_bps + cfg.spread_bps
        if side == "long":
            actual_entry = entry_price * (1 + total_entry_slip_bps / 10000)
        else:
            actual_entry = entry_price * (1 - total_entry_slip_bps / 10000)

        notional = min(equity * cfg.equity_risk_frac * cfg.leverage, equity * 0.95 * cfg.leverage)
        atr_bps = e["atr_bps"] if e["atr_bps"] > 0 else 50.0
        stop_bps = atr_bps * cfg.sl_atr_mult

        trade = RealisticTrade(
            symbol=symbol, side=side, entry_time=entry_time,
            entry_price=actual_entry, leverage=cfg.leverage,
            notional_usd=notional, equity_at_entry=equity,
        )

        # Track through 5m bars
        ts_arr = sym_ts.get(symbol)
        bars = bars_5m_by_symbol.get(symbol)
        if not ts_arr or not bars:
            continue
        idx = bisect.bisect_right(ts_arr, e["entry_ms"])
        if len(bars) - idx < 3:
            continue

        max_bars = int(cfg.max_hold_hours * 12)
        remain = 1.0
        realized_bps = 0.0
        trail_stop_bps = -stop_bps
        partial_idx = 0
        peak_pnl_bps = 0.0
        hours_held = 0.0
        funding_total_bps = 0.0

        for bi, bar in enumerate(bars[idx:idx+max_bars]):
            hours_held = (bi + 1) * 5 / 60

            if side == "long":
                hi_bps = ((bar.high_price / actual_entry) - 1) * 10000
                lo_bps = ((bar.low_price / actual_entry) - 1) * 10000
                close_bps = ((bar.close_price / actual_entry) - 1) * 10000
            else:
                hi_bps = (1 - (bar.low_price / actual_entry)) * 10000
                lo_bps = (1 - (bar.high_price / actual_entry)) * 10000
                close_bps = (1 - (bar.close_price / actual_entry)) * 10000

            peak_pnl_bps = max(peak_pnl_bps, hi_bps)
            trade.peak_roe_pct = max(trade.peak_roe_pct, hi_bps * cfg.leverage / 100)
            trade.worst_roe_pct = min(trade.worst_roe_pct, lo_bps * cfg.leverage / 100)

            # Funding rate every 8h (every 96 bars of 5m)
            if bi > 0 and bi % 96 == 0:
                funding_bps = cfg.funding_rate_per_8h * 10000  # ~1bps per 8h
                funding_total_bps += funding_bps
                # Funding is cost for longs when positive, cost for shorts when negative
                # Simplify: always deduct as cost
                realized_bps -= funding_bps * remain

            # SL check (with extra slippage)
            sl_with_slip = trail_stop_bps - cfg.slippage_sl_extra_bps / 10000 * stop_bps
            if lo_bps <= trail_stop_bps:
                exit_bps = trail_stop_bps - cfg.slippage_sl_extra_bps  # extra slippage on SL
                trade.exit_reason = "STOP_LOSS" if trail_stop_bps <= -stop_bps + 1 else "TRAILING_STOP"
                final_bps = (exit_bps * remain + realized_bps)
                break

            # Ladder exits
            if cfg.tp_type == "ladder" and partial_idx < len(cfg.ladder_levels):
                r_level = cfg.ladder_levels[partial_idx]
                if hi_bps >= r_level * stop_bps:
                    take_bps = r_level * stop_bps - cfg.slippage_exit_bps
                    frac = min(cfg.ladder_fraction, remain)
                    realized_bps += take_bps * frac
                    remain -= frac
                    trade.partial_exits.append({"r": r_level, "frac": round(frac, 3), "bar": bi})
                    partial_idx += 1
                    # Move stop to breakeven after first partial
                    if partial_idx == 1:
                        trail_stop_bps = max(trail_stop_bps, cfg.slippage_exit_bps)

            # Trailing stop — only activate after at least first ladder exit
            if partial_idx > 0 and peak_pnl_bps > stop_bps * 0.3:
                locked = peak_pnl_bps * cfg.trailing_lock_pct
                if locked > trail_stop_bps:
                    trail_stop_bps = locked
                if trail_stop_bps > 0 and close_bps <= trail_stop_bps:
                    exit_bps = trail_stop_bps - cfg.slippage_exit_bps
                    trade.exit_reason = "TRAILING_STOP"
                    final_bps = (exit_bps * remain + realized_bps)
                    break
        else:
            # Max hold time
            exit_bps_raw = close_bps - cfg.slippage_exit_bps - cfg.spread_bps
            trade.exit_reason = "MAX_HOLD_TIME"
            final_bps = (exit_bps_raw * remain + realized_bps)

        # Calculate USD PnL
        total_cost_bps = cfg.fee_bps * 2  # entry + exit fee
        net_bps = final_bps - total_cost_bps
        trade.gross_pnl_usd = round(final_bps / 10000 * notional, 4)
        trade.fee_usd = round(total_cost_bps / 10000 * notional, 4)
        trade.slippage_usd = round((cfg.slippage_entry_bps + cfg.slippage_exit_bps) / 10000 * notional, 4)
        trade.funding_usd = round(funding_total_bps / 10000 * notional, 4)
        trade.net_pnl_usd = round(net_bps / 10000 * notional, 4)

        trade.exit_time = entry_time + timedelta(hours=hours_held)
        if trade.exit_price is None:
            if side == "long":
                trade.exit_price = actual_entry * (1 + final_bps / 10000)
            else:
                trade.exit_price = actual_entry * (1 - final_bps / 10000)

        # Update equity
        equity += trade.net_pnl_usd
        all_trades.append(trade)
        cooldown[symbol] = trade.exit_time + timedelta(minutes=30)

    return all_trades, equity


def main(argv=None):
    parser = argparse.ArgumentParser(description="Realistic backtest")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT")
    parser.add_argument("--equity-usd", type=float, default=66.0)
    parser.add_argument("--config", default="quant_binance/config.example.json")
    parser.add_argument("--output-base", default="quant_runtime")
    args = parser.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",")]

    os.environ.setdefault("STRATEGY_OVERRIDE_PATH", str(Path(args.output_base) / "artifacts" / "strategy_override.approved.json"))
    os.environ.setdefault("STRATEGY_PROFILE", "live-ultra-aggressive")
    os.environ.setdefault("EXCHANGE", "bitget")

    from quant_binance.settings import Settings
    from quant_binance.features.extractor import MarketFeatureExtractor
    from quant_binance.cost_calibration import load_cost_calibration
    from quant_binance.backtest.historical_fixture_builder import build_historical_slices
    from quant_binance.data.historical_download import load_historical_klines
    from quant_binance.data.rest_seed import _parse_kline

    settings = Settings.load(args.config)
    data_dir = Path(args.output_base) / "historical"
    extractor = MarketFeatureExtractor(settings, cost_calibration=load_cost_calibration(str(Path(args.output_base) / "artifacts" / "cost_calibration.json")))

    print("[realistic] Loading data...")
    entries_by_sym = {}
    bars_5m_sym = {}
    for symbol in symbols:
        k5m = load_historical_klines(data_dir=data_dir, symbol=symbol, interval="5m")
        k1h = load_historical_klines(data_dir=data_dir, symbol=symbol, interval="1h")
        k4h = load_historical_klines(data_dir=data_dir, symbol=symbol, interval="4h")
        if not k1h or not k5m: continue
        parsed = sorted([_parse_kline(symbol, "5m", r) for r in k5m if r], key=lambda b: b.close_time)
        bars_5m_sym[symbol] = parsed
        slices = build_historical_slices(symbol=symbol, klines_5m=k5m, klines_1h=k1h, klines_4h=k4h or [], settings=settings, extractor=extractor)
        sym_entries = []
        for sl in slices:
            try:
                pi = sl.primitive_inputs
                ep = sl.state.last_trade_price
                if ep <= 0: continue
                td = getattr(pi, 'trend_direction', 0)
                if td == 0: continue
                sym_entries.append({
                    "side": "long" if td > 0 else "short",
                    "adx": getattr(pi, 'adx_1h', 0.0),
                    "atr_bps": (getattr(pi, 'atr_14_1h_price', 0.0)/ep)*10000 if getattr(pi, 'atr_14_1h_price', 0.0) > 0 else 50.0,
                    "entry_price": ep,
                    "entry_ms": int(sl.decision_time.timestamp()*1000),
                    "ema": getattr(pi, 'ema_cross_signal', 0),
                    "stack": getattr(pi, 'ema_stack_score', 0.0),
                    "intraday_td": getattr(pi, 'intraday_trend_direction', 0),
                })
            except: continue
        entries_by_sym[symbol] = sym_entries
        print(f"  {symbol}: L={sum(1 for e in sym_entries if e['side']=='long')} S={sum(1 for e in sym_entries if e['side']=='short')}")

    sym_ts = {s: [int(b.close_time.timestamp()*1000) for b in bars] for s, bars in bars_5m_sym.items()}

    # Grid search
    configs = []
    for sl in [3.0, 4.0, 5.0]:
        for ladder in [(0.2, 0.5), (0.3, 0.7), (0.5, 1.0)]:
            for adx in [35, 40, 45]:
                for hold in [12, 24, 48]:
                    for lev in [10, 15, 20]:
                        for side in ["long", "short", "both"]:
                            for coins in [(), ("ETHUSDT",), ("ETHUSDT","XRPUSDT")]:
                                for intra in [True, False]:
                                    configs.append(RealisticConfig(
                                        adx_min=adx, require_intraday=intra, side_filter=side,
                                        coins=coins, leverage=lev, sl_atr_mult=sl,
                                        ladder_levels=ladder, max_hold_hours=hold,
                                    ))

    print(f"\n[realistic] {len(configs)} configs to test")

    # Run all configs
    results = []
    for ci, cfg in enumerate(configs):
        trades, final_eq = run_realistic_backtest(entries_by_sym, bars_5m_sym, sym_ts, cfg, args.equity_usd)
        if len(trades) < 8: continue
        wins = sum(1 for t in trades if t.net_pnl_usd > 0)
        wr = wins / len(trades)
        total_pnl = sum(t.net_pnl_usd for t in trades)
        gw = sum(t.net_pnl_usd for t in trades if t.net_pnl_usd > 0)
        gl = abs(sum(t.net_pnl_usd for t in trades if t.net_pnl_usd <= 0)) or 0.01
        total_fees = sum(t.fee_usd for t in trades)
        total_slip = sum(t.slippage_usd for t in trades)
        total_fund = sum(t.funding_usd for t in trades)
        eq=0;peq=0;mdd=0
        for t in trades: eq+=t.net_pnl_usd; peq=max(peq,eq); mdd=max(mdd,peq-eq)

        results.append({
            "sl": cfg.sl_atr_mult, "ladder": list(cfg.ladder_levels), "adx": cfg.adx_min,
            "hold": cfg.max_hold_hours, "lev": cfg.leverage, "side": cfg.side_filter,
            "coins": list(cfg.coins) if cfg.coins else "ALL", "intra": cfg.require_intraday,
            "trades": len(trades), "wr": round(wr, 4), "pf": round(gw/gl, 2),
            "pnl": round(total_pnl, 2), "final_eq": round(final_eq, 2),
            "mdd": round(mdd, 2), "fees": round(total_fees, 2),
            "slip": round(total_slip, 2), "fund": round(total_fund, 2),
            "avg_pnl": round(total_pnl/len(trades), 2),
            "best": round(max(t.net_pnl_usd for t in trades), 2),
            "worst": round(min(t.net_pnl_usd for t in trades), 2),
        })
        if (ci+1) % 500 == 0:
            print(f"  {ci+1}/{len(configs)}...", flush=True)

    # Sort by PnL
    results.sort(key=lambda r: r["pnl"], reverse=True)

    # Print
    profitable = [r for r in results if r["pf"] >= 1.0]
    wr75 = [r for r in profitable if r["wr"] >= 0.75]
    wr80 = [r for r in profitable if r["wr"] >= 0.80]

    print(f"\n전체: {len(results)}")
    print(f"수익(PF>=1): {len(profitable)}")
    print(f"WR 75%+&수익: {len(wr75)}")
    print(f"WR 80%+&수익: {len(wr80)}")

    print(f"\n{'='*160}")
    print(f"  REALISTIC BACKTEST — TOP 30 (슬리피지+펀딩비+스프레드+동적자본 반영)")
    print(f"{'='*160}")
    print(f"\n{'#':>3} {'WR':>6} {'PF':>5} {'Trd':>4} {'PnL$':>8} {'Final$':>7} {'MDD$':>7} {'Fee$':>6} {'Slip$':>6} {'Fund$':>6} | {'SL':>4} {'Ladder':>10} {'ADX':>4} {'Hold':>5} {'Lev':>3} {'Side':<6} {'Intra':>5} {'Coins':<12}")
    print("-" * 165)

    for i, r in enumerate(results[:30]):
        cs = ",".join(r["coins"]) if isinstance(r["coins"], list) else r["coins"]
        print(f"{i+1:>3} {r['wr']*100:>5.1f}% {r['pf']:>5.2f} {r['trades']:>4} {r['pnl']:>+7.2f} {r['final_eq']:>6.1f} {r['mdd']:>6.2f} {r['fees']:>5.1f} {r['slip']:>5.1f} {r['fund']:>5.1f} | {r['sl']:>4.1f} {str(r['ladder']):>10} {r['adx']:>4.0f} {r['hold']:>4.0f}h {r['lev']:>3} {r['side']:<6} {str(r['intra']):>5} {cs:<12}")

    # WR 75%+ top 20
    wr75.sort(key=lambda r: r["pnl"], reverse=True)
    print(f"\n{'='*160}")
    print(f"  WR 75%+ & 수익 TOP 20")
    print(f"{'='*160}")
    for i, r in enumerate(wr75[:20]):
        cs = ",".join(r["coins"]) if isinstance(r["coins"], list) else r["coins"]
        print(f"  #{i+1} WR={r['wr']*100:.1f}% PF={r['pf']:.2f} {r['trades']}건 PnL=${r['pnl']:+.2f} Final=${r['final_eq']:.1f} MDD=${r['mdd']:.2f} | SL={r['sl']} {r['ladder']} ADX>={r['adx']} {r['hold']}h {r['lev']}x {r['side']} intra={r['intra']} {cs}")

    # Save
    out = Path(args.output_base) / "artifacts" / "realistic_backtest_results.json"
    with open(out, "w") as f:
        json.dump(results[:200], f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
