#!/usr/bin/env python3
"""Phase O: Diversified portfolio selection (greedy + risk parity).

Phase N 가 17 strategies 의 correlation matrix 산출.
이걸로 truly diversified subset 선정:
1. greedy Sharpe maximization (correlation penalty)
2. cap per-symbol exposure (max 2 per coin)
3. cap meme exposure (max 2 of WIF/PEPE/DOGE_heikin)

목표: 8-10 strategy subset 으로 동일 expected pnl 유지하면서 risk 감소.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np


def run():
    nf = Path("quant_runtime/output/auto4h/phaseN_correlation.json")
    if not nf.exists():
        print(f"missing {nf}"); return
    data = json.loads(nf.read_text())
    strats = {s["sid"]: s for s in data["strategies"]}
    pairs = data["pairs"]

    # build corr matrix
    sids = list(strats.keys())
    n = len(sids)
    idx = {s: i for i, s in enumerate(sids)}
    C = np.eye(n)
    for p in pairs:
        i = idx[p["a"]]; j = idx[p["b"]]
        c = p["weekly_pnl_corr"]
        C[i,j] = C[j,i] = c

    pnl = np.array([strats[s]["sum_pnl"] for s in sids])
    n_pos = np.array([strats[s]["n_in_pos"] for s in sids])

    # Greedy: pick strategy maximizing (pnl) - lambda * sum_corr_with_picked
    LAMBDA = 80.0  # corr penalty
    picked = []
    pool = list(range(n))
    target_n = 10

    while len(picked) < target_n and pool:
        best = None; best_score = -1e9
        for i in pool:
            corr_pen = sum(C[i,j] for j in picked)
            score = pnl[i] - LAMBDA * corr_pen
            if score > best_score:
                best_score = score; best = i
        picked.append(best); pool.remove(best)

    # symbol caps
    sym_of = {s: strats[s].get("sid","").split("_")[0] for s in sids}
    sid_to_sym = {
        "eth_donchian":"ETH","eth_volexp_2":"ETH",
        "sui_atrexp_4":"SUI","sui_atrexp_2":"SUI",
        "arb_volexp":"ARB",
        "doge_volexp_4":"DOGE","doge_volexp_2":"DOGE","doge_heikin":"DOGE","doge_momobv":"DOGE",
        "wif_momobv":"WIF","wif_heikin":"WIF",
        "ada_heikin_300":"ADA","ada_heikin_150":"ADA","ada_heikin_200":"ADA","ada_heikin_2":"ADA",
        "op_atrexp":"OP","pepe_atrexp":"PEPE",
    }

    # Apply hard cap: max 2 per symbol, and only top-pnl per symbol cluster among Jaccard ≥0.7
    high_jacc_pairs = [(p["a"], p["b"]) for p in pairs if p["jaccard"] >= 0.7]
    # Union-find groups
    parent = {s:s for s in sids}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    for a, b in high_jacc_pairs:
        union(a, b)
    groups = {}
    for s in sids:
        groups.setdefault(find(s), []).append(s)
    # pick 1 best per group
    cluster_winner = {}
    for root, mems in groups.items():
        winner = max(mems, key=lambda s: strats[s]["sum_pnl"])
        cluster_winner[root] = winner

    print("=== High-correlation clusters (Jaccard ≥ 0.7) ===")
    for root, mems in groups.items():
        if len(mems) > 1:
            print(f"  cluster {root}: {mems}")
            print(f"    keep -> {cluster_winner[root]} (best pnl)")

    # Final selection: greedy with cluster filter + symbol cap
    final = []
    sym_count = {}
    used_clusters = set()
    # rank greedy candidates by score
    while len(final) < target_n:
        best = None; best_score = -1e9
        for s in sids:
            if s in final: continue
            cl = find(s)
            if cl in used_clusters: continue
            sym = sid_to_sym.get(s, "?")
            if sym_count.get(sym, 0) >= 2: continue
            corr_pen = sum(C[idx[s], idx[f]] for f in final)
            score = strats[s]["sum_pnl"] - LAMBDA * corr_pen
            if score > best_score:
                best_score = score; best = s
        if best is None: break
        final.append(best)
        used_clusters.add(find(best))
        sym_count[sid_to_sym.get(best, "?")] = sym_count.get(sid_to_sym.get(best, "?"), 0) + 1

    print(f"\n=== FINAL PORTFOLIO ({len(final)} strategies) ===")
    print(f"{'sid':<18} {'sym':<6} {'pnl':>8} {'cluster':<8}")
    tot_pnl = 0
    for s in final:
        cl = find(s)
        sym = sid_to_sym.get(s, "?")
        p = strats[s]["sum_pnl"]
        tot_pnl += p
        print(f"  {s:<18} {sym:<6} ${p:>+6.0f}  {cl}")
    print(f"  TOTAL: ${tot_pnl:+.0f}")

    # average corr in selected
    avg_corr = 0; npair = 0
    for i in range(len(final)):
        for j in range(i+1, len(final)):
            avg_corr += C[idx[final[i]], idx[final[j]]]
            npair += 1
    print(f"  avg pairwise pnl_corr: {avg_corr/max(npair,1):.3f}")

    out_path = Path("quant_runtime/output/auto4h/phaseO_portfolio.json")
    with open(out_path, "w") as f:
        json.dump({"final_portfolio": final, "tot_pnl": tot_pnl,
                   "avg_corr": avg_corr/max(npair,1)}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
