#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quant_binance.data.state import KlineBar, SymbolMarketState, TopOfBook
from quant_binance.funding_rate_strategy import FundingRateTracker, load_funding_rate_config


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "quant_runtime" / "historical"
OUTPUT_PATH = ROOT / "quant_runtime" / "artifacts" / "carry_runtime_validation.json"


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _build_hour_bars(symbol: str) -> list[KlineBar]:
    rows = _load_json(DATA_DIR / symbol / "1h.json")
    bars: list[KlineBar] = []
    for row in rows:
        start = datetime.fromtimestamp(int(row["open_time"]) / 1000.0, tz=timezone.utc)
        close = start + timedelta(hours=1)
        bars.append(
            KlineBar(
                symbol=symbol,
                interval="1h",
                start_time=start,
                close_time=close,
                open_price=float(row["open_price"]),
                high_price=float(row["high_price"]),
                low_price=float(row["low_price"]),
                close_price=float(row["close_price"]),
                volume=float(row.get("base_volume", 0.0) or 0.0),
                quote_volume=float(row.get("quote_volume", 0.0) or 0.0),
                is_closed=True,
            )
        )
    return bars


def _load_funding_map(symbol: str) -> dict[int, float]:
    rows = _load_json(DATA_DIR / symbol / "funding_rates.json")
    return {int(row["funding_time"]): float(row["funding_rate"]) for row in rows}


def _state_from_bar(
    *,
    symbol: str,
    bar: KlineBar,
    funding_rate: float,
    open_interest: float,
    basis_bps: float,
    history: list[KlineBar],
) -> SymbolMarketState:
    price = bar.close_price
    return SymbolMarketState(
        symbol=symbol,
        top_of_book=TopOfBook(
            bid_price=price * 0.9999,
            bid_qty=1.0,
            ask_price=price * 1.0001,
            ask_qty=1.0,
            updated_at=bar.close_time,
        ),
        last_trade_price=price,
        funding_rate=funding_rate,
        open_interest=open_interest,
        basis_bps=basis_bps,
        last_update_time=bar.close_time,
        klines={"1h": list(history)},
        funding_rate_samples=[funding_rate],
        basis_bps_samples=[basis_bps],
        open_interest_samples=[open_interest],
    )


def run_validation(override_path: Path) -> dict[str, object]:
    override = json.loads(override_path.read_text(encoding="utf-8"))
    config = load_funding_rate_config(override)
    tracker = FundingRateTracker(config)
    per_symbol: dict[str, dict[str, object]] = {}

    for symbol in config.symbols:
        bars = _build_hour_bars(symbol)
        funding_map = _load_funding_map(symbol)
        if not bars or not funding_map:
            continue
        history: list[KlineBar] = []
        states: dict[str, SymbolMarketState] = {}
        for index, bar in enumerate(bars):
            history.append(bar)
            funding_rate = funding_map.get(int(bar.start_time.timestamp() * 1000), 0.0)
            basis_bps = funding_rate * 10000.0 * 0.5
            open_interest = 1_000_000.0 + index * 1000.0
            state = _state_from_bar(
                symbol=symbol,
                bar=bar,
                funding_rate=funding_rate,
                open_interest=open_interest,
                basis_bps=basis_bps,
                history=history[-60:],
            )
            states[symbol] = state
            signals = tracker.generate_signals(states, bar.close_time)
            for signal in signals:
                tracker.open_position(signal)
            exits = tracker.evaluate_exits(states, bar.close_time)
            for exit_symbol, exit_reason, exit_price in exits:
                tracker.close_position(exit_symbol, exit_reason, exit_price, bar.close_time)
        summary = tracker.summary()
        per_symbol[symbol] = summary

    return {
        "override_path": str(override_path),
        "config": {
            "enabled": config.enabled,
            "threshold": config.threshold,
            "max_hold_hours": config.max_hold_hours,
            "symbols": list(config.symbols),
            "notional_usd_per_trade": config.notional_usd_per_trade,
        },
        "per_symbol": per_symbol,
        "portfolio": {
            "total_trades": sum(int(item.get("total_trades", 0)) for item in per_symbol.values()),
            "total_pnl_usd": round(sum(float(item.get("total_pnl_usd", 0.0)) for item in per_symbol.values()), 4),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a carry candidate override against FundingRateTracker on local historical data.")
    parser.add_argument("--override", default="quant_runtime/artifacts/candidate_overrides/strategy_override.carry_top1.json")
    args = parser.parse_args()
    payload = run_validation(Path(args.override))
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
