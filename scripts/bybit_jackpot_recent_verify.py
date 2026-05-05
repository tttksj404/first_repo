#!/usr/bin/env python3
"""Recent Bybit verification for auto4h jackpot candidates.

Fetches the latest Bybit linear 1h candles and replays the strongest Stage 3
long candidates with the same ROE TP/SL mechanics. No orders are placed.
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
OUT = ROOT / "quant_runtime" / "output" / "bybit_jackpot_recent_verify.json"
LOCAL_HIST_END_MS = int(datetime(2026, 4, 4, 15, tzinfo=timezone.utc).timestamp() * 1000)

sys.path.insert(0, str(ROOT / "scripts"))
from auto4h_signal_library import SIGNALS  # noqa: E402
from auto4h_stage1_matrix import precompute_btc_regime  # noqa: E402
from quant_phase15_signal_library import add_extra_features  # noqa: E402
from quant_phase16_robustness import add_obv  # noqa: E402
from quant_rotation_engine import compute_indicators  # noqa: E402

LEVERAGE = 10
MARGIN = 5.0
COST_RT = 0.0012
FUNDING_8H = 0.0001
SLIPPAGE_BPS = 10
LIQ_ROE = -95.0
SIGNAL_OFF_MIN_ROE = 0.0
COOLDOWN_AFTER_EXIT_H = 12
COOLDOWN_AFTER_LOSS_H = 24

CANDIDATES = [
    ("momentum_obv", "WIFUSDT", 0.04, 300, -25),
    ("heikin_cont", "WIFUSDT", 0.06, 100, -25),
    ("atr_expansion", "SUIUSDT", 0.04, 150, -40),
    ("vol_expansion", "ARBUSDT", 0.04, 50, -20),
    ("atr_expansion", "SUIUSDT", 0.02, 80, -35),
    ("vol_expansion", "DOGEUSDT", 0.04, 80, -30),
    ("donchian_20", "ETHUSDT", 0.02, 50, -25),
    ("donchian_20", "ETHUSDT", 0.02, 50, -35),
    ("heikin_cont", "DOGEUSDT", 0.06, 80, -35),
    ("vol_expansion", "ETHUSDT", 0.02, 50, -25),
    # Kept as a reference because it was originally recommended, but Stage 3 marks it marginal.
    ("adx_trend", "XRPUSDT", 0.04, 30, -30),
]


def fetch_klines(symbol: str, limit: int = 1000) -> tuple[np.ndarray, np.ndarray]:
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


def last_closed_index(times: np.ndarray) -> int:
    current_hour_open = (int(time.time() * 1000) // 3_600_000) * 3_600_000
    return len(times) - 2 if times[-1] >= current_hour_open else len(times) - 1


def simulate(ind: dict, btc_regime: np.ndarray, sig_fn, start_i: int, end_i: int,
             tp_roe: float, sl_roe: float, mom_min: float) -> list[dict]:
    trades = []
    in_pos = False
    entry_px = 0.0
    entry_i = 0
    last_exit_i = -1
    last_loss_i = -1
    slip = SLIPPAGE_BPS / 10000.0

    for i in range(max(start_i, 50), end_i):
        if not in_pos:
            if last_exit_i >= 0 and (i - last_exit_i) < COOLDOWN_AFTER_EXIT_H:
                continue
            if last_loss_i >= 0 and (i - last_loss_i) < COOLDOWN_AFTER_LOSS_H:
                continue
            if i >= len(btc_regime) or not bool(btc_regime[i]):
                continue
            if ind["mom24"][i] < mom_min:
                continue
            if not sig_fn(ind, i):
                continue
            entry_px = ind["close"][i] * (1 + slip)
            entry_i = i
            in_pos = True
            continue

        hi = ind["high"][i]
        lo = ind["low"][i]
        cl = ind["close"][i]
        roe_lo = (lo / entry_px - 1) * LEVERAGE * 100
        roe_hi = (hi / entry_px - 1) * LEVERAGE * 100
        roe_cl = (cl / entry_px - 1) * LEVERAGE * 100
        exit_roe = None
        reason = None
        if roe_lo <= LIQ_ROE:
            exit_roe = -100.0
            reason = "LIQ"
        elif roe_lo <= sl_roe:
            sl_px = entry_px * (1 + sl_roe / 100 / LEVERAGE)
            fill = sl_px * (1 - slip)
            exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
            reason = "SL"
        elif roe_hi >= tp_roe:
            tp_px = entry_px * (1 + tp_roe / 100 / LEVERAGE)
            fill = tp_px * (1 - slip)
            exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
            reason = "TP"
        elif (not sig_fn(ind, i)) and roe_cl > SIGNAL_OFF_MIN_ROE:
            fill = cl * (1 - slip)
            exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
            reason = "SIG_OFF"

        if exit_roe is None:
            continue

        hold_h = i - entry_i
        notional = MARGIN * LEVERAGE
        fee = notional * COST_RT
        funding = notional * FUNDING_8H * (hold_h / 8)
        pnl = -MARGIN - fee if exit_roe <= -100 else MARGIN * (exit_roe / 100) - fee - funding
        trades.append({
            "entry_i": entry_i,
            "exit_i": i,
            "pnl": float(pnl),
            "roe": float(exit_roe),
            "reason": reason,
            "hold_h": int(hold_h),
        })
        in_pos = False
        last_exit_i = i
        if pnl < 0:
            last_loss_i = i
    return trades


def aggregate(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "net": 0.0, "pf": 0.0, "wr": 0.0, "reasons": {}}
    pnl = np.array([t["pnl"] for t in trades], dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    pf = float(wins.sum() / abs(losses.sum())) if losses.size else 99.0
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    return {
        "n": int(len(trades)),
        "net": float(pnl.sum()),
        "pf": pf,
        "wr": float((pnl > 0).mean()),
        "avg": float(pnl.mean()),
        "reasons": reasons,
    }


def main() -> None:
    symbols = sorted({c[1] for c in CANDIDATES} | {"BTCUSDT"})
    cache = {}
    times_by_symbol = {}
    for sym in symbols:
        times, arr = fetch_klines(sym)
        ind = compute_indicators(arr)
        ind = add_extra_features(ind)
        ind = add_obv(ind)
        cache[sym] = ind
        times_by_symbol[sym] = times

    btc_last = last_closed_index(times_by_symbol["BTCUSDT"])
    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    start_full = 220
    end_i = btc_last + 1
    post_start = int(np.searchsorted(times_by_symbol["BTCUSDT"], LOCAL_HIST_END_MS))

    rows = []
    for sig_name, sym, mom, tp, sl in CANDIDATES:
        ind = cache[sym]
        sig_fn = SIGNALS[sig_name]
        full_trades = simulate(ind, btc_regime, sig_fn, start_full, end_i, tp, sl, mom)
        post_trades = simulate(ind, btc_regime, sig_fn, post_start, end_i, tp, sl, mom)
        row = {
            "signal": sig_name,
            "symbol": sym,
            "mom_min": mom,
            "tp_roe": tp,
            "sl_roe": sl,
            "full_recent": aggregate(full_trades),
            "post_local_history": aggregate(post_trades),
        }
        rows.append(row)

    rows.sort(key=lambda r: (-r["post_local_history"]["net"], -r["post_local_history"]["n"]))
    payload = {
        "exchange": "bybit_linear_public",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "config": {
            "leverage": LEVERAGE,
            "margin_usdt": MARGIN,
            "cost_rt": COST_RT,
            "slippage_bps": SLIPPAGE_BPS,
            "local_history_end_utc": datetime.fromtimestamp(LOCAL_HIST_END_MS / 1000, tz=timezone.utc).isoformat(),
        },
        "data_window": {
            "first_utc": datetime.fromtimestamp(times_by_symbol["BTCUSDT"][0] / 1000, tz=timezone.utc).isoformat(),
            "last_closed_utc": datetime.fromtimestamp(times_by_symbol["BTCUSDT"][btc_last] / 1000, tz=timezone.utc).isoformat(),
            "post_start_utc": datetime.fromtimestamp(times_by_symbol["BTCUSDT"][post_start] / 1000, tz=timezone.utc).isoformat(),
        },
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"window {payload['data_window']['first_utc']} -> {payload['data_window']['last_closed_utc']}")
    print(f"post-local start {payload['data_window']['post_start_utc']}")
    print(f"{'symbol':<9} {'signal':<16} {'TP/SL':>9} {'recent n/net/pf':>22} {'post n/net/pf':>22}")
    for r in rows:
        fr = r["full_recent"]
        po = r["post_local_history"]
        print(
            f"{r['symbol']:<9} {r['signal']:<16} {f'+{r['tp_roe']}/{r['sl_roe']}':>9} "
            f"{fr['n']:>3}/${fr['net']:>+6.2f}/{fr['pf']:>5.2f} "
            f"{po['n']:>3}/${po['net']:>+6.2f}/{po['pf']:>5.2f}"
        )
    print(f"[saved] {OUT}")


if __name__ == "__main__":
    main()
