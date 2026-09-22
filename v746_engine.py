from __future__ import annotations

"""POWERHOUSE AI V74.6 aggressive/dynamic decision layer.

Additive over V74.5.  The purpose is to react earlier and surface more qualified
setups without bypassing hard data-integrity, extreme-volatility, or execution
quality blocks.  It remains read-only decision support and does not place orders.
"""

from typing import Any, Dict, Mapping, Optional, Sequence
import math
import v745_engine as base

VERSION = "74.6"
RELEASE = "POWERHOUSE-AI-V74.6-AGGRESSIVE-DYNAMIC-MASTER-FINAL"

PROFILES: Dict[str, Dict[str, float]] = {
    "BALANCED": {
        "ready_signal": 78, "ready_exec": 66, "max_uncertainty": 42,
        "early_signal": 70, "early_exec": 60, "early_uncertainty": 50,
        "hard_signal": 60, "hard_exec": 48, "hard_uncertainty": 64,
        "late_mult": 1.15, "severe_mult": 1.10, "vix_hard": 94,
        "poll_sec": 20, "profile_bonus": 0,
    },
    "AGGRESSIVE": {
        "ready_signal": 68, "ready_exec": 54, "max_uncertainty": 55,
        "early_signal": 62, "early_exec": 52, "early_uncertainty": 60,
        "hard_signal": 55, "hard_exec": 42, "hard_uncertainty": 70,
        "late_mult": 1.55, "severe_mult": 1.35, "vix_hard": 96,
        "poll_sec": 12, "profile_bonus": 12,
    },
    "TURBO": {
        "ready_signal": 64, "ready_exec": 50, "max_uncertainty": 60,
        "early_signal": 58, "early_exec": 48, "early_uncertainty": 65,
        "hard_signal": 52, "hard_exec": 38, "hard_uncertainty": 74,
        "late_mult": 1.80, "severe_mult": 1.55, "vix_hard": 97,
        "poll_sec": 8, "profile_bonus": 20,
    },
}


def profile(name: Optional[str]) -> tuple[str, Dict[str, float]]:
    p = str(name or "AGGRESSIVE").strip().upper()
    if p not in PROFILES:
        p = "AGGRESSIVE"
    return p, dict(PROFILES[p])


def _action_side(action: str) -> int:
    a = str(action or "").upper()
    if a in {"BUY", "BUY CE"}: return 1
    if a in {"SELL", "BUY PE"}: return -1
    return 0


def _direction_ok(action: str, resolver: Mapping[str, Any]) -> bool:
    side = _action_side(action)
    direction = str(resolver.get("direction") or "MIXED").upper()
    if side > 0: return direction == "BULLISH"
    if side < 0: return direction == "BEARISH"
    return False


def dynamic_thresholds(profile_name: str, dq: Mapping[str, Any], regime: Mapping[str, Any], vix: Mapping[str, Any]) -> Dict[str, float]:
    p, cfg = profile(profile_name)
    r = str(regime.get("regime") or "").upper()
    dq_score = base.f(dq.get("score"), 50.0) or 50.0
    vrisk = base.f(vix.get("risk_score"), 50.0) if vix.get("available") else 50.0

    # Dynamic sensitivity: trending + clean feeds = earlier qualification.
    if "TRENDING" in r:
        cfg["ready_signal"] -= 3
        cfg["early_signal"] -= 2
        cfg["max_uncertainty"] += 2
    elif "RANGE" in r:
        cfg["ready_signal"] += 3
        cfg["ready_exec"] += 2
    elif "TRANSITION" in r:
        cfg["ready_signal"] += 1
        cfg["ready_exec"] += 2
    elif "HIGH VOL" in r:
        cfg["ready_exec"] += 5
        cfg["max_uncertainty"] -= 4
        cfg["early_exec"] += 4

    if dq_score >= 92:
        cfg["ready_signal"] -= 2
        cfg["early_signal"] -= 1
    elif dq_score < 78:
        cfg["ready_signal"] += 4
        cfg["ready_exec"] += 4
        cfg["max_uncertainty"] -= 4

    if vrisk is not None and vrisk >= 82:
        cfg["ready_exec"] += 4
        cfg["max_uncertainty"] -= 4
    if vrisk is not None and vrisk <= 42 and "TRENDING" in r:
        cfg["ready_signal"] -= 1

    cfg["profile"] = p
    return cfg


def _dynamic_late(setup: Mapping[str, Any], cfg: Mapping[str, Any]) -> Dict[str, Any]:
    cmp_ = base.f(setup.get("cmp") or setup.get("ltp"))
    entry_zone = setup.get("entry_zone") if isinstance(setup.get("entry_zone"), Mapping) else {}
    trigger = base.f(setup.get("buy_above") or setup.get("trigger") or entry_zone.get("high"))
    instrument = str(setup.get("instrument") or "STOCK").upper()
    if cmp_ is None or trigger in (None, 0):
        return {"late": False, "severe": False, "overextension_pct": None, "status": "UNKNOWN"}
    distance = abs(cmp_ - trigger) / abs(trigger) * 100.0
    base_threshold = 6.0 if instrument == "OPTION" else 1.15
    base_severe = 10.0 if instrument == "OPTION" else 2.0
    threshold = base_threshold * float(cfg.get("late_mult", 1.0))
    severe = base_severe * float(cfg.get("severe_mult", 1.0))
    return {
        "late": distance > threshold,
        "severe": distance > severe,
        "overextension_pct": round(distance, 3),
        "threshold_pct": round(threshold, 3),
        "severe_pct": round(severe, 3),
        "status": "OVEREXTENDED" if distance > severe else "LATE" if distance > threshold else "OK",
    }


def urgency_score(setup: Mapping[str, Any], sig: float, exe: float, regime: Mapping[str, Any], vix: Mapping[str, Any], late: Mapping[str, Any]) -> float:
    stage = str(setup.get("stage") or setup.get("status") or "").upper()
    stage_boost = 14 if any(x in stage for x in ("ENTRY ACTIVE", "READY")) else 10 if "TRIGGER NEAR" in stage else 7 if any(x in stage for x in ("TRIGGER", "ARMING")) else 3
    reg = str(regime.get("regime") or "").upper()
    reg_boost = 8 if "TRENDING" in reg else 3 if "HIGH VOL" in reg else 0
    vrisk = base.f(vix.get("risk_score"), 50.0) or 50.0
    vix_penalty = max(0.0, vrisk - 75.0) * .18
    late_penalty = 12 if late.get("severe") else 5 if late.get("late") else 0
    score = sig * .42 + exe * .32 + stage_boost + reg_boost - vix_penalty - late_penalty
    return round(base.clamp(score), 1)


def aggression_score(profile_name: str, dq: Mapping[str, Any], regime: Mapping[str, Any], vix: Mapping[str, Any], exe: float) -> float:
    p, cfg = profile(profile_name)
    dq_score = base.f(dq.get("score"), 50.0) or 50.0
    r = str(regime.get("regime") or "").upper()
    vrisk = base.f(vix.get("risk_score"), 50.0) if vix.get("available") else 50.0
    score = 42.0 + cfg.get("profile_bonus", 0.0) + (dq_score - 70.0) * .25 + (exe - 50.0) * .20
    if "TRENDING" in r: score += 10
    if "RANGE" in r: score -= 5
    if "HIGH VOL" in r: score += 3
    if vrisk is not None and vrisk >= 88: score -= 12
    return round(base.clamp(score), 1)


def qualify_dynamic(setup: Mapping[str, Any], dq: Mapping[str, Any], regime: Mapping[str, Any], vix: Mapping[str, Any], profile_name: str = "AGGRESSIVE") -> Dict[str, Any]:
    # Re-use the V74.5 evidence calculators, then relax only soft gates dynamically.
    original = dict(setup)
    old_adaptive = dict(original.get("adaptive") or {})
    original.pop("adaptive", None)

    sig_obj = base.signal_quality(original, dq, regime, vix)
    exe_obj = base.execution_quality(original)
    sig = base.f(sig_obj.get("score"), 0.0) or 0.0
    exe = base.f(exe_obj.get("score"), 0.0) or 0.0
    cfg = dynamic_thresholds(profile_name, dq, regime, vix)
    late = _dynamic_late(original, cfg)
    weights = base.adaptive_weights(str(regime.get("regime") or ""))
    resolver = base.contradiction_resolver(base._setup_evidence(original, regime, vix), weights)

    uncertainty = 16.0 + resolver["conflict_ratio"] * 36.0 + (100.0 - (base.f(dq.get("score"), 50.0) or 50.0)) * .24
    r = str(regime.get("regime") or "").upper()
    if r == "TRANSITION": uncertainty += 5
    if "HIGH VOL" in r: uncertainty += 6
    if late.get("late"): uncertainty += 6
    uncertainty = base.clamp(uncertainty)

    action = str(original.get("option_action") or original.get("action") or "WAIT").upper()
    direction_ok = _direction_ok(action, resolver)
    vrisk = base.f(vix.get("risk_score"), 0.0) or 0.0
    hard_reasons = []
    if str(dq.get("gate") or "").upper() == "BLOCK": hard_reasons.append("DATA QUALITY BLOCK")
    if sig < cfg["hard_signal"]: hard_reasons.append("SIGNAL TOO WEAK")
    if exe < cfg["hard_exec"]: hard_reasons.append("EXECUTION TOO WEAK")
    if uncertainty > cfg["hard_uncertainty"]: hard_reasons.append("UNCERTAINTY EXTREME")
    if vrisk >= cfg["vix_hard"]: hard_reasons.append("VIX EXTREME RISK")
    if late.get("severe"): hard_reasons.append("SEVERELY OVEREXTENDED")
    if resolver.get("conflict_ratio", 0) >= .92: hard_reasons.append("EVIDENCE CONFLICT EXTREME")

    blockers = [str(x) for x in (sig_obj.get("blockers") or [])]
    for b in blockers:
        u = b.upper()
        if any(k in u for k in ("AUTH", "NO DATA", "STALE", "LIQUIDITY", "SPREAD")):
            hard_reasons.append(b)

    raw_ready = (
        not hard_reasons and direction_ok and
        sig >= cfg["ready_signal"] and exe >= cfg["ready_exec"] and uncertainty <= cfg["max_uncertainty"]
    )
    early_ready = (
        not hard_reasons and direction_ok and not raw_ready and
        sig >= cfg["early_signal"] and exe >= cfg["early_exec"] and uncertainty <= cfg["early_uncertainty"]
    )

    if hard_reasons:
        lifecycle = "INVALIDATED"
    elif raw_ready:
        lifecycle = "READY"
    elif early_ready:
        lifecycle = "EARLY READY"
    elif sig >= max(52.0, cfg["early_signal"] - 5) and exe >= max(45.0, cfg["early_exec"] - 5):
        lifecycle = "ARMED"
    elif sig >= 50:
        lifecycle = "FORMING"
    else:
        lifecycle = "SCANNING"

    urgency = urgency_score(original, sig, exe, regime, vix, late)
    aggr = aggression_score(str(cfg["profile"]), dq, regime, vix, exe)
    confidence = min(100.0, sig + (5 if raw_ready else 2 if early_ready else 0), exe + 18.0, 100.0 - uncertainty * .40)
    if direction_ok: confidence += 2
    confidence = base.clamp(confidence)

    final_action = action if raw_ready and action not in {"WAIT", "WATCH", ""} else "WAIT"
    probe_action = action if early_ready and action not in {"WAIT", "WATCH", ""} else None
    entry_style = "ATTACK" if raw_ready and aggr >= 78 else "FAST" if raw_ready else "EARLY WATCH" if early_ready else "WAIT"

    adaptive = {
        "profile": cfg["profile"],
        "signal_quality": sig_obj,
        "execution_quality": exe_obj,
        "late_entry": late,
        "resolver": resolver,
        "uncertainty_score": round(uncertainty, 1),
        "confidence_score": round(confidence, 1),
        "confidence_band": "HIGH" if confidence >= 76 else "MEDIUM" if confidence >= 60 else "LOW",
        "lifecycle": lifecycle,
        "raw_ready": raw_ready,
        "early_ready": early_ready,
        "qualified": raw_ready,
        "final_action": final_action,
        "probe_action": probe_action,
        "entry_style": entry_style,
        "urgency_score": urgency,
        "aggression_score": aggr,
        "no_trade_reasons": list(dict.fromkeys(hard_reasons)),
        "soft_wait_reasons": [] if (raw_ready or early_ready) else [
            x for x, cond in (
                ("SIGNAL BUILDING", sig < cfg["ready_signal"]),
                ("EXECUTION BUILDING", exe < cfg["ready_exec"]),
                ("UNCERTAINTY ABOVE READY", uncertainty > cfg["max_uncertainty"]),
                ("DIRECTION NOT ALIGNED", not direction_ok),
            ) if cond
        ],
        "dynamic_thresholds": {k: round(v, 2) if isinstance(v, float) else v for k, v in cfg.items() if k not in {"poll_sec", "profile_bonus"}},
        "poll_sec": int(cfg["poll_sec"]),
        "weights": weights,
        "v745_reference": old_adaptive,
    }
    return {**original, "adaptive": adaptive}


def temporal_required(row: Mapping[str, Any]) -> int:
    a = row.get("adaptive") or {}
    p = str(a.get("profile") or "AGGRESSIVE").upper()
    sig = base.f((a.get("signal_quality") or {}).get("score"), 0.0) or 0.0
    exe = base.f((a.get("execution_quality") or {}).get("score"), 0.0) or 0.0
    urgency = base.f(a.get("urgency_score"), 0.0) or 0.0
    vix_ref = a.get("v745_reference") or {}
    # TURBO is intentionally one-snapshot except weak-borderline states.
    if p == "TURBO" and sig >= 66 and exe >= 52: return 1
    # Strong aggressive setup can trigger on first independent snapshot.
    if p == "AGGRESSIVE" and sig >= 76 and exe >= 62 and urgency >= 72: return 1
    return 2


def best_dynamic_setup(setups: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    rows = [dict(x) for x in setups or [] if bool((x.get("adaptive") or {}).get("qualified"))]
    if not rows:
        return None
    rows.sort(key=lambda x: (
        base.f((x.get("adaptive") or {}).get("urgency_score"), 0.0) or 0.0,
        base.f((x.get("adaptive") or {}).get("confidence_score"), 0.0) or 0.0,
        base.f(((x.get("adaptive") or {}).get("execution_quality") or {}).get("score"), 0.0) or 0.0,
    ), reverse=True)
    return rows[0]


def best_early_setup(setups: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    rows = [dict(x) for x in setups or [] if bool((x.get("adaptive") or {}).get("early_ready"))]
    if not rows: return None
    rows.sort(key=lambda x: base.f((x.get("adaptive") or {}).get("urgency_score"), 0.0) or 0.0, reverse=True)
    return rows[0]
