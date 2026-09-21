from __future__ import annotations

import copy
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse

import v744_app as legacy
import v745_engine as core
import v743_memory as market_memory

VERSION = core.VERSION
RELEASE = core.RELEASE
ROOT = Path(__file__).parent
UI = ROOT / "static" / "v745.html"
LEGACY_UI = ROOT / "static" / "v744.html"
app = legacy.app
app.title = "POWERHOUSE AI V74.5 — Adaptive Intelligence Master"
app.version = VERSION

_LOCK = threading.RLock()
_VIX_HISTORY = deque(maxlen=600)
_SMART_ALERTS = deque(maxlen=600)
_ALERT_SIG: Dict[str, float] = {}
_LAST_SNAPSHOT: Optional[Dict[str, Any]] = None
_SETUP_STATE: Dict[str, str] = {}
_SETUP_CONFIRM: Dict[str, int] = {}
_LAST_MEMORY_STATE: Dict[str, Any] = {}

SEVERITY_RANK = {"INFO": 0, "WATCH": 1, "SETUP": 2, "TRADE READY": 3, "CRITICAL": 4}

V745_FEATURES = {
    "smart_alert_manager": "IMPLEMENTED",
    "data_quality_gate": "IMPLEMENTED",
    "india_vix_intelligence": "IMPLEMENTED",
    "market_regime_brain": "IMPLEMENTED",
    "adaptive_weighting": "IMPLEMENTED",
    "setup_lifecycle": "IMPLEMENTED",
    "temporal_confirmation": "IMPLEMENTED",
    "contradiction_resolver": "IMPLEMENTED",
    "signal_quality": "IMPLEMENTED",
    "execution_quality": "IMPLEMENTED",
    "uncertainty_and_abstention": "IMPLEMENTED",
    "late_entry_overextension_guard": "IMPLEMENTED",
    "cross_market_context": "IMPLEMENTED",
    "correlation_guard": "IMPLEMENTED",
    "market_memory": "IMPLEMENTED",
    "what_changed": "IMPLEMENTED",
    "calibration_reporting": "IMPLEMENTED",
    "walk_forward_validation_policy": "ENFORCED_POLICY",
    "champion_challenger_shadow_policy": "ENFORCED_POLICY",
    "replay_shadow_forensics": "PRESERVED_FROM_V66_V74",
    "expiry_hero_and_options_intelligence": "PRESERVED_FROM_V74_3_V74_4",
    "sector_rotation_breadth_smart_money": "PRESERVED_FROM_V74_3",
    "one_thesis_engine": "PRESERVED_AND_GATED",
    "broker_order_placement": "DISABLED_BY_DESIGN",
}


def _iso(epoch: Optional[float] = None) -> str:
    return datetime.fromtimestamp(float(epoch or time.time()), timezone.utc).isoformat()


def _remove_get(path: str) -> None:
    app.router.routes[:] = [
        r for r in app.router.routes
        if not (getattr(r, "path", None) == path and "GET" in (getattr(r, "methods", None) or set()))
    ]


_remove_get("/")


@app.get("/")
def home():
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
        "X-Powerhouse-Build": "V74.5-ADAPTIVE-INTELLIGENCE-MASTER-FINAL",
    }
    if UI.exists():
        return FileResponse(UI, headers=headers)
    return legacy.home()


@app.get("/v744")
def v744_preserved_ui():
    if LEGACY_UI.exists():
        return FileResponse(LEGACY_UI, headers={"Cache-Control": "no-store", "X-Powerhouse-Build": "V74.4-PRESERVED"})
    raise HTTPException(status_code=404, detail="V74.4 UI unavailable")


def _smart_emit(severity: str, kind: str, symbol: str, title: str, body: str, payload: Optional[Dict[str, Any]] = None, cooldown: int = 60):
    severity = str(severity or "INFO").upper()
    if severity not in SEVERITY_RANK:
        severity = "INFO"
    # Production safety: test/debug noise is never emitted into the normal stream.
    if "TEST" in str(kind).upper() or "TEST" in str(title).upper():
        return None
    now = time.time()
    sig = f"{severity}|{kind}|{symbol}|{body}"
    with _LOCK:
        if now - _ALERT_SIG.get(sig, 0.0) < max(20, int(cooldown)):
            return None
        _ALERT_SIG[sig] = now
        item = {
            "id": f"V745-{int(now * 1000)}-{len(_SMART_ALERTS)}",
            "epoch": now,
            "iso": _iso(now),
            "severity": severity,
            "priority": "P0" if severity == "CRITICAL" else "P1" if severity == "TRADE READY" else "P2" if severity in {"SETUP", "WATCH"} else "P3",
            "kind": kind,
            "symbol": symbol or "SYSTEM",
            "title": title,
            "body": body,
            "payload": payload or {},
            "read_only": True,
        }
        _SMART_ALERTS.append(item)
    # V74.5 intentionally does not send server push by default. Browser notification
    # policy is user controlled in the UI. This prevents disruptive alert storms.
    return item


def _record_vix(markets):
    row = next((x for x in markets or [] if str(x.get("market") or "").upper() == "INDIA VIX"), None)
    if not row:
        return
    p = core.f(row.get("price"))
    if p is None:
        return
    now = time.time()
    with _LOCK:
        if not _VIX_HISTORY or now - float(_VIX_HISTORY[-1].get("epoch") or 0) >= 12:
            _VIX_HISTORY.append({"epoch": now, "price": p, "change_pct": core.f(row.get("change_pct"))})


def _material_memory(snapshot: Dict[str, Any]) -> None:
    global _LAST_MEMORY_STATE
    state = {
        "regime": ((snapshot.get("market_regime") or {}).get("regime")),
        "risk": ((snapshot.get("risk_state") or {}).get("state")),
        "data_gate": ((snapshot.get("data_quality") or {}).get("gate")),
        "vix_regime": ((snapshot.get("vix") or {}).get("regime")),
        "best": ((snapshot.get("best_setup") or {}).get("symbol")),
    }
    if state == _LAST_MEMORY_STATE:
        return
    _LAST_MEMORY_STATE = copy.deepcopy(state)
    try:
        market_memory.MEMORY.record(
            "REGIME",
            {"v745": state, "risk_score": (snapshot.get("risk_state") or {}).get("score")},
            scope_key="V74.5_ADAPTIVE_STATE",
            event_key="STATE_CHANGE",
            source="V74.5_ADAPTIVE_ENGINE",
        )
    except Exception:
        pass


def _apply_temporal_confirmation(adaptive_setups):
    """Require repeated independent snapshots before exposing TRADE READY.

    This is an accuracy-first debounce. A setup that briefly spikes through the
    threshold remains CONFIRMING until it survives two snapshots.
    """
    out = []
    for row in adaptive_setups or []:
        x = copy.deepcopy(row)
        sym = str(x.get("symbol") or "").upper()
        a = x.get("adaptive") or {}
        raw_ready = bool(a.get("qualified")) and str(a.get("lifecycle") or "") == "READY"
        streak = (_SETUP_CONFIRM.get(sym, 0) + 1) if raw_ready else 0
        _SETUP_CONFIRM[sym] = min(5, streak)
        a["temporal_confirmation"] = {"required": 2, "observed": streak, "passed": streak >= 2}
        if raw_ready and streak < 2:
            a["pre_debounce_action"] = a.get("final_action")
            a["qualified"] = False
            a["lifecycle"] = "CONFIRMING"
            a["final_action"] = "WAIT"
            reasons = list(a.get("no_trade_reasons") or [])
            reasons.append(f"TEMPORAL CONFIRMATION {streak}/2")
            a["no_trade_reasons"] = list(dict.fromkeys(reasons))
        x["adaptive"] = a
        out.append(x)
    return out


def _setup_transition_alerts(adaptive_setups):
    for row in adaptive_setups or []:
        sym = str(row.get("symbol") or "").upper()
        if not sym:
            continue
        state = str((row.get("adaptive") or {}).get("lifecycle") or "WATCH")
        old = _SETUP_STATE.get(sym)
        _SETUP_STATE[sym] = state
        if not old or old == state:
            continue
        a = row.get("adaptive") or {}
        if state == "READY":
            action = a.get("final_action") or row.get("action") or "SETUP"
            _smart_emit(
                "TRADE READY", "SETUP_READY", sym,
                f"{sym} — {action} READY",
                f"Qualified setup: confidence {a.get('confidence_score')} · execution {(a.get('execution_quality') or {}).get('score')}",
                {"from": old, "to": state, "action": action}, cooldown=90,
            )
        elif state == "INVALIDATED" and old in {"READY", "CONFIRMING"}:
            _smart_emit("WATCH", "SETUP_INVALIDATED", sym, f"{sym} — SETUP INVALIDATED", f"Lifecycle {old} → {state}", {"from": old, "to": state}, cooldown=60)


def _build_snapshot(svc) -> Dict[str, Any]:
    global _LAST_SNAPSHOT
    try:
        provider = svc.status() or {}
    except Exception:
        provider = {}
    scanner = legacy.base._background_meta()
    try:
        global_payload = svc.global_market_snapshot(force=False) or {}
        markets = [dict(x) for x in (global_payload.get("markets") or []) if isinstance(x, dict)]
    except Exception as exc:
        global_payload = {"status": "UNAVAILABLE", "reason": str(exc)[:160], "markets": []}
        markets = []
    _record_vix(markets)
    with _LOCK:
        vix_hist = list(_VIX_HISTORY)

    indexes = legacy._index_cards(svc)
    sectors = legacy._sector_rows()
    raw_setups = legacy._setup_cards()
    dq = core.data_quality(provider, scanner)
    vix = core.vix_intelligence(markets, vix_hist)
    regime = core.market_regime(indexes, vix, sectors)
    macro = core.cross_market_context(markets)
    adaptive = [core.qualify_setup(x, dq, regime, vix) for x in raw_setups]
    adaptive = _apply_temporal_confirmation(adaptive)
    best = core.best_qualified_setup(adaptive)
    risk = core.risk_state(dq, vix, regime, adaptive)
    correlation = core.correlation_guard(adaptive)
    priority = core.watchlist_priority(adaptive, 10)

    current = {
        "version": VERSION,
        "release": RELEASE,
        "epoch": time.time(),
        "iso": _iso(),
        "market_regime": regime,
        "vix": vix,
        "macro_context": macro,
        "risk_state": risk,
        "data_quality": dq,
        "best_setup": best,
        "priority_setups": priority,
        "setups": adaptive,
        "indices": indexes,
        "sectors": sectors,
        "correlation_guard": correlation,
        "global_markets": markets,
        "provider_global_status": global_payload.get("status"),
        "policy": "Decision support only. No synthetic market values, no guaranteed accuracy, no broker order placement.",
        "read_only": True,
        "execution_enabled": False,
    }

    with _LOCK:
        previous = copy.deepcopy(_LAST_SNAPSHOT) if _LAST_SNAPSHOT else None
    changes = core.what_changed(previous, current)
    current["what_changed"] = changes

    for event in changes:
        severity = core.alert_severity(event)
        if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK["WATCH"]:
            continue
        field = str(event.get("field") or "STATE").upper().replace("_", " ")
        _smart_emit(severity, "STATE_CHANGE", "MARKET", f"{field} CHANGED", f"{event.get('from')} → {event.get('to')}", event, cooldown=75)
    _setup_transition_alerts(adaptive)
    _material_memory(current)

    with _LOCK:
        _LAST_SNAPSHOT = copy.deepcopy(current)
        current["alerts"] = list(_SMART_ALERTS)[-80:][::-1]
    return current


@app.get("/api/v74.5/command-center")
def command_center(request: Request):
    svc = legacy.base.request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=legacy.base._auth_detail(svc))
    return _build_snapshot(svc)


@app.get("/api/v74.5/vix-risk")
def vix_risk(request: Request):
    svc = legacy.base.request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=legacy.base._auth_detail(svc))
    snap = _build_snapshot(svc)
    return {
        "version": VERSION,
        "vix": snap.get("vix"),
        "market_regime": snap.get("market_regime"),
        "risk_state": snap.get("risk_state"),
        "macro_context": snap.get("macro_context"),
        "read_only": True,
    }


@app.get("/api/v74.5/setup/{symbol}")
def adaptive_setup(symbol: str, request: Request):
    svc = legacy.base.request_service(request)
    if not svc.authenticated or getattr(svc, "token_invalid", False):
        raise HTTPException(status_code=401, detail=legacy.base._auth_detail(svc))
    sym = legacy.base._clean_symbol(symbol)
    snap = _build_snapshot(svc)
    row = next((x for x in snap.get("setups") or [] if str(x.get("symbol") or "").upper() == sym), None)
    if not row:
        return {
            "version": VERSION,
            "symbol": sym,
            "status": "NO QUALIFIED SETUP DATA",
            "final_action": "NO TRADE",
            "data_quality": snap.get("data_quality"),
            "risk_state": snap.get("risk_state"),
            "read_only": True,
        }
    return {"version": VERSION, "symbol": sym, "setup": row, "market_regime": snap.get("market_regime"), "vix": snap.get("vix"), "risk_state": snap.get("risk_state"), "read_only": True}


@app.get("/api/v74.5/alerts")
def smart_alerts(since_epoch: float = Query(0.0), limit: int = Query(100, ge=1, le=500), minimum_severity: str = Query("WATCH")):
    minimum_severity = str(minimum_severity or "WATCH").upper()
    threshold = SEVERITY_RANK.get(minimum_severity, SEVERITY_RANK["WATCH"])
    with _LOCK:
        rows = [dict(x) for x in _SMART_ALERTS if float(x.get("epoch") or 0) > since_epoch and SEVERITY_RANK.get(str(x.get("severity") or "INFO"), 0) >= threshold]
        latest = max([float(x.get("epoch") or 0) for x in _SMART_ALERTS], default=0.0)
    return {
        "version": VERSION,
        "items": rows[-limit:][::-1],
        "latest_epoch": latest,
        "default_mode": "IMPORTANT_ONLY",
        "policy": "Normal UI suppresses INFO/test noise; one visible toast at a time; duplicates are cooled down.",
        "read_only": True,
    }


@app.get("/api/v74.5/accuracy")
def adaptive_accuracy(request: Request, limit: int = Query(1000, ge=20, le=5000)):
    _ = legacy.base.request_service(request)
    report = legacy.prev.precision.accuracy_report(limit)
    with _LOCK:
        snap = copy.deepcopy(_LAST_SNAPSHOT) if _LAST_SNAPSHOT else {}
    setups = snap.get("setups") or []
    qualified = sum(1 for x in setups if bool((x.get("adaptive") or {}).get("qualified")))
    rejected = max(0, len(setups) - qualified)
    return {
        "version": VERSION,
        "legacy_observed": report,
        "adaptive_calibration": core.calibration_summary(report, qualified, rejected),
        "validation_policy": {
            "walk_forward_required": True,
            "future_leakage_forbidden": True,
            "slippage_and_spread_required": True,
            "champion_challenger_shadow_first": True,
            "confidence_is_not_guaranteed_accuracy": True,
        },
        "read_only": True,
    }


@app.get("/api/v74.5/memory")
def adaptive_memory(request: Request, limit: int = Query(80, ge=1, le=500)):
    _ = legacy.base.request_service(request)
    rows = market_memory.MEMORY.recent(limit=limit)
    return {"version": VERSION, "memory": rows, "summary": market_memory.MEMORY.summary(), "read_only": True}


@app.get("/api/v74.5/feature-manifest")
def feature_manifest():
    return {
        "version": VERSION,
        "release": RELEASE,
        "features": V745_FEATURES,
        "locked_rule": "V74.5 is additive. Existing V74.3/V74.4 functionality is preserved; new trade-ready states pass accuracy, risk and execution gates.",
        "read_only": True,
    }


@app.get("/api/v74.5/system")
def adaptive_system(request: Request):
    svc = legacy.base.request_service(request)
    try:
        provider = svc.status() or {}
    except Exception:
        provider = {}
    route_paths = {getattr(r, "path", None) for r in app.router.routes}
    return {
        "version": VERSION,
        "release": RELEASE,
        "provider": provider,
        "scanner": legacy.base._background_meta(),
        "memory": market_memory.MEMORY.summary(),
        "production_safety": {
            "test_alerts_in_normal_stream": False,
            "legacy_server_push_default": bool(os.getenv("POWERHOUSE_LEGACY_PUSH", "0") == "1"),
            "broker_execution": False,
            "missing_values_as_zero": False,
            "no_trade_abstention": True,
        },
        "features": V745_FEATURES,
        "feature_contract": {
            "v743_preserved": "/v743" in route_paths,
            "v744_preserved": "/v744" in route_paths,
            "v744_light_preserved": "/v744-light" in route_paths,
            "adaptive_command_center": "/api/v74.5/command-center" in route_paths,
            "vix_intelligence": "/api/v74.5/vix-risk" in route_paths,
            "smart_alerts": "/api/v74.5/alerts" in route_paths,
            "adaptive_accuracy": "/api/v74.5/accuracy" in route_paths,
        },
        "read_only": True,
        "execution_enabled": False,
    }


# Keep static mounts after dynamic routes, matching the V74.4 protection.
try:
    from starlette.routing import Mount
    mounts = [r for r in app.router.routes if isinstance(r, Mount)]
    normal = [r for r in app.router.routes if not isinstance(r, Mount)]
    app.router.routes[:] = normal + mounts
except Exception:
    pass
