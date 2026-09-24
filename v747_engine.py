from __future__ import annotations

"""POWERHOUSE AI V74.7 — Whole-Market Move Intelligence.

Additive decision-support layer over V74.6. It is designed to discover observable
market anomalies early, in both directions, and to keep discovery separate from
trade qualification. It never guarantees that every profitable move can be
predicted or captured and it never places broker orders.
"""

import math
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

VERSION = "74.7"
RELEASE = "74.7-whole-market-move-intelligence-master"

STAGES = (
    "DISCOVERY", "PRE-MOVE", "BUILDING", "ACCELERATING", "TRIGGER NEAR",
    "ENTRY READY", "MOVE ACTIVE", "PULLBACK / RETEST", "SECOND LEG", "EXHAUSTION",
)

ALERT_SEVERITY = {
    "DISCOVERY": "WATCH", "PRE-MOVE": "SETUP", "BUILDING": "SETUP",
    "ACCELERATING": "SETUP", "TRIGGER NEAR": "TRADE READY",
    "ENTRY READY": "TRADE READY", "MOVE ACTIVE": "WATCH",
    "PULLBACK / RETEST": "SETUP", "SECOND LEG": "TRADE READY", "EXHAUSTION": "WATCH",
}


def f(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if v is None or v == "":
            return default
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def clamp(x: Any, lo: float = 0.0, hi: float = 100.0) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except Exception:
        return lo


def pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b in (None, 0):
        return None
    return (a - b) / abs(b) * 100.0


def _hist_point(history: Sequence[Mapping[str, Any]], seconds: float) -> Optional[Mapping[str, Any]]:
    if not history:
        return None
    now = float(history[-1].get("t") or time.time())
    target = now - seconds
    prior = None
    for x in reversed(history):
        prior = x
        if float(x.get("t") or 0) <= target:
            return x
    return prior


def _velocity(history: Sequence[Mapping[str, Any]], seconds: float, key: str) -> Optional[float]:
    if len(history) < 2:
        return None
    cur = f(history[-1].get(key))
    old_row = _hist_point(history, seconds)
    old = f((old_row or {}).get(key))
    return pct(cur, old)


def _delta_rate(history: Sequence[Mapping[str, Any]], seconds: float, key: str) -> Optional[float]:
    if len(history) < 2:
        return None
    cur_row = history[-1]
    old_row = _hist_point(history, seconds)
    if not old_row:
        return None
    cur = f(cur_row.get(key))
    old = f(old_row.get(key))
    dt = max(1.0, float(cur_row.get("t") or 0) - float(old_row.get("t") or 0))
    if cur is None or old is None:
        return None
    return (cur - old) / dt


def _depth(row: Mapping[str, Any]) -> Dict[str, Any]:
    buy = f(row.get("total_buy_qty"), f(row.get("total_buy_quantity")))
    sell = f(row.get("total_sell_qty"), f(row.get("total_sell_quantity")))
    levels = row.get("depth_levels") or []
    if buy is None and isinstance(levels, list):
        buy = sum(f((x or {}).get("bid_qty"), 0.0) or 0.0 for x in levels if isinstance(x, dict))
    if sell is None and isinstance(levels, list):
        sell = sum(f((x or {}).get("ask_qty"), 0.0) or 0.0 for x in levels if isinstance(x, dict))
    bid = f(row.get("bid"))
    ask = f(row.get("ask"))
    ltp = f(row.get("ltp"))
    pressure = None
    if buy is not None and sell is not None and buy + sell > 0:
        pressure = 100.0 * buy / (buy + sell)
    ratio = None
    if buy is not None and sell is not None:
        ratio = buy / sell if sell > 0 else (999.0 if buy > 0 else None)
    spread = ((ask - bid) / ltp * 100.0) if ltp and bid is not None and ask is not None and ask >= bid else None
    return {
        "buy_qty": buy, "sell_qty": sell,
        "pressure": round(pressure, 1) if pressure is not None else None,
        "ratio": round(ratio, 3) if ratio is not None and ratio < 998 else ("BUY_ONLY" if ratio else None),
        "spread_pct": round(spread, 4) if spread is not None else None,
        "levels": len(levels) if isinstance(levels, list) else 0,
    }


def _time_of_day_pace(volume: Optional[float], now_epoch: Optional[float] = None) -> Optional[float]:
    if volume is None:
        return None
    import datetime as _dt
    from zoneinfo import ZoneInfo
    dt = _dt.datetime.fromtimestamp(float(now_epoch or time.time()), ZoneInfo("Asia/Kolkata"))
    mins = (dt.hour * 60 + dt.minute + dt.second / 60.0) - (9 * 60 + 15)
    if mins <= 0:
        return None
    return volume / mins


def classify_row(row: Mapping[str, Any], history: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    symbol = str(row.get("symbol") or row.get("tradingsymbol") or "").upper().strip()
    ltp = f(row.get("ltp"))
    cp = f(row.get("cp"), f(row.get("prev_close")))
    chg = f(row.get("change_pct"), pct(ltp, cp))
    vol = f(row.get("volume"))
    op = f(row.get("day_open"), f(row.get("open")))
    hi = f(row.get("day_high"), f(row.get("high")))
    lo = f(row.get("day_low"), f(row.get("low")))
    rvol = f(row.get("rvol"))
    avg20 = f(row.get("avg_volume_20d"), f(row.get("average_volume")))
    if rvol is None and vol is not None and avg20 and avg20 > 0:
        rvol = vol / avg20
    dep = _depth(row)
    p15 = _velocity(history, 15, "ltp")
    p30 = _velocity(history, 30, "ltp")
    p60 = _velocity(history, 60, "ltp")
    p180 = _velocity(history, 180, "ltp")
    p300 = _velocity(history, 300, "ltp")
    p900 = _velocity(history, 900, "ltp")
    vps15 = _delta_rate(history, 15, "volume")
    vps60 = _delta_rate(history, 60, "volume")
    tvps15 = (vps15 * ltp) if vps15 is not None and ltp is not None else None
    tvps60 = (vps60 * ltp) if vps60 is not None and ltp is not None else None
    turnover = (vol * ltp) if vol is not None and ltp is not None else None
    pace = _time_of_day_pace(vol)

    open_low = ((op - lo) / op * 100.0) if op and lo is not None and op > 0 else None
    high_open = ((hi - op) / op * 100.0) if op and hi is not None and op > 0 else None
    recovery = ((ltp - lo) / lo * 100.0) if ltp and lo and lo > 0 else None
    fall_from_high = ((hi - ltp) / hi * 100.0) if ltp and hi and hi > 0 else None
    high_attack = ((hi - ltp) / ltp * 100.0) if ltp and hi and ltp > 0 else None
    low_attack = ((ltp - lo) / ltp * 100.0) if ltp and lo and ltp > 0 else None

    up_evidence: List[str] = []
    dn_evidence: List[str] = []
    up = dn = activity = 0.0

    for name, val, weight in (("15s", p15, 18), ("30s", p30, 20), ("60s", p60, 24), ("3m", p180, 18)):
        if val is None:
            continue
        activity += min(weight, abs(val) * weight * 2.2)
        if val > 0:
            up += min(weight, val * weight * 2.2)
            if abs(val) >= .12:
                up_evidence.append(f"{name} price +{val:.2f}%")
        elif val < 0:
            dn += min(weight, abs(val) * weight * 2.2)
            if abs(val) >= .12:
                dn_evidence.append(f"{name} price {val:.2f}%")

    if chg is not None:
        activity += min(22, abs(chg) * 4.5)
        if chg > 0:
            up += min(18, chg * 3.6)
        elif chg < 0:
            dn += min(18, abs(chg) * 3.6)

    pressure = f(dep.get("pressure"))
    if pressure is not None:
        if pressure >= 58:
            up += min(18, (pressure - 50) * .8)
            if pressure >= 66:
                up_evidence.append(f"book pressure {pressure:.0f}% BUY")
        elif pressure <= 42:
            dn += min(18, (50 - pressure) * .8)
            if pressure <= 34:
                dn_evidence.append(f"book pressure {100-pressure:.0f}% SELL")

    if rvol is not None:
        activity += min(25, max(0, rvol - .8) * 10)
        if rvol >= 1.8:
            (up_evidence if up >= dn else dn_evidence).append(f"RVOL {rvol:.2f}x")

    if tvps15 is not None:
        tv_abs = abs(tvps15)
        if tv_abs >= 2_000_000:
            activity += min(24, 8 + math.log10(max(tv_abs, 1)) * 2)
            (up_evidence if up >= dn else dn_evidence).append(f"turnover velocity ₹{tv_abs/1e6:.1f}m/s")

    if open_low is not None and open_low <= .12 and chg is not None and chg > .25:
        up += 12; up_evidence.append("OPEN≈LOW")
    if high_open is not None and high_open <= .12 and chg is not None and chg < -.25:
        dn += 12; dn_evidence.append("OPEN≈HIGH")
    if recovery is not None and recovery >= 2.0:
        up += min(18, recovery * 2); up_evidence.append(f"recovery +{recovery:.2f}% from low")
    if fall_from_high is not None and fall_from_high >= 2.0:
        dn += min(18, fall_from_high * 2); dn_evidence.append(f"fall {fall_from_high:.2f}% from high")

    spread = f(dep.get("spread_pct"))
    execution_quality = 70.0
    if spread is not None:
        execution_quality = clamp(100 - spread * 220)
    if turnover is not None:
        if turnover >= 1_000_000_000: execution_quality += 12
        elif turnover >= 250_000_000: execution_quality += 7
        elif turnover < 10_000_000: execution_quality -= 18
    execution_quality = clamp(execution_quality)

    signed = up - dn
    direction = "UP" if signed >= 8 else "DOWN" if signed <= -8 else "NEUTRAL"
    directional_score = clamp(50 + signed * .8)
    anomaly = clamp(activity + max(up, dn) * .55)
    max_short = max([abs(x) for x in (p15, p30, p60) if x is not None] or [0.0])
    exceptional = bool(
        max_short >= .28 or (rvol is not None and rvol >= 2.2) or
        (tvps15 is not None and abs(tvps15) >= 2_000_000) or
        (pressure is not None and (pressure >= 72 or pressure <= 28)) or
        (chg is not None and abs(chg) >= 2.0)
    )

    if anomaly >= 84 and max_short >= .35:
        stage = "ACCELERATING"
    elif anomaly >= 76 and exceptional:
        stage = "TRIGGER NEAR"
    elif anomaly >= 66 and exceptional:
        stage = "PRE-MOVE"
    elif anomaly >= 54:
        stage = "BUILDING"
    else:
        stage = "DISCOVERY"
    if chg is not None and abs(chg) >= 4.0 and max_short < .18:
        stage = "MOVE ACTIVE"
    if chg is not None and abs(chg) >= 6.0 and max_short < .10:
        stage = "EXHAUSTION"

    uc = f(row.get("upper_circuit_limit"), f(row.get("upper_circuit")))
    lc = f(row.get("lower_circuit_limit"), f(row.get("lower_circuit")))
    dist_uc = ((uc - ltp) / ltp * 100.0) if ltp and uc and uc >= ltp else None
    dist_lc = ((ltp - lc) / ltp * 100.0) if ltp and lc and lc <= ltp else None
    circuit = None
    if direction == "UP" and dist_uc is not None and dist_uc <= 8:
        circuit = "LOCK IMMINENT" if dist_uc <= .25 else "PRE-CIRCUIT" if dist_uc <= 1.2 else "ARMING" if dist_uc <= 3 else "EARLY PRESSURE"
    elif direction == "DOWN" and dist_lc is not None and dist_lc <= 8:
        circuit = "LOCK IMMINENT" if dist_lc <= .25 else "PRE-CIRCUIT" if dist_lc <= 1.2 else "ARMING" if dist_lc <= 3 else "EARLY PRESSURE"

    flow_state = "NO CLEAR LARGE-FLOW FOOTPRINT"
    if direction == "UP" and anomaly >= 58:
        flow_state = "ACCUMULATION-LIKE / BUYING PRESSURE" if pressure is None or pressure >= 55 else "PRICE-UP / BOOK-CONFLICT"
    elif direction == "DOWN" and anomaly >= 58:
        flow_state = "DISTRIBUTION-LIKE / SELLING PRESSURE" if pressure is None or pressure <= 45 else "PRICE-DOWN / BOOK-CONFLICT"

    reasons = up_evidence if direction == "UP" else dn_evidence if direction == "DOWN" else (up_evidence + dn_evidence)
    return {
        "symbol": symbol, "instrument_key": row.get("instrument_key"), "name": row.get("name"),
        "source_universe": row.get("source_universe") or "NSE CASH", "ltp": ltp,
        "change_pct": round(chg, 3) if chg is not None else None, "volume": vol,
        "turnover": round(turnover, 2) if turnover is not None else None,
        "volume_pace_per_min": round(pace, 2) if pace is not None else None,
        "rvol": round(rvol, 2) if rvol is not None else None,
        "price_velocity": {"15s_pct": round(p15,3) if p15 is not None else None, "30s_pct": round(p30,3) if p30 is not None else None, "60s_pct": round(p60,3) if p60 is not None else None, "180s_pct": round(p180,3) if p180 is not None else None, "300s_pct": round(p300,3) if p300 is not None else None, "900s_pct": round(p900,3) if p900 is not None else None},
        "turnover_velocity": {"15s_value_per_sec": round(tvps15,2) if tvps15 is not None else None, "60s_value_per_sec": round(tvps60,2) if tvps60 is not None else None},
        "open_low_distance_pct": round(open_low,3) if open_low is not None else None,
        "open_high_distance_pct": round(high_open,3) if high_open is not None else None,
        "recovery_from_low_pct": round(recovery,3) if recovery is not None else None,
        "fall_from_high_pct": round(fall_from_high,3) if fall_from_high is not None else None,
        "high_attack_distance_pct": round(high_attack,3) if high_attack is not None else None,
        "low_attack_distance_pct": round(low_attack,3) if low_attack is not None else None,
        "depth": dep, "direction": direction, "directional_score": round(directional_score,1),
        "anomaly_score": round(anomaly,1), "execution_quality": round(execution_quality,1),
        "stage": stage, "exceptional_anomaly": exceptional, "fast_lane": bool(exceptional and anomaly >= 58),
        "large_flow_state": flow_state, "circuit_state": circuit,
        "distance_to_uc_pct": round(dist_uc,3) if dist_uc is not None else None,
        "distance_to_lc_pct": round(dist_lc,3) if dist_lc is not None else None,
        "upper_circuit": uc, "lower_circuit": lc, "reasons": reasons[:8],
        "observed_epoch": f(row.get("quote_epoch"), time.time()), "read_only": True,
    }


def plan_entry(m: Mapping[str, Any]) -> Dict[str, Any]:
    ltp = f(m.get("ltp")); direction = str(m.get("direction") or "NEUTRAL"); stage = str(m.get("stage") or "DISCOVERY")
    q = f(m.get("execution_quality"), 0.0) or 0.0
    if not ltp or direction == "NEUTRAL" or stage == "DISCOVERY":
        return {"state":"WATCH","reason":"No directional pre-move state","read_only":True}
    if q < 35:
        return {"state":"WATCH / POOR EXECUTION","reason":"Liquidity/spread quality too weak for an entry plan","read_only":True}
    entry_pad = ltp * .0008
    risk = ltp * (.0045 if q >= 60 else .0065)
    entry_low, entry_high = ltp-entry_pad, ltp+entry_pad
    if direction == "UP":
        sl = entry_low-risk; t1,t2,t3 = entry_high+risk, entry_high+risk*1.7, entry_high+risk*2.5
        action = "EARLY BUY" if stage in {"PRE-MOVE","BUILDING"} else "BUY"
    else:
        sl = entry_high+risk; t1,t2,t3 = entry_low-risk, entry_low-risk*1.7, entry_low-risk*2.5
        action = "EARLY SELL" if stage in {"PRE-MOVE","BUILDING"} else "SELL"
    return {"state":action,"entry_zone":[round(entry_low,4),round(entry_high,4)],"invalidation":round(sl,4),"t1":round(t1,4),"t2":round(t2,4),"t3":round(t3,4),"do_not_chase":bool(stage in {"MOVE ACTIVE","EXHAUSTION"}),"basis":"Observed price/liquidity plan; selected-symbol chart structure should supersede generic bands.","read_only":True}


def autotrender(m: Mapping[str, Any], timeframe_min: int = 5) -> Dict[str, Any]:
    x = dict(m); plan = plan_entry(x); stage=str(x.get("stage") or "DISCOVERY"); direction=str(x.get("direction") or "NEUTRAL"); score=f(x.get("anomaly_score"),0.0) or 0.0
    tf_key = "180s_pct" if int(timeframe_min) <= 3 else "300s_pct" if int(timeframe_min) <= 5 else "900s_pct"
    tf_velocity = f((x.get("price_velocity") or {}).get(tf_key))
    if tf_velocity is not None:
        score = clamp(score + min(12.0, abs(tf_velocity) * 6.0))
        if direction == "NEUTRAL" and abs(tf_velocity) >= .25:
            direction = "UP" if tf_velocity > 0 else "DOWN"
            x["direction"] = direction
    if direction == "UP": signal = "BUY" if stage in {"TRIGGER NEAR","ENTRY READY","ACCELERATING"} and score >= 68 else "EARLY BUY" if stage in {"PRE-MOVE","BUILDING"} else "WATCH"
    elif direction == "DOWN": signal = "SELL" if stage in {"TRIGGER NEAR","ENTRY READY","ACCELERATING"} and score >= 68 else "EARLY SELL" if stage in {"PRE-MOVE","BUILDING"} else "WATCH"
    else: signal = "WATCH"
    return {**x,"signal":signal,"plan":plan,"strength":round(score,1),"acceleration":round(abs(f((x.get("price_velocity") or {}).get("30s_pct"),0.0) or 0.0),3),"timeframe_min":int(timeframe_min),"timeframe_velocity_pct":round(tf_velocity,3) if tf_velocity is not None else None}


def rank_market(rows: Iterable[Mapping[str, Any]], histories: Mapping[str, Sequence[Mapping[str, Any]]], limit: int = 180) -> Dict[str, Any]:
    out: List[Dict[str, Any]]=[]
    for row in rows or []:
        sym=str(row.get("symbol") or row.get("tradingsymbol") or "").upper().strip()
        if not sym: continue
        m=autotrender(classify_row(row,histories.get(sym) or ()))
        if m.get("ltp") is not None: out.append(m)
    out.sort(key=lambda x:(bool(x.get("fast_lane")),f(x.get("anomaly_score"),0) or 0,abs(f(x.get("change_pct"),0) or 0)),reverse=True)
    up=[x for x in out if x.get("direction")=="UP"]; down=[x for x in out if x.get("direction")=="DOWN"]
    premove=[x for x in out if x.get("stage") in {"PRE-MOVE","BUILDING","ACCELERATING","TRIGGER NEAR"}]
    fast=[x for x in out if x.get("fast_lane")]; circuits=[x for x in out if x.get("circuit_state")]
    unusual=[x for x in out if (f(x.get("rvol"),0) or 0)>=1.8 or abs(f((x.get("turnover_velocity") or {}).get("15s_value_per_sec"),0) or 0)>=2_000_000]
    return {"rows":out[:max(1,limit)],"up":up[:80],"down":down[:80],"pre_move":premove[:100],"fast_lane":fast[:100],"circuits":circuits[:100],"unusual_liquidity":unusual[:100],"counts":{"observed":len(out),"up":len(up),"down":len(down),"pre_move":len(premove),"fast_lane":len(fast),"circuits":len(circuits)}}


def blind_spot_report(market: Mapping[str, Any], alerted_symbols: Iterable[str]) -> Dict[str, Any]:
    alerted={str(x).upper() for x in alerted_symbols or []}; misses=[]
    for x in market.get("rows") or []:
        chg=abs(f(x.get("change_pct"),0.0) or 0.0); fast=bool(x.get("fast_lane")); meaningful=chg>=2.0 or fast or (f(x.get("anomaly_score"),0) or 0)>=72
        if meaningful and str(x.get("symbol") or "").upper() not in alerted:
            misses.append({"symbol":x.get("symbol"),"change_pct":x.get("change_pct"),"stage":x.get("stage"),"anomaly_score":x.get("anomaly_score"),"reason":"MOVE EXISTS OUTSIDE ALERTED RADAR","forced_hot_lane":True})
    misses.sort(key=lambda x:(f(x.get("anomaly_score"),0) or 0,abs(f(x.get("change_pct"),0) or 0)),reverse=True)
    return {"status":"PASS" if not misses else "ATTENTION","silent_misses_allowed":False,"forced_discovery":misses[:100],"count":len(misses),"policy":"Observable large moves without a corresponding alert are forced into the hot lane and audited."}


def merge_with_v746(base_snap: Mapping[str, Any], market: Mapping[str, Any], alerts: Sequence[Mapping[str, Any]], health: Mapping[str, Any]) -> Dict[str, Any]:
    return {**dict(base_snap),"version":VERSION,"release":RELEASE,"whole_market":dict(market),"auto_trender":{"all":list(market.get("rows") or []),"stocks":list(market.get("rows") or []),"indices":[x for x in (base_snap.get("setups") or []) if str(x.get("symbol") or "").upper() in {"NIFTY","BANKNIFTY","MIDCPNIFTY","SENSEX"}],"policy":"Index + whole-NSE-cash discovery. BUY/SELL labels are decision-support states, not profit guarantees."},"module_health":dict(health),"alerts":[dict(x) for x in alerts],"read_only":True,"execution_enabled":False,"policy":"Discover first, judge later. Upside and downside anomalies are treated symmetrically."}
