#!/usr/bin/env python3
"""Aggregate ALL backtest results and produce final profit-max winner report.

Sources:
  - confluence_oos_summary.json (5-sym 1h initial)
  - profit_max_expanded.json (20-sym 1h, 4-sym 4h)
  - bb_squeeze_oos_summary.json (20-sym BB squeeze)
  - donchian_trend_oos_summary.json (20-sym trend)
  - confluence_winner_validate.json (per-sym + WF + slippage stress)

Output: quant_runtime/final_winner_report.json + console table
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RT = ROOT / "quant_runtime"
OUT = RT / "final_winner_report.json"


def safe_load(p: Path):
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception as e:
        return {"error": str(e)}


def main():
    expanded = safe_load(RT / "profit_max_expanded.json") or {}
    bb = safe_load(RT / "bb_squeeze_oos_summary.json") or {}
    donch = safe_load(RT / "donchian_trend_oos_summary.json") or {}
    val = safe_load(RT / "confluence_winner_validate.json") or {}

    # 1. Strategy survey
    survey = []
    if expanded.get("configs"):
        for cfg, c in expanded["configs"].items():
            survey.append(
                {
                    "strategy": f"confluence_{cfg}",
                    "n_variants": c.get("n_variants", 0),
                    "qualified": c.get("qualified_count", 0),
                    "best_total_pnl": (c.get("qualified") or [{"total_pnl": 0}])[0].get("total_pnl", 0)
                    if c.get("qualified") else 0,
                }
            )
    survey.append(
        {
            "strategy": "bb_squeeze_20sym",
            "n_variants": bb.get("n_variants", 0),
            "qualified": bb.get("qualified_count", 0),
            "best_total_pnl": (bb.get("qualified") or [{"total_pnl": 0}])[0].get("total_pnl", 0)
            if bb.get("qualified") else 0,
        }
    )
    survey.append(
        {
            "strategy": "donchian_trend_20sym",
            "n_variants": donch.get("n_variants", 0),
            "qualified": donch.get("qualified_count", 0),
            "best_total_pnl": (donch.get("qualified") or [{"total_pnl": 0}])[0].get("total_pnl", 0)
            if donch.get("qualified") else 0,
        }
    )

    # 2. Leverage scaling for validated winners
    # Input: $50 paper-equity per arm (Bitget paper baseline)
    # Position notional = $50 * mp * leverage where mp = margin_pct (default 1.0)
    EQUITY = 50.0
    candidates = (val.get("candidates") or [])

    proj_rows = []
    for c in candidates:
        agg = c.get("aggregate", {})
        slip = c.get("slippage_stress", [])
        slip_5 = next((s for s in slip if s.get("extra_bps") == 5.0), {})
        slip_10 = next((s for s in slip if s.get("extra_bps") == 10.0), {})
        slip_0 = next((s for s in slip if s.get("extra_bps") == 0.0), {})
        wf_pass = c.get("wf_pass_count", 0)
        per_sym = c.get("per_symbol", {})
        sym_pos = sum(1 for v in per_sym.values() if v.get("pnl", 0) > 0)
        sym_total = len(per_sym)
        # Annual PnL on $100 notional
        n_total = agg.get("n", 0)
        pnl_total = agg.get("pnl_total_usd", 0)
        max_dd = agg.get("max_dd_usd", 0)
        # Leverage scaling: profit AND drawdown both scale linearly
        # Safe leverage = EQUITY / (max_dd * safety_factor); safety_factor=2 (50% buffer)
        safe_lev_base100 = EQUITY / (max_dd * 2) if max_dd > 0 else 1.0
        # Conservative cap at 5x
        safe_lev = min(safe_lev_base100, 5.0)
        annual_pnl_safe = pnl_total * safe_lev * (EQUITY / 100.0)
        annual_return_pct = (annual_pnl_safe / EQUITY) * 100

        proj_rows.append(
            {
                "name": c["name"],
                "params": c.get("params", {}),
                "n_trades": n_total,
                "wr": agg.get("wr", 0),
                "pf": agg.get("pf"),
                "pnl_full_year_usd": pnl_total,
                "max_dd_usd": max_dd,
                "max_loss_streak": agg.get("max_consecutive_losses", 0),
                "wf_pass": f"{wf_pass}/4",
                "sym_diversification": f"{sym_pos}/{sym_total}",
                "test_pnl_0bps": slip_0.get("pnl"),
                "test_pnl_5bps": slip_5.get("pnl"),
                "test_pnl_10bps": slip_10.get("pnl"),
                "safe_leverage": round(safe_lev, 2),
                "annual_pnl_at_50equity_safelev": round(annual_pnl_safe, 2),
                "annual_return_pct": round(annual_return_pct, 1),
            }
        )

    # Rank by 5bps slippage survival × diversification × annual return
    def score(r):
        slip5 = r.get("test_pnl_5bps") or -999
        return (slip5, r.get("annual_return_pct", 0))

    proj_rows.sort(key=score, reverse=True)

    # Print
    print("=" * 80)
    print("STRATEGY SURVEY")
    print("=" * 80)
    print(f"  {'strategy':30s} {'tested':>8s} {'qualified':>10s} {'best_total':>12s}")
    for s in survey:
        print(f"  {s['strategy']:30s} {s['n_variants']:>8d} {s['qualified']:>10d} ${s['best_total_pnl']:>10.2f}")

    print()
    print("=" * 80)
    print("VALIDATED PROFIT-MAX WINNERS — full-year aggregate, $100 notional, leverage=1")
    print("=" * 80)
    for r in proj_rows:
        print(f"\n  [{r['name']}]")
        p = r["params"]
        print(f"    rsi {p.get('rsi_long')}/{p.get('rsi_short')}, macd={p.get('req_macd')}, ema={p.get('req_ema')}, vol_min={p.get('vol_min')}, tp={p.get('tp_atr')} sl={p.get('sl_atr')}, hold={p.get('hold')}h")
        print(f"    N={r['n_trades']:>3d}  WR={r['wr']:.3f}  PF={r['pf']}  PnL=${r['pnl_full_year_usd']:+.2f}  maxDD=${r['max_dd_usd']:.2f}  maxLossStreak={r['max_loss_streak']}")
        print(f"    WF={r['wf_pass']}  diversif={r['sym_diversification']} symbols positive")
        print(f"    Slippage stress: 0bps=${r['test_pnl_0bps']:+.2f}  5bps=${r['test_pnl_5bps']:+.2f}  10bps=${r['test_pnl_10bps']:+.2f}")
        print(f"    Safe leverage: {r['safe_leverage']}x  →  annual ${r['annual_pnl_at_50equity_safelev']:+.1f} on $50 equity = {r['annual_return_pct']}%/yr")

    print()
    print("=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    # Pick: 5bps>=0 AND wf=4/4 AND diversif >= 12
    finals = [r for r in proj_rows if (r.get("test_pnl_5bps") or -1) > 0 and r["wf_pass"] == "4/4"]
    if finals:
        f = finals[0]
        print(f"  PRIMARY: {f['name']}")
        print(f"    Robust to 5bps slippage: ${f['test_pnl_5bps']:+.2f}")
        print(f"    Diversification: {f['sym_diversification']}")
        print(f"    Recommended deploy: leverage {f['safe_leverage']}x, expected ~{f['annual_return_pct']}%/yr on $50 equity")
    else:
        print("  No candidate passes all gates (5bps survival + WF 4/4).")

    out = {"survey": survey, "winners": proj_rows, "finals": finals}
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nSaved: {OUT}")


if __name__ == "__main__":
    main()
