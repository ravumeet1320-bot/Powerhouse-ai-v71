from __future__ import annotations

import copy
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse

import v745_app as legacy
import v746_engine as core

VERSION = core.VERSION
RELEASE = core.RELEASE
ROOT = Path(__file__).parent
UI = ROOT / "static" / "v746.html"
app = legacy.app
app.title = "POWERHOUSE AI V74.6 — Aggressive Dynamic Master"
app.version = VERSION

_LOCK = threading.RLock()
_LAST: Dict[str, Dict[str, Any]] = {}
_CONFIRM: Dict[str, Dict[str, int]] = {"BALANCED": {}, "AGGRESSIVE": {}, "TURBO": {}}
_ALERTS = deque(maxlen=600)
_ALERT_SIG: Dict[str, float] = {}
_STATE: Dict[str, Dict[str, str]] = {"BALANCED": {}, "AGGRESSIVE": {}, "TURBO": {}}
SEVERITY_RANK = {"INFO":0,"WATCH":1,"SETUP":2,"TRADE READY":3,"CRITICAL":4}

FEATURES = {
    "aggressive_dynamic_profile": "IMPLEMENTED",
    "turbo_profile": "IMPLEMENTED_OPTIONAL",
    "dynamic_thresholds": "IMPLEMENTED",
    "early_ready_state": "IMPLEMENTED",
    "urgency_engine": "IMPLEMENTED",
    "aggression_score": "IMPLEMENTED",
    "adaptive_temporal_confirmation": "IMPLEMENTED",
    "faster_command_refresh": "IMPLEMENTED",
    "hard_data_integrity_gate": "PRESERVED",
    "extreme_vix_kill_gate": "PRESERVED",
    "execution_quality_floor": "PRESERVED",
    "v745_accuracy_layer": "PRESERVED",
    "v744_v743_stack": "PRESERVED",
    "broker_order_placement": "DISABLED_BY_DESIGN",
}


def _remove_get(path: str) -> None:
    app.router.routes[:] = [r for r in app.router.routes if not (getattr(r,"path",None)==path and "GET" in (getattr(r,"methods",None) or set()))]

_remove_get("/")

@app.get("/")
def home():
    h={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","Expires":"0","X-Powerhouse-Build":"V74.6-AGGRESSIVE-DYNAMIC-MASTER-FINAL"}
    if UI.exists(): return FileResponse(UI, headers=h)
    return legacy.home()

@app.get("/v745")
def v745_preserved():
    ui=ROOT/"static"/"v745.html"
    if ui.exists(): return FileResponse(ui, headers={"Cache-Control":"no-store","X-Powerhouse-Build":"V74.5-PRESERVED"})
    raise HTTPException(status_code=404,detail="V74.5 UI unavailable")


def _emit(severity: str, kind: str, symbol: str, title: str, body: str, payload: Optional[Dict[str,Any]]=None, cooldown: int=45):
    now=time.time(); sig=f"{severity}|{kind}|{symbol}|{title}|{body}"
    with _LOCK:
        if now-_ALERT_SIG.get(sig,0)<cooldown: return
        _ALERT_SIG[sig]=now
        _ALERTS.append({"epoch":now,"severity":severity,"kind":kind,"symbol":symbol,"title":title,"body":body,"payload":payload or {}})


def _temporal(rows, p):
    p=str(p).upper(); state=_CONFIRM.setdefault(p,{})
    out=[]
    for row in rows or []:
        x=copy.deepcopy(row); a=x.get("adaptive") or {}; sym=str(x.get("symbol") or "").upper()
        raw=bool(a.get("raw_ready")); required=core.temporal_required(x)
        streak=(state.get(sym,0)+1) if raw else 0; state[sym]=min(5,streak)
        a["temporal_confirmation"]={"required":required,"observed":streak,"passed":streak>=required}
        if raw and streak<required:
            a["qualified"]=False; a["pre_debounce_action"]=a.get("final_action"); a["final_action"]="WAIT"; a["lifecycle"]="EARLY READY" if a.get("early_ready") else "ARMED"
        elif raw and streak>=required:
            a["qualified"]=True; a["lifecycle"]="READY"
        x["adaptive"]=a; out.append(x)
    return out


def _transition_alerts(rows,p):
    p=str(p).upper(); states=_STATE.setdefault(p,{})
    for row in rows or []:
        sym=str(row.get("symbol") or "").upper(); a=row.get("adaptive") or {}; st=str(a.get("lifecycle") or "SCANNING")
        old=states.get(sym); states[sym]=st
        if not old or old==st: continue
        if st=="READY":
            _emit("TRADE READY","DYNAMIC_READY",sym,f"{sym} — {a.get('final_action') or 'SETUP'} READY",f"{p} · urgency {a.get('urgency_score')} · confidence {a.get('confidence_score')}",{"from":old,"to":st,"profile":p},45)
        elif st=="EARLY READY":
            _emit("SETUP","EARLY_READY",sym,f"{sym} — EARLY READY",f"{p} · probe {a.get('probe_action') or 'WATCH'} · urgency {a.get('urgency_score')}",{"from":old,"to":st,"profile":p},35)
        elif st=="INVALIDATED" and old in {"READY","EARLY READY","ARMED"}:
            _emit("WATCH","INVALIDATED",sym,f"{sym} — INVALIDATED",f"{old} → INVALIDATED",{"from":old,"to":st,"profile":p},40)


def _build(request: Request, profile_name: str) -> Dict[str,Any]:
    p,_=core.profile(profile_name)
    svc=legacy.legacy.base.request_service(request)
    if not svc.authenticated or getattr(svc,"token_invalid",False):
        raise HTTPException(status_code=401,detail=legacy.legacy.base._auth_detail(svc))
    base_snap=legacy._build_snapshot(svc)
    dq=base_snap.get("data_quality") or {}; regime=base_snap.get("market_regime") or {}; vix=base_snap.get("vix") or {}
    rows=[core.qualify_dynamic(x,dq,regime,vix,p) for x in (base_snap.get("setups") or [])]
    rows=_temporal(rows,p)
    best=core.best_dynamic_setup(rows); early=core.best_early_setup(rows)
    risk=legacy.core.risk_state(dq,vix,regime,rows)
    corr=legacy.core.correlation_guard(rows)
    priority=legacy.core.watchlist_priority(rows,12)
    thresholds=core.dynamic_thresholds(p,dq,regime,vix)

    current={
        **{k:v for k,v in base_snap.items() if k not in {"setups","best_setup","priority_setups","risk_state","correlation_guard","alerts","version","release"}},
        "version":VERSION,"release":RELEASE,"profile":p,"dynamic_thresholds":thresholds,
        "setups":rows,"best_setup":best,"best_early_setup":early,"priority_setups":priority,
        "risk_state":risk,"correlation_guard":corr,
        "dynamic_policy":"Earlier qualification with dynamic thresholds; hard feed/extreme-volatility/execution gates remain active.",
        "read_only":True,"execution_enabled":False,
    }
    prev=_LAST.get(p)
    current["what_changed"]=legacy.core.what_changed(prev,current) if prev else []
    _transition_alerts(rows,p)
    with _LOCK:
        _LAST[p]=copy.deepcopy(current)
        current["alerts"]=[dict(x) for x in list(_ALERTS)[-100:]][::-1]
    return current

@app.get("/api/v74.6/command-center")
def command_center(request: Request, profile: str = Query("AGGRESSIVE")):
    return _build(request,profile)

@app.get("/api/v74.6/setup/{symbol}")
def setup(symbol: str, request: Request, profile: str = Query("AGGRESSIVE")):
    snap=_build(request,profile); sym=legacy.legacy.base._clean_symbol(symbol)
    row=next((x for x in snap.get("setups") or [] if str(x.get("symbol") or "").upper()==sym),None)
    return {"version":VERSION,"profile":snap.get("profile"),"symbol":sym,"setup":row,"market_regime":snap.get("market_regime"),"vix":snap.get("vix"),"risk_state":snap.get("risk_state"),"read_only":True}

@app.get("/api/v74.6/alerts")
def alerts(since_epoch: float=Query(0.0), limit: int=Query(100,ge=1,le=500), minimum_severity: str=Query("WATCH")):
    threshold=SEVERITY_RANK.get(str(minimum_severity).upper(),1)
    with _LOCK:
        rows=[dict(x) for x in _ALERTS if float(x.get("epoch") or 0)>since_epoch and SEVERITY_RANK.get(str(x.get("severity") or "INFO"),0)>=threshold]
    return {"version":VERSION,"items":rows[-limit:][::-1],"default_mode":"IMPORTANT_ONLY","read_only":True}

@app.get("/api/v74.6/profiles")
def profiles():
    return {"version":VERSION,"default":"AGGRESSIVE","profiles":core.PROFILES,"note":"TURBO is faster/more permissive but still keeps hard safety gates.","read_only":True}

@app.get("/api/v74.6/system")
def system(request: Request):
    _=legacy.legacy.base.request_service(request)
    paths={getattr(r,"path",None) for r in app.router.routes}
    return {"version":VERSION,"release":RELEASE,"features":FEATURES,"default_profile":"AGGRESSIVE","production_safety":{"broker_execution":False,"hard_data_gate":True,"extreme_vix_gate":True,"missing_values_as_zero":False,"test_alerts_in_normal_stream":False},"feature_contract":{"v743_preserved":"/v743" in paths,"v744_preserved":"/v744" in paths,"v745_preserved":"/v745" in paths,"v746_command_center":"/api/v74.6/command-center" in paths},"read_only":True}

# Keep static mounts last.
try:
    from starlette.routing import Mount
    mounts=[r for r in app.router.routes if isinstance(r,Mount)]
    normal=[r for r in app.router.routes if not isinstance(r,Mount)]
    app.router.routes[:]=normal+mounts
except Exception:
    pass
