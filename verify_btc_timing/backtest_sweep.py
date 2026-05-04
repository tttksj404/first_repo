"""Sweep BTC MA window lengths AND threshold to test robustness.
If Cherry's market timing helps at ANY reasonable param combo, it should show up here."""
import json
import sys
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent / "local_emulators" / "_shared"))
from g002_mingogogo_ch1_backtest import compute_ch1_score, atr_pct  # type: ignore

DATA = ROOT / "data"
UNIVERSE_ALL = ['BTCUSDT', 'DOGEUSDT', 'PEPEUSDT', 'ARBUSDT', 'OPUSDT',
                'AVAXUSDT', 'SUIUSDT', 'ADAUSDT', 'APTUSDT', 'BNBUSDT',
                'DOTUSDT', 'LINKUSDT', 'NEARUSDT', 'SOLUSDT', 'UNIUSDT', 'XRPUSDT']
ALTS = [s for s in UNIVERSE_ALL if s != 'BTCUSDT']

EQUITY_USD = 100.0
SIZE_PCT = 0.20
LEVERAGE = 20.0
HOLD_BARS = 24
MAX_CONC = 5
ATR_GUARD_PCT = 6.0
COST_BPS_RT = 16.0


def load_bars(symbol):
    raw = json.loads((DATA / f"{symbol}.json").read_text())
    return pd.DataFrame(raw, columns=['open_time', 'open_price', 'high_price', 'low_price', 'close_price', 'base_volume'])


def run(threshold, ma_long_days, ma_short_days, gate_in, gate_out, label,
        coins, btc_close, scores):
    n = len(btc_close)
    ma_long_bars = ma_long_days * 24
    ma_short_bars = ma_short_days * 24
    btc_ma_long = pd.Series(btc_close).rolling(ma_long_bars).mean().values
    btc_ma_short = pd.Series(btc_close).rolling(ma_short_bars).mean().values
    fee = EQUITY_USD * SIZE_PCT * LEVERAGE * (COST_BPS_RT / 10000.0)
    margin = EQUITY_USD * SIZE_PCT
    open_pos = {}
    closed = []
    eq_hist = []

    start_i = max(ma_long_bars + 1, 200)
    for i in range(start_i, n - 1):
        # exits
        btc_exit = gate_out and not np.isnan(btc_ma_short[i]) and (btc_close[i] < btc_ma_short[i])
        for sym in list(open_pos.keys()):
            ep, ei, _ = open_pos[sym]
            cp = coins[sym]['close_price'].iloc[i]
            roe = (cp / ep - 1.0) * LEVERAGE
            held = i - ei
            reason = None
            if held >= HOLD_BARS:
                reason = 'hold'
            elif roe <= -ATR_GUARD_PCT / 100.0:
                reason = 'sl'
            elif btc_exit:
                reason = 'btc_gate'
            if reason:
                closed.append({'pnl': margin * roe - fee, 'reason': reason})
                del open_pos[sym]

        # entries
        if gate_in and not np.isnan(btc_ma_long[i]) and btc_close[i] < btc_ma_long[i]:
            eq_hist.append(EQUITY_USD + sum(t['pnl'] for t in closed))
            continue
        if len(open_pos) >= MAX_CONC:
            eq_hist.append(EQUITY_USD + sum(t['pnl'] for t in closed))
            continue
        cands = []
        for sym in ALTS:
            if sym in open_pos:
                continue
            sa, aa = scores[sym]
            s = sa[i]; a = aa[i]
            if np.isnan(s) or np.isnan(a) or s < threshold or a > ATR_GUARD_PCT:
                continue
            cands.append((sym, s))
        if cands:
            cands.sort(key=lambda x: -x[1])
            best = cands[0][0]
            ep = coins[best]['close_price'].iloc[i]
            open_pos[best] = (ep, i, None)
        eq_hist.append(EQUITY_USD + sum(t['pnl'] for t in closed))

    last = n - 1
    for sym, (ep, ei, _) in open_pos.items():
        cp = coins[sym]['close_price'].iloc[last]
        roe = (cp / ep - 1.0) * LEVERAGE
        closed.append({'pnl': margin * roe - fee, 'reason': 'eof'})

    if not closed:
        return {'label': label, 'n': 0, 'pnl': 0, 'wr': 0, 'mdd': 0}
    pnls = [t['pnl'] for t in closed]
    wins = sum(1 for p in pnls if p > 0)
    eq = np.array(eq_hist) if eq_hist else np.array([EQUITY_USD])
    peak = np.maximum.accumulate(eq)
    mdd = float(((eq - peak) / peak).min() * 100) if len(eq) else 0
    return {
        'label': label, 'n': len(closed), 'pnl': round(sum(pnls), 2),
        'wr': round(100 * wins / len(closed), 1), 'mdd': round(mdd, 1),
    }


def main():
    coins = {sym: load_bars(sym) for sym in UNIVERSE_ALL}
    btc_close = coins['BTCUSDT']['close_price'].values

    print("computing scores...")
    scores = {}
    for sym in ALTS:
        s_ser, _ = compute_ch1_score(coins[sym])
        a_ser = atr_pct(coins[sym]['high_price'], coins[sym]['low_price'], coins[sym]['close_price'], 14)
        scores[sym] = (s_ser.values.astype(float), a_ser.values.astype(float))

    rows = []
    for thr in [60, 65, 70, 75, 80]:
        # baseline (no gates)
        r = run(thr, 20, 10, False, False, f"thr{thr}_base", coins, btc_close, scores)
        rows.append(r)
        # entry gate variations
        for ma_l in [3, 5, 10, 20]:
            r = run(thr, ma_l, 10, True, False, f"thr{thr}_in{ma_l}d", coins, btc_close, scores)
            rows.append(r)
        # exit gate variations
        for ma_s in [2, 3, 5, 10]:
            r = run(thr, 20, ma_s, False, True, f"thr{thr}_out{ma_s}d", coins, btc_close, scores)
            rows.append(r)

    # report
    print(f"\n{'config':<22} {'n':>5} {'pnl$':>8} {'wr%':>6} {'mdd%':>7}")
    print("-" * 55)
    base_pnls = {}
    for r in rows:
        marker = ""
        if "_base" in r['label']:
            base_pnls[r['label'].split('_')[0]] = r['pnl']
        else:
            base_key = r['label'].split('_')[0]
            base = base_pnls.get(base_key, 0)
            if r['pnl'] > base * 1.05:
                marker = "  [BETTER]"
            elif r['pnl'] < base * 0.95:
                marker = "  [WORSE]"
        print(f"{r['label']:<22} {r['n']:>5} {r['pnl']:>8.2f} {r['wr']:>6.1f} {r['mdd']:>7.1f}{marker}")

    # final verdict: did ANY gate variant beat its baseline?
    print("\n=== VERDICT ===")
    improvements = 0
    total = 0
    for r in rows:
        if "_base" in r['label']:
            continue
        base_key = r['label'].split('_')[0]
        base = base_pnls.get(base_key, 0)
        total += 1
        if r['pnl'] > base * 1.05:
            improvements += 1
    print(f"Gate variants tested: {total}")
    print(f"  beat baseline by 5%+: {improvements}")
    print(f"  tied or worse: {total - improvements}")


if __name__ == '__main__':
    main()
