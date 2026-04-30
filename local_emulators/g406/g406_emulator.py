"""G406 paper-live emulator (Linux/cloud)."""
import json, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

APP = Path(__file__).parent
sys.path.insert(0, str(APP))
from g002_mingogogo_ch1_backtest import compute_ch1_score, atr_pct  # type: ignore

OUT = APP / "runtime"; OUT.mkdir(parents=True, exist_ok=True)
TRADES = OUT / "trades.jsonl"
STATE  = OUT / "state.json"
LOG    = OUT / "emulator.log"

UNIVERSE = ['DOGEUSDT', 'PEPEUSDT', 'ARBUSDT', 'OPUSDT', 'AVAXUSDT', 'SUIUSDT', 'ADAUSDT', 'APTUSDT', 'BNBUSDT', 'DOTUSDT', 'LINKUSDT', 'NEARUSDT', 'SOLUSDT', 'UNIUSDT', 'XRPUSDT']
EQUITY_USD=100.0; SIZE_PCT=0.15; LEVERAGE=15.0; THRESHOLD=80; HOLD_BARS=24
MAX_CONC=8; ATR_GUARD_PCT=8.0; COST_BPS_RT=16.0; CYCLE_SECONDS=300
BINANCE_KLINES="https://api.binance.com/api/v3/klines"

def log(m):
    line=f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {m}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f: f.write(line+"\n")

def load_state():
    if STATE.exists():
        try: return json.loads(STATE.read_text(encoding="utf-8"))
        except: pass
    return {"started_at": datetime.now(timezone.utc).isoformat(),"open_positions":{},"closed_count":0,"wins":0,"losses":0,"cumulative_pnl_usd":0.0,"last_cycle":None}

def save_state(s):
    s["last_cycle"]=datetime.now(timezone.utc).isoformat()
    STATE.write_text(json.dumps(s,indent=2,ensure_ascii=False), encoding="utf-8")

def append_trade(e):
    with TRADES.open("a", encoding="utf-8") as f: f.write(json.dumps(e,ensure_ascii=False)+"\n")

def fetch_klines(symbol, limit=200):
    url=f"{BINANCE_KLINES}?symbol={symbol}&interval=1h&limit={limit}"
    try:
        req=urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            chunk=json.loads(r.read())
    except Exception as e:
        log(f"  fetch {symbol} FAIL: {e}"); return None
    if not chunk: return None
    bars=[]
    for b in chunk[:-1]:
        bars.append({"open_time":b[0],"open_price":float(b[1]),"high_price":float(b[2]),"low_price":float(b[3]),
                     "close_price":float(b[4]),"base_volume":float(b[5]),"quote_volume":float(b[7])})
    return pd.DataFrame(bars)

def evaluate(symbol):
    df=fetch_klines(symbol)
    if df is None or len(df)<100: return None
    score,_=compute_ch1_score(df)
    atrp=atr_pct(df["high_price"],df["low_price"],df["close_price"],14)
    return {"symbol":symbol,"score":float(score.iloc[-1]) if not pd.isna(score.iloc[-1]) else 0.0,
            "atr_pct":float(atrp.iloc[-1]) if not pd.isna(atrp.iloc[-1]) else 0.0,
            "close":float(df["close_price"].iloc[-1]),"bar_ts":int(df["open_time"].iloc[-1])}

def cycle(state):
    now_ms=int(time.time()*1000)
    open_pos=state["open_positions"]
    expired=[s for s,p in open_pos.items() if now_ms >= p["entry_ts_ms"]+HOLD_BARS*3600*1000]
    for sym in expired:
        pos=open_pos.pop(sym)
        df=fetch_klines(sym, limit=2)
        if df is None:
            log(f"  EXIT {sym} fetch fail keeping open"); open_pos[sym]=pos; continue
        ec=float(df["close_price"].iloc[-1])
        gp=(ec/pos["entry_close"]-1)*100
        npp=(gp/100 - COST_BPS_RT/10000)*LEVERAGE
        if npp < -0.90: npp=-0.90
        pnl=round(EQUITY_USD*SIZE_PCT*npp, 4)
        state["cumulative_pnl_usd"]=round(state["cumulative_pnl_usd"]+pnl, 4)
        state["closed_count"]+=1
        if pnl>0: state["wins"]+=1
        else: state["losses"]+=1
        append_trade({"type":"EXIT","symbol":sym,"entry_ts_ms":pos["entry_ts_ms"],"entry_close":pos["entry_close"],
                      "exit_ts_ms":now_ms,"exit_close":ec,"gross_pct":round(gp,4),"net_pct_levered":round(npp,4),
                      "pnl_usd":pnl,"score_at_entry":pos.get("score"),"atr_pct_at_entry":pos.get("atr_pct")})
        log(f"  EXIT  {sym}: {gp:+.2f}% gross / {npp*100:+.2f}% lev / PnL ${pnl:+.2f}")

    cands=[]
    for sym in UNIVERSE:
        if sym in open_pos: continue
        info=evaluate(sym)
        if info: cands.append(info)
        time.sleep(0.05)
    cands.sort(key=lambda x:x["score"], reverse=True)

    for info in cands:
        sym=info["symbol"]
        if len(open_pos)>=MAX_CONC: break
        if info["score"]<THRESHOLD: continue
        if info["atr_pct"]>ATR_GUARD_PCT:
            log(f"  SKIP {sym}: score {info['score']:.1f} but ATR {info['atr_pct']:.2f}% > {ATR_GUARD_PCT}%"); continue
        pos={"entry_ts_ms":now_ms,"entry_close":info["close"],"score":info["score"],"atr_pct":info["atr_pct"]}
        open_pos[sym]=pos
        append_trade({"type":"ENTRY","symbol":sym,"entry_ts_ms":now_ms,"entry_close":info["close"],
                      "score":info["score"],"atr_pct":info["atr_pct"],
                      "size_usd_margin":EQUITY_USD*SIZE_PCT,"notional_usd":EQUITY_USD*SIZE_PCT*LEVERAGE})
        log(f"  ENTRY {sym}: score {info['score']:.1f} ATR {info['atr_pct']:.2f}% close {info['close']:.6f}")

    state["open_positions"]=open_pos
    save_state(state)
    top5=[(c["symbol"], round(c["score"],1)) for c in cands[:5]]
    log(f"  HEARTBEAT open={len(open_pos)} closed={state['closed_count']} W/L={state['wins']}/{state['losses']} cumPnL=${state['cumulative_pnl_usd']:+.2f} top5={top5}")

def main():
    log(f"=== G406 emulator START === eq=${EQUITY_USD} size={SIZE_PCT} lev={LEVERAGE}x thr={THRESHOLD} hold={HOLD_BARS}h max_conc={MAX_CONC} atr_guard={ATR_GUARD_PCT}%")
    log(f"universe ({len(UNIVERSE)}): {','.join(UNIVERSE)}")
    state=load_state()
    while True:
        try: cycle(state)
        except KeyboardInterrupt: log("STOP"); break
        except Exception as e: log(f"CYCLE_ERROR: {type(e).__name__}: {e}")
        time.sleep(CYCLE_SECONDS)

if __name__=="__main__": main()
