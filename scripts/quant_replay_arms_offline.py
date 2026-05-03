#!/usr/bin/env python3
"""Offline 4-arm cross-coin gate replay.

For each cycle in `quant_runtime_paper50/bitget_external_alpha_shadow/`,
synthesize an entry signal per symbol whose side is implied by the OI×price
quadrant (newLongs/shortCover→long, newShorts/longUnwind→short). Then for
each of 4 arm configs apply (or skip) the cross-coin gate from
`quant_binance.cross_coin_scorer`, compute forward 60m PnL using cached
klines, and emit per-arm forensics+closed_trades that the existing monitor
script can read.

Why this and not decisions.jsonl replay:
  Production decisions.jsonl is post-symbol_profile-filter. ~99.97% are
  flat (rejected upstream). Cross-coin gate sits downstream of those
  filters, so a decisions.jsonl replay measures nothing. Cycle-level
  replay treats every (cycle, symbol) as a hypothetical signal and tells
  us how the gate WOULD redirect notional under that maximum-coverage
  assumption.

CAVEAT: in-sample. The EV table this gate uses was built from this same
4-day cycle window, so positive scenarios will look unrealistically good.
Use the resulting block/boost counts and relative arm ranking, not the
absolute PnL number.

Usage:
  scripts/quant_python.sh scripts/quant_replay_arms_offline.py
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

UNIVERSE_FULL = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "PEPEUSDT", "XRPUSDT"]
UNIVERSE_MAJORS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
UNIVERSE_ALTS = ["PEPEUSDT", "DOGEUSDT", "XRPUSDT", "SOLUSDT"]

ARMS = {
    # name → (output_dir_suffix, universe, gate_enabled)
    "A_live": ("quant_runtime_armA_replay", UNIVERSE_FULL, True),
    "B_gate_off": ("quant_runtime_armB_replay", UNIVERSE_FULL, False),
    "C_majors": ("quant_runtime_armC_replay", UNIVERSE_MAJORS, True),
    "D_alts": ("quant_runtime_armD_replay", UNIVERSE_ALTS, True),
}

NOTIONAL_USD = 10.0  # base entry notional (paper-equivalent)
COST_BPS_RT = 16.0   # round-trip fee+funding flat cost (matches batch_backtest)
LEVERAGE = 5.0       # paper50 default
FORWARD_MIN = 60     # forward window for PnL


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
            if sym not in UNIVERSE_FULL:
                continue
            ts_str = row.get("timestamp")
            if not ts_str:
                continue
            try:
                ts = _parse_timestamp(ts_str)
                ts_ms = int(ts.timestamp() * 1000)
            except Exception:
                continue
            cycles[sym].append(
                CycleSnapshot(
                    symbol=sym,
                    ts_ms=ts_ms,
                    open_interest=_safe_float(row.get("open_interest")),
                    last_price=_safe_float(row.get("last_price")),
                )
            )
    for sym in cycles:
        cycles[sym].sort(key=lambda c: c.ts_ms)
    return dict(cycles)


def _states_at(
    cycles_by_sym: dict[str, list[CycleSnapshot]],
    universe: list[str],
    ts_ms: int,
) -> dict[str, SymbolState]:
    """Return per-symbol SymbolState computed from the latest TWO cycles ≤ ts_ms."""
    out: dict[str, SymbolState] = {}
    for sym in universe:
        snaps = cycles_by_sym.get(sym) or []
        if len(snaps) < 2:
            continue
        ts_list = [c.ts_ms for c in snaps]
        idx = bisect_left(ts_list, ts_ms + 1)  # last index with ts ≤ ts_ms
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


def _forward_ret_bps(client, *, symbol: str, ts_iso: str, ref_price: float) -> float | None:
    if ref_price <= 0.0:
        return None
    ts = _parse_timestamp(ts_iso)
    start_ms = int(ts.timestamp() * 1000)
    end_ms = int((ts + timedelta(minutes=FORWARD_MIN + 1)).timestamp() * 1000)
    try:
        bars = sorted(
            fetch_klines_cached(
                client.get_klines,
                symbol=symbol,
                start_ms=start_ms,
                end_ms=end_ms,
                forward_minutes=FORWARD_MIN,
                cache_dir=KLINE_CACHE,
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


def _emit_forensics(arm_dir: Path, decisions: list[dict[str, Any]], trades: list[dict[str, Any]]) -> None:
    (arm_dir / "forensics").mkdir(parents=True, exist_ok=True)
    with (arm_dir / "forensics" / "decisions.jsonl").open("w") as f:
        for d in decisions:
            f.write(json.dumps(d) + "\n")
    with (arm_dir / "closed_trades.jsonl").open("w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")


def _replay_arm(
    arm_name: str,
    universe: list[str],
    gate_enabled: bool,
    cycles_by_sym: dict[str, list[CycleSnapshot]],
    ev_table: dict[str, Any],
    client,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Replay one arm. Returns (decisions, closed_trades, summary)."""
    decisions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    n_blocked = 0
    n_boosted = 0
    n_passed = 0
    n_skipped_unknown_side = 0
    pnl_sum_usd = 0.0
    cost_sum_usd = 0.0
    wins = 0
    losses = 0

    # iterate every cycle position for every symbol in universe
    for sym in universe:
        snaps = cycles_by_sym.get(sym) or []
        if len(snaps) < 2:
            continue
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
                n_skipped_unknown_side += 1
                continue

            # Forward PnL
            ref_price = cur.last_price
            fwd = _forward_ret_bps(client, symbol=sym, ts_iso=ts_iso, ref_price=ref_price)
            if fwd is None:
                continue
            # signed forward by side
            signed = fwd if side == "long" else -fwd

            notional = NOTIONAL_USD
            boost_factor = 1.0
            ev_bps = 0.0
            rejection: list[str] = []
            size_boosts: list[str] = []
            blocker_reason = ""
            cross_coin_meta: dict[str, Any] = {
                "cross_coin_own_quadrant": own.own_quadrant,
                "cross_coin_own_dir": own.own_dir,
            }

            if gate_enabled:
                leader_sym = (ev_table.get("leader_per_symbol") or {}).get(sym)
                leader = states.get(leader_sym) if leader_sym else None
                cross_coin_meta["cross_coin_leader_symbol"] = leader_sym or ""
                if leader is not None:
                    cross_coin_meta["cross_coin_leader_quadrant"] = leader.own_quadrant
                    cross_coin_meta["cross_coin_leader_dir"] = leader.own_dir
                try:
                    score = score_symbol(ev_table, own, leader, now_ms=ts_ms)
                except Exception:
                    score = None

                if score is not None:
                    cross_coin_meta["cross_coin_ev_bps"] = float(score.ev_bps)
                    cross_coin_meta["cross_coin_winrate"] = float(score.winrate)
                    cross_coin_meta["cross_coin_n"] = int(score.n)
                    cross_coin_meta["cross_coin_rank"] = int(score.rank)
                    if score.blocker_match is not None:
                        n_blocked += 1
                        blocker_reason = str(score.blocker_match.get("reason", "unknown"))
                        rejection.append(f"CROSS_COIN_OI_QUADRANT_BLOCKED:{blocker_reason}")
                        notional = 0.0  # no entry
                    else:
                        # positive scenario — apply EV-strength boost if side aligns
                        ev_threshold = float(ev_table.get("ev_threshold_bps", 5.0))
                        ev_bps = float(score.ev_bps)
                        scenario_side = str(score.side or "").lower()
                        if scenario_side == side and ev_threshold > 0.0 and ev_bps > ev_threshold:
                            boost_factor = min(1.0 + (ev_bps - ev_threshold) / ev_threshold, 1.5)
                        if boost_factor > 1.000001:
                            n_boosted += 1
                            notional = round(NOTIONAL_USD * boost_factor, 4)
                            size_boosts.append(f"CROSS_COIN_EV_BOOST:{ev_bps:.1f}bps")
                        else:
                            n_passed += 1
                else:
                    # no scenario, no blocker — pass-through
                    n_passed += 1
            else:
                # gate disabled: pass-through
                n_passed += 1

            # Synthesize the decision row (monitor reads side, final_mode, rejection_reasons,
            # size_boost_reasons, order_intent_notional_usd, symbol, timestamp)
            d_row: dict[str, Any] = {
                "timestamp": ts_iso,
                "symbol": sym,
                "side": "flat" if notional <= 0.0 else side,
                "final_mode": "cash" if notional <= 0.0 else "futures",
                "reference_price": ref_price,
                "order_intent_notional_usd": notional,
                "rejection_reasons": rejection,
                "size_boost_reasons": size_boosts,
                "strategy_size_multiplier": boost_factor,
                "cross_coin_is_top_priority": False,
                **cross_coin_meta,
            }
            if blocker_reason:
                d_row["cross_coin_blocker_reason"] = blocker_reason
            decisions.append(d_row)

            # Compute PnL only for actual entries
            if notional > 0.0:
                # PnL = signed_bps × notional × leverage / 10000
                pnl_gross = signed * notional * LEVERAGE / 10000.0
                cost = COST_BPS_RT * notional / 10000.0
                pnl_net = pnl_gross - cost
                pnl_sum_usd += pnl_net
                cost_sum_usd += cost
                if pnl_net > 0:
                    wins += 1
                else:
                    losses += 1
                trades.append(
                    {
                        "timestamp": ts_iso,
                        "symbol": sym,
                        "side": side,
                        "entry_price": ref_price,
                        "notional_usd": notional,
                        "leverage": LEVERAGE,
                        "forward_60m_bps": round(fwd, 3),
                        "signed_60m_bps": round(signed, 3),
                        "fees_bps_rt": COST_BPS_RT,
                        "realized_pnl_usd": round(pnl_net, 4),
                        "exit_reason": "forward_60m_proxy",
                        "boosted": boost_factor > 1.000001,
                    }
                )

    n_total_entries = len(trades)
    win_rate = wins / max(n_total_entries, 1)
    summary = {
        "arm": arm_name,
        "universe": universe,
        "gate_enabled": gate_enabled,
        "n_decisions": len(decisions),
        "n_entries": n_total_entries,
        "n_blocked": n_blocked,
        "n_boosted": n_boosted,
        "n_passed": n_passed,
        "n_skipped_unknown_side": n_skipped_unknown_side,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4),
        "gross_pnl_usd": round(pnl_sum_usd + cost_sum_usd, 4),
        "fees_usd": round(cost_sum_usd, 4),
        "net_pnl_usd": round(pnl_sum_usd, 4),
    }
    return decisions, trades, summary


def main() -> None:
    print("loading cycles …")
    cycles_by_sym = _load_cycles_per_symbol()
    for sym, snaps in cycles_by_sym.items():
        print(f"  {sym}: {len(snaps)}")

    print("loading EV table …")
    ev_table = load_ev_table(EV_TABLE_PATH)
    print(
        f"  scenarios={len(ev_table.get('scenarios') or [])}, "
        f"blockers={len(ev_table.get('blockers') or [])}, "
        f"threshold={ev_table.get('ev_threshold_bps')}"
    )

    print("connecting REST client (read-only kline cache fallback) …")
    client = build_exchange_rest_client(
        exchange="bitget", allow_insecure_ssl=True, allow_missing_credentials=True
    )

    summaries = []
    for arm_name, (suffix, universe, gate_enabled) in ARMS.items():
        print(f"\n--- replaying {arm_name} (gate={gate_enabled}, universe={universe}) ---")
        decisions, trades, summary = _replay_arm(
            arm_name, universe, gate_enabled, cycles_by_sym, ev_table, client
        )
        out_dir = ROOT / suffix
        _emit_forensics(out_dir, decisions, trades)
        summaries.append(summary)
        print(
            f"  decisions={summary['n_decisions']}  entries={summary['n_entries']}  "
            f"blocked={summary['n_blocked']}  boosted={summary['n_boosted']}  "
            f"net_pnl=${summary['net_pnl_usd']}  win_rate={summary['win_rate']}"
        )
        print(f"  → {out_dir}/forensics/decisions.jsonl  +  {out_dir}/closed_trades.jsonl")

    # write a compact comparison artifact
    out_path = ROOT / "quant_runtime" / "multi_arm_replay_summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"summaries": summaries}, indent=2))
    print(f"\nsummary → {out_path}")


if __name__ == "__main__":
    main()
