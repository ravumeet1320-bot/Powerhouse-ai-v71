from __future__ import annotations

"""Powerhouse AI V50 Supreme intelligence layer.

Read-only analytical orchestration over the data already collected by the app.
It intentionally does not place orders, store P&L, or turn quality scores into
probabilities of profit.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import math
import time


def num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def mean(values: List[Optional[float]]) -> Optional[float]:
    xs = [x for x in values if x is not None]
    return sum(xs) / len(xs) if xs else None


def _evidence_family(candidate: Dict[str, Any], market: Dict[str, Any], ai: Dict[str, Any], sm: Dict[str, Any]) -> Dict[str, Any]:
    side = candidate.get("side")
    move = num(candidate.get("change_pct"))
    quality = num(candidate.get("quality"))
    sector_ok = "sector confirmation" in (candidate.get("reasons") or [])
    trend = clamp(50 + (move or 0) * (15 if side == "CE" else -15)) if move is not None else None
    structure = quality
    participation = clamp(45 + min(abs(move or 0) * 18, 38)) if move is not None else None

    oi_bias = num(sm.get("option_oi_bias"))
    doi_bias = num(sm.get("delta_oi_bias"))
    deriv_parts: List[Optional[float]] = []
    if oi_bias is not None:
        deriv_parts.append(clamp(50 + oi_bias * (0.45 if side == "CE" else -0.45)))
    if doi_bias is not None:
        deriv_parts.append(clamp(50 + doi_bias * (0.35 if side == "CE" else -0.35)))
    derivatives = mean(deriv_parts)

    iv = num((market.get("analytics") or {}).get("iv")) or num(sm.get("iv"))
    volatility = 50.0 if iv is not None else None
    data_q = num(sm.get("data_quality")) or num(ai.get("data_quality"))
    liquidity = 75.0 if candidate.get("kind") == "INDEX" else (70.0 if candidate.get("freshness") == "LIVE" else None)
    context = 82.0 if sector_ok else 38.0

    fam = {
        "trend": trend,
        "structure": structure,
        "participation": participation,
        "derivatives": derivatives,
        "volatility": volatility,
        "liquidity": liquidity,
        "context": context,
        "data_trust": data_q,
    }
    available = [v for v in fam.values() if v is not None]
    fam["available_families"] = len(available)
    fam["independent_strength"] = round(mean(available) or 0)
    return fam


def _red_team(candidate: Dict[str, Any], fam: Dict[str, Any]) -> Dict[str, Any]:
    objections: List[str] = []
    conflicts = candidate.get("counter_signals") or []
    objections.extend([str(x) for x in conflicts[:3]])
    if candidate.get("chase_risk") == "HIGH":
        objections.append("Move is extended; chase risk is high.")
    if (num(candidate.get("conflict")) or 0) >= 30:
        objections.append("Independent context is not fully aligned.")
    if (num(fam.get("data_trust")) or 0) < 60:
        objections.append("Data quality is below the preferred review floor.")
    if (num(fam.get("available_families")) or 0) < 4:
        objections.append("Too few independent evidence families are available.")
    survived = len(objections) <= 1 and (num(candidate.get("quality")) or 0) >= 80
    verdict = "SURVIVED RED TEAM" if survived else "NEEDS CONFIRMATION" if len(objections) <= 3 else "REJECT / WAIT"
    return {"verdict": verdict, "objections": objections, "survived": survived}


def _fragility(candidate: Dict[str, Any], fam: Dict[str, Any], red: Dict[str, Any]) -> Dict[str, Any]:
    risk = 18.0
    if candidate.get("chase_risk") == "MEDIUM": risk += 18
    if candidate.get("chase_risk") == "HIGH": risk += 34
    risk += min(30, (num(candidate.get("conflict")) or 0) * 0.55)
    if not red.get("survived"): risk += 10
    if (num(fam.get("available_families")) or 0) < 5: risk += 12
    risk = clamp(risk)
    label = "ROBUST" if risk < 30 else "NORMAL" if risk < 55 else "FRAGILE" if risk < 75 else "VERY FRAGILE"
    return {"score": round(risk), "label": label}


def _timing(candidate: Dict[str, Any], fragility: Dict[str, Any]) -> str:
    life = str(candidate.get("lifecycle") or "WATCH")
    chase = candidate.get("chase_risk")
    if chase == "HIGH": return "TOO EXTENDED — SECOND CHANCE HUNT"
    if life == "TRIGGER READY" and fragility["score"] < 60: return "ENTRY REVIEW READY"
    if life == "READY": return "WAIT FOR TRIGGER / ACCEPTANCE"
    if life == "ARMING": return "EARLY — ONE OR MORE CONFIRMATIONS PENDING"
    return "WATCH — SETUP NOT READY"


def _candidate_passport(candidate: Dict[str, Any], market: Dict[str, Any], ai: Dict[str, Any], sm: Dict[str, Any]) -> Dict[str, Any]:
    fam = _evidence_family(candidate, market, ai, sm)
    red = _red_team(candidate, fam)
    frag = _fragility(candidate, fam, red)
    missing = [k for k, v in fam.items() if k not in ("available_families", "independent_strength") and v is None]
    levels = candidate.get("levels") or {}
    waiting: List[str] = []
    if candidate.get("lifecycle") not in ("READY", "TRIGGER READY"): waiting.append("quality/lifecycle promotion")
    if red.get("objections"): waiting.append("red-team objections to clear")
    if candidate.get("chase_risk") == "HIGH": waiting.append("retest / second-chance structure")
    if missing: waiting.append("fresh " + ", ".join(missing[:2]) + " data")
    return {
        **candidate,
        "evidence": fam,
        "red_team": red,
        "fragility": frag,
        "timing": _timing(candidate, frag),
        "waiting_for": waiting or ["live trigger acceptance"],
        "why_now": (candidate.get("reasons") or [])[:5],
        "why_not": red.get("objections")[:5],
        "what_changes_mind": candidate.get("flip_condition") or "Opposing structure and flow confirmation.",
        "route": {"entry": levels.get("entry_trigger"), "invalidation": levels.get("sl"), "t1": levels.get("t1"), "t2": levels.get("t2")},
        "score_semantics": "setup/evidence quality, not probability of profit",
    }


def _chain_geometry(market: Dict[str, Any]) -> Dict[str, Any]:
    rows = market.get("option_data") or []
    clean = []
    for r in rows:
        strike = num(r.get("strike") or r.get("strike_price"))
        ce = r.get("ce") or r.get("call") or r.get("call_options") or {}
        pe = r.get("pe") or r.get("put") or r.get("put_options") or {}
        # Support both normalized and raw-ish records.
        cem = ce.get("market_data") or ce
        pem = pe.get("market_data") or pe
        ce_oi, pe_oi = num(cem.get("oi")), num(pem.get("oi"))
        ce_vol, pe_vol = num(cem.get("volume")), num(pem.get("volume"))
        ce_doi = num(cem.get("delta_oi")) or num(cem.get("oi_change"))
        pe_doi = num(pem.get("delta_oi")) or num(pem.get("oi_change"))
        if strike is not None:
            clean.append({"strike": strike, "ce_oi": ce_oi, "pe_oi": pe_oi, "ce_vol": ce_vol, "pe_vol": pe_vol, "ce_doi": ce_doi, "pe_doi": pe_doi})
    if not clean:
        return {"available": False, "note": "Option-chain geometry unavailable."}
    call_wall = max(clean, key=lambda x: x["ce_oi"] if x["ce_oi"] is not None else -1)
    put_wall = max(clean, key=lambda x: x["pe_oi"] if x["pe_oi"] is not None else -1)
    active = max(clean, key=lambda x: sum(v or 0 for v in (x["ce_vol"], x["pe_vol"], x["ce_doi"], x["pe_doi"])))
    return {
        "available": True,
        "call_wall": call_wall["strike"] if call_wall["ce_oi"] is not None else None,
        "put_wall": put_wall["strike"] if put_wall["pe_oi"] is not None else None,
        "most_active_strike": active["strike"],
        "visible_strikes": len(clean),
        "semantics": "anonymous visible option activity; no participant identity attribution",
    }


def _market_heartbeat(market: Dict[str, Any], radar: Dict[str, Any], sm: Dict[str, Any]) -> Dict[str, Any]:
    breadth = radar.get("breadth") or {}
    live = int((radar.get("coverage") or {}).get("live_stocks") or 0)
    adv, dec = int(breadth.get("bullish") or 0), int(breadth.get("bearish") or 0)
    participation = round(clamp((adv + dec) / max(1, live) * 100)) if live else None
    breadth_score = num(radar.get("breadth_score"))
    flow = num(sm.get("footprint_score"))
    trap = num(sm.get("trap_risk"))
    tension_parts = [abs(breadth_score) if breadth_score is not None else None, abs((flow or 50) - 50) * 2 if flow is not None else None, trap]
    tension = mean(tension_parts)
    label = "CALM" if tension is not None and tension < 25 else "BUILDING" if tension is not None and tension < 45 else "TENSE" if tension is not None and tension < 70 else "RELEASE / EXTREME" if tension is not None else "N/A"
    return {
        "market_state": radar.get("market_state"),
        "market_bias": radar.get("market_bias"),
        "participation": participation,
        "breadth_score": breadth_score,
        "flow_score": flow,
        "trap_risk": trap,
        "tension": round(tension) if tension is not None else None,
        "tension_label": label,
    }


def build_supreme_intelligence(market: Dict[str, Any], ai: Dict[str, Any], sm: Dict[str, Any], radar: Dict[str, Any]) -> Dict[str, Any]:
    queue = radar.get("queue") or []
    passports = [_candidate_passport(x, market, ai, sm) for x in queue[:20]]
    # Ranking: quality + independent family strength - fragility/chase penalty.
    for p in passports:
        q = num(p.get("quality")) or 0
        ind = num((p.get("evidence") or {}).get("independent_strength")) or 0
        frag = num((p.get("fragility") or {}).get("score")) or 100
        chase = 12 if p.get("chase_risk") == "HIGH" else 4 if p.get("chase_risk") == "MEDIUM" else 0
        p["supreme_rank_score"] = round(clamp(q * .56 + ind * .34 + (100 - frag) * .10 - chase))
    passports.sort(key=lambda x: x.get("supreme_rank_score", 0), reverse=True)

    almost = [p for p in passports if p.get("lifecycle") in ("ARMING", "READY") and p.get("chase_risk") != "HIGH"][:8]
    trigger = [p for p in passports if p.get("lifecycle") == "TRIGGER READY" and p.get("chase_risk") != "HIGH"][:5]
    second_chance = [p for p in passports if p.get("chase_risk") == "HIGH"][:6]
    red_survivors = [p for p in passports if (p.get("red_team") or {}).get("survived")][:6]

    # Unknown/unclassified anomalies are deliberately modest: unusual move that isn't yet A-grade.
    anomalies = [p for p in passports if abs(num(p.get("change_pct")) or 0) >= 1.0 and (num(p.get("quality")) or 0) < 80][:8]

    cov = radar.get("coverage") or {}
    configured = int(cov.get("configured_universe") or 0)
    live = int(cov.get("live_stocks") or 0)
    fresh_pct = round(live / configured * 100, 1) if configured else None
    coverage = {
        "configured": configured,
        "fresh_live": live,
        "missing_or_stale": max(0, configured - live),
        "fresh_pct": fresh_pct,
        "sectors": cov.get("sectors"),
        "claim": "connected configured universe only; not guaranteed complete NSE/F&O coverage",
    }

    funnel = dict(radar.get("funnel") or {})
    funnel.update({
        "anomalies": len(anomalies),
        "deep_scan": len(passports),
        "almost_ready": len(almost),
        "trigger_ready": len(trigger),
        "red_team_survivors": len(red_survivors),
    })

    engines = [
        ("Whole-Market Hunter", True), ("Pre-Signal / Almost Ready", True), ("AI Detective", True),
        ("Evidence Independence", True), ("Red-Team Judge", True), ("Fragility / Anti-FOMO", True),
        ("Second-Chance Hunter", True), ("Opportunity Passport", True), ("Chain Geometry", True),
        ("Coverage Truth", True), ("Blind-Spot Guard", True), ("Parallel Thesis", True),
        ("Dynamic Invalidation", True), ("Target Friction Context", True), ("Alert Escalation", True),
        ("Time Machine", False), ("Post-Market Autopsy", False), ("Historical Fingerprint Memory", False),
        ("Participant Positioning", False), ("Full NSE licensed feed", False),
    ]

    best = passports[:3]
    return {
        "version": "50.0",
        "generated_at": time.time(),
        "heartbeat": _market_heartbeat(market, radar, sm),
        "coverage": coverage,
        "mission_control": funnel,
        "best_now": best,
        "almost_ready": almost,
        "trigger_ready": trigger,
        "second_chance": second_chance,
        "unknown_anomalies": anomalies,
        "red_team_survivors": red_survivors,
        "option_chain_geometry": _chain_geometry(market),
        "engines": [{"name": n, "live": live_} for n, live_ in engines],
        "guardian": {
            "status": "DEGRADED COVERAGE" if fresh_pct is not None and fresh_pct < 75 else "LIVE / GUARDED" if live else "DATA WAIT",
            "signals_suppressed_when_data_weak": True,
            "missing_is_not_zero": True,
            "anonymous_flow_identity_policy": True,
        },
        "policy": {
            "read_only": True,
            "orders_enabled": False,
            "execution_enabled": False,
            "pnl_enabled": False,
            "quality_not_profit_probability": True,
            "no_guaranteed_trade_detection": True,
        },
    }
