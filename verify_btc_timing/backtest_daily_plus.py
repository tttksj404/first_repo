"""Find strategies that trade >= 1/day (>= 365/year) + positive PnL + reasonable MDD.

H8: Multi-coin session momentum (각 alt별 독립 결정)
H9: Multi-coin Asia reversal w/ SL (각 alt별 독립)
H10: Multi-coin BB squeeze (각 alt별)
"""
import json, sys
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent
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
    df['hour'] = df['dt'].dt.hour
    df['date'] = df['dt'].dt.date
    return df


def summarize(label, pnls):
    if not pnls:
        return {'label': label, 'n': 0, 'pnl': 0, 'wr': 0, 'mdd': 0, 'sharpe': 0,
                'per_day': 0, 'final': EQUITY}
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
        'label': label, 'n': len(pnls), 'pnl': round(sum(pnls), 2),
        'wr': round(100 * wins / len(pnls), 1),
        'mdd': round(mdd, 1),
        'sharpe': round(sharpe, 2),
        'per_day': round(len(pnls) / 365, 2),
        'final': round(EQUITY + sum(pnls), 2),
    }


# ── H8: Multi-coin Europe session momentum ──
def h8_multi_session(coins, target_long=75, target_short=25, lookback_days=30,
                     margin=5.0, lev=10.0, min_coins=2):
    """매일 16 UTC 모든 alt 평가, p75 초과 = LONG, p25 미만 = SHORT.
    여러 코인 동시 가능."""
    pnls = []
    fee = margin * lev * COST_RT
    daily_per_coin = {}
    for sym in ALTS:
        df = coins[sym].copy()
        df.set_index(pd.to_datetime(df['ts'], unit='ms', utc=True), inplace=True)
        df['date'] = df.index.date
        df['hour'] = df.index.hour
        d = []
        for date, grp in df.groupby('date'):
            eo = grp[grp['hour'] == 8]['o'].values
            ec = grp[grp['hour'] == 16]['o'].values
            uc = grp[grp['hour'] == 23]['c'].values
            if not (len(eo) and len(ec) and len(uc)):
                continue
            d.append({'date': date, 'eur_ret': (ec[0]/eo[0]-1) if eo[0] > 0 else 0,
                      'us_open': float(ec[0]), 'us_close': float(uc[0])})
        daily_per_coin[sym] = pd.DataFrame(d)

    if not daily_per_coin:
        return pnls
    n_days = max(len(d) for d in daily_per_coin.values())

    for i in range(lookback_days, n_days):
        for sym, df_d in daily_per_coin.items():
            if i >= len(df_d):
                continue
            prev = df_d.iloc[i-lookback_days:i]['eur_ret']
            cur = df_d.iloc[i]['eur_ret']
            if len(prev) < lookback_days - 5:
                continue
            p75 = np.percentile(prev, target_long)
            p25 = np.percentile(prev, target_short)
            ep = df_d.iloc[i]['us_open']
            xp = df_d.iloc[i]['us_close']
            if cur > p75:
                roe = (xp/ep - 1) * lev
                pnls.append(margin * roe - fee)
            elif cur < p25:
                roe = (ep/xp - 1) * lev
                pnls.append(margin * roe - fee)
    return pnls


# ── H9: Multi-coin Asia reversal + SL ──
def h9_multi_asia_rev(coins, threshold_pct=1.0, sl_pct=5.0, margin=5.0, lev=10.0):
    pnls = []
    fee = margin * lev * COST_RT
    thr = threshold_pct / 100.0
    sl = sl_pct / 100.0
    daily_per_coin = {}
    for sym in ALTS:
        df = coins[sym].copy()
        df.set_index(pd.to_datetime(df['ts'], unit='ms', utc=True), inplace=True)
        df['date'] = df.index.date
        df['hour'] = df.index.hour
        d = []
        for date, grp in df.groupby('date'):
            bars = grp.set_index('hour')
            if 0 not in bars.index or 8 not in bars.index:
                continue
            try:
                a_open = float(bars.loc[0, 'o']) if not isinstance(bars.loc[0, 'o'], pd.Series) else float(bars.loc[0, 'o'].iloc[0])
                a_close = float(bars.loc[8, 'o']) if not isinstance(bars.loc[8, 'o'], pd.Series) else float(bars.loc[8, 'o'].iloc[0])
                a_high = float(grp[grp['hour'].between(0, 8)]['h'].max())
                a_low = float(grp[grp['hour'].between(0, 8)]['l'].min())
            except Exception:
                continue
            d.append({'date': date, 'asia_ret': (a_close/a_open - 1) if a_open > 0 else 0,
                      'open': a_open, 'high': a_high, 'low': a_low, 'close': a_close})
        daily_per_coin[sym] = pd.DataFrame(d)

    n_days = max((len(d) for d in daily_per_coin.values()), default=0)
    for i in range(1, n_days):
        for sym, df_d in daily_per_coin.items():
            if i >= len(df_d) or i-1 < 0:
                continue
            prev_ret = df_d.iloc[i-1]['asia_ret']
            cur = df_d.iloc[i]
            ep = cur['open']
            xp = cur['close']
            ch_high = cur['high']
            ch_low = cur['low']
            if prev_ret > thr:
                sl_price = ep * (1 + sl)
                if ch_high >= sl_price:
                    roe = -sl * lev
                else:
                    roe = (ep/xp - 1) * lev
                pnls.append(margin * roe - fee)
            elif prev_ret < -thr:
                sl_price = ep * (1 - sl)
                if ch_low <= sl_price:
                    roe = -sl * lev
                else:
                    roe = (xp/ep - 1) * lev
                pnls.append(margin * roe - fee)
    return pnls


# ── H10: Daily multi-coin breakout (each coin's prev day H/L) ──
def h10_daily_breakout(coins, k=0.5, hold_h=12, margin=5.0, lev=10.0):
    """Larry Williams style but multi-coin. target = today_open + k*(prev_high-prev_low).
    Entry: when intra-day high >= target. Exit: end of day (24 UTC)."""
    pnls = []
    fee = margin * lev * COST_RT
    for sym in ALTS:
        df = coins[sym].copy()
        df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
        df['date'] = df['dt'].dt.date
        daily = df.groupby('date').agg(
            first_open=('o', 'first'), max_h=('h', 'max'),
            min_l=('l', 'min'), last_c=('c', 'last'),
        ).reset_index()
        for i in range(1, len(daily)-1):
            prev = daily.iloc[i-1]
            today = daily.iloc[i]
            rng = prev['max_h'] - prev['min_l']
            if rng <= 0:
                continue
            target = today['first_open'] + k * rng
            if today['max_h'] >= target:
                ep = target
                xp = today['last_c']
                roe = (xp/ep - 1) * lev
                pnls.append(margin * roe - fee)
    return pnls


def main():
    print("loading data...")
    coins = {s: load(s) for s in UNIVERSE}

    results = []
    print("H8 multi-coin session momentum...")
    for thr_long, thr_short in [(70, 30), (75, 25), (80, 20)]:
        for margin in [3.0, 5.0, 8.0]:
            for lev in [10.0, 15.0]:
                pnls = h8_multi_session(coins, thr_long, thr_short, 30, margin, lev)
                results.append(summarize(f"H8 sess p{thr_long}/{thr_short} m{margin} L{lev}", pnls))

    print("H9 multi-coin Asia rev + SL...")
    for thr_pct in [0.8, 1.0, 1.5, 2.0]:
        for sl_pct in [3.0, 5.0, 8.0]:
            for margin in [3.0, 5.0]:
                pnls = h9_multi_asia_rev(coins, thr_pct, sl_pct, margin, 10.0)
                results.append(summarize(f"H9 asia thr{thr_pct}% SL{sl_pct}% m{margin}", pnls))

    print("H10 multi-coin Larry Williams...")
    for k in [0.3, 0.5, 0.7]:
        for margin in [3.0, 5.0]:
            pnls = h10_daily_breakout(coins, k, 12, margin, 10.0)
            results.append(summarize(f"H10 LW k{k} m{margin}", pnls))

    # report
    print(f"\n=== QUALIFIED: per_day >= 1.0, pnl > 0, mdd > -50% ===")
    print(f"{'config':<35} {'n':>4} {'/d':>5} {'pnl$':>8} {'wr%':>6} {'mdd%':>7} {'sharpe':>7}")
    print("-" * 80)
    qualified = [r for r in results if r['per_day'] >= 1.0 and r['pnl'] > 0 and r['mdd'] > -50]
    qualified.sort(key=lambda r: -r['sharpe'])
    for r in qualified:
        print(f"{r['label']:<35} {r['n']:>4} {r['per_day']:>5.2f} {r['pnl']:>8.2f} {r['wr']:>6.1f} {r['mdd']:>7.1f} {r['sharpe']:>7.2f}")

    print(f"\n=== ALL by per_day desc (top 20) ===")
    results.sort(key=lambda r: -r['per_day'])
    for r in results[:20]:
        flag = "[OK]" if (r['per_day'] >= 1.0 and r['pnl'] > 0 and r['mdd'] > -50) else "    "
        print(f"{flag} {r['label']:<33} {r['n']:>4} {r['per_day']:>5.2f} {r['pnl']:>8.2f} {r['wr']:>6.1f} {r['mdd']:>7.1f} {r['sharpe']:>7.2f}")

    out = ROOT / "daily_plus_results.json"
    out.write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
