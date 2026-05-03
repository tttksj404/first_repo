#!/usr/bin/env python3
"""Strategy-matrix offline replay.

Extends `quant_replay_arms_offline.py` to sweep multiple strategy dimensions
simultaneously in a single pass through the cached cycle data:

  - 8 STRATEGY_PROFILE leverage levels (proxied by max_leverage value)
  - cross-coin gate ON / OFF
  - 3 universes (full / majors / alts)
  - 2 size_multipliers (normal=1.0 / strong=1.35)

For each variant emits a row to `quant_runtime/strategy_matrix_summary.json`
ranked by composite score (net_pnl × 10 + selectivity bonuses).

Caveat: in-sample (EV table built from same window). Use ranking, not
absolute PnL. Profile differences only affect leverage in this replay since
the symbol_profile filter is intentionally bypassed (every (cycle, symbol)
treated as a hypothetical entry).

Usage:
  scripts/quant_python.sh scripts/quant_replay_strategy_matrix.py
"""

from __future__ import annotations

import json
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quant_binance.cross_coin_scorer import (  # type: ignore[import-not-found]
    CycleSnapshot,
    SymbolState,
    compute_state,
    load_ev_table,
    score_symbol,
)
from scripts.quant_paper50_counterfactual import (  # type: ignore[import-not-found]
    fetch_klines_cached,
    _parse_timestamp,
    _safe_float,
)
from quant_binance.execution.client_factory import (  # type: ignore[import-not-found]
    build_exchange_rest_client,
)


SHADOW_ROOT = ROOT / "quant_runtime_paper50" / "bitget_external_alpha_shadow"
EV_TABLE_PATH = ROOT / "quant_runtime_paper50" / "cross_coin_ev_table.json"
KLINE_CACHE = ROOT / "quant_runtime_paper50" / "cache" / "klines"

UNIVERSES = {
    "full": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "PEPEUSDT", "XRPUSDT"],
    "majors": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "alts": ["PEPEUSDT", "DOGEUSDT", "XRPUSDT", "SOLUSDT"],
}

# 8 STRATEGY_PROFILE proxy via max_leverage (exact mapping from settings.py via Explore)
PROFILE_LEVERAGE = {
    "conservative":                       2.0,
    "balanced":                           10.0,
    "active":                             10.0,
    "live-aggressive":                    12.0,
    "live-ultra-aggressive":              15.0,
    "autoresearch-bearish-short-bias":    10.0,
    "autoresearch-futures-active":        10.0,
    "autoresearch-leverage-strong":       15.0,  # +profile-specific override
}

SIZE_VARIANTS = {
    "normal": 1.0,
    "strong": 1.35,
}

NOTIONAL_USD = 10.0
COST_BPS_RT = 16.0
FORWARD_MIN = 60


def _load_cycles_per_symbol() -> dict[str, list[CycleSnapshot]]:
    cycles: dict[str, list[CycleSnapshot]] = defaultdict(list)
    cycle_dirs = sorted(SHADOW_ROOT.glob("cycle_*"))
    for cdir in cycle_dirs:
        mfile = cdir / "metrics.json"
        if not mfile.exists():
            continue
        try:
            payload = json.loads(mfile.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for row in payload.get("rows") or []:
            sym = (row.get("symbol") or "").upper()
            if sym not in UNIVERSES["full"]:
                continue
            ts_str = row.get("timestamp")
            if not ts_str:
                continue
            try:
                ts_ms = int(_parse_timestamp(ts_str).timestamp() * 1000)
            except Exception:
                continue
            cycles[sym].append(
                CycleSnapshot(
                    symbol=sym, ts_ms=ts_ms,
                    open_interest=_safe_float(row.get("open_interest")),
                    last_price=_safe_float(row.get("last_price")),
                )
            )
    for sym in cycles:
        cycles[sym].sort(key=lambda c: c.ts_ms)
    return dict(cycles)


def _states_at(cycles_by_sym, universe, ts_ms):
    out = {}
    for sym in universe:
        snaps = cycles_by_sym.get(sym) or []
        if len(snaps) < 2:
            continue
        ts_list = [c.ts_ms for c in snaps]
        idx = bisect_left(ts_list, ts_ms + 1)
        if idx < 2:
            continue
        st = compute_state(snaps[idx - 2 : idx])
        if st is not None:
            out[sym] = st
    return out


def _implied_side(quadrant: str) -> str:
    if quadrant in {"newLongs", "shortCover"}:
        return "long"
    if quadrant in {"newShorts", "longUnwind"}:
        return "short"
    return "flat"


def _forward_ret_bps(client, *, symbol, ts_iso, ref_price):
    if ref_price <= 0.0:
        return None
    ts = _parse_timestamp(ts_iso)
    start_ms = int(ts.timestamp() * 1000)
    end_ms = int((ts + timedelta(minutes=FORWARD_MIN + 1)).timestamp() * 1000)
    try:
        bars = sorted(
            fetch_klines_cached(
                client.get_klines, symbol=symbol, start_ms=start_ms, end_ms=end_ms,
                forward_minutes=FORWARD_MIN, cache_dir=KLINE_CACHE,
            ),
            key=lambda x: int(x.get("open_time") or 0),
        )
    except Exception:
        return None
    if not bars:
        return None
    target_ms = start_ms + FORWARD_MIN * 60_000
    after = [b for b in bars if int(b.get("open_time") or 0) >= target_ms] or [bars[-1]]
    close = _safe_float(after[0].get("close_price"))
    if close <= 0.0:
        return None
    return (close / ref_price - 1.0) * 10000.0


def _build_signal_pool(cycles_by_sym, universe, client):
    """Single pass: gather every (cycle, symbol) hypothetical signal with own/leader
    state + forward return. Reused across all variants to avoid recomputing."""
    pool = []
    leader_map = {"BTCUSDT": "ETHUSDT", "ETHUSDT": "BTCUSDT",
                  "SOLUSDT": "BTCUSDT", "DOGEUSDT": "BTCUSDT",
                  "PEPEUSDT": "BTCUSDT", "XRPUSDT": "BTCUSDT"}
    for sym in universe:
        snaps = cycles_by_sym.get(sym) or []
        for i in range(1, len(snaps)):
            cur = snaps[i]
            ts_ms = cur.ts_ms
            ts_iso = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
            states = _states_at(cycles_by_sym, universe, ts_ms)
            own = states.get(sym)
            if own is None:
                continue
            side = _implied_side(own.own_quadrant)
            if side not in {"long", "short"}:
                continue
            fwd = _forward_ret_bps(client, symbol=sym, ts_iso=ts_iso, ref_price=cur.last_price)
            if fwd is None:
                continue
            leader_sym = leader_map.get(sym)
            leader = states.get(leader_sym) if leader_sym else None
            pool.append({
                "ts_ms": ts_ms,
                "symbol": sym,
                "side": side,
                "ref_price": cur.last_price,
                "fwd_bps": fwd,
                "signed_bps": fwd if side == "long" else -fwd,
                "own": own,
                "leader": leader,
                "leader_sym": leader_sym or "",
            })
    return pool


def _evaluate_variant(pool, *, gate_enabled, leverage, size_mult, ev_table):
    """Run one variant against the pool, return aggregated stats."""
    n_total = len(pool)
    n_blocked = 0
    n_boosted = 0
    n_passed = 0
    pnl_sum = 0.0
    cost_sum = 0.0
    wins = 0
    losses = 0
    for s in pool:
        notional = NOTIONAL_USD * size_mult
        boost_factor = 1.0
        blocked = False
        if gate_enabled:
            try:
                score = score_symbol(ev_table, s["own"], s["leader"], now_ms=s["ts_ms"])
            except Exception:
                score = None
            if score is not None:
                if score.blocker_match is not None:
                    blocked = True
                else:
                    ev_threshold = float(ev_table.get("ev_threshold_bps", 5.0))
                    ev_bps = float(score.ev_bps)
                    scenario_side = str(score.side or "").lower()
                    if scenario_side == s["side"] and ev_threshold > 0.0 and ev_bps > ev_threshold:
                        boost_factor = min(1.0 + (ev_bps - ev_threshold) / ev_threshold, 1.5)
        if blocked:
            n_blocked += 1
            continue
        if boost_factor > 1.000001:
            n_boosted += 1
            notional *= boost_factor
        else:
            n_passed += 1
        pnl_gross = s["signed_bps"] * notional * leverage / 10000.0
        cost = COST_BPS_RT * notional / 10000.0
        net = pnl_gross - cost
        pnl_sum += net
        cost_sum += cost
        if net > 0:
            wins += 1
        else:
            losses += 1
    n_entries = wins + losses
    return {
        "n_signals": n_total,
        "n_entries": n_entries,
        "n_blocked": n_blocked,
        "n_boosted": n_boosted,
        "n_passed": n_passed,
        "wins": wins, "losses": losses,
        "win_rate": round(wins / max(n_entries, 1), 4),
        "fees_usd": round(cost_sum, 4),
        "net_pnl_usd": round(pnl_sum, 4),
        "pnl_per_trade_usd": round(pnl_sum / max(n_entries, 1), 6),
    }


def _composite(stats):
    s = stats["net_pnl_usd"] * 10.0
    s += min(stats["n_blocked"] * 0.05, 5.0)
    s += min(stats["n_boosted"] * 0.1, 5.0)
    if stats["n_entries"] >= 100:
        s += (stats["win_rate"] - 0.5) * 20.0
    return round(s, 3)


def main() -> None:
    print("loading cycles …")
    cycles_by_sym = _load_cycles_per_symbol()
    print(f"  symbols loaded={len(cycles_by_sym)}")

    print("loading EV table …")
    ev_table = load_ev_table(EV_TABLE_PATH)

    client = build_exchange_rest_client(
        exchange="bitget", allow_insecure_ssl=True, allow_missing_credentials=True
    )

    print("building signal pools per universe …")
    pools = {}
    for univ_name, syms in UNIVERSES.items():
        pool = _build_signal_pool(cycles_by_sym, syms, client)
        pools[univ_name] = pool
        print(f"  {univ_name}: {len(pool)} hypothetical signals")

    rows = []
    print("\nsweeping variants …")
    for univ_name, pool in pools.items():
        for profile, max_lev in PROFILE_LEVERAGE.items():
            for size_name, size_mult in SIZE_VARIANTS.items():
                for gate_state, gate_enabled in [("on", True), ("off", False)]:
                    stats = _evaluate_variant(
                        pool, gate_enabled=gate_enabled, leverage=max_lev,
                        size_mult=size_mult, ev_table=ev_table,
                    )
                    variant = {
                        "variant": f"{profile}|{univ_name}|gate_{gate_state}|size_{size_name}",
                        "profile": profile,
                        "universe": univ_name,
                        "gate": gate_state,
                        "size": size_name,
                        "max_leverage": max_lev,
                        "size_multiplier": size_mult,
                        **stats,
                        "composite": 0.0,  # filled below
                    }
                    variant["composite"] = _composite(stats)
                    rows.append(variant)

    rows.sort(key=lambda r: -r["composite"])
    print(f"\nevaluated {len(rows)} variants. top 15:\n")
    print(f"{'rank':>4s} {'variant':70s} {'entries':>8s} {'blocked':>8s} {'boosted':>8s} {'WR':>6s} {'pnl':>9s} {'comp':>9s}")
    for i, r in enumerate(rows[:15], 1):
        print(f"{i:>4d} {r['variant']:70s} {r['n_entries']:>8d} {r['n_blocked']:>8d} "
              f"{r['n_boosted']:>8d} {r['win_rate']:>6.3f} {r['net_pnl_usd']:>+9.2f} {r['composite']:>+9.2f}")

    print("\nworst 5:")
    for i, r in enumerate(rows[-5:], len(rows) - 4):
        print(f"{i:>4d} {r['variant']:70s} {r['n_entries']:>8d} {r['n_blocked']:>8d} "
              f"{r['n_boosted']:>8d} {r['win_rate']:>6.3f} {r['net_pnl_usd']:>+9.2f} {r['composite']:>+9.2f}")

    out_path = ROOT / "quant_runtime" / "strategy_matrix_summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"variants": rows}, indent=2))
    print(f"\nfull matrix → {out_path}")


if __name__ == "__main__":
    main()
