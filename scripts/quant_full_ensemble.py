"""Full ensemble search: all factors × all coins × all params × regime weights.
Fixes WIF 759d bug (per-coin length). 3Y data for 18 coins.
Saves results to JSON for context-free analysis.

Usage: python scripts/quant_full_ensemble.py
"""
import json, random, statistics, itertools
from pathlib import Path

dd = Path("quant_runtime/historical")
COST_RT = 0.0012
EQUITY = 75.0

# Load coins individually (no min-length truncation)
all_coins = {}
for sym_dir in sorted(dd.iterdir()):
    if not sym_dir.is_dir(): continue
    sym = sym_dir.name
    p1h = sym_dir / "1h.json"
    if not p1h.exists(): continue
    b1 = json.load(open(p1h))
    if len(b1) < 15000: continue  # at least ~2 years
    all_coins[sym] = [b["close_price"] for b in b1]

btc = all_coins.get("BTCUSDT", [])
print(f"Loaded {len(all_coins)} coins (>=15000 bars each)", flush=True)
for sym, c in sorted(all_coins.items()):
    print(f"  {sym}: {len(c)} bars ({len(c)/24:.0f}d)", flush=True)

def mom(c, i, p):
    return (c[i] - c[i-p]) / c[i-p] if i >= p and c[i-p] > 0 else 0

def vol(c, i, p=480):
    if i < p: return 1
    rets = [(c[i-j] - c[i-j-1]) / c[i-j-1] for j in range(1, min(p, i))]
    return statistics.stdev(rets) if len(rets) > 10 else 1

def regime(btc_c, i):
    if i < 720 or i >= len(btc_c): return 1
    r5d = (btc_c[i] - btc_c[i-120]) / btc_c[i-120] if btc_c[i-120] > 0 else 0
    if r5d < -0.08: return 0  # crash
    e20 = sum(btc_c[max(0,i-20):i+1]) / min(20, i+1)
    e50 = sum(btc_c[max(0,i-50):i+1]) / min(50, i+1)
    return 2 if e20 > e50 else 1  # trend or range

results = []

# === STRATEGY TYPES ===
# 1. Per-coin reversal (buy -10% 3d crash)
# 2. Per-coin vol-managed momentum
# 3. Cross-sectional rotation (top N by momentum)
# 4. Regime-switched hybrid

for strategy in ["reversal", "vol_mom", "xsect_rotation"]:
  for lev in [5, 10, 15]:
    for mp in [0.50, 0.75]:
      for sl_roe in [10, 15, 20]:
        for hold_h in [168, 336]:  # 1w, 2w
          margin = EQUITY * mp
          notional = margin * lev
          fee = notional * COST_RT
          sl_dollar = margin * sl_roe / 100
          if fee / sl_dollar > 0.20: continue

          trades = []
          pos = None
          cd = 0

          # Use longest coin's length as reference
          max_n = max(len(c) for c in all_coins.values())

          for i in range(720, max_n, 24):  # daily check
              if pos:
                  c = all_coins.get(pos["sym"])
                  if not c or i >= len(c):
                      pos = None; continue
                  pc = (c[i] / pos["bp"] - 1)
                  roe = pc * 100 * lev
                  hh = i - pos["ei"]
                  fd = notional * 0.0001 * (hh // 8)
                  if roe <= -sl_roe:
                      trades.append(margin * (-sl_roe/100) - fee - fd)
                      pos = None; cd = i + 48; continue
                  if hh >= hold_h:
                      trades.append(margin * (roe/100) - fee - fd)
                      pos = None; continue
                  continue

              if i < cd: continue
              reg = regime(btc, i)
              if reg == 0: continue

              best_sym = None
              best_score = -999

              for sym, c in all_coins.items():
                  if sym == "BTCUSDT" or i >= len(c): continue

                  if strategy == "reversal":
                      r3d = mom(c, i, 72)
                      if r3d < -0.10:
                          score = -r3d  # bigger crash = higher score
                          if score > best_score:
                              best_score = score; best_sym = sym

                  elif strategy == "vol_mom":
                      m7d = mom(c, i, 168)
                      v = vol(c, i)
                      if m7d > 0.03:
                          score = m7d / max(v, 0.001)
                          if reg == 2: score *= 1.5
                          if score > best_score:
                              best_score = score; best_sym = sym

                  elif strategy == "xsect_rotation":
                      m7d = mom(c, i, 168)
                      btc_m = mom(btc, i, 168) if i < len(btc) else 0
                      rs = m7d - btc_m  # residual strength
                      if m7d > 0.02 and rs > 0:
                          score = rs
                          if score > best_score:
                              best_score = score; best_sym = sym

              if best_sym and best_score > 0:
                  c = all_coins[best_sym]
                  pos = {"sym": best_sym, "bp": c[i], "ei": i}

          if not trades or len(trades) < 10: continue
          w = sum(1 for t in trades if t > 0)
          nt = len(trades); total = sum(trades)
          if total <= 0: continue
          gp = sum(t for t in trades if t > 0)
          gl = abs(sum(t for t in trades if t <= 0))
          pf = gp / max(gl, 0.01)
          wr = w / max(nt, 1)
          aw = gp / max(w, 1)
          al = gl / max(nt - w, 1)
          ev = wr * aw - (1 - wr) * al
          tpm = nt / (max_n / 24) * 30

          fs = max(nt // 4, 1)
          wf = sum(1 for fi in range(4) if sum(trades[fi*fs:(fi+1)*fs if fi < 3 else nt]) > 0)
          if wf < 3: continue

          ruin = 0
          for _ in range(1000):
              bal = 75.0
              for t in random.choices(trades, k=nt):
                  bal += t
                  if bal <= 0: ruin += 1; break

          results.append({
              "strategy": strategy, "lev": lev, "mp": mp,
              "sl": sl_roe, "hold": hold_h,
              "nt": nt, "tpm": round(tpm, 1),
              "wr": round(wr, 4), "pnl": round(total, 2),
              "pf": round(pf, 2), "aw": round(aw, 2),
              "al": round(al, 2), "ev": round(ev, 2),
              "wf": wf, "ruin": round(ruin / 10, 1),
          })

print(f"\nTotal profitable WF3+: {len(results)}", flush=True)

# Rankings
for label, subset in [
    ("RUIN<=5%", sorted([r for r in results if r["ruin"] <= 5], key=lambda r: -r["ev"])),
    ("RUIN<=10%", sorted([r for r in results if r["ruin"] <= 10], key=lambda r: -r["ev"])),
    ("ALL by EV", sorted(results, key=lambda r: -r["ev"])),
]:
    print(f"\n{label} (top 10):", flush=True)
    for r in subset[:10]:
        print(f"  {r['strategy']:>10} {r['lev']}x {r['mp']*100:.0f}% sl{r['sl']} h{r['hold']}: "
              f"{r['nt']}t({r['tpm']:.0f}/m) WR={r['wr']*100:.0f}% aw=${r['aw']:.2f} "
              f"EV=${r['ev']:.2f} ruin={r['ruin']}% PF={r['pf']} WF={r['wf']}/4 ${r['pnl']:+.0f}",
              flush=True)

out = Path("quant_runtime/output/full_ensemble_3y.json")
out.write_text(json.dumps(results[:200], indent=2))
print(f"\nSaved {out}", flush=True)
