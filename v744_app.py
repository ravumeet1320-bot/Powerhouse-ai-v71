
from __future__ import annotations
import copy, threading, time, statistics, os
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse

import v742_app as base
import v743_app as prev
import v743_precision as precision
import v744_engine as core

VERSION=core.VERSION
RELEASE=core.RELEASE
ROOT=Path(__file__).parent
UI=ROOT/"static"/"v744.html"
app=prev.app
app.title="POWERHOUSE AI V74.4 — Move Capture & Execution OS"
app.version=VERSION

_LOCK=threading.RLock()
_ACTIVITY_PREV={}
_ACTIVITY_ROWS={}
_ACTIVITY_EVENTS=deque(maxlen=1200)
_ALERTS=deque(maxlen=1200)
_ALERT_SIG={}
_DERIV_CURRENT={}
_DERIV_HISTORY=defaultdict(lambda:deque(maxlen=360))
_DERIV_PREV={}
_STOP=threading.Event()
_ACTIVITY_THREAD=None
_DERIV_THREAD=None
INDEXES=("NIFTY","BANKNIFTY","MIDCPNIFTY","SENSEX")

def _iso(e=None): return datetime.fromtimestamp(float(e or time.time()),timezone.utc).isoformat()

def _push_alert(item):
    # V74.5 production-safety default: legacy server push is opt-in.
    # The legacy alert API remains preserved, but it cannot create notification storms
    # unless POWERHOUSE_LEGACY_PUSH=1 is explicitly configured.
    if os.getenv("POWERHOUSE_LEGACY_PUSH", "0") != "1": return
    if item.get("priority") not in ("P0","P1"): return
    try:
        precision.queue_push({"title":item.get("title") or "POWERHOUSE AI","body":item.get("body") or "Market state changed",
                              "priority":item.get("priority"),"url":"/","tag":item.get("kind") or "powerhouse-alert"})
    except Exception: pass

def _emit(priority,kind,symbol,title,body,payload=None,ttl=45):
    now=time.time(); sig=f"{priority}|{kind}|{symbol}|{body}"
    with _LOCK:
        if now-_ALERT_SIG.get(sig,0)<max(10,ttl): return None
        _ALERT_SIG[sig]=now
        item={"id":f"V744-{int(now*1000)}-{len(_ALERTS)}","epoch":now,"iso":_iso(now),"priority":priority,"kind":kind,
              "symbol":symbol,"title":title,"body":body,"payload":payload or {},"read_only":True}
        _ALERTS.append(item)
    _push_alert(item); return item

def _scanner_rows():
    try:
        with base._V74_BG_LOCK:
            rows=list((((base._V74_BG_RESULT or {}).get("radar") or {}).get("candidates") or []))
        return [dict(x) for x in rows if isinstance(x,dict)]
    except Exception:return []

def _activity_once():
    rows=_scanner_rows()
    if not rows:return
    now=time.time()
    with _LOCK: prev={k:dict(v) for k,v in _ACTIVITY_PREV.items()}
    for row in rows:
        sym=str(row.get("symbol") or "").upper()
        if not sym:continue
        act=core.sudden_activity(row,prev.get(sym)); act.update({"epoch":now,"iso":_iso(now)})
        with _LOCK:
            _ACTIVITY_ROWS[sym]=act; _ACTIVITY_PREV[sym]=dict(row)
        for ev in act.get("events") or []:
            e={"epoch":now,"iso":_iso(now),"symbol":sym,"priority":ev.get("priority"),"kind":ev.get("kind"),
               "text":ev.get("text"),"intensity":act.get("intensity"),"ltp":act.get("ltp"),"stage":act.get("stage")}
            with _LOCK:_ACTIVITY_EVENTS.append(e)
            _emit(str(ev.get("priority") or "P3"),str(ev.get("kind") or "ACTIVITY"),sym,
                  f"{sym} — {str(ev.get('kind') or 'ACTIVITY').replace('_',' ')}",str(ev.get("text") or "Market activity changed"),
                  {"intensity":act.get("intensity"),"stage":act.get("stage"),"ltp":act.get("ltp")},
                  35 if ev.get("priority")=="P1" else 60)

def _activity_loop():
    while not _STOP.wait(3):
        try:_activity_once()
        except Exception:pass

def _derivative_pulse(symbol):
    svc=base.service_for("default")
    if not getattr(svc,"authenticated",False) or getattr(svc,"token_invalid",False):return None
    chain=base._option_chain_snapshot(svc,symbol,force=False)
    with _LOCK: previous=copy.deepcopy(_DERIV_PREV.get(symbol) or {})
    summary=core.chain_summary(chain,previous); now=time.time(); summary.update({"symbol":symbol,"epoch":now,"iso":_iso(now)})
    with _LOCK:
        old=copy.deepcopy(_DERIV_CURRENT.get(symbol) or {})
        _DERIV_CURRENT[symbol]=summary; _DERIV_PREV[symbol]=summary
        _DERIV_HISTORY[symbol].append({"epoch":now,"iso":_iso(now),"symbol":symbol,"call_oi":summary.get("total_call_oi"),
            "put_oi":summary.get("total_put_oi"),"call_doi":summary.get("total_call_oi_change"),"put_doi":summary.get("total_put_oi_change"),
            "diff":summary.get("oi_diff_put_minus_call"),"doi_diff":summary.get("oi_change_diff_put_minus_call"),
            "pcr":summary.get("pcr_oi"),"pcr_volume":summary.get("pcr_volume"),"liquidity":summary.get("liquidity_score"),
            "call_state":summary.get("call_state"),"put_state":summary.get("put_state")})
    for key,label in (("call_state","CALL"),("put_state","PUT")):
        cur,prv=str(summary.get(key) or ""),str(old.get(key) or "")
        if prv and cur and cur!=prv and "WARMING" not in cur:
            _emit("P2",f"{label}_STATE",symbol,f"{symbol} — {cur}",f"{label} state {prv} → {cur}",
                  {"pcr":summary.get("pcr_oi"),"liquidity":summary.get("liquidity_score")},50)
    pcr,op=core.f(summary.get("pcr_oi")),core.f(old.get("pcr_oi"))
    if pcr is not None and op is not None and abs(pcr-op)>=.18:
        _emit("P2","PCR_SHIFT",symbol,f"{symbol} — PCR SHIFT",f"PCR {round(op,2)} → {round(pcr,2)}",{"pcr":pcr},60)
    liq,ol=core.f(summary.get("liquidity_score")),core.f(old.get("liquidity_score"))
    if liq is not None and ol is not None and abs(liq-ol)>=12:
        direction="INCREASING" if liq>ol else "DECREASING"
        _emit("P2" if liq>ol else "P1","OPTION_LIQUIDITY",symbol,f"{symbol} — LIQUIDITY {direction}",
              f"Option liquidity {round(ol,1)} → {round(liq,1)}",{"liquidity":liq},60)
    return summary

def _derivative_loop():
    # Resource-stable round-robin: all locked indexes are covered without
    # bursting four option-chain calls at the same instant on small instances.
    i=0
    while not _STOP.wait(6):
        symbol=INDEXES[i%len(INDEXES)]; i+=1
        try:_derivative_pulse(symbol)
        except Exception:pass

def _remove_get(path):
    app.router.routes[:]=[r for r in app.router.routes if not (getattr(r,"path",None)==path and "GET" in (getattr(r,"methods",None) or set()))]

_remove_get("/")
@app.get("/")
def home():
    h={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","Expires":"0","X-Powerhouse-Build":"V74.4-MASTER-VERIFIED"}
    if UI.exists():return FileResponse(UI,headers=h)
    return prev.v743_home()

@app.get("/v743")
def v743_locked_ui():
    ui=ROOT/"static"/"v743.html"
    if ui.exists():return FileResponse(ui,headers={"Cache-Control":"no-store","X-Powerhouse-Build":"V74.3-LOCKED-PRESERVED"})
    raise HTTPException(status_code=404,detail="V74.3 locked UI unavailable")

@app.get("/v744-light")
def v744_light_draft():
    ui=ROOT/"static"/"v744_light_draft.html"
    if ui.exists():return FileResponse(ui,headers={"Cache-Control":"no-store","X-Powerhouse-Build":"V74.4-LIGHT-DRAFT"})
    raise HTTPException(status_code=404,detail="V74.4 light draft unavailable")

def _call_rows():
    try:return list((base._V74_AUTO_CALLS or {}).get("results") or [])
    except Exception:return []

def _setup_cards():
    rows=_call_rows(); out=[]; option_symbols=set()
    for r in rows:
        c=copy.deepcopy(r.get("call") or {}); sym=str(r.get("symbol") or "").upper()
        action=str(c.get("action") or "WAIT").upper(); cand=str(c.get("candidate_action") or "").upper()
        is_option=action in ("BUY CE","BUY PE") or cand in ("BUY CE","BUY PE")
        if not is_option:continue
        option_symbols.add(sym); ez=c.get("entry_zone") or {}; tg=c.get("targets") or {}; actual=action if action!="WAIT" else cand
        status=str(c.get("status") or "WAIT").upper()
        if action=="WAIT" and cand in ("BUY CE","BUY PE"):status="TRIGGER WATCH" if status in ("WAIT","ULTRA WAIT") else status
        out.append({"symbol":sym,"instrument":"OPTION","action":actual if action!="WAIT" else "WATCH","option_action":actual,"status":status,
                    "strike":c.get("strike"),"expiry":c.get("expiry"),"cmp":c.get("premium"),"buy_above":ez.get("high") or ez.get("ideal"),
                    "entry_low":ez.get("low"),"entry_high":ez.get("high"),"sl":c.get("sl"),"targets":tg,"rr":c.get("risk_reward"),
                    "quality":c.get("meta_score") or c.get("call_quality"),"meta_label":c.get("meta_label"),"stage":c.get("stage") or r.get("stage"),
                    "why":list(c.get("why_now") or [])[:4],"blocked_by":list(c.get("blocked_by") or [])[:5],
                    "liquidity":{"score":c.get("liquidity_score"),"spread_pct":c.get("spread_pct"),"grade":c.get("liquidity_grade")},
                    "order_type":"MARKET OK" if core.f(c.get("liquidity_score"),0)>=80 and core.f(c.get("spread_pct"),99)<=.5 else
                                 "LIMIT PREFERRED" if core.f(c.get("liquidity_score"),0)>=60 else "LIMIT ONLY" if core.f(c.get("liquidity_score"),0)>=40 else "DO NOT ENTER",
                    "read_only":True})
    for row in _scanner_rows():
        sym=str(row.get("symbol") or "").upper()
        if not sym or sym in option_symbols or sym in INDEXES:continue
        plan=core.stock_trade_plan(row)
        if plan.get("status") in ("READY","TRIGGER NEAR") or core.f(row.get("score"),0)>=68:out.append(plan)
    rank={"READY":5,"ENTRY ACTIVE":5,"TRIGGER NEAR":4,"TRIGGER WATCH":3,"ARMING":3,"WATCH":2}
    out.sort(key=lambda x:(rank.get(str(x.get("status") or ""),1),core.f(x.get("quality"),core.f(x.get("score"),0)) or 0),reverse=True)
    return out[:24]

def _sector_rows():
    try:
        with base._V74_BG_LOCK:
            market=(((base._V74_BG_RESULT or {}).get("workspaces") or {}).get("market") or {})
            return [dict(x) for x in list(market.get("sectors") or [])[:40] if isinstance(x,dict)]
    except Exception:return []

def _index_cards(svc):
    try:
        with svc.lock: levels={k:dict(v) for k,v in getattr(svc,"index_levels",{}).items()}
    except Exception:levels={}
    cr=_call_rows(); out=[]
    for sym in INDEXES:
        lv=levels.get(sym) or {}; ltp,cp=core.f(lv.get("ltp")),core.f(lv.get("cp"))
        ar=next((x for x in cr if str(x.get("symbol") or "").upper()==sym),{}) or {}
        with _LOCK:der=copy.deepcopy(_DERIV_CURRENT.get(sym) or {})
        out.append({"symbol":sym,"ltp":ltp,"change_pct":core.pct(ltp,cp),"stage":ar.get("stage") or "WATCH","score":ar.get("score"),
                    "call":copy.deepcopy(ar.get("call") or {}),"derivative":der,"source":"Upstox in-memory index LTPC","read_only":True})
    return out

@app.get("/api/v74.4/command-center")
def command_center(request:Request):
    svc=base.request_service(request)
    if not svc.authenticated or getattr(svc,"token_invalid",False):raise HTTPException(status_code=401,detail=base._auth_detail(svc))
    try:provider=svc.status() or {}
    except Exception:provider={}
    scanner=base._background_meta()
    with _LOCK:
        activity=sorted((dict(x) for x in _ACTIVITY_ROWS.values()),key=lambda x:core.f(x.get("intensity"),0) or 0,reverse=True)[:30]
        events=list(_ACTIVITY_EVENTS)[-80:][::-1]; alerts=list(_ALERTS)[-80:][::-1]; deriv={k:copy.deepcopy(v) for k,v in _DERIV_CURRENT.items()}
    setups=_setup_cards(); idx=_index_cards(svc); changes=[core.f(x.get("change_pct")) for x in idx if core.f(x.get("change_pct")) is not None]
    avg=statistics.fmean(changes) if changes else None
    bias="INSUFFICIENT DATA" if avg is None else "INDEX BREADTH POSITIVE" if avg>=.25 else "INDEX BREADTH NEGATIVE" if avg<=-.25 else "MIXED / RANGE"
    push=precision.push_config()
    return {"version":VERSION,"release":RELEASE,"epoch":time.time(),"iso":_iso(),"indices":idx,"market_bias":bias,
            "best_setup":setups[0] if setups else None,"sudden_activity":activity,"activity_tape":events,"setups":setups,
            "sectors":_sector_rows(),"derivatives":deriv,"alerts":alerts,
            "data_quality":{"data_status":provider.get("data_status"),"tick_age_sec":provider.get("tick_age_sec"),"rest_age_sec":provider.get("rest_age_sec"),
                            "scanner":scanner,"push_configured":push.get("configured"),"push_library_available":push.get("library_available")},
            "policy":"Decision support only. No synthetic market values and no broker order placement.","read_only":True,"execution_enabled":False}

@app.get("/api/v74.4/options/{symbol}")
def options(symbol:str,request:Request):
    svc=base.request_service(request)
    if not svc.authenticated or getattr(svc,"token_invalid",False):raise HTTPException(status_code=401,detail=base._auth_detail(svc))
    sym=base._clean_symbol(symbol)
    try:cur=_derivative_pulse(sym)
    except Exception as exc:
        with _LOCK:cur=copy.deepcopy(_DERIV_CURRENT.get(sym))
        if not cur:raise HTTPException(status_code=503,detail=f"Option data unavailable: {str(exc)[:160]}")
    with _LOCK:hist=list(_DERIV_HISTORY[sym])[-80:]
    doi,pcr=core.f(cur.get("oi_change_diff_put_minus_call")),core.f(cur.get("pcr_oi")); signal="MIXED"
    if doi is not None and pcr is not None:
        if doi>0 and pcr>=1.05:signal="PUT OI DOMINANT"
        elif doi<0 and pcr<=.95:signal="CALL OI DOMINANT"
    return {"version":VERSION,"symbol":sym,"current":cur,"history":hist,"intraday_derivative_state":signal,
            "truth":"OI dominance is context, not a standalone buy/sell instruction.","read_only":True}

@app.get("/api/v74.4/chart-behaviour/{symbol}")
def chart_behaviour(symbol:str,request:Request,interval:int=Query(5,ge=1,le=30),limit:int=Query(180,ge=30,le=240)):
    svc=base.request_service(request)
    if not svc.authenticated or getattr(svc,"token_invalid",False):raise HTTPException(status_code=401,detail=base._auth_detail(svc))
    sym=base._clean_symbol(symbol); cand=base._cached_candidate(sym) or {}
    if not cand and sym in getattr(base,"_INDEX_ALIASES",{}):
        try:cand=base._index_underlying_row(svc,sym) or {}
        except Exception:cand={}
    candles=svc.instrument_candles(sym,interval=interval,limit=limit)
    ctx={"prev_day_high":cand.get("prev_day_high"),"prev_day_low":cand.get("prev_day_low"),"prev_day_close":cand.get("prev_day_close"),
         "day_open":cand.get("day_open"),"day_high":cand.get("day_high"),"day_low":cand.get("day_low")}
    return {"version":VERSION,"symbol":sym,"interval":interval,"candles":candles,"analysis":core.behaviour_summary(candles,ctx),
            "candidate_context":ctx,"truth":"Patterns are derived from observed candles and are not guarantees.","read_only":True}

@app.get("/api/v74.4/alerts")
def alerts(since_epoch:float=Query(0.0),limit:int=Query(150,ge=1,le=500)):
    with _LOCK:rows=[dict(x) for x in _ALERTS if float(x.get("epoch") or 0)>since_epoch]; latest=max([float(x.get("epoch") or 0) for x in _ALERTS],default=0)
    return {"version":VERSION,"items":rows[-limit:],"latest_epoch":latest,"read_only":True}

@app.post("/api/v74.4/test-alert")
def test_alert():
    item=_emit("P0","TEST","SYSTEM","POWERHOUSE AI — TEST ALERT","Popup pipeline test successful. This is not a market signal.",{},5)
    return {"ok":True,"alert":item,"push":precision.push_config(),"read_only":True}

@app.get("/api/v74.4/system")
def system(request:Request):
    svc=base.request_service(request)
    try:provider=svc.status() or {}
    except Exception:provider={}
    return {"version":VERSION,"release":RELEASE,"provider":provider,"scanner":base._background_meta(),"push":precision.push_config(),
            "precision_safe_mode":precision.safe_mode(),"threads":{"activity":bool(_ACTIVITY_THREAD and _ACTIVITY_THREAD.is_alive()),
            "derivatives":bool(_DERIV_THREAD and _DERIV_THREAD.is_alive())},"read_only":True,"execution_enabled":False}

@app.on_event("startup")
def _start():
    global _ACTIVITY_THREAD,_DERIV_THREAD
    _STOP.clear()
    if not (_ACTIVITY_THREAD and _ACTIVITY_THREAD.is_alive()):
        _ACTIVITY_THREAD=threading.Thread(target=_activity_loop,name="v744-activity",daemon=True); _ACTIVITY_THREAD.start()
    if not (_DERIV_THREAD and _DERIV_THREAD.is_alive()):
        _DERIV_THREAD=threading.Thread(target=_derivative_loop,name="v744-derivatives",daemon=True); _DERIV_THREAD.start()

@app.on_event("shutdown")
def _stop():_STOP.set()

try:
    from starlette.routing import Mount
    m=[r for r in app.router.routes if isinstance(r,Mount)]; n=[r for r in app.router.routes if not isinstance(r,Mount)]
    app.router.routes[:]=n+m
except Exception:pass
