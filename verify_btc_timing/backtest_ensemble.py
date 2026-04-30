"""Ensemble backtest:
  S1 = ch1_score baseline (current G405 logic, threshold=80)
  S2 = H3 DOGE session momentum (the only single alpha that survived)
  S3 = Trendwise gate (Bitwise 2025): BTC EMA10 > EMA20 gating S1

Configurations tested:
  E1: S1 only (baseline)
  E2: S2 only (DOGE session)
  E3: S1 + S2 parallel (capital split 50/50, separate decisions)
  E4: S1 with Trendwise gate (only enter S1 when BTC EMA10 > EMA20)
  E5: S1 + S2 parallel, S1 has Trendwise gate
  E6: AND ensemble (both S1 and S2 must agree on direction)

Goal: find combinations where Sharpe > sum of parts (true diversification benefit).
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
    df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df['date'] = df['dt'].dt.date
    df['hour'] = df['dt'].dt.hour
    # aliases for compute_ch1_score
    df['high_price'] = df['h']
    df['low_price'] = df['l']
    df['close_price'] = df['c']
    df['base_volume'] = df['v']
    return df


def summarize(label, pnls, capital=EQUITY):
    if not pnls:
        return {'label': label, 'n': 0, 'pnl': 0, 'wr': 0, 'mdd': 0, 'sharpe': 0, 'final': capital}
    cum = capital + np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    mdd = float(((cum - peak) / np.maximum(peak, 1)).min() * 100)
    wins = sum(1 for p in pnls if p > 0)
    # weekly returns approx (avg trades/week)
    weekly_pnl = []
    bucket_size = max(1, len(pnls) // 52)
    for i in range(0, len(pnls), bucket_size):
        weekly_pnl.append(sum(pnls[i:i+bucket_size]))
    if len(weekly_pnl) > 5 and np.std(weekly_pnl) > 0:
        sharpe = np.mean(weekly_pnl) / np.std(weekly_pnl) * np.sqrt(52)
    else:
        sharpe = 0
    return {
        'label': label, 'n': len(pnls), 'pnl': round(sum(pnls), 2),
        'wr': round(100 * wins / len(pnls), 1),
        'mdd': round(mdd, 1),
        'sharpe': round(sharpe, 2),
        'final': round(capital + sum(pnls), 2),
    }


# ── Strategy 1: ch1_score (baseline G405) ──
def strategy_s1(coins, scores, threshold=80, btc_close=None, ema_fast=None, ema_slow=None,
                margin=20.0, lev=20.0, hold=24, max_conc=5, atr_guard=6.0,
                use_trendwise=False):
    """Returns list of (timestamp_idx, pnl_usd, exit_reason). Single trade per signal."""
    n = len(coins['BTCUSDT'])
    fee = margin * lev * COST_RT
    open_pos = {}
    pnls = []
    for i in range(200, n - 1):
        # exits
        for sym in list(open_pos):
            ep, ei = open_pos[sym]
            cp = coins[sym]['c'].iloc[i]
            roe = (cp / ep - 1.0) * lev
            held = i - ei
            if held >= hold or roe <= -atr_guard / 100.0:
                pnls.append(margin * roe - fee)
                del open_pos[sym]

        # Trendwise gate
        if use_trendwise and ema_fast is not None and ema_slow is not None:
            if np.isnan(ema_fast[i]) or np.isnan(ema_slow[i]):
                continue
            if ema_fast[i] <= ema_slow[i]:
                continue  # bearish regime — skip entry

        if len(open_pos) >= max_conc:
            continue
        cands = []
        for sym in ALTS:
            if sym in open_pos:
                continue
            sa, aa = scores[sym]
            s = sa[i]; a = aa[i]
            if np.isnan(s) or np.isnan(a) or s < threshold or a > atr_guard:
                continue
            cands.append((sym, s))
        if cands:
            cands.sort(key=lambda x: -x[1])
            best = cands[0][0]
            open_pos[best] = (coins[best]['c'].iloc[i], i)
    # close eof
    for sym, (ep, ei) in open_pos.items():
        cp = coins[sym]['c'].iloc[n - 1]
        roe = (cp / ep - 1.0) * lev
        pnls.append(margin * roe - fee)
    return pnls


# ── Strategy 2: H3 DOGE session momentum ──
def strategy_s2(df, p_long=75, p_short=25, lookback_days=30, margin=20.0, lev=20.0):
    df = df.copy()
    df.set_index(pd.to_datetime(df['ts'], unit='ms', utc=True), inplace=True)
    df['date'] = df.index.date
    daily = []
    for date, grp in df.groupby('date'):
        if len(grp) < 24:
            continue
        eo = grp[grp['hour'] == 8]['o'].values
        ec = grp[grp['hour'] == 16]['o'].values
        uc = grp[grp['hour'] == 23]['c'].values
        if not (len(eo) and len(ec) and len(uc)):
            continue
        daily.append({'date': date, 'eur_ret': (ec[0]/eo[0]-1) if eo[0] > 0 else 0,
                      'us_open': float(ec[0]), 'us_close': float(uc[0])})
    df_d = pd.DataFrame(daily)
    pnls = []
    fee = margin * lev * COST_RT
    for i in range(lookback_days, len(df_d)):
        prev = df_d.iloc[i - lookback_days:i]['eur_ret']
        cur = df_d.iloc[i]['eur_ret']
        p75 = np.percentile(prev, p_long)
        p25 = np.percentile(prev, p_short)
        ep = df_d.iloc[i]['us_open']
        xp = df_d.iloc[i]['us_close']
        if cur > p75:
            roe = (xp / ep - 1) * lev
            pnls.append(margin * roe - fee)
        elif cur < p25:
            roe = (ep / xp - 1) * lev
            pnls.append(margin * roe - fee)
    return pnls


def main():
    print("loading data...")
    coins = {s: load(s) for s in UNIVERSE}
    btc = coins['BTCUSDT']

    print("computing ch1 scores...")
    scores = {}
    for sym in ALTS:
        s_ser, _ = compute_ch1_score(coins[sym])
        a_ser = atr_pct(coins[sym]['high_price'], coins[sym]['low_price'], coins[sym]['close_price'], 14)
        scores[sym] = (s_ser.values.astype(float), a_ser.values.astype(float))

    print("computing BTC EMA fast/slow...")
    btc_close = btc['c'].values
    # EMA10 days, EMA20 days on 1h bars (×24)
    ema10 = pd.Series(btc_close).ewm(span=10*24, adjust=False).mean().values
    ema20 = pd.Series(btc_close).ewm(span=20*24, adjust=False).mean().values

    results = []

    # E1: S1 only (baseline) — full capital
    print("\nE1: S1 baseline...")
    pnls_s1 = strategy_s1(coins, scores, threshold=80, margin=20.0)
    results.append(summarize("E1 S1 baseline (full)", pnls_s1))

    # E2: S2 only — full capital
    print("E2: S2 DOGE session...")
    pnls_s2 = strategy_s2(coins['DOGEUSDT'], margin=20.0)
    results.append(summarize("E2 S2 DOGE-session (full)", pnls_s2))

    # E3: S1 + S2 parallel (each with $50 sub-capital, margin halved)
    print("E3: S1 + S2 parallel 50/50...")
    pnls_s1_half = strategy_s1(coins, scores, threshold=80, margin=10.0)
    pnls_s2_half = strategy_s2(coins['DOGEUSDT'], margin=10.0)
    combined_e3 = pnls_s1_half + pnls_s2_half  # treat as one stream of trades
    results.append(summarize("E3 S1+S2 parallel(50/50)", combined_e3))
    results.append(summarize("  - E3.S1 sub", pnls_s1_half, capital=50.0))
    results.append(summarize("  - E3.S2 sub", pnls_s2_half, capital=50.0))

    # E4: S1 with Trendwise gate — full capital
    print("E4: S1 + Trendwise gate (EMA10>EMA20)...")
    pnls_s1_tw = strategy_s1(coins, scores, threshold=80, margin=20.0,
                              btc_close=btc_close, ema_fast=ema10, ema_slow=ema20,
                              use_trendwise=True)
    results.append(summarize("E4 S1+Trendwise gate", pnls_s1_tw))

    # E5: S1+Trendwise + S2 parallel
    print("E5: S1+Trendwise + S2 parallel...")
    pnls_s1_tw_half = strategy_s1(coins, scores, threshold=80, margin=10.0,
                                    btc_close=btc_close, ema_fast=ema10, ema_slow=ema20,
                                    use_trendwise=True)
    combined_e5 = pnls_s1_tw_half + pnls_s2_half
    results.append(summarize("E5 (S1+TW)+S2 parallel", combined_e5))

    # E6: lower threshold (try thr=75 to get more S1 trades) + parallel S2
    print("E6: S1 thr=75 + S2 parallel...")
    pnls_s1_75 = strategy_s1(coins, scores, threshold=75, margin=10.0)
    combined_e6 = pnls_s1_75 + pnls_s2_half
    results.append(summarize("E6 S1(thr75)+S2 parallel", combined_e6))

    # E7: thr=75 + Trendwise
    print("E7: S1 thr=75 + Trendwise + S2 parallel...")
    pnls_s1_75_tw = strategy_s1(coins, scores, threshold=75, margin=10.0,
                                  btc_close=btc_close, ema_fast=ema10, ema_slow=ema20,
                                  use_trendwise=True)
    combined_e7 = pnls_s1_75_tw + pnls_s2_half
    results.append(summarize("E7 S1(thr75+TW)+S2", combined_e7))

    # report
    print(f"\n{'config':<32} {'n':>5} {'pnl$':>8} {'wr%':>6} {'mdd%':>7} {'sharpe':>7} {'final$':>9}")
    print("-" * 80)
    for r in results:
        print(f"{r['label']:<32} {r['n']:>5} {r['pnl']:>8.2f} {r['wr']:>6.1f} {r['mdd']:>7.1f} {r['sharpe']:>7.2f} {r['final']:>9.2f}")

    # diversification check
    print("\n=== diversification benefit check ===")
    e1_pnl = next(r['pnl'] for r in results if r['label'] == 'E1 S1 baseline (full)')
    e2_pnl = next(r['pnl'] for r in results if r['label'] == 'E2 S2 DOGE-session (full)')
    e3_pnl = next(r['pnl'] for r in results if r['label'] == 'E3 S1+S2 parallel(50/50)')
    e4_pnl = next(r['pnl'] for r in results if r['label'] == 'E4 S1+Trendwise gate')
    print(f"E1 S1 alone: ${e1_pnl}")
    print(f"E2 S2 alone: ${e2_pnl}")
    print(f"naive sum  : ${(e1_pnl + e2_pnl)/2:.2f} (since each gets half capital)")
    print(f"E3 actual  : ${e3_pnl}")
    print(f"  -> diversification {'POSITIVE' if e3_pnl > (e1_pnl+e2_pnl)/2 else 'NEGATIVE'}")
    print(f"\nE1 baseline:           ${e1_pnl}  Sharpe={next(r['sharpe'] for r in results if r['label'] == 'E1 S1 baseline (full)')}")
    print(f"E4 S1+Trendwise gate:  ${e4_pnl}  Sharpe={next(r['sharpe'] for r in results if r['label'] == 'E4 S1+Trendwise gate')}")

    out = ROOT / "ensemble_results.json"
    out.write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
