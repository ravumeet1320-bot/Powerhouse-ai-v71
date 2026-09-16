from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
load_dotenv(ROOT / ".env")

from upstox_service import UpstoxAuthError, UpstoxError, UpstoxService  # noqa: E402
from ai_engine import AIFusionEngine  # noqa: E402
from demo_data import demo_snapshot  # noqa: E402
from index_brain import INDEX_UNIVERSES  # noqa: E402
from smart_money import analyse_smart_money
from candle_intel import analyse_candles  # noqa: E402
from nse_oi import fetch_nse_oi_spurts  # noqa: E402
from market_intel import analyse_market_intel  # noqa: E402
from opportunity_engine import build_opportunity_radar  # noqa: E402
from supreme_engine import build_supreme_intelligence  # noqa: E402
from v53_engine import build_v53  # noqa: E402
from v54_engine import build_v54, stock_option_heatmap  # noqa: E402
from v55_engine import build_v55  # noqa: E402
from v56_engine import build_v56, apply_custom_scan  # noqa: E402
from v57_engine import build_v57  # noqa: E402
from v58_engine import build_v58  # noqa: E402
from v60_engine import build_v60, record_outcome
from volume_intel import build_volume_intelligence  # noqa: E402
from daily_plan_engine import build_daily_plan  # noqa: E402
from v61_engine import build_v61, build_replay, alert_center, catalyst_guard, add_catalyst, daily_self_audit  # noqa: E402
from v62_engine import build_v62, record_cross_market, latest_cross_market  # noqa: E402
from v63_engine import build_v63, strongest_sector_today, market_movers, global_markets_dashboard  # noqa: E402
from v64_engine import build_v64, sector_best_opportunities, ingest_institutional, cash_activity, participant_positioning, holding_changes, institutional_footprint_score  # noqa: E402
from v65_engine import build_v65, institutional_money_map, ingest_verified, run_configured_collectors, source_health, ownership_trends, sector_money_map, stock_consensus, participant_trends, promoter_intelligence, deal_timeline, institutional_screener, alerts as v65_alerts, reports as v65_reports, start_collector_scheduler, institution_search, symbol_footprint_timeline, data_completeness  # noqa: E402
from v66_engine import build_v66, metric_history, sector_rotation, option_migration, replay as v66_replay, missed_move_audit, provenance_status, record_detection, chart_workspace  # noqa: E402
from v67_engine import build_v67, build_chart_intelligence, smart_money_advanced  # noqa: E402
from v69_engine import build_v69, depth_intelligence, bulk_block_intelligence  # noqa: E402
from v70_engine import build_v70, hero_history, all_index_rank  # noqa: E402
from v71_engine import build_v71, universal_census, stock_option_hero, chart_intelligence as chart_intelligence_v71, missed_move_audit as missed_move_audit_v71  # noqa: E402
from v72_2_engine import build_v72, pre_move_radar, predictive_strike_selector, predictive_chart_intelligence, lead_time_audit, signal_forensics, replay_timeline  # noqa: E402
from v73_lts_engine import build_v73, circuit_hunter as circuit_hunter_v73, hero_execution_plan as hero_execution_plan_v73, TAB_ARCHITECTURE as V73_TABS, LOCKED_FEATURES as V73_LOCKED_FEATURES  # noqa: E402

ai_engine = AIFusionEngine()

# Multi-device isolation: every browser/PWA installation gets its own UpstoxService.
# Device IDs are random values generated locally by the frontend and contain no personal data.
_services: dict[str, UpstoxService] = {}
_services_lock = threading.RLock()
_oauth_sessions: dict[str, str] = {}
RUNTIME = ROOT / ".runtime" / "devices"

def _clean_device_id(raw: str | None) -> str:
    raw = (raw or "").strip()
    if not raw:
        return "default"
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", raw)[:80]
    return cleaned or "default"

def service_for(device_id: str | None) -> UpstoxService:
    key = _clean_device_id(device_id)
    with _services_lock:
        svc = _services.get(key)
        if svc is None:
            token_file = RUNTIME / key / "upstox_token.json"
            svc = UpstoxService(token_file=token_file)
            _services[key] = svc
            if svc.authenticated:
                svc.start_background()
        return svc

def request_service(request: Request) -> UpstoxService:
    return service_for(request.headers.get("X-Device-ID"))

def _auth_detail(svc: UpstoxService) -> str:
    return "TOKEN INVALID" if getattr(svc, "token_invalid", False) else "Connect Upstox first"

def _require_auth(request: Request) -> UpstoxService:
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    return svc

def _raise_upstox(exc: UpstoxError) -> None:
    if isinstance(exc, UpstoxAuthError) or "TOKEN INVALID" in str(exc).upper():
        raise HTTPException(status_code=401, detail="TOKEN INVALID")
    raise HTTPException(status_code=400, detail=str(exc))

def build_snapshot(request: Request) -> dict:
    """Per-device live snapshot for legacy V64-V67 routes.

    The old single-service helper disappeared during multi-device migration; keeping
    this request-scoped helper prevents cross-device token/data leakage and NameError.
    """
    svc = _require_auth(request)
    return _attach_global_markets(svc, svc.snapshot())

def _attach_global_markets(svc: UpstoxService, snap: dict) -> dict:
    """Attach per-device authenticated global data without leaking tokens into payloads."""
    try:
        snap["upstox_global_markets"] = svc.global_market_snapshot()
    except Exception as exc:
        snap["upstox_global_markets"] = {"status":"UNAVAILABLE","markets":[],"reason":str(exc)[:140]}
    return snap
app = FastAPI(title="POWERHOUSE AI V73 LTS — Institutional Intelligence OS", version="73.0")
start_collector_scheduler()



@app.get("/api/v71/status")
def v71_status(request: Request):
    svc=request_service(request)
    snap=_attach_global_markets(svc, svc.snapshot() if svc.authenticated else demo_snapshot())
    return build_v71(snap, record=bool(svc.authenticated and not getattr(svc, "token_invalid", False)))

@app.get("/api/v71/universe")
def v71_universe(request: Request, stage: str | None = Query(None), side: str | None = Query(None), limit: int = Query(500, ge=1, le=1000)):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    census=universal_census(svc.snapshot(), record=True)
    rows=census.get("all_rows") or []
    if stage:
        want=stage.upper().strip(); rows=[r for r in rows if str(r.get("stage") or "").upper()==want]
    if side:
        want=side.upper().strip(); rows=[r for r in rows if str(r.get("side") or "").upper()==want]
    return {"version":"71.0","coverage":{k:v for k,v in census.items() if k not in ("all_rows","hero_ready","trigger_ready","early_movers","building","top")},"rows":rows[:limit],"returned":min(len(rows),limit),"matched":len(rows),"read_only":True}

@app.get("/api/v71/stock-hero/{symbol}")
def v71_stock_hero(symbol: str, request: Request, force: bool = Query(False)):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    snap=svc.snapshot(); census=universal_census(snap, record=True)
    sym=re.sub(r"[^A-Za-z0-9&.-]", "", symbol.upper())
    row=next((r for r in (census.get("all_rows") or []) if r.get("symbol")==sym), None)
    if not row:
        raise HTTPException(status_code=404, detail=f"{sym} is not in the current discovered F&O census")
    try:
        chain=svc.stock_option_chain_snapshot(sym, force=force)
        return stock_option_hero(sym, row, chain, record=True)
    except UpstoxError as exc:
        _raise_upstox(exc)

@app.get("/api/v71/hero-scan")
def v71_hero_scan(request: Request, max_symbols: int = Query(12, ge=1, le=30), rotate: int = Query(4, ge=0, le=15)):
    """Candidate-first + round-robin stock option Hero scan.

    Every F&O underlying is observed by the universal census first. Rich option-chain
    calls are then allocated to strongest candidates plus rotating names so dormant
    symbols are not permanently excluded by a top-N gate.
    """
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    census=universal_census(svc.snapshot(), record=True); allrows=census.get("all_rows") or []
    hot=[r for r in allrows if r.get("stage") in ("HERO READY","TRIGGER READY","EARLY MOVER","BUILDING")]
    hot_count=max(0,max_symbols-rotate); selected=hot[:hot_count]
    chosen={r.get("symbol") for r in selected}
    universe=[r for r in allrows if r.get("symbol") not in chosen]
    cursor=int(getattr(svc,"v71_option_scan_cursor",0) or 0)
    if universe and rotate:
        for i in range(min(rotate,len(universe))):
            selected.append(universe[(cursor+i)%len(universe)])
        svc.v71_option_scan_cursor=(cursor+min(rotate,len(universe)))%len(universe)
    selected=selected[:max_symbols]
    results=[]; errors=[]
    for row in selected:
        sym=str(row.get("symbol") or "")
        try:
            chain=svc.stock_option_chain_snapshot(sym)
            results.append(stock_option_hero(sym,row,chain,record=True))
        except Exception as exc:
            errors.append({"symbol":sym,"error":str(exc)[:180]})
    winners=[x.get("winner") for x in results if x.get("winner")]
    winners.sort(key=lambda x:(x.get("stage")=="HERO ACTIVE",x.get("stage")=="HERO READY",float(x.get("score") or 0)),reverse=True)
    return {"version":"71.0","universe_observed":census.get("observed"),"universe_expected":census.get("expected_universe"),"underlyings_deep_scanned":len(results),"rotation_cursor":getattr(svc,"v71_option_scan_cursor",0),"winners":winners,"results":results,"errors":errors,"policy":"All underlyings are observed before ranking; option-chain depth is promoted dynamically and round-robin names prevent permanent top-N exclusion. No 100% win guarantee."}

@app.get("/api/v71/chart/{symbol}")
def v71_chart(symbol: str, request: Request, interval: int = Query(5, ge=1, le=30), limit: int = Query(180, ge=20, le=240)):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    sym=re.sub(r"[^A-Za-z0-9&.-]", "", symbol.upper())
    try:
        candles=svc.instrument_candles(sym, interval=interval, limit=limit)
        snap=svc.snapshot(); census=universal_census(snap, record=True)
        row=next((r for r in (census.get("all_rows") or []) if r.get("symbol")==sym), None)
        base_sm=analyse_smart_money(snap)
        v67=build_chart_intelligence(candles,sym,interval,snap,base_sm)
        v67["candle_intel"]=analyse_candles(candles)
        return {"version":"71.0","symbol":sym,"base_chart":v67,"intelligence_chart":chart_intelligence_v71(candles,sym,interval,snap,row),"census_row":row,"read_only":True}
    except UpstoxError as exc:
        _raise_upstox(exc)

@app.get("/api/v71/missed-move-audit")
def v71_missed_move_audit(request: Request, minutes: int = Query(390, ge=30, le=10080), threshold_pct: float = Query(1.25, ge=0.2, le=20)):
    _require_auth(request)
    return missed_move_audit_v71(minutes, threshold_pct)



@app.get("/api/v72/status")
def v72_status(request: Request):
    svc=request_service(request)
    snap=_attach_global_markets(svc, svc.snapshot() if svc.authenticated else demo_snapshot())
    return build_v72(snap, record=bool(svc.authenticated and not getattr(svc, "token_invalid", False)))

@app.get("/api/v72/universe")
def v72_universe(request: Request, stage: str | None = Query(None), side: str | None = Query(None), limit: int = Query(500, ge=1, le=1000)):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    radar=pre_move_radar(svc.snapshot(), record=True)
    rows=radar.get("rows") or []
    if stage:
        want=stage.upper().strip(); rows=[r for r in rows if str(r.get("pre_move_stage") or "").upper()==want]
    if side:
        want=side.upper().strip(); rows=[r for r in rows if str(r.get("v72_side") or "").upper()==want]
    return {"version":"72.2","coverage":{k:v for k,v in radar.items() if k not in ("rows","top","trigger_ready","arming","building","late")},"rows":rows[:limit],"matched":len(rows),"returned":min(len(rows),limit),"read_only":True}

@app.get("/api/v72/stock-strike/{symbol}")
def v72_stock_strike(symbol: str, request: Request, compare_expiries: int = Query(2, ge=1, le=2), force: bool = Query(False)):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    sym=re.sub(r"[^A-Za-z0-9&.-]", "", symbol.upper())
    radar=pre_move_radar(svc.snapshot(), record=True)
    row=next((r for r in (radar.get("rows") or []) if r.get("symbol")==sym),None)
    if not row:
        raise HTTPException(status_code=404, detail=f"{sym} is not in the current discovered F&O census")
    try:
        first=svc.stock_option_chain_snapshot(sym, force=force)
        packs=[predictive_strike_selector(sym,row,first)]
        expiries=first.get("expiries") or []
        if compare_expiries>1 and len(expiries)>1:
            second=svc.stock_option_chain_snapshot(sym, force=force, expiry_override=expiries[1])
            packs.append(predictive_strike_selector(sym,row,second))
        eligible=[x for x in packs if x.get("winner")]
        chosen=max(eligible,key=lambda x:(float((x.get("winner") or {}).get("score") or 0), x.get("multi_strike_confirmation") is True),default=(packs[0] if packs else None))
        return {"version":"72.2","symbol":sym,"underlying":row,"expiry_comparison":packs,"chosen":chosen,"read_only":True,"policy":"At most two listed expiries are compared on-demand; whole-market scanning does not continuously fetch every chain."}
    except UpstoxError as exc:
        _raise_upstox(exc)

@app.get("/api/v72/hero-scan")
def v72_hero_scan(request: Request, max_symbols: int = Query(12, ge=1, le=20), rotate: int = Query(4, ge=0, le=10)):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    radar=pre_move_radar(svc.snapshot(), record=True); rows=radar.get("rows") or []
    hot=[r for r in rows if r.get("pre_move_stage") in ("TRIGGER READY","ARMING","BUILDING") and not r.get("late_entry") and r.get("v72_side") in ("CE","PE")]
    hot_count=max(0,max_symbols-rotate); selected=hot[:hot_count]; chosen={r.get("symbol") for r in selected}
    universe=[r for r in rows if r.get("symbol") not in chosen and not r.get("late_entry")]
    cursor=int(getattr(svc,"v72_option_scan_cursor",0) or 0)
    if universe and rotate:
        for i in range(min(rotate,len(universe))): selected.append(universe[(cursor+i)%len(universe)])
        svc.v72_option_scan_cursor=(cursor+min(rotate,len(universe)))%len(universe)
    selected=selected[:max_symbols]
    results=[]; errors=[]
    for row in selected:
        sym=str(row.get("symbol") or "")
        try:
            chain=svc.stock_option_chain_snapshot(sym)
            results.append(predictive_strike_selector(sym,row,chain))
        except Exception as exc:
            errors.append({"symbol":sym,"error":str(exc)[:180]})
    winners=[x.get("winner") | {"hero_state":x.get("hero_state"),"pcr":x.get("pcr"),"why_not_hero":x.get("why_not_hero")} for x in results if x.get("winner")]
    winners.sort(key=lambda x:(str(x.get("hero_state") or "").startswith("HERO"),float(x.get("score") or 0)),reverse=True)
    return {"version":"72.2","universe_observed":radar.get("observed"),"universe_expected":radar.get("expected_universe"),"underlyings_deep_scanned":len(results),"rotation_cursor":getattr(svc,"v72_option_scan_cursor",0),"winners":winners,"results":results,"errors":errors,"policy":"Pre-move candidates are promoted first; rotating names preserve discovery coverage. ₹50+ Hero floor, no upper premium cap, no guaranteed profit."}

@app.get("/api/v72/chart/{symbol}")
def v72_chart(symbol: str, request: Request, interval: int = Query(5, ge=1, le=30), limit: int = Query(180, ge=20, le=240)):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    sym=re.sub(r"[^A-Za-z0-9&.-]", "", symbol.upper())
    try:
        candles=svc.instrument_candles(sym, interval=interval, limit=limit)
        snap=svc.snapshot(); radar=pre_move_radar(snap,record=True)
        row=next((r for r in (radar.get("rows") or []) if r.get("symbol")==sym),None)
        base_sm=analyse_smart_money(snap); v67=build_chart_intelligence(candles,sym,interval,snap,base_sm); v67["candle_intel"]=analyse_candles(candles)
        v71=chart_intelligence_v71(candles,sym,interval,snap,row)
        pred=predictive_chart_intelligence(candles,sym,interval,snap,row)
        return {"version":"72.2","symbol":sym,"base_chart":v67,"intelligence_chart":v71,"predictive_chart":pred,"census_row":row,"read_only":True}
    except UpstoxError as exc:
        _raise_upstox(exc)

@app.get("/api/v72/lead-time-audit")
def v72_lead_time_audit(request: Request, minutes: int = Query(390, ge=30, le=10080), threshold_pct: float = Query(1.25, ge=0.2, le=20)):
    _=request_service(request)
    return lead_time_audit(minutes,threshold_pct)

@app.get("/api/v72/forensics")
def v72_forensics(request: Request, minutes: int = Query(390, ge=30, le=10080)):
    _=request_service(request)
    return signal_forensics(minutes)

@app.get("/api/v72/replay/{symbol}")
def v72_replay(symbol: str, request: Request, minutes: int = Query(390, ge=30, le=10080)):
    _=request_service(request)
    sym=re.sub(r"[^A-Za-z0-9&.-]", "", symbol.upper())
    return replay_timeline(sym, minutes)



# ---------- V73 LTS Institutional Intelligence OS ----------
@app.get("/api/v73/status")
def v73_status(request: Request):
    svc=request_service(request)
    snap=_attach_global_markets(svc, svc.snapshot() if svc.authenticated else demo_snapshot())
    return build_v73(snap, record=bool(svc.authenticated and not getattr(svc, "token_invalid", False)))

@app.get("/api/v73/tabs")
def v73_tabs():
    return {"version":"73.0","tabs":V73_TABS,"locked_features":V73_LOCKED_FEATURES,"read_only":True}

@app.get("/api/v73/coverage")
def v73_coverage(request: Request):
    svc=request_service(request)
    snap=_attach_global_markets(svc, svc.snapshot() if svc.authenticated else demo_snapshot())
    out=build_v73(snap, record=False)
    return {"version":"73.0","coverage":out.get("opportunity_coverage"),"data_quality":out.get("data_quality"),"performance":out.get("performance"),"read_only":True}

@app.get("/api/v73/circuit-hunter")
def v73_circuit_hunter(request: Request, limit: int = Query(40, ge=1, le=200)):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    return circuit_hunter_v73(svc.snapshot(), limit=limit)

@app.get("/api/v73/alerts")
def v73_alerts(request: Request):
    svc=request_service(request)
    snap=_attach_global_markets(svc, svc.snapshot() if svc.authenticated else demo_snapshot())
    return build_v73(snap, record=False).get("alerts")

@app.get("/api/v73/hero/{symbol}")
def v73_hero(symbol: str, request: Request, force: bool = Query(False), interval: int = Query(5, ge=1, le=30), limit: int = Query(120, ge=20, le=240)):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    sym=re.sub(r"[^A-Za-z0-9&.-]", "", symbol.upper())
    snap=svc.snapshot(); radar=pre_move_radar(snap, record=True)
    row=next((r for r in (radar.get("rows") or []) if r.get("symbol")==sym),None)
    if not row:
        raise HTTPException(status_code=404, detail=f"{sym} is not in the current discovered F&O census")
    try:
        chain=svc.stock_option_chain_snapshot(sym, force=force)
        pack=predictive_strike_selector(sym,row,chain)
        chart=None
        try:
            candles=svc.instrument_candles(sym, interval=interval, limit=limit)
            chart=predictive_chart_intelligence(candles,sym,interval,snap,row)
        except Exception:
            chart=None
        return {"version":"73.0","symbol":sym,"underlying":row,"strike_intelligence":pack,"chart_context":chart,"execution_plan":hero_execution_plan_v73(sym,row,pack,chart),"read_only":True}
    except UpstoxError as exc:
        _raise_upstox(exc)


@app.get("/api/v70/status")
def v70_status(request: Request):
    svc=request_service(request)
    snap=_attach_global_markets(svc, svc.snapshot() if svc.authenticated else demo_snapshot())
    return build_v70(snap, record=svc.authenticated)

@app.get("/api/v70/hero")
def v70_hero(request: Request):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False): raise HTTPException(status_code=401, detail=_auth_detail(svc))
    snap=_attach_global_markets(svc, svc.snapshot())
    return build_v70(snap, record=True).get("expiry_precision_hero")

@app.get("/api/v70/hero-radar")
def v70_hero_radar(request: Request):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False): raise HTTPException(status_code=401, detail=_auth_detail(svc))
    results=[]; errors=[]
    active=str(getattr(svc,"active_code","NIFTY") or "NIFTY").upper()
    for code in ("NIFTY","BANKNIFTY","MIDCPNIFTY","SENSEX"):
        try:
            if code==active:
                snap=_attach_global_markets(svc,svc.snapshot())
                out=build_v70(snap,record=True)
            else:
                snap=svc.snapshot_for_underlying(code)
                out=build_v70(snap,record=False)
            results.append(out)
        except Exception as exc:
            errors.append({"underlying":code,"error":str(exc)[:180]})
            results.append({"expiry_precision_hero":{"underlying":code,"expiry":None,"state":"UNAVAILABLE","side":"WAIT","score":0,"winner":None,"data_truth":{"score":0,"source":"UNAVAILABLE","freshness":"UNAVAILABLE"}}})
    ranked=all_index_rank(results)
    ranked["errors"]=errors
    ranked["read_only"]=True
    ranked["execution_enabled"]=False
    return ranked

@app.get("/api/v70/history")
def v70_history(request: Request, underlying: str = Query("NIFTY"), minutes: int = Query(390, ge=5, le=43200)):
    _require_auth(request)
    return hero_history(underlying,minutes)


@app.get("/api/v69/status")
def v69_status(request: Request):
    svc=request_service(request)
    snap=_attach_global_markets(svc, svc.snapshot() if svc.authenticated else demo_snapshot())
    return build_v69(snap)

@app.get("/api/v69/depth")
def v69_depth(request: Request, symbol: str | None = None):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False): raise HTTPException(status_code=401, detail=_auth_detail(svc))
    return depth_intelligence(svc.snapshot(), symbol)

@app.get("/api/v69/bulk-block")
def v69_bulk_block(request: Request, limit: int = Query(100, ge=1, le=500)):
    _require_auth(request)
    return bulk_block_intelligence(limit)

@app.get("/api/v67/status")
def v67_status(request: Request):
    _require_auth(request)
    snap=build_snapshot(request)
    base_sm=analyse_smart_money(snap)
    snap["_base_smart_money"]=base_sm
    return build_v67(snap, build_v66(snap, build_v65(snap, build_v64(snap, build_v63(snap)))))

@app.get("/api/v67/symbols")
def v67_symbols(request: Request):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False): raise HTTPException(status_code=401, detail=_auth_detail(svc))
    try:
        symbols=svc.fno_chart_symbols()
        return {"indexes":["NIFTY","BANKNIFTY","MIDCPNIFTY","SENSEX"],"fno":symbols,"count":len(symbols),"source":"Official Upstox NSE BOD instrument universe"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.get("/api/v67/chart/{symbol}")
def v67_chart(symbol: str, request: Request, interval: int = Query(5, ge=1, le=30), limit: int = Query(160, ge=20, le=240)):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False): raise HTTPException(status_code=401, detail=_auth_detail(svc))
    try:
        rows=svc.instrument_candles(symbol, interval=interval, limit=limit)
        snap=svc.snapshot(); base_sm=analyse_smart_money(snap)
        out=analyse_candles(rows)
        adv=build_chart_intelligence(rows, symbol, interval, snap, base_sm)
        adv["candle_intel"]=out
        return adv
    except UpstoxError as exc:
        _raise_upstox(exc)

@app.get("/api/v67/smart-money")
def v67_smart_money(request: Request):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False): raise HTTPException(status_code=401, detail=_auth_detail(svc))
    snap=svc.snapshot(); base=analyse_smart_money(snap)
    return {"base":base,"advanced":smart_money_advanced(snap,base,None)}

@app.get("/api/v67/scan")
def v67_scan(request: Request, interval: int = Query(5, ge=1, le=30), limit: int = Query(12, ge=3, le=30)):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False): raise HTTPException(status_code=401, detail=_auth_detail(svc))
    try:
        symbols=svc.fno_chart_symbols()
        # Prefer currently live F&O equities with largest absolute move; fallback alphabetical.
        live=[]
        for row in (svc.fno_equities or {}).values():
            if row.get("symbol"):
                live.append((abs(float(row.get("change_pct") or row.get("cp") or 0)), str(row.get("symbol")).upper()))
        ordered=[s for _,s in sorted(live, reverse=True)] or symbols
        seen=set(); picks=[]
        for s in ordered:
            if s not in seen:
                seen.add(s); picks.append(s)
            if len(picks)>=limit: break
        snap=svc.snapshot(); base=analyse_smart_money(snap); results=[]; errors=[]
        for sym in picks:
            try:
                rows=svc.instrument_candles(sym,interval=interval,limit=100)
                x=build_chart_intelligence(rows,sym,interval,snap,base)
                pm=x.get("pre_move_radar") or {}; fp=(x.get("forming_patterns") or [{}])[0]
                score=float(fp.get("formation_quality") or 0) + (12 if pm.get("trigger_near") else 0) + (8 if pm.get("rvol_awakening") else 0)
                results.append({"symbol":sym,"score":round(score,1),"pattern":pm.get("pattern"),"stage":pm.get("pattern_stage"),"trigger_near":pm.get("trigger_near"),"rvol_awakening":pm.get("rvol_awakening"),"smart_money":(x.get("smart_money") or {}).get("state"),"pressure":(x.get("smart_money") or {}).get("pressure_score"),"structure":(x.get("market_structure") or {}).get("state")})
            except Exception as exc:
                errors.append({"symbol":sym,"error":str(exc)[:160]})
        results.sort(key=lambda x:x.get("score") or 0,reverse=True)
        return {"interval":interval,"scanned":len(results),"results":results,"errors":errors[:5],"truth":"Scanner ranks evidence quality; score is not probability of profit."}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.get("/api/v66/status")
def v66_status(request: Request):
    _require_auth(request)
    snap=build_snapshot(request)
    v65=build_v65(snap, build_v64(snap, build_v63(snap)))
    return build_v66(snap, v65)

@app.get("/api/v66/history/{symbol}")
def v66_history(symbol: str, request: Request, minutes: int = Query(60, ge=1, le=10080)):
    _require_auth(request); return metric_history(symbol, minutes)

@app.get("/api/v66/sector-rotation")
def v66_sector_rotation(request: Request, minutes: int = Query(60, ge=5, le=1440)):
    _require_auth(request); return sector_rotation(minutes)

@app.get("/api/v66/option-migration")
def v66_option_migration(request: Request, underlying: str = Query("NIFTY"), minutes: int = Query(60, ge=5, le=1440)):
    _require_auth(request); return option_migration(underlying, minutes)

@app.get("/api/v66/replay/{symbol}")
def v66_symbol_replay(symbol: str, request: Request, minutes: int = Query(390, ge=5, le=10080), speed: int = Query(10, ge=1, le=100)):
    _require_auth(request); return v66_replay(symbol, minutes, speed)

@app.get("/api/v66/missed-move-audit")
def v66_missed_audit(request: Request, minutes: int = Query(390, ge=30, le=10080), threshold_pct: float = Query(2.0, ge=0.2, le=20)):
    _require_auth(request); return missed_move_audit(minutes, threshold_pct)

@app.get("/api/v66/provenance")
def v66_provenance(request: Request):
    _require_auth(request); return provenance_status()

@app.get("/api/v66/chart/{symbol}")
def v66_chart(symbol: str, request: Request, minutes: int = Query(390, ge=5, le=10080)):
    _require_auth(request); return chart_workspace(symbol, minutes)

@app.post("/api/v66/detection")
async def v66_detection(request: Request):
    _require_auth(request); return record_detection(await request.json())

@app.get("/api/v65/status")
def v65_status(request: Request):
    _require_auth(request)
    snap=build_snapshot(request)
    return build_v65(snap, build_v64(snap, build_v63(snap)))

@app.get("/api/v65/money-map")
def v65_money_map(request: Request):
    _require_auth(request)
    return institutional_money_map(build_snapshot(request))

@app.get("/api/v65/source-health")
def v65_source_health(request: Request):
    _require_auth(request)
    return source_health()

@app.post("/api/v65/collect")
def v65_collect(request: Request):
    _require_auth(request)
    return run_configured_collectors()

@app.post("/api/v65/ingest/{dataset}")
async def v65_ingest(dataset: str, request: Request):
    _require_auth(request)
    body=await request.json()
    rows=body.get("rows") or []
    if isinstance(rows,dict): rows=[rows]
    try: return ingest_verified(dataset,rows,str(body.get("source_id") or "MANUAL_USER"),body.get("source_url"),body.get("source_timestamp"))
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc))

@app.get("/api/v65/ownership-trends")
def v65_ownership_trends(request: Request):
    _require_auth(request); return ownership_trends()

@app.get("/api/v65/sector-money-map")
def v65_sector_money_map(request: Request):
    _require_auth(request); return sector_money_map(build_snapshot(request))

@app.get("/api/v65/stock-consensus")
def v65_stock_consensus(request: Request):
    _require_auth(request); return stock_consensus(build_snapshot(request))

@app.get("/api/v65/participant-trends")
def v65_participant_trends(request: Request):
    _require_auth(request); return participant_trends()

@app.get("/api/v65/promoter")
def v65_promoter(request: Request):
    _require_auth(request); return promoter_intelligence()

@app.get("/api/v65/deals")
def v65_deals(request: Request):
    _require_auth(request); return deal_timeline()

@app.post("/api/v65/screener")
async def v65_screener(request: Request):
    _require_auth(request); body=await request.json(); return institutional_screener(build_snapshot(request),body or {})

@app.get("/api/v65/alerts")
def v65_alert_center(request: Request):
    _require_auth(request); return v65_alerts()

@app.get("/api/v65/reports")
def v65_reporting(request: Request):
    _require_auth(request); return v65_reports(build_snapshot(request))

@app.get("/api/v65/institution-search")
def v65_institution_search(request: Request, q: str = Query(..., min_length=1)):
    _require_auth(request); return institution_search(q)

@app.get("/api/v65/symbol/{symbol}/timeline")
def v65_symbol_timeline(symbol: str, request: Request):
    _require_auth(request); return symbol_footprint_timeline(symbol)

@app.get("/api/v65/data-completeness")
def v65_data_completeness(request: Request):
    _require_auth(request); return data_completeness()


@app.get("/api/v64/status")
def v64_status(request: Request):
    _require_auth(request)
    snap=build_snapshot(request)
    return build_v64(snap, build_v63(snap))

@app.get("/api/v64/sector-opportunity")
def v64_sector_opportunity(request: Request):
    _require_auth(request)
    return sector_best_opportunities(build_snapshot(request))

@app.get("/api/v64/institutional-footprints")
def v64_institutional_footprints(request: Request):
    _require_auth(request)
    return institutional_footprint_score(build_snapshot(request))

@app.get("/api/v64/cash-activity")
def v64_cash_activity(request: Request):
    _require_auth(request)
    return cash_activity()

@app.get("/api/v64/participant-positioning")
def v64_participant_positioning(request: Request):
    _require_auth(request)
    return participant_positioning()

@app.get("/api/v64/holding-changes")
def v64_holding_changes(request: Request):
    _require_auth(request)
    return holding_changes()

@app.post("/api/v64/institutional/ingest")
async def v64_institutional_ingest(request: Request):
    _require_auth(request)
    body=await request.json()
    return ingest_institutional(body)

@app.post("/api/v63/global-markets/ingest")
async def v63_global_markets_ingest(request: Request):
    body=await request.json()
    market=str(body.get("market") or "").upper().strip()
    allowed={"GIFT NIFTY","INDIA VIX"}
    if market not in allowed: raise HTTPException(status_code=400,detail="Unsupported global market")
    try: row=record_cross_market(market,body.get("price"),body.get("change_pct"),str(body.get("source") or "manual_verified_ingest"),bool(body.get("verified",False)),body.get("epoch"),body)
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc))
    return {"ok":True,"row":row,"read_only":True}

@app.get("/api/v63/status")
def v63_status(request: Request):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False): raise HTTPException(status_code=401, detail=_auth_detail(svc))
    snap=_attach_global_markets(svc, svc.snapshot())
    return build_v63(snap)

@app.get("/api/v63/strongest-sector")
def v63_strongest_sector(request: Request):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False): raise HTTPException(status_code=401, detail=_auth_detail(svc))
    return strongest_sector_today(svc.snapshot())

@app.get("/api/v63/market-movers")
def v63_market_movers(request: Request):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False): raise HTTPException(status_code=401, detail=_auth_detail(svc))
    return market_movers(svc.snapshot())

@app.get("/api/v63/global-markets")
def v63_global_markets(request: Request):
    svc=request_service(request)
    snap=_attach_global_markets(svc, svc.snapshot()) if svc.authenticated else {"active_underlying":"NIFTY"}
    return global_markets_dashboard(snap)

app.mount("/static", StaticFiles(directory=STATIC), name="static")


class TokenBody(BaseModel):
    access_token: str
    persist: bool = True


class ExpiryBody(BaseModel):
    expiry: str

class UnderlyingBody(BaseModel):
    code: str


@app.on_event("startup")
def startup() -> None:
    # Device services are created lazily on first request.
    pass


@app.on_event("shutdown")
def shutdown() -> None:
    with _services_lock:
        for svc in _services.values():
            svc.stop()


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def sw() -> FileResponse:
    return FileResponse(STATIC / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/api/upstox/status")
def status(request: Request):
    return request_service(request).status()


@app.get("/api/upstox/login")
def login(device_id: str = Query("default")):
    svc = service_for(device_id)
    try:
        url = svc.oauth_login_url()
        if svc.oauth_state:
            _oauth_sessions[svc.oauth_state] = _clean_device_id(device_id)
        return RedirectResponse(url, status_code=302)
    except UpstoxError as exc:
        _raise_upstox(exc)


@app.get("/api/upstox/callback")
def callback(code: str = Query(...), state: Optional[str] = None):
    try:
        device_id = _oauth_sessions.pop(state or "", "default")
        service_for(device_id).exchange_code(code, state)
        return HTMLResponse(
            """
            <html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>
            <body style='font-family:system-ui;background:#071018;color:#fff;padding:28px'>
            <h2>Upstox connected.</h2>
            <p>Returning to NIFTY Powerhouse AI Index Brain…</p>
            <script>setTimeout(()=>{location.href='/'},900)</script>
            </body></html>
            """
        )
    except UpstoxError as exc:
        _raise_upstox(exc)


@app.post("/api/upstox/manual-token")
def manual_token(body: TokenBody, request: Request):
    svc = request_service(request)
    if getattr(svc, "server_token_configured", False):
        raise HTTPException(status_code=409, detail="Server Analytics Token is active; browser token override is disabled")
    try:
        svc.set_manual_token(body.access_token, body.persist)
        return {"ok": True, "status": svc.status()}
    except UpstoxError as exc:
        _raise_upstox(exc)


@app.post("/api/upstox/logout")
def logout(request: Request):
    svc = request_service(request)
    svc.clear_token()
    return {"ok": True, "status": svc.status(), "server_token_preserved": bool(getattr(svc, "server_token_configured", False))}


@app.get("/api/upstox/expiries")
def expiries(request: Request, force: bool = False):
    svc = request_service(request)
    try:
        return {"ok": True, "expiries": svc.fetch_expiries(force=force)}
    except UpstoxError as exc:
        _raise_upstox(exc)


@app.post("/api/upstox/expiry")
def set_expiry(body: ExpiryBody, request: Request):
    svc = request_service(request)
    try:
        svc.set_expiry(body.expiry)
        return svc.snapshot()
    except UpstoxError as exc:
        _raise_upstox(exc)


@app.post("/api/upstox/underlying")
def set_underlying(body: UnderlyingBody, request: Request):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    try:
        svc.set_underlying(body.code)
        return svc.status()
    except UpstoxError as exc:
        _raise_upstox(exc)


@app.get("/api/nse/oi-spurts")
def nse_oi_spurts():
    return fetch_nse_oi_spurts()


@app.post("/api/upstox/resync")
def resync(request: Request):
    svc = request_service(request)
    try:
        svc.sync_chain_rest()
        svc.sync_analytics()
        return svc.snapshot()
    except UpstoxError as exc:
        _raise_upstox(exc)


@app.get("/api/health")
def health(request: Request):
    svc = request_service(request)
    return {
        "ok": True,
        "app": "POWERHOUSE AI V73 LTS",
        "version": "73.0",
        "lts": True,
        "v72_2_compatibility": True,
        "universal_opportunity_radar": True,
        "intelligence_chart": True,
        "expiry_precision_hero": True,
        "institutional_footprints": True,
        "multi_device_laptop": True,
        "mode": "ai_index_brain_read_only_signals",
        "orders_enabled": False,
        "pnl_enabled": False,
        "execution_enabled": False,
        "upstox_authenticated": svc.authenticated,
        "upstox_data_status": svc.status().get("data_status"),
        "upstox_server_token_configured": bool(getattr(svc, "server_token_configured", False)),
        "multi_device": True,
    }


@app.get("/api/index/weights")
def index_weights():
    """Read-only constituent/weight metadata used by Index Brain."""
    return {
        code: {
            "label": cfg["label"],
            "weights_as_of": cfg["weights_as_of"],
            "weights_source": cfg["weights_source"],
            "tracked_weight_pct": round(sum(float(x["weight"]) for x in cfg["stocks"]), 2),
            "stocks": cfg["stocks"],
        }
        for code, cfg in INDEX_UNIVERSES.items()
    }


@app.get("/api/upstox/diagnostics")
def diagnostics(request: Request):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    return svc.diagnostics()


@app.get("/api/upstox/snapshot")
def snapshot(request: Request):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    snap = svc.snapshot()
    if not snap.get("option_data"):
        try:
            svc.sync_chain_rest()
            snap = svc.snapshot()
        except UpstoxError as exc:
            _raise_upstox(exc)
    return snap


@app.get("/api/ai/snapshot")
def ai_snapshot(request: Request, mode: str = Query("strict", pattern="^(strict|balanced|fast)$")):
    """Return one resilient read-only analytics snapshot.

    V72 preserves resilient optional-module isolation so one broken engine or a temporary
    option-chain REST error cannot blank the whole application while the market
    transport is otherwise healthy.
    """
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))

    snap = _attach_global_markets(svc, svc.snapshot())
    chain_error = None
    if not snap.get("option_data"):
        try:
            svc.sync_chain_rest()
            svc.sync_analytics()
            snap = _attach_global_markets(svc, svc.snapshot())
        except UpstoxError as exc:
            chain_error = str(exc)
            snap = _attach_global_markets(svc, svc.snapshot())

    if getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail="TOKEN INVALID")

    if chain_error:
        snap["chain_status"] = "UNAVAILABLE"
        snap["chain_error"] = chain_error
        note = str(snap.get("analytics_note") or "").strip()
        snap["analytics_note"] = (note + " | " if note else "") + "Option chain temporarily unavailable; non-chain live inputs remain active."
    else:
        snap["chain_status"] = "READY" if snap.get("option_data") else "WARMING"

    module_health: dict[str, dict] = {}

    def safe_build(name: str, fn, fallback=None):
        try:
            value = fn()
            module_health[name] = {"ok": True, "status": "READY"}
            return value
        except Exception as exc:  # optional analytics must never blank the whole UI
            module_health[name] = {"ok": False, "status": "UNAVAILABLE", "error": str(exc)[:180]}
            return fallback

    ai = safe_build("ai", lambda: ai_engine.analyse(snap, mode=mode), {
        "ok": True, "mode": mode, "signal": "WAIT", "side": "WAIT",
        "raw_side": "WAIT", "confidence": 0, "fusion_score": 0,
        "agreement": 0, "conflict": 0, "regime": "NO_DATA",
        "lifecycle": "FILTERED", "data_quality": 0, "data_age_seconds": None,
        "data_quality_notes": ["AI module unavailable"], "trap_risk": 100,
        "agents": [], "top_contract": None, "backups": [], "radar": [],
        "summary": "AI analytics temporarily unavailable; market transport may still be live.",
        "metrics": {}, "orders_enabled": False,
    })
    sm = safe_build("smart_money", lambda: analyse_smart_money(snap), {})
    market_intel = safe_build("market_intel", lambda: analyse_market_intel(snap, ai, sm), {})
    radar = safe_build("v31", lambda: build_opportunity_radar(snap, ai, sm), {})

    for _c in ((radar or {}).get("best_now") or [])[:5]:
        try:
            record_detection({"symbol":_c.get("symbol"),"price":_c.get("ltp"),"action":_c.get("side"),"stage":_c.get("lifecycle"),"score":_c.get("quality"),"sector":_c.get("sector"),"evidence":_c.get("reasons")})
        except Exception:
            pass

    v50 = safe_build("v50", lambda: build_supreme_intelligence(snap, ai, sm, radar or {}), {})
    v53 = safe_build("v53", lambda: build_v53(snap, ai, sm, radar or {}, v50 or {}), {})
    v54 = safe_build("v54", lambda: build_v54(snap, ai, sm, radar or {}, v53 or {}), {})
    v55 = safe_build("v55", lambda: build_v55(snap, v53 or {}), {})
    v56 = safe_build("v56", lambda: build_v56(snap, v55 or {}), {})
    v57 = safe_build("v57", lambda: build_v57(snap, v56 or {}), {})
    v58 = safe_build("v58", lambda: build_v58(snap, v57 or {}), {})
    v60 = safe_build("v60", lambda: build_v60(snap, v58 or {}), {})
    volume = safe_build("volume_intelligence", lambda: build_volume_intelligence(snap), {})
    daily_plan = safe_build("daily_plan", lambda: build_daily_plan(snap, v60 or {}, volume or {}), {})
    v61 = safe_build("v61", lambda: build_v61(snap, v60 or {}), {})
    v62 = safe_build("v62", lambda: build_v62(snap, v60 or {}, v61 or {}), {})
    v63 = safe_build("v63", lambda: build_v63(snap, v62 or {}), {})
    v64 = safe_build("v64", lambda: build_v64(snap, v63 or {}), {})
    v65 = safe_build("v65", lambda: build_v65(snap, v64 or {}), {})
    v66 = safe_build("v66", lambda: build_v66(snap, v65 or {}), {})
    v70 = safe_build("v70", lambda: build_v70(snap, record=not bool(snap.get("demo"))), {})
    v71 = safe_build("v71", lambda: build_v71(snap, record=not bool(snap.get("demo"))), {})
    v72 = safe_build("v72", lambda: build_v72(snap, record=not bool(snap.get("demo"))), {})

    provider_status = svc.status()
    data_status = provider_status.get("data_status") or snap.get("data_status") or "WARMING"
    snapshot_health = {
        "status": "READY" if data_status in ("LIVE", "REST") else data_status,
        "data_status": data_status,
        "transport": "WS" if data_status == "LIVE" else ("REST" if data_status == "REST" else data_status),
        "tick_age_sec": provider_status.get("tick_age_sec"),
        "rest_age_sec": provider_status.get("rest_age_sec"),
        "chain": snap.get("chain_status") or ("READY" if snap.get("option_data") else "WARMING"),
        "module_ready": sum(1 for x in module_health.values() if x.get("ok")),
        "module_total": len(module_health),
        "errors": {k:v.get("error") for k,v in module_health.items() if not v.get("ok")},
    }

    return {
        "market": snap, "ai": ai, "smart_money": sm, "market_intel": market_intel,
        "v31": radar, "v50": v50, "v53": v53, "v54": v54, "v55": v55,
        "v56": v56, "v57": v57, "v58": v58, "v60": v60,
        "volume_intelligence": volume, "daily_plan": daily_plan, "v61": v61,
        "v62": v62, "v63": v63, "v64": v64, "v65": v65, "v66": v66,
        "v70": v70, "v71": v71, "v72": v72, "snapshot_health": snapshot_health,
        "module_health": module_health,
    }



@app.get("/api/chart/candles")
def chart_candles(request: Request, interval: int = Query(5), limit: int = Query(120)):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    try:
        rows = svc.intraday_candles(interval=interval, limit=limit)
        out = analyse_candles(rows)
        out.update({"interval": interval, "underlying": getattr(svc, "active_underlying", "NIFTY"), "read_only": True})
        return out
    except UpstoxError as exc:
        _raise_upstox(exc)


@app.get("/api/smart-money")
def smart_money(request: Request):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    return analyse_smart_money(svc.snapshot())

@app.get("/api/ai/demo")
def ai_demo(mode: str = Query("strict", pattern="^(strict|balanced|fast)$")):
    snap = demo_snapshot()
    ai = ai_engine.analyse(snap, mode=mode)
    sm = analyse_smart_money(snap)
    radar = build_opportunity_radar(snap, ai, sm)
    v50 = build_supreme_intelligence(snap, ai, sm, radar)
    v53 = build_v53(snap, ai, sm, radar, v50)
    return {"market": snap, "ai": ai, "smart_money": sm, "market_intel": analyse_market_intel(snap, ai, sm), "v31": radar, "v50": v50, "v53": v53, "v54": build_v54(snap, ai, sm, radar, v53), "v55": build_v55(snap, v53), "v56": build_v56(snap, build_v55(snap, v53)), "v57": build_v57(snap, build_v56(snap, build_v55(snap, v53))), "v58": build_v58(snap, build_v57(snap, build_v56(snap, build_v55(snap, v53)))), "v60": build_v60(snap, build_v58(snap, build_v57(snap, build_v56(snap, build_v55(snap, v53))))), "volume_intelligence": build_volume_intelligence(snap), "daily_plan": build_daily_plan(snap, build_v60(snap, build_v58(snap, build_v57(snap, build_v56(snap, build_v55(snap, v53))))), build_volume_intelligence(snap)), "v61": build_v61(snap, build_v60(snap, build_v58(snap, build_v57(snap, build_v56(snap, build_v55(snap, v53)))))), "v62": build_v62(snap, build_v60(snap, build_v58(snap, build_v57(snap, build_v56(snap, build_v55(snap, v53))))), build_v61(snap, build_v60(snap, build_v58(snap, build_v57(snap, build_v56(snap, build_v55(snap, v53))))))), "v63": build_v63(snap, build_v62(snap, build_v60(snap, build_v58(snap, build_v57(snap, build_v56(snap, build_v55(snap, v53))))), build_v61(snap, build_v60(snap, build_v58(snap, build_v57(snap, build_v56(snap, build_v55(snap, v53)))))))), "v64": build_v64(snap, build_v63(snap)), "v65": build_v65(snap, build_v64(snap, build_v63(snap))), "v66": build_v66(snap, build_v65(snap, build_v64(snap, build_v63(snap)))), "v70": build_v70(snap, record=False), "v71": build_v71(snap, record=False), "v72": build_v72(snap, record=False), "demo": True}


@app.post("/api/v60/outcome")
async def v60_outcome(request: Request):
    """Read-only diagnostic hook for verified post-move/session-replay outcomes. Never places orders."""
    body = await request.json()
    try:
        ev = record_outcome(
            body.get("symbol"),
            body.get("category"),
            body.get("detail", ""),
            body.get("move_pct"),
            body.get("detected_epoch"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "read_only": True, "event": ev}

@app.get("/api/v60/status")
def v60_status(request: Request):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    snap=svc.snapshot(); ai=ai_engine.analyse(snap, mode="strict"); sm=analyse_smart_money(snap)
    radar=build_opportunity_radar(snap, ai, sm); v50=build_supreme_intelligence(snap, ai, sm, radar); v53=build_v53(snap, ai, sm, radar, v50)
    v55=build_v55(snap,v53); v56=build_v56(snap,v55); v57=build_v57(snap,v56); v58=build_v58(snap,v57); v60=build_v60(snap,v58)
    return {"ok":True,"read_only":True,"version":"60.0","production_readiness":v60.get("production_readiness"),"scanner_health":v60.get("scanner_health"),"detection_benchmark":v60.get("detection_benchmark")}



@app.get("/api/v60/daily-plan")
def v60_daily_plan(request: Request):
    """Read-only daily/next-session NIFTY scenario plan over verified connected data."""
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    snap=svc.snapshot()
    vol=build_volume_intelligence(snap)
    return build_daily_plan(snap, None, vol)

@app.get("/api/v60/fno-foundation")
def v60_fno_foundation(request: Request):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    try:
        svc.discover_full_fno_universe()
        svc.sync_full_fno_quotes(force=True)
    except Exception:
        pass
    return svc.fno_foundation_status()


@app.get("/api/v60/volume-shockers")
def v60_volume_shockers(request: Request):
    """Read-only NSE volume activity radar over the connected verified universe."""
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    return build_volume_intelligence(svc.snapshot())


@app.get("/api/v31/stock-option")
def v31_stock_option(request: Request, symbol: str = Query(..., min_length=1, max_length=30)):
    """On-demand stock-option resolver. Read-only and intentionally not polled continuously."""
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    symbol = re.sub(r"[^A-Za-z0-9&.-]", "", symbol.upper())
    try:
        eq = svc._search_equity(symbol)
        key = (eq or {}).get("instrument_key")
        if not key:
            raise UpstoxError(f"NSE equity instrument not found for {symbol}")
        contracts = svc.get(f"https://api.upstox.com/v2/option/contract", params={"instrument_key": key}).get("data") or []
        expiries = sorted({str(x.get("expiry")) for x in contracts if x.get("expiry")})
        if not expiries:
            return {"ok":False,"symbol":symbol,"reason":"No listed option expiry returned for this instrument"}
        expiry=expiries[0]
        chain = svc.get("https://api.upstox.com/v2/option/chain", params={"instrument_key":key,"expiry_date":expiry}).get("data") or []
        compact=[]
        for item in chain:
            c=item.get("call_options") or {}; p=item.get("put_options") or {}; cm=c.get("market_data") or {}; pm=p.get("market_data") or {}
            compact.append({"strike":item.get("strike_price"),"spot":item.get("underlying_spot_price"),
              "ce":{"ltp":cm.get("ltp"),"oi":cm.get("oi"),"volume":cm.get("volume"),"bid":cm.get("bid_price"),"ask":cm.get("ask_price"),"key":c.get("instrument_key")},
              "pe":{"ltp":pm.get("ltp"),"oi":pm.get("oi"),"volume":pm.get("volume"),"bid":pm.get("bid_price"),"ask":pm.get("ask_price"),"key":p.get("instrument_key")}})
        return {"ok":True,"symbol":symbol,"instrument_key":key,"expiry":expiry,"expiries":expiries[:8],"chain":compact,"read_only":True}
    except UpstoxError as exc:
        _raise_upstox(exc)


@app.get("/api/v54/stock-option-heatmap")
def v54_stock_option_heatmap(request: Request, symbol: str = Query(..., min_length=1, max_length=30), expiry: Optional[str] = None):
    """On-demand F&O stock option heatmap. No continuous full-market chain polling."""
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    symbol = re.sub(r"[^A-Za-z0-9&.-]", "", symbol.upper())
    try:
        eq = svc._search_equity(symbol)
        key = (eq or {}).get("instrument_key")
        if not key:
            raise UpstoxError(f"NSE equity instrument not found for {symbol}")
        contracts = svc.get("https://api.upstox.com/v2/option/contract", params={"instrument_key": key}).get("data") or []
        expiries = sorted({str(x.get("expiry")) for x in contracts if x.get("expiry")})
        if not expiries:
            return {"ok":False,"symbol":symbol,"reason":"No listed option expiry returned for this instrument"}
        chosen = expiry if expiry in expiries else expiries[0]
        chain = svc.get("https://api.upstox.com/v2/option/chain", params={"instrument_key":key,"expiry_date":chosen}).get("data") or []
        compact=[]
        for item in chain:
            c=item.get("call_options") or {}; p=item.get("put_options") or {}
            cm=c.get("market_data") or {}; pm=p.get("market_data") or {}
            cg=c.get("option_greeks") or {}; pg=p.get("option_greeks") or {}
            compact.append({"strike":item.get("strike_price"),"spot":item.get("underlying_spot_price"),
              "ce":{"ltp":cm.get("ltp"),"oi":cm.get("oi"),"delta_oi":cm.get("oi")-cm.get("prev_oi") if isinstance(cm.get("oi"),(int,float)) and isinstance(cm.get("prev_oi"),(int,float)) else None,"volume":cm.get("volume"),"bid":cm.get("bid_price"),"ask":cm.get("ask_price"),"bid_qty":cm.get("bid_qty"),"ask_qty":cm.get("ask_qty"),"iv":cg.get("iv"),"delta":cg.get("delta"),"gamma":cg.get("gamma"),"theta":cg.get("theta"),"vega":cg.get("vega")},
              "pe":{"ltp":pm.get("ltp"),"oi":pm.get("oi"),"delta_oi":pm.get("oi")-pm.get("prev_oi") if isinstance(pm.get("oi"),(int,float)) and isinstance(pm.get("prev_oi"),(int,float)) else None,"volume":pm.get("volume"),"bid":pm.get("bid_price"),"ask":pm.get("ask_price"),"bid_qty":pm.get("bid_qty"),"ask_qty":pm.get("ask_qty"),"iv":pg.get("iv"),"delta":pg.get("delta"),"gamma":pg.get("gamma"),"theta":pg.get("theta"),"vega":pg.get("vega")}})
        out=stock_option_heatmap(symbol, chosen, compact)
        out.update({"ok":True,"instrument_key":key,"expiries":expiries[:8]})
        return out
    except UpstoxError as exc:
        _raise_upstox(exc)


@app.get("/api/v56/screener")
def v56_screener(request: Request, field: str = Query("setup_score"), op: str = Query("gte", pattern="^(gt|gte|lt|lte|eq)$"), value: float = Query(70)):
    """Read-only custom stock screener over verified live snapshot fields."""
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    snap=svc.snapshot()
    ai=ai_engine.analyse(snap, mode="balanced")
    sm=analyse_smart_money(snap); radar=build_opportunity_radar(snap,ai,sm); v50=build_supreme_intelligence(snap,ai,sm,radar); v53=build_v53(snap,ai,sm,radar,v50); v55=build_v55(snap,v53); v56=build_v56(snap,v55)
    rows=(v56.get("advanced_screener") or {}).get("universe") or []
    allowed=(v56.get("advanced_screener") or {}).get("available_fields") or []
    if field not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported field. Allowed: {', '.join(allowed)}")
    return {"ok":True,"field":field,"operator":op,"value":value,"matches":apply_custom_scan(rows,field,op,value),"read_only":True}


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("UPSTOX_HOST") or os.getenv("HOST") or "0.0.0.0"
    port = int(os.getenv("UPSTOX_PORT") or os.getenv("PORT") or "8787")
    print(f"POWERHOUSE AI V73 LTS running at http://{host}:{port}")
    uvicorn.run("app:app", host=host, port=port, reload=False)


@app.get("/api/v61/status")
def v61_status(request: Request):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False): raise HTTPException(status_code=401, detail=_auth_detail(svc))
    snap=svc.snapshot(); ai=ai_engine.analyse(snap,mode="strict"); sm=analyse_smart_money(snap); radar=build_opportunity_radar(snap,ai,sm); v50=build_supreme_intelligence(snap,ai,sm,radar); v53=build_v53(snap,ai,sm,radar,v50); v55=build_v55(snap,v53); v56=build_v56(snap,v55); v57=build_v57(snap,v56); v58=build_v58(snap,v57); v60=build_v60(snap,v58)
    return build_v61(snap,v60)

@app.get("/api/v61/replay")
def v61_replay(limit:int=Query(80,ge=1,le=250)):
    return build_replay(limit)

@app.get("/api/v61/alerts")
def v61_alerts():
    return alert_center(None,100)

@app.get("/api/v61/catalysts")
def v61_catalysts():
    return catalyst_guard(100)

@app.post("/api/v61/catalysts")
async def v61_add_catalyst(request:Request):
    body=await request.json()
    try: ev=add_catalyst(body.get("symbol",""),body.get("category","EVENT"),body.get("severity","INFO"),body.get("title",""),body.get("source",""),bool(body.get("verified",False)))
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc))
    return {"ok":True,"event":ev,"read_only":True}

@app.get("/api/v61/daily-audit")
def v61_daily_audit():
    return daily_self_audit()


@app.get("/api/v62/status")
def v62_status(request: Request):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False): raise HTTPException(status_code=401, detail=_auth_detail(svc))
    snap=svc.snapshot(); ai=ai_engine.analyse(snap,mode="strict"); sm=analyse_smart_money(snap); radar=build_opportunity_radar(snap,ai,sm); v50=build_supreme_intelligence(snap,ai,sm,radar); v53=build_v53(snap,ai,sm,radar,v50); v55=build_v55(snap,v53); v56=build_v56(snap,v55); v57=build_v57(snap,v56); v58=build_v58(snap,v57); v60=build_v60(snap,v58); v61=build_v61(snap,v60)
    return build_v62(snap,v60,v61)

@app.get("/api/v62/cross-market")
def v62_cross_market(request: Request):
    svc=request_service(request)
    snap=svc.snapshot() if svc.authenticated else {"active_underlying":"NIFTY"}
    return build_v62(snap).get("modules",{}).get("cross_market",{})

@app.post("/api/v62/cross-market/ingest")
async def v62_cross_market_ingest(request: Request):
    body=await request.json()
    market=str(body.get("market") or "").upper().strip()
    if market != "GIFT NIFTY": raise HTTPException(status_code=400,detail="Only verified GIFT NIFTY ingest remains enabled in V71.3")
    try: row=record_cross_market(market,body.get("price"),body.get("change_pct"),str(body.get("source") or "manual_verified_ingest"),bool(body.get("verified",False)),body.get("epoch"),body)
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc))
    return {"ok":True,"row":row,"read_only":True}
