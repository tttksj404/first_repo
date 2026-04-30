"""A/B/C/D backtest:
  A = baseline (current G405 emulator logic, no BTC gate)
  B = + BTC 20-day MA entry gate
  C = + asymmetric exit (close all if BTC < BTC 10-day MA)
  D = B + C combined

Uses the SAME compute_ch1_score that the live emulator uses,
so no logic drift between paper-live and backtest.
"""
import json
import sys
import statistics
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent / "local_emulators" / "_shared"))
from g002_mingogogo_ch1_backtest import compute_ch1_score, atr_pct  # type: ignore

DATA = ROOT / "data"
UNIVERSE_ALL = ['BTCUSDT', 'DOGEUSDT', 'PEPEUSDT', 'ARBUSDT', 'OPUSDT',
                'AVAXUSDT', 'SUIUSDT', 'ADAUSDT', 'APTUSDT', 'BNBUSDT',
                'DOTUSDT', 'LINKUSDT', 'NEARUSDT', 'SOLUSDT', 'UNIUSDT', 'XRPUSDT']
ALTS = [s for s in UNIVERSE_ALL if s != 'BTCUSDT']

# Strategy params (same as G405 emulator)
EQUITY_USD = 100.0
SIZE_PCT = 0.20
LEVERAGE = 20.0
THRESHOLD = 80
HOLD_BARS = 24
MAX_CONC = 5
ATR_GUARD_PCT = 6.0
COST_BPS_RT = 16.0  # round-trip
CYCLE_HOURS = 1  # we'll evaluate every 1h bar (instead of 5min) for backtest speed

# BTC market timing windows (in 1h bars)
BTC_MA_LONG = 20 * 24   # 20 days
BTC_MA_SHORT = 10 * 24  # 10 days


def load_bars(symbol):
    raw = json.loads((DATA / f"{symbol}.json").read_text())
    df = pd.DataFrame(raw, columns=['open_time', 'open_price', 'high_price', 'low_price', 'close_price', 'base_volume'])
    df['quote_volume'] = df['close_price'] * df['base_volume']  # rough
    return df


def precompute_btc_ma(btc_df):
    close = btc_df['close_price'].values
    ma_long = pd.Series(close).rolling(BTC_MA_LONG).mean().values
    ma_short = pd.Series(close).rolling(BTC_MA_SHORT).mean().values
    return close, ma_long, ma_short


def precompute_scores(coins):
    """compute_ch1_score uses rolling indicators (causal) — call ONCE per coin
    on full series, then sample at each bar. No lookahead because rolling
    windows only see past data."""
    out = {}
    for sym, df in coins.items():
        if sym == 'BTCUSDT':
            continue
        try:
            s_series, _ = compute_ch1_score(df)
            a_series = atr_pct(df['high_price'], df['low_price'], df['close_price'], 14)
            scores = s_series.values.astype(float)
            atrs = a_series.values.astype(float)
        except Exception as e:
            print(f"  {sym}: SKIP ({e})")
            continue
        out[sym] = (scores, atrs)
        print(f"  {sym}: {(~np.isnan(scores)).sum()} valid scores  range=[{np.nanmin(scores):.1f},{np.nanmax(scores):.1f}]")
    return out


def run_strategy(coins, btc_close, btc_ma_long, btc_ma_short, scores, label,
                 use_btc_entry_gate=False, use_btc_exit_gate=False):
    n = len(btc_close)
    fee_per_trade = EQUITY_USD * SIZE_PCT * LEVERAGE * (COST_BPS_RT / 10000.0)  # round-trip fee
    margin_per_trade = EQUITY_USD * SIZE_PCT
    open_positions = {}  # sym -> (entry_price, entry_idx, atr_at_entry)
    closed_trades = []  # list of {sym, entry_idx, exit_idx, pnl_usd, reason}
    equity_history = []

    for i in range(BTC_MA_LONG + 1, n - 1):  # need warmup for MA20
        # ── exit logic (process every bar) ──
        btc_exit_signal = use_btc_exit_gate and (btc_close[i] < btc_ma_short[i])
        for sym in list(open_positions.keys()):
            (entry_p, entry_i, entry_atr) = open_positions[sym]
            cur_p = coins[sym]['close_price'].iloc[i]
            held = i - entry_i
            ret = (cur_p / entry_p - 1.0)
            roe = ret * LEVERAGE  # leveraged return on margin

            exit_reason = None
            if held >= HOLD_BARS:
                exit_reason = 'hold'
            elif roe <= -ATR_GUARD_PCT / 100.0:  # SL ~ -6% ROE
                exit_reason = 'sl'
            elif btc_exit_signal:
                exit_reason = 'btc_gate'

            if exit_reason:
                pnl = margin_per_trade * roe - fee_per_trade
                closed_trades.append({
                    'sym': sym, 'entry_idx': entry_i, 'exit_idx': i,
                    'pnl_usd': pnl, 'reason': exit_reason, 'roe_pct': roe * 100,
                })
                del open_positions[sym]

        # ── entry logic ──
        if use_btc_entry_gate and btc_close[i] < btc_ma_long[i]:
            equity_history.append(_calc_equity(closed_trades))
            continue  # skip entry in bear regime

        if len(open_positions) >= MAX_CONC:
            equity_history.append(_calc_equity(closed_trades))
            continue

        # find best alt by score
        candidates = []
        for sym in ALTS:
            if sym in open_positions:
                continue
            score_arr, atr_arr = scores[sym]
            s = score_arr[i]
            a = atr_arr[i]
            if np.isnan(s) or np.isnan(a):
                continue
            if s < THRESHOLD:
                continue
            if a > ATR_GUARD_PCT:  # too volatile, skip
                continue
            candidates.append((sym, s, a))

        if candidates:
            candidates.sort(key=lambda x: -x[1])  # highest score first
            best_sym, best_s, best_atr = candidates[0]
            entry_p = coins[best_sym]['close_price'].iloc[i]
            open_positions[best_sym] = (entry_p, i, best_atr)

        equity_history.append(_calc_equity(closed_trades))

    # close any leftover at last bar
    last_i = n - 1
    for sym, (entry_p, entry_i, _) in open_positions.items():
        cur_p = coins[sym]['close_price'].iloc[last_i]
        ret = (cur_p / entry_p - 1.0)
        roe = ret * LEVERAGE
        pnl = margin_per_trade * roe - fee_per_trade
        closed_trades.append({
            'sym': sym, 'entry_idx': entry_i, 'exit_idx': last_i,
            'pnl_usd': pnl, 'reason': 'eof', 'roe_pct': roe * 100,
        })

    return _summarize(label, closed_trades, equity_history)


def _calc_equity(closed_trades):
    return EQUITY_USD + sum(t['pnl_usd'] for t in closed_trades)


def _summarize(label, trades, equity_history):
    if not trades:
        return {'label': label, 'trades': 0, 'wins': 0, 'losses': 0, 'wr_pct': 0.0,
                'pnl': 0.0, 'final_equity': EQUITY_USD, 'mdd_pct': 0.0,
                'sharpe': 0.0, 'avg_per_trade': 0.0, 'exits': {}}
    pnls = [t['pnl_usd'] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p <= 0)
    total_pnl = sum(pnls)
    wr = wins / len(pnls) if pnls else 0
    eq_arr = np.array(equity_history) if equity_history else np.array([EQUITY_USD])
    peak = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peak) / peak
    mdd_pct = float(dd.min() * 100) if len(dd) else 0.0
    # daily returns approx (one bar = 1h)
    if len(eq_arr) > 24:
        daily_eq = eq_arr[::24]
        daily_ret = np.diff(daily_eq) / daily_eq[:-1]
        sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(365)) if daily_ret.std() > 0 else 0
    else:
        sharpe = 0
    n_btc_exits = sum(1 for t in trades if t['reason'] == 'btc_gate')
    n_hold = sum(1 for t in trades if t['reason'] == 'hold')
    n_sl = sum(1 for t in trades if t['reason'] == 'sl')
    return {
        'label': label,
        'trades': len(trades),
        'wins': wins, 'losses': losses, 'wr_pct': round(wr * 100, 1),
        'pnl': round(total_pnl, 2),
        'final_equity': round(EQUITY_USD + total_pnl, 2),
        'mdd_pct': round(mdd_pct, 1),
        'sharpe': round(sharpe, 2),
        'avg_per_trade': round(total_pnl / len(pnls), 3),
        'exits': {'hold': n_hold, 'sl': n_sl, 'btc_gate': n_btc_exits, 'eof': len(trades) - n_hold - n_sl - n_btc_exits},
    }


def main():
    print("loading data...")
    coins = {sym: load_bars(sym) for sym in UNIVERSE_ALL}
    btc = coins['BTCUSDT']
    btc_close, btc_ma_long, btc_ma_short = precompute_btc_ma(btc)
    print(f"  {len(btc)} bars per coin, ~{len(btc)/24:.0f} days")

    print("precomputing scores (slow ~3-5 min)...")
    scores = precompute_scores(coins)

    print("\nrunning A/B/C/D variants...")
    results = []
    for label, gate_in, gate_out in [
        ('A baseline',     False, False),
        ('B +entry gate',  True,  False),
        ('C +exit gate',   False, True),
        ('D both gates',   True,  True),
    ]:
        print(f"  {label}...")
        r = run_strategy(coins, btc_close, btc_ma_long, btc_ma_short, scores,
                          label, gate_in, gate_out)
        results.append(r)

    # report
    print("\n" + "=" * 90)
    print(f"{'variant':<18} {'trades':>7} {'wr%':>6} {'pnl$':>8} {'final$':>8} {'mdd%':>7} {'sharpe':>7} {'avg$':>7}  exits")
    print("-" * 90)
    for r in results:
        print(f"{r['label']:<18} {r['trades']:>7} {r['wr_pct']:>6.1f} {r['pnl']:>8.2f} {r['final_equity']:>8.2f} {r['mdd_pct']:>7.1f} {r['sharpe']:>7.2f} {r['avg_per_trade']:>7.3f}  {r['exits']}")
    print("=" * 90)

    out = ROOT / "results.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nresults saved -> {out}")


if __name__ == '__main__':
    main()
