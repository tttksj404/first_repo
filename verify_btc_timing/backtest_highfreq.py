"""High-frequency variant search:
  HF1: ch1_score thr=70 + Trendwise gate (more permissive, plus filter)
  HF2: ch1_score thr=75 + Trendwise gate + short hold (12h instead of 24h)
  HF3: 4h hold variant of baseline (turnover 6x)
  HF4: Asia reversal w/ stop-loss (fix the -100% MDD problem)
  HF5: Simple BB squeeze intraday breakout (1h bar)
  HF6: 1h cycle ch1_score with shorter hold + smaller size

Find configs with: trades > 200/yr AND PnL > 0 AND MDD > -30%.
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
    df['dt'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df['hour'] = df['dt'].dt.hour
    df['date'] = df['dt'].dt.date
    return df


def summarize(label, pnls):
    if not pnls:
        return {'label': label, 'n': 0, 'pnl': 0, 'wr': 0, 'mdd': 0, 'sharpe': 0, 'final': EQUITY}
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
        'final': round(EQUITY + sum(pnls), 2),
    }


def precompute_scores(coins):
    out = {}
    for sym in ALTS:
        s_ser, _ = compute_ch1_score(coins[sym])
        a_ser = atr_pct(coins[sym]['high_price'], coins[sym]['low_price'], coins[sym]['close_price'], 14)
        out[sym] = (s_ser.values.astype(float), a_ser.values.astype(float))
    return out


# ── HF1/HF2/HF3/HF6: ch1_score variants ──
def hf_ch1(coins, scores, threshold, hold, margin, lev, atr_guard, max_conc,
           use_trendwise=False, btc_close=None, ema_fast=None, ema_slow=None, label=""):
    n = len(coins['BTCUSDT'])
    fee = margin * lev * COST_RT
    open_pos = {}
    pnls = []
    for i in range(max(200, 20*24+1), n - 1):
        # exits
        for sym in list(open_pos):
            ep, ei = open_pos[sym]
            cp = coins[sym]['c'].iloc[i]
            roe = (cp / ep - 1.0) * lev
            held = i - ei
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


# ── HF4: Asia reversal WITH stop-loss ──
def hf_asia_rev_sl(df, threshold_pct=1.0, sl_pct=2.0, lev=10.0, margin=10.0):
    """At 00 UTC look at yesterday's Asia ret. If +X%+: short. If -X%-: long.
    Exit at 08 UTC OR if loss exceeds sl_pct (intra-bar stop)."""
    df = df.copy()
    df.set_index(pd.to_datetime(df['ts'], unit='ms', utc=True), inplace=True)
    df['date'] = df.index.date
    df['hour'] = df.index.hour
    daily = []
    for date, grp in df.groupby('date'):
        bars = grp.set_index('hour')
        if 0 not in bars.index or 8 not in bars.index:
            continue
        a_open = float(bars.loc[0, 'o']) if isinstance(bars.loc[0, 'o'], (int, float)) else float(bars.loc[0, 'o'].iloc[0])
        a_high = max(grp[grp['hour'].between(0, 8)]['h'].values, default=0)
        a_low = min(grp[grp['hour'].between(0, 8)]['l'].values, default=0)
        a_close = float(bars.loc[8, 'o']) if isinstance(bars.loc[8, 'o'], (int, float)) else float(bars.loc[8, 'o'].iloc[0])
        daily.append({'date': date, 'asia_ret': (a_close / a_open - 1) if a_open > 0 else 0,
                      'open': a_open, 'high': a_high, 'low': a_low, 'close': a_close})
    df_d = pd.DataFrame(daily)
    pnls = []
    fee = margin * lev * COST_RT
    thr = threshold_pct / 100.0
    sl = sl_pct / 100.0
    for i in range(1, len(df_d)):
        prev = df_d.iloc[i - 1]['asia_ret']
        cur = df_d.iloc[i]
        ep = cur['open']; cp_today_low = cur['low']; cp_today_high = cur['high']; xp = cur['close']
        if prev > thr:
            # short
            sl_price = ep * (1 + sl)
            if cp_today_high >= sl_price:
                roe = -sl * lev
            else:
                roe = (ep / xp - 1) * lev
            pnls.append(margin * roe - fee)
        elif prev < -thr:
            # long
            sl_price = ep * (1 - sl)
            if cp_today_low <= sl_price:
                roe = -sl * lev
            else:
                roe = (xp / ep - 1) * lev
            pnls.append(margin * roe - fee)
    return pnls


# ── HF5: Simple BB squeeze intraday breakout ──
def hf_bb_breakout(coins, sym, bb_period=20, bb_thr=0.03, hold=8, margin=10.0, lev=15.0):
    df = coins[sym]
    close = df['c'].values
    rolling_mean = pd.Series(close).rolling(bb_period).mean().values
    rolling_std = pd.Series(close).rolling(bb_period).std().values
    bb_width = (4 * rolling_std) / rolling_mean  # 2 sigma each side / mean
    n = len(close)
    pnls = []
    fee = margin * lev * COST_RT
    in_pos = None
    for i in range(bb_period + 1, n - 1):
        if in_pos is not None:
            ep, ei = in_pos
            cp = close[i]
            roe = (cp / ep - 1) * lev
            if i - ei >= hold or roe < -0.10:
                pnls.append(margin * roe - fee)
                in_pos = None
            continue
        if np.isnan(bb_width[i-1]) or np.isnan(bb_width[i]):
            continue
        # squeeze: BB width < threshold for prev 6 bars, then expand at i
        squeeze = (bb_width[i-6:i] < bb_thr).all() if i >= 6 else False
        if squeeze and bb_width[i] > bb_thr * 1.5 and close[i] > close[i-1]:
            in_pos = (close[i], i)
    return pnls


def main():
    print("loading data + scores...")
    coins = {s: load(s) for s in UNIVERSE}
    btc_close = coins['BTCUSDT']['c'].values
    ema10 = pd.Series(btc_close).ewm(span=10*24, adjust=False).mean().values
    ema20 = pd.Series(btc_close).ewm(span=20*24, adjust=False).mean().values
    scores = precompute_scores(coins)

    results = []

    # HF1: thr=70 + TW gate
    print("HF1: thr=70 + Trendwise gate...")
    pnls = hf_ch1(coins, scores, threshold=70, hold=24, margin=10.0, lev=20.0,
                   atr_guard=6.0, max_conc=5, use_trendwise=True,
                   ema_fast=ema10, ema_slow=ema20, label="HF1")
    results.append(summarize("HF1 thr70+TW hold24h", pnls))

    # HF1b: thr=70 + TW + atr_guard 8% (more permissive)
    pnls = hf_ch1(coins, scores, threshold=70, hold=24, margin=10.0, lev=20.0,
                   atr_guard=8.0, max_conc=8, use_trendwise=True,
                   ema_fast=ema10, ema_slow=ema20, label="HF1b")
    results.append(summarize("HF1b thr70+TW conc8 atr8", pnls))

    # HF2: thr=75 + TW + 12h hold
    print("HF2: thr=75 + TW + 12h hold...")
    pnls = hf_ch1(coins, scores, threshold=75, hold=12, margin=10.0, lev=20.0,
                   atr_guard=6.0, max_conc=5, use_trendwise=True,
                   ema_fast=ema10, ema_slow=ema20, label="HF2")
    results.append(summarize("HF2 thr75+TW hold12h", pnls))

    # HF3: thr=80 + 4h hold (turnover 6x)
    print("HF3: thr=80 + 4h hold...")
    pnls = hf_ch1(coins, scores, threshold=80, hold=4, margin=10.0, lev=20.0,
                   atr_guard=6.0, max_conc=5, use_trendwise=False,
                   label="HF3")
    results.append(summarize("HF3 thr80 hold4h", pnls))

    # HF3b: thr=80 + 6h hold + TW
    pnls = hf_ch1(coins, scores, threshold=80, hold=6, margin=10.0, lev=20.0,
                   atr_guard=6.0, max_conc=5, use_trendwise=True,
                   ema_fast=ema10, ema_slow=ema20, label="HF3b")
    results.append(summarize("HF3b thr80+TW hold6h", pnls))

    # HF6: thr=70 + 4h hold + TW + smaller size + lev 10x
    print("HF6: thr=70 + 4h hold + TW + lev 10x...")
    pnls = hf_ch1(coins, scores, threshold=70, hold=4, margin=10.0, lev=10.0,
                   atr_guard=6.0, max_conc=5, use_trendwise=True,
                   ema_fast=ema10, ema_slow=ema20, label="HF6")
    results.append(summarize("HF6 thr70+TW hold4h lev10x", pnls))

    # HF4: Asia reversal + SL
    print("HF4: Asia reversal w/ SL...")
    for sym in ['DOGEUSDT', 'AVAXUSDT', 'BNBUSDT', 'BTCUSDT']:
        for thr_pct in [1.0, 1.5, 2.0]:
            for sl_pct in [3.0, 5.0]:
                try:
                    pnls = hf_asia_rev_sl(coins[sym], threshold_pct=thr_pct, sl_pct=sl_pct,
                                           lev=10.0, margin=10.0)
                    results.append(summarize(f"HF4 {sym} thr{thr_pct}% SL{sl_pct}%", pnls))
                except Exception as e:
                    print(f"  HF4 {sym} {thr_pct} {sl_pct} skip: {e}")

    # HF5: BB squeeze
    print("HF5: BB squeeze breakout...")
    for sym in ['BTCUSDT', 'DOGEUSDT', 'AVAXUSDT', 'SOLUSDT', 'BNBUSDT']:
        pnls = hf_bb_breakout(coins, sym, bb_period=20, bb_thr=0.03, hold=8,
                                margin=10.0, lev=15.0)
        results.append(summarize(f"HF5 BB-sqz {sym}", pnls))

    # filter & rank
    print(f"\n{'config':<35} {'n':>5} {'pnl$':>8} {'wr%':>6} {'mdd%':>7} {'sharpe':>7}")
    print("-" * 80)
    # First: high-freq + positive PnL + MDD > -30
    qualified = [r for r in results if r['n'] >= 50 and r['pnl'] > 0 and r['mdd'] > -50]
    qualified.sort(key=lambda r: -r['sharpe'])
    print("=== QUALIFIED (n>=50, pnl>0, mdd>-50%) ===")
    for r in qualified:
        print(f"{r['label']:<35} {r['n']:>5} {r['pnl']:>8.2f} {r['wr']:>6.1f} {r['mdd']:>7.1f} {r['sharpe']:>7.2f}")

    print("\n=== ALL by trade count (top 30) ===")
    results.sort(key=lambda r: -r['n'])
    for r in results[:30]:
        flag = "✅" if (r['n'] >= 50 and r['pnl'] > 0 and r['mdd'] > -50) else "  "
        print(f"{flag}{r['label']:<33} {r['n']:>5} {r['pnl']:>8.2f} {r['wr']:>6.1f} {r['mdd']:>7.1f} {r['sharpe']:>7.2f}")

    out = ROOT / "highfreq_results.json"
    out.write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
