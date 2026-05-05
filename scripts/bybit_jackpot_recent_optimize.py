#!/usr/bin/env python3
"""Small recent-grid optimizer before paper trading.

This intentionally uses a narrow search surface around the only recent survivor:
ETH 1h Donchian-style long breakout. It fetches current Bybit public 1h candles,
splits the post-local-history window into tune/holdout, and rejects configs that
only work in the tuning slice.
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
OUT = ROOT / "quant_runtime" / "output" / "bybit_jackpot_recent_optimize.json"
LOCAL_HIST_END_MS = int(datetime(2026, 4, 4, 15, tzinfo=timezone.utc).timestamp() * 1000)

sys.path.insert(0, str(ROOT / "scripts"))
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


def make_signal(lookback: int, vol_min: float, mom_min: float, adx_min: float,
                require_ema: bool, require_close_above_ema20: bool):
    def signal(ind: dict, i: int) -> bool:
        if i < max(lookback + 1, 50):
            return False
        if ind["close"][i] <= float(np.max(ind["high"][i - lookback:i])):
            return False
        if ind["vol_r"][i] < vol_min:
            return False
        if ind["mom24"][i] < mom_min:
            return False
        if ind["adx"][i] < adx_min:
            return False
        if require_ema and ind["ema20"][i] <= ind["ema50"][i]:
            return False
        if require_close_above_ema20 and ind["close"][i] <= ind["ema20"][i]:
            return False
        return True
    return signal


def simulate(ind: dict, btc_regime: np.ndarray, sig_fn, start_i: int, end_i: int,
             tp_roe: float, sl_roe: float, cooldown_exit: int, cooldown_loss: int,
             exit_on_signal_off: bool) -> list[dict]:
    trades = []
    in_pos = False
    entry_px = 0.0
    entry_i = 0
    last_exit_i = -1
    last_loss_i = -1
    slip = SLIPPAGE_BPS / 10000.0

    for i in range(max(start_i, 50), end_i):
        if not in_pos:
            if last_exit_i >= 0 and (i - last_exit_i) < cooldown_exit:
                continue
            if last_loss_i >= 0 and (i - last_loss_i) < cooldown_loss:
                continue
            if i >= len(btc_regime) or not bool(btc_regime[i]):
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
        elif exit_on_signal_off and (not sig_fn(ind, i)) and roe_cl > SIGNAL_OFF_MIN_ROE:
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
            "entry_i": int(entry_i),
            "exit_i": int(i),
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
        return {"n": 0, "net": 0.0, "pf": 0.0, "wr": 0.0, "avg": 0.0, "max_loss": 0.0}
    pnl = np.array([t["pnl"] for t in trades], dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    pf = float(wins.sum() / abs(losses.sum())) if losses.size else 99.0
    return {
        "n": int(len(trades)),
        "net": float(pnl.sum()),
        "pf": pf,
        "wr": float((pnl > 0).mean()),
        "avg": float(pnl.mean()),
        "max_loss": float(pnl.min()),
    }


def score_row(row: dict) -> tuple:
    tune = row["tune"]
    hold = row["holdout"]
    full = row["full"]
    passes = (
        tune["n"] >= 3
        and hold["n"] >= 2
        and full["n"] >= 7
        and tune["net"] > 0
        and hold["net"] > 0
        and full["pf"] >= 1.2
    )
    row["passes"] = passes
    return (
        0 if passes else 1,
        -hold["net"],
        -full["net"],
        abs(tune["pf"] - hold["pf"]),
        -full["n"],
    )


def main() -> None:
    times_btc, arr_btc = fetch_klines("BTCUSDT")
    times_eth, arr_eth = fetch_klines("ETHUSDT")
    btc = add_obv(add_extra_features(compute_indicators(arr_btc)))
    eth = add_obv(add_extra_features(compute_indicators(arr_eth)))
    btc_regime = precompute_btc_regime(btc)

    end_i = min(last_closed_index(times_btc), last_closed_index(times_eth)) + 1
    post_start = int(np.searchsorted(times_eth, LOCAL_HIST_END_MS))
    split_i = post_start + int((end_i - post_start) * 0.67)
    folds = {
        "tune": (post_start, split_i),
        "holdout": (split_i, end_i),
        "full": (post_start, end_i),
    }

    rows = []
    for lookback in [10, 15, 20, 25, 30]:
        for vol_min in [0.6, 0.8, 1.0, 1.2, 1.5]:
            for mom_min in [0.0, 0.01, 0.02, 0.03]:
                for adx_min in [0, 15, 20, 25]:
                    for require_ema in [False, True]:
                        for require_close_above_ema20 in [False, True]:
                            for tp in [30, 40, 50, 60, 80]:
                                for sl in [-20, -25, -30, -35, -40]:
                                    for cooldown_loss in [12, 24]:
                                        sig = make_signal(
                                            lookback, vol_min, mom_min, adx_min,
                                            require_ema, require_close_above_ema20,
                                        )
                                        cfg = {
                                            "symbol": "ETHUSDT",
                                            "family": "donchian_param",
                                            "lookback": lookback,
                                            "vol_min": vol_min,
                                            "mom_min": mom_min,
                                            "adx_min": adx_min,
                                            "require_ema": require_ema,
                                            "require_close_above_ema20": require_close_above_ema20,
                                            "tp_roe": tp,
                                            "sl_roe": sl,
                                            "cooldown_exit": 12,
                                            "cooldown_loss": cooldown_loss,
                                            "exit_on_signal_off": True,
                                        }
                                        row = dict(cfg)
                                        for name, (s_i, e_i) in folds.items():
                                            trades = simulate(
                                                eth, btc_regime, sig, s_i, e_i, tp, sl,
                                                cfg["cooldown_exit"], cooldown_loss, cfg["exit_on_signal_off"],
                                            )
                                            row[name] = aggregate(trades)
                                        score_row(row)
                                        rows.append(row)

    rows.sort(key=score_row)
    passers = [r for r in rows if r["passes"]]
    baseline = next(
        (
            r for r in rows
            if r["lookback"] == 20
            and r["vol_min"] == 1.5
            and r["mom_min"] == 0.02
            and r["adx_min"] == 0
            and r["require_ema"] is False
            and r["require_close_above_ema20"] is False
            and r["tp_roe"] == 50
            and r["sl_roe"] == -35
            and r["cooldown_loss"] == 24
        ),
        None,
    )
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
        "window": {
            "post_start_utc": datetime.fromtimestamp(times_eth[post_start] / 1000, tz=timezone.utc).isoformat(),
            "tune_end_utc": datetime.fromtimestamp(times_eth[split_i] / 1000, tz=timezone.utc).isoformat(),
            "last_closed_utc": datetime.fromtimestamp(times_eth[end_i - 1] / 1000, tz=timezone.utc).isoformat(),
        },
        "n_tested": len(rows),
        "n_pass": len(passers),
        "baseline": baseline,
        "top": rows[:25],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"tested={len(rows)} pass={len(passers)}")
    print(f"window {payload['window']}")
    if baseline:
        print(
            "baseline "
            f"lb={baseline['lookback']} vol={baseline['vol_min']} mom={baseline['mom_min']} "
            f"adx={baseline['adx_min']} TP/SL=+{baseline['tp_roe']}/{baseline['sl_roe']} "
            f"full={baseline['full']['n']}/${baseline['full']['net']:+.2f}/{baseline['full']['pf']:.2f} "
            f"hold={baseline['holdout']['n']}/${baseline['holdout']['net']:+.2f}/{baseline['holdout']['pf']:.2f}"
        )
    print(f"{'pass':<5} {'lb':>2} {'vol':>4} {'mom':>4} {'adx':>3} {'ema':>3} {'c>e':>3} {'TP/SL':>8} {'tune':>16} {'hold':>16} {'full':>16}")
    for r in rows[:12]:
        print(
            f"{str(r['passes']):<5} {r['lookback']:>2} {r['vol_min']:>4.1f} "
            f"{r['mom_min']*100:>3.0f}% {r['adx_min']:>3.0f} "
            f"{str(r['require_ema'])[0]:>3} {str(r['require_close_above_ema20'])[0]:>3} "
            f"{f'+{r['tp_roe']}/{r['sl_roe']}':>8} "
            f"{r['tune']['n']:>2}/${r['tune']['net']:>+5.2f}/{r['tune']['pf']:>4.1f} "
            f"{r['holdout']['n']:>2}/${r['holdout']['net']:>+5.2f}/{r['holdout']['pf']:>4.1f} "
            f"{r['full']['n']:>2}/${r['full']['net']:>+5.2f}/{r['full']['pf']:>4.1f}"
        )
    print(f"[saved] {OUT}")


if __name__ == "__main__":
    main()
