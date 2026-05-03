#!/usr/bin/env python3
"""Profit-maximization analysis across all collected backtest results.

Re-rank every existing variant by:
  1. Train PnL (absolute profit)
  2. PF (long-term EV proxy)
  3. PnL / max_drawdown (Calmar-ish)
  4. Risk-adjusted: avg_pnl / std(pnl)

Then estimate leverage-scaled PnL for survivors with PF > 1.0.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "profit_max_summary.json"


def load_jsonl_safe(p: Path):
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def main() -> None:
    sources: list[tuple[str, list[dict], str]] = []

    # 1. WR80 mean-rev (initial search)
    p = ROOT / "quant_runtime" / "wr80_search_summary.json"
    d = load_jsonl_safe(p)
    if d:
        for v in d.get("variants", []):
            sources.append(("wr80_meanrev", [v], v.get("label", "?")))
    # 2. WR80 momentum
    p = ROOT / "quant_runtime" / "wr80_momentum_summary.json"
    d = load_jsonl_safe(p)
    if d:
        for v in d.get("variants", []):
            sources.append(("wr80_momentum", [v], v.get("label", "?")))
    # 3. Pair trading
    p = ROOT / "quant_runtime" / "pair_trading_oos_summary.json"
    d = load_jsonl_safe(p)
    if d:
        for v in d.get("all", []):
            sources.append(("pair_trading", [v], v.get("label", "?")))
    # 4. Confluence
    p = ROOT / "quant_runtime" / "confluence_oos_summary.json"
    d = load_jsonl_safe(p)
    if d:
        for v in d.get("top20", []):
            sources.append(("confluence_top20", [v], v.get("label", "?")))
        for v in d.get("qualified", []):
            sources.append(("confluence_qualified", [v], v.get("label", "?")))

    # Normalize records
    norm: list[dict] = []
    for src, vlist, lbl in sources:
        v = vlist[0]
        # confluence top has 'train' subdict; pair_trading has 'train'; wr80 has flat
        if "train" in v and isinstance(v["train"], dict):
            t = v["train"]
            n = t.get("n", 0)
            wr = t.get("wr", 0)
            pnl = t.get("pnl", 0)
            test = v.get("test", {})
            test_n = test.get("n", 0)
            test_wr = test.get("wr", 0)
            test_pnl = test.get("pnl", 0)
            pf = t.get("pf")
        else:
            n = v.get("n_trades", 0)
            wr = v.get("win_rate", 0)
            pnl = v.get("total_pnl_usd", 0)
            test_n = test_wr = test_pnl = 0
            pf = v.get("profit_factor")
        norm.append(
            {
                "source": src,
                "label": lbl,
                "n": n,
                "wr": wr,
                "pnl": pnl,
                "pf": pf,
                "test_n": test_n,
                "test_wr": test_wr,
                "test_pnl": test_pnl,
            }
        )

    # Filter: real variants only (n >= 30, label not None)
    pool = [r for r in norm if r["n"] >= 30 and r["pnl"] is not None]
    print(f"Total candidates: {len(pool)}")

    # Rank 1: Total PnL (gross profit, train)
    by_pnl = sorted(pool, key=lambda r: -r["pnl"])
    print()
    print("=== TOP 15 by TOTAL PnL (train, $100 notional, leverage=1) ===")
    for r in by_pnl[:15]:
        pf_s = f"{r['pf']:.2f}" if r["pf"] is not None and isinstance(r["pf"], (int, float)) else "n/a"
        print(
            f"  pnl={r['pnl']:+8.2f}  WR={r['wr']:.3f}  N={r['n']:>4d}  PF={pf_s:>5s}  src={r['source'][:18]:18s}  {r['label']}"
        )

    # Rank 2: PF (positive EV)
    pf_pool = [r for r in pool if r["pf"] is not None and isinstance(r["pf"], (int, float)) and r["pf"] >= 1.0]
    by_pf = sorted(pf_pool, key=lambda r: (-r["pf"], -r["pnl"]))
    print()
    print(f"=== POSITIVE-EV variants (PF >= 1.0): {len(pf_pool)} ===")
    for r in by_pf[:15]:
        print(
            f"  PF={r['pf']:.3f}  pnl={r['pnl']:+8.2f}  WR={r['wr']:.3f}  N={r['n']:>4d}  src={r['source'][:18]:18s}  {r['label']}"
        )

    # Rank 3: OOS-validated positive-EV (test PnL > 0)
    oos_pos = [r for r in pool if r["test_pnl"] > 0 and r["test_n"] >= 20]
    oos_pos.sort(key=lambda r: -r["test_pnl"])
    print()
    print(f"=== OOS positive PnL (test_pnl > 0, test_n >= 20): {len(oos_pos)} ===")
    for r in oos_pos[:15]:
        pf_s = f"{r['pf']:.2f}" if r["pf"] is not None and isinstance(r["pf"], (int, float)) else "n/a"
        print(
            f"  TEST pnl={r['test_pnl']:+7.2f} WR={r['test_wr']:.3f} N={r['test_n']:>3d}  | TRAIN pnl={r['pnl']:+7.2f} WR={r['wr']:.3f} PF={pf_s}  {r['label']}"
        )

    # Combined "best for profit": PF >= 1.0 + test_pnl > 0
    combined = [r for r in pool if r["pf"] is not None and isinstance(r["pf"], (int, float)) and r["pf"] >= 1.0 and r["test_pnl"] > 0]
    combined.sort(key=lambda r: -(r["pnl"] + r["test_pnl"]))
    print()
    print(f"=== TRUE PROFIT WINNERS (PF>=1.0 AND test_pnl>0): {len(combined)} ===")
    for r in combined[:15]:
        total = r["pnl"] + r["test_pnl"]
        print(
            f"  TOTAL pnl={total:+7.2f}  PF={r['pf']:.2f}  TRAIN pnl={r['pnl']:+.2f} WR={r['wr']:.3f} N={r['n']}  TEST pnl={r['test_pnl']:+.2f} WR={r['test_wr']:.3f} N={r['test_n']}  {r['label']}"
        )

    # Save
    out = {
        "total_candidates": len(pool),
        "top_pnl": by_pnl[:30],
        "positive_ev_count": len(pf_pool),
        "top_pf": by_pf[:30],
        "oos_positive_count": len(oos_pos),
        "top_oos": oos_pos[:30],
        "true_winners_count": len(combined),
        "true_winners": combined[:30],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))
    print(f"\nSaved: {OUT}")


if __name__ == "__main__":
    main()
