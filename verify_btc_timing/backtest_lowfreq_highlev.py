"""Low-freq + high-lev + high-volume variants.

Direction:
  - thr UP (80→85,90) → fewer entries
  - lev UP (20x→30,40,50)
  - size_pct UP (0.10→0.30,0.40)
  - max_conc DOWN (5→3,1) → 더 집중
  - + Trendwise gate
"""
import json, sys
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent / "local_emulators" / "_shared"))
from g002_mingogogo_ch1_backtest import compute_ch1_score, atr_pct  # type: ignore

DATA = ROOT / "data"
UNIVERSE = ['BTCUSDT', 'DOGEUSDT', 'PEPEUSDT', 'ARBUSDT', 'OPUSDT',
            'AVAXUSDT', 'SUIUSDT', 'ADAUSDT', 'APTUSDT', 'BNBUSDT',
            'DOTUSDT', 'LINKUSDT', 'NEARUSDT', 'SOLUSDT', 'UNIUSDT', 'XRPUSDT']
ALTS = [s for s in UNIVERSE if s != 'BTCUSDT']
EQUITY = 100.0
COST_RT = 16.0 / 10000.0


def load(sym):
    raw = json.loads((DATA / f"{sym}.json").read_text())
    df = pd.DataFrame(raw, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
    df['high_price'] = df['h']; df['low_price'] = df['l']
    df['close_price'] = df['c']; df['base_volume'] = df['v']
    return df


def summarize(label, pnls, params):
    if not pnls:
        return {'label': label, **params, 'n': 0, 'pnl': 0, 'wr': 0, 'mdd': 0, 'sharpe': 0, 'final': EQUITY}
    cum = EQUITY + np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    mdd = float(((cum - peak) / np.maximum(peak, 1)).min() * 100)
    wins = sum(1 for p in pnls if p > 0)
    weekly = []
    bs = max(1, len(pnls) // 52)
    for i in range(0, len(pnls), bs):
        weekly.append(sum(pnls[i:i+bs]))
    sharpe = (np.mean(weekly) / np.std(weekly) * np.sqrt(52)) if (len(weekly) > 5 and np.std(weekly) > 0) else 0
    return {
        'label': label, **params,
        'n': len(pnls), 'pnl': round(sum(pnls), 2),
        'wr': round(100 * wins / len(pnls), 1),
        'mdd': round(mdd, 1),
        'sharpe': round(sharpe, 2),
        'final': round(EQUITY + sum(pnls), 2),
    }


def precompute_scores(coins):
    out = {}
    for sym in ALTS:
        s_ser, _ = compute_ch1_score(coins[sym])
        a_ser = atr_pct(coins[sym]['high_price'], coins[sym]['low_price'], coins[sym]['close_price'], 14)
        out[sym] = (s_ser.values.astype(float), a_ser.values.astype(float))
    return out


def run(coins, scores, threshold, hold, margin, lev, atr_guard, max_conc,
        use_trendwise=False, ema_fast=None, ema_slow=None, liquidation_check=True):
    n = len(coins['BTCUSDT'])
    fee = margin * lev * COST_RT
    open_pos = {}
    pnls = []
    for i in range(20*24+1, n - 1):
        for sym in list(open_pos):
            ep, ei = open_pos[sym]
            cp = coins[sym]['c'].iloc[i]
            ret = (cp / ep - 1.0)
            roe = ret * lev
            held = i - ei
            # liquidation: roe <= -0.95 (95% margin loss = effectively liquidated)
            if liquidation_check and roe <= -0.95:
                pnls.append(-margin * 0.95 - fee)  # near total loss of margin
                del open_pos[sym]
                continue
            if held >= hold or roe <= -atr_guard / 100.0:
                pnls.append(margin * roe - fee)
                del open_pos[sym]

        if use_trendwise and ema_fast is not None and ema_slow is not None:
            if np.isnan(ema_fast[i]) or np.isnan(ema_slow[i]) or ema_fast[i] <= ema_slow[i]:
                continue
        if len(open_pos) >= max_conc:
            continue
        cands = []
        for sym in ALTS:
            if sym in open_pos: continue
            sa, aa = scores[sym]
            s = sa[i]; a = aa[i]
            if np.isnan(s) or np.isnan(a) or s < threshold or a > atr_guard:
                continue
            cands.append((sym, s))
        if cands:
            cands.sort(key=lambda x: -x[1])
            best = cands[0][0]
            open_pos[best] = (coins[best]['c'].iloc[i], i)
    return pnls


def main():
    print("loading data + scores...")
    coins = {s: load(s) for s in UNIVERSE}
    btc_close = coins['BTCUSDT']['c'].values
    ema10 = pd.Series(btc_close).ewm(span=10*24, adjust=False).mean().values
    ema20 = pd.Series(btc_close).ewm(span=20*24, adjust=False).mean().values
    scores = precompute_scores(coins)

    results = []
    # baseline reference
    pnls = run(coins, scores, 80, 24, 20.0, 20.0, 6.0, 5)
    results.append(summarize("REF baseline thr80 lev20 size0.20", pnls,
                              {'thr': 80, 'lev': 20, 'size': 0.20, 'conc': 5, 'tw': False}))

    print("running variants...")
    # combos: high thr × high lev × big size × low conc × +/- TW
    combos = []
    for thr in [80, 82, 85, 88]:
        for lev in [20, 30, 40, 50]:
            for size in [0.10, 0.20, 0.30, 0.40]:
                for conc in [1, 3, 5]:
                    for tw in [False, True]:
                        combos.append((thr, lev, size, conc, tw))
    print(f"  {len(combos)} combos to test")

    for thr, lev, size, conc, tw in combos:
        margin = EQUITY * size
        try:
            pnls = run(coins, scores, thr, 24, margin, lev, 6.0, conc,
                       use_trendwise=tw, ema_fast=ema10, ema_slow=ema20)
        except Exception:
            continue
        if len(pnls) == 0:
            continue
        label = f"thr{thr} lev{lev} size{size:.2f} conc{conc}{'+TW' if tw else ''}"
        params = {'thr': thr, 'lev': lev, 'size': size, 'conc': conc, 'tw': tw}
        results.append(summarize(label, pnls, params))

    # ranking
    print(f"\n=== TOP 15 by PnL ===")
    print(f"{'config':<40} {'n':>4} {'pnl$':>8} {'wr%':>6} {'mdd%':>7} {'sharpe':>7}")
    print("-" * 80)
    by_pnl = sorted(results, key=lambda r: -r['pnl'])
    for r in by_pnl[:15]:
        print(f"{r['label']:<40} {r['n']:>4} {r['pnl']:>8.2f} {r['wr']:>6.1f} {r['mdd']:>7.1f} {r['sharpe']:>7.2f}")

    print(f"\n=== TOP 10 by Sharpe (n>=5, mdd > -50) ===")
    qualified = [r for r in results if r['n'] >= 5 and r['mdd'] > -50 and r['pnl'] > 0]
    qualified.sort(key=lambda r: -r['sharpe'])
    for r in qualified[:10]:
        print(f"{r['label']:<40} {r['n']:>4} {r['pnl']:>8.2f} {r['wr']:>6.1f} {r['mdd']:>7.1f} {r['sharpe']:>7.2f}")

    print(f"\n=== Liquidation risk (roe<=-95%) detection ===")
    deep_loss = [r for r in results if r['mdd'] < -80]
    print(f"  configs with MDD<-80%: {len(deep_loss)}/{len(results)}")

    out = ROOT / "lowfreq_highlev_results.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nsaved -> {out}")


if __name__ == '__main__':
    main()
