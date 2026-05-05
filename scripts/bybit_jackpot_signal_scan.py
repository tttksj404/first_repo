#!/usr/bin/env python3
"""Scan current Bybit 1h candles for small-account jackpot candidates.

This is a no-order scanner. It reuses the auto4h signal definitions and checks
only the latest closed Bybit linear 1h candle.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "output" / "bybit_jackpot_signal_scan.json"

sys.path.insert(0, str(ROOT / "scripts"))
from auto4h_phaseQ_short_side import SHORT_SIGNALS, precompute_bear_regime  # noqa: E402
from auto4h_phaseV_extra_shorts import EXTRA_SHORT_SIGNALS  # noqa: E402
from auto4h_signal_library import SIGNALS  # noqa: E402
from auto4h_stage1_matrix import precompute_btc_regime  # noqa: E402
from quant_phase15_signal_library import add_extra_features  # noqa: E402
from quant_phase16_robustness import add_obv  # noqa: E402
from quant_rotation_engine import compute_indicators  # noqa: E402


ALL_SHORT_SIGNALS = {**SHORT_SIGNALS, **EXTRA_SHORT_SIGNALS}

DEFAULT_CANDIDATES = [
    {
        "name": "XRP adx_trend core",
        "source": "auto4h_stage2",
        "side": "long",
        "symbol": "XRPUSDT",
        "signal": "adx_trend",
        "mom": 0.04,
        "tp_roe": 30,
        "sl_roe": -30,
        "evidence": {"n": 33, "pf": 3.13, "wf": 4},
    },
    {
        "name": "ETH donchian paper tightened",
        "source": "recent_optimize",
        "side": "long",
        "symbol": "ETHUSDT",
        "signal": "donchian_20",
        "mom": 0.02,
        "tp_roe": 50,
        "sl_roe": -25,
        "evidence": {"local_n": 49, "local_pf": 2.11, "local_wf": 3, "recent_n": 7},
    },
    {
        "name": "ETH vol_expansion",
        "source": "auto4h_stage2",
        "side": "long",
        "symbol": "ETHUSDT",
        "signal": "vol_expansion",
        "mom": 0.02,
        "tp_roe": 50,
        "sl_roe": -25,
        "evidence": {"n": 31, "pf": 2.50, "wf": 4},
    },
    {
        "name": "SUI donchian yolo",
        "source": "auto4h_stage2",
        "side": "long",
        "symbol": "SUIUSDT",
        "signal": "donchian_20",
        "mom": 0.04,
        "tp_roe": 100,
        "sl_roe": -50,
        "evidence": {"n": 29, "pf": 3.14, "wf": 4},
    },
    {
        "name": "WIF momentum_obv jackpot",
        "source": "auto4h_stage2",
        "side": "long",
        "symbol": "WIFUSDT",
        "signal": "momentum_obv",
        "mom": 0.04,
        "tp_roe": 300,
        "sl_roe": -25,
        "evidence": {"n": 46, "pf": 2.16, "wf": 3},
    },
    {
        "name": "WIF heikin 5usdt jackpot",
        "source": "phaseUUU",
        "side": "long",
        "symbol": "WIFUSDT",
        "signal": "heikin_cont",
        "mom": 0.06,
        "tp_roe": 100,
        "sl_roe": -25,
        "evidence": {"n": 23, "wr_pct": 65.2, "ruin_pct": 1.1},
    },
    {
        "name": "DOGE vol_expansion 5usdt",
        "source": "phaseUUU",
        "side": "long",
        "symbol": "DOGEUSDT",
        "signal": "vol_expansion",
        "mom": 0.04,
        "tp_roe": 80,
        "sl_roe": -30,
        "evidence": {"n": 29, "wr_pct": 75.9, "ruin_pct": 0.0},
    },
    {
        "name": "ADA heikin 5usdt",
        "source": "phaseUUU",
        "side": "long",
        "symbol": "ADAUSDT",
        "signal": "heikin_cont",
        "mom": 0.02,
        "tp_roe": 300,
        "sl_roe": -50,
        "evidence": {"n": 39, "wr_pct": 76.9, "ruin_pct": 1.9},
    },
    {
        "name": "NEAR short_atr 5usdt",
        "source": "phaseUUU",
        "side": "short",
        "symbol": "NEARUSDT",
        "signal": "short_atr_expansion",
        "mom": -0.02,
        "tp_roe": 200,
        "sl_roe": -40,
        "evidence": {"n": 42, "wr_pct": 76.2, "ruin_pct": 4.6},
    },
    {
        "name": "DOT short_adx 5usdt",
        "source": "phaseUUU",
        "side": "short",
        "symbol": "DOTUSDT",
        "signal": "short_adx_trend_dn",
        "mom": -0.02,
        "tp_roe": 150,
        "sl_roe": -35,
        "evidence": {"n": 62, "wr_pct": 67.7, "ruin_pct": 5.2},
    },
    {
        "name": "LINK short_adx 5usdt",
        "source": "phaseUUU",
        "side": "short",
        "symbol": "LINKUSDT",
        "signal": "short_adx_trend_dn",
        "mom": -0.06,
        "tp_roe": 200,
        "sl_roe": -40,
        "evidence": {"n": 35, "wr_pct": 80.0, "ruin_pct": 5.2},
    },
]


def fetch_klines(symbol: str, limit: int = 300) -> tuple[np.ndarray, np.ndarray]:
    url = (
        "https://api.bybit.com/v5/market/kline"
        f"?category=linear&symbol={symbol}&interval=60&limit={limit}"
    )
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    if data.get("retCode") != 0:
        raise RuntimeError(f"{symbol}: {data.get('retMsg')}")
    raw = list(reversed(data["result"]["list"]))
    times = np.array([int(r[0]) for r in raw], dtype=np.int64)
    arr = np.array(
        [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in raw],
        dtype=np.float64,
    )
    return times, arr


def fetch_min_notional(symbols: list[str]) -> dict[str, dict]:
    url = "https://api.bybit.com/v5/market/instruments-info?category=linear&limit=1000"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    rows = {r["symbol"]: r for r in data.get("result", {}).get("list", [])}
    out = {}
    for sym in symbols:
        row = rows.get(sym, {})
        lot = row.get("lotSizeFilter", {})
        lev = row.get("leverageFilter", {})
        out[sym] = {
            "min_notional": float(lot.get("minNotionalValue", 0) or 0),
            "min_order_qty": lot.get("minOrderQty"),
            "qty_step": lot.get("qtyStep"),
            "max_leverage": lev.get("maxLeverage"),
        }
    return out


def last_closed_index(times: np.ndarray) -> int:
    current_hour_open = (int(time.time() * 1000) // 3_600_000) * 3_600_000
    return len(times) - 2 if times[-1] >= current_hour_open else len(times) - 1


def main() -> None:
    symbols = sorted({c["symbol"] for c in DEFAULT_CANDIDATES} | {"BTCUSDT"})
    cache: dict[str, dict] = {}
    times_by_symbol: dict[str, np.ndarray] = {}

    for sym in symbols:
        times, arr = fetch_klines(sym)
        ind = compute_indicators(arr)
        ind = add_extra_features(ind)
        ind = add_obv(ind)
        cache[sym] = ind
        times_by_symbol[sym] = times

    btc_i = last_closed_index(times_by_symbol["BTCUSDT"])
    btc_long = precompute_btc_regime(cache["BTCUSDT"])
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    instrument = fetch_min_notional([s for s in symbols if s != "BTCUSDT"])

    rows = []
    for cand in DEFAULT_CANDIDATES:
        ind = cache[cand["symbol"]]
        i = last_closed_index(times_by_symbol[cand["symbol"]])
        side = cand["side"]
        gate = bool(btc_long[btc_i]) if side == "long" else bool(btc_bear[btc_i])
        sig_fn = (SIGNALS if side == "long" else ALL_SHORT_SIGNALS)[cand["signal"]]
        signal_fire = bool(sig_fn(ind, i))
        mom24 = float(ind["mom24"][i])
        mom_ok = mom24 >= cand["mom"] if side == "long" else mom24 <= cand["mom"]
        row = {
            **cand,
            "candle_utc": datetime.fromtimestamp(times_by_symbol[cand["symbol"]][i] / 1000, tz=timezone.utc).isoformat(),
            "close": float(ind["close"][i]),
            "mom24": mom24,
            "vol_r": float(ind["vol_r"][i]),
            "adx": float(ind["adx"][i]),
            "ema20_gt_ema50": bool(ind["ema20"][i] > ind["ema50"][i]),
            "close_vs_ema20_pct": float((ind["close"][i] / ind["ema20"][i] - 1) * 100),
            "btc_gate": gate,
            "signal_fire": signal_fire,
            "mom_ok": mom_ok,
            "entry": bool(gate and signal_fire and mom_ok),
            "instrument": instrument.get(cand["symbol"], {}),
        }
        rows.append(row)

    payload = {
        "exchange": "bybit_linear_public",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "btc_snapshot": {
            "candle_utc": datetime.fromtimestamp(times_by_symbol["BTCUSDT"][btc_i] / 1000, tz=timezone.utc).isoformat(),
            "close": float(cache["BTCUSDT"]["close"][btc_i]),
            "long_regime": bool(btc_long[btc_i]),
            "bear_regime": bool(btc_bear[btc_i]),
            "mom24": float(cache["BTCUSDT"]["mom24"][btc_i]),
            "adx": float(cache["BTCUSDT"]["adx"][btc_i]),
        },
        "entries": [r for r in rows if r["entry"]],
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"BTC long={payload['btc_snapshot']['long_regime']} bear={payload['btc_snapshot']['bear_regime']} "
          f"candle={payload['btc_snapshot']['candle_utc']}")
    print(f"{'entry':<5} {'side':<5} {'symbol':<9} {'signal':<20} {'mom24':>7} {'vol_r':>6} {'adx':>6} {'TP/SL':>10} name")
    for row in rows:
        print(
            f"{str(row['entry']):<5} {row['side']:<5} {row['symbol']:<9} {row['signal']:<20} "
            f"{row['mom24']*100:>6.2f}% {row['vol_r']:>6.2f} {row['adx']:>6.1f} "
            f"{row['tp_roe']:>3}/{row['sl_roe']:<4} {row['name']}"
        )
    print(f"[saved] {OUT}")


if __name__ == "__main__":
    main()
