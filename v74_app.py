from __future__ import annotations

"""V74 additive FastAPI wrapper.

The legacy cumulative application remains mounted intact as a fallback. V74 owns the
root UI and /api/v74/* routes; all older /api/vXX routes keep working through the
mounted legacy app.
"""

import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import app as legacy_app, request_service, _auth_detail, _raise_upstox
from upstox_service import UpstoxError
from v72_2_engine import (
    pre_move_radar,
    predictive_chart_intelligence,
    predictive_strike_selector,
    replay_timeline,
    signal_forensics,
)
from v74_engine import (
    VERSION,
    RELEASE,
    TAB_ARCHITECTURE,
    build_v74,
    empty_v74_status,
    hero5_execution_plan,
    miss_killer_report,
    performance_intelligence,
    record_ui_latency,
)

ROOT = Path(__file__).parent
V74_UI = ROOT / "static" / "v74.html"

app = FastAPI(
    title="POWERHOUSE AI V74 — Maximum Move Capture & Accountability OS",
    version=VERSION,
)


def _live_snapshot(request: Request):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        return svc, None
    return svc, svc.snapshot()


def _clean_symbol(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9&.-]", "", symbol.upper())


@app.get("/")
def v74_home():
    if V74_UI.exists():
        return FileResponse(V74_UI)
    raise HTTPException(status_code=503, detail="V74 UI asset missing")


@app.get("/api/v74/status")
def v74_status(request: Request):
    svc, snap = _live_snapshot(request)
    if snap is None:
        return empty_v74_status(_auth_detail(svc))
    out = build_v74(snap, record=True)
    out["data_status"] = "LIVE"
    out["authenticated"] = True
    return out


@app.get("/api/v74/tabs")
def v74_tabs():
    return {
        "version": VERSION,
        "release": RELEASE,
        "tabs": TAB_ARCHITECTURE,
        "no_more_menu": True,
        "read_only": True,
    }


@app.get("/api/v74/coverage")
def v74_coverage(request: Request):
    svc, snap = _live_snapshot(request)
    if snap is None:
        e = empty_v74_status(_auth_detail(svc))
        return {"version": VERSION, "coverage": e["coverage"], "data_status": "UNAVAILABLE", "reason": e["reason"]}
    out = build_v74(snap, record=True)
    return {"version": VERSION, "coverage": out.get("coverage"), "data_quality": (out.get("base_v73") or {}).get("data_quality"), "read_only": True}


@app.get("/api/v74/radar")
def v74_radar(
    request: Request,
    stage: Optional[str] = Query(None),
    move_class: Optional[str] = Query(None),
    limit: int = Query(250, ge=1, le=1000),
):
    svc, snap = _live_snapshot(request)
    if snap is None:
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    out = build_v74(snap, record=True)
    rows = list((out.get("radar") or {}).get("candidates") or [])
    if stage:
        want = stage.upper().strip()
        rows = [r for r in rows if str(r.get("stage") or "").upper() == want]
    if move_class:
        want = move_class.upper().strip()
        rows = [r for r in rows if str(r.get("move_class") or "").upper() == want]
    return {"version": VERSION, "matched": len(rows), "rows": rows[:limit], "read_only": True}


@app.get("/api/v74/big-move")
def v74_big_move(request: Request, limit: int = Query(100, ge=1, le=500)):
    svc, snap = _live_snapshot(request)
    if snap is None:
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    out = build_v74(snap, record=True)
    engine = out.get("big_move_capture_engine") or {}
    return {**engine, "candidates": (engine.get("candidates") or [])[:limit], "version": VERSION, "read_only": True}


@app.get("/api/v74/missed-moves")
def v74_missed_moves(request: Request, limit: int = Query(200, ge=1, le=1000)):
    _ = request_service(request)
    return miss_killer_report(limit)


@app.get("/api/v74/performance")
def v74_performance(request: Request):
    _ = request_service(request)
    return performance_intelligence()


@app.get("/api/v74/forensics")
def v74_forensics(request: Request, minutes: int = Query(390, ge=30, le=10080)):
    _ = request_service(request)
    return {"version": VERSION, "legacy_forensics": signal_forensics(minutes), "v74_miss_killer": miss_killer_report(), "read_only": True}


@app.get("/api/v74/replay/{symbol}")
def v74_replay(symbol: str, request: Request, minutes: int = Query(390, ge=30, le=10080)):
    _ = request_service(request)
    sym = _clean_symbol(symbol)
    return {"version": VERSION, "symbol": sym, "timeline": replay_timeline(sym, minutes), "read_only": True}


@app.get("/api/v74/hero/{symbol}")
def v74_hero(
    symbol: str,
    request: Request,
    force: bool = Query(False),
    interval: int = Query(5, ge=1, le=30),
    limit: int = Query(120, ge=20, le=240),
):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    sym = _clean_symbol(symbol)
    snap = svc.snapshot()
    radar = pre_move_radar(snap, record=True)
    row = next((r for r in (radar.get("rows") or []) if str(r.get("symbol") or "").upper() == sym), None)
    if not row:
        raise HTTPException(status_code=404, detail=f"{sym} is not in the current discovered F&O census")
    try:
        chain = svc.stock_option_chain_snapshot(sym, force=force)
        pack = predictive_strike_selector(sym, row, chain)
        chart = None
        try:
            candles = svc.instrument_candles(sym, interval=interval, limit=limit)
            chart = predictive_chart_intelligence(candles, sym, interval, snap, row)
        except Exception:
            chart = None
        return {
            "version": VERSION,
            "symbol": sym,
            "underlying": row,
            "strike_intelligence": pack,
            "chart_context": chart,
            "hero5": hero5_execution_plan(sym, row, pack, chart),
            "read_only": True,
            "execution_enabled": False,
        }
    except UpstoxError as exc:
        _raise_upstox(exc)


@app.get("/api/v74/chart/{symbol}")
def v74_chart(symbol: str, request: Request, interval: int = Query(5, ge=1, le=30), limit: int = Query(180, ge=20, le=240)):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    sym = _clean_symbol(symbol)
    try:
        candles = svc.instrument_candles(sym, interval=interval, limit=limit)
        snap = svc.snapshot()
        radar = pre_move_radar(snap, record=True)
        row = next((r for r in (radar.get("rows") or []) if str(r.get("symbol") or "").upper() == sym), None)
        return {
            "version": VERSION,
            "symbol": sym,
            "chart": predictive_chart_intelligence(candles, sym, interval, snap, row),
            "candles": candles,
            "read_only": True,
        }
    except UpstoxError as exc:
        _raise_upstox(exc)


@app.get("/api/v74/option-chain/{symbol}")
def v74_option_chain(symbol: str, request: Request, force: bool = Query(False)):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    sym = _clean_symbol(symbol)
    try:
        chain = svc.stock_option_chain_snapshot(sym, force=force)
        return {"version": VERSION, "symbol": sym, "option_chain": chain, "read_only": True}
    except UpstoxError as exc:
        _raise_upstox(exc)


class UILatency(BaseModel):
    fetch_ms: Optional[float] = None
    render_ms: Optional[float] = None
    tab: Optional[str] = None


@app.post("/api/v74/telemetry/ui")
def v74_ui_telemetry(payload: UILatency):
    return {"version": VERSION, **record_ui_latency(payload.fetch_ms, payload.render_ms, payload.tab)}


# Keep every legacy endpoint and static asset available. The mount is intentionally last
# so V74 routes above take precedence while /api/v73, /api/v72, /api/health, OAuth,
# PWA assets and all cumulative compatibility routes continue to function.
app.mount("/", legacy_app)
