from __future__ import annotations

"""POWERHOUSE AI V74.5 adaptive decision-quality layer.

The module is deliberately deterministic and provider-truth preserving.  It adds
regime, volatility, uncertainty, execution-quality and abstention gates over the
existing V74.3/V74.4 stack.  It does not place broker orders and it does not
claim guaranteed accuracy.
"""

import math
import statistics
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

VERSION = "74.5"
RELEASE = "POWERHOUSE-AI-V74.5-ADAPTIVE-INTELLIGENCE-MASTER-FINAL"


def f(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def clamp(value: Any, lo: float = 0.0, hi: float = 100.0) -> float:
    x = f(value, 0.0) or 0.0
    return max(lo, min(hi, x))


def pct(a: Any, b: Any) -> Optional[float]:
    aa, bb = f(a), f(b)
    if aa is None or bb in (None, 0):
        return None
    return (aa - bb) / abs(bb) * 100.0


def mean(values: Iterable[Any]) -> Optional[float]:
    nums = [x for x in (f(v) for v in values) if x is not None]
    return statistics.fmean(nums) if nums else None


def _status(value: Any) -> str:
    return str(value or "UNKNOWN").strip().upper().replace("_", " ")


def freshness_label(age_sec: Any, live: float = 8.0, delayed: float = 30.0, stale: float = 90.0) -> str:
    age = f(age_sec)
    if age is None:
        return "UNKNOWN"
    if age <= live:
        return "FRESH"
    if age <= delayed:
        return "DELAYED"
    if age <= stale:
        return "STALE"
    return "VERY STALE"


def data_quality(provider: Mapping[str, Any], scanner: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Score only observable feed-health metadata; never infer missing prices as zero."""
    scanner = scanner or {}
    status = _status(provider.get("data_status") or provider.get("status"))
    tick_age = f(provider.get("tick_age_sec"))
    rest_age = f(provider.get("rest_age_sec"))
    authenticated = provider.get("authenticated")
    token_invalid = bool(provider.get("token_invalid"))
    scanner_status = _status(scanner.get("status") or scanner.get("state") or scanner.get("data_status"))
    reasons: List[str] = []
    score = 100.0

    if authenticated is False or token_invalid:
        score -= 70
        reasons.append("BROKER AUTH INVALID")
    if status in {"UNAVAILABLE", "OFFLINE", "ERROR", "UNKNOWN", "N/A", "NONE"}:
        score -= 55
        reasons.append(f"DATA {status}")
    elif status in {"STALE", "PARTIAL"}:
        score -= 25
        reasons.append(f"DATA {status}")
    elif status not in {"LIVE", "REST", "READY"}:
        score -= 12
        reasons.append(f"DATA STATUS {status}")

    if tick_age is not None:
        if tick_age > 90:
            score -= 35; reasons.append("TICK VERY STALE")
        elif tick_age > 30:
            score -= 20; reasons.append("TICK STALE")
        elif tick_age > 10:
            score -= 8; reasons.append("TICK DELAYED")
    if rest_age is not None:
        if rest_age > 180:
            score -= 25; reasons.append("REST VERY STALE")
        elif rest_age > 75:
            score -= 12; reasons.append("REST STALE")

    if scanner_status in {"ERROR", "UNAVAILABLE", "OFFLINE"}:
        score -= 15
        reasons.append("SCANNER DEGRADED")

    score = clamp(score)
    if score >= 82:
        gate = "PASS"
    elif score >= 62:
        gate = "CAUTION"
    else:
        gate = "BLOCK"
    return {
        "score": round(score, 1),
        "gate": gate,
        "data_status": status,
        "tick_age_sec": tick_age,
        "rest_age_sec": rest_age,
        "tick_freshness": freshness_label(tick_age),
        "rest_freshness": freshness_label(rest_age, live=20, delayed=75, stale=180),
        "scanner_status": scanner_status,
        "reasons": reasons,
        "truth": "Missing or stale inputs reduce confidence or block new trade-ready states.",
    }


def _market_row(markets: Sequence[Mapping[str, Any]], name: str) -> Optional[Mapping[str, Any]]:
    target = name.upper()
    for row in markets or []:
        if str(row.get("market") or row.get("name") or "").upper() == target:
            return row
    return None


def vix_intelligence(markets: Sequence[Mapping[str, Any]], history: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    row = _market_row(markets, "INDIA VIX")
    level = f((row or {}).get("price"))
    day_change = f((row or {}).get("change_pct"))
    hist = []
    for h in history or []:
        p, e = f(h.get("price")), f(h.get("epoch"))
        if p is not None and e is not None:
            hist.append((e, p))
    hist.sort()
    now = time.time()
    recent = [(e, p) for e, p in hist if now - e <= 900]
    ref = recent[0][1] if recent else (hist[-1][1] if hist else None)
    intraday_accel = pct(level, ref) if level is not None and ref is not None else None

    if level is None:
        regime = "UNAVAILABLE"
        risk = None
    elif level < 12:
        regime, risk = "LOW VOL", 24.0
    elif level < 18:
        regime, risk = "NORMAL", 38.0
    elif level < 24:
        regime, risk = "ELEVATED", 58.0
    elif level < 30:
        regime, risk = "HIGH", 76.0
    else:
        regime, risk = "EXTREME", 92.0

    if risk is not None and day_change is not None:
        risk += min(16.0, max(-8.0, day_change * 1.6))
    if risk is not None and intraday_accel is not None:
        risk += min(12.0, max(-6.0, intraday_accel * 1.4))
    risk = round(clamp(risk), 1) if risk is not None else None

    prices = [p for _, p in hist[-120:]]
    z = None
    percentile = None
    if level is not None and len(prices) >= 10:
        mu = statistics.fmean(prices)
        sd = statistics.pstdev(prices)
        z = (level - mu) / sd if sd > 1e-9 else 0.0
        percentile = sum(1 for p in prices if p <= level) / len(prices) * 100.0

    if day_change is None:
        state = "NO CHANGE DATA"
    elif day_change >= 5:
        state = "VOLATILITY EXPANDING FAST"
    elif day_change >= 2:
        state = "VOLATILITY EXPANDING"
    elif day_change <= -5:
        state = "VOLATILITY COMPRESSING FAST"
    elif day_change <= -2:
        state = "VOLATILITY COMPRESSING"
    else:
        state = "VOLATILITY STABLE"

    return {
        "available": level is not None,
        "level": level,
        "change_pct": day_change,
        "acceleration_15m_pct": round(intraday_accel, 3) if intraday_accel is not None else None,
        "regime": regime,
        "state": state,
        "risk_score": risk,
        "zscore_session": round(z, 3) if z is not None else None,
        "percentile_session": round(percentile, 1) if percentile is not None else None,
        "source": (row or {}).get("source") or "UNAVAILABLE",
        "truth": "India VIX is contextual/risk evidence only; never a standalone BUY/SELL trigger.",
    }


def cross_market_context(markets: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Small explainable macro context score; absent feeds are omitted, never fabricated."""
    weights = {
        "GIFT NIFTY": 1.6,
        "S&P 500": 1.0,
        "NASDAQ / US TECH 100": 0.8,
        "DXY": -0.45,
        "USD/INR": -0.35,
        "BRENT CRUDE": -0.25,
    }
    used = []
    raw = 0.0
    denom = 0.0
    for name, weight in weights.items():
        row = _market_row(markets, name)
        ch = f((row or {}).get("change_pct"))
        if ch is None:
            continue
        capped = max(-2.5, min(2.5, ch))
        raw += capped * weight
        denom += abs(weight)
        used.append({"market": name, "change_pct": ch, "weight": weight})
    score = max(-100.0, min(100.0, (raw / denom * 35.0) if denom else 0.0))
    label = "RISK-ON" if score >= 18 else "RISK-OFF" if score <= -18 else "MIXED"
    return {"score": round(score, 1), "label": label, "feeds_used": used, "available_count": len(used)}


def market_regime(index_cards: Sequence[Mapping[str, Any]], vix: Mapping[str, Any], sectors: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    changes = [x for x in (f(r.get("change_pct")) for r in index_cards or []) if x is not None]
    avg = statistics.fmean(changes) if changes else None
    pos = sum(1 for x in changes if x > 0.15)
    neg = sum(1 for x in changes if x < -0.15)
    dispersion = statistics.pstdev(changes) if len(changes) >= 2 else None
    vreg = str(vix.get("regime") or "UNAVAILABLE")
    vrisk = f(vix.get("risk_score"))

    if vrisk is not None and vrisk >= 76:
        regime = "HIGH VOLATILITY"
    elif avg is None:
        regime = "INSUFFICIENT DATA"
    elif abs(avg) >= 0.45 and max(pos, neg) >= max(2, math.ceil(len(changes) * 0.75)):
        regime = "TRENDING UP" if avg > 0 else "TRENDING DOWN"
    elif abs(avg) <= 0.18 and (dispersion is None or dispersion <= 0.65):
        regime = "RANGE / MIXED"
    else:
        regime = "TRANSITION"

    confidence = 35.0
    if changes:
        agreement = max(pos, neg) / max(1, len(changes))
        confidence += agreement * 40
        confidence += min(15.0, abs(avg or 0.0) * 15)
    if vreg != "UNAVAILABLE":
        confidence += 8
    confidence = clamp(confidence)
    bias = "BULLISH" if avg is not None and avg >= 0.2 else "BEARISH" if avg is not None and avg <= -0.2 else "NEUTRAL"
    return {
        "regime": regime,
        "bias": bias,
        "confidence": round(confidence, 1),
        "index_avg_change_pct": round(avg, 3) if avg is not None else None,
        "index_positive": pos,
        "index_negative": neg,
        "dispersion": round(dispersion, 3) if dispersion is not None else None,
        "vix_regime": vreg,
    }


def adaptive_weights(regime: str) -> Dict[str, float]:
    r = str(regime or "").upper()
    if "TRENDING" in r:
        return {"trend": .25, "momentum": .18, "structure": .18, "derivatives": .15, "breadth": .10, "sector": .07, "liquidity": .07}
    if "HIGH VOL" in r:
        return {"trend": .17, "momentum": .10, "structure": .17, "derivatives": .16, "breadth": .09, "sector": .06, "liquidity": .15, "volatility": .10}
    if "RANGE" in r:
        return {"trend": .12, "momentum": .12, "structure": .24, "derivatives": .16, "breadth": .10, "sector": .08, "liquidity": .10, "volatility": .08}
    return {"trend": .18, "momentum": .15, "structure": .18, "derivatives": .15, "breadth": .10, "sector": .08, "liquidity": .09, "volatility": .07}


def execution_quality(setup: Mapping[str, Any]) -> Dict[str, Any]:
    liq = setup.get("liquidity") if isinstance(setup.get("liquidity"), Mapping) else {}
    liq_score = f((liq or {}).get("score"), f(setup.get("liquidity_score"), 50.0)) or 50.0
    spread = f((liq or {}).get("spread_pct"), f(setup.get("spread_pct")))
    rr = f(setup.get("rr") or setup.get("risk_reward"))
    score = liq_score * 0.72 + (min(100.0, max(0.0, (rr or 1.0) / 2.5 * 100.0)) * 0.18) + 10.0
    reasons = []
    if spread is not None:
        if spread > 2.0:
            score -= 35; reasons.append("WIDE SPREAD")
        elif spread > 1.0:
            score -= 20; reasons.append("SPREAD ELEVATED")
        elif spread > 0.5:
            score -= 8; reasons.append("SPREAD MODERATE")
    if liq_score < 40:
        score -= 22; reasons.append("LOW LIQUIDITY")
    if rr is not None and rr < 1.2:
        score -= 15; reasons.append("LOW R:R")
    score = clamp(score)
    label = "HIGH" if score >= 78 else "MEDIUM" if score >= 60 else "LOW"
    return {"score": round(score, 1), "label": label, "reasons": reasons, "spread_pct": spread, "liquidity_score": liq_score}


def late_entry_check(setup: Mapping[str, Any]) -> Dict[str, Any]:
    cmp_ = f(setup.get("cmp") or setup.get("ltp"))
    entry_zone = setup.get("entry_zone") if isinstance(setup.get("entry_zone"), Mapping) else {}
    trigger = f(setup.get("buy_above") or setup.get("trigger") or entry_zone.get("high"))
    instrument = str(setup.get("instrument") or "STOCK").upper()
    if cmp_ is None or trigger in (None, 0):
        return {"late": False, "overextension_pct": None, "status": "UNKNOWN"}
    distance = abs(cmp_ - trigger) / abs(trigger) * 100.0
    threshold = 6.0 if instrument == "OPTION" else 1.15
    severe = 10.0 if instrument == "OPTION" else 2.0
    return {
        "late": distance > threshold,
        "severe": distance > severe,
        "overextension_pct": round(distance, 3),
        "threshold_pct": threshold,
        "status": "OVEREXTENDED" if distance > severe else "LATE" if distance > threshold else "OK",
    }


def contradiction_resolver(evidence: Mapping[str, Any], weights: Mapping[str, float]) -> Dict[str, Any]:
    signed = []
    weighted = 0.0
    total = 0.0
    for key, weight in weights.items():
        v = f(evidence.get(key))
        if v is None:
            continue
        v = max(-1.0, min(1.0, v))
        signed.append((key, v, weight))
        weighted += v * weight
        total += abs(weight)
    consensus = weighted / total if total else 0.0
    bulls = sum(1 for _, v, _ in signed if v > .15)
    bears = sum(1 for _, v, _ in signed if v < -.15)
    conflicts = min(bulls, bears)
    conflict_ratio = conflicts / max(1, max(bulls, bears))
    direction = "BULLISH" if consensus >= .18 else "BEARISH" if consensus <= -.18 else "MIXED"
    return {
        "direction": direction,
        "consensus": round(consensus, 3),
        "bullish_inputs": bulls,
        "bearish_inputs": bears,
        "conflict_ratio": round(conflict_ratio, 3),
        "inputs": [{"name": k, "value": round(v, 3), "weight": w} for k, v, w in signed],
    }


def _setup_evidence(setup: Mapping[str, Any], regime: Mapping[str, Any], vix: Mapping[str, Any]) -> Dict[str, float]:
    action = str(setup.get("option_action") or setup.get("action") or "WAIT").upper()
    side = 1.0 if action in {"BUY", "BUY CE"} else -1.0 if action in {"SELL", "BUY PE"} else 0.0
    quality = (f(setup.get("quality"), f(setup.get("score"), 50.0)) or 50.0) / 100.0
    stage = str(setup.get("stage") or setup.get("status") or "").upper()
    stage_strength = .9 if any(x in stage for x in ("READY", "ACTIVE", "TRIGGER")) else .55 if "WATCH" in stage else .35
    market_bias = str(regime.get("bias") or "NEUTRAL").upper()
    breadth = 1.0 if market_bias == "BULLISH" else -1.0 if market_bias == "BEARISH" else 0.0
    liq = setup.get("liquidity") if isinstance(setup.get("liquidity"), Mapping) else {}
    liq_score = (f((liq or {}).get("score"), 50.0) or 50.0) / 100.0
    vrisk = (f(vix.get("risk_score"), 50.0) or 50.0) / 100.0
    return {
        "trend": side * quality,
        "momentum": side * stage_strength,
        "structure": side * min(1.0, .45 + len(setup.get("why") or []) * .12),
        "derivatives": side * (.72 if setup.get("instrument") == "OPTION" else .48),
        "breadth": breadth,
        "sector": side * .45,
        "liquidity": side * liq_score,
        "volatility": -side * max(0.0, vrisk - .65) * .65,
    }


def signal_quality(setup: Mapping[str, Any], dq: Mapping[str, Any], regime: Mapping[str, Any], vix: Mapping[str, Any]) -> Dict[str, Any]:
    base = f(setup.get("quality"), f(setup.get("score"), 50.0)) or 50.0
    status = str(setup.get("status") or setup.get("stage") or "").upper()
    if "READY" in status or "ENTRY ACTIVE" in status:
        base += 8
    elif "TRIGGER" in status:
        base += 4
    blockers = list(setup.get("blocked_by") or [])
    base -= min(30.0, len(blockers) * 8.0)
    dq_score = f(dq.get("score"), 50.0) or 50.0
    base = base * .78 + dq_score * .22
    vrisk = f(vix.get("risk_score"))
    if vrisk is not None and vrisk >= 80:
        base -= 8
    if str(regime.get("regime") or "").upper() == "INSUFFICIENT DATA":
        base -= 20
    score = clamp(base)
    return {"score": round(score, 1), "label": "HIGH" if score >= 78 else "MEDIUM" if score >= 62 else "LOW", "blockers": blockers}


def setup_lifecycle(signal_score: float, execution_score: float, uncertainty: float, dq_gate: str, late: Mapping[str, Any], original_status: str = "") -> str:
    s = str(original_status or "").upper()
    if dq_gate == "BLOCK" or late.get("severe"):
        return "INVALIDATED"
    if signal_score >= 80 and execution_score >= 70 and uncertainty <= 35 and not late.get("late"):
        return "READY"
    if signal_score >= 70 and execution_score >= 58 and uncertainty <= 48:
        return "CONFIRMING"
    if signal_score >= 58:
        return "FORMING"
    if any(x in s for x in ("ACTIVE", "READY", "TRIGGER")):
        return "WEAKENING"
    return "WATCH"


def qualify_setup(setup: Mapping[str, Any], dq: Mapping[str, Any], regime: Mapping[str, Any], vix: Mapping[str, Any]) -> Dict[str, Any]:
    sig = signal_quality(setup, dq, regime, vix)
    exe = execution_quality(setup)
    late = late_entry_check(setup)
    weights = adaptive_weights(str(regime.get("regime") or ""))
    resolver = contradiction_resolver(_setup_evidence(setup, regime, vix), weights)
    uncertainty = 20.0 + resolver["conflict_ratio"] * 42.0 + (100.0 - (f(dq.get("score"), 50.0) or 50.0)) * .32
    if str(regime.get("regime") or "").upper() in {"TRANSITION", "HIGH VOLATILITY"}:
        uncertainty += 8
    if late.get("late"):
        uncertainty += 10
    uncertainty = clamp(uncertainty)
    lifecycle = setup_lifecycle(sig["score"], exe["score"], uncertainty, str(dq.get("gate")), late, str(setup.get("status") or ""))

    action = str(setup.get("option_action") or setup.get("action") or "WAIT").upper()
    no_trade = []
    if dq.get("gate") == "BLOCK":
        no_trade.append("DATA QUALITY BLOCK")
    if sig["score"] < 70:
        no_trade.append("SIGNAL QUALITY BELOW READY THRESHOLD")
    if exe["score"] < 60:
        no_trade.append("EXECUTION QUALITY TOO LOW")
    if uncertainty > 50:
        no_trade.append("UNCERTAINTY HIGH")
    if (f(vix.get("risk_score")) or 0.0) >= 90:
        no_trade.append("VIX EXTREME RISK")
    if late.get("late"):
        no_trade.append("LATE / OVEREXTENDED ENTRY")
    if resolver["direction"] == "MIXED":
        no_trade.append("EVIDENCE CONFLICT")
    if sig.get("blockers"):
        no_trade.extend([str(x) for x in sig["blockers"][:3]])

    qualified = lifecycle == "READY" and not no_trade
    final_action = action if qualified and action not in {"WATCH", "WAIT", ""} else "NO TRADE" if no_trade else "WAIT"
    confidence = min(sig["score"], 100.0 - uncertainty * .55, exe["score"] + 12.0)
    confidence = clamp(confidence)
    band = "HIGH" if confidence >= 78 else "MEDIUM" if confidence >= 62 else "LOW"
    return {
        **dict(setup),
        "adaptive": {
            "signal_quality": sig,
            "execution_quality": exe,
            "late_entry": late,
            "resolver": resolver,
            "uncertainty_score": round(uncertainty, 1),
            "confidence_score": round(confidence, 1),
            "confidence_band": band,
            "lifecycle": lifecycle,
            "qualified": qualified,
            "final_action": final_action,
            "no_trade_reasons": list(dict.fromkeys(no_trade)),
            "weights": weights,
        },
    }


def risk_state(dq: Mapping[str, Any], vix: Mapping[str, Any], regime: Mapping[str, Any], setups: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    dq_score = f(dq.get("score"), 50.0) or 50.0
    vix_risk = f(vix.get("risk_score"), 50.0) if vix.get("available") else 50.0
    uncertainty = [f(((x.get("adaptive") or {}).get("uncertainty_score"))) for x in setups or []]
    uncertainty = [x for x in uncertainty if x is not None]
    avg_unc = statistics.fmean(uncertainty) if uncertainty else 50.0
    score = (100.0 - dq_score) * .45 + (vix_risk or 50.0) * .35 + avg_unc * .20
    score = clamp(score)
    if dq.get("gate") == "BLOCK" or score >= 78:
        state = "BLOCKED"
    elif score >= 60:
        state = "HIGH RISK"
    elif score >= 42:
        state = "CAUTION"
    else:
        state = "NORMAL"
    return {"state": state, "score": round(score, 1), "data_quality": dq_score, "vix_risk": vix_risk, "average_uncertainty": round(avg_unc, 1)}


def best_qualified_setup(setups: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    qualified = [dict(x) for x in setups or [] if bool((x.get("adaptive") or {}).get("qualified"))]
    if not qualified:
        return None
    qualified.sort(key=lambda x: (
        f((x.get("adaptive") or {}).get("confidence_score"), 0.0) or 0.0,
        f((x.get("adaptive") or {}).get("execution_quality", {}).get("score"), 0.0) or 0.0,
    ), reverse=True)
    return qualified[0]


def watchlist_priority(setups: Sequence[Mapping[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    rows = []
    for x in setups or []:
        a = x.get("adaptive") or {}
        score = (f(a.get("confidence_score"), 0.0) or 0.0) * .55 + (f((a.get("execution_quality") or {}).get("score"), 0.0) or 0.0) * .25 + (f((a.get("signal_quality") or {}).get("score"), 0.0) or 0.0) * .20
        rows.append({**dict(x), "priority_score": round(score, 1)})
    rows.sort(key=lambda x: f(x.get("priority_score"), 0.0) or 0.0, reverse=True)
    return rows[:max(1, int(limit))]


def what_changed(previous: Optional[Mapping[str, Any]], current: Mapping[str, Any]) -> List[Dict[str, Any]]:
    if not previous:
        return []
    out = []
    paths = [
        ("regime", ("market_regime", "regime")),
        ("risk", ("risk_state", "state")),
        ("vix", ("vix", "level")),
        ("vix_state", ("vix", "state")),
        ("data_gate", ("data_quality", "gate")),
        ("best_symbol", ("best_setup", "symbol")),
        ("best_action", ("best_setup", "adaptive", "final_action")),
    ]
    def pick(obj: Mapping[str, Any], path: Sequence[str]):
        cur: Any = obj
        for p in path:
            if not isinstance(cur, Mapping): return None
            cur = cur.get(p)
        return cur
    for label, path in paths:
        a, b = pick(previous, path), pick(current, path)
        if a != b and (a is not None or b is not None):
            out.append({"field": label, "from": a, "to": b})
    return out


def alert_severity(event: Mapping[str, Any]) -> str:
    field = str(event.get("field") or "")
    to = str(event.get("to") or "").upper()
    if field == "risk" and to == "BLOCKED":
        return "CRITICAL"
    if field == "data_gate" and to == "BLOCK":
        return "CRITICAL"
    if field == "best_action" and to in {"BUY", "SELL", "BUY CE", "BUY PE"}:
        return "TRADE READY"
    if field in {"regime", "vix_state", "risk"}:
        return "WATCH"
    return "INFO"


def calibration_summary(existing_accuracy: Mapping[str, Any], qualified_count: int, rejected_count: int) -> Dict[str, Any]:
    observed = f(existing_accuracy.get("execution_adjusted_precision_proxy_pct"))
    calibration = existing_accuracy.get("calibration") if isinstance(existing_accuracy.get("calibration"), Mapping) else {}
    sample = f((calibration or {}).get("sample") or existing_accuracy.get("resolved_take"), 0.0) or 0.0
    state = str((calibration or {}).get("status") or "INSUFFICIENT SAMPLE")
    return {
        "observed_precision_pct": observed,
        "resolved_sample": int(sample),
        "calibration_status": state,
        "qualified_now": int(qualified_count),
        "rejected_now": int(rejected_count),
        "policy": "Accuracy is measured on resolved out-of-sample/live observations; confidence is not a guarantee.",
    }


def correlation_guard(setups: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    groups = {
        "BANK": {"BANKNIFTY", "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK"},
        "INDEX": {"NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX"},
    }
    hits = []
    for name, members in groups.items():
        rows = [x for x in setups or [] if str(x.get("symbol") or "").upper() in members and bool((x.get("adaptive") or {}).get("qualified"))]
        if len(rows) >= 2:
            hits.append({"group": name, "count": len(rows), "symbols": [x.get("symbol") for x in rows], "warning": "Correlated exposure; not independent opportunities."})
    return {"warnings": hits, "status": "CAUTION" if hits else "CLEAR"}
