"""Test 4 hypotheses against same 365-day dataset:
  H1: Top-N simple momentum (20d ranking, hold N days)
  H2: Z-score cross momentum (short vs long window)
  H3: Session momentum (Europe -> US: long if Europe > 75th, short if < 25th)
  H4: Asia reversal (00 UTC entry, 08 UTC exit, reverse Asia trend)

All against same baseline portfolio sizing (margin=$20, lev=20x, cost=16bps RT).
"""
import json
import sys
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent
DATA = ROOT / "data"
UNIVERSE = ['BTCUSDT', 'DOGEUSDT', 'PEPEUSDT', 'ARBUSDT', 'OPUSDT',
            'AVAXUSDT', 'SUIUSDT', 'ADAUSDT', 'APTUSDT', 'BNBUSDT',
            'DOTUSDT', 'LINKUSDT', 'NEARUSDT', 'SOLUSDT', 'UNIUSDT', 'XRPUSDT']
ALTS = [s for s in UNIVERSE if s != 'BTCUSDT']

EQUITY = 100.0
MARGIN = 20.0      # SIZE_PCT 0.2
LEV = 20.0
COST_RT = 16.0 / 10000.0  # 16 bps round trip


def load(sym):
    raw = json.loads((DATA / f"{sym}.json").read_text())
    df = pd.DataFrame(raw, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
    df['hour_utc'] = pd.to_datetime(df['ts'], unit='ms', utc=True).dt.hour
    return df


def summarize(label, pnls):
    if not pnls:
        return {'label': label, 'n': 0, 'pnl': 0, 'wr': 0, 'avg': 0, 'final': EQUITY}
    eq_curve = EQUITY + np.cumsum(pnls)
    peak = np.maximum.accumulate(eq_curve)
    mdd = float(((eq_curve - peak) / np.maximum(peak, 1)).min() * 100)
    wins = sum(1 for p in pnls if p > 0)
    daily_groups = max(1, len(pnls) // 365)
    if daily_groups > 1:
        daily_pnl = np.array([pnls[i:i+daily_groups] for i in range(0, len(pnls), daily_groups)])
        daily_sum = [s.sum() for s in daily_pnl if len(s) > 0]
        if len(daily_sum) > 1 and np.std(daily_sum) > 0:
            sharpe = np.mean(daily_sum) / np.std(daily_sum) * np.sqrt(365)
        else:
            sharpe = 0
    else:
        sharpe = 0
    return {
        'label': label, 'n': len(pnls), 'pnl': round(sum(pnls), 2),
        'wr': round(100 * wins / len(pnls), 1),
        'avg': round(np.mean(pnls), 3),
        'mdd': round(mdd, 1),
        'sharpe': round(sharpe, 2),
        'final': round(EQUITY + sum(pnls), 2),
    }


def calc_pnl(entry_p, exit_p, side='long'):
    """side=+1 (long) or -1 (short). returns pnl in dollars."""
    if side == 'long' or side == 1:
        roe = (exit_p / entry_p - 1.0) * LEV
    else:
        roe = (entry_p / exit_p - 1.0) * LEV
    fee = MARGIN * LEV * COST_RT
    return MARGIN * roe - fee


# ── H1: Top-N momentum ──
def h1_top_n_momentum(coins, lookback_days=20, hold_days=5, top_n=3):
    """Each `hold_days`, rank alts by past `lookback_days` return,
    long the top N equally-weighted. Equity split per slot."""
    n = len(coins['BTCUSDT'])
    lb = lookback_days * 24
    hd = hold_days * 24
    pnls = []
    margin_per_slot = MARGIN / top_n  # split equity among slots
    fee_per_slot = margin_per_slot * LEV * COST_RT
    for i in range(lb, n - hd, hd):
        rets = []
        for s in ALTS:
            arr = coins[s]['c'].values
            if i - lb < 0 or i >= len(arr):
                continue
            r = (arr[i] / arr[i - lb] - 1.0) if arr[i - lb] > 0 else 0
            rets.append((s, r))
        rets.sort(key=lambda x: -x[1])
        chosen = rets[:top_n]
        for s, _ in chosen:
            arr = coins[s]['c'].values
            entry = arr[i]
            exit_idx = min(i + hd, len(arr) - 1)
            exit_p = arr[exit_idx]
            roe = (exit_p / entry - 1.0) * LEV
            pnls.append(margin_per_slot * roe - fee_per_slot)
    return pnls


# ── H2: Z-score momentum ──
def h2_zscore_momentum(coins, short=24, long_=24*7, z_thr=1.0, hold=24):
    """For each hour, compute zscore = (mean_short - mean_long) / std_long of returns.
    Enter long top alt if zscore > thr, hold for `hold` hours."""
    n = len(coins['BTCUSDT'])
    pnls = []
    open_pos = {}  # sym -> (entry_price, entry_idx)
    fee = MARGIN * LEV * COST_RT
    for i in range(long_ + 10, n - 1):
        # exit
        for s in list(open_pos):
            ep, ei = open_pos[s]
            if i - ei >= hold:
                exit_p = coins[s]['c'].iloc[i]
                roe = (exit_p / ep - 1.0) * LEV
                pnls.append(MARGIN * roe - fee)
                del open_pos[s]
        # entry
        if i % 4 != 0:
            continue  # check every 4h to reduce overtrade
        if len(open_pos) >= 3:
            continue
        cands = []
        for s in ALTS:
            if s in open_pos:
                continue
            c = coins[s]['c'].values
            rets = np.diff(c[i - long_:i]) / c[i - long_:i - 1]
            if len(rets) < 10:
                continue
            mu_short = rets[-short:].mean()
            mu_long = rets.mean()
            sd_long = rets.std()
            if sd_long == 0:
                continue
            z = (mu_short - mu_long) / sd_long
            if z > z_thr:
                cands.append((s, z))
        if cands:
            cands.sort(key=lambda x: -x[1])
            best = cands[0][0]
            open_pos[best] = (coins[best]['c'].iloc[i], i)
    # close eof
    last = n - 1
    for s, (ep, ei) in open_pos.items():
        exit_p = coins[s]['c'].iloc[last]
        roe = (exit_p / ep - 1.0) * LEV
        pnls.append(MARGIN * roe - fee)
    return pnls


# ── H3: Session momentum (Europe -> US) ──
def h3_session_momentum(df, target_long_pctile=75, target_short_pctile=25, lookback_days=30):
    """At 16:00 UTC, look at Europe session return (08-16 UTC).
    If > 75th pctile of past N days, long. < 25th, short. Exit at 00:00 UTC."""
    pnls = []
    fee = MARGIN * LEV * COST_RT
    # build hourly dataframe
    df = df.copy()
    df.set_index(pd.to_datetime(df['ts'], unit='ms', utc=True), inplace=True)
    df['date'] = df.index.date
    # group by date, compute Europe session return (h=08 to h=16)
    daily = []
    for date, grp in df.groupby('date'):
        if len(grp) < 24:
            continue
        eur_open = grp[grp['hour_utc'] == 8]['o'].values
        eur_close = grp[grp['hour_utc'] == 16]['o'].values
        us_close = grp[grp['hour_utc'] == 23]['c'].values
        if len(eur_open) == 0 or len(eur_close) == 0 or len(us_close) == 0:
            continue
        daily.append({
            'date': date,
            'eur_ret': (eur_close[0] / eur_open[0] - 1.0) if eur_open[0] > 0 else 0,
            'us_open': float(eur_close[0]),  # entry price
            'us_close': float(us_close[0]),  # exit price
        })
    if len(daily) < lookback_days + 5:
        return pnls
    df_d = pd.DataFrame(daily)
    for i in range(lookback_days, len(df_d)):
        prev = df_d.iloc[i - lookback_days:i]['eur_ret']
        cur_eur = df_d.iloc[i]['eur_ret']
        p75 = np.percentile(prev, target_long_pctile)
        p25 = np.percentile(prev, target_short_pctile)
        ep = df_d.iloc[i]['us_open']
        xp = df_d.iloc[i]['us_close']
        if cur_eur > p75:
            roe = (xp / ep - 1.0) * LEV
            pnls.append(MARGIN * roe - fee)
        elif cur_eur < p25:
            roe = (ep / xp - 1.0) * LEV  # short
            pnls.append(MARGIN * roe - fee)
    return pnls


# ── H4: Asia reversal ──
def h4_asia_reversal(df, threshold_pct=2.0):
    """At 00:00 UTC, look at yesterday's Asia session direction (00-08 UTC).
    If yesterday Asia +X%+, short today's Asia. If -X%-, long. Exit at 08:00 UTC."""
    pnls = []
    fee = MARGIN * LEV * COST_RT
    df = df.copy()
    df.set_index(pd.to_datetime(df['ts'], unit='ms', utc=True), inplace=True)
    df['date'] = df.index.date
    daily = []
    for date, grp in df.groupby('date'):
        if len(grp) < 24:
            continue
        a_open = grp[grp['hour_utc'] == 0]['o'].values
        a_close = grp[grp['hour_utc'] == 8]['o'].values
        if len(a_open) == 0 or len(a_close) == 0:
            continue
        daily.append({'date': date, 'asia_ret': (a_close[0] / a_open[0] - 1.0),
                      'open': float(a_open[0]), 'close': float(a_close[0])})
    df_d = pd.DataFrame(daily)
    thr = threshold_pct / 100.0
    for i in range(1, len(df_d)):
        prev_ret = df_d.iloc[i - 1]['asia_ret']
        ep = df_d.iloc[i]['open']
        xp = df_d.iloc[i]['close']
        if prev_ret > thr:
            roe = (ep / xp - 1.0) * LEV  # short
            pnls.append(MARGIN * roe - fee)
        elif prev_ret < -thr:
            roe = (xp / ep - 1.0) * LEV  # long
            pnls.append(MARGIN * roe - fee)
    return pnls


def main():
    print("loading data...")
    coins = {s: load(s) for s in UNIVERSE}

    results = []

    # H1 sweeps
    print("\nH1: Top-N momentum sweep...")
    for lb in [10, 20, 30]:
        for hd in [3, 5, 7]:
            for n in [2, 3, 5]:
                pnls = h1_top_n_momentum(coins, lb, hd, n)
                results.append(summarize(f"H1 top{n} lb{lb}d hd{hd}d", pnls))

    # H2 sweeps
    print("H2: Z-score momentum sweep...")
    for short in [12, 24, 48]:
        for long_ in [168, 336]:
            for thr in [0.8, 1.2, 1.6]:
                pnls = h2_zscore_momentum(coins, short, long_, thr)
                results.append(summarize(f"H2 z>{thr} s{short}h L{long_}h", pnls))

    # H3 sessions on each coin separately
    print("H3: Session momentum (per-coin)...")
    for sym in ['BTCUSDT', 'ETHUSDT' if 'ETHUSDT' in coins else 'BNBUSDT', 'SOLUSDT', 'AVAXUSDT', 'DOGEUSDT']:
        if sym not in coins:
            continue
        pnls = h3_session_momentum(coins[sym])
        results.append(summarize(f"H3 sess {sym}", pnls))

    # H4 asia reversal
    print("H4: Asia reversal (per-coin)...")
    for sym in ['BTCUSDT', 'BNBUSDT', 'SOLUSDT', 'AVAXUSDT', 'DOGEUSDT']:
        if sym not in coins:
            continue
        for thr in [1.0, 2.0, 3.0]:
            pnls = h4_asia_reversal(coins[sym], thr)
            results.append(summarize(f"H4 asia rev {sym} thr{thr}%", pnls))

    # rank by PnL
    results.sort(key=lambda r: -r['pnl'])
    print(f"\n{'config':<30} {'n':>5} {'pnl$':>8} {'wr%':>6} {'avg$':>7} {'mdd%':>7} {'sharpe':>7}")
    print("-" * 75)
    for r in results[:30]:
        print(f"{r['label']:<30} {r['n']:>5} {r['pnl']:>8.2f} {r['wr']:>6.1f} {r['avg']:>7.3f} {r['mdd']:>7.1f} {r['sharpe']:>7.2f}")
    print("\n...")
    print("WORST 10:")
    for r in results[-10:]:
        print(f"{r['label']:<30} {r['n']:>5} {r['pnl']:>8.2f} {r['wr']:>6.1f} {r['avg']:>7.3f} {r['mdd']:>7.1f} {r['sharpe']:>7.2f}")

    # baseline reminder
    print(f"\n>>> baseline (current G405 thr=80): n=10 pnl=+$76.11 wr=30%")

    out = ROOT / "h1_h4_results.json"
    out.write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
