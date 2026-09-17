from __future__ import annotations

"""POWERHOUSE AI V74 — Maximum Move Capture & Accountability OS.

Additive orchestration over the V73 LTS / V72.2 cumulative intelligence stack.
Primary engineering objective:
MAXIMUM MOVE CAPTURE + EARLY DETECTION + HIGH-QUALITY EXECUTION + ZERO AVOIDABLE MISSES.

This module is read-only decision support. It never places orders and never claims
100% profitability or guaranteed movement capture. Missing/stale evidence stays visible.
"""

import math
import statistics
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from v73_lts_engine import (
    build_v73,
    circuit_hunter,
    depth_dom_intelligence,
    hero_execution_plan as hero_execution_plan_v73,
    volume_pulse,
)

VERSION = "74.0"
RELEASE = "74.0-maximum-move-capture-accountability"
IST = ZoneInfo("Asia/Kolkata")
_LOCK = threading.RLock()

TOP_LEVEL_TABS = [
    "COMMAND", "LIVE MARKET", "RADAR", "PRE-MOVE", "HERO", "AUTO TRENDER",
    "BREAKOUT", "REVERSAL", "SUPPLY-DEMAND", "SECTORS", "HEATMAP",
    "GAINERS-LOSERS", "FAST MOVERS", "DERIVATIVES", "OPTION CHAIN", "OI",
    "FUTURES", "GREEKS", "IV", "EXPIRY", "VOLUME", "ORDER FLOW", "DEPTH",
    "SMART MONEY", "CHART", "PATTERNS", "CANDLESTICKS", "VIX", "CIRCUITS",
    "ALERTS", "RE-ENTRY", "MISSED MOVES", "REPLAY", "PERFORMANCE", "SYSTEM",
]
TAB_ARCHITECTURE = [
    {"id": t.lower().replace(" ", "-").replace("/", "-"), "label": t}
    for t in TOP_LEVEL_TABS
]

LIFECYCLE = [
    "DISCOVERY", "EARLY CLUE", "BUILDING", "ACCELERATING", "ARMING",
    "TRIGGER NEAR", "TRIGGER READY", "HERO", "ENTRY ACTIVE", "T1", "T2",
    "T3", "RUNNER", "EXIT / RE-ENTRY",
]
MOVE_CLASSES = [
    "MICRO MOVE", "TRADEABLE MOVE", "BIG MOVE", "SECTOR MOVE",
    "BREAKOUT MOVE", "REVERSAL MOVE", "CIRCUIT MOVE", "EXPIRY GAMMA MOVE",
]
MISS_CLASSES = [
    "NOT DISCOVERED", "DISCOVERED LATE", "PROMOTION TOO SLOW",
    "OPTION CHAIN DELAY", "FEED STALE", "THRESHOLD TOO STRICT",
    "SECTOR FILTER BLOCKED", "PATTERN LATE", "UI DELAY",
    "PREMIUM RESPONSE LATE", "RATE LIMIT",
]

SCOUT_WEIGHTS = {
    "price": 0.20,
    "volume": 0.15,
    "oi": 0.15,
    "sector": 0.12,
    "order_flow": 0.14,
    "pattern": 0.12,
    "options": 0.12,
}

# Intraday, process-local telemetry. V72/V73 replay remains the durable forensic source.
_SYMBOL_HISTORY: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1200))
_CANDIDATE_STATE: Dict[str, dict] = {}
_MOVE_EVENTS: deque = deque(maxlen=5000)
_MISS_EVENTS: deque = deque(maxlen=2000)
_UI_LATENCY: deque = deque(maxlen=500)


def _f(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(v)))


def _symbol(row: dict) -> str:
    return str(row.get("symbol") or row.get("tradingsymbol") or "").upper().strip()


def _snapshot_rows(snapshot: dict, v73: Optional[dict] = None) -> List[dict]:
    """Prefer V72 pre-move rows; merge snapshot rows without inventing missing fields."""
    rows: List[dict] = []
    if isinstance(v73, dict):
        base72 = v73.get("base_v72") or {}
        pm = base72.get("pre_move_rows") or []
        if isinstance(pm, list):
            rows.extend(x for x in pm if isinstance(x, dict))
    for key in ("fno_universe", "stocks", "stock_rows", "sector_data", "sector_heatmap"):
        val = snapshot.get(key)
        if isinstance(val, list):
            rows.extend(x for x in val if isinstance(x, dict))
    ded: Dict[str, dict] = {}
    for r in rows:
        sym = _symbol(r)
        if not sym:
            continue
        ded[sym] = {**ded.get(sym, {}), **r, "symbol": sym}
    return list(ded.values())


def _quote_age(row: dict) -> Optional[float]:
    return _f(row.get("quote_age_sec"), _f(row.get("age_sec"), _f(row.get("feed_age_sec"))))


def _change_pct(row: dict) -> float:
    return _f(row.get("change_pct"), _f(row.get("changePercent"), 0.0)) or 0.0


def _history_metrics(sym: str, ltp: Optional[float], volume: Optional[float], oi: Optional[float]) -> dict:
    now = time.time()
    with _LOCK:
        h = _SYMBOL_HISTORY[sym]
        prior = h[-1] if h else None
        h.append({"t": now, "ltp": ltp, "volume": volume, "oi": oi})
        # A short baseline if API polling is slower than 15s; no interpolation/fake ticks.
        def ref(seconds: int) -> Optional[dict]:
            target = now - seconds
            found = None
            for item in reversed(h):
                found = item
                if item["t"] <= target:
                    break
            return found
        r15, r30, r60 = ref(15), ref(30), ref(60)

    def pct(old: Optional[float], cur: Optional[float]) -> Optional[float]:
        if old is None or cur is None or old == 0:
            return None
        return (cur - old) / abs(old) * 100.0

    p15 = pct(_f((r15 or {}).get("ltp")), ltp)
    p30 = pct(_f((r30 or {}).get("ltp")), ltp)
    p60 = pct(_f((r60 or {}).get("ltp")), ltp)
    v60 = pct(_f((r60 or {}).get("volume")), volume)
    oi60 = pct(_f((r60 or {}).get("oi")), oi)
    acceleration = None
    if p15 is not None and p30 is not None:
        acceleration = p15 - (p30 / 2.0)
    return {
        "price_15s_pct": p15,
        "price_30s_pct": p30,
        "price_60s_pct": p60,
        "price_acceleration": acceleration,
        "volume_60s_pct": v60,
        "oi_60s_pct": oi60,
        "samples": len(_SYMBOL_HISTORY.get(sym, ())),
        "prior": prior,
    }


def _score_price(row: dict, hm: dict) -> dict:
    chg = abs(_change_pct(row))
    p15, p30, p60 = (_f(hm.get(k)) for k in ("price_15s_pct", "price_30s_pct", "price_60s_pct"))
    accel = abs(_f(hm.get("price_acceleration"), 0.0) or 0.0)
    live_parts = [abs(x) for x in (p15, p30, p60) if x is not None]
    score = _clamp(chg * 13 + (max(live_parts) * 38 if live_parts else 0) + accel * 55)
    ready = _f(row.get("ltp")) is not None
    return {"status": "READY" if ready else "UNAVAILABLE", "score": round(score, 1) if ready else None,
            "change_pct": round(_change_pct(row), 3), "velocity": {"15s": p15, "30s": p30, "60s": p60},
            "acceleration": _f(hm.get("price_acceleration"))}


def _score_volume(row: dict, hm: dict) -> dict:
    vp = volume_pulse(row)
    if vp.get("status") != "READY":
        return {"status": "UNAVAILABLE", "score": None, "rvol": None, "volume_velocity": _f(hm.get("volume_60s_pct"))}
    rvol = _f(vp.get("rvol"))
    vv = abs(_f(hm.get("volume_60s_pct"), 0.0) or 0.0)
    base = _f(vp.get("score"), 0.0) or 0.0
    score = _clamp(base * 0.75 + min(25, vv * 0.8))
    return {"status": "READY", "score": round(score, 1), "rvol": rvol,
            "volume_velocity": _f(hm.get("volume_60s_pct")), "state": vp.get("state"),
            "turnover": vp.get("turnover_estimate")}


def _oi_value(row: dict) -> Optional[float]:
    return _f(row.get("futures_oi"), _f(row.get("oi"), _f(row.get("open_interest"))))


def _score_oi(row: dict, hm: dict) -> dict:
    d = _f(row.get("futures_oi_change_pct"), _f(row.get("oi_change_pct"), _f(row.get("delta_oi_pct"))))
    vel = _f(row.get("oi_velocity"), _f(hm.get("oi_60s_pct")))
    acc = _f(row.get("oi_acceleration"))
    state = row.get("oi_state")
    ready = any(x is not None for x in (d, vel, acc)) or bool(state)
    if not ready:
        return {"status": "UNAVAILABLE", "score": None, "delta_oi_pct": None, "oi_velocity": None, "oi_acceleration": None}
    score = _clamp(abs(d or 0) * 8 + abs(vel or 0) * 2.2 + abs(acc or 0) * 1.8 + (12 if state else 0))
    return {"status": "READY", "score": round(score, 1), "delta_oi_pct": d, "oi_velocity": vel,
            "oi_acceleration": acc, "state": state}


def _score_sector(row: dict) -> dict:
    strength = _f(row.get("sector_strength"), _f(row.get("sector_score"), _f(row.get("sector_momentum"))))
    breadth = _f(row.get("sector_breadth"), _f(row.get("breadth_pct")))
    ignition = row.get("sector_ignition")
    ready = strength is not None or breadth is not None or ignition is not None
    if not ready:
        return {"status": "UNAVAILABLE", "score": None, "strength": None, "breadth": None, "ignition": None}
    # Strength values may already be 0..100; small signed values are treated as percentage momentum.
    s = 50.0
    if strength is not None:
        s = strength if 0 <= strength <= 100 else _clamp(50 + strength * 10)
    if breadth is not None:
        b = breadth if 0 <= breadth <= 100 else _clamp(50 + breadth)
        s = s * 0.65 + b * 0.35
    if bool(ignition):
        s = min(100, s + 12)
    return {"status": "READY", "score": round(_clamp(s), 1), "strength": strength, "breadth": breadth,
            "ignition": bool(ignition), "sector": row.get("sector")}


def _score_order_flow(row: dict) -> dict:
    dom = row.get("depth_intelligence") or depth_dom_intelligence(row)
    if dom.get("status") != "READY":
        return {"status": "UNAVAILABLE", "score": None, "pressure": None, "spread_pct": None}
    pressure = _f(dom.get("pressure"))
    spread = _f(dom.get("spread_pct"))
    side = str(row.get("v72_side") or row.get("side") or "").upper()
    directional = pressure
    if pressure is not None and side in ("PE", "PUT", "SELL", "SHORT"):
        directional = 100 - pressure
    score = _clamp((directional if directional is not None else 50) - max(0, (spread or 0.8) - 0.8) * 12)
    absorption = row.get("absorption") or row.get("depth_absorption")
    vacuum = row.get("liquidity_vacuum")
    if absorption:
        score = min(100, score + 7)
    if vacuum:
        score = min(100, score + 8)
    return {"status": "READY", "score": round(score, 1), "pressure": pressure, "spread_pct": spread,
            "bias": dom.get("bias"), "absorption": absorption, "liquidity_vacuum": vacuum,
            "bid_refill": row.get("bid_refill"), "ask_depletion": row.get("ask_depletion")}


def _pattern_name(row: dict) -> Optional[str]:
    p = row.get("pattern") or row.get("developing_pattern") or row.get("pattern_name")
    if p:
        return str(p)
    arr = row.get("forming_patterns")
    if isinstance(arr, list) and arr:
        x = arr[0]
        if isinstance(x, dict):
            return str(x.get("name") or x.get("pattern") or "") or None
        return str(x)
    return None


def _score_pattern(row: dict) -> dict:
    pattern = _pattern_name(row)
    quality = _f(row.get("pattern_quality"), _f(row.get("formation_quality")))
    location = _f(row.get("location_score"))
    breakout = bool(row.get("breakout") or row.get("breakout_ready") or "BREAK" in str(pattern or "").upper())
    reversal = bool(row.get("reversal") or "REVERS" in str(pattern or "").upper())
    compression = bool(row.get("compression") or "SQUEEZE" in str(pattern or "").upper())
    ready = pattern is not None or quality is not None or any((breakout, reversal, compression))
    if not ready:
        return {"status": "UNAVAILABLE", "score": None, "pattern": None}
    score = quality if quality is not None else 48.0
    if location is not None:
        score = score * 0.72 + location * 0.28
    score += 8 if breakout or reversal else 4 if compression else 0
    return {"status": "READY", "score": round(_clamp(score), 1), "pattern": pattern,
            "breakout": breakout, "reversal": reversal, "compression": compression,
            "location_score": location}


def _score_options(row: dict) -> dict:
    premium = _f(row.get("premium_response"), _f((row.get("scores") or {}).get("premium_response")))
    iv = _f(row.get("iv"), _f(row.get("implied_volatility")))
    gamma = _f(row.get("gamma"), _f((row.get("scores") or {}).get("gamma")))
    wall = row.get("oi_wall_migration") or row.get("strike_migration")
    elasticity = _f(row.get("premium_elasticity"))
    ready = any(x is not None for x in (premium, iv, gamma, elasticity)) or wall is not None
    if not ready:
        return {"status": "UNAVAILABLE", "score": None, "premium_response": None, "iv": None,
                "gamma": None, "oi_wall_migration": None}
    vals = []
    if premium is not None:
        vals.append(_clamp(premium))
    if gamma is not None:
        vals.append(_clamp(gamma if 0 <= gamma <= 100 else gamma * 1000))
    if elasticity is not None:
        vals.append(_clamp(50 + elasticity * 12))
    if wall is not None:
        vals.append(68.0)
    score = statistics.fmean(vals) if vals else 50.0
    return {"status": "READY", "score": round(_clamp(score), 1), "premium_response": premium,
            "iv": iv, "gamma": gamma, "oi_wall_migration": wall, "premium_elasticity": elasticity,
            "premium_failure": row.get("premium_failure")}


def seven_scouts(row: dict) -> dict:
    sym = _symbol(row)
    ltp = _f(row.get("ltp"))
    vol = _f(row.get("volume"))
    oi = _oi_value(row)
    hm = _history_metrics(sym, ltp, vol, oi) if sym else {}
    scouts = {
        "price": _score_price(row, hm),
        "volume": _score_volume(row, hm),
        "oi": _score_oi(row, hm),
        "sector": _score_sector(row),
        "order_flow": _score_order_flow(row),
        "pattern": _score_pattern(row),
        "options": _score_options(row),
    }
    weighted = 0.0
    used = 0.0
    ready = []
    for name, info in scouts.items():
        score = _f(info.get("score"))
        if info.get("status") == "READY" and score is not None:
            w = SCOUT_WEIGHTS[name]
            weighted += score * w
            used += w
            ready.append(name)
    aggregate = weighted / used if used else 0.0
    return {
        "symbol": sym,
        "aggregate_score": round(_clamp(aggregate), 1),
        "ready_scouts": ready,
        "ready_count": len(ready),
        "missing_scouts": [k for k in scouts if k not in ready],
        "scouts": scouts,
        "history_metrics": {k: v for k, v in hm.items() if k != "prior"},
    }


def _lifecycle(score: float, row: dict, scout: dict) -> str:
    # Preserve stronger evidence-supported V72 state when available.
    base = str(row.get("pre_move_stage") or row.get("stage") or "").upper().strip()
    aliases = {
        "SCANNING": "DISCOVERY", "WATCH": "EARLY CLUE", "EARLY MOVER": "EARLY CLUE",
        "EARLY CLUE": "EARLY CLUE", "BUILDING": "BUILDING", "ACCELERATING": "ACCELERATING",
        "ARMING": "ARMING", "TRIGGER NEAR": "TRIGGER NEAR", "TRIGGER READY": "TRIGGER READY",
        "HERO READY": "HERO", "HERO ACTIVE": "ENTRY ACTIVE",
    }
    by_score = (
        "TRIGGER READY" if score >= 84 else
        "TRIGGER NEAR" if score >= 76 else
        "ARMING" if score >= 67 else
        "ACCELERATING" if score >= 57 else
        "BUILDING" if score >= 45 else
        "EARLY CLUE" if score >= 32 else
        "DISCOVERY"
    )
    b = aliases.get(base)
    if not b:
        return by_score
    rank = {x: i for i, x in enumerate(LIFECYCLE)}
    return b if rank.get(b, -1) > rank.get(by_score, -1) else by_score


def _move_class(row: dict, scout: dict, session: Optional[dict] = None) -> str:
    chg = abs(_change_pct(row))
    p = scout.get("scouts", {}).get("pattern", {})
    s = scout.get("scouts", {}).get("sector", {})
    options = scout.get("scouts", {}).get("options", {})
    ltp = _f(row.get("ltp"))
    uc = _f(row.get("upper_circuit_limit"), _f(row.get("upper_circuit"), _f(row.get("uc"))))
    lc = _f(row.get("lower_circuit_limit"), _f(row.get("lower_circuit"), _f(row.get("lc"))))
    if ltp is not None and ((uc and abs(uc-ltp)/max(abs(ltp),1e-9) <= 0.003) or (lc and abs(ltp-lc)/max(abs(ltp),1e-9) <= 0.003)):
        return "CIRCUIT MOVE"
    if (session or {}).get("expiry_mode") and (_f(options.get("gamma"), 0) or 0) >= 65:
        return "EXPIRY GAMMA MOVE"
    if p.get("reversal") and chg >= 0.6:
        return "REVERSAL MOVE"
    if p.get("breakout") and chg >= 0.6:
        return "BREAKOUT MOVE"
    if s.get("ignition") and (_f(s.get("score"), 0) or 0) >= 70 and chg >= 0.75:
        return "SECTOR MOVE"
    if chg >= 2.0:
        return "BIG MOVE"
    if chg >= 0.75:
        return "TRADEABLE MOVE"
    return "MICRO MOVE"


def _direction(row: dict) -> str:
    side = str(row.get("v72_side") or row.get("side") or "").upper()
    if side in ("CE", "CALL", "BUY", "LONG", "BULLISH"):
        return "UP"
    if side in ("PE", "PUT", "SELL", "SHORT", "BEARISH"):
        return "DOWN"
    return "UP" if _change_pct(row) >= 0 else "DOWN"


def _second_chance(row: dict, scout: dict, stage: str) -> List[str]:
    out: List[str] = []
    if row.get("breakout_retest") or row.get("retest"):
        out.append("Breakout Retest")
    if row.get("vwap_reclaim"):
        out.append("VWAP Reclaim")
    if row.get("demand_retest"):
        out.append("Demand Retest")
    if row.get("supply_flip"):
        out.append("Supply Flip")
    if row.get("pullback_continuation"):
        out.append("Pullback Continuation")
    if row.get("ema_hold") or row.get("vwap_hold"):
        out.append("EMA/VWAP Hold")
    opt = scout.get("scouts", {}).get("options", {})
    if (_f(opt.get("premium_response"), 0) or 0) >= 65 and stage not in ("DISCOVERY", "EARLY CLUE"):
        out.append("Option Premium Re-acceleration")
    if row.get("alternate_strike_ready"):
        out.append("Alternate Strike")
    if row.get("reentry_ready"):
        out.append("Re-entry")
    # Do not fabricate a retest; if no evidence is supplied, state what is being watched.
    if not out and stage in ("TRIGGER READY", "HERO", "ENTRY ACTIVE"):
        out = ["WATCH: Breakout Retest", "WATCH: VWAP/EMA Hold", "WATCH: Re-entry"]
    return out


def _big_move_state(move_class: str, score: float, scout: dict) -> str:
    if move_class != "MICRO MOVE" and abs(_f(scout.get("scouts", {}).get("price", {}).get("change_pct"), 0) or 0) >= 0.75:
        return "MOVE ACTIVE"
    if score >= 78:
        return "BREAK IMMINENT"
    if score >= 65:
        return "PRESSURE RISING"
    if score >= 48:
        return "EARLY BUILD"
    return "WATCH"


def _session_name(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(IST)
    hm = now.hour * 60 + now.minute
    if 9 * 60 + 15 <= hm <= 9 * 60 + 30:
        return "OPENING BRAIN"
    if 14 * 60 + 45 <= hm <= 15 * 60 + 30:
        return "CLOSING BRAIN"
    if 9 * 60 + 15 <= hm <= 15 * 60 + 30:
        return "INTRADAY BRAIN"
    return "MARKET CLOSED / OFF SESSION"


def _expiry_mode(snapshot: dict, v73: Optional[dict] = None) -> bool:
    flags = [
        snapshot.get("expiry_mode"), snapshot.get("is_expiry_day"), snapshot.get("hero_zero_mode"),
        ((v73 or {}).get("base_v72") or {}).get("expiry_mode"),
        (((v73 or {}).get("base_v72") or {}).get("expiry_intelligence") or {}).get("is_expiry"),
    ]
    if any(x is True for x in flags):
        return True
    dte = _f(snapshot.get("days_to_expiry"))
    return dte == 0 if dte is not None else False


def session_brain(snapshot: dict, candidates: Optional[List[dict]] = None, v73: Optional[dict] = None) -> dict:
    now = datetime.now(IST)
    mode = _session_name(now)
    expiry = _expiry_mode(snapshot, v73)
    rows = candidates or []
    opening = sorted(rows, key=lambda x: (
        _f(((x.get("scout_pack") or {}).get("scouts") or {}).get("volume", {}).get("score"), 0) or 0,
        _f(x.get("score"), 0) or 0,
    ), reverse=True)[:15]
    closing = sorted(rows, key=lambda x: (
        abs(_f(x.get("change_pct"), 0) or 0), _f(x.get("score"), 0) or 0
    ), reverse=True)[:15]
    return {
        "time_ist": now.isoformat(),
        "active_brain": "EXPIRY BRAIN" if expiry else mode,
        "expiry_mode": expiry,
        "opening_window": "09:15-09:30 IST",
        "closing_window": "14:45-15:30 IST",
        "opening_focus": ["gap", "opening volume", "opening range", "VWAP", "sector leadership", "first breakout", "first failure"],
        "closing_focus": ["short covering", "long unwinding", "closing momentum", "expiry pressure", "overnight risk"],
        "expiry_focus": ["gamma", "theta", "pinning", "wall migration", "premium decay", "Hero-Zero mode", "late-entry block"],
        "opening_candidates": opening,
        "closing_candidates": closing,
    }


def record_ui_latency(fetch_ms: Optional[float], render_ms: Optional[float], tab: Optional[str] = None) -> dict:
    item = {"t": time.time(), "fetch_ms": _f(fetch_ms), "render_ms": _f(render_ms), "tab": str(tab or "")[:40]}
    with _LOCK:
        _UI_LATENCY.append(item)
    return {"recorded": True, **item}


def _ui_delay_active() -> bool:
    with _LOCK:
        recent = list(_UI_LATENCY)[-30:]
    vals = [(_f(x.get("fetch_ms"), 0) or 0) + (_f(x.get("render_ms"), 0) or 0) for x in recent]
    return bool(vals and statistics.fmean(vals) >= 1800)


def _root_cause(row: dict, candidate: Optional[dict], moved: bool) -> Optional[str]:
    if not moved:
        return None
    age = _quote_age(row)
    if age is not None and age > 10:
        return "FEED STALE"
    error = str(row.get("provider_error") or row.get("error") or "").lower()
    if "rate limit" in error or "429" in error:
        return "RATE LIMIT"
    if _ui_delay_active():
        return "UI DELAY"
    if candidate is None:
        return "NOT DISCOVERED"
    if candidate.get("discovered_after_move"):
        return "DISCOVERED LATE"
    if candidate.get("promotion_lag_sec") and (_f(candidate.get("promotion_lag_sec"), 0) or 0) > 45:
        return "PROMOTION TOO SLOW"
    sc = candidate.get("scout_pack") or {}
    opts = (sc.get("scouts") or {}).get("options") or {}
    if opts.get("status") != "READY" and row.get("option_chain_expected"):
        return "OPTION CHAIN DELAY"
    sector = (sc.get("scouts") or {}).get("sector") or {}
    if sector.get("status") == "READY" and (_f(sector.get("score"), 50) or 50) < 40:
        return "SECTOR FILTER BLOCKED"
    pattern = (sc.get("scouts") or {}).get("pattern") or {}
    if pattern.get("status") != "READY" and row.get("pattern_expected"):
        return "PATTERN LATE"
    premium = _f(opts.get("premium_response"))
    if opts.get("status") == "READY" and premium is not None and premium < 45:
        return "PREMIUM RESPONSE LATE"
    if (_f(candidate.get("score"), 0) or 0) < 45:
        return "THRESHOLD TOO STRICT"
    return "DISCOVERED LATE"


def _remember_candidate(row: dict, candidate: dict) -> None:
    sym = candidate["symbol"]
    if not sym:
        return
    now = time.time()
    ltp = _f(row.get("ltp"))
    side = _direction(row)
    with _LOCK:
        old = _CANDIDATE_STATE.get(sym)
        if old is None:
            old = {
                "symbol": sym, "first_seen": now, "first_ltp": ltp, "side": side,
                "first_stage": candidate.get("stage"), "first_score": candidate.get("score"),
                "max_stage_rank": LIFECYCLE.index(candidate.get("stage")) if candidate.get("stage") in LIFECYCLE else 0,
                "mfe_pct": 0.0, "mae_pct": 0.0, "move_started_at": None,
                "first_clue_at": now if candidate.get("stage") != "DISCOVERY" else None,
                "trigger_ready_at": now if candidate.get("stage") == "TRIGGER READY" else None,
            }
            _CANDIDATE_STATE[sym] = old
        rank = LIFECYCLE.index(candidate.get("stage")) if candidate.get("stage") in LIFECYCLE else 0
        old["max_stage_rank"] = max(int(old.get("max_stage_rank") or 0), rank)
        if old.get("first_clue_at") is None and candidate.get("stage") != "DISCOVERY":
            old["first_clue_at"] = now
        if old.get("trigger_ready_at") is None and candidate.get("stage") == "TRIGGER READY":
            old["trigger_ready_at"] = now
        if old.get("first_ltp") and ltp:
            raw = (ltp - old["first_ltp"]) / abs(old["first_ltp"]) * 100.0
            fav = raw if old.get("side") == "UP" else -raw
            old["mfe_pct"] = max(_f(old.get("mfe_pct"), 0) or 0, fav)
            old["mae_pct"] = min(_f(old.get("mae_pct"), 0) or 0, fav)
        old["latest"] = candidate
        old["last_seen"] = now


def _audit_move(row: dict, candidate: dict) -> Optional[dict]:
    move_class = candidate.get("move_class")
    if move_class == "MICRO MOVE":
        return None
    sym = candidate.get("symbol")
    now = time.time()
    with _LOCK:
        state = _CANDIDATE_STATE.get(sym)
        existing = next((x for x in reversed(_MOVE_EVENTS) if x.get("symbol") == sym and now - x.get("event_at", 0) < 900), None)
        if existing:
            existing["move_class"] = move_class
            existing["latest_change_pct"] = candidate.get("change_pct")
            return existing
        first_clue = (state or {}).get("first_clue_at")
        event = {
            "symbol": sym,
            "event_at": now,
            "move_class": move_class,
            "direction": _direction(row),
            "latest_change_pct": candidate.get("change_pct"),
            "first_clue_at": first_clue,
            "lead_time_sec": round(now - first_clue, 2) if first_clue and first_clue <= now else None,
            "detection": "EARLY" if first_clue and first_clue < now - 1 else "LATE",
        }
        _MOVE_EVENTS.append(event)
        cause = _root_cause(row, candidate if first_clue else None, True)
        if cause:
            miss = {**event, "classification": cause, "silent_miss": False}
            _MISS_EVENTS.append(miss)
            event["miss_classification"] = cause
        return event


def candidate_from_row(row: dict, session: Optional[dict] = None) -> dict:
    sc = seven_scouts(row)
    score = _f(sc.get("aggregate_score"), 0.0) or 0.0
    stage = _lifecycle(score, row, sc)
    move_class = _move_class(row, sc, session)
    cand = {
        "symbol": _symbol(row),
        "ltp": _f(row.get("ltp")),
        "change_pct": round(_change_pct(row), 3),
        "side": _direction(row),
        "score": round(score, 1),
        "stage": stage,
        "big_move_state": _big_move_state(move_class, score, sc),
        "move_class": move_class,
        "meaningful_move": move_class != "MICRO MOVE",
        "quote_age_sec": _quote_age(row),
        "scout_pack": sc,
        "second_chance": _second_chance(row, sc, stage),
        "sector": row.get("sector"),
        "pattern": _pattern_name(row),
        "vix_regime": row.get("vix_regime"),
        "supply_demand": row.get("supply_demand") or {
            "supply": row.get("supply_zone"), "demand": row.get("demand_zone")
        },
        "break_pressure": row.get("break_pressure"),
        "data_truth": {
            "fresh": (_quote_age(row) is None or (_quote_age(row) or 999) <= 10),
            "ready_scouts": sc.get("ready_count"),
            "missing_scouts": sc.get("missing_scouts"),
        },
    }
    _remember_candidate(row, cand)
    _audit_move(row, cand)
    return cand


def _coverage(v73: dict, candidates: List[dict]) -> dict:
    c = v73.get("opportunity_coverage") or {}
    expected = int(c.get("expected") or c.get("expected_universe") or 0)
    observed = int(c.get("observed") or len(candidates))
    fresh = int(c.get("fresh_under_10s") or sum(1 for x in candidates if (x.get("data_truth") or {}).get("fresh")))
    with _LOCK:
        moves = list(_MOVE_EVENTS)
        misses = list(_MISS_EVENTS)
    early = sum(1 for x in moves if x.get("detection") == "EARLY")
    late = sum(1 for x in moves if x.get("detection") == "LATE")
    miss_symbols = {x.get("symbol") for x in misses if x.get("classification") in ("NOT DISCOVERED", "FEED STALE", "RATE LIMIT")}
    leads = [_f(x.get("lead_time_sec")) for x in moves if _f(x.get("lead_time_sec")) is not None]
    return {
        "universe_expected": expected,
        "universe_covered": observed,
        "universe_coverage_pct": round(100 * observed / expected, 1) if expected else (100.0 if observed else 0.0),
        "fresh_quotes": fresh,
        "symbols_scanned": len(candidates),
        "meaningful_moves_today": len(moves),
        "moves_detected_early": early,
        "moves_detected_late": late,
        "moves_completely_missed": len(miss_symbols),
        "average_lead_time_sec": round(statistics.fmean(leads), 2) if leads else None,
        "coverage_state": c.get("coverage_state") or ("FULL" if expected and observed >= expected else "PARTIAL" if observed else "WARMING"),
        "silent_misses_allowed": False,
        "accountability": "Every observed meaningful move must be detected or receive an explicit miss classification.",
    }


def miss_killer_report(limit: int = 200) -> dict:
    with _LOCK:
        items = list(_MISS_EVENTS)[-max(1, min(limit, 1000)):]
    counts = {k: 0 for k in MISS_CLASSES}
    for x in items:
        k = str(x.get("classification") or "")
        if k in counts:
            counts[k] += 1
    repeated = sorted(({"classification": k, "count": v} for k, v in counts.items() if v), key=lambda x: x["count"], reverse=True)
    return {
        "version": VERSION,
        "allowed_classifications": MISS_CLASSES,
        "counts": counts,
        "repeated_problems": repeated,
        "events": list(reversed(items)),
        "silent_miss_allowed": False,
    }


def performance_intelligence(candidates: Optional[List[dict]] = None) -> dict:
    with _LOCK:
        states = list(_CANDIDATE_STATE.values())
        moves = list(_MOVE_EVENTS)
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for st in states:
        latest = st.get("latest") or {}
        key = str(latest.get("pattern") or "NO_PATTERN")
        grouped[key].append(st)
    pattern_stats = []
    for pattern, rows in grouped.items():
        mfes = [_f(x.get("mfe_pct"), 0) or 0 for x in rows]
        maes = [_f(x.get("mae_pct"), 0) or 0 for x in rows]
        follow = sum(1 for x in mfes if x >= 0.75)
        pattern_stats.append({
            "pattern": pattern,
            "sample_size": len(rows),
            "observed_follow_through_pct": round(100 * follow / len(rows), 1) if rows else None,
            "median_mfe_pct": round(statistics.median(mfes), 3) if mfes else None,
            "median_mae_pct": round(statistics.median(maes), 3) if maes else None,
            "win_probability": None,
            "truth": "Observed follow-through only; not a forecast probability.",
        })
    pattern_stats.sort(key=lambda x: (x["sample_size"], x.get("observed_follow_through_pct") or 0), reverse=True)
    leads = [_f(x.get("lead_time_sec")) for x in moves if _f(x.get("lead_time_sec")) is not None]
    return {
        "version": VERSION,
        "pattern_records": pattern_stats[:100],
        "overall": {
            "tracked_setups": len(states),
            "meaningful_moves": len(moves),
            "median_lead_time_sec": round(statistics.median(leads), 2) if leads else None,
        },
        "dimensions": ["Pattern", "Regime", "Session", "Sector", "Entry type", "Strike quality", "Observed follow-through", "MFE", "MAE", "Average R", "False breakout rate", "Median lead time", "Sample size"],
        "policy": "No probability label is emitted from small or synthetic samples. Statistics are descriptive observations only.",
    }


def _hero_blockers(underlying: dict, strike_pack: dict, plan: dict, chart: Optional[dict]) -> List[str]:
    blockers: List[str] = []
    age = _quote_age(underlying)
    if age is not None and age > 10:
        blockers.append("DATA STALE")
    winner = (strike_pack or {}).get("winner") or {}
    scores = winner.get("scores") or {}
    spread = _f(winner.get("spread_pct"), _f((plan.get("evidence") or {}).get("spread_pct")))
    liquidity = _f(winner.get("liquidity"), _f(scores.get("liquidity"), _f((plan.get("evidence") or {}).get("liquidity"))))
    premium_response = _f(scores.get("premium_response"), _f((plan.get("evidence") or {}).get("premium_response")))
    theta = _f(scores.get("theta_risk"), _f(winner.get("theta_risk")))
    if spread is not None and spread > 2.5:
        blockers.append("SPREAD WIDE")
    if liquidity is not None and liquidity < 55:
        blockers.append("LIQUIDITY POOR")
    if premium_response is not None and premium_response < 48:
        blockers.append("PREMIUM NOT RESPONDING")
    if underlying.get("sector_conflict"):
        blockers.append("SECTOR CONFLICT")
    if underlying.get("oi_conflict"):
        blockers.append("OI CONFLICT")
    if underlying.get("false_breakout") or (strike_pack or {}).get("false_breakout"):
        blockers.append("FALSE-BREAK EVIDENCE")
    if underlying.get("late_entry") or str(underlying.get("move_quality") or "").upper() in ("LATE", "CROWDED", "EXHAUSTED"):
        blockers.append("LATE/CROWDED ENTRY")
    if underlying.get("vix_shock") or str(underlying.get("vix_regime") or "").upper() in ("SHOCK", "PANIC"):
        blockers.append("VIX SHOCK")
    entry = (plan.get("entry") or {}).get("ideal")
    sl = (plan.get("risk") or {}).get("premium_sl")
    t1 = (plan.get("targets") or {}).get("t1")
    if all(_f(x) is not None for x in (entry, sl, t1)):
        risk = abs(_f(entry) - _f(sl))
        reward = abs(_f(t1) - _f(entry))
        if risk <= 0 or reward / risk < 1.1:
            blockers.append("POOR R:R")
    if theta is not None and theta >= 75 and _expiry_mode(underlying):
        blockers.append("EXPIRY THETA DANGER")
    if underlying.get("mtf_conflict") or (isinstance(chart, dict) and chart.get("mtf_conflict")):
        blockers.append("MULTI-TIMEFRAME CONFLICT")
    return blockers


def hero5_execution_plan(symbol: str, underlying: dict, strike_pack: dict, chart: Optional[dict] = None) -> dict:
    base = hero_execution_plan_v73(symbol, underlying, strike_pack, chart)
    winner = (strike_pack or {}).get("winner") or {}
    blockers = _hero_blockers(underlying, strike_pack, base, chart)
    ready = base.get("status") == "READY" and not blockers
    side = str(base.get("side") or winner.get("side") or "WAIT").upper()
    action = "CALL" if side == "CE" and ready else "PUT" if side == "PE" and ready else "WAIT"
    ev = base.get("evidence") or {}
    liquidity = _f(ev.get("liquidity"), _f(winner.get("liquidity")))
    spread = _f(winner.get("spread_pct"))
    lgrade = "A" if liquidity is not None and liquidity >= 80 and (spread is None or spread <= 1.0) else "B" if liquidity is not None and liquidity >= 65 else "C" if liquidity is not None else "UNAVAILABLE"
    sc = seven_scouts(underlying)
    opt = sc.get("scouts", {}).get("options", {})
    order = sc.get("scouts", {}).get("order_flow", {})
    oi = sc.get("scouts", {}).get("oi", {})
    pattern = sc.get("scouts", {}).get("pattern", {})
    sector = sc.get("scouts", {}).get("sector", {})
    entry = base.get("entry") or {}
    risk = base.get("risk") or {}
    targets = base.get("targets") or {}
    why_now = [
        f"{name.replace('_',' ').title()} scout {info.get('score')}" for name, info in sc.get("scouts", {}).items()
        if info.get("status") == "READY" and (_f(info.get("score"), 0) or 0) >= 65
    ][:6]
    if not why_now:
        why_now = ["Insufficient multi-scout confirmation; WAIT remains valid."]
    why_strike = []
    if winner:
        if winner.get("strike") is not None:
            why_strike.append(f"Selected strike {winner.get('strike')} from current strike intelligence.")
        if liquidity is not None:
            why_strike.append(f"Liquidity evidence {round(liquidity,1)} / 100.")
        if spread is not None:
            why_strike.append(f"Observed spread {round(spread,3)}%.")
    what_changed = list((underlying.get("what_changed") or [])) if isinstance(underlying.get("what_changed"), list) else []
    hm = sc.get("history_metrics") or {}
    if _f(hm.get("price_acceleration")) is not None:
        what_changed.append(f"Price acceleration {round(_f(hm.get('price_acceleration')) or 0,3)} pct-units.")
    invalidates = list(blockers)
    underlying_inv = risk.get("underlying_invalidation")
    if underlying_inv is not None:
        invalidates.append(f"Underlying invalidation {underlying_inv}")
    if risk.get("premium_sl") is not None:
        invalidates.append(f"Premium SL {risk.get('premium_sl')}")
    return {
        "version": VERSION,
        "status": "READY" if ready else "BLOCKED",
        "action": action,
        "symbol": symbol.upper(),
        "expiry": base.get("expiry") or winner.get("expiry") or strike_pack.get("expiry"),
        "strike": base.get("strike") or winner.get("strike"),
        "premium": base.get("premium") or winner.get("premium"),
        "entry_low": entry.get("low"), "ideal_entry": entry.get("ideal"), "entry_high": entry.get("high"),
        "do_not_chase": entry.get("do_not_chase_above"),
        "sl": risk.get("premium_sl"), "structural_sl": risk.get("underlying_invalidation"), "time_stop_min": risk.get("time_stop_min"),
        "t1": targets.get("t1"), "t2": targets.get("t2"), "t3": targets.get("t3"), "extended_target": targets.get("extended"),
        "trailing_rule": "After T1, trail only while OI + premium response + depth + underlying structure remain supportive; never widen risk.",
        "re_entry": "Only evidence-supported breakout retest / VWAP reclaim / demand retest / supply flip / continuation; never average down.",
        "liquidity_grade": lgrade, "liquidity_score": liquidity, "spread_pct": spread,
        "depth": order, "oi_state": oi, "iv_state": {"iv": opt.get("iv"), "gamma": opt.get("gamma")},
        "vix_regime": underlying.get("vix_regime"), "sector_strength": sector,
        "pattern": pattern, "supply_demand": underlying.get("supply_demand") or {"supply": underlying.get("supply_zone"), "demand": underlying.get("demand_zone")},
        "break_pressure": underlying.get("break_pressure"), "premium_response": opt.get("premium_response") or ev.get("premium_response"),
        "why_now": why_now, "why_this_strike": why_strike or ["No qualifying strike evidence."],
        "what_changed": what_changed or ["No change telemetry supplied."],
        "what_invalidates": invalidates or ["Loss of multi-scout alignment or breach of structural risk level."],
        "blocked_by": blockers,
        "base_v73_plan": base,
        "read_only": True,
        "execution_enabled": False,
        "policy": "Exact levels are decision-support values, not guaranteed fills/returns. Trade qualification is stricter than opportunity discovery.",
    }


def build_v74(snapshot: dict, record: bool = True) -> dict:
    t0 = time.perf_counter()
    v73 = build_v73(snapshot, record=record)
    raw_rows = _snapshot_rows(snapshot, v73)
    # First pass session without candidates; second pass uses candidates for ranking.
    sess0 = {"expiry_mode": _expiry_mode(snapshot, v73)}
    candidates = [candidate_from_row(r, sess0) for r in raw_rows]
    candidates.sort(key=lambda x: (x.get("stage") in ("TRIGGER READY", "TRIGGER NEAR", "ARMING"), _f(x.get("score"), 0) or 0), reverse=True)
    sess = session_brain(snapshot, candidates, v73)
    coverage = _coverage(v73, candidates)
    big = [x for x in candidates if x.get("big_move_state") in ("EARLY BUILD", "PRESSURE RISING", "BREAK IMMINENT", "MOVE ACTIVE")]
    big.sort(key=lambda x: (_f(x.get("score"), 0) or 0, abs(_f(x.get("change_pct"), 0) or 0)), reverse=True)
    reentry = [x for x in candidates if x.get("second_chance")]
    ms = (time.perf_counter() - t0) * 1000.0
    return {
        "version": VERSION,
        "release": RELEASE,
        "name": "POWERHOUSE AI V74 — Maximum Move Capture & Accountability OS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "execution_enabled": False,
        "mission": "MAXIMUM MOVE CAPTURE + EARLY DETECTION + HIGH-QUALITY EXECUTION + ZERO AVOIDABLE MISSES",
        "tabs": TAB_ARCHITECTURE,
        "move_classes": MOVE_CLASSES,
        "lifecycle": LIFECYCLE,
        "command": {
            "coverage": coverage,
            "big_move_forming": big[:20],
            "hero_ready": [x for x in candidates if x.get("stage") in ("TRIGGER READY", "HERO", "ENTRY ACTIVE")][:20],
            "re_entry": reentry[:20],
            "session_brain": sess,
            "data_quality": v73.get("data_quality"),
        },
        "coverage": coverage,
        "radar": {"count": len(candidates), "candidates": candidates},
        "big_move_capture_engine": {
            "version": "5.0", "scouts": list(SCOUT_WEIGHTS), "candidates": big[:100],
            "states": ["WATCH", "EARLY BUILD", "PRESSURE RISING", "BREAK IMMINENT", "MOVE ACTIVE"],
        },
        "miss_killer": miss_killer_report(),
        "performance_intelligence": performance_intelligence(candidates),
        "session_brain": sess,
        "circuits": v73.get("circuit_hunter"),
        "alerts": v73.get("alerts"),
        "base_v73": v73,
        "performance": {"v74_orchestration_ms": round(ms, 2), "base_v73": v73.get("performance")},
        "truth_policy": [
            "100% movement capture is an engineering coverage target, not a profitability guarantee.",
            "Every observed meaningful move is detected or assigned an explicit miss classification; silent misses are not allowed.",
            "Missing scouts reduce evidence coverage; missing data is never fabricated as neutral or LIVE.",
            "Opportunity discovery stays broad, while Hero trade qualification remains strict.",
            "All outputs are read-only market intelligence; no automatic broker order placement is enabled.",
        ],
    }


def empty_v74_status(reason: str = "Live market authentication/data unavailable") -> dict:
    return {
        "version": VERSION, "release": RELEASE,
        "name": "POWERHOUSE AI V74 — Maximum Move Capture & Accountability OS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True, "execution_enabled": False,
        "tabs": TAB_ARCHITECTURE,
        "coverage": {"universe_expected": 0, "universe_covered": 0, "fresh_quotes": 0, "symbols_scanned": 0,
                     "meaningful_moves_today": 0, "moves_detected_early": 0, "moves_detected_late": 0,
                     "moves_completely_missed": 0, "average_lead_time_sec": None, "coverage_state": "UNAVAILABLE",
                     "silent_misses_allowed": False},
        "radar": {"count": 0, "candidates": []},
        "big_move_capture_engine": {"version": "5.0", "scouts": list(SCOUT_WEIGHTS), "candidates": []},
        "miss_killer": miss_killer_report(),
        "performance_intelligence": performance_intelligence(),
        "data_status": "UNAVAILABLE", "reason": reason,
        "truth_policy": ["No demo/mock market values are substituted for unavailable LIVE data."],
    }
