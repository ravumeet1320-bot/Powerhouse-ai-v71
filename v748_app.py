from __future__ import annotations
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict
from fastapi import Query, Request
from fastapi.responses import FileResponse
import v747_app as base

app = base.app
IST = ZoneInfo("Asia/Kolkata")
ROOT = base.ROOT
UI = ROOT / "static" / "v748.html"
VERSION = "74.8"
RELEASE = "V74.8 OLD-GOOD + MOVE INTELLIGENCE + EXPIRY HERO MERGE"
INDEXES = {"NIFTY","BANKNIFTY","MIDCPNIFTY","SENSEX"}

base._remove_get("/")

@app.get("/")
def v748_home():
    if UI.exists():
        return FileResponse(
            UI,
            headers={
                "Cache-Control":"no-store, no-cache, must-revalidate, max-age=0",
                "Pragma":"no-cache",
                "Expires":"0",
                "X-Powerhouse-Build":"V74.8-FINAL-HOTFIX",
            },
        )
    return base.home()

def _index_setups(request: Request, profile: str="AGGRESSIVE"):
    snap=base.legacy._build(request,profile)
    setups=[x for x in (snap.get("setups") or []) if str(x.get("symbol") or "").upper() in INDEXES]
    auto=base._index_autotrend(snap)
    amap={str(x.get("symbol") or "").upper():x for x in auto}
    return snap,setups,amap

def _expiry_value(x: Dict[str,Any]):
    pools=[x,x.get("call") or {},x.get("hero5") or {},x.get("adaptive") or {}]
    for p in pools:
        for k in ("expiry","expiry_date","expiryDate","expiration","expiration_date"):
            v=p.get(k) if isinstance(p,dict) else None
            if v: return str(v)
    return None

def _today(exp):
    if not exp:return None
    try:return datetime.fromisoformat(str(exp)[:10]).date()==datetime.now(IST).date()
    except Exception:return None

def _hero_state(x, auto):
    h=x.get("hero5") or x.get("call") or {}
    ad=x.get("adaptive") or {}
    action=str(h.get("action") or ad.get("final_action") or ad.get("probe_action") or x.get("option_action") or x.get("action") or "WAIT").upper()
    meta=h.get("meta_score") or h.get("score") or ad.get("confidence_score") or x.get("score")
    expiry=_expiry_value(x)
    is_today=_today(expiry)
    state="WATCH" if action in {"WAIT","WATCH","NONE","NO TRADE",""} else "ARMED"
    lifecycle=str(ad.get("lifecycle") or x.get("stage") or auto.get("stage") or "").upper()
    if state=="ARMED" and lifecycle in {"ENTRY READY","MOVE ACTIVE","TRIGGERED"}:
        state="TRIGGERED"
    return {"symbol":str(x.get("symbol") or "").upper(),"ltp":x.get("ltp"),"change_pct":x.get("change_pct"),"expiry":expiry,"expiry_today":is_today,"state":state,"action":action,"hero":h,"adaptive":ad,"auto":auto,"meta_score":meta,"read_only":True}

@app.get("/api/v74.8/index-workspace")
def index_workspace(request:Request, profile:str=Query("AGGRESSIVE")):
    snap,setups,amap=_index_setups(request,profile)
    rows=[]
    for x in setups:
        sym=str(x.get("symbol") or "").upper()
        rows.append(_hero_state(x,amap.get(sym) or {}))
    return {"version":VERSION,"release":RELEASE,"rows":rows,"source":"preserved V74.6/V74.7 index stack","read_only":True}

@app.get("/api/v74.8/expiry-hero")
def expiry_hero(request:Request, profile:str=Query("AGGRESSIVE")):
    snap,setups,amap=_index_setups(request,profile)
    rows=[_hero_state(x,amap.get(str(x.get("symbol") or "").upper()) or {}) for x in setups]
    today=[x for x in rows if x.get("expiry_today") is True]
    return {"version":VERSION,"engine":"EXPIRY-DAY GAMMA & LIQUIDITY HERO","today":datetime.now(IST).date().isoformat(),"expiry_detected":bool(today),"rows":today or rows,"states":["WATCH","ARMED","TRIGGERED","INVALIDATED"],"policy":"No forced trade; preserved engine remains authoritative.","read_only":True,"execution_enabled":False}

@app.get("/api/v74.8/system")
def v748_system(request:Request):
    old=base.system(request)
    return {**old,"version":VERSION,"release":RELEASE,"v748":{"old_good_preserved":True,"v747_preserved":True,"index_click_workspace":True,"dedicated_alert_dock":True,"heatmap_surface":True,"expiry_hero_engine":True,"duplicate_tab_policy":"one detailed home per function; command center summary only"}}
