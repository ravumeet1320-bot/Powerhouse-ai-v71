from __future__ import annotations

"""V74 additive FastAPI wrapper.

The legacy cumulative application remains mounted intact as a fallback. V74 owns the
root UI and /api/v74/* routes; all older /api/vXX routes keep working through the
mounted legacy app.
"""

import copy
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import app as legacy_app, request_service, service_for, _auth_detail, _raise_upstox
from upstox_service import UpstoxError
from v70_engine import master_decision
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
    WORKSPACE_ARCHITECTURE,
    build_v74,
    empty_v74_status,
    hero5_execution_plan,
    call_engine_plan,
    track_call_plan,
    emit_call_alert,
    active_call_symbols,
    call_journal,
    candidate_from_row,
    alert_engine_v74,
    miss_killer_report,
    performance_intelligence,
    record_ui_latency,
    alert_snapshot,
)

ROOT = Path(__file__).parent
V74_UI = ROOT / "static" / "v74.html"

app = FastAPI(
    title="POWERHOUSE AI V74.2 — Autonomous Call Intelligence OS",
    version=VERSION,
)

# Browser-independent V74 scan loop. It consumes only the already verified in-memory
# Upstox snapshot, so it adds no order actions and no per-scan broker API calls.
_V74_SCAN_INTERVAL_SEC = max(2.0, min(10.0, float(os.getenv("V74_SCAN_INTERVAL_SEC", "8"))))
_V74_BG_LOCK = threading.RLock()
_V74_BUILD_LOCK = threading.RLock()
_V74_BG_RESULT = None
_V74_BG_META = {
    "running": False, "last_scan_epoch": 0.0, "last_scan_ms": None,
    "last_error": None, "scan_count": 0, "interval_sec": _V74_SCAN_INTERVAL_SEC,
    "hot_lane_running": False, "hot_interval_sec": 1.0, "last_hot_epoch": 0.0,
    "hot_scan_count": 0, "hot_symbols": 0,
}
_V74_BG_STOP = threading.Event()
_V74_BG_THREAD = None
_V74_AUTO_DEEP_INTERVAL_SEC = max(10.0, min(60.0, float(os.getenv("V74_AUTO_DEEP_INTERVAL_SEC", "30"))))
_V74_AUTO_DEEP_MAX = max(1, min(8, int(os.getenv("V74_AUTO_DEEP_MAX", "2"))))
_V74_AUTO_DEEP_LAST = 0.0
_V74_AUTO_INDEX_CODES = [x.strip().upper() for x in os.getenv("V74_AUTO_INDEX_CODES", "NIFTY,BANKNIFTY").split(",") if x.strip()][:4]
_V74_AUTO_CALLS = {"status":"WARMING","updated_epoch":0.0,"results":[],"errors":[],"policy":"Promotion-based automatic CALL ENGINE deep scan; no orders."}
_V74_HOT_INTERVAL_SEC = max(0.8, min(3.0, float(os.getenv("V74_HOT_INTERVAL_SEC", "3"))))
_V74_HOT_STOP = threading.Event()
_V74_HOT_THREAD = None



def _store_v74_result(out: dict, scan_ms: float) -> None:
    global _V74_BG_RESULT
    # LIVEFIX4: scanner builds a fresh immutable result object each cycle. Store the
    # object reference instead of deep-copying the entire radar/workspace tree. The
    # next scan replaces the reference atomically under the lock.
    with _V74_BG_LOCK:
        _V74_BG_RESULT = out
        _V74_BG_META["last_scan_epoch"] = time.time()
        _V74_BG_META["last_scan_ms"] = round(scan_ms, 2)
        _V74_BG_META["last_error"] = None
        _V74_BG_META["scan_count"] = int(_V74_BG_META.get("scan_count") or 0) + 1


def _background_meta() -> dict:
    with _V74_BG_LOCK:
        meta = dict(_V74_BG_META)
    age = time.time() - float(meta.get("last_scan_epoch") or 0) if meta.get("last_scan_epoch") else None
    meta["last_scan_age_sec"] = round(age, 2) if age is not None else None
    hot_age = time.time() - float(meta.get("last_hot_epoch") or 0) if meta.get("last_hot_epoch") else None
    meta["last_hot_age_sec"] = round(hot_age, 2) if hot_age is not None else None
    meta["fresh"] = bool(age is not None and age <= max(12.0, _V74_SCAN_INTERVAL_SEC * 2.5))
    return meta


def _automatic_call_scan(svc, out: dict) -> dict:
    """Rate-bounded automatic option-chain/chart deep scan for qualified calls."""
    global _V74_AUTO_DEEP_LAST, _V74_AUTO_CALLS
    now = time.time()
    if now - _V74_AUTO_DEEP_LAST < _V74_AUTO_DEEP_INTERVAL_SEC:
        return dict(_V74_AUTO_CALLS)
    _V74_AUTO_DEEP_LAST = now
    rows = list(((out.get("workspaces") or {}).get("calls") or {}).get("hero_ready") or [])
    if not rows:
        all_rows = list((out.get("radar") or {}).get("candidates") or [])
        rows = [x for x in all_rows if str(x.get("stage") or "") in ("ARMING","TRIGGER NEAR","TRIGGER READY","HERO","ENTRY ACTIVE")]
    rows.sort(key=lambda x: (str(x.get("stage") or "") in ("TRIGGER READY","HERO","ENTRY ACTIVE"), float(x.get("score") or 0)), reverse=True)

    # Keep unresolved model calls under surveillance even if they drop out of the
    # current promotion queue, so T1/T2/T3/SL outcomes remain auditable.
    all_rows = list((out.get("radar") or {}).get("candidates") or [])
    row_map = {str(x.get("symbol") or "").upper(): x for x in all_rows}
    present = {str(x.get("symbol") or "").upper() for x in rows}
    for sym in active_call_symbols(60):
        if sym not in present and sym in row_map:
            rows.append(row_map[sym])
            present.add(sym)

    # Indices are first-class and do not depend on the equity F&O census.
    seen = {str(x.get("symbol") or "").upper() for x in rows}
    for code in _V74_AUTO_INDEX_CODES:
        if code in seen:
            continue
        try:
            idx_row = _index_underlying_row(svc, code)
            if idx_row:
                rows.append(idx_row)
        except Exception:
            pass

    results, errors = [], []
    for row in rows[:_V74_AUTO_DEEP_MAX + len(_V74_AUTO_INDEX_CODES)]:
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        try:
            chain = _option_chain_snapshot(svc, sym, force=False)
            pack = predictive_strike_selector(sym, row, chain)
            chart = None
            try:
                candles = svc.instrument_candles(sym, interval=5, limit=120)
                chart = predictive_chart_intelligence(candles, sym, 5, svc.snapshot(), row)
            except Exception:
                chart = None
            hero = hero5_execution_plan(sym, row, pack, chart)
            call = track_call_plan(call_engine_plan(sym, row, pack, chart, now_epoch=now))
            emit_call_alert(call)
            results.append({
                "symbol":sym,"stage":row.get("stage"),"score":row.get("score"),
                "ltp":row.get("ltp"),"change_pct":row.get("change_pct"),
                "data_status":row.get("data_status"),"source":row.get("source"),
                "call":call,"hero5":hero,"strike_intelligence":pack,"read_only":True
            })
        except Exception as exc:
            errors.append({"symbol":sym,"error":str(exc)[:180]})
    _V74_AUTO_CALLS = {
        "status":"READY" if results else "NO_QUALIFIED_CANDIDATE",
        "updated_epoch":now, "interval_sec":_V74_AUTO_DEEP_INTERVAL_SEC,
        "max_promoted_per_cycle":_V74_AUTO_DEEP_MAX, "automatic_indices":_V74_AUTO_INDEX_CODES,
        "results":results, "errors":errors,
        "journal": call_journal(40),
        "read_only":True, "execution_enabled":False,
        "policy":"Automatic CALL ENGINE deep scan is candidate-first and rate-bounded. It never places orders; WAIT/DO NOT CHASE are valid outputs and call quality is not a profit probability.",
    }
    return dict(_V74_AUTO_CALLS)

def _background_scan_once() -> bool:
    svc = service_for("default")
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        return False
    snap = svc.snapshot()
    t0 = time.perf_counter()
    with _V74_BUILD_LOCK:
        out = build_v74(snap, record=True)
    scan_ms = (time.perf_counter() - t0) * 1000.0
    out["data_status"] = snap.get("data_status") or "LIVE"
    out["authenticated"] = True
    out["continuous_scanner"] = {
        "running": True, "interval_sec": _V74_SCAN_INTERVAL_SEC,
        "last_scan_ms": round(scan_ms, 2),
        "source": "server-side verified Upstox in-memory snapshot",
        "browser_independent": True, "request_driven": False,
    }
    calls = _automatic_call_scan(svc, out)
    out["automated_call_engine"] = calls
    out["automated_execution"] = calls  # backward-compatible alias; no orders are enabled
    _store_v74_result(out, scan_ms)
    return True


def _hot_lane_scan_once() -> bool:
    """One-second promoted-symbol evidence refresh using the verified in-memory snapshot.

    This does not call option-chain REST endpoints and does not replace the three-second
    full-universe scan. It only advances short-window evidence/history for already-hot
    names so fast moves are less likely to disappear between full scans.
    """
    svc = service_for("default")
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        return False
    with _V74_BG_LOCK:
        hot_rows = [dict(x) for x in (((_V74_BG_RESULT or {}).get("hot_lane") or [])[:20])]
    symbols = [str(x.get("symbol") or "").upper() for x in hot_rows if x.get("symbol")]
    if not symbols:
        return False
    # LIVEFIX4: do not materialize the complete service snapshot every hot-lane tick.
    # Pull only the promoted symbols directly from the already-updated provider maps.
    wanted=set(symbols); source_rows=[]
    try:
        with svc.lock:
            vals=list(getattr(svc,"fno_equities",{}).values()) or list(getattr(svc,"sector_equities",{}).values())
            for x in vals:
                sym=str(x.get("symbol") or x.get("tradingsymbol") or "").upper()
                if sym in wanted:
                    source_rows.append(dict(x))
    except Exception:
        source_rows=[]
    bysym = {str(x.get("symbol") or x.get("tradingsymbol") or "").upper(): x for x in source_rows}
    updates=[]
    for sym in symbols:
        row=bysym.get(sym)
        if row:
            try:
                updates.append(candidate_from_row(row, {"expiry_mode": bool(snap.get("expiry_mode") or snap.get("is_expiry_day"))}))
            except Exception:
                pass
    if updates:
        try:
            alert_engine_v74(updates, None)
        except Exception:
            pass
    with _V74_BG_LOCK:
        _V74_BG_META["last_hot_epoch"] = time.time()
        _V74_BG_META["hot_scan_count"] = int(_V74_BG_META.get("hot_scan_count") or 0) + 1
        _V74_BG_META["hot_symbols"] = len(updates)
    return bool(updates)


def _hot_lane_loop() -> None:
    with _V74_BG_LOCK:
        _V74_BG_META["hot_lane_running"] = True
        _V74_BG_META["hot_interval_sec"] = _V74_HOT_INTERVAL_SEC
    while not _V74_HOT_STOP.is_set():
        try:
            _hot_lane_scan_once()
        except Exception:
            pass
        _V74_HOT_STOP.wait(_V74_HOT_INTERVAL_SEC)
    with _V74_BG_LOCK:
        _V74_BG_META["hot_lane_running"] = False


def _background_scan_loop() -> None:
    with _V74_BG_LOCK:
        _V74_BG_META["running"] = True
    while not _V74_BG_STOP.is_set():
        try:
            _background_scan_once()
        except Exception as exc:
            with _V74_BG_LOCK:
                _V74_BG_META["last_error"] = str(exc)[:240]
        _V74_BG_STOP.wait(_V74_SCAN_INTERVAL_SEC)
    with _V74_BG_LOCK:
        _V74_BG_META["running"] = False


@app.on_event("startup")
def _start_v74_continuous_scanner():
    global _V74_BG_THREAD, _V74_HOT_THREAD
    if not (_V74_BG_THREAD and _V74_BG_THREAD.is_alive()):
        _V74_BG_STOP.clear()
        _V74_BG_THREAD = threading.Thread(target=_background_scan_loop, name="v74-continuous-scanner", daemon=True)
        _V74_BG_THREAD.start()
    if not (_V74_HOT_THREAD and _V74_HOT_THREAD.is_alive()):
        _V74_HOT_STOP.clear()
        _V74_HOT_THREAD = threading.Thread(target=_hot_lane_loop, name="v74-hot-lane", daemon=True)
        _V74_HOT_THREAD.start()


@app.on_event("shutdown")
def _stop_v74_continuous_scanner():
    _V74_BG_STOP.set()
    _V74_HOT_STOP.set()


def _live_v74_result(request: Request):
    """Read the server-side scanner cache only; never run V74 because a page requested it.

    LIVEFIX4 avoids deep-copying the complete cached universe for every HTTP request.
    Scanner cycles replace the cached root object rather than mutating it, so a shallow
    response envelope is enough and dramatically reduces CPU/RAM pressure.
    """
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        return svc, None
    with _V74_BG_LOCK:
        root = _V74_BG_RESULT
    meta = _background_meta()
    if root is None:
        return svc, None
    cached = dict(root)
    cached["continuous_scanner"] = meta
    cached["automated_call_engine"] = dict(_V74_AUTO_CALLS)
    cached["automated_execution"] = dict(_V74_AUTO_CALLS)
    if not meta.get("fresh"):
        cached["data_status"] = "STALE"
        cached["scanner_warning"] = "Automated scanner cache is stale; no request-triggered scan was substituted."
    return svc, cached


def _cached_candidate(symbol: str):
    sym = str(symbol or "").upper()
    with _V74_BG_LOCK:
        rows = (((_V74_BG_RESULT or {}).get("radar") or {}).get("candidates") or [])
        row = next((r for r in rows if str(r.get("symbol") or "").upper() == sym), None)
    return copy.deepcopy(row) if row is not None else None


def _live_snapshot(request: Request):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        return svc, None
    return svc, svc.snapshot()


def _clean_symbol(symbol: str) -> str:
    raw = re.sub(r"[^A-Za-z0-9&.-]", "", str(symbol or "").upper())
    compact = re.sub(r"[^A-Z0-9]", "", raw)
    aliases = {
        "NIFTY": "NIFTY", "NIFTY50": "NIFTY",
        "BANKNIFTY": "BANKNIFTY", "NIFTYBANK": "BANKNIFTY",
        "MIDCPNIFTY": "MIDCPNIFTY", "NIFTYMIDSELECT": "MIDCPNIFTY",
        "SENSEX": "SENSEX", "BSESENSEX": "SENSEX",
    }
    return aliases.get(compact, raw)


_INDEX_ALIASES = {
    "NIFTY": "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
    "MIDCPNIFTY": "MIDCPNIFTY",
    "SENSEX": "SENSEX",
}


def _index_underlying_row(svc, symbol: str):
    """Build an evidence-only Hero row for supported index underlyings.

    The full F&O census is equity/futures oriented, so indices are not required to
    appear in that stock census. Index Hero requests use the verified Upstox index
    snapshot + V70 master-decision evidence instead of failing as "not in census".
    Short-window fields stay unavailable unless truly supplied; nothing is fabricated.
    """
    code = _INDEX_ALIASES.get(symbol)
    if not code:
        return None
    idx = svc.snapshot_for_underlying(code)
    if not idx.get("ok"):
        return None
    master = master_decision(idx)
    score = float(master.get("score") or 0.0)
    side = str(master.get("side") or "WAIT").upper()
    stage = "TRIGGER READY" if side in ("CE", "PE") and score >= 70 else "ARMING" if side in ("CE", "PE") and score >= 55 else "WATCH"
    series = (idx.get("price_series") or {}).get("5") or []
    change_pct = None
    try:
        if len(series) >= 2 and float(series[0]):
            change_pct = (float(series[-1]) - float(series[0])) / abs(float(series[0])) * 100.0
    except Exception:
        change_pct = None
    return {
        "symbol": code,
        "ltp": idx.get("spot"),
        "change_pct": change_pct,
        "side": side,
        "v72_side": side,
        "evidence_score": score,
        "pre_move_score": score,
        "score": score,
        "stage": stage,
        "pre_move_stage": stage,
        "live": False,
        "data_status": "REST",
        "source": idx.get("source") or "upstox_rest_all_index_scan",
        "quote_age_sec": None,
        "directional_evidence": {
            "aligned_groups": len(master.get("evidence") or []),
            "opposed_groups": len(master.get("counter_evidence") or []),
        },
        "what_changed": list(master.get("evidence") or []),
        "mtf_conflict": bool(master.get("conflict")),
        "index_underlying": True,
        "index_snapshot": idx,
        "master_decision": master,
        # Deliberately unavailable unless provided by the actual short-window feed.
        "velocity_15s": None, "velocity_30s": None, "velocity_60s": None,
        "acceleration": None, "rvol": None,
    }


def _option_chain_snapshot(svc, symbol: str, force: bool = False):
    """Return one normalized chain shape for index and stock underlyings.

    Index names must never fall through generic equity discovery because symbols such
    as NIFTY can collide with NSE_EQ instruments/ETFs. Index chains therefore use the
    service's official index resolver and read-only index snapshot path.
    """
    code = _INDEX_ALIASES.get(symbol)
    if not code:
        return svc.stock_option_chain_snapshot(symbol, force=force)

    snap = svc.snapshot_for_underlying(code)
    if not snap.get("ok"):
        return {
            "ok": False,
            "symbol": symbol,
            "instrument_key": svc.resolve_underlying_key(code),
            "expiry": snap.get("expiry"),
            "chain": [],
            "reason": snap.get("reason") or "No listed option expiry returned",
        }

    rows = []
    for r in snap.get("option_data") or []:
        coi = r.get("coi")
        poi = r.get("poi")
        cchg = r.get("cchg")
        pchg = r.get("pchg")
        rows.append({
            "strike": r.get("s"),
            "spot": snap.get("spot"),
            "ce": {
                "ltp": r.get("cltp"), "oi": coi,
                "prev_oi": (coi - cchg) if coi is not None and cchg is not None else coi,
                "volume": r.get("cvol"), "bid": r.get("cbid"), "ask": r.get("cask"),
                "iv": r.get("civ"), "delta": r.get("c_delta"), "gamma": r.get("c_gamma"),
                "theta": r.get("c_theta"), "vega": r.get("c_vega"), "key": r.get("call_key"),
            },
            "pe": {
                "ltp": r.get("pltp"), "oi": poi,
                "prev_oi": (poi - pchg) if poi is not None and pchg is not None else poi,
                "volume": r.get("pvol"), "bid": r.get("pbid"), "ask": r.get("pask"),
                "iv": r.get("piv"), "delta": r.get("p_delta"), "gamma": r.get("p_gamma"),
                "theta": r.get("p_theta"), "vega": r.get("p_vega"), "key": r.get("put_key"),
            },
        })
    return {
        "ok": True,
        "symbol": symbol,
        "instrument_key": svc.resolve_underlying_key(code),
        "expiry": snap.get("expiry"),
        "expiries": [snap.get("expiry")] if snap.get("expiry") else [],
        "spot": snap.get("spot"),
        "chain": rows,
        "chain_rows": len(rows),
        "source": snap.get("source") or "Upstox option chain",
        "read_only": True,
    }


@app.get("/")
def v74_home():
    if V74_UI.exists():
        return FileResponse(V74_UI)
    raise HTTPException(status_code=503, detail="V74 UI asset missing")


@app.get("/api/v74/status")
def v74_status(request: Request):
    svc, out = _live_v74_result(request)
    if out is None:
        e = empty_v74_status(_auth_detail(svc))
        e["continuous_scanner"] = _background_meta()
        return e
    return out


def _ui_candidate_row(row: dict) -> dict:
    """Small projection for the mobile dashboard; no raw scout/replay trees."""
    if not isinstance(row, dict):
        return {}
    hist = row.get("history_metrics") or {}
    scouts = ((row.get("scout_pack") or {}).get("scouts") or {})
    vol = scouts.get("volume") or {}
    oi = scouts.get("oi") or {}
    return {
        "symbol": row.get("symbol"), "sector": row.get("sector"),
        "ltp": row.get("ltp"), "change_pct": row.get("change_pct"),
        "stage": row.get("stage"), "pre_move_stage": row.get("pre_move_stage"),
        "score": row.get("score"), "pre_move_score": row.get("pre_move_score"),
        "side": row.get("side"), "direction": row.get("direction"), "bias": row.get("bias"),
        "acceleration": row.get("acceleration"), "rvol": row.get("rvol"),
        "data_status": row.get("data_status"), "source": row.get("source"),
        "history_metrics": {
            "price_60s_pct": hist.get("price_60s_pct"),
            "price_acceleration": hist.get("price_acceleration"),
        },
        "scout_pack": {"scouts": {
            "volume": {"rvol": vol.get("rvol")},
            "oi": {"delta_oi_pct": oi.get("delta_oi_pct")},
        }},
    }


@app.get("/api/v74/ui-status")
def v74_ui_status(request: Request):
    """LIVEFIX5 cache-only UI state; excludes heavy nested scanner payloads."""
    svc, out = _live_v74_result(request)
    if out is None:
        e = empty_v74_status(_auth_detail(svc))
        return {
            "version": VERSION, "release": RELEASE,
            "data_status": e.get("data_status") or "UNAVAILABLE",
            "reason": e.get("reason"),
            "continuous_scanner": _background_meta(),
            "radar": {"candidates": []},
            "workspaces": {"market": {"breadth": {}, "sectors": []}, "flow-technical": {"flow": []}},
            "sector_heatmap": [], "circuits": {"candidates": []},
            "read_only": True,
        }
    radar = out.get("radar") or {}
    workspaces = out.get("workspaces") or {}
    market = workspaces.get("market") or {}
    flow_ws = workspaces.get("flow-technical") or {}
    circuits = out.get("circuits") or {}
    return {
        "version": out.get("version") or VERSION,
        "release": out.get("release") or RELEASE,
        "data_status": out.get("data_status"),
        "continuous_scanner": out.get("continuous_scanner") or _background_meta(),
        "radar": {"candidates": [_ui_candidate_row(x) for x in list(radar.get("candidates") or [])[:180]]},
        "workspaces": {
            "market": {
                "breadth": dict(market.get("breadth") or {}),
                "sectors": [dict(x) for x in list(market.get("sectors") or [])[:60] if isinstance(x, dict)],
            },
            "flow-technical": {
                "flow": [dict(x) for x in list(flow_ws.get("flow") or [])[:80] if isinstance(x, dict)],
            },
        },
        "sector_heatmap": [dict(x) for x in list(out.get("sector_heatmap") or [])[:60] if isinstance(x, dict)],
        "circuits": {"candidates": [dict(x) for x in list(circuits.get("candidates") or [])[:80] if isinstance(x, dict)]},
        "read_only": True,
    }


@app.get("/api/v74/tabs")
def v74_tabs():
    return {
        "version": VERSION,
        "release": RELEASE,
        "tabs": TAB_ARCHITECTURE,
        "ui_workspaces": WORKSPACE_ARCHITECTURE,
        "legacy_feature_count": len(TAB_ARCHITECTURE),
        "merged_ui": True,
        "no_more_menu": True,
        "read_only": True,
    }


@app.get("/api/health")
def v74_health(request: Request):
    """Production health endpoint owned by the V74 wrapper.

    The legacy app remains mounted for cumulative compatibility, but Render and
    operators should see the active V74 runtime rather than the V73 legacy label.
    """
    svc = request_service(request)
    try:
        svc_status = svc.status() or {}
    except Exception:
        svc_status = {}
    return {
        "ok": True,
        "app": "POWERHOUSE AI V74.2",
        "version": VERSION,
        "release": RELEASE,
        "legacy_v73_compatibility": True,
        "v72_2_compatibility": True,
        "read_only": True,
        "orders_enabled": False,
        "execution_enabled": False,
        "upstox_authenticated": bool(getattr(svc, "authenticated", False)),
        "upstox_data_status": svc_status.get("data_status"),
        "upstox_server_token_configured": bool(getattr(svc, "server_token_configured", False)),
        "continuous_scanner": _background_meta(),
        "request_driven_scanning": False,
        "ui_workspace_count": len(WORKSPACE_ARCHITECTURE),
        "legacy_feature_count": len(TAB_ARCHITECTURE),
        "automated_call_engine": copy.deepcopy(_V74_AUTO_CALLS),
        "automated_execution": copy.deepcopy(_V74_AUTO_CALLS),
    }


@app.get("/api/v74/workspaces")
def v74_workspaces(request: Request):
    svc, out = _live_v74_result(request)
    if out is None:
        raise HTTPException(status_code=503 if getattr(svc, "authenticated", False) else 401, detail="Automated scanner warming" if getattr(svc, "authenticated", False) else _auth_detail(svc))
    return {"version": VERSION, "ui_workspaces": WORKSPACE_ARCHITECTURE, "workspaces": out.get("workspaces") or {}, "automated_call_engine": out.get("automated_call_engine"), "automated_execution": out.get("automated_execution"), "continuous_scanner": out.get("continuous_scanner"), "read_only": True}


@app.get("/api/v74/coverage")
def v74_coverage(request: Request):
    svc, out = _live_v74_result(request)
    if out is None:
        e = empty_v74_status(_auth_detail(svc))
        return {"version": VERSION, "coverage": e["coverage"], "data_status": "UNAVAILABLE", "reason": e["reason"], "continuous_scanner": _background_meta()}
    return {"version": VERSION, "coverage": out.get("coverage"), "data_quality": (out.get("base_v73") or {}).get("data_quality"), "continuous_scanner": out.get("continuous_scanner"), "read_only": True}


@app.get("/api/v74/radar")
def v74_radar(
    request: Request,
    stage: Optional[str] = Query(None),
    move_class: Optional[str] = Query(None),
    limit: int = Query(250, ge=1, le=1000),
):
    svc, out = _live_v74_result(request)
    if out is None:
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    rows = list((out.get("radar") or {}).get("candidates") or [])
    if stage:
        want = stage.upper().strip()
        rows = [r for r in rows if str(r.get("stage") or "").upper() == want]
    if move_class:
        want = move_class.upper().strip()
        rows = [r for r in rows if str(r.get("move_class") or "").upper() == want]
    return {"version": VERSION, "matched": len(rows), "rows": rows[:limit], "continuous_scanner": out.get("continuous_scanner"), "read_only": True}


@app.get("/api/v74/big-move")
def v74_big_move(request: Request, limit: int = Query(100, ge=1, le=500)):
    svc, out = _live_v74_result(request)
    if out is None:
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    engine = out.get("big_move_capture_engine") or {}
    return {**engine, "candidates": (engine.get("candidates") or [])[:limit], "version": VERSION, "continuous_scanner": out.get("continuous_scanner"), "read_only": True}


@app.get("/api/v74/alerts")
def v74_alerts(
    request: Request,
    since_epoch: float = Query(0.0, ge=0.0),
    limit: int = Query(200, ge=1, le=500),
):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    out = alert_snapshot(since_epoch=since_epoch, limit=limit)
    out["continuous_scanner"] = _background_meta()
    return out


@app.get("/api/v74/calls")
def v74_calls(request: Request):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    return {"version":VERSION,"automated_call_engine":copy.deepcopy(_V74_AUTO_CALLS),"journal":call_journal(200),"continuous_scanner":_background_meta(),"read_only":True,"execution_enabled":False}


@app.get("/api/v74/call/{symbol}")
def v74_call(symbol: str, request: Request, force: bool = Query(False)):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    sym = _clean_symbol(symbol)
    row = _cached_candidate(sym)
    if not row and sym in _INDEX_ALIASES:
        row = _index_underlying_row(svc, sym)
    if not row:
        raise HTTPException(status_code=404, detail=f"{sym} is not in the current automated scanner census")
    try:
        chain = _option_chain_snapshot(svc, sym, force=force)
        pack = predictive_strike_selector(sym, row, chain)
        chart = None
        try:
            candles = svc.instrument_candles(sym, interval=5, limit=120)
            chart = predictive_chart_intelligence(candles, sym, 5, svc.snapshot(), row)
        except Exception:
            chart = None
        hero = hero5_execution_plan(sym, row, pack, chart)
        call = track_call_plan(call_engine_plan(sym, row, pack, chart))
        emit_call_alert(call)
        return {"version":VERSION,"symbol":sym,"call":call,"hero5":hero,"strike_intelligence":pack,"chart_context":chart,"read_only":True,"execution_enabled":False}
    except UpstoxError as exc:
        _raise_upstox(exc)


@app.get("/api/v74/journal")
def v74_journal(request: Request, limit: int = Query(200, ge=1, le=1000)):
    svc = request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=_auth_detail(svc))
    return call_journal(limit)


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
    row = _cached_candidate(sym)
    if not row and sym in _INDEX_ALIASES:
        row = _index_underlying_row(svc, sym)
    snap = svc.snapshot()
    if not row:
        raise HTTPException(status_code=404, detail=f"{sym} is not in the current discovered F&O census")
    try:
        chain = _option_chain_snapshot(svc, sym, force=force)
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
            "call": track_call_plan(call_engine_plan(sym, row, pack, chart)),
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
        row = _cached_candidate(sym)
        if not row and sym in _INDEX_ALIASES:
            row = _index_underlying_row(svc, sym)
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
        chain = _option_chain_snapshot(svc, sym, force=force)
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
