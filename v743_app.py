from __future__ import annotations

"""POWERHOUSE AI V74.3 — Pro Ultra Accuracy FastAPI wrapper.

This module upgrades V74.2 additively. Existing V74/V73/V72 APIs remain available.
The V74.2 server scanner stays browser-independent; its CALL ENGINE is wrapped by an
Ultra Accuracy meta-label gate before a new model call can become READY.
"""

import copy
import os
import threading
import time
from pathlib import Path
from typing import Optional

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
    if V743_UI.exists():
        return FileResponse(V743_UI)
    if base.V74_UI.exists():
        return FileResponse(base.V74_UI)
    raise HTTPException(status_code=503, detail="V74.3 UI asset missing")


@app.get("/api/health")
def v743_health(request: Request):
    svc = base.request_service(request)
    try:
        svc_status = svc.status() or {}
    except Exception:
        svc_status = {}
    precision.observe_scanner(base._background_meta())
    return {
        "ok": True,
        "app": "POWERHOUSE AI V74.3",
        "version": VERSION,
        "release": RELEASE,
        "read_only": True,
        "orders_enabled": False,
        "execution_enabled": False,
        "upstox_authenticated": bool(getattr(svc, "authenticated", False)),
        "upstox_data_status": svc_status.get("data_status"),
        "continuous_scanner": base._background_meta(),
        "ultra_accuracy": precision.pro_status(),
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
    "ULTRA DERIVATIVES", "OPTION CHAIN", "OI WALLS", "DEPTH/DOM", "EXPIRY HERO",
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
    ui_present = {name: (name in ui) for name in FEATURE_MANIFEST[:22]}
    backend_checks = {
        "continuous_scanner": callable(getattr(base, "_background_meta", None)),
        "call_engine": callable(getattr(base, "call_engine_plan", None)),
        "chart": callable(getattr(base, "predictive_chart_intelligence", None)),
        "strike_selector": callable(getattr(base, "predictive_strike_selector", None)),
        "alerts": callable(getattr(eng, "alert_snapshot", None)),
        "memory": memory.MEMORY is not None,
        "precision": precision.STORE is not None,
    }
    return {
        "version": VERSION,
        "release": RELEASE,
        "required_features": FEATURE_MANIFEST,
        "ui_modules": ui_present,
        "ui_loaded": sum(1 for x in ui_present.values() if x),
        "ui_required": len(ui_present),
        "backend_checks": backend_checks,
        "backend_ready": all(backend_checks.values()),
        "regression_guard": "PASS" if all(ui_present.values()) and all(backend_checks.values()) else "ATTENTION",
        "read_only": True,
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
