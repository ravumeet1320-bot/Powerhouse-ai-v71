from __future__ import annotations

"""POWERHOUSE AI V74.3 — Pro Ultra Accuracy FastAPI wrapper.

This module upgrades V74.2 additively. Existing V74/V73/V72 APIs remain available.
The V74.2 server scanner stays browser-independent; its CALL ENGINE is wrapped by an
Ultra Accuracy meta-label gate before a new model call can become READY.
"""

import copy
import math
import os
import statistics
import threading
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

import v742_app as base
import v74_engine as eng
import v743_precision as precision
import v743_memory as memory

VERSION = precision.VERSION
RELEASE = precision.RELEASE
ROOT = Path(__file__).parent
V743_UI = ROOT / "static" / "v743.html"
app = base.app
app.title = "POWERHOUSE AI V74.3 — Pro Ultra Accuracy OS"
app.version = VERSION

_ORIGINAL_CALL_ENGINE_PLAN = base.call_engine_plan
_ORIGINAL_TRACK_CALL_PLAN = base.track_call_plan
_ORIGINAL_STORE_RESULT = base._store_v74_result
_MODEL_CALL_TO_DECISION = {}
_PATCH_LOCK = threading.RLock()


def _enrich_underlying(underlying: dict, strike_pack: dict, chart: Optional[dict]) -> dict:
    u = copy.deepcopy(underlying or {})
    if not u.get("scout_pack"):
        try:
            u["scout_pack"] = eng.seven_scouts(u)
        except Exception:
            pass
    winner = (strike_pack or {}).get("winner") or {}
    scores = winner.get("scores") or {}
    if u.get("premium_response") is None and scores.get("premium_response") is not None:
        u["premium_response"] = scores.get("premium_response")
    if u.get("iv") is None and winner.get("iv") is not None:
        u["iv"] = winner.get("iv")
    if u.get("gamma") is None and winner.get("gamma") is not None:
        u["gamma"] = winner.get("gamma")
    if chart:
        if chart.get("mtf_conflict") is not None:
            u["mtf_conflict"] = bool(chart.get("mtf_conflict"))
        for k in ("pattern", "developing_pattern", "breakout", "reversal", "compression"):
            if u.get(k) is None and chart.get(k) is not None:
                u[k] = chart.get(k)
    # Recompute scout pack after evidence enrichment so the meta-label sees the same
    # decision-time evidence that the base call inspector used.
    try:
        u["scout_pack"] = eng.seven_scouts(u)
    except Exception:
        pass
    return u


def _v743_call_engine_plan(symbol: str, underlying: dict, strike_pack: dict, chart: Optional[dict] = None, now_epoch: Optional[float] = None) -> dict:
    enriched = _enrich_underlying(underlying, strike_pack, chart)
    plan = _ORIGINAL_CALL_ENGINE_PLAN(symbol, enriched, strike_pack, chart, now_epoch=now_epoch)
    safe = precision.safe_mode()
    out = precision.apply_precision_gate(enriched, plan, strike_pack, chart, now_epoch=now_epoch)
    try:
        memory.MEMORY.record(
            "CALL_SNAPSHOT",
            {
                "action": out.get("action"),
                "status": out.get("status"),
                "meta_label": out.get("meta_label"),
                "meta_score": out.get("meta_score"),
                "entry_zone": out.get("entry_zone"),
                "sl": out.get("sl"),
                "structural_sl": out.get("structural_sl"),
                "targets": out.get("targets"),
                "stage": out.get("stage"),
                "ultra_accuracy": out.get("ultra_accuracy"),
                "underlying_snapshot": enriched,
                "strike_winner": (strike_pack or {}).get("winner"),
                "chart_context": chart or {},
            },
            symbol=symbol,
            scope_key=f"CALL:{symbol}",
            event_key=str(out.get("decision_id") or out.get("model_call_id") or f"{symbol}:{int(now_epoch or time.time())}"),
            source="V74.3 CALL ENGINE",
            config_hash=precision.CONFIG_HASH,
            epoch=now_epoch,
        )
    except Exception:
        pass
    if safe.get("enabled") and out.get("action") in ("BUY CE", "BUY PE"):
        out["candidate_action"] = out.get("action")
        out["action"] = "WAIT"
        out["status"] = "SAFE MODE"
        out["meta_label"] = "SKIP"
        out.setdefault("blocked_by", []).append("SYSTEM SAFE MODE")
        ua = out.get("ultra_accuracy") or {}
        ua["decision"] = "SKIP"
        ua.setdefault("hard_blockers", []).append("SYSTEM SAFE MODE")
        out["ultra_accuracy"] = ua
    return out


def _v743_track_call_plan(plan: dict) -> dict:
    out = _ORIGINAL_TRACK_CALL_PLAN(plan)
    call_id = out.get("model_call_id")
    decision_id = out.get("decision_id")
    if call_id and decision_id and str(out.get("meta_label") or "") == "TAKE":
        with _PATCH_LOCK:
            _MODEL_CALL_TO_DECISION[call_id] = decision_id
    result = out.get("model_call_result")
    if call_id and result:
        with _PATCH_LOCK:
            did = _MODEL_CALL_TO_DECISION.get(call_id)
        if did:
            try:
                # V74 journal MFE/MAE is model-call premium excursion. The precision
                # store keeps the final outcome tied to the original immutable TAKE.
                journal = eng.call_journal(300)
                row = next((r for r in journal.get("rows", []) if r.get("call_id") == call_id), None)
                precision.STORE.update_outcome(
                    did,
                    result,
                    (row or {}).get("max_favorable_pct"),
                    (row or {}).get("max_adverse_pct"),
                )
            except Exception:
                pass
    return out


def _v743_store_result(out: dict, scan_ms: float) -> None:
    _ORIGINAL_STORE_RESULT(out, scan_ms)
    try:
        precision.observe_scanner(base._background_meta())
    except Exception:
        pass
    try:
        cov=(out or {}).get("coverage") or {}
        memory.MEMORY.record(
            "SYSTEM",
            {"scan_ms": scan_ms, "coverage": cov, "data_status": (out or {}).get("data_status")},
            scope_key="SCANNER", event_key=f"scan:{int(time.time())}", source="V74 CONTINUOUS SCANNER",
            config_hash=precision.CONFIG_HASH,
        )
    except Exception:
        pass


# Patch only decision qualification/tracking. Discovery engine and provider feed remain intact.
base.call_engine_plan = _v743_call_engine_plan
base.track_call_plan = _v743_track_call_plan
base._store_v74_result = _v743_store_result


# Replace V74.2 root + health routes with V74.3-owned versions. Legacy mounted routes remain.
def _remove_owned_route(path: str) -> None:
    app.router.routes[:] = [r for r in app.router.routes if not (getattr(r, "path", None) == path and "GET" in (getattr(r, "methods", None) or set()))]


_remove_owned_route("/")
_remove_owned_route("/api/health")


@app.get("/")
def v743_home():
    headers={
        "Cache-Control":"no-store, no-cache, must-revalidate, max-age=0",
        "Pragma":"no-cache",
        "Expires":"0",
        "X-Powerhouse-Build":"V74.3-LIVEFIX4",
    }
    if V743_UI.exists():
        return FileResponse(V743_UI, headers=headers)
    if base.V74_UI.exists():
        return FileResponse(base.V74_UI, headers=headers)
    raise HTTPException(status_code=503, detail="V74.3 UI asset missing")


@app.get("/api/health")
def v743_health(request: Request):
    # LIVEFIX4 health is intentionally O(1): no calibration/DB query and no full
    # market snapshot. The UI only needs auth, feed state and scanner heartbeat here.
    svc = base.request_service(request)
    try:
        ds = svc._data_status() if hasattr(svc,"_data_status") else {}
    except Exception:
        ds = {}
    return {
        "ok": True,
        "app": "POWERHOUSE AI V74.3",
        "version": VERSION,
        "release": RELEASE,
        "build": "LIVEFIX4",
        "read_only": True,
        "orders_enabled": False,
        "execution_enabled": False,
        "upstox_authenticated": bool(getattr(svc, "authenticated", False)),
        "upstox_data_status": ds.get("data_status"),
        "tick_age_sec": ds.get("tick_age_sec"),
        "rest_age_sec": ds.get("rest_age_sec"),
        "continuous_scanner": base._background_meta(),
        "request_driven_scanning": False,
    }


@app.get("/api/v74.3/status")
def v743_status(request: Request):
    svc, out = base._live_v74_result(request)
    precision.observe_scanner(base._background_meta())
    return {
        "version": VERSION,
        "release": RELEASE,
        "base_v74": {
            "available": out is not None,
            "data_status": (out or {}).get("data_status"),
            "coverage": (out or {}).get("coverage"),
            "continuous_scanner": base._background_meta(),
            "automated_call_engine": copy.deepcopy(base._V74_AUTO_CALLS),
        },
        "precision": precision.pro_status(),
        "authenticated": bool(getattr(svc, "authenticated", False)),
        "read_only": True,
        "execution_enabled": False,
    }


@app.get("/api/v74.3/index-command")
def v743_index_command(request: Request):
    """Ultra-light index board: live LTPC from provider memory + cached call plans.

    This endpoint never fires option-chain, candle or per-index REST requests.
    """
    svc = base.request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=base._auth_detail(svc))
    try:
        with svc.lock:
            levels={k:dict(v) for k,v in getattr(svc,"index_levels",{}).items()}
    except Exception:
        levels={}
    auto=dict(base._V74_AUTO_CALLS)
    auto_rows=list(auto.get("results") or [])
    out=[]
    for symbol in ("NIFTY","BANKNIFTY","MIDCPNIFTY","SENSEX"):
        lv=levels.get(symbol) or {}
        ltp=_vf(lv.get("ltp")); cp=_vf(lv.get("cp"))
        chg=((ltp-cp)/abs(cp)*100.0) if ltp is not None and cp not in (None,0) else None
        ar=next((r for r in auto_rows if str(r.get("symbol") or "").upper()==symbol),None) or {}
        call=copy.deepcopy(ar.get("call") or {})
        if not call:
            call={"action":"WAIT","status":"WAIT","meta_label":"SKIP","entry_zone":{},"targets":{},"blocked_by":["CALL PLAN WARMING"]}
        out.append({
            "symbol":symbol,"label":symbol,"ltp":ltp,"change_pct":chg,
            "data_status":"LIVE" if ltp is not None else "N/A",
            "source":"Upstox in-memory index LTPC",
            "stage":ar.get("stage") or "WATCH","score":ar.get("score"),
            "call":call,"updated_epoch":auto.get("updated_epoch"),"read_only":True,
        })
    return {
        "version":VERSION,"release":RELEASE,"results":out,"rows":out,"count":len(out),
        "policy":"Index Calls is cache-only and never mixes equities into index cards.",
        "read_only":True,"execution_enabled":False,
    }


def _vf(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if v is None or v == "":
            return default
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _clamp100(v: Any) -> float:
    x = _vf(v, 0.0) or 0.0
    return max(0.0, min(100.0, x))


def _norm_candles(candles: list[Any]) -> list[dict]:
    out=[]
    for c in candles or []:
        if isinstance(c, dict):
            o,h,l,cl=_vf(c.get("open") or c.get("o")),_vf(c.get("high") or c.get("h")),_vf(c.get("low") or c.get("l")),_vf(c.get("close") or c.get("c")); vol=_vf(c.get("volume") or c.get("v"),0.0); ts=c.get("timestamp") or c.get("ts") or c.get("time")
        elif isinstance(c,(list,tuple)) and len(c)>=5:
            ts=c[0]; o,h,l,cl=_vf(c[1]),_vf(c[2]),_vf(c[3]),_vf(c[4]); vol=_vf(c[5],0.0) if len(c)>5 else 0.0
        else:
            continue
        if None in (o,h,l,cl):
            continue
        out.append({"ts":ts,"open":o,"high":h,"low":l,"close":cl,"volume":vol or 0.0})
    return out


def _atr(cs: list[dict], n: int = 14) -> Optional[float]:
    if len(cs) < 2:
        return None
    tr=[]
    prev=cs[0]["close"]
    for x in cs[1:]:
        tr.append(max(x["high"]-x["low"], abs(x["high"]-prev), abs(x["low"]-prev)))
        prev=x["close"]
    vals=tr[-n:]
    return (sum(vals)/len(vals)) if vals else None


def _pivots(cs: list[dict], w: int = 2) -> tuple[list[dict], list[dict]]:
    hi=[]; lo=[]
    for i in range(w, len(cs)-w):
        seg=cs[i-w:i+w+1]
        if cs[i]["high"] >= max(x["high"] for x in seg): hi.append({"i":i,"price":cs[i]["high"],"ts":cs[i]["ts"]})
        if cs[i]["low"] <= min(x["low"] for x in seg): lo.append({"i":i,"price":cs[i]["low"],"ts":cs[i]["ts"]})
    return hi,lo


def _extract_level(chart: dict, *keys: str) -> Optional[float]:
    queue=[chart]
    seen=set()
    while queue:
        obj=queue.pop(0)
        if not isinstance(obj,dict) or id(obj) in seen:
            continue
        seen.add(id(obj))
        for k in keys:
            v=obj.get(k)
            x=_vf(v)
            if x is not None:
                return x
        for v in obj.values():
            if isinstance(v,dict): queue.append(v)
    return None


def _derive_level_map(candles: list[Any], chart: dict, spot: Optional[float]) -> dict:
    cs=_norm_candles(candles)
    if not cs:
        return {"support":None,"resistance":None,"demand":None,"supply":None,"atr":None,"source":"UNAVAILABLE"}
    spot=_vf(spot, cs[-1]["close"])
    atr=_atr(cs) or max(spot*0.002, 1e-9)
    highs,lows=_pivots(cs[-100:],2)
    engine_support=_extract_level(chart,"support","support_level","nearest_support","s1")
    engine_resistance=_extract_level(chart,"resistance","resistance_level","nearest_resistance","r1")
    support=engine_support
    resistance=engine_resistance
    if support is None:
        below=[x["price"] for x in lows if x["price"] <= spot]
        support=max(below) if below else min(x["low"] for x in cs[-20:])
    if resistance is None:
        above=[x["price"] for x in highs if x["price"] >= spot]
        resistance=min(above) if above else max(x["high"] for x in cs[-20:])
    d_half=max(atr*0.35, spot*0.0005)
    s_half=max(atr*0.35, spot*0.0005)
    demand={"low":support-d_half,"high":support+d_half,"mid":support,"source":"ENGINE" if engine_support is not None else "CANDLE_DERIVED"}
    supply={"low":resistance-s_half,"high":resistance+s_half,"mid":resistance,"source":"ENGINE" if engine_resistance is not None else "CANDLE_DERIVED"}
    tol=max(atr*0.28, spot*0.0006)
    def touches(level: float, kind: str) -> int:
        if level is None: return 0
        if kind=="support": return sum(1 for x in cs[-80:] if abs(x["low"]-level)<=tol)
        return sum(1 for x in cs[-80:] if abs(x["high"]-level)<=tol)
    def health(level: float, kind: str) -> dict:
        t=touches(level,kind)
        rejections=[]
        for x in cs[-60:]:
            if kind=="support" and abs(x["low"]-level)<=tol: rejections.append(max(0.0,x["close"]-x["low"]))
            if kind=="resistance" and abs(x["high"]-level)<=tol: rejections.append(max(0.0,x["high"]-x["close"]))
        avg=(sum(rejections)/len(rejections)) if rejections else 0.0
        score=_clamp100(72 - max(0,t-1)*11 + min(22,(avg/max(atr,1e-9))*16))
        state="STRONG" if score>=72 else "HOLDING" if score>=55 else "WEAKENING" if score>=35 else "CONSUMED"
        return {"score":round(score,1),"state":state,"tests":t,"avg_rejection":round(avg,4)}
    return {
        "support":round(support,4) if support is not None else None,
        "resistance":round(resistance,4) if resistance is not None else None,
        "demand":{k:(round(v,4) if isinstance(v,(int,float)) else v) for k,v in demand.items()},
        "supply":{k:(round(v,4) if isinstance(v,(int,float)) else v) for k,v in supply.items()},
        "atr":round(atr,4),
        "support_health":health(support,"support"),
        "resistance_health":health(resistance,"resistance"),
        "source":"ENGINE+CANDLES" if engine_support is not None or engine_resistance is not None else "CANDLE_DERIVED",
    }


def _chain_analytics(chain: dict, spot: Optional[float]) -> dict:
    rows=list((chain or {}).get("chain") or [])
    def oi(side: dict) -> float: return _vf(side.get("oi"),0.0) or 0.0
    def poi(side: dict) -> float: return _vf(side.get("prev_oi"),oi(side)) or oi(side)
    def enrich(row: dict, side_key: str) -> dict:
        sd=row.get(side_key) or {}; cur=oi(sd); prev=poi(sd); change=cur-prev; pct=(change/abs(prev)*100.0) if prev else None
        return {"strike":_vf(row.get("strike")),"ltp":_vf(sd.get("ltp")),"oi":cur,"prev_oi":prev,"oi_change":change,"oi_change_pct":pct,"volume":_vf(sd.get("volume"),0.0),"bid":_vf(sd.get("bid")),"ask":_vf(sd.get("ask")),"iv":_vf(sd.get("iv")),"delta":_vf(sd.get("delta")),"gamma":_vf(sd.get("gamma")),"theta":_vf(sd.get("theta")),"vega":_vf(sd.get("vega"))}
    ce_rows=[enrich(r,"ce") for r in rows]; pe_rows=[enrich(r,"pe") for r in rows]
    ce_wall=max(ce_rows,key=lambda x:x["oi"],default={}); pe_wall=max(pe_rows,key=lambda x:x["oi"],default={})
    total_ce=sum(x["oi"] for x in ce_rows); total_pe=sum(x["oi"] for x in pe_rows)
    total_cv=sum((x["volume"] or 0) for x in ce_rows); total_pv=sum((x["volume"] or 0) for x in pe_rows)
    atm={}
    valid=[r for r in rows if _vf(r.get("strike")) is not None and spot is not None]
    if valid:
        raw=min(valid,key=lambda r:abs((_vf(r.get("strike")) or 0)-spot)); atm={"strike":_vf(raw.get("strike")),"ce":enrich(raw,"ce"),"pe":enrich(raw,"pe")}
    def wall_state(w: dict) -> str:
        d=_vf(w.get("oi_change"))
        if d is None:return "N/A"
        if d>0:return "BUILDING"
        if d<0:return "WEAKENING/UNWINDING"
        return "UNCHANGED"
    return {
        "spot":spot,"expiry":(chain or {}).get("expiry"),"rows":rows,
        "call_wall":{**ce_wall,"state":wall_state(ce_wall),"share_pct":(ce_wall.get("oi",0)/total_ce*100 if total_ce else None)},
        "put_wall":{**pe_wall,"state":wall_state(pe_wall),"share_pct":(pe_wall.get("oi",0)/total_pe*100 if total_pe else None)},
        "atm":atm,"total_call_oi":total_ce,"total_put_oi":total_pe,"pcr_oi":(total_pe/total_ce if total_ce else None),
        "total_call_volume":total_cv,"total_put_volume":total_pv,"pcr_volume":(total_pv/total_cv if total_cv else None),
        "source":(chain or {}).get("source") or "Upstox option chain",
    }


def _level_attack(spot: Optional[float], levels: dict, chain: dict, candidate: dict) -> dict:
    if spot is None:
        return {"state":"INSUFFICIENT_DATA","up_break_pressure":None,"down_break_pressure":None,"evidence":[]}
    atr=_vf(levels.get("atr"), max(abs(spot)*0.002,1e-9)) or 1.0
    res=_vf(levels.get("resistance")); sup=_vf(levels.get("support"))
    sc=(candidate.get("scout_pack") or {}).get("scouts") or {}
    vol=sc.get("volume") or {}; oi=sc.get("oi") or {}; opt=sc.get("options") or {}; order=sc.get("order_flow") or {}
    rvol=_vf(vol.get("rvol"),_vf(candidate.get("rvol")))
    depth=_vf(order.get("pressure"))
    premium=_vf(opt.get("premium_response"),_vf(candidate.get("premium_response")))
    atm=chain.get("atm") or {}; ce=atm.get("ce") or {}; pe=atm.get("pe") or {}
    cechg=_vf(ce.get("oi_change")); pechg=_vf(pe.get("oi_change"))
    up=35.0; down=35.0; ev=[]
    if res is not None:
        dist=(res-spot)/max(atr,1e-9)
        if 0<=dist<=0.6: up+=15; ev.append("Price is attacking resistance")
        elif spot>res: up+=20; ev.append("Price is above resistance")
    if sup is not None:
        dist=(spot-sup)/max(atr,1e-9)
        if 0<=dist<=0.6: down+=15; ev.append("Price is attacking support")
        elif spot<sup: down+=20; ev.append("Price is below support")
    if rvol is not None:
        if rvol>=1.5: up+=8; down+=8; ev.append(f"RVOL {rvol:.2f}x")
        elif rvol<0.8: up-=6; down-=6
    if depth is not None:
        up+=(depth-50)*0.45; down+=(50-depth)*0.45; ev.append(f"Depth pressure {depth:.0f}")
    if premium is not None:
        side=str(candidate.get("side") or candidate.get("v72_side") or "").upper()
        if side=="CE": up+=(premium-50)*0.25
        elif side=="PE": down+=(premium-50)*0.25
    if cechg is not None:
        if cechg<0: up+=9; ev.append("ATM Call OI unwinding")
        elif cechg>0: up-=5
    if pechg is not None:
        if pechg>0: up+=7; ev.append("ATM Put OI building")
        elif pechg<0: down+=7
    if pechg is not None and pechg<0: down+=9; ev.append("ATM Put OI unwinding")
    if cechg is not None and cechg>0: down+=7; ev.append("ATM Call OI building")
    up=_clamp100(up); down=_clamp100(down)
    if max(up,down)<55: state="WAIT"
    elif up>=down+12: state="UPSIDE BREAK PRESSURE"
    elif down>=up+12: state="DOWNSIDE BREAK PRESSURE"
    else: state="CONFLICT / WAIT"
    return {
        "state":state,"up_break_pressure":round(up,1),"down_break_pressure":round(down,1),
        "rvol":rvol,"depth_pressure":depth,"premium_response":premium,
        "atm_ce_oi_change":cechg,"atm_pe_oi_change":pechg,"evidence":ev[:10],
        "policy":"Evidence pressure score, not a probability of a breakout.",
    }


def _symbol_candidate(svc, sym: str) -> dict:
    row=base._cached_candidate(sym)
    if row:
        return copy.deepcopy(row)
    if sym in getattr(base,"_INDEX_ALIASES",{}):
        try:return base._index_underlying_row(svc,sym) or {}
        except Exception:return {}
    return {}


_INTEL_CACHE = {}
_INTEL_CACHE_LOCK = threading.RLock()
_INTEL_CACHE_TTL_SEC = max(12.0, min(60.0, float(os.getenv("V743_INTEL_CACHE_TTL_SEC", "24"))))


def _chain_from_index_snapshot(svc, symbol: str, snap: dict) -> dict:
    """Reuse an already-fetched index snapshot so intelligence does not hit the same
    option-contract + option-chain endpoints twice in one request."""
    if not isinstance(snap, dict) or not snap.get("ok"):
        return {}
    rows=[]
    for r in snap.get("option_data") or []:
        coi=r.get("coi"); poi=r.get("poi"); cchg=r.get("cchg"); pchg=r.get("pchg")
        rows.append({
            "strike":r.get("s"), "spot":snap.get("spot"),
            "ce":{
                "ltp":r.get("cltp"), "oi":coi,
                "prev_oi":(coi-cchg) if coi is not None and cchg is not None else coi,
                "volume":r.get("cvol"), "bid":r.get("cbid"), "ask":r.get("cask"),
                "iv":r.get("civ"), "delta":r.get("c_delta"), "gamma":r.get("c_gamma"),
                "theta":r.get("c_theta"), "vega":r.get("c_vega"), "key":r.get("call_key"),
            },
            "pe":{
                "ltp":r.get("pltp"), "oi":poi,
                "prev_oi":(poi-pchg) if poi is not None and pchg is not None else poi,
                "volume":r.get("pvol"), "bid":r.get("pbid"), "ask":r.get("pask"),
                "iv":r.get("piv"), "delta":r.get("p_delta"), "gamma":r.get("p_gamma"),
                "theta":r.get("p_theta"), "vega":r.get("p_vega"), "key":r.get("put_key"),
            },
        })
    return {
        "ok":True,"symbol":symbol,"instrument_key":svc.resolve_underlying_key(symbol),
        "expiry":snap.get("expiry"),"expiries":[snap.get("expiry")] if snap.get("expiry") else [],
        "spot":snap.get("spot"),"chain":rows,"chain_rows":len(rows),
        "source":(snap.get("source") or "Upstox option chain")+"/reused",
        "read_only":True,
    }


@app.get("/api/v74.3/intelligence/{symbol}")
def v743_intelligence(symbol: str, request: Request, interval: int = Query(5, ge=1, le=30), limit: int = Query(180, ge=30, le=240)):
    """One truth-preserving payload for Chart Pro, zones, OI walls and Level War Room."""
    svc=base.request_service(request)
    if not svc.authenticated or getattr(svc,"token_invalid",False):
        raise HTTPException(status_code=401,detail=base._auth_detail(svc))
    sym=base._clean_symbol(symbol)
    cache_key=(sym,int(interval),int(limit))
    with _INTEL_CACHE_LOCK:
        cached=_INTEL_CACHE.get(cache_key)
        if cached and time.time()-float(cached.get("_cache_epoch") or 0) <= _INTEL_CACHE_TTL_SEC:
            out=copy.deepcopy(cached.get("payload") or {})
            out.setdefault("provenance",{})["response_cache"]="HIT"
            return out
    candidate=_symbol_candidate(svc,sym)
    candles=[]; chart={}; chain={}; errors=[]
    try:
        candles=svc.instrument_candles(sym,interval=interval,limit=limit)
        snap=svc.snapshot()
        chart=base.predictive_chart_intelligence(candles,sym,interval,snap,candidate) or {}
    except Exception as exc:
        errors.append(f"chart:{str(exc)[:120]}")
    try:
        idx_snap=(candidate or {}).get("index_snapshot") if sym in getattr(base,"_INDEX_ALIASES",{}) else None
        chain=_chain_from_index_snapshot(svc,sym,idx_snap) if idx_snap else (base._option_chain_snapshot(svc,sym,force=False) or {})
    except Exception as exc:
        errors.append(f"chain:{str(exc)[:120]}")
    cs=_norm_candles(candles); spot=_vf((chain or {}).get("spot"), _vf(candidate.get("ltp"), cs[-1]["close"] if cs else None))
    levels=_derive_level_map(candles,chart,spot)
    ca=_chain_analytics(chain,spot)
    attack=_level_attack(spot,levels,ca,candidate)
    try: provider_status=svc.status() or {}
    except Exception: provider_status={}
    payload={
        "version":VERSION,"release":RELEASE,"symbol":sym,"spot":spot,"interval":interval,
        "candidate":candidate,"candles":candles,"chart":chart,"option_chain":chain,
        "levels":levels,"derivatives":ca,"level_attack":attack,
        "provenance":{
            "market_data":"Upstox live/REST provider via existing service",
            "option_chain":ca.get("source"),
            "levels":levels.get("source"),
            "data_status":provider_status.get("data_status"),
            "tick_age_sec":provider_status.get("tick_age_sec"),
            "rest_age_sec":provider_status.get("rest_age_sec"),
            "generated_epoch":time.time(),
        },
        "errors":errors,"read_only":True,"execution_enabled":False,
        "truth_policy":"No synthetic market values. Derived zones/levels are labelled CANDLE_DERIVED when not supplied by the chart engine. Break pressure is evidence strength, not a guaranteed probability.",
    }
    payload.setdefault("provenance",{})["response_cache"]="MISS"
    with _INTEL_CACHE_LOCK:
        _INTEL_CACHE[cache_key]={"_cache_epoch":time.time(),"payload":copy.deepcopy(payload)}
        if len(_INTEL_CACHE)>12:
            oldest=sorted(_INTEL_CACHE.items(), key=lambda kv: float((kv[1] or {}).get("_cache_epoch") or 0))[:-12]
            for k,_ in oldest:
                _INTEL_CACHE.pop(k,None)
    return payload


@app.get("/api/v74.3/precision")
def v743_precision(request: Request):
    svc = base.request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=base._auth_detail(svc))
    engine = copy.deepcopy(base._V74_AUTO_CALLS)
    results=[]
    for row in engine.get("results") or []:
        c=row.get("call") or {}
        results.append({
            "symbol":row.get("symbol"),"stage":row.get("stage"),"score":row.get("score"),
            "call":c,"ultra_accuracy":c.get("ultra_accuracy"),"meta_label":c.get("meta_label"),
            "meta_score":c.get("meta_score"),"read_only":True,
        })
    return {
        "version":VERSION,"release":RELEASE,"results":results,
        "take_count":sum(1 for x in results if x.get("meta_label")=="TAKE"),
        "abstain_count":sum(1 for x in results if x.get("meta_label")!="TAKE"),
        "policy":"Only TAKE is actionable. SKIP/INSUFFICIENT_DATA remain WAIT.",
        "read_only":True,"execution_enabled":False,
    }


@app.get("/api/v74.3/decisions")
def v743_decisions(request: Request, limit: int = Query(200, ge=1, le=1000)):
    _ = base.request_service(request)
    return precision.recent_decisions(limit)


@app.get("/api/v74.3/accuracy")
def v743_accuracy(request: Request, limit: int = Query(1000, ge=20, le=5000)):
    _ = base.request_service(request)
    return precision.accuracy_report(limit)


@app.get("/api/v74.3/sla")
def v743_sla(request: Request):
    _ = base.request_service(request)
    precision.observe_scanner(base._background_meta())
    return {
        "version":VERSION,
        "scanner":base._background_meta(),
        "heartbeats":precision.heartbeat_snapshot(),
        "safe_mode":precision.safe_mode(),
        "storage":precision.STORE.status(),
        "push":precision.push_config(),
        "memory":memory.MEMORY.summary(),
        "feature_manifest":_feature_manifest_payload(),
        "read_only":True,
    }


@app.get("/api/v74.3/config")
def v743_config():
    return {"version":VERSION,"release":RELEASE,"config":precision.CFG,"config_hash":precision.CONFIG_HASH,"read_only":True}


FEATURE_MANIFEST = [
    "COMMAND", "INDEX CALLS", "MARKET", "SMART MONEY", "FII/DII", "HEATWAVE",
    "SECTORS", "AUTO TRENDER", "CIRCUITS", "ULTRA CALLS", "CHART PRO",
    "SUPPLY/DEMAND", "S/R BREAK", "ULTRA DERIVATIVES", "OPTION CHAIN", "OI WALLS", "DEPTH/DOM", "EXPIRY HERO",
    "ALERTS", "WATCHLIST", "ACCURACY", "REPLAY", "AUDIT", "SYSTEM",
    "LEVEL MEMORY", "SYMBOL DNA MEMORY", "INDEX DNA MEMORY", "EXPIRY MEMORY",
    "OI WALL MEMORY", "SMART MONEY MEMORY", "SECTOR ROTATION MEMORY", "SETUP MEMORY",
    "FAILURE MEMORY", "MISSED MOVE MEMORY", "REGIME MEMORY", "TIME-OF-DAY MEMORY",
    "STRIKE MEMORY", "PATTERN MEMORY", "CALIBRATION MEMORY", "VERSION MEMORY",
    "DATA QUALITY MEMORY", "RE-ENTRY MEMORY", "TRAP MEMORY", "SCENARIO ENGINE",
    "SIGNAL DECAY", "CONFLICT RESOLVER", "OPPORTUNITY RANKING", "MARKET REPLAY LAB",
    "REGRESSION GUARD", "FEATURE MANIFEST", "EVENT GUARD", "VOLATILITY REGIME",
    "CORRELATION GUARD", "EXECUTION REALITY", "CALL LIFECYCLE", "DATA PROVENANCE",
    "FEED GAP DETECTOR", "OPENING BRAIN", "CLOSING BRAIN", "EMERGENCY SAFE MODE",
]


def _feature_manifest_payload() -> dict:
    ui = V743_UI.read_text(errors="ignore") if V743_UI.exists() else ""
    required_ui = FEATURE_MANIFEST[:24]
    ui_present = {name: (f'data-feature="{name}"' in ui or f"data-feature='{name}'" in ui) for name in required_ui}
    route_paths={getattr(r,"path",None) for r in app.router.routes}
    backend_checks = {
        "continuous_scanner": callable(getattr(base, "_background_meta", None)),
        "call_engine": callable(getattr(base, "call_engine_plan", None)),
        "chart": callable(getattr(base, "predictive_chart_intelligence", None)),
        "strike_selector": callable(getattr(base, "predictive_strike_selector", None)),
        "alerts": callable(getattr(eng, "alert_snapshot", None)),
        "memory": memory.MEMORY is not None,
        "precision": precision.STORE is not None,
        "index_command_route": "/api/v74.3/index-command" in route_paths,
        "intelligence_route": "/api/v74.3/intelligence/{symbol}" in route_paths,
    }
    truth_checks={
        "no_demo_market_values": "DATA_TRUTH_FINAL" in ui and "NO_SYNTHETIC_MARKET_VALUES" in ui,
        "index_calls_index_only": "INDEX_ONLY_CALLS" in ui,
        "heatwave_sectors_separate": "HEATWAVE_VISUAL_ONLY" in ui and "SECTOR_ANALYTICS_ONLY" in ui,
        "real_indicator_calculation": "computeRSI" in ui and "computeMACD" in ui,
        "level_war_room": "LEVEL_WAR_ROOM" in ui,
        "oi_change_columns": "CE ΔOI" in ui and "PE ΔOI" in ui,
    }
    all_ok=all(ui_present.values()) and all(backend_checks.values()) and all(truth_checks.values())
    return {
        "version": VERSION,"release": RELEASE,"required_features": FEATURE_MANIFEST,
        "ui_modules":ui_present,"ui_loaded":sum(1 for x in ui_present.values() if x),"ui_required":len(ui_present),
        "backend_checks":backend_checks,"truth_checks":truth_checks,"backend_ready":all(backend_checks.values()),
        "regression_guard":"PASS" if all_ok else "ATTENTION","read_only":True,
    }


@app.get("/api/v74.3/feature-manifest")
def v743_feature_manifest():
    return _feature_manifest_payload()


@app.get("/api/v74.3/memory/status")
def v743_memory_status():
    return {"version": VERSION, "memory": memory.MEMORY.summary(), "read_only": True}


@app.get("/api/v74.3/memory/recent")
def v743_memory_recent(
    limit: int = Query(100, ge=1, le=1000),
    symbol: Optional[str] = Query(None),
    memory_type: Optional[str] = Query(None),
):
    return {"version": VERSION, **memory.MEMORY.recent(limit=limit, symbol=symbol, memory_type=memory_type), "read_only": True}


class PushSubscription(BaseModel):
    subscription: dict
    label: Optional[str] = None


class PushUnsubscribe(BaseModel):
    endpoint: str


@app.get("/api/v74.3/push/public-key")
def v743_push_public_key():
    cfg=precision.push_config()
    return {"version":VERSION,"configured":cfg.get("configured"),"public_key":cfg.get("public_key"),"library_available":cfg.get("library_available")}


@app.post("/api/v74.3/push/subscribe")
def v743_push_subscribe(payload: PushSubscription):
    try:
        return precision.register_push_subscription(payload.subscription,payload.label)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:180])


@app.post("/api/v74.3/push/unsubscribe")
def v743_push_unsubscribe(payload: PushUnsubscribe):
    return precision.revoke_push_subscription(payload.endpoint)


@app.on_event("startup")
def _start_v743_services():
    precision.start_push_worker()
    precision.heartbeat("V743_RUNTIME","GREEN",release=RELEASE,config_hash=precision.CONFIG_HASH)
    memory.MEMORY.record("VERSION", {"release": RELEASE, "version": VERSION}, scope_key="RUNTIME", event_key=f"startup:{int(time.time())}", source="V74.3 STARTUP", config_hash=precision.CONFIG_HASH)


@app.on_event("shutdown")
def _stop_v743_services():
    precision.stop_push_worker()


# v74_app mounts the cumulative legacy application as a catch-all. V74.3 routes are
# registered after import, so keep every Mount last to ensure the new endpoints win.
try:
    from starlette.routing import Mount
    _mounts=[r for r in app.router.routes if isinstance(r,Mount)]
    _normal=[r for r in app.router.routes if not isinstance(r,Mount)]
    app.router.routes[:] = _normal + _mounts
except Exception:
    pass
