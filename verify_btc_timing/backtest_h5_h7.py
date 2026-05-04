"""H5: Larry Williams Volatility Breakout — the most cited rule in crypto.
   Target = open + k × (yesterday_high - yesterday_low)
   Entry: when intraday price breaks above target
   Exit: end of UTC day (23:59)
   SL: midpoint between yesterday_low and entry_price

H6: BTC-Pair mean reversion (cointegration-style)
   Trade z-score of (alt_log - beta * btc_log)

H7: Walk-forward of H3 DOGE session momentum (4 folds × 90 days)
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

EQUITY = 100.0
MARGIN = 20.0
LEV = 20.0
COST_RT = 16.0 / 10000.0


def load(sym):
    raw = json.loads((DATA / f"{sym}.json").read_text())
    df = pd.DataFrame(raw, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
    df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df['date'] = df['dt'].dt.date
    df['hour'] = df['dt'].dt.hour
    return df


def summarize(label, pnls, capped=True):
    if not pnls:
        return {'label': label, 'n': 0, 'pnl': 0, 'wr': 0, 'mdd': 0, 'final': EQUITY}
    if capped:
        # account blowup: cap cumulative loss at -EQUITY
        eq = EQUITY
        for p in pnls:
            eq += p
            if eq <= 1:
                eq = 1
                break
        final = max(eq, 1)
    else:
        final = EQUITY + sum(pnls)
    cum = np.cumsum(pnls) + EQUITY
    peak = np.maximum.accumulate(cum)
    mdd = float(((cum - peak) / np.maximum(peak, 1)).min() * 100)
    wins = sum(1 for p in pnls if p > 0)
    return {
        'label': label, 'n': len(pnls), 'pnl': round(sum(pnls), 2),
        'final': round(final, 2),
        'wr': round(100 * wins / len(pnls), 1),
        'mdd': round(mdd, 1),
        'avg': round(np.mean(pnls), 3),
    }


# ── H5: Larry Williams Volatility Breakout ──
def h5_lw_breakout(df, k=0.5):
    """For each UTC day, calc target = today_open + k × (prev_high - prev_low).
    If today's high reaches target, enter long at target. Exit at day close."""
    daily = df.groupby('date').agg(
        first_open=('o', 'first'),
        max_h=('h', 'max'),
        min_l=('l', 'min'),
        last_c=('c', 'last'),
    ).reset_index()
    pnls = []
    fee = MARGIN * LEV * COST_RT
    for i in range(1, len(daily) - 1):
        prev = daily.iloc[i - 1]
        today = daily.iloc[i]
        rng = prev['max_h'] - prev['min_l']
        if rng <= 0:
            continue
        target = today['first_open'] + k * rng
        if today['max_h'] >= target:  # breakout occurred
            entry_p = target
            exit_p = today['last_c']
            sl_price = (prev['min_l'] + entry_p) / 2  # SL = midpoint
            # check if SL hit before close (approximate via min_l)
            if today['min_l'] <= sl_price:
                # assume SL hit
                roe = (sl_price / entry_p - 1.0) * LEV
            else:
                roe = (exit_p / entry_p - 1.0) * LEV
            pnls.append(MARGIN * roe - fee)
    return pnls


# ── H6: BTC-Pair mean reversion ──
def h6_btc_pair(df_btc, df_alt, lookback=24*30, z_thr=2.0, hold_max_h=24):
    """beta-neutral spread = log(alt) - beta * log(btc), beta from rolling reg.
    Long when z < -thr (alt cheap), short when z > +thr.
    Exit when |z| < 0.5 or hold_max_h reached."""
    n = min(len(df_btc), len(df_alt))
    btc_c = df_btc['c'].values[:n]
    alt_c = df_alt['c'].values[:n]
    log_btc = np.log(btc_c)
    log_alt = np.log(alt_c)
    pnls = []
    fee = MARGIN * LEV * COST_RT
    pos = None  # (side, entry_alt, entry_btc, entry_idx, beta)
    for i in range(lookback + 1, n - 1):
        # rolling beta
        x = log_btc[i - lookback:i]
        y = log_alt[i - lookback:i]
        x_m = x.mean(); y_m = y.mean()
        cov = ((x - x_m) * (y - y_m)).mean()
        var = ((x - x_m) ** 2).mean()
        if var <= 0:
            continue
        beta = cov / var
        spread_hist = y - beta * x
        spread_now = log_alt[i] - beta * log_btc[i]
        z = (spread_now - spread_hist.mean()) / (spread_hist.std() + 1e-9)

        if pos is not None:
            side, ea, eb, ei, _ = pos
            held = i - ei
            cur_z_abs = abs(z)
            if cur_z_abs < 0.5 or held >= hold_max_h:
                # close
                cur_alt = alt_c[i]
                cur_btc = btc_c[i]
                if side == 'long':
                    alt_ret = cur_alt / ea - 1.0
                    btc_ret = cur_btc / eb - 1.0
                    net = alt_ret - beta * btc_ret  # beta-hedged
                else:
                    alt_ret = ea / cur_alt - 1.0
                    btc_ret = eb / cur_btc - 1.0
                    net = alt_ret - beta * btc_ret
                roe = net * LEV
                pnls.append(MARGIN * roe - fee)
                pos = None
            continue

        if z < -z_thr:
            pos = ('long', alt_c[i], btc_c[i], i, beta)
        elif z > z_thr:
            pos = ('short', alt_c[i], btc_c[i], i, beta)
    return pnls


# ── H7: H3 DOGE session walk-forward (4 folds) ──
def h7_walk_forward(df, p_long=75, p_short=25, lookback_days=30):
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
        daily.append({'date': date, 'eur_ret': (ec[0] / eo[0] - 1) if eo[0] > 0 else 0,
                      'us_open': float(ec[0]), 'us_close': float(uc[0])})
    df_d = pd.DataFrame(daily)
    n = len(df_d)
    fold_size = n // 4
    folds = []
    fee = MARGIN * LEV * COST_RT
    for f in range(4):
        s = f * fold_size + lookback_days
        e = (f + 1) * fold_size if f < 3 else n
        pnls = []
        for i in range(s, e):
            if i < lookback_days:
                continue
            prev = df_d.iloc[i - lookback_days:i]['eur_ret']
            cur = df_d.iloc[i]['eur_ret']
            p75 = np.percentile(prev, p_long)
            p25 = np.percentile(prev, p_short)
            ep = df_d.iloc[i]['us_open']
            xp = df_d.iloc[i]['us_close']
            if cur > p75:
                roe = (xp / ep - 1) * LEV
                pnls.append(MARGIN * roe - fee)
            elif cur < p25:
                roe = (ep / xp - 1) * LEV
                pnls.append(MARGIN * roe - fee)
        folds.append((f, summarize(f"fold{f+1}", pnls)))
    return folds


def main():
    print("loading data...")
    coins = {s: load(s) for s in UNIVERSE}
    btc = coins['BTCUSDT']

    results = []

    # ── H5 sweep across all coins and k values ──
    print("H5 Larry Williams Volatility Breakout...")
    for sym in UNIVERSE:
        for k in [0.3, 0.5, 0.7]:
            pnls = h5_lw_breakout(coins[sym], k)
            results.append(summarize(f"H5 LW {sym} k={k}", pnls))

    # ── H6 BTC pairs (selected coins) ──
    print("H6 BTC-pair mean reversion...")
    for alt in ['DOGEUSDT', 'AVAXUSDT', 'SOLUSDT', 'BNBUSDT', 'LINKUSDT']:
        for thr in [1.5, 2.0, 2.5]:
            pnls = h6_btc_pair(btc, coins[alt], 24 * 30, thr)
            results.append(summarize(f"H6 BTC-{alt} z>{thr}", pnls))

    # ── H7 walk-forward H3 DOGE ──
    print("H7 walk-forward H3 DOGE...")
    folds = h7_walk_forward(coins['DOGEUSDT'])
    for f, s in folds:
        s['label'] = f"H7 DOGE-WF {s['label']}"
        results.append(s)

    # report top 30
    results.sort(key=lambda r: -r['pnl'])
    print(f"\n{'config':<35} {'n':>5} {'pnl$':>8} {'wr%':>6} {'avg$':>7} {'mdd%':>7}")
    print("-" * 75)
    for r in results[:30]:
        print(f"{r['label']:<35} {r['n']:>5} {r['pnl']:>8.2f} {r['wr']:>6.1f} {r['avg']:>7.3f} {r['mdd']:>7.1f}")

    print("\nWORST 10:")
    for r in results[-10:]:
        print(f"{r['label']:<35} {r['n']:>5} {r['pnl']:>8.2f} {r['wr']:>6.1f} {r['avg']:>7.3f} {r['mdd']:>7.1f}")

    # H7 specific summary
    print("\n=== H7 Walk-Forward DOGE Session (4 folds) ===")
    h7 = [r for r in results if r['label'].startswith('H7')]
    for r in sorted(h7, key=lambda x: x['label']):
        sign = "+" if r['pnl'] > 0 else ""
        print(f"  {r['label']:<25} n={r['n']:>3} pnl={sign}${r['pnl']:.2f} wr={r['wr']}% mdd={r['mdd']}%")
    pos_folds = sum(1 for r in h7 if r['pnl'] > 0)
    print(f"  positive folds: {pos_folds}/4")
    print(f"  -> walk-forward {'PASS (>=3/4)' if pos_folds >= 3 else 'FAIL'}")

    out = ROOT / "h5_h7_results.json"
    out.write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
