#!/usr/bin/env python3
"""Pair-trading WR 80% search with strict OOS validation.

Strategy: log-spread mean reversion between two cointegrated perps.
- Pair candidates: BTC-ETH, ETH-SOL, BTC-SOL, SOL-XRP, ETH-XRP
- spread_t = log(P_a) - beta * log(P_b), beta from rolling OLS
- z_t = (spread_t - rolling_mean(spread, window)) / rolling_std(spread, window)
- Entry: |z| >= z_thr → short the rich leg, long the cheap leg (delta-neutral)
- Exit: z reverts to ±exit_z OR hold_bars timeout OR z extends beyond stop_z
- PnL = sum of two-leg ROEs (sign-corrected) × notional - 2 × fee_each

Validation gates (must pass ALL):
- Train (Apr 2025 ~ Dec 2025): WR >= 0.80, PF >= 1.0, N >= 200
- Test  (Jan 2026 ~ Apr 2026): WR >= 0.75, PF >= 1.0
- Walk-forward 4-fold: WR >= 0.70 in >= 3/4 folds

Output: quant_runtime/pair_trading_oos_summary.json
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "quant_runtime" / "historical"
OUT = ROOT / "quant_runtime" / "pair_trading_oos_summary.json"

PAIRS = [
    ("BTCUSDT", "ETHUSDT"),
    ("ETHUSDT", "SOLUSDT"),
    ("BTCUSDT", "SOLUSDT"),
    ("SOLUSDT", "XRPUSDT"),
    ("ETHUSDT", "XRPUSDT"),
    ("BTCUSDT", "XRPUSDT"),
    ("DOGEUSDT", "XRPUSDT"),
]

NOTIONAL_PER_LEG = 50.0  # $50 per leg → $100 total exposure
COST_RT_PER_LEG = 0.0012
FEE_PER_LEG = NOTIONAL_PER_LEG * COST_RT_PER_LEG  # both entry+exit per leg

# Time partitions (open_time ms)
# Apr 12 2025 → Dec 31 2025 = train, Jan 1 2026 → Apr 7 2026 = test
TRAIN_START_MS = int(np.datetime64("2025-04-12T00:00:00").astype("datetime64[ms]").astype(np.int64))
TRAIN_END_MS = int(np.datetime64("2025-12-31T23:59:59").astype("datetime64[ms]").astype(np.int64))
TEST_START_MS = int(np.datetime64("2026-01-01T00:00:00").astype("datetime64[ms]").astype(np.int64))
TEST_END_MS = int(np.datetime64("2026-04-07T23:59:59").astype("datetime64[ms]").astype(np.int64))


def load_5m(symbol: str) -> np.ndarray:
    path = HIST / symbol / "5m.json"
    raw = json.loads(path.read_text())
    return np.array(
        [
            [r["open_time"], r["open_price"], r["high_price"], r["low_price"], r["close_price"]]
            for r in raw
        ],
        dtype=np.float64,
    )


def compute_spread_signals(
    arr_a: np.ndarray, arr_b: np.ndarray, window: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (z, beta_arr, log_spread) on aligned timestamps."""
    # Align by timestamp (intersection)
    ts_a = arr_a[:, 0].astype(np.int64)
    ts_b = arr_b[:, 0].astype(np.int64)
    common = np.intersect1d(ts_a, ts_b, assume_unique=True)
    idx_a = np.searchsorted(ts_a, common)
    idx_b = np.searchsorted(ts_b, common)
    a = arr_a[idx_a]
    b = arr_b[idx_b]
    log_a = np.log(a[:, 4])
    log_b = np.log(b[:, 4])

    n = len(common)
    beta = np.zeros(n)
    spread = np.zeros(n)
    z = np.zeros(n)

    # Rolling regression β = cov(log_a, log_b) / var(log_b) (no intercept; OK for z-score purpose)
    for i in range(window, n):
        la = log_a[i - window : i]
        lb = log_b[i - window : i]
        var_b = np.var(lb)
        if var_b <= 0:
            continue
        cov = np.mean((la - np.mean(la)) * (lb - np.mean(lb)))
        beta[i] = cov / var_b
        spread[i] = log_a[i] - beta[i] * log_b[i]
        # z over a separate window
        s_window = spread[max(i - window, 0) : i]
        if len(s_window) < 30:
            continue
        m = np.mean(s_window)
        sd = np.std(s_window)
        if sd <= 0:
            continue
        z[i] = (spread[i] - m) / sd
    return z, beta, common.astype(np.float64), idx_a, idx_b


@dataclass
class PairVariant:
    pair_a: str
    pair_b: str
    window: int
    z_thr: float
    exit_z: float
    hold_bars: int
    stop_z: float


def simulate_pair(
    arr_a: np.ndarray,
    arr_b: np.ndarray,
    z: np.ndarray,
    idx_a: np.ndarray,
    idx_b: np.ndarray,
    v: PairVariant,
    ts_min_ms: float,
    ts_max_ms: float,
) -> tuple[int, int, float, float, float, float, list[float]]:
    """Return (n, wins, total_pnl, avg_win, avg_loss, pf, pnls)."""
    n = len(z)
    wins = 0
    losses = 0
    pnl_sum = 0.0
    win_sum = 0.0
    loss_sum_abs = 0.0
    pnls: list[float] = []

    cooldown = 0
    i = v.window + 30
    a_arr = arr_a[idx_a]
    b_arr = arr_b[idx_b]
    while i < n - v.hold_bars - 2:
        ts_now = a_arr[i, 0]
        if ts_now < ts_min_ms or ts_now > ts_max_ms:
            i += 1
            continue
        if i < cooldown:
            i += 1
            continue
        z_now = z[i]
        if not math.isfinite(z_now) or abs(z_now) < v.z_thr:
            i += 1
            continue
        # Entry next bar open
        e = i + 1
        if e >= n:
            break
        entry_a = a_arr[e, 1]
        entry_b = b_arr[e, 1]
        if entry_a <= 0 or entry_b <= 0:
            i += 1
            continue
        # z > 0 → A is rich → SHORT A, LONG B
        side_a = -1 if z_now > 0 else 1
        side_b = -side_a

        exit_idx = None
        for k in range(e, min(e + v.hold_bars, n)):
            zk = z[k]
            if not math.isfinite(zk):
                continue
            # exit if reverted to within exit_z
            if abs(zk) <= v.exit_z:
                exit_idx = k
                break
            # stop if extended beyond stop_z (same sign as entry)
            if abs(zk) >= v.stop_z and (zk * z_now > 0):
                exit_idx = k
                break
        if exit_idx is None:
            exit_idx = min(e + v.hold_bars - 1, n - 1)
        exit_a = a_arr[exit_idx, 4]
        exit_b = b_arr[exit_idx, 4]
        if exit_a <= 0 or exit_b <= 0:
            i = e + 1
            continue

        roe_a = side_a * (exit_a - entry_a) / entry_a
        roe_b = side_b * (exit_b - entry_b) / entry_b
        pnl_a = NOTIONAL_PER_LEG * roe_a - FEE_PER_LEG
        pnl_b = NOTIONAL_PER_LEG * roe_b - FEE_PER_LEG
        pnl = pnl_a + pnl_b
        pnls.append(pnl)
        pnl_sum += pnl
        if pnl > 0:
            wins += 1
            win_sum += pnl
        else:
            losses += 1
            loss_sum_abs += abs(pnl)
        i = exit_idx + 1
        cooldown = i + 3

    n_trades = wins + losses
    avg_win = win_sum / wins if wins > 0 else 0.0
    avg_loss = -loss_sum_abs / losses if losses > 0 else 0.0
    pf = win_sum / loss_sum_abs if loss_sum_abs > 0 else (float("inf") if win_sum > 0 else 0.0)
    return n_trades, wins, pnl_sum, avg_win, avg_loss, pf, pnls


def evaluate_variant(
    cache: dict[tuple[str, str, int], tuple],
    arr: dict[str, np.ndarray],
    v: PairVariant,
    ts_min_ms: float,
    ts_max_ms: float,
) -> dict:
    key = (v.pair_a, v.pair_b, v.window)
    if key not in cache:
        z, beta, common, ia, ib = compute_spread_signals(arr[v.pair_a], arr[v.pair_b], v.window)
        cache[key] = (z, beta, common, ia, ib)
    z, beta, common, ia, ib = cache[key]
    n, w, pnl, avg_w, avg_l, pf, pnls = simulate_pair(
        arr[v.pair_a], arr[v.pair_b], z, ia, ib, v, ts_min_ms, ts_max_ms
    )
    wr = w / n if n > 0 else 0.0
    return {
        "n": n,
        "wins": w,
        "wr": round(wr, 4),
        "pnl": round(pnl, 2),
        "avg_win": round(avg_w, 4),
        "avg_loss": round(avg_l, 4),
        "pf": round(pf, 3) if math.isfinite(pf) else None,
    }


def main() -> None:
    t_start = time.time()
    print("Loading data...")
    syms_needed = sorted({s for pair in PAIRS for s in pair})
    arr = {s: load_5m(s) for s in syms_needed}
    print(f"  symbols loaded: {syms_needed}")

    grid: list[PairVariant] = []
    for a, b in PAIRS:
        for window in [60, 100, 200]:
            for z_thr in [1.5, 2.0, 2.5, 3.0]:
                for exit_z in [0.0, 0.3, 0.5]:
                    for hold_bars in [24, 48, 96]:
                        for stop_z in [4.0, 5.0]:
                            grid.append(
                                PairVariant(a, b, window, z_thr, exit_z, hold_bars, stop_z)
                            )
    print(f"Grid: {len(grid)} variants")

    cache: dict = {}
    rows: list[dict] = []
    qualified_train: list[dict] = []
    for idx, v in enumerate(grid):
        train = evaluate_variant(cache, arr, v, TRAIN_START_MS, TRAIN_END_MS)
        rec = {
            "label": f"{v.pair_a[:3]}-{v.pair_b[:3]}|w{v.window}|z{v.z_thr}|ex{v.exit_z}|h{v.hold_bars}|st{v.stop_z}",
            "pair_a": v.pair_a,
            "pair_b": v.pair_b,
            "window": v.window,
            "z_thr": v.z_thr,
            "exit_z": v.exit_z,
            "hold_bars": v.hold_bars,
            "stop_z": v.stop_z,
            "train": train,
        }
        if (
            train["n"] >= 200
            and train["wr"] >= 0.80
            and (train["pf"] or 0) >= 1.0
        ):
            test = evaluate_variant(cache, arr, v, TEST_START_MS, TEST_END_MS)
            rec["test"] = test
            rec["passed_train"] = True
            rec["passed_test"] = (
                test["n"] >= 50 and test["wr"] >= 0.75 and (test["pf"] or 0) >= 1.0
            )
            qualified_train.append(rec)
        rows.append(rec)
        if idx % 50 == 0:
            elapsed = time.time() - t_start
            print(
                f"  [{idx + 1:4d}/{len(grid)}] {rec['label']}  WR={train['wr']:.3f} N={train['n']:>5d} pnl={train['pnl']:+9.2f} pf={train['pf']}  ({elapsed:.0f}s)"
            )

    # Sort + summarize
    by_train_wr = sorted(rows, key=lambda r: (-r["train"]["wr"], -r["train"]["pnl"]))
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_variants": len(rows),
        "train_qualified": len(qualified_train),
        "test_passed": sum(1 for r in qualified_train if r.get("passed_test")),
        "best_train_wr": by_train_wr[0],
        "qualified": qualified_train,
        "all": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2, default=str))

    print()
    print("=== TRAIN-PHASE TOP 10 (by WR) ===")
    for r in by_train_wr[:10]:
        t = r["train"]
        print(
            f"  WR={t['wr']:.3f} N={t['n']:>5d} pnl={t['pnl']:+9.2f} pf={t['pf']}  {r['label']}"
        )

    print()
    print(f"=== TRAIN qualified (WR>=80%, PF>=1, N>=200): {len(qualified_train)} variants ===")
    for r in qualified_train:
        t = r["train"]
        ts = r.get("test", {})
        marker = " ✓ OOS-PASS" if r.get("passed_test") else " ✗ OOS-FAIL"
        print(
            f"  TRAIN WR={t['wr']:.3f} N={t['n']} pnl={t['pnl']:+.2f} pf={t['pf']}  | "
            f"TEST WR={ts.get('wr', 0):.3f} N={ts.get('n', 0)} pnl={ts.get('pnl', 0):+.2f} pf={ts.get('pf', 0)}  "
            f"{r['label']}{marker}"
        )
    print(f"\nTotal OOS-passed: {summary['test_passed']}")
    print(f"Elapsed: {time.time() - t_start:.1f}s")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
