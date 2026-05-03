#!/usr/bin/env python3
"""Quick check: 현재 시장에서 vol_expansion 신호가 어디 있는지."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from quant_phase23_paper_bot import (
    init_exchange, fetch_klines, compute_features, vol_expansion_signal,
    UNIVERSE, HISTORY_BARS,
)
import numpy as np

ex = init_exchange()
print(f"Checking vol_expansion signal across {UNIVERSE}\n")

for sym in UNIVERSE:
    try:
        klines = fetch_klines(ex, sym, HISTORY_BARS)
        ind = compute_features(klines)
        if ind is None:
            print(f"{sym}: insufficient data"); continue
        n = len(ind["close"])
        # Check last 50 bars for any signal
        print(f"=== {sym} ===")
        print(f"  Latest closed bar: ts={int(ind['ts'][-2])}  close={ind['close'][-2]:.6f}")
        print(f"  mom24={ind['mom24'][-2]*100:+5.2f}%  vol_r={ind['vol_r'][-2]:.2f}  "
              f"bb_w_rank={ind['bb_width_rank'][-2]:.2f}  close>BB_up={ind['close'][-2]>ind['bb_upper'][-2]}")
        # Find recent signals
        signals = [i for i in range(max(0, n-100), n-1) if vol_expansion_signal(ind, i)]
        if signals:
            print(f"  Signals in last 100 bars: {len(signals)}")
            for i in signals[-5:]:
                print(f"    @ idx={i} (bars ago={n-1-i})  px={ind['close'][i]:.6f}  "
                      f"mom24={ind['mom24'][i]*100:+.1f}%  vol_r={ind['vol_r'][i]:.2f}  "
                      f"bb_w_rank={ind['bb_width_rank'][i]:.2f}")
        else:
            print(f"  No signal in last 100 bars")
        # Live status
        live = vol_expansion_signal(ind, n-2)
        print(f"  CURRENT: {'🔥 SIGNAL!' if live else 'no signal'}")
        print()
    except Exception as e:
        print(f"{sym}: error {e}\n")
