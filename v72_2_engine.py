from __future__ import annotations

"""POWERHOUSE AI V72.2 — Timing + Execution Intelligence.

This is a cumulative extension of V72.1.  It does not replace the proven V71/V72.1
census/scoring core; it enriches it with timing, conflict, latency, re-entry,
expiry-mode, alert-priority and replay/forensics layers.  The software remains
read-only and never fabricates market data or guarantees outcomes.
"""

import math
import statistics
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import v72_engine as v721

IST = ZoneInfo("Asia/Kolkata")
_LOCK = threading.RLock()
_TIMING_STATE: Dict[str, deque] = defaultdict(lambda: deque(maxlen=420))
_OPTION_EXEC_STATE: Dict[str, deque] = defaultdict(lambda: deque(maxlen=420))
_LAST_BEST: Dict[str, Any] = {"signature": None, "score": None, "epoch": 0.0}
_FORENSICS_CACHE: Dict[str, Any] = {"epoch": 0.0, "value": None}
_CALIBRATION_CACHE: Dict[str, Any] = {"epoch": 0.0, "value": None}
_LAST_CALIBRATION_LOG = 0.0


def _f(v: Any, default=None):
    return v721._f(v, default)


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return v721._clamp(x, lo, hi)


def _session_mode(now_epoch: Optional[float] = None) -> dict:
    dt = datetime.fromtimestamp(now_epoch or time.time(), IST)
    minute = dt.hour * 60 + dt.minute
    weekday = dt.weekday()
    if weekday >= 5:
        mode = "CLOSED"
    elif 9 * 60 <= minute < 9 * 60 + 15:
        mode = "PREOPEN"
    elif 9 * 60 + 15 <= minute < 9 * 60 + 20:
        mode = "OPENING_5"
    elif 9 * 60 + 20 <= minute < 9 * 60 + 30:
        mode = "OPENING_15"
    elif 9 * 60 + 30 <= minute < 15 * 60:
        mode = "NORMAL"
    elif 15 * 60 <= minute <= 15 * 60 + 30:
        mode = "LATE_SESSION"
    else:
        mode = "CLOSED"
    return {"mode": mode, "ist": dt.isoformat(), "weekday": weekday}


def _multi_tf_alignment(row: dict, side: str) -> dict:
    sign = 1.0 if side == "CE" else -1.0 if side == "PE" else 0.0
    vals = {
        "15s": _f(row.get("velocity_15s")),
        "60s": _f(row.get("velocity_60s")),
        "180s": _f(row.get("velocity_180s")),
        "acceleration": _f(row.get("acceleration")),
    }
    aligned = opposed = 0
    states = {}
    for name, val in vals.items():
        if val is None or sign == 0:
            states[name] = "N/A"
            continue
        score = sign * val
        if score >= (0.08 if name != "acceleration" else 0.05):
            states[name] = "ALIGNED"; aligned += 1
        elif score <= (-0.12 if name != "acceleration" else -0.08):
            states[name] = "OPPOSED"; opposed += 1
        else:
            states[name] = "NEUTRAL"
    state = "ALIGNED" if aligned >= 2 and opposed == 0 else "CONFLICTING" if opposed >= 1 and aligned >= 1 else "OPPOSED" if opposed >= 2 else "NEUTRAL"
    return {"state": state, "aligned": aligned, "opposed": opposed, "frames": states}


def _opening_auction(raw: dict, session: str) -> dict:
    op = _f(raw.get("open"))
    prev = _f(raw.get("prev_day_close") or raw.get("previous_close") or raw.get("prev_close"))
    ltp = _f(raw.get("ltp"))
    gap = ((op - prev) / abs(prev) * 100.0) if op and prev else None
    hold = ((ltp - op) / abs(op) * 100.0) if ltp and op else None
    state = "N/A"
    side = "WAIT"
    if session in ("PREOPEN", "OPENING_5", "OPENING_15"):
        if gap is not None and gap >= .35 and (hold is None or hold >= -.12):
            state, side = "GAP-UP HOLD", "CE"
        elif gap is not None and gap <= -.35 and (hold is None or hold <= .12):
            state, side = "GAP-DOWN HOLD", "PE"
        elif gap is not None and abs(gap) >= .35:
            state = "GAP FADE / CONFLICT"
        else:
            state = "BALANCED OPEN"
    return {"state": state, "side": side, "gap_pct": round(gap, 3) if gap is not None else None, "from_open_pct": round(hold, 3) if hold is not None else None}


def _history(sym: str) -> List[dict]:
    with _LOCK:
        return list(_TIMING_STATE.get(sym) or [])


def _false_breakout(sym: str, side: str, px: float, trigger: Optional[float], depth: dict, row: dict) -> dict:
    if side not in ("CE", "PE") or not trigger or not px:
        return {"state": "NONE", "detected": False}
    hist = [x for x in _history(sym) if time.time() - x.get("t", 0) <= 120 and _f(x.get("px")) is not None]
    crossed = False
    if side == "CE":
        crossed = any((_f(x.get("px"), 0) or 0) >= trigger * 1.0005 for x in hist)
        failed = crossed and px <= trigger * 0.999 and ((_f(row.get("velocity_15s"), 0) or 0) < 0 or (_f(depth.get("pressure"), 50) or 50) < 46)
        return {"state": "FAILED UPSIDE BREAKOUT" if failed else "CROSS TEST" if crossed else "NONE", "detected": bool(failed), "trap_side": "BEAR" if failed else None}
    crossed = any((_f(x.get("px"), 10**18) or 10**18) <= trigger * 0.9995 for x in hist)
    failed = crossed and px >= trigger * 1.001 and ((_f(row.get("velocity_15s"), 0) or 0) > 0 or (_f(depth.get("pressure"), 50) or 50) > 54)
    return {"state": "FAILED DOWNSIDE BREAKOUT" if failed else "CROSS TEST" if crossed else "NONE", "detected": bool(failed), "trap_side": "BULL" if failed else None}


def _crowding(row: dict, side: str) -> dict:
    cp = abs(_f(row.get("change_pct"), 0.0) or 0.0)
    rv = _f(row.get("rvol"))
    v15 = abs(_f(row.get("velocity_15s"), 0.0) or 0.0)
    v60 = abs(_f(row.get("velocity_60s"), 0.0) or 0.0)
    spread = _f((row.get("depth_intelligence") or {}).get("spread_pct"))
    decay = _f(row.get("opportunity_decay"), 0.0) or 0.0
    score = decay * .55
    if cp > 1.8: score += min(24, (cp - 1.8) * 9)
    if rv is not None and rv > 3.2: score += min(18, (rv - 3.2) * 6)
    if v60 > .35 and v15 < v60 * .48: score += 12
    if spread is not None and spread > .65: score += 8
    score = _clamp(score)
    state = "CLEAN" if score < 28 else "CROWDED" if score < 55 else "LATE" if score < 75 else "EXHAUSTED"
    return {"score": round(score, 1), "state": state, "do_not_chase": state in ("LATE", "EXHAUSTED")}


def _reentry(sym: str, side: str, px: float, trigger: Optional[float], depth: dict, row: dict) -> dict:
    hist = [x for x in _history(sym) if time.time() - x.get("t", 0) <= 300 and _f(x.get("px")) is not None]
    if side not in ("CE", "PE") or len(hist) < 3 or not px:
        return {"state": "NONE", "score": 0}
    prices = [_f(x.get("px")) for x in hist if _f(x.get("px")) is not None]
    dp = _f(depth.get("pressure"), 50) or 50
    v15 = _f(row.get("velocity_15s"), 0.0) or 0.0
    score = 0.0
    if side == "CE":
        peak = max(prices)
        pullback = (peak - px) / max(peak, 1e-9) * 100
        if .25 <= pullback <= 1.10: score += 45
        if trigger and abs(px - trigger) / trigger * 100 <= .40: score += 25
        if dp >= 55: score += 18
        if v15 >= -.05: score += 12
    else:
        trough = min(prices)
        pullback = (px - trough) / max(trough, 1e-9) * 100
        if .25 <= pullback <= 1.10: score += 45
        if trigger and abs(px - trigger) / trigger * 100 <= .40: score += 25
        if dp <= 45: score += 18
        if v15 <= .05: score += 12
    score = _clamp(score)
    state = "RE-ENTRY READY" if score >= 78 else "RE-ENTRY ARMING" if score >= 58 else "WAIT RETRACEMENT" if score >= 35 else "NONE"
    return {"state": state, "score": round(score, 1), "policy": "re-entry only after evidence-supported pullback/retest; never averaging down"}


def _conflict_matrix(row: dict, multi_tf: dict, false_breakout: dict, crowd: dict) -> dict:
    ev = row.get("directional_evidence") or {}
    aligned = int(ev.get("aligned_groups") or 0)
    opposed = int(ev.get("opposed_groups") or 0)
    reasons = []
    if opposed: reasons.append(f"{opposed} independent opposing groups")
    if multi_tf.get("state") == "CONFLICTING": reasons.append("multi-timeframe conflict")
    if multi_tf.get("state") == "OPPOSED": reasons.append("multi-timeframe opposition")
    if false_breakout.get("detected"): reasons.append(false_breakout.get("state"))
    if crowd.get("state") in ("LATE", "EXHAUSTED"): reasons.append("crowding/exhaustion")
    severity = "HIGH" if false_breakout.get("detected") or opposed >= 2 or multi_tf.get("state") == "OPPOSED" else "MEDIUM" if reasons else "LOW"
    decision = "BLOCK" if severity == "HIGH" else "WARN" if severity == "MEDIUM" else "ALLOW"
    return {"severity": severity, "decision": decision, "aligned": aligned, "opposed": opposed, "reasons": reasons[:6]}


def signal_forensics(minutes: int = 390, follow_through_pct: float = .70, adverse_pct: float = .55) -> dict:
    """Observed-outcome audit of stored V72 events; not a predictive win-rate claim."""
    cutoff = time.time() - max(30, int(minutes)) * 60
    try:
        with v721._db() as c:
            ev = [dict(x) for x in c.execute(
                "SELECT epoch,symbol,stage,side,score,price,trigger_price FROM premove_events_v72 WHERE epoch>=? AND stage IN ('ARMING','TRIGGER READY','MOVE STARTED') ORDER BY symbol,epoch",
                (cutoff,),
            )]
            snaps = [dict(x) for x in c.execute(
                "SELECT epoch,symbol,ltp FROM premove_snapshots_v72 WHERE epoch>=? ORDER BY symbol,epoch",
                (cutoff,),
            )]
    except Exception as exc:
        return {"status": "UNAVAILABLE", "reason": str(exc), "sample_size": 0}
    by_ev: Dict[str, List[dict]] = defaultdict(list)
    by_snap: Dict[str, List[dict]] = defaultdict(list)
    for x in ev: by_ev[str(x.get("symbol"))].append(x)
    for x in snaps: by_snap[str(x.get("symbol"))].append(x)
    outcomes = []
    for sym, events in by_ev.items():
        # First early event per symbol in window avoids duplicate stage promotions inflating stats.
        e = next((x for x in events if x.get("side") in ("CE", "PE") and _f(x.get("price"))), None)
        if not e: continue
        p0 = _f(e.get("price")); t0 = _f(e.get("epoch")); sign = 1 if e.get("side") == "CE" else -1
        if not p0 or not t0: continue
        result = "OPEN"
        target_min = adverse_min = None
        best = worst = 0.0
        for s in by_snap.get(sym, []):
            ts = _f(s.get("epoch")); p = _f(s.get("ltp"))
            if ts is None or p is None or ts <= t0 or ts - t0 > 90 * 60: continue
            ex = (p - p0) / p0 * 100 * sign
            best = max(best, ex); worst = min(worst, ex)
            if target_min is None and ex >= follow_through_pct:
                target_min = (ts - t0) / 60
                if adverse_min is None: result = "FOLLOW_THROUGH"
                break
            if adverse_min is None and ex <= -adverse_pct:
                adverse_min = (ts - t0) / 60
                result = "FALSE_POSITIVE"
                break
        if result == "OPEN":
            result = "NO_FOLLOW_THROUGH" if best < follow_through_pct else "FOLLOW_THROUGH"
        outcomes.append({
            "symbol": sym, "side": e.get("side"), "stage": e.get("stage"), "score": e.get("score"),
            "result": result, "best_excursion_pct": round(best, 3), "worst_excursion_pct": round(worst, 3),
            "minutes_to_target": round(target_min, 1) if target_min is not None else None,
        })
    resolved = [x for x in outcomes if x["result"] in ("FOLLOW_THROUGH", "FALSE_POSITIVE", "NO_FOLLOW_THROUGH")]
    hits = sum(1 for x in resolved if x["result"] == "FOLLOW_THROUGH")
    false = sum(1 for x in resolved if x["result"] == "FALSE_POSITIVE")
    no_follow = sum(1 for x in resolved if x["result"] == "NO_FOLLOW_THROUGH")
    times = [x["minutes_to_target"] for x in resolved if x.get("minutes_to_target") is not None]
    n = len(resolved)
    return {
        "status": "READY", "minutes": minutes, "sample_size": n, "follow_through": hits,
        "false_positive": false, "no_follow_through": no_follow,
        "observed_follow_through_rate_pct": round(100 * hits / n, 1) if n else None,
        "observed_false_positive_rate_pct": round(100 * false / n, 1) if n else None,
        "median_minutes_to_target": round(statistics.median(times), 1) if times else None,
        "outcomes": outcomes[:100],
        "policy": "Historical observed follow-through audit only. It is not a forward accuracy or profit guarantee.",
    }


def _forensics_cached() -> dict:
    now = time.time()
    with _LOCK:
        if _FORENSICS_CACHE.get("value") is not None and now - _FORENSICS_CACHE.get("epoch", 0) < 30:
            return _FORENSICS_CACHE["value"]
    out = signal_forensics(390)
    with _LOCK:
        _FORENSICS_CACHE.update({"epoch": now, "value": out})
    return out


def _calibration_profile() -> dict:
    """Bounded threshold tuning from observed outcomes; max +/-3 points."""
    global _LAST_CALIBRATION_LOG
    now = time.time()
    with _LOCK:
        if _CALIBRATION_CACHE.get("value") is not None and now - _CALIBRATION_CACHE.get("epoch", 0) < 60:
            return _CALIBRATION_CACHE["value"]
    f = _forensics_cached()
    n = int(f.get("sample_size") or 0)
    hit = _f(f.get("observed_follow_through_rate_pct"))
    fp = _f(f.get("observed_false_positive_rate_pct"))
    early_shift = confirmed_shift = 0
    reason = "insufficient sample; defaults retained"
    if n >= 20:
        if fp is not None and fp >= 45:
            early_shift, confirmed_shift, reason = 3, 3, "false-positive rate elevated; tighten both gates"
        elif fp is not None and fp >= 35:
            early_shift, confirmed_shift, reason = 2, 2, "false-positive rate elevated; modest tightening"
        elif hit is not None and hit >= 70 and (fp or 100) <= 20:
            early_shift, confirmed_shift, reason = -2, -1, "stable observed follow-through; allow slightly earlier entry"
    profile = {
        "sample_size": n, "early_threshold_shift": int(max(-3, min(3, early_shift))),
        "confirmed_threshold_shift": int(max(-3, min(3, confirmed_shift))), "reason": reason,
        "bounded": True, "max_shift_points": 3,
    }
    # Log infrequently for auditability; failure must never block market analytics.
    if n >= 20 and now - _LAST_CALIBRATION_LOG >= 900:
        try:
            with v721._db() as c:
                c.execute("CREATE TABLE IF NOT EXISTS calibration_v722(epoch REAL, early_shift INTEGER, confirmed_shift INTEGER, sample_size INTEGER, hit_rate REAL, false_positive_rate REAL, reason TEXT)")
                c.execute("INSERT INTO calibration_v722 VALUES(?,?,?,?,?,?,?)", (now, profile["early_threshold_shift"], profile["confirmed_threshold_shift"], n, hit, fp, reason))
                c.commit()
            _LAST_CALIBRATION_LOG = now
        except Exception:
            pass
    with _LOCK:
        _CALIBRATION_CACHE.update({"epoch": now, "value": profile})
    return profile


def _trigger_countdown(row: dict, multi_tf: dict, conflict: dict, crowd: dict, session: str) -> dict:
    base = _f(row.get("pre_move_score"), 0.0) or 0.0
    pers = row.get("persistence") or {}
    stable = _f(pers.get("score_stability")); evp = _f(pers.get("evidence_persistence"))
    aligned = int((row.get("directional_evidence") or {}).get("aligned_groups") or 0)
    side = row.get("v72_side")
    px = _f(row.get("ltp")); trig = _f(row.get("breakout_trigger"))
    score = base * .72 + aligned * 3.2
    if stable is not None: score += max(-5, min(8, (stable - 55) * .16))
    if evp is not None: score += max(-4, min(8, (evp - 55) * .15))
    if multi_tf.get("state") == "ALIGNED": score += 6
    elif multi_tf.get("state") in ("CONFLICTING", "OPPOSED"): score -= 7
    if trig and px:
        dist = abs(trig - px) / px * 100
        score += 9 if dist <= .15 else 6 if dist <= .35 else 3 if dist <= .70 else -3 if dist > 1.5 else 0
    if crowd.get("state") == "CROWDED": score -= 8
    elif crowd.get("state") in ("LATE", "EXHAUSTED"): score -= 20
    if conflict.get("decision") == "BLOCK": score -= 18
    elif conflict.get("decision") == "WARN": score -= 7
    if session == "OPENING_5": score += 3  # speed mode, freshness gate remains strict later
    if session in ("CLOSED", "PREOPEN"): score = min(score, 69)
    score = _clamp(score)
    state = "TRIGGER READY" if score >= 86 and side in ("CE", "PE") else "ARMING" if score >= 72 and side in ("CE", "PE") else "BUILDING" if score >= 58 else "WATCH"
    sym = str(row.get("symbol") or "")
    prev = None
    hist = _history(sym)
    if hist: prev = _f(hist[-1].get("countdown"))
    trend = None if prev is None else round(score - prev, 1)
    return {"score": int(round(score)), "state": state, "delta": trend, "previous": round(prev, 1) if prev is not None else None}


def _fast_signal_722(row: dict) -> dict:
    side = row.get("v72_side")
    session = row.get("session_mode") or "NORMAL"
    countdown = int((row.get("trigger_countdown_detail") or {}).get("score") or 0)
    age = _f(row.get("quote_age_sec"), 999.0) or 999.0
    aligned = int((row.get("directional_evidence") or {}).get("aligned_groups") or 0)
    opposed = int((row.get("directional_evidence") or {}).get("opposed_groups") or 0)
    conflict = row.get("conflict_matrix") or {}
    crowd = row.get("crowding") or {}
    pers = row.get("persistence") or {}
    ep = _f(pers.get("evidence_persistence")); stable = _f(pers.get("score_stability")); samples = int(pers.get("samples") or 0)
    spread = _f((row.get("depth_intelligence") or {}).get("spread_pct"))
    calibration = _calibration_profile()
    early_thr = 66 + calibration["early_threshold_shift"]
    conf_thr = 78 + calibration["confirmed_threshold_shift"]
    if session == "OPENING_5":
        early_thr -= 3; conf_thr -= 2
    freshness_limit = 5 if session == "OPENING_5" else 10
    freshness = age <= freshness_limit
    spread_ok = spread is None or spread <= .65
    persistence_ok = samples < 2 or ep is None or ep >= 60
    stability_ok = samples < 3 or stable is None or stable >= 58
    base_ok = side in ("CE", "PE") and freshness and spread_ok and not row.get("late_entry") and crowd.get("state") not in ("LATE", "EXHAUSTED") and conflict.get("decision") != "BLOCK" and session not in ("CLOSED", "PREOPEN")
    tier = "NONE"; action = "WAIT"
    if base_ok and countdown >= early_thr and aligned >= 4 and opposed <= 1 and persistence_ok:
        tier, action = "EARLY", f"EARLY {side}"
    confirmed_persistence = (samples >= 2 and (ep or 0) >= 66) or aligned >= 6
    if base_ok and countdown >= conf_thr and aligned >= 5 and opposed <= 1 and persistence_ok and stability_ok and confirmed_persistence:
        tier, action = "CONFIRMED", f"BUY {side}"
    return {
        "tier": tier, "action": action, "countdown": countdown, "early_threshold": early_thr, "confirmed_threshold": conf_thr,
        "freshness_pass": freshness, "spread_pass": spread_ok, "persistence_pass": persistence_ok, "stability_pass": stability_ok,
        "aligned_groups": aligned, "opposed_groups": opposed, "session_mode": session, "calibration": calibration,
        "policy": "EARLY optimizes lead-time; BUY requires fresh, stable, independent evidence. No guaranteed accuracy percentage.",
    }


def _alert_priority(row: dict) -> dict:
    fs = row.get("fast_signal") or {}
    tier = fs.get("tier")
    stage = row.get("pre_move_stage")
    if tier == "CONFIRMED" or stage == "TRIGGER READY":
        p = "P1"; label = "TRIGGER READY"
    elif tier == "EARLY" or stage == "ARMING":
        p = "P2"; label = "ARMING"
    else:
        p = "P3"; label = "WATCH"
    return {"priority": p, "label": label, "notify": p in ("P1", "P2")}


def _enrich_rows(rows: List[dict], snapshot: dict) -> List[dict]:
    now = time.time()
    session = _session_mode(now)["mode"]
    raw_map = {str(x.get("symbol") or "").upper(): x for x in (snapshot.get("sector_heatmap") or []) if isinstance(x, dict)}
    enriched = []
    for base in rows:
        r = dict(base)
        sym = str(r.get("symbol") or "")
        side = r.get("v72_side")
        px = _f(r.get("ltp"), 0.0) or 0.0
        trigger = _f(r.get("breakout_trigger"))
        depth = r.get("depth_intelligence") or {}
        mtf = _multi_tf_alignment(r, side)
        crowd = _crowding(r, side)
        fb = _false_breakout(sym, side, px, trigger, depth, r)
        reentry = _reentry(sym, side, px, trigger, depth, r)
        conflict = _conflict_matrix(r, mtf, fb, crowd)
        auction = _opening_auction(raw_map.get(sym, {}), session)
        r.update({
            "session_mode": session, "opening_auction": auction, "multi_tf_alignment": mtf,
            "false_breakout": fb, "reentry": reentry, "crowding": crowd, "conflict_matrix": conflict,
        })
        cd = _trigger_countdown(r, mtf, conflict, crowd, session)
        r["trigger_countdown_detail"] = cd
        r["trigger_countdown"] = cd["score"]
        # Promote/demote stage using timing layer without erasing V72.1's original stage.
        r["base_pre_move_stage"] = r.get("pre_move_stage")
        if not r.get("late_entry") and side in ("CE", "PE"):
            if cd["state"] == "TRIGGER READY": r["pre_move_stage"] = "TRIGGER READY"
            elif cd["state"] == "ARMING" and r.get("pre_move_stage") not in ("TRIGGER READY",): r["pre_move_stage"] = "ARMING"
        if fb.get("detected"):
            r["pre_move_stage"] = "FAILED / REVERSAL WATCH"
        if crowd.get("do_not_chase") and r.get("pre_move_stage") == "TRIGGER READY":
            r["pre_move_stage"] = "MOVE ACTIVE / DO NOT CHASE"
        # V72.2 move quality is execution-oriented.
        if r.get("late_entry") or crowd.get("state") in ("LATE", "EXHAUSTED"):
            r["move_quality"] = crowd.get("state")
        elif r.get("pre_move_stage") in ("ARMING", "TRIGGER READY"):
            r["move_quality"] = "CLEAN"
        else:
            r["move_quality"] = "EARLY"
        r["fast_signal"] = _fast_signal_722(r)
        r["alert"] = _alert_priority(r)
        if fb.get("detected"):
            r.setdefault("v72_counter_evidence", []).append(fb.get("state"))
        if reentry.get("state") in ("RE-ENTRY ARMING", "RE-ENTRY READY"):
            r.setdefault("v72_evidence", []).append(reentry.get("state"))
        if auction.get("side") == side and auction.get("state") != "N/A":
            r.setdefault("v72_evidence", []).append(auction.get("state"))
        with _LOCK:
            h = _TIMING_STATE[sym]
            if not h or now - h[-1].get("t", 0) >= 1.0:
                h.append({"t": now, "px": px, "countdown": cd["score"], "side": side, "stage": r.get("pre_move_stage"), "score": r.get("pre_move_score")})
        enriched.append(r)
    pr = {"P1": 4, "P2": 3, "P3": 2}
    enriched.sort(key=lambda x: (pr.get((x.get("alert") or {}).get("priority"), 1), (x.get("trigger_countdown_detail") or {}).get("score", 0), x.get("pre_move_score", 0)), reverse=True)
    return enriched


def _alert_queue(rows: List[dict]) -> dict:
    global _LAST_BEST
    candidates = [x for x in rows if (x.get("alert") or {}).get("priority") in ("P1", "P2") and x.get("v72_side") in ("CE", "PE")]
    queue = []
    now = time.time()
    for r in candidates[:12]:
        sig = f"{r.get('symbol')}:{r.get('v72_side')}:{(r.get('alert') or {}).get('priority')}"
        prev_seen = next((x for x in reversed(_history(str(r.get("symbol") or ""))) if x.get("signature") == sig), None)
        queue.append({
            "symbol": r.get("symbol"), "side": r.get("v72_side"), "priority": (r.get("alert") or {}).get("priority"),
            "stage": r.get("pre_move_stage"), "countdown": r.get("trigger_countdown"), "score": r.get("pre_move_score"),
            "duplicate_suppressed": bool(prev_seen and now - prev_seen.get("t", 0) < 45),
        })
    best = queue[0] if queue else None
    replacement = None
    if best:
        signature = f"{best['symbol']}:{best['side']}:{best['priority']}"
        if _LAST_BEST.get("signature") and _LAST_BEST.get("signature") != signature:
            replacement = {"replaced": _LAST_BEST.get("signature"), "new": signature, "reason": "higher current timing/execution priority"}
        _LAST_BEST = {"signature": signature, "score": best.get("score"), "epoch": now}
        # store signature on symbol history for duplicate detection
        with _LOCK:
            h = _TIMING_STATE[str(best["symbol"])]
            if h: h[-1]["signature"] = signature
    return {"queue": queue, "replacement": replacement, "counts": {p: sum(1 for x in queue if x["priority"] == p) for p in ("P0", "P1", "P2", "P3")}}


def pre_move_radar(snapshot: dict, record: bool = True) -> dict:
    t0 = time.perf_counter()
    base = v721.pre_move_radar(snapshot, record=record)
    rows = _enrich_rows(base.get("rows") or [], snapshot)
    alerts = _alert_queue(rows)
    out = dict(base)
    out.update({
        "version": "72.2", "release": "72.2-timing-execution", "rows": rows, "top": rows[:40],
        "trigger_ready": [x for x in rows if x.get("pre_move_stage") == "TRIGGER READY"],
        "arming": [x for x in rows if x.get("pre_move_stage") == "ARMING"],
        "building": [x for x in rows if x.get("pre_move_stage") in ("BUILDING", "EARLY CLUE")],
        "late": [x for x in rows if x.get("late_entry") or (x.get("crowding") or {}).get("do_not_chase")],
        "fast_confirmed": [x for x in rows if (x.get("fast_signal") or {}).get("tier") == "CONFIRMED"],
        "fast_early": [x for x in rows if (x.get("fast_signal") or {}).get("tier") == "EARLY"],
        "alert_center": alerts, "session": _session_mode(), "scan_ms": round((time.perf_counter() - t0) * 1000, 2),
    })
    return out


def _latency_guard(snapshot: dict, rows: List[dict], scan_ms: float, decision_ms: float, total_ms: float) -> dict:
    base = v721._latency_guard(snapshot, rows)
    best_age = min([_f(x.get("quote_age_sec")) for x in rows if _f(x.get("quote_age_sec")) is not None], default=None)
    alert_lag = (best_age + total_ms / 1000.0) if best_age is not None else None
    state = base.get("state")
    if total_ms > 2500 and state == "LIVE": state = "PROCESSING SLOW"
    base.update({
        "state": state, "scanner_lag_ms": round(scan_ms, 2), "decision_lag_ms": round(decision_ms, 2),
        "total_pipeline_ms": round(total_ms, 2), "best_alert_lag_sec": round(alert_lag, 2) if alert_lag is not None else None,
        "guard_pass": state not in ("STALE", "DELAYED") and (alert_lag is None or alert_lag <= 12),
    })
    return base


def ai_brain(snapshot: dict, radar: Optional[dict] = None) -> dict:
    radar = radar or pre_move_radar(snapshot, record=False)
    rows = radar.get("rows") or []
    confirmed = [x for x in rows if (x.get("fast_signal") or {}).get("tier") == "CONFIRMED"]
    early = [x for x in rows if (x.get("fast_signal") or {}).get("tier") == "EARLY"]
    best = (confirmed or early or [x for x in rows if x.get("pre_move_stage") in ("TRIGGER READY", "ARMING")] or [None])[0]
    if not best:
        return {
            "name": "AI Brain 3.2 Timing + Execution", "action": "WAIT", "state": "SCANNING", "confidence": 0,
            "signal_tier": "NONE", "best_candidate": None, "why_not": ["No fresh timing-qualified candidate"],
            "session_mode": (radar.get("session") or {}).get("mode"), "thesis_lock": "One active directional thesis; verified flip invalidates the old thesis.",
        }
    fs = best.get("fast_signal") or {}
    conflict = best.get("conflict_matrix") or {}
    countdown = int(best.get("trigger_countdown") or 0)
    conf = _clamp(countdown - (_f(best.get("opportunity_decay"), 0) or 0) * .12 - (8 if conflict.get("severity") == "MEDIUM" else 18 if conflict.get("severity") == "HIGH" else 0))
    action = fs.get("action") or "WAIT"
    if conflict.get("decision") == "BLOCK" or (best.get("crowding") or {}).get("do_not_chase"):
        action = "WAIT"
    why = []
    if conflict.get("decision") != "ALLOW": why += conflict.get("reasons") or []
    if (best.get("crowding") or {}).get("do_not_chase"): why.append("MOVE ALREADY ACTIVE — DO NOT CHASE")
    if fs.get("tier") == "EARLY": why.append("EARLY signal; confirmation still pending")
    return {
        "name": "AI Brain 3.2 Timing + Execution", "action": action,
        "state": "FAST CONFIRMED" if fs.get("tier") == "CONFIRMED" else "FAST EARLY" if fs.get("tier") == "EARLY" else best.get("pre_move_stage"),
        "confidence": round(conf, 1), "signal_tier": fs.get("tier"), "fast_signal": fs, "best_candidate": best,
        "session_mode": best.get("session_mode"), "trigger_countdown": best.get("trigger_countdown_detail"),
        "alert_priority": best.get("alert"), "conflict_matrix": conflict, "reentry": best.get("reentry"), "crowding": best.get("crowding"),
        "why_not": why[:8], "thesis_lock": "One active directional thesis; verified flip invalidates the old thesis.",
        "driver_policy": "Timing layer favors early persistent evidence, blocks stale/conflicted/crowded setups, and supports evidence-based re-entry without averaging down.",
    }


def _expiry_mode(expiry: Any) -> dict:
    if not expiry:
        return {"mode": "UNKNOWN", "days": None, "gamma_weight": 1.0, "theta_weight": 1.0}
    text = str(expiry)[:10]
    try:
        d = datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        try:
            d = datetime.fromisoformat(str(expiry).replace("Z", "+00:00")).date()
        except Exception:
            return {"mode": "UNKNOWN", "days": None, "gamma_weight": 1.0, "theta_weight": 1.0}
    today = datetime.now(IST).date()
    days = (d - today).days
    if days <= 0: mode, gw, tw = "EXPIRY GAMMA", 1.35, 1.35
    elif days == 1: mode, gw, tw = "NEXT-DAY GAMMA", 1.22, 1.22
    elif days <= 3: mode, gw, tw = "SHORT-DATED", 1.12, 1.12
    else: mode, gw, tw = "NORMAL", 1.0, 1.0
    return {"mode": mode, "days": days, "gamma_weight": gw, "theta_weight": tw}


def predictive_strike_selector(symbol: str, underlying: dict, chain_payload: dict) -> dict:
    base = v721.predictive_strike_selector(symbol, underlying, chain_payload)
    expiry = _expiry_mode(chain_payload.get("expiry"))
    direction = base.get("direction")
    uvel = _f(underlying.get("velocity_15s"), 0.0) or 0.0
    enhanced = []
    now = time.time()
    for c0 in base.get("top_candidates") or []:
        c = dict(c0)
        key = str(c.get("contract_key") or f"{symbol}:{c.get('strike')}:{c.get('side')}")
        premium = _f(c.get("premium"), 0.0) or 0.0
        pv = _f(c.get("premium_velocity"))
        theta = abs(_f(c.get("theta"), 0.0) or 0.0)
        gamma = abs(_f(c.get("gamma"), 0.0) or 0.0)
        iv = _f(c.get("iv"))
        side = c.get("side")
        underlying_impulse = (uvel >= .12 and side == "CE") or (uvel <= -.12 and side == "PE")
        response_pass = (pv is None) or (not underlying_impulse) or pv >= .02
        theta_pct = theta / max(premium, 1.0) * 100
        theta_danger = theta_pct * expiry["theta_weight"]
        iv_state = "NORMAL" if iv is None or iv <= 65 else "ELEVATED" if iv <= 90 else "OVERPRICED RISK"
        score = _f(c.get("score"), 0.0) or 0.0
        if response_pass and underlying_impulse: score += 5
        if not response_pass: score -= 14
        if gamma > 0: score += min(5, gamma * max(_f(base.get("spot"), 1) or 1, 1) * 120 * expiry["gamma_weight"])
        if theta_danger > 4: score -= min(10, (theta_danger - 4) * 1.5)
        if iv_state == "OVERPRICED RISK": score -= 6
        score = _clamp(score)
        eligible = bool(c.get("eligible")) and response_pass and theta_danger <= 9 and iv_state != "OVERPRICED RISK"
        with _LOCK:
            h = _OPTION_EXEC_STATE[key]
            if not h or now - h[-1]["t"] >= 1:
                h.append({"t": now, "premium": premium, "score": score})
            hist = list(h)
        peak = max([_f(x.get("premium"), premium) or premium for x in hist], default=premium)
        trail_floor = peak * (0.84 if expiry["mode"] == "EXPIRY GAMMA" else 0.82)
        c.update({
            "score": round(score, 1), "eligible": eligible, "premium_response_pass": response_pass,
            "theta_danger_score": round(_clamp(theta_danger * 10), 1), "iv_state": iv_state,
            "expiry_mode": expiry, "premium_peak": round(peak, 2), "dynamic_trail_floor": round(trail_floor, 2),
        })
        enhanced.append(c)
    enhanced.sort(key=lambda x: (x.get("eligible") is True, _f(x.get("score"), 0) or 0), reverse=True)
    winner = next((x for x in enhanced if x.get("eligible") and x.get("side") == direction and _f(x.get("premium"), 0) >= 50), None)
    same = [x for x in enhanced if x.get("side") == direction and _f(x.get("steps_from_atm"), 99) <= 1.6]
    responsive = sum(1 for x in same if x.get("premium_response_pass") and ((_f(x.get("premium_velocity"), 0) or 0) > .10 or (_f(x.get("oi_change"), 0) or 0) > 0 or (_f(x.get("volume"), 0) or 0) > 0))
    multi = responsive >= 2 if len(same) >= 2 else False
    state = "NO TRADE"
    if winner:
        score = _f(winner.get("score"), 0) or 0
        pv = _f(winner.get("premium_velocity"), 0) or 0
        if score >= 86 and multi:
            state = "HERO CALL" if direction == "CE" else "HERO PUT"
        elif score >= 76:
            state = "TRIGGER READY CALL" if direction == "CE" else "TRIGGER READY PUT"
        move_stage = "IGNITION" if pv > .25 else "HERO READY" if score >= 86 else "TRIGGER READY"
        if pv > 1.5: move_stage = "EXPANSION"
        if winner.get("theta_danger_score", 0) >= 70 or winner.get("iv_state") == "OVERPRICED RISK": move_stage = "EXIT RISK"
        winner = dict(winner)
        winner["move_capture_stage"] = move_stage
        winner["alert_priority"] = "P0" if state.startswith("HERO") else "P1"
    why = list(base.get("why_not_hero") or [])
    if winner and not winner.get("premium_response_pass"): why.append("underlying moved but premium response failed")
    if winner and winner.get("iv_state") == "OVERPRICED RISK": why.append("IV overpricing risk")
    if winner and winner.get("theta_danger_score", 0) >= 70: why.append("theta danger elevated")
    if winner and not multi: why.append("multi-strike confirmation incomplete")
    return {
        **base, "version": "72.2", "release": "72.2-timing-execution", "expiry_mode": expiry,
        "top_candidates": enhanced[:16], "winner": winner, "hero_state": state, "multi_strike_confirmation": multi,
        "why_not_hero": list(dict.fromkeys(why))[:10],
        "execution_policy": "Reject non-responsive premiums, excessive theta/IV risk and poor liquidity; expiry-day mode increases gamma/theta sensitivity. Read-only analytics only.",
    }


def predictive_chart_intelligence(candles: List[Any], symbol: str, interval: int, snapshot: dict, census_row: Optional[dict] = None) -> dict:
    out = v721.predictive_chart_intelligence(candles, symbol, interval, snapshot, census_row)
    if out.get("status") != "READY": return out
    cs = v721._norm_candles(candles)
    if not cs: return out
    closes = [x["close"] for x in cs]
    # Multi-timeframe proxy from candle horizons: 3, 6, 12 bars. This is not a separate feed.
    def ret(n):
        if len(closes) <= n or closes[-n-1] == 0: return None
        return (closes[-1] - closes[-n-1]) / abs(closes[-n-1]) * 100
    r3, r6, r12 = ret(3), ret(6), ret(12)
    side = out.get("side")
    sign = 1 if side == "CE" else -1 if side == "PE" else 0
    aligned = sum(1 for r in (r3, r6, r12) if r is not None and sign * r > .05)
    opposed = sum(1 for r in (r3, r6, r12) if r is not None and sign * r < -.08)
    mtf = {"3bar": r3, "6bar": r6, "12bar": r12, "aligned": aligned, "opposed": opposed, "state": "ALIGNED" if aligned >= 2 and opposed == 0 else "CONFLICTING" if aligned and opposed else "NEUTRAL"}
    out = dict(out)
    out.update({"version": "72.2", "multi_timeframe_trigger": mtf})
    if mtf["state"] == "ALIGNED": out["score"] = round(_clamp((_f(out.get("score"), 0) or 0) + 5), 1)
    if mtf["state"] == "CONFLICTING":
        out["score"] = round(_clamp((_f(out.get("score"), 0) or 0) - 7), 1)
        out.setdefault("counter_evidence", []).append("multi-timeframe chart conflict")
    return out


def lead_time_audit(minutes: int = 390, threshold_pct: float = 1.25) -> dict:
    base = v721.lead_time_audit(minutes, threshold_pct)
    return {**base, "version": "72.2", "signal_quality": _forensics_cached(), "calibration": _calibration_profile()}


def replay_timeline(symbol: str, minutes: int = 390) -> dict:
    cutoff = time.time() - max(30, int(minutes)) * 60
    sym = str(symbol or "").upper().strip()
    try:
        with v721._db() as c:
            snaps = [dict(x) for x in c.execute("SELECT epoch,symbol,ltp,side,stage,premove_score,depth_pressure,relative_strength,opportunity_decay,quote_age_sec FROM premove_snapshots_v72 WHERE symbol=? AND epoch>=? ORDER BY epoch", (sym, cutoff))]
            ev = [dict(x) for x in c.execute("SELECT epoch,symbol,event_type,stage,side,score,price,trigger_price FROM premove_events_v72 WHERE symbol=? AND epoch>=? ORDER BY epoch", (sym, cutoff))]
    except Exception as exc:
        return {"status": "UNAVAILABLE", "symbol": sym, "reason": str(exc)}
    return {"status": "READY", "version": "72.2", "symbol": sym, "minutes": minutes, "snapshots": snaps[-500:], "events": ev[-100:], "policy": "Historical replay only; no look-ahead data is inserted into prior snapshots."}


def build_v72(snapshot: dict, record: bool = True) -> dict:
    t0 = time.perf_counter()
    base = v721.build_v72(snapshot, record=record)
    t1 = time.perf_counter()
    rows = _enrich_rows(list(base.get("pre_move_rows") or []), snapshot)
    alerts = _alert_queue(rows)
    radar_base = dict(base.get("pre_move_radar") or {})
    radar_base.update({
        "version": "72.2", "release": "72.2-timing-execution",
        "trigger_ready": [x for x in rows if x.get("pre_move_stage") == "TRIGGER READY"],
        "arming": [x for x in rows if x.get("pre_move_stage") == "ARMING"],
        "fast_confirmed": [x for x in rows if (x.get("fast_signal") or {}).get("tier") == "CONFIRMED"],
        "fast_early": [x for x in rows if (x.get("fast_signal") or {}).get("tier") == "EARLY"],
        "alert_center": alerts, "session": _session_mode(),
    })
    radar_full = {**radar_base, "rows": rows}
    brain = ai_brain(snapshot, radar_full)
    t2 = time.perf_counter()
    total_ms = (t2 - t0) * 1000
    scan_ms = (t1 - t0) * 1000
    decision_ms = (t2 - t1) * 1000
    latency = _latency_guard(snapshot, rows, scan_ms, decision_ms, total_ms)
    quality = _forensics_cached()
    calibration = _calibration_profile()
    cc = dict(base.get("command_center") or {})
    cc.update({
        "session_mode": (radar_base.get("session") or {}).get("mode"),
        "p0": alerts["counts"].get("P0", 0), "p1": alerts["counts"].get("P1", 0), "p2": alerts["counts"].get("P2", 0),
        "reentry_ready": sum(1 for x in rows if (x.get("reentry") or {}).get("state") == "RE-ENTRY READY"),
        "crowded": sum(1 for x in rows if (x.get("crowding") or {}).get("state") in ("CROWDED", "LATE", "EXHAUSTED")),
        "false_breakouts": sum(1 for x in rows if (x.get("false_breakout") or {}).get("detected")),
        "observed_follow_through_rate_pct": quality.get("observed_follow_through_rate_pct"),
        "forensics_sample_size": quality.get("sample_size"),
    })
    sectors = base.get("sector_heatmap") or []
    return {
        **base,
        "version": "72.2", "release": "72.2-timing-execution", "name": "Timing + Execution Intelligence • Predictive AI Brain 3.2",
        "ai_brain": brain, "pre_move_radar": radar_base, "pre_move_rows": rows,
        "market_heatmap": rows[:60], "sector_heatmap": sectors, "latency_guard": latency, "command_center": cc,
        "alert_center": alerts, "signal_quality": quality, "adaptive_calibration": calibration,
        "modules": {
            **(base.get("modules") or {}),
            "trigger_countdown_trajectory": True, "confidence_stability": True, "evidence_persistence": True,
            "pipeline_latency_guardian": True, "opportunity_decay": True, "reentry_engine": True,
            "move_quality_crowding_detector": True, "opening_5_min_brain": True, "expiry_gamma_mode": True,
            "false_breakout_detector": True, "premium_response_test": True, "conflict_matrix": True,
            "alert_priority_p0_p3": True, "duplicate_suppression": True, "opportunity_replacement": True,
            "signal_forensics": True, "bounded_adaptive_thresholds": True, "replay_engine": True,
            "multi_timeframe_trigger": True,
        },
        "truth_policy": list(dict.fromkeys(list(base.get("truth_policy") or []) + [
            "P0/P1/P2/P3 are attention priorities, not probability guarantees.",
            "Observed follow-through statistics are retrospective audits and are never presented as guaranteed forward accuracy.",
            "Adaptive threshold changes are bounded to ±3 score points and logged when enough resolved samples exist.",
            "Re-entry is evidence-based pullback/retest logic only; averaging down is never recommended.",
        ])),
    }
