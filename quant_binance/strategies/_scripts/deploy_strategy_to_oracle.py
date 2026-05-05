"""Deploy a strategy variant to Oracle Cloud as additional systemd service.

Each strategy gets its own:
  - emulator script (~/g{ID}/g{id}_emulator.py)
  - runtime dir   (~/g{ID}/runtime/)
  - systemd unit  (g{id}-emulator.service)

Usage:
  python deploy_strategy_to_oracle.py G186 G187
"""
import base64, gzip, sys, subprocess, shlex
from pathlib import Path

ROOT = Path(r"C:\Users\SSAFY\Desktop\first_repo")
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"

UNIV_FULL = ["DOGEUSDT","PEPEUSDT","WIFUSDT","ARBUSDT","OPUSDT","AVAXUSDT","SUIUSDT","ADAUSDT","APTUSDT","BNBUSDT","DOTUSDT","LINKUSDT","LTCUSDT","NEARUSDT","SOLUSDT","UNIUSDT","XRPUSDT","BTCUSDT"]
UNIV_NO_DEAD = [s for s in UNIV_FULL if s not in {"WIFUSDT","LTCUSDT","BTCUSDT"}]
UNIV_TOP10 = ["DOGEUSDT","PEPEUSDT","SOLUSDT","ARBUSDT","ADAUSDT","LINKUSDT","DOTUSDT","NEARUSDT","AVAXUSDT","UNIUSDT"]
UNIV_MEMECOIN = ["DOGEUSDT","PEPEUSDT","WIFUSDT"]

STRATEGY_PARAMS = {
    "G185": {"folder":"G185_size40_100usd",          "size":0.40,"lev":5.0,"thr":80,"hold":24,"max_conc":5,"atr":8.0,"universe":UNIV_FULL},
    "G186": {"folder":"G186_size45_100usd",          "size":0.45,"lev":5.0,"thr":80,"hold":24,"max_conc":5,"atr":8.0,"universe":UNIV_FULL},
    "G187": {"folder":"G187_lev6_100usd",            "size":0.40,"lev":6.0,"thr":80,"hold":24,"max_conc":5,"atr":8.0,"universe":UNIV_FULL},
    "G188": {"folder":"G188_hold48_100usd",          "size":0.40,"lev":5.0,"thr":80,"hold":48,"max_conc":5,"atr":8.0,"universe":UNIV_FULL},
    "G189": {"folder":"G189_thr85_100usd",           "size":0.40,"lev":5.0,"thr":85,"hold":24,"max_conc":5,"atr":8.0,"universe":UNIV_FULL},
    "G190": {"folder":"G190_size45_lev6_100usd",     "size":0.45,"lev":6.0,"thr":80,"hold":24,"max_conc":5,"atr":8.0,"universe":UNIV_FULL},
    "G191": {"folder":"G191_lev6_conc8_100usd",      "size":0.40,"lev":6.0,"thr":80,"hold":24,"max_conc":8,"atr":8.0,"universe":UNIV_FULL},
    "G192": {"folder":"G192_lev6_atr6_100usd",       "size":0.40,"lev":6.0,"thr":80,"hold":24,"max_conc":5,"atr":6.0,"universe":UNIV_FULL},
    "G193": {"folder":"G193_lev6_thr78_100usd",      "size":0.40,"lev":6.0,"thr":78,"hold":24,"max_conc":5,"atr":8.0,"universe":UNIV_FULL},
    "G194": {"folder":"G194_lev6_hold16_100usd",     "size":0.40,"lev":6.0,"thr":80,"hold":16,"max_conc":5,"atr":8.0,"universe":UNIV_FULL},
    "G210": {"folder":"G210_g191_drop_dead",         "size":0.40,"lev":6.0,"thr":80,"hold":24,"max_conc":8,"atr":8.0,"universe":UNIV_NO_DEAD},
    "G220": {"folder":"G220_g191_top10",             "size":0.40,"lev":6.0,"thr":80,"hold":24,"max_conc":8,"atr":8.0,"universe":UNIV_TOP10},
    # G300 series — REALISTIC $100 with peak leverage <= 10x (cross margin)
    "G300": {"folder":"G300_real100_5x",              "size":0.20,"lev":5.0, "thr":80,"hold":24,"max_conc":5,"atr":8.0,"universe":UNIV_NO_DEAD},
    "G301": {"folder":"G301_real100_6x",              "size":0.20,"lev":6.0, "thr":80,"hold":24,"max_conc":5,"atr":8.0,"universe":UNIV_NO_DEAD},
    "G302": {"folder":"G302_real100_conc8_lev6",      "size":0.15,"lev":6.0, "thr":80,"hold":24,"max_conc":8,"atr":8.0,"universe":UNIV_NO_DEAD},
    "G303": {"folder":"G303_real100_8x",              "size":0.20,"lev":8.0, "thr":80,"hold":24,"max_conc":5,"atr":8.0,"universe":UNIV_NO_DEAD},
    "G304": {"folder":"G304_real100_conc8_lev8",      "size":0.15,"lev":8.0, "thr":80,"hold":24,"max_conc":8,"atr":8.0,"universe":UNIV_NO_DEAD},
    "G305": {"folder":"G305_real100_10x_max",         "size":0.20,"lev":10.0,"thr":80,"hold":24,"max_conc":5,"atr":8.0,"universe":UNIV_NO_DEAD},
    "G306": {"folder":"G306_real100_top10_conc8",     "size":0.15,"lev":6.0, "thr":80,"hold":24,"max_conc":8,"atr":8.0,"universe":UNIV_TOP10},
    "G307": {"folder":"G307_real100_atr6_6x",         "size":0.20,"lev":6.0, "thr":80,"hold":24,"max_conc":5,"atr":6.0,"universe":UNIV_NO_DEAD},
    # G400 series — extended 10x-20x peak leverage, $100 cross-margin
    "G400": {"folder":"G400_real100_10x_baseline",    "size":0.20,"lev":10.0,"thr":80,"hold":24,"max_conc":5,"atr":8.0,"universe":UNIV_NO_DEAD},
    "G401": {"folder":"G401_real100_12x",             "size":0.20,"lev":12.0,"thr":80,"hold":24,"max_conc":5,"atr":8.0,"universe":UNIV_NO_DEAD},
    "G402": {"folder":"G402_real100_15x",             "size":0.20,"lev":15.0,"thr":80,"hold":24,"max_conc":5,"atr":8.0,"universe":UNIV_NO_DEAD},
    "G403": {"folder":"G403_real100_20x_max",         "size":0.20,"lev":20.0,"thr":80,"hold":24,"max_conc":5,"atr":8.0,"universe":UNIV_NO_DEAD},
    "G405": {"folder":"G405_real100_20x_atr6",        "size":0.20,"lev":20.0,"thr":80,"hold":24,"max_conc":5,"atr":6.0,"universe":UNIV_NO_DEAD},
    "G406": {"folder":"G406_real100_15x_conc8",       "size":0.15,"lev":15.0,"thr":80,"hold":24,"max_conc":8,"atr":8.0,"universe":UNIV_NO_DEAD},
    "G408": {"folder":"G408_real100_10x_conc8",       "size":0.20,"lev":10.0,"thr":80,"hold":24,"max_conc":8,"atr":8.0,"universe":UNIV_NO_DEAD},
    # G710 series — TRUE MAX GAMBLE on $50, size 1.0 + max_conc 1
    # NOTE: equity=$50 implicit (per backtest); emulator template still uses $100 hardcoded so PnL scaling 2x — for paper-live comparison this is OK
    "G710": {"folder":"G710_meme_lev20_size1",        "size":1.00,"lev":20.0,"thr":80,"hold":24,"max_conc":1,"atr":8.0,"universe":UNIV_MEMECOIN},
    "G711": {"folder":"G711_meme_lev30_size1",        "size":1.00,"lev":30.0,"thr":80,"hold":24,"max_conc":1,"atr":8.0,"universe":UNIV_MEMECOIN},
    # G800 series — grid search winners (1458 combos / 138 robust pass)
    # Both use atr_min=3% (NEW dim: require minimum volatility for entry)
    "G801": {"folder":"G801_atr3to10_lev20",          "size":0.20,"lev":20.0,"thr":80,"hold":24,"max_conc":5,"atr":10.0,"atr_min":3.0,"universe":UNIV_NO_DEAD},
    "G802": {"folder":"G802_hold36_atr3to10",         "size":0.20,"lev":20.0,"thr":80,"hold":36,"max_conc":5,"atr":10.0,"atr_min":3.0,"universe":UNIV_NO_DEAD},
}

EMULATOR_TEMPLATE = r'''"""{SID} paper-live emulator (Linux/cloud)."""
import json, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

HOME = Path.home()
APP = HOME / "{SID_LOWER}"
sys.path.insert(0, str(APP))
from g002_mingogogo_ch1_backtest import compute_ch1_score, atr_pct  # type: ignore

OUT = APP / "runtime"; OUT.mkdir(parents=True, exist_ok=True)
TRADES = OUT / "trades.jsonl"
STATE  = OUT / "state.json"
LOG    = OUT / "emulator.log"

UNIVERSE = {UNIVERSE_LIST}
EQUITY_USD={EQUITY}; SIZE_PCT={SIZE}; LEVERAGE={LEV}; THRESHOLD={THR}; HOLD_BARS={HOLD}
MAX_CONC={MAX_CONC}; ATR_GUARD_PCT={ATR}; ATR_MIN_PCT={ATR_MIN}; COST_BPS_RT=16.0; CYCLE_SECONDS=300
BINANCE_KLINES="https://api.binance.com/api/v3/klines"

def log(m):
    line=f"[{{datetime.now(timezone.utc).isoformat(timespec='seconds')}}] {{m}}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f: f.write(line+"\n")

def load_state():
    if STATE.exists():
        try: return json.loads(STATE.read_text(encoding="utf-8"))
        except: pass
    return {{"started_at": datetime.now(timezone.utc).isoformat(),"open_positions":{{}},"closed_count":0,"wins":0,"losses":0,"cumulative_pnl_usd":0.0,"last_cycle":None}}

def save_state(s):
    s["last_cycle"]=datetime.now(timezone.utc).isoformat()
    STATE.write_text(json.dumps(s,indent=2,ensure_ascii=False), encoding="utf-8")

def append_trade(e):
    with TRADES.open("a", encoding="utf-8") as f: f.write(json.dumps(e,ensure_ascii=False)+"\n")

def fetch_klines(symbol, limit=200):
    url=f"{{BINANCE_KLINES}}?symbol={{symbol}}&interval=1h&limit={{limit}}"
    try:
        req=urllib.request.Request(url, headers={{"User-Agent":"Mozilla/5.0"}})
        with urllib.request.urlopen(req, timeout=15) as r:
            chunk=json.loads(r.read())
    except Exception as e:
        log(f"  fetch {{symbol}} FAIL: {{e}}"); return None
    if not chunk: return None
    bars=[]
    for b in chunk[:-1]:
        bars.append({{"open_time":b[0],"open_price":float(b[1]),"high_price":float(b[2]),"low_price":float(b[3]),
                     "close_price":float(b[4]),"base_volume":float(b[5]),"quote_volume":float(b[7])}})
    return pd.DataFrame(bars)

def evaluate(symbol):
    df=fetch_klines(symbol)
    if df is None or len(df)<100: return None
    score,_=compute_ch1_score(df)
    atrp=atr_pct(df["high_price"],df["low_price"],df["close_price"],14)
    return {{"symbol":symbol,"score":float(score.iloc[-1]) if not pd.isna(score.iloc[-1]) else 0.0,
            "atr_pct":float(atrp.iloc[-1]) if not pd.isna(atrp.iloc[-1]) else 0.0,
            "close":float(df["close_price"].iloc[-1]),"bar_ts":int(df["open_time"].iloc[-1])}}

def cycle(state):
    now_ms=int(time.time()*1000)
    open_pos=state["open_positions"]
    expired=[s for s,p in open_pos.items() if now_ms >= p["entry_ts_ms"]+HOLD_BARS*3600*1000]
    for sym in expired:
        pos=open_pos.pop(sym)
        df=fetch_klines(sym, limit=2)
        if df is None:
            log(f"  EXIT {{sym}} fetch fail keeping open"); open_pos[sym]=pos; continue
        ec=float(df["close_price"].iloc[-1])
        gp=(ec/pos["entry_close"]-1)*100
        npp=(gp/100 - COST_BPS_RT/10000)*LEVERAGE
        if npp < -0.90: npp=-0.90
        pnl=round(EQUITY_USD*SIZE_PCT*npp, 4)
        state["cumulative_pnl_usd"]=round(state["cumulative_pnl_usd"]+pnl, 4)
        state["closed_count"]+=1
        if pnl>0: state["wins"]+=1
        else: state["losses"]+=1
        append_trade({{"type":"EXIT","symbol":sym,"entry_ts_ms":pos["entry_ts_ms"],"entry_close":pos["entry_close"],
                      "exit_ts_ms":now_ms,"exit_close":ec,"gross_pct":round(gp,4),"net_pct_levered":round(npp,4),
                      "pnl_usd":pnl,"score_at_entry":pos.get("score"),"atr_pct_at_entry":pos.get("atr_pct")}})
        log(f"  EXIT  {{sym}}: {{gp:+.2f}}% gross / {{npp*100:+.2f}}% lev / PnL ${{pnl:+.2f}}")

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
            log(f"  SKIP {{sym}}: score {{info['score']:.1f}} but ATR {{info['atr_pct']:.2f}}% > {{ATR_GUARD_PCT}}%"); continue
        if info["atr_pct"]<ATR_MIN_PCT:
            log(f"  SKIP {{sym}}: score {{info['score']:.1f}} but ATR {{info['atr_pct']:.2f}}% < {{ATR_MIN_PCT}}% (vol filter)"); continue
        pos={{"entry_ts_ms":now_ms,"entry_close":info["close"],"score":info["score"],"atr_pct":info["atr_pct"]}}
        open_pos[sym]=pos
        append_trade({{"type":"ENTRY","symbol":sym,"entry_ts_ms":now_ms,"entry_close":info["close"],
                      "score":info["score"],"atr_pct":info["atr_pct"],
                      "size_usd_margin":EQUITY_USD*SIZE_PCT,"notional_usd":EQUITY_USD*SIZE_PCT*LEVERAGE}})
        log(f"  ENTRY {{sym}}: score {{info['score']:.1f}} ATR {{info['atr_pct']:.2f}}% close {{info['close']:.6f}}")

    state["open_positions"]=open_pos
    save_state(state)
    top5=[(c["symbol"], round(c["score"],1)) for c in cands[:5]]
    log(f"  HEARTBEAT open={{len(open_pos)}} closed={{state['closed_count']}} W/L={{state['wins']}}/{{state['losses']}} cumPnL=${{state['cumulative_pnl_usd']:+.2f}} top5={{top5}}")

def main():
    log(f"=== {SID} emulator START === eq=${{EQUITY_USD}} size={{SIZE_PCT}} lev={{LEVERAGE}}x thr={{THRESHOLD}} hold={{HOLD_BARS}}h max_conc={{MAX_CONC}} atr_guard={{ATR_GUARD_PCT}}%")
    log(f"universe ({{len(UNIVERSE)}}): {{','.join(UNIVERSE)}}")
    state=load_state()
    while True:
        try: cycle(state)
        except KeyboardInterrupt: log("STOP"); break
        except Exception as e: log(f"CYCLE_ERROR: {{type(e).__name__}}: {{e}}")
        time.sleep(CYCLE_SECONDS)

if __name__=="__main__": main()
'''


def render_emulator(sid: str) -> str:
    p = STRATEGY_PARAMS[sid]
    return EMULATOR_TEMPLATE.format(
        SID=sid, SID_LOWER=sid.lower(),
        EQUITY=100.0, SIZE=p["size"], LEV=p["lev"], THR=p["thr"], HOLD=p["hold"],
        MAX_CONC=p["max_conc"], ATR=p["atr"], ATR_MIN=p.get("atr_min", 0.0),
        UNIVERSE_LIST=repr(p["universe"]),
    )


def ssh(cmd: str) -> tuple[int, str]:
    full = ["ssh", "g185", cmd]
    r = subprocess.run(full, capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out


def deploy(sid: str):
    print(f"\n=== deploying {sid} ===")
    code = render_emulator(sid)
    code_b64 = base64.b64encode(gzip.compress(code.encode("utf-8"))).decode()
    sid_lower = sid.lower()

    # 1) create dirs
    rc, out = ssh(f"mkdir -p ~/{sid_lower}/runtime")
    print(f"  mkdir: rc={rc}")

    # 2) upload emulator
    proc = subprocess.run(
        ["ssh", "g185", f"base64 -d | gunzip > ~/{sid_lower}/{sid_lower}_emulator.py"],
        input=code_b64, capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
    )
    print(f"  upload emulator: rc={proc.returncode}")

    # 3) symlink shared dependency
    rc, out = ssh(f"ln -sf ~/g185/g002_mingogogo_ch1_backtest.py ~/{sid_lower}/g002_mingogogo_ch1_backtest.py")
    print(f"  link dep: rc={rc}")

    # 4) systemd unit
    unit = f"""[Unit]
Description={sid} paper-live emulator
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/{sid_lower}
ExecStart=/usr/bin/python3 %h/{sid_lower}/{sid_lower}_emulator.py
Restart=always
RestartSec=30
StandardOutput=append:%h/{sid_lower}/runtime/stdout.log
StandardError=append:%h/{sid_lower}/runtime/stderr.log

[Install]
WantedBy=default.target
"""
    proc = subprocess.run(
        ["ssh", "g185", f"cat > ~/.config/systemd/user/{sid_lower}-emulator.service"],
        input=unit, capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
    )
    print(f"  unit file: rc={proc.returncode}")

    # 5) reload + enable + start
    rc, out = ssh(f"systemctl --user daemon-reload && systemctl --user enable --now {sid_lower}-emulator.service")
    print(f"  enable+start: rc={rc}")

    # 6) verify
    rc, out = ssh(f"sleep 5; systemctl --user is-active {sid_lower}-emulator; tail -5 ~/{sid_lower}/runtime/emulator.log 2>/dev/null")
    print(f"  status:\n{out}")


if __name__ == "__main__":
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["G186", "G187"]
    for sid in targets:
        if sid not in STRATEGY_PARAMS:
            print(f"unknown strategy {sid}, skip")
            continue
        deploy(sid)
    print("\n=== final cluster status ===")
    rc, out = ssh("for s in g185 g186 g187 g188 g189; do printf '%s: ' $s; systemctl --user is-active ${s}-emulator 2>/dev/null || echo 'not-deployed'; done")
    print(out)
