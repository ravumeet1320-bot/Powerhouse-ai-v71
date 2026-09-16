from __future__ import annotations

"""POWERHOUSE AI V73 LTS — Institutional Intelligence OS.

Additive orchestration layer over the proven V72.2 engine. The design goal is
maximum opportunity coverage with truthful data, lower latency, stronger execution
planning, and auditable alerts. This module remains read-only: it never places orders.
"""

import math
import statistics
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from v72_2_engine import build_v72, pre_move_radar

VERSION = "73.0"
RELEASE = "73.0-lts-institutional-intelligence"
_LOCK = threading.RLock()
_CANDIDATE_HISTORY: Dict[str, deque] = defaultdict(lambda: deque(maxlen=900))
_ALERT_HISTORY: deque = deque(maxlen=1200)
_LAST_ALERT_SIG: Dict[str, float] = {}

TAB_ARCHITECTURE = [
    {"id":"home","label":"HOME","title":"Command Center","subtabs":["Market Regime","P0 Hero","Pre-Move","Circuit","Breadth","System"]},
    {"id":"opportunities","label":"OPPORTUNITIES","title":"Opportunity OS","subtabs":["Hero","Pre-Move Radar","Circuit Hunter","Scanners","Watchlist"]},
    {"id":"execution","label":"EXECUTION","title":"Execution OS","subtabs":["Execution Plan","Live Thesis","Chart","Dynamic Targets","Re-entry","Alerts"]},
    {"id":"market","label":"MARKET","title":"Market Intelligence","subtabs":["Trend","Heatmap","Sectors","Breadth","Global","Events"]},
    {"id":"derivatives","label":"DERIVATIVES","title":"Derivatives Intelligence","subtabs":["Options","OI","Futures","Greeks","Expiry Intelligence"]},
    {"id":"money-flow","label":"MONEY FLOW","title":"Money Flow OS","subtabs":["Volume Pulse","Depth DOM","Smart Money","Institutional Flow"]},
    {"id":"intelligence","label":"INTELLIGENCE","title":"Unified Market Brain","subtabs":["Regime Brain","Scenario Engine","Leader/Follower","Relative Strength","Risk Brain","Data Quality"]},
    {"id":"lab-system","label":"LAB & SYSTEM","title":"Audit & Reliability","subtabs":["Replay","Forensics","Missed Moves","False Signals","Shadow Engine","System Health"]},
]

LOCKED_FEATURES = {
    "dual_theme_large_readable_ui": True,
    "unified_market_brain": True,
    "whole_fno_opportunity_coverage": True,
    "fastpath_priority_scheduler": True,
    "pre_move_state_machine": True,
    "hero_call_put_execution_plan": True,
    "dynamic_entry_sl_targets": True,
    "target_expansion_from_oi_volume_depth_chart": True,
    "runner_and_reentry_logic": True,
    "circuit_hunter_before_lock": True,
    "volume_pulse": True,
    "market_depth_dom": True,
    "smart_money_footprint": True,
    "official_institutional_flow_only_when_attributable": True,
    "oi_pcr_wall_migration": True,
    "sector_breadth_leader_follower": True,
    "market_regime_and_event_risk": True,
    "alerts_p0_p3": True,
    "coverage_sentinel": True,
    "missed_trade_audit": True,
    "replay_forensics_shadow_mode": True,
    "data_freshness_quality_lineage": True,
    "zero_fake_data": True,
    "read_only_no_auto_orders": True,
}


def _f(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(v)))


def _rows(snapshot: dict) -> List[dict]:
    out: List[dict] = []
    for key in ("fno_universe", "sector_data", "stocks", "stock_rows", "sector_heatmap"):
        val = snapshot.get(key)
        if isinstance(val, list):
            out.extend(x for x in val if isinstance(x, dict))
    ded: Dict[str, dict] = {}
    for r in out:
        sym = str(r.get("symbol") or r.get("tradingsymbol") or "").upper().strip()
        if not sym:
            continue
        prev = ded.get(sym, {})
        ded[sym] = {**prev, **r, "symbol": sym}
    return list(ded.values())


def _depth_levels(row: dict) -> List[dict]:
    levels = row.get("depth_levels") or row.get("market_depth") or []
    return [x for x in levels if isinstance(x, dict)] if isinstance(levels, list) else []


def depth_dom_intelligence(row: dict) -> dict:
    """Truthful depth analytics from supplied levels / total quantities only."""
    levels = _depth_levels(row)
    buy = _f(row.get("total_buy_qty"), _f(row.get("total_buy_quantity")))
    sell = _f(row.get("total_sell_qty"), _f(row.get("total_sell_quantity")))
    if buy is None and levels:
        buy = sum(_f(x.get("bid_qty"), 0.0) or 0.0 for x in levels)
    if sell is None and levels:
        sell = sum(_f(x.get("ask_qty"), 0.0) or 0.0 for x in levels)
    bid = _f(row.get("bid"))
    ask = _f(row.get("ask"))
    if bid is None and levels:
        bid = _f(levels[0].get("bid"))
    if ask is None and levels:
        ask = _f(levels[0].get("ask"))
    ltp = _f(row.get("ltp"))
    spread_pct = ((ask - bid) / ltp * 100.0) if ltp and bid is not None and ask is not None and ask >= bid else None
    ratio = (buy / sell) if buy is not None and sell and sell > 0 else (999.0 if buy and (sell == 0) else None)
    pressure = None
    if buy is not None and sell is not None and buy + sell > 0:
        pressure = 100.0 * buy / (buy + sell)
    elif levels:
        b = sum(_f(x.get("bid_qty"), 0.0) or 0.0 for x in levels)
        a = sum(_f(x.get("ask_qty"), 0.0) or 0.0 for x in levels)
        if b + a > 0:
            pressure = 100.0 * b / (b + a)
    bias = "BUY" if pressure is not None and pressure >= 62 else "SELL" if pressure is not None and pressure <= 38 else "BALANCED"
    top = levels[:5]
    buy_wall = max(top, key=lambda x: _f(x.get("bid_qty"), 0.0) or 0.0, default={})
    sell_wall = max(top, key=lambda x: _f(x.get("ask_qty"), 0.0) or 0.0, default={})
    return {
        "status": "READY" if any(x is not None for x in (buy, sell, bid, ask)) else "UNAVAILABLE",
        "levels": len(levels), "top_levels": top,
        "total_buy_qty": buy, "total_sell_qty": sell,
        "buy_sell_ratio": round(ratio, 3) if ratio is not None and ratio < 998 else ("BUY_ONLY" if ratio else None),
        "pressure": round(pressure, 1) if pressure is not None else None,
        "bias": bias,
        "best_bid": bid, "best_ask": ask,
        "spread_pct": round(spread_pct, 3) if spread_pct is not None else None,
        "buy_wall": buy_wall or None, "sell_wall": sell_wall or None,
        "policy": "Displayed orders can change or be cancelled; depth is evidence, not proof of institutional identity.",
    }


def volume_pulse(row: dict) -> dict:
    ltp = _f(row.get("ltp"))
    volume = _f(row.get("volume"))
    rvol = _f(row.get("rvol"))
    chg = _f(row.get("change_pct"), 0.0) or 0.0
    avg = _f(row.get("avg_volume_20d"), _f(row.get("average_volume")))
    if rvol is None and volume is not None and avg and avg > 0:
        rvol = volume / avg
    turnover = (ltp * volume) if ltp is not None and volume is not None else None
    score = 0.0
    if rvol is not None:
        score += _clamp((rvol - 0.75) * 32, 0, 62)
    score += _clamp(abs(chg) * 8, 0, 26)
    if turnover and turnover >= 1e9:
        score += 8
    state = "IGNITION" if score >= 75 else "BUILDING" if score >= 55 else "ACTIVE" if score >= 35 else "NORMAL"
    return {
        "status": "READY" if volume is not None else "UNAVAILABLE",
        "volume": volume, "rvol": round(rvol, 2) if rvol is not None else None,
        "turnover_estimate": round(turnover, 2) if turnover is not None else None,
        "change_pct": round(chg, 3), "score": round(_clamp(score), 1), "state": state,
    }


def _circuit_limits(row: dict) -> tuple[Optional[float], Optional[float]]:
    uc = _f(row.get("upper_circuit_limit"), _f(row.get("upper_circuit"), _f(row.get("uc"))))
    lc = _f(row.get("lower_circuit_limit"), _f(row.get("lower_circuit"), _f(row.get("lc"))))
    return uc, lc


def circuit_candidate(row: dict) -> dict:
    ltp = _f(row.get("ltp"))
    uc, lc = _circuit_limits(row)
    if ltp is None or uc is None or uc <= 0:
        return {"status":"UNAVAILABLE","symbol":str(row.get("symbol") or ""),"reason":"Upper circuit limit not supplied by live quote"}
    distance = max(0.0, (uc - ltp) / max(abs(ltp), 1e-9) * 100.0)
    depth = depth_dom_intelligence(row)
    vol = volume_pulse(row)
    chg = _f(row.get("change_pct"), 0.0) or 0.0
    dp = _f(depth.get("pressure"), 50.0) or 50.0
    rvol = _f(vol.get("rvol"), 1.0) or 1.0
    proximity = _clamp(100 - distance * 22)
    depth_score = _clamp((dp - 50) * 2.2 + 50)
    volume_score = _clamp((rvol - 0.7) * 32)
    momentum_score = _clamp(max(0, chg) * 11)
    score = proximity * .43 + depth_score * .24 + volume_score * .20 + momentum_score * .13
    ratio = depth.get("buy_sell_ratio")
    buy_only = ratio == "BUY_ONLY"
    if buy_only:
        score += 5
    score = _clamp(score)
    if distance <= .30 and score >= 82:
        state = "LOCK IMMINENT"
    elif distance <= 1.2 and score >= 72:
        state = "PRE-CIRCUIT"
    elif distance <= 2.8 and score >= 58:
        state = "ARMING"
    elif distance <= 5.0:
        state = "WATCH"
    else:
        state = "DISTANT"
    return {
        "status":"READY","symbol":str(row.get("symbol") or ""),"ltp":ltp,"upper_circuit":uc,"lower_circuit":lc,
        "distance_to_uc_pct":round(distance,3),"pressure_score":round(score,1),"state":state,
        "depth":depth,"volume":vol,"change_pct":round(chg,3),
        "do_not_chase": bool(distance <= .25 and state != "LOCK IMMINENT"),
        "policy":"Pre-circuit state is an evidence score, not a guarantee that the security will hit or remain at its upper band.",
    }


def circuit_hunter(snapshot: dict, limit: int = 40) -> dict:
    rows = _rows(snapshot)
    out = [circuit_candidate(r) for r in rows]
    ready = [x for x in out if x.get("status") == "READY" and x.get("state") != "DISTANT"]
    rank = {"LOCK IMMINENT":5,"PRE-CIRCUIT":4,"ARMING":3,"WATCH":2,"DISTANT":1}
    ready.sort(key=lambda x:(rank.get(str(x.get("state")),0), _f(x.get("pressure_score"),0) or 0, -(_f(x.get("distance_to_uc_pct"),99) or 99)), reverse=True)
    return {
        "status":"READY" if ready else "UNAVAILABLE","version":VERSION,"universe_observed":len(rows),
        "circuit_data_ready":sum(1 for x in out if x.get("status") == "READY"),
        "candidates":ready[:max(1, min(int(limit), 200))],
        "counts":{s:sum(1 for x in ready if x.get("state")==s) for s in ("LOCK IMMINENT","PRE-CIRCUIT","ARMING","WATCH")},
        "source_policy":"Uses numeric live circuit limits supplied by the market-data provider. NSE/Dhan/Screener may be used as separate confirmation/discovery adapters, never as fabricated fallback values.",
    }


def _remember_candidates(rows: Iterable[dict]) -> dict:
    now = time.time()
    revived = []
    accelerating = []
    with _LOCK:
        for r in rows:
            sym = str(r.get("symbol") or "").upper()
            if not sym:
                continue
            score = _f(r.get("pre_move_score"), _f(r.get("score"), 0.0)) or 0.0
            stage = str(r.get("pre_move_stage") or r.get("stage") or "SCANNING")
            h = _CANDIDATE_HISTORY[sym]
            prior = h[-1] if h else None
            h.append({"t":now,"score":score,"stage":stage,"ltp":_f(r.get("ltp"))})
            if prior:
                dt = max(1.0, now - prior["t"])
                velocity = (score - prior["score"]) * 60.0 / dt
                if velocity >= 4:
                    accelerating.append({"symbol":sym,"score":round(score,1),"velocity_per_min":round(velocity,2),"stage":stage})
                weak = prior["stage"] in ("SCANNING","WATCH","EARLY CLUE","BUILDING")
                strong = stage in ("ARMING","TRIGGER READY")
                if weak and strong:
                    revived.append({"symbol":sym,"from":prior["stage"],"to":stage,"score":round(score,1)})
        # Age out histories for symbols not seen for a trading-day scale window.
        for sym in list(_CANDIDATE_HISTORY):
            h = _CANDIDATE_HISTORY[sym]
            if not h or now - h[-1]["t"] > 86400:
                _CANDIDATE_HISTORY.pop(sym, None)
    accelerating.sort(key=lambda x:x["velocity_per_min"], reverse=True)
    return {"tracked_symbols":len(_CANDIDATE_HISTORY),"revived":revived[:20],"accelerating":accelerating[:30]}


def opportunity_coverage(snapshot: dict, radar: Optional[dict] = None) -> dict:
    radar = radar or pre_move_radar(snapshot, record=False)
    rows = radar.get("rows") or []
    expected = int(radar.get("expected_universe") or 0)
    observed = int(radar.get("observed") or len(rows))
    fresh = sum(1 for r in rows if (_f(r.get("quote_age_sec"), 999) or 999) <= 10)
    depth_ready = sum(1 for r in rows if (r.get("depth_intelligence") or {}).get("pressure") is not None or depth_dom_intelligence(r).get("status") == "READY")
    oi_ready = sum(1 for r in rows if r.get("futures_oi_change_pct") is not None or (r.get("oi_state") or {}).get("state") not in (None,"UNAVAILABLE"))
    circuit_ready = sum(1 for r in _rows(snapshot) if _circuit_limits(r)[0] is not None)
    memory = _remember_candidates(rows)
    return {
        "expected":expected,"observed":observed,"coverage_pct":round(100*observed/expected,1) if expected else (100.0 if observed else 0.0),
        "fresh_under_10s":fresh,"freshness_pct":round(100*fresh/len(rows),1) if rows else 0.0,
        "depth_ready":depth_ready,"oi_ready":oi_ready,"circuit_limit_ready":circuit_ready,
        "stages":radar.get("stages") or {},"memory":memory,
        "coverage_state":"FULL" if expected and observed>=expected and fresh>=max(1,int(observed*.95)) else "PARTIAL" if observed else "WARMING",
        "policy":"Every expected symbol should be accounted for. Missing/stale coverage is exposed instead of silently treated as a neutral signal.",
    }


def _reachability(score: float) -> str:
    return "HIGH" if score >= 78 else "MEDIUM" if score >= 60 else "LOW"


def hero_execution_plan(symbol: str, underlying: dict, strike_pack: dict, chart: Optional[dict] = None) -> dict:
    winner = (strike_pack or {}).get("winner") or {}
    if not winner:
        return {"status":"NO TRADE","symbol":symbol.upper(),"hero_state":(strike_pack or {}).get("hero_state") or "NO TRADE","reason":(strike_pack or {}).get("why_not_hero") or ["No aligned liquid strike"],"read_only":True}
    premium = _f(winner.get("premium"))
    if premium is None or premium <= 0:
        return {"status":"NO TRADE","symbol":symbol.upper(),"reason":["Winner has no numeric premium"],"read_only":True}
    scores = winner.get("scores") or {}
    liquidity = _f(winner.get("liquidity"), _f(scores.get("liquidity"), 50.0)) or 50.0
    spread = _f(winner.get("spread_pct"), 1.0) or 1.0
    theta_risk = _f(scores.get("theta_risk"), 35.0) or 35.0
    oi_flow = _f(scores.get("oi_flow"), 50.0) or 50.0
    premium_response = _f(scores.get("premium_response"), 50.0) or 50.0
    gamma = _f(scores.get("gamma"), 50.0) or 50.0
    hero_score = _f(winner.get("score"), 0.0) or 0.0
    base_score = _f(underlying.get("pre_move_score"), _f(underlying.get("score"), 50.0)) or 50.0
    depth = underlying.get("depth_intelligence") or depth_dom_intelligence(underlying)
    depth_pressure = _f(depth.get("pressure"), 50.0) or 50.0
    side = str(winner.get("side") or underlying.get("v72_side") or "WAIT")
    side_depth = depth_pressure if side == "CE" else (100-depth_pressure if side == "PE" else 50)

    entry_width_pct = _clamp(max(spread * 0.75, 0.35), 0.35, 2.2)
    ideal = premium
    entry_low = premium * (1 - entry_width_pct / 200)
    entry_high = premium * (1 + entry_width_pct / 200)
    risk_pct = 8.0 + max(0, spread-1.0)*0.45 + max(0, theta_risk-45)*0.035 + max(0, 60-liquidity)*0.06
    risk_pct = _clamp(risk_pct, 6.0, 16.0)
    stop = premium * (1-risk_pct/100)
    r = max(premium-stop, premium*.02)

    expansion_strength = (
        oi_flow*.22 + premium_response*.24 + liquidity*.18 + gamma*.10 + base_score*.16 + side_depth*.10
    )
    if strike_pack.get("multi_strike_confirmation"):
        expansion_strength += 5
    expansion_strength = _clamp(expansion_strength)
    rr1, rr2, rr3 = 1.25, 2.1, 3.15
    t1, t2, t3 = premium+r*rr1, premium+r*rr2, premium+r*rr3
    extension = None
    extension_state = "LOCKED"
    if expansion_strength >= 78 and oi_flow >= 62 and premium_response >= 62:
        extension = premium + r * (3.7 + (expansion_strength-78)/18)
        extension_state = "ARMED" if expansion_strength < 88 else "ACTIVE"

    trigger = _f(underlying.get("trigger_price"), _f(underlying.get("ltp")))
    invalid = None
    vwap = _f(underlying.get("vwap"))
    pdh = _f(underlying.get("prev_day_high")); pdl = _f(underlying.get("prev_day_low"))
    ltp = _f(underlying.get("ltp"))
    if side == "CE":
        cands = [x for x in (vwap, pdl, ltp*(1-.006) if ltp else None) if x is not None and (ltp is None or x < ltp)]
        invalid = max(cands) if cands else None
    elif side == "PE":
        cands = [x for x in (vwap, pdh, ltp*(1+.006) if ltp else None) if x is not None and (ltp is None or x > ltp)]
        invalid = min(cands) if cands else None

    chart_state = None
    chart_score = None
    chart_evidence: List[str] = []
    if isinstance(chart, dict):
        chart_state = chart.get("stage") or chart.get("status")
        chart_score = _f(chart.get("score"))
        chart_evidence = list(chart.get("leading_evidence") or [])[:6]
        if chart_score is not None and str(chart.get("side")) == side:
            expansion_strength = _clamp(expansion_strength*.85 + chart_score*.15)

    do_not_chase_above = premium * (1 + max(2.2, risk_pct*.30)/100)
    time_stop_min = 6 if theta_risk >= 70 else 8 if theta_risk >= 45 else 12
    state = str((strike_pack or {}).get("hero_state") or "TRIGGER READY")
    return {
        "status":"READY","version":VERSION,"symbol":symbol.upper(),"hero_state":state,"side":side,
        "strike":winner.get("strike"),"expiry":winner.get("expiry") or strike_pack.get("expiry"),"premium":round(premium,2),
        "entry":{"low":round(entry_low,2),"ideal":round(ideal,2),"high":round(entry_high,2),"do_not_chase_above":round(do_not_chase_above,2),"underlying_trigger":round(trigger,2) if trigger is not None else None},
        "risk":{"premium_sl":round(stop,2),"risk_pct":round(risk_pct,2),"underlying_invalidation":round(invalid,2) if invalid is not None else None,"time_stop_min":time_stop_min},
        "targets":{"t1":round(t1,2),"t2":round(t2,2),"t3":round(t3,2),"extended":round(extension,2) if extension is not None else None,"extension_state":extension_state,"expansion_strength":round(expansion_strength,1)},
        "reachability":{"t1":_reachability(hero_score+8),"t2":_reachability(hero_score),"t3":_reachability(expansion_strength),"extended":_reachability(expansion_strength-8) if extension is not None else "LOCKED"},
        "evidence":{"hero_score":round(hero_score,1),"underlying_score":round(base_score,1),"oi_flow":round(oi_flow,1),"premium_response":round(premium_response,1),"liquidity":round(liquidity,1),"depth_side_support":round(side_depth,1),"gamma":round(gamma,1),"multi_strike":bool(strike_pack.get("multi_strike_confirmation")),"chart_state":chart_state,"chart_score":round(chart_score,1) if chart_score is not None else None,"chart_evidence":chart_evidence},
        "management":{"after_t1":"Move SL toward cost only if premium response and underlying structure remain intact.","runner":"Enable runner only while OI/premium/depth/sector evidence remains supportive.","reentry":"Evidence-supported pullback/retest only; never average down."},
        "read_only":True,
        "policy":"Entry/SL/targets are decision-support levels derived from current data, not guaranteed fills or returns. Target expansion requires stronger OI + premium + liquidity evidence.",
    }


def _alert(priority: str, kind: str, symbol: str, title: str, data: dict, ttl: int = 45) -> Optional[dict]:
    now = time.time()
    sig = f"{priority}|{kind}|{symbol}|{title}"
    with _LOCK:
        if now - _LAST_ALERT_SIG.get(sig, 0.0) < ttl:
            return None
        _LAST_ALERT_SIG[sig] = now
        item = {"id":f"V73-{int(now*1000)}-{len(_ALERT_HISTORY)}","epoch":now,"priority":priority,"kind":kind,"symbol":symbol,"title":title,"data":data}
        _ALERT_HISTORY.append(item)
        return item


def alert_os(snapshot: dict, base: Optional[dict] = None, circuits: Optional[dict] = None) -> dict:
    base = base or build_v72(snapshot, record=False)
    rows = base.get("pre_move_rows") or []
    circuits = circuits or circuit_hunter(snapshot)
    fresh: List[dict] = []
    for r in rows[:80]:
        sym = str(r.get("symbol") or "")
        stage = str(r.get("pre_move_stage") or "")
        score = _f(r.get("pre_move_score"),0) or 0
        if stage == "TRIGGER READY":
            x=_alert("P1","TRIGGER_READY",sym,f"{sym} trigger ready",{"score":round(score,1),"side":r.get("v72_side"),"countdown":r.get("trigger_countdown")},30)
            if x:fresh.append(x)
        elif stage == "ARMING":
            x=_alert("P2","ARMING",sym,f"{sym} arming",{"score":round(score,1),"side":r.get("v72_side")},60)
            if x:fresh.append(x)
        fs=r.get("fast_signal") or {}
        if fs.get("tier") == "CONFIRMED":
            x=_alert("P0","FAST_CONFIRMED",sym,f"{sym} fast confirmed",{"score":round(score,1),"side":r.get("v72_side"),"fast_signal":fs},30)
            if x:fresh.append(x)
    for c in (circuits.get("candidates") or [])[:30]:
        state=c.get("state"); sym=str(c.get("symbol") or "")
        if state=="LOCK IMMINENT": pri="P0"
        elif state=="PRE-CIRCUIT": pri="P1"
        elif state=="ARMING": pri="P2"
        else: continue
        x=_alert(pri,"CIRCUIT",sym,f"{sym} {state}",{"distance_to_uc_pct":c.get("distance_to_uc_pct"),"pressure_score":c.get("pressure_score")},45)
        if x:fresh.append(x)
    with _LOCK:
        all_items=list(_ALERT_HISTORY)
    return {
        "status":"READY","version":VERSION,"new":fresh,
        "items":list(reversed(all_items[-200:])),
        "counts":{p:sum(1 for x in all_items[-200:] if x.get("priority")==p) for p in ("P0","P1","P2","P3")},
        "policy":"P0 is reserved for actionable/critical state changes; lower-priority discovery stays quieter to reduce alert fatigue.",
    }


def data_quality(snapshot: dict, base: dict, coverage: dict) -> dict:
    latency = base.get("latency_guard") or {}
    ws = snapshot.get("websocket_connected")
    feed_age = _f(latency.get("feed_lag_sec"))
    fresh = _f(coverage.get("freshness_pct"),0) or 0
    cov = _f(coverage.get("coverage_pct"),0) or 0
    score = cov*.40 + fresh*.40 + (100 if ws else 62)*.20
    if feed_age is not None and feed_age > 10:
        score -= min(30,(feed_age-10)*2)
    score=_clamp(score)
    return {
        "score":round(score,1),"state":"EXCELLENT" if score>=92 else "GOOD" if score>=80 else "DEGRADED" if score>=60 else "UNSAFE",
        "websocket_connected":ws,"feed_lag_sec":feed_age,"coverage_pct":cov,"freshness_pct":fresh,
        "actionable_allowed":bool(score>=60 and latency.get("state") not in ("STALE",)),
        "policy":"Missing/stale data lowers quality or blocks actionability; it is never backfilled with invented live values.",
    }


def build_v73(snapshot: dict, record: bool = True) -> dict:
    t0=time.perf_counter()
    base=build_v72(snapshot,record=record)
    radar={**(base.get("pre_move_radar") or {}),"rows":base.get("pre_move_rows") or []}
    coverage=opportunity_coverage(snapshot,radar)
    circuits=circuit_hunter(snapshot)
    alerts=alert_os(snapshot,base,circuits)
    quality=data_quality(snapshot,base,coverage)
    rows=base.get("pre_move_rows") or []
    p0=[r for r in rows if (r.get("fast_signal") or {}).get("tier")=="CONFIRMED" and not r.get("late_entry")]
    p1=[r for r in rows if r.get("pre_move_stage")=="TRIGGER READY" and not r.get("late_entry")]
    p2=[r for r in rows if r.get("pre_move_stage")=="ARMING"]
    total_ms=(time.perf_counter()-t0)*1000
    return {
        "version":VERSION,"release":RELEASE,"name":"POWERHOUSE AI V73 LTS — Institutional Intelligence OS",
        "generated_at":datetime.now(timezone.utc).isoformat(),"read_only":True,"execution_enabled":False,
        "tabs":TAB_ARCHITECTURE,"locked_features":LOCKED_FEATURES,
        "command_center":{
            "p0":len(p0),"p1":len(p1),"p2":len(p2),"best":(p0 or p1 or p2 or rows[:1] or [None])[0],
            "circuit_best":(circuits.get("candidates") or [None])[0],"coverage":coverage,"data_quality":quality,
            "market_regime":((base.get("base_v71") or {}).get("base_v70") or {}).get("market_regime") or (base.get("ai_brain") or {}).get("state"),
        },
        "opportunity_coverage":coverage,"circuit_hunter":circuits,"alerts":alerts,"data_quality":quality,
        "base_v72":base,
        "performance":{"orchestration_ms":round(total_ms,2),"base_pipeline":base.get("latency_guard")},
        "truth_policy":[
            "No system can guarantee capture of every profitable trade; V73 optimizes coverage, lead time and precision while auditing misses.",
            "No stale/unavailable value is labelled LIVE and no institutional identity is inferred without attributable source data.",
            "P0/P1/P2/P3 are attention priorities, not profit probabilities.",
            "All outputs are read-only market intelligence; no automatic order placement is enabled.",
        ],
    }
