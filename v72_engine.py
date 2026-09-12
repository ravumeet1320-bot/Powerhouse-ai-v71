from __future__ import annotations

"""POWERHOUSE AI V72.1 — Fast Signal + Accuracy Guard / Predictive AI Brain 3.1.

This layer is intentionally read-only. It builds on the proven V71 universal census and
adds *earlier* evidence fusion, low-latency signal tiers, and independent-evidence accuracy guards rather than simply increasing post-move momentum weight.
Every output is evidence/state based; unavailable inputs remain unavailable and no
module is allowed to invent market data, participant identity, fills, P&L, or profit odds.
"""

import json
import math
import os
import sqlite3
import statistics
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from v71_engine import build_v71, universal_census, stock_option_hero, chart_intelligence as chart_intelligence_v71, missed_move_audit as missed_move_audit_v71
from v67_engine import build_chart_intelligence as build_chart_intelligence_v67

ROOT = Path(__file__).parent
DB_PATH = Path(os.getenv("POWERHOUSE_V72_DB_PATH") or (ROOT / ".runtime" / "powerhouse_v72.sqlite3"))
_LOCK = threading.RLock()
_FLOW_STATE: Dict[str, deque] = defaultdict(lambda: deque(maxlen=480))
_CHAIN_STATE: Dict[str, deque] = defaultdict(lambda: deque(maxlen=240))
_LAST_STAGE: Dict[str, str] = {}
_LAST_DB_EPOCH = 0.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS premove_snapshots_v72(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 epoch REAL NOT NULL,
 symbol TEXT NOT NULL,
 ltp REAL,
 side TEXT,
 stage TEXT,
 premove_score REAL,
 depth_pressure REAL,
 relative_strength REAL,
 opportunity_decay REAL,
 quote_age_sec REAL,
 payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_v72_pm_symbol_epoch ON premove_snapshots_v72(symbol, epoch DESC);
CREATE INDEX IF NOT EXISTS idx_v72_pm_epoch ON premove_snapshots_v72(epoch DESC);
CREATE TABLE IF NOT EXISTS premove_events_v72(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 epoch REAL NOT NULL,
 symbol TEXT NOT NULL,
 event_type TEXT NOT NULL,
 stage TEXT,
 side TEXT,
 score REAL,
 price REAL,
 trigger_price REAL,
 payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_v72_ev_symbol_epoch ON premove_events_v72(symbol, epoch DESC);
"""


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=8)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def _f(v: Any, default=None):
    try:
        if v is None or v == "":
            return default
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _mean(values: Iterable[Any], default=None):
    xs = [_f(x) for x in values]
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else default


def _stdev(values: Iterable[Any], default=0.0):
    xs = [_f(x) for x in values]
    xs = [x for x in xs if x is not None]
    return statistics.pstdev(xs) if len(xs) >= 2 else default


def _pct(a: Any, b: Any, default=None):
    a = _f(a); b = _f(b)
    if a is None or b in (None, 0):
        return default
    return (a - b) / abs(b) * 100.0


def _weighted_depth(raw: dict) -> dict:
    levels = list(raw.get("depth_levels") or [])[:30]
    if not levels:
        bq, aq = _f(raw.get("bid_qty")), _f(raw.get("ask_qty"))
        if bq is not None or aq is not None:
            levels = [{"bid_qty": bq or 0.0, "ask_qty": aq or 0.0, "bid": raw.get("bid"), "ask": raw.get("ask")}]
    if not levels:
        return {"status": "UNAVAILABLE", "levels": 0, "pressure": None, "imbalance": None, "wall": None, "spread_pct": None}
    wb = wa = 0.0
    bids: List[Tuple[float, int]] = []
    asks: List[Tuple[float, int]] = []
    for i, x in enumerate(levels):
        w = 1.0 / ((i + 1) ** 0.62)
        bq = max(0.0, _f(x.get("bid_qty"), 0.0) or 0.0)
        aq = max(0.0, _f(x.get("ask_qty"), 0.0) or 0.0)
        wb += bq * w; wa += aq * w
        bids.append((bq, i)); asks.append((aq, i))
    den = wb + wa
    pressure = 100.0 * wb / den if den > 0 else 50.0
    imbalance = 100.0 * (wb - wa) / den if den > 0 else 0.0
    bid_vals = [q for q, _ in bids if q > 0]; ask_vals = [q for q, _ in asks if q > 0]
    med_b = statistics.median(bid_vals) if bid_vals else 0.0
    med_a = statistics.median(ask_vals) if ask_vals else 0.0
    bmax, bi = max(bids, default=(0.0, 0)); amax, ai = max(asks, default=(0.0, 0))
    wall = None
    if bmax > max(med_b * 2.2, 0) and bmax > amax * 1.15:
        wall = {"side": "BID", "level": bi + 1, "strength_x": round(bmax / max(med_b, 1.0), 2)}
    elif amax > max(med_a * 2.2, 0) and amax > bmax * 1.15:
        wall = {"side": "ASK", "level": ai + 1, "strength_x": round(amax / max(med_a, 1.0), 2)}
    bid = _f(raw.get("bid")); ask = _f(raw.get("ask")); px = _f(raw.get("ltp"))
    spread = ((ask - bid) / px * 100.0) if ask is not None and bid is not None and px and ask >= bid else None
    return {
        "status": "READY", "levels": len(levels), "pressure": round(pressure, 1), "imbalance": round(imbalance, 1),
        "weighted_bid_qty": round(wb, 2), "weighted_ask_qty": round(wa, 2), "wall": wall,
        "spread_pct": round(spread, 4) if spread is not None else None,
        "bias": "POSITIVE" if pressure >= 61 else "NEGATIVE" if pressure <= 39 else "NEUTRAL",
    }


def _sector_stats(census_rows: List[dict]) -> dict:
    by: Dict[str, List[dict]] = defaultdict(list)
    for r in census_rows:
        by[str(r.get("sector") or "F&O")].append(r)
    out = {}
    for sec, rows in by.items():
        cps = [_f(x.get("change_pct"), 0.0) or 0.0 for x in rows]
        signed = [_f(x.get("signed_score"), 0.0) or 0.0 for x in rows]
        bull = sum(1 for x in signed if x >= 12); bear = sum(1 for x in signed if x <= -12)
        out[sec] = {
            "sector": sec, "count": len(rows), "avg_change_pct": round(_mean(cps, 0.0), 3),
            "breadth": round(100.0 * (bull - bear) / max(len(rows), 1), 1),
            "bullish": bull, "bearish": bear,
        }
    return out


def _oi_state(cp: float, oic: Optional[float]) -> dict:
    if oic is None:
        return {"state": "UNAVAILABLE", "bias": "NEUTRAL", "quality": 0}
    if cp > 0.05 and oic > 0.15: return {"state": "LONG BUILDUP", "bias": "POSITIVE", "quality": min(100, 55 + abs(oic) * 4)}
    if cp < -0.05 and oic > 0.15: return {"state": "SHORT BUILDUP", "bias": "NEGATIVE", "quality": min(100, 55 + abs(oic) * 4)}
    if cp > 0.05 and oic < -0.15: return {"state": "SHORT COVERING", "bias": "POSITIVE", "quality": min(88, 45 + abs(oic) * 3)}
    if cp < -0.05 and oic < -0.15: return {"state": "LONG UNWINDING", "bias": "NEGATIVE", "quality": min(88, 45 + abs(oic) * 3)}
    return {"state": "MIXED / FLAT", "bias": "NEUTRAL", "quality": 30}


def _flow_persistence(sym: str, now: float, sample: dict) -> dict:
    with _LOCK:
        h = _FLOW_STATE[sym]
        if not h or now - h[-1]["t"] >= 1.0:
            h.append({"t": now, **sample})
        rows = list(h)
    recent = [x for x in rows if now - x["t"] <= 120]
    if len(recent) < 2:
        return {"samples": len(recent), "depth_persistence": None, "score_stability": None, "evidence_persistence": None}
    pressures = [_f(x.get("depth")) for x in recent]; pressures = [x for x in pressures if x is not None]
    scores = [_f(x.get("score")) for x in recent]; scores = [x for x in scores if x is not None]
    depth_p = None
    if pressures:
        side = 1 if statistics.mean(pressures) >= 50 else -1
        depth_p = 100.0 * sum(1 for x in pressures if (x - 50) * side >= 5) / len(pressures)
    stable = None
    if scores:
        stable = _clamp(100.0 - _stdev(scores) * 4.0)
    evidence_p = None
    sides = [x.get("side") for x in recent if x.get("side") in ("CE", "PE")]
    if sides:
        leader = max(set(sides), key=sides.count)
        evidence_p = 100.0 * sides.count(leader) / len(sides)
    return {"samples": len(recent), "depth_persistence": round(depth_p, 1) if depth_p is not None else None,
            "score_stability": round(stable, 1) if stable is not None else None,
            "evidence_persistence": round(evidence_p, 1) if evidence_p is not None else None}


def _directional_evidence(side: str, row: dict, depth: dict, oi: dict, relative: float, breadth: float, compression: float) -> dict:
    """Count independent aligned/opposed evidence groups for low-latency signals.

    This is deliberately group-based so multiple metrics from one family do not
    masquerade as independent confirmation. It improves selectivity without waiting
    for slow lagging indicators.
    """
    if side not in ("CE", "PE"):
        return {"aligned_groups": 0, "opposed_groups": 0, "groups": {}, "aligned": [], "opposed": []}
    sign = 1.0 if side == "CE" else -1.0
    groups = {}

    # Structure/compression is direction-neutral preparation, so it confirms readiness
    # only when a directional trigger exists elsewhere.
    groups["structure"] = "ALIGNED" if compression >= 28 else "NEUTRAL"

    v15 = _f(row.get("velocity_15s")); v60 = _f(row.get("velocity_60s")); acc = _f(row.get("acceleration"))
    momentum = 0.0
    for v, w in ((v15, 1.2), (v60, .8), (acc, 1.0)):
        if v is not None:
            momentum += sign * v * w
    groups["momentum"] = "ALIGNED" if momentum >= .12 else "OPPOSED" if momentum <= -.18 else "NEUTRAL"

    rv = _f(row.get("rvol")); vv = _f(row.get("volume_velocity"))
    volume_ready = (rv is not None and .75 <= rv <= 2.5) or (vv is not None and vv > 0)
    groups["volume"] = "ALIGNED" if volume_ready else "NEUTRAL"

    dp = _f(depth.get("pressure"))
    if dp is None:
        groups["depth"] = "NEUTRAL"
    else:
        d = sign * (dp - 50.0)
        groups["depth"] = "ALIGNED" if d >= 7 else "OPPOSED" if d <= -9 else "NEUTRAL"

    ob = str(oi.get("bias") or "NEUTRAL")
    want = "POSITIVE" if side == "CE" else "NEGATIVE"
    wrong = "NEGATIVE" if side == "CE" else "POSITIVE"
    groups["oi"] = "ALIGNED" if ob == want else "OPPOSED" if ob == wrong else "NEUTRAL"

    rs = sign * relative
    groups["relative_strength"] = "ALIGNED" if rs >= .15 else "OPPOSED" if rs <= -.25 else "NEUTRAL"
    br = sign * breadth
    groups["breadth"] = "ALIGNED" if br >= 12 else "OPPOSED" if br <= -18 else "NEUTRAL"

    aligned = [k for k, v in groups.items() if v == "ALIGNED"]
    opposed = [k for k, v in groups.items() if v == "OPPOSED"]
    return {"aligned_groups": len(aligned), "opposed_groups": len(opposed), "groups": groups, "aligned": aligned, "opposed": opposed}


def _fast_signal_profile(row: dict) -> dict:
    """Two-stage fast signal: EARLY for speed, CONFIRMED for action quality.

    No historical win-rate is claimed. The guard only describes current evidence
    quality/freshness and blocks stale, late, or conflicted setups.
    """
    side = row.get("v72_side")
    score = _f(row.get("pre_move_score"), 0.0) or 0.0
    age = _f(row.get("quote_age_sec"), 999.0) or 999.0
    late = bool(row.get("late_entry"))
    decay = _f(row.get("opportunity_decay"), 100.0) or 100.0
    ev = row.get("directional_evidence") or {}
    aligned = int(ev.get("aligned_groups") or 0)
    opposed = int(ev.get("opposed_groups") or 0)
    pers = row.get("persistence") or {}
    samples = int(pers.get("samples") or 0)
    ep = _f(pers.get("evidence_persistence"))
    stable = _f(pers.get("score_stability"))
    spread = _f((row.get("depth_intelligence") or {}).get("spread_pct"))

    freshness_pass = age <= 10
    spread_pass = spread is None or spread <= .65
    persistence_pass = samples < 2 or ep is None or ep >= 60
    stability_pass = samples < 3 or stable is None or stable >= 58
    conflict_pass = opposed <= 1
    base_pass = side in ("CE", "PE") and not late and decay < 48 and freshness_pass and spread_pass and conflict_pass

    tier = "NONE"
    action = "WAIT"
    # EARLY deliberately fires before the old TRIGGER READY threshold, but only when
    # at least four independent evidence families line up.
    if base_pass and score >= 66 and aligned >= 4 and persistence_pass:
        tier = "EARLY"
        action = f"EARLY {side}"
    # CONFIRMED requires either stronger breadth of evidence or short persistence,
    # preserving speed while filtering one-tick noise.
    confirmed_persistence = (samples >= 2 and (ep or 0) >= 66) or aligned >= 6
    if base_pass and score >= 76 and aligned >= 5 and persistence_pass and stability_pass and confirmed_persistence:
        tier = "CONFIRMED"
        action = f"BUY {side}"

    return {
        "tier": tier, "action": action, "score": round(score, 1), "quote_age_sec": round(age, 2),
        "aligned_groups": aligned, "opposed_groups": opposed,
        "freshness_pass": freshness_pass, "spread_pass": spread_pass,
        "persistence_pass": persistence_pass, "stability_pass": stability_pass,
        "late_entry_pass": not late, "decay_pass": decay < 48,
        "evidence_persistence": ep, "score_stability": stable,
        "policy": "EARLY prioritizes low latency; BUY is reserved for CONFIRMED independent evidence. This is not a guaranteed accuracy percentage.",
    }


def _pre_move_row(row: dict, raw: dict, sec: dict, market_avg: float, now: float) -> dict:
    px = _f(row.get("ltp"), 0.0) or 0.0
    cp = _f(row.get("change_pct"), 0.0) or 0.0
    rv = _f(row.get("rvol")); vv = _f(row.get("volume_velocity")); oic = _f(row.get("futures_oi_change_pct")); oiv = _f(row.get("oi_velocity"))
    v15 = _f(row.get("velocity_15s")); v60 = _f(row.get("velocity_60s")); acc = _f(row.get("acceleration"))
    depth = _weighted_depth(raw)
    relative = cp - (_f(sec.get("avg_change_pct"), market_avg) or market_avg)
    lv = row.get("nearest_levels") or {}; above = lv.get("above"); below = lv.get("below")
    nearest = min([_f(x.get("distance_pct")) for x in (above, below) if isinstance(x, dict) and _f(x.get("distance_pct")) is not None], default=None)
    two_sided = above is not None and below is not None
    corridor = ((_f(above.get("value")) - _f(below.get("value"))) / px * 100.0) if two_sided and px and _f(above.get("value")) and _f(below.get("value")) else None
    compression = 0.0
    if nearest is not None:
        compression += 24 if nearest <= .18 else 18 if nearest <= .35 else 10 if nearest <= .7 else 0
    if corridor is not None:
        compression += 18 if corridor <= 1.0 else 12 if corridor <= 1.8 else 5 if corridor <= 3 else 0
    if abs(cp) <= 1.25: compression += 10
    if rv is not None and rv <= 1.15: compression += 8
    compression = _clamp(compression, 0, 60)

    signed = _f(row.get("signed_score"), 0.0) or 0.0
    if depth.get("pressure") is not None: signed += (depth["pressure"] - 50.0) * .45
    signed += _clamp(relative * 12.0, -16, 16)
    if oic is not None:
        direction_ref = cp if abs(cp) > .05 else (v60 or 0.0)
        if direction_ref:
            signed += math.copysign(min(abs(oic) * 1.1, 10), direction_ref)
    signed = _clamp(signed, -100, 100)
    side = "CE" if signed >= 10 else "PE" if signed <= -10 else "WAIT"

    oi = _oi_state(cp, oic)
    score = 12.0 + compression * .45
    score += min(16, abs(relative) * 13.0)
    if rv is not None:
        # Pre-move preference: quiet-to-waking volume scores better than already-crowded RVOL.
        score += 12 if .75 <= rv <= 1.35 else 16 if 1.35 < rv <= 2.2 else 7 if 2.2 < rv <= 3.5 else 2 if rv > 3.5 else 5
    if vv is not None and vv > 0: score += min(12, vv * .20)
    if acc is not None and abs(acc) >= .08: score += min(12, abs(acc) * 10)
    if oiv is not None and abs(oiv) > .2: score += min(9, abs(oiv) * .7)
    if oic is not None and abs(oic) >= .5: score += min(8, abs(oic) * 1.1)
    dp = _f(depth.get("pressure"))
    if dp is not None and abs(dp - 50) >= 8: score += min(12, abs(dp - 50) * .45)
    breadth = _f(sec.get("breadth"), 0.0) or 0.0
    if side == "CE" and breadth > 10: score += min(9, breadth * .12)
    if side == "PE" and breadth < -10: score += min(9, abs(breadth) * .12)
    if side == "CE" and relative > .15: score += min(8, relative * 7)
    if side == "PE" and relative < -.15: score += min(8, abs(relative) * 7)
    score = _clamp(score)

    # Explicit late-entry / crowding guard. This does not erase discovery; it changes entry quality.
    move_active = abs(cp) >= 2.2 or (v60 is not None and abs(v60) >= 1.35) or (rv is not None and rv >= 4.0 and abs(cp) >= 1.4)
    parabolic = abs(cp) >= 4.0 or (v15 is not None and abs(v15) >= 2.2)
    decay = 0.0
    if abs(cp) > 1.4: decay += min(38, (abs(cp) - 1.4) * 12)
    if rv is not None and rv > 2.8: decay += min(25, (rv - 2.8) * 8)
    if v15 is not None and v60 is not None and abs(v15) < abs(v60) * .55 and abs(v60) > .35: decay += 18
    if parabolic: decay += 25
    decay = _clamp(decay)

    if side == "WAIT" or score < 44: stage = "SCANNING"
    elif score < 54: stage = "EARLY CLUE"
    elif score < 64: stage = "BUILDING"
    elif score < 75: stage = "ARMING"
    elif score < 86: stage = "TRIGGER READY"
    else: stage = "MOVE STARTED" if move_active else "TRIGGER READY"
    if move_active and stage in ("ARMING", "TRIGGER READY"):
        stage = "MOVE STARTED"
    if parabolic:
        stage = "EXPANSION / LATE"

    quality = "EARLY" if stage in ("EARLY CLUE", "BUILDING") else "CLEAN" if stage in ("ARMING", "TRIGGER READY") and decay < 28 else "CROWDED" if decay < 60 else "LATE / EXHAUSTION RISK"
    breakout_window = "5–15 min" if score >= 80 and not move_active else "15–30 min" if score >= 70 else "30–60 min" if score >= 60 else "UNCONFIRMED"
    trigger = None
    if side == "CE" and above: trigger = _f(above.get("value"))
    elif side == "PE" and below: trigger = _f(below.get("value"))

    persistence = _flow_persistence(str(row.get("symbol")), now, {"depth": dp, "score": score, "side": side, "px": px})
    if persistence.get("evidence_persistence") is not None and persistence["evidence_persistence"] >= 70 and stage in ("BUILDING", "ARMING"):
        score = _clamp(score + 4)

    directional = _directional_evidence(side, row, depth, oi, relative, breadth, compression)
    # Opposing independent evidence is an accuracy guard; aligned breadth can reward
    # an early setup without relying on lagging averages.
    if directional["aligned_groups"] >= 5 and directional["opposed_groups"] == 0:
        score = _clamp(score + 3)
    elif directional["opposed_groups"] >= 2:
        score = _clamp(score - min(10, directional["opposed_groups"] * 4))

    evidence, counter = [], []
    if compression >= 28: evidence.append("range/key-level compression")
    if rv is not None and .75 <= rv <= 2.2: evidence.append(f"volume sequence {rv:.2f}x RVOL")
    if vv is not None and vv > 0: evidence.append("volume velocity turning up")
    if acc is not None and abs(acc) >= .08: evidence.append(f"momentum ignition {acc:+.2f}")
    if abs(relative) >= .25: evidence.append(f"relative strength acceleration {relative:+.2f}%")
    if oi.get("state") not in ("UNAVAILABLE", "MIXED / FLAT"): evidence.append(oi["state"])
    if dp is not None and abs(dp - 50) >= 10: evidence.append(f"depth pressure {dp:.0f}/100")
    if abs(breadth) >= 20: evidence.append(f"sector breadth {breadth:+.0f}")
    if persistence.get("depth_persistence") is not None and persistence["depth_persistence"] >= 65: evidence.append("order-book pressure persistent")
    if decay >= 45: counter.append(f"opportunity decay {decay:.0f}/100")
    if move_active: counter.append("MOVE ALREADY ACTIVE — DO NOT CHASE")
    if parabolic: counter.append("PARABOLIC / EXHAUSTION RISK")
    if _f(row.get("quote_age_sec"), 999) > 30: counter.append("stale quote")
    spread = _f(depth.get("spread_pct"))
    if spread is not None and spread > .8: counter.append(f"wide spread {spread:.2f}%")

    if directional["opposed"]:
        counter.append("opposed evidence: " + ", ".join(directional["opposed"][:3]))
    out = {
        **row,
        "v72_side": side, "pre_move_score": round(score, 1), "pre_move_stage": stage,
        "trigger_countdown": int(round(score)), "move_quality": quality,
        "estimated_breakout_window": breakout_window, "breakout_trigger": trigger,
        "opportunity_decay": round(decay, 1), "late_entry": bool(move_active),
        "relative_strength": round(relative, 3), "compression_score": round(compression, 1),
        "depth_intelligence": depth, "oi_state": oi, "sector_breadth": breadth,
        "persistence": persistence, "directional_evidence": directional,
        "v72_evidence": evidence[:10], "v72_counter_evidence": counter[:8],
    }
    out["fast_signal"] = _fast_signal_profile(out)
    return out


def _record(rows: List[dict], now: float) -> None:
    global _LAST_DB_EPOCH
    if not rows or now - _LAST_DB_EPOCH < max(5, int(os.getenv("POWERHOUSE_V72_SNAPSHOT_SECONDS", "5"))):
        return
    vals, events = [], []
    for r in rows:
        sym = str(r.get("symbol") or "")
        payload = json.dumps({"evidence": r.get("v72_evidence"), "counter": r.get("v72_counter_evidence"), "persistence": r.get("persistence")}, default=str)[:12000]
        vals.append((now, sym, r.get("ltp"), r.get("v72_side"), r.get("pre_move_stage"), r.get("pre_move_score"), (r.get("depth_intelligence") or {}).get("pressure"), r.get("relative_strength"), r.get("opportunity_decay"), r.get("quote_age_sec"), payload))
        prev = _LAST_STAGE.get(sym)
        stage = str(r.get("pre_move_stage") or "")
        if prev != stage and stage in ("ARMING", "TRIGGER READY", "MOVE STARTED"):
            events.append((now, sym, "STAGE_PROMOTION", stage, r.get("v72_side"), r.get("pre_move_score"), r.get("ltp"), r.get("breakout_trigger"), payload))
        _LAST_STAGE[sym] = stage
    try:
        with _db() as c:
            c.executemany("INSERT INTO premove_snapshots_v72(epoch,symbol,ltp,side,stage,premove_score,depth_pressure,relative_strength,opportunity_decay,quote_age_sec,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?)", vals)
            if events:
                c.executemany("INSERT INTO premove_events_v72(epoch,symbol,event_type,stage,side,score,price,trigger_price,payload) VALUES(?,?,?,?,?,?,?,?,?)", events)
            c.execute("DELETE FROM premove_snapshots_v72 WHERE epoch<?", (now - 45 * 86400,))
            c.execute("DELETE FROM premove_events_v72 WHERE epoch<?", (now - 90 * 86400,))
            c.commit()
        _LAST_DB_EPOCH = now
    except Exception:
        pass


def pre_move_radar(snapshot: dict, record: bool = True) -> dict:
    now = time.time()
    census = universal_census(snapshot, record=record)
    base_rows = census.get("all_rows") or []
    raw_map = {str(x.get("symbol") or "").upper(): x for x in (snapshot.get("sector_heatmap") or []) if isinstance(x, dict)}
    sectors = _sector_stats(base_rows)
    market_avg = _mean([x.get("change_pct") for x in base_rows], 0.0) or 0.0
    rows = []
    for r in base_rows:
        sec = sectors.get(str(r.get("sector") or "F&O"), {"avg_change_pct": market_avg, "breadth": 0.0})
        rows.append(_pre_move_row(r, raw_map.get(str(r.get("symbol") or "").upper(), {}), sec, market_avg, now))
    priority = {"TRIGGER READY": 7, "ARMING": 6, "BUILDING": 5, "EARLY CLUE": 4, "MOVE STARTED": 3, "EXPANSION / LATE": 2, "SCANNING": 1}
    rows.sort(key=lambda x: (priority.get(x.get("pre_move_stage"), 0), x.get("pre_move_score", 0), -x.get("opportunity_decay", 0)), reverse=True)

    # Leader-follower engine: strongest sector leader can promote scans of lagging peers.
    leaders = {}
    for sec in sectors:
        candidates = [x for x in rows if x.get("sector") == sec and x.get("v72_side") != "WAIT"]
        if candidates:
            leaders[sec] = max(candidates, key=lambda x: (x.get("pre_move_score", 0), abs(x.get("relative_strength", 0))))
    for r in rows:
        leader = leaders.get(r.get("sector"))
        if leader and leader.get("symbol") != r.get("symbol") and leader.get("v72_side") == r.get("v72_side") and leader.get("pre_move_score", 0) >= 72 and r.get("pre_move_score", 0) >= 52:
            r["leader_follower"] = {"leader": leader.get("symbol"), "side": leader.get("v72_side"), "leader_score": leader.get("pre_move_score"), "state": "SECTOR CASCADE WATCH"}
        else:
            r["leader_follower"] = None

    if record:
        _record(rows, now)
    stages = defaultdict(int)
    for r in rows: stages[r.get("pre_move_stage") or "UNKNOWN"] += 1
    fresh = [r for r in rows if (_f(r.get("quote_age_sec"), 999) or 999) <= 10]
    return {
        "status": "READY" if rows else "UNAVAILABLE", "version": "72.0", "release": "72.1-fast-signal", "rows": rows,
        "top": rows[:40], "trigger_ready": [x for x in rows if x.get("pre_move_stage") == "TRIGGER READY"],
        "arming": [x for x in rows if x.get("pre_move_stage") == "ARMING"],
        "building": [x for x in rows if x.get("pre_move_stage") == "BUILDING"],
        "late": [x for x in rows if x.get("late_entry")],
        "fast_confirmed": [x for x in rows if (x.get("fast_signal") or {}).get("tier") == "CONFIRMED"],
        "fast_early": [x for x in rows if (x.get("fast_signal") or {}).get("tier") == "EARLY"],
        "stages": dict(stages), "sector_stats": list(sectors.values()),
        "expected_universe": census.get("expected_universe"), "observed": census.get("observed"),
        "coverage_pct": census.get("coverage_pct"), "freshness_pct": round(100 * len(fresh) / len(rows), 1) if rows else 0.0,
        "policy": "Pre-move score ranks early observable pressure/compression evidence. Estimated windows are probabilistic timing bands, not promises.",
    }


def _module_bias(rows: List[dict]) -> dict:
    if not rows:
        return {"bias": "NEUTRAL", "score": 50.0, "positive": 0, "negative": 0, "conflicting": 0}
    pos = sum(1 for x in rows if x.get("v72_side") == "CE" and x.get("pre_move_score", 0) >= 60)
    neg = sum(1 for x in rows if x.get("v72_side") == "PE" and x.get("pre_move_score", 0) >= 60)
    n = max(pos + neg, 1)
    signed = (pos - neg) / n
    score = 50 + signed * 45
    bias = "POSITIVE" if score >= 58 else "NEGATIVE" if score <= 42 else "CONFLICTING" if pos and neg else "NEUTRAL"
    return {"bias": bias, "score": round(score, 1), "positive": pos, "negative": neg, "conflicting": min(pos, neg)}


def _latency_guard(snapshot: dict, rows: List[dict]) -> dict:
    now = time.time()
    ages = [_f(x.get("quote_age_sec")) for x in rows]; ages = [x for x in ages if x is not None]
    last_tick = _f(snapshot.get("last_tick_epoch"))
    tick_age = max(0.0, now - last_tick) if last_tick else None
    med = statistics.median(ages) if ages else None
    p95 = sorted(ages)[min(len(ages) - 1, int(len(ages) * .95))] if ages else None
    if tick_age is not None and tick_age > 45: state = "STALE"
    elif med is not None and med > 20: state = "DELAYED"
    elif snapshot.get("websocket_connected") and (tick_age is None or tick_age <= 10): state = "LIVE"
    else: state = "REST / WARMING"
    return {"state": state, "transport": "WS" if snapshot.get("websocket_connected") else "REST", "feed_lag_sec": round(tick_age, 2) if tick_age is not None else None, "median_quote_age_sec": round(med, 2) if med is not None else None, "p95_quote_age_sec": round(p95, 2) if p95 is not None else None}


def ai_brain(snapshot: dict, radar: Optional[dict] = None) -> dict:
    radar = radar or pre_move_radar(snapshot, record=False)
    rows = radar.get("rows") or []
    confirmed = [x for x in rows if (x.get("fast_signal") or {}).get("tier") == "CONFIRMED"]
    early = [x for x in rows if (x.get("fast_signal") or {}).get("tier") == "EARLY"]
    legacy = [x for x in rows if x.get("pre_move_stage") in ("ARMING", "TRIGGER READY") and not x.get("late_entry") and (_f(x.get("quote_age_sec"), 999) or 999) <= 15]
    best = (confirmed or early or legacy or [None])[0]
    bias = _module_bias(rows)
    evidence_matrix = {
        "Pre-Move": "POSITIVE" if best and best.get("v72_side") == "CE" else "NEGATIVE" if best and best.get("v72_side") == "PE" else "NEUTRAL",
        "Market Breadth": bias.get("bias"),
        "Depth": ((best or {}).get("depth_intelligence") or {}).get("bias", "NEUTRAL"),
        "OI": ((best or {}).get("oi_state") or {}).get("bias", "NEUTRAL"),
        "Relative Strength": "POSITIVE" if best and best.get("relative_strength", 0) > .2 else "NEGATIVE" if best and best.get("relative_strength", 0) < -.2 else "NEUTRAL",
        "Freshness": "POSITIVE" if best and (_f(best.get("quote_age_sec"), 999) or 999) <= 10 else "CONFLICTING" if best else "NEUTRAL",
    }
    pos = sum(1 for v in evidence_matrix.values() if v == "POSITIVE")
    neg = sum(1 for v in evidence_matrix.values() if v == "NEGATIVE")
    conflicts = min(pos, neg) + sum(1 for v in evidence_matrix.values() if v == "CONFLICTING")
    fast = (best or {}).get("fast_signal") or {}
    tier = fast.get("tier") or "NONE"
    if not best:
        action = "WAIT"; state = "SCANNING"; conf = max(0, 50 - conflicts * 7)
    else:
        state = "FAST CONFIRMED" if tier == "CONFIRMED" else "FAST EARLY" if tier == "EARLY" else (best.get("pre_move_stage") or "SCANNING")
        conf = _clamp((best.get("pre_move_score") or 0) - conflicts * 6 - (best.get("opportunity_decay") or 0) * .18)
        if tier == "CONFIRMED" and conflicts <= 1:
            action = f"BUY {best.get('v72_side')}"
        elif tier == "EARLY" and conflicts <= 1:
            action = f"EARLY {best.get('v72_side')}"
        else:
            action = "WAIT"
        if conflicts >= 3 or conf < 60:
            action = "WAIT"
    why_not = []
    if not best: why_not.append("No fresh fast/arming candidate")
    if best and best.get("late_entry"): why_not.append("Move already active — chase filter")
    if conflicts >= 2: why_not.append("Evidence conflict elevated")
    if best and (_f(best.get("quote_age_sec"), 999) or 999) > 15: why_not.append("Quote freshness failed")
    if best and tier == "EARLY": why_not.append("EARLY signal is not yet CONFIRMED BUY")
    return {
        "name": "AI Brain 3.1 Fast Signal", "action": action, "state": state, "confidence": round(conf, 1),
        "signal_tier": tier, "fast_signal": fast,
        "best_candidate": best, "data_bias": bias, "evidence_matrix": evidence_matrix,
        "conflict_count": conflicts, "why_not": why_not,
        "thesis_lock": "One active directional thesis; a verified flip invalidates the old thesis.",
        "driver_policy": "Fast signals use fresh independent leading evidence. EARLY is low-latency; BUY requires CONFIRMED evidence. VWAP/lagging averages remain context only.",
    }


def _chain_pcr(chain_payload: dict, symbol: str) -> dict:
    rows = chain_payload.get("chain") or []
    spot = _f(chain_payload.get("spot"))
    ce_oi = pe_oi = ce_vol = pe_vol = ce_doi = pe_doi = 0.0
    weighted_ce = weighted_pe = 0.0
    strikes = sorted([_f(r.get("strike")) for r in rows if _f(r.get("strike")) is not None])
    steps = [b - a for a, b in zip(strikes, strikes[1:]) if b > a]
    step = statistics.median(steps) if steps else 1.0
    for r in rows:
        k = _f(r.get("strike")); ce = r.get("ce") or {}; pe = r.get("pe") or {}
        co, po = _f(ce.get("oi"), 0.0) or 0.0, _f(pe.get("oi"), 0.0) or 0.0
        cv, pv = _f(ce.get("volume"), 0.0) or 0.0, _f(pe.get("volume"), 0.0) or 0.0
        cprev, pprev = _f(ce.get("prev_oi"), co) or co, _f(pe.get("prev_oi"), po) or po
        ce_oi += co; pe_oi += po; ce_vol += cv; pe_vol += pv
        ce_doi += max(0.0, co - cprev); pe_doi += max(0.0, po - pprev)
        dist = abs((k or spot or 0) - (spot or k or 0)) / max(step, 1e-9) if k is not None else 9
        w = 1.0 / (1.0 + dist)
        weighted_ce += co * w; weighted_pe += po * w
    def ratio(a, b): return round(a / b, 3) if b > 0 else None
    metrics = {"oi_pcr": ratio(pe_oi, ce_oi), "volume_pcr": ratio(pe_vol, ce_vol), "change_oi_pcr": ratio(pe_doi, ce_doi), "atm_weighted_pcr": ratio(weighted_pe, weighted_ce)}
    now = time.time()
    with _LOCK:
        h = _CHAIN_STATE[symbol]
        h.append({"t": now, **metrics})
        hist = list(h)
    vel = None
    if len(hist) >= 2 and metrics.get("oi_pcr") is not None:
        old = next((x for x in reversed(hist[:-1]) if now - x["t"] >= 30 and x.get("oi_pcr") is not None), hist[0])
        if old.get("oi_pcr") is not None:
            dt = max(1.0, now - old["t"]); vel = (metrics["oi_pcr"] - old["oi_pcr"]) * 60.0 / dt
    metrics["pcr_velocity_per_min"] = round(vel, 4) if vel is not None else None
    metrics["spot"] = spot; metrics["strike_step"] = step
    return metrics


def predictive_strike_selector(symbol: str, underlying: dict, chain_payload: dict) -> dict:
    base = stock_option_hero(symbol, underlying, chain_payload, record=False)
    pcr = _chain_pcr(chain_payload, symbol)
    rows = chain_payload.get("chain") or []
    spot = _f(chain_payload.get("spot")) or _f(underlying.get("ltp"))
    strikes = sorted([_f(r.get("strike")) for r in rows if _f(r.get("strike")) is not None])
    step = _f(pcr.get("strike_step"), 1.0) or 1.0
    atm = min(strikes, key=lambda x: abs(x - spot)) if strikes and spot else None
    base_map = {str(x.get("contract_key")): x for x in (base.get("candidates") or [])}
    target_side = underlying.get("v72_side") or underlying.get("side") or "WAIT"
    scored = []
    for r in rows:
        strike = _f(r.get("strike"))
        if strike is None: continue
        steps_from_atm = abs(strike - (atm or strike)) / max(step, 1e-9)
        if steps_from_atm > 4.2: continue
        for side, legname in (("CE", "ce"), ("PE", "pe")):
            leg = r.get(legname) or {}; premium = _f(leg.get("ltp")); key = str(leg.get("key") or "")
            if premium is None or premium <= 0: continue
            bid, ask = _f(leg.get("bid")), _f(leg.get("ask")); spread = ((ask - bid) / premium * 100.0) if ask is not None and bid is not None and ask >= bid else None
            oi = _f(leg.get("oi"), 0.0) or 0.0; prev = _f(leg.get("prev_oi"), oi) or oi; vol = _f(leg.get("volume"), 0.0) or 0.0
            delta = abs(_f(leg.get("delta"), 0.0) or 0.0); gamma = abs(_f(leg.get("gamma"), 0.0) or 0.0); theta = abs(_f(leg.get("theta"), 0.0) or 0.0); iv = _f(leg.get("iv"))
            b = base_map.get(key, {})
            align = 100 if target_side == side else 48 if target_side == "WAIT" else 0
            proximity = _clamp(100 - steps_from_atm * 20)
            delta_q = 100 if .35 <= delta <= .65 else 82 if .25 <= delta <= .75 else 55 if .15 <= delta <= .85 else 25
            liquidity = _f(b.get("liquidity_score"), 45.0) or 45.0
            if spread is not None and spread > 12: liquidity -= 25
            premium_velocity = _f(b.get("premium_velocity_15s"))
            response = _clamp(50 + (premium_velocity or 0) * 8)
            oi_flow = _clamp(50 + ((oi - prev) / max(abs(prev), 1.0) * 100.0) * 2.0)
            gamma_q = _clamp(gamma * max(spot or 1.0, 1.0) * 650)
            theta_risk = _clamp(theta / max(premium, 1.0) * 1000)
            iv_q = 65 if iv is None else 78 if 8 <= iv <= 55 else 58 if iv <= 85 else 38
            score = align * .25 + proximity * .12 + delta_q * .10 + liquidity * .16 + response * .13 + oi_flow * .08 + gamma_q * .06 + iv_q * .05 + max(0, 100 - theta_risk) * .05
            eligible = premium >= 50 and align >= 90 and liquidity >= 52 and (spread is None or spread <= 12)
            if premium < 50: score -= 18
            if spread is not None and spread > 12: score -= 15
            scored.append({"symbol": symbol, "expiry": chain_payload.get("expiry"), "strike": strike, "side": side, "contract_key": key,
                           "premium": premium, "score": round(_clamp(score), 1), "eligible": bool(eligible), "steps_from_atm": round(steps_from_atm, 2),
                           "liquidity": round(_clamp(liquidity), 1), "spread_pct": round(spread, 2) if spread is not None else None,
                           "delta": _f(leg.get("delta")), "gamma": _f(leg.get("gamma")), "theta": _f(leg.get("theta")), "iv": iv,
                           "oi": oi, "oi_change": oi - prev, "volume": vol, "premium_velocity": premium_velocity,
                           "scores": {"alignment": align, "proximity": round(proximity,1), "delta": round(delta_q,1), "liquidity": round(_clamp(liquidity),1), "premium_response": round(response,1), "oi_flow": round(oi_flow,1), "gamma": round(gamma_q,1), "theta_risk": round(theta_risk,1)}})
    scored.sort(key=lambda x: (x["eligible"], x["score"]), reverse=True)
    eligible = [x for x in scored if x["eligible"] and x["side"] == target_side]
    winner = eligible[0] if eligible else None

    # Multi-strike confirmation around the chosen direction.
    same = [x for x in scored if x["side"] == target_side and x["steps_from_atm"] <= 1.6]
    responsive = sum(1 for x in same if (_f(x.get("premium_velocity"), 0.0) or 0.0) > .15 or x.get("oi_change", 0) > 0 or x.get("volume", 0) > 0)
    multi_confirm = responsive >= 2 if len(same) >= 2 else False
    if winner and multi_confirm:
        winner = dict(winner); winner["score"] = round(_clamp(winner["score"] + 4), 1); winner["multi_strike_confirmation"] = True

    side_pcr_bias = "NEUTRAL"
    opcr = _f(pcr.get("oi_pcr"))
    if opcr is not None:
        side_pcr_bias = "CE" if opcr >= 1.08 else "PE" if opcr <= .92 else "NEUTRAL"
    hero_state = "NO TRADE"
    if winner and winner["score"] >= 84 and multi_confirm: hero_state = "HERO CALL" if target_side == "CE" else "HERO PUT"
    elif winner and winner["score"] >= 74: hero_state = "TRIGGER READY CALL" if target_side == "CE" else "TRIGGER READY PUT"
    why_not = []
    if target_side == "WAIT": why_not.append("underlying thesis is WAIT")
    if not winner: why_not.append("no ₹50+ liquid aligned strike passed filters")
    if winner and not multi_confirm: why_not.append("multi-strike confirmation incomplete")
    if winner and winner.get("score", 0) < 84: why_not.append("Hero evidence score below 84")
    return {"status": "READY" if scored else "UNAVAILABLE", "symbol": symbol, "expiry": chain_payload.get("expiry"), "spot": spot, "atm": atm,
            "direction": target_side, "hero_state": hero_state, "winner": winner, "top_candidates": scored[:16], "pcr": pcr,
            "pcr_direction_context": side_pcr_bias, "multi_strike_confirmation": multi_confirm, "why_not_hero": why_not,
            "policy": "Hero requires ₹50+ premium at alert time, directional alignment, acceptable liquidity and multi-strike evidence. No hard premium ceiling and no profit guarantee."}


def _rsi(values: List[float], period: int = 14) -> List[Optional[float]]:
    if not values: return []
    out: List[Optional[float]] = [None] * len(values)
    if len(values) <= period: return out
    gains, losses = [], []
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]; gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = sum(gains) / period; al = sum(losses) / period
    out[period] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        ag = (ag * (period - 1) + max(d, 0)) / period
        al = (al * (period - 1) + max(-d, 0)) / period
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def _pivots(cs: List[dict], w: int = 2):
    highs, lows = [], []
    for i in range(w, len(cs) - w):
        seg = cs[i-w:i+w+1]
        if cs[i]["high"] >= max(x["high"] for x in seg): highs.append((i, cs[i]["high"]))
        if cs[i]["low"] <= min(x["low"] for x in seg): lows.append((i, cs[i]["low"]))
    return highs, lows


def _norm_candles(candles: List[Any]) -> List[dict]:
    out = []
    for c in candles or []:
        if isinstance(c, dict):
            o,h,l,cl = _f(c.get("open")),_f(c.get("high")),_f(c.get("low")),_f(c.get("close")); vol=_f(c.get("volume")); ts=c.get("ts") or c.get("timestamp")
        elif isinstance(c,(list,tuple)) and len(c)>=5:
            ts=c[0]; o,h,l,cl=_f(c[1]),_f(c[2]),_f(c[3]),_f(c[4]); vol=_f(c[5]) if len(c)>5 else None
        else: continue
        if None in (o,h,l,cl): continue
        out.append({"ts":str(ts),"open":o,"high":h,"low":l,"close":cl,"volume":vol})
    return out


def predictive_chart_intelligence(candles: List[Any], symbol: str, interval: int, snapshot: dict, census_row: Optional[dict] = None) -> dict:
    cs = _norm_candles(candles)
    base71 = chart_intelligence_v71(candles, symbol, interval, snapshot, census_row)
    base67 = build_chart_intelligence_v67(candles, symbol, interval, snapshot, {})
    if len(cs) < 20:
        return {"status":"UNAVAILABLE","version":"72.0","symbol":symbol,"reason":"Need at least 20 valid candles","base_v71":base71,"base_v67":base67}
    closes=[x["close"] for x in cs]; rsi=_rsi(closes); highs,lows=_pivots(cs,2); last=closes[-1]
    divergences=[]
    if len(lows)>=2:
        (i1,p1),(i2,p2)=lows[-2],lows[-1]; r1,r2=rsi[i1],rsi[i2]
        if r1 is not None and r2 is not None:
            if p2 < p1 and r2 > r1: divergences.append({"type":"REGULAR BULLISH RSI DIVERGENCE","side":"BULL","price_1":p1,"price_2":p2,"rsi_1":round(r1,1),"rsi_2":round(r2,1)})
            if p2 > p1 and r2 < r1: divergences.append({"type":"HIDDEN BULLISH RSI DIVERGENCE","side":"BULL","price_1":p1,"price_2":p2,"rsi_1":round(r1,1),"rsi_2":round(r2,1)})
    if len(highs)>=2:
        (i1,p1),(i2,p2)=highs[-2],highs[-1]; r1,r2=rsi[i1],rsi[i2]
        if r1 is not None and r2 is not None:
            if p2 > p1 and r2 < r1: divergences.append({"type":"REGULAR BEARISH RSI DIVERGENCE","side":"BEAR","price_1":p1,"price_2":p2,"rsi_1":round(r1,1),"rsi_2":round(r2,1)})
            if p2 < p1 and r2 > r1: divergences.append({"type":"HIDDEN BEARISH RSI DIVERGENCE","side":"BEAR","price_1":p1,"price_2":p2,"rsi_1":round(r1,1),"rsi_2":round(r2,1)})

    recent=cs[-20:]; prior=cs[-40:-20] if len(cs)>=40 else cs[:-20]
    rr=max(x["high"] for x in recent)-min(x["low"] for x in recent); pr=max(x["high"] for x in prior)-min(x["low"] for x in prior) if prior else rr
    compression_ratio=rr/max(pr,1e-9)
    compression_state="SQUEEZE" if compression_ratio<=.62 else "CONTRACTING" if compression_ratio<=.82 else "NORMAL"
    prev_hi=max(x["high"] for x in cs[-21:-1]); prev_lo=min(x["low"] for x in cs[-21:-1]); lastc=cs[-1]
    sweep=None
    if lastc["high"]>prev_hi and lastc["close"]<prev_hi: sweep={"side":"BEAR","type":"BUY-SIDE LIQUIDITY SWEEP","level":prev_hi}
    elif lastc["low"]<prev_lo and lastc["close"]>prev_lo: sweep={"side":"BULL","type":"SELL-SIDE LIQUIDITY SWEEP","level":prev_lo}

    fib=(base67.get("fibonacci") or {})
    patterns=base67.get("forming_patterns") or []
    leading=[]; counter=[]; signed=0.0
    for d in divergences[:2]:
        s=15 if d["side"]=="BULL" else -15; signed+=s; leading.append(d["type"])
    if sweep:
        signed += 16 if sweep["side"]=="BULL" else -16; leading.append(sweep["type"])
    if patterns:
        p=patterns[0]; ps=p.get("side")
        if ps=="BULL": signed+=18
        elif ps=="BEAR": signed-=18
        if p.get("stage") in ("TRIGGER NEAR","MATURE"): leading.append(f"{p.get('pattern')} {p.get('stage')}")
    if compression_state in ("SQUEEZE","CONTRACTING"): leading.append(f"volatility {compression_state.lower()}")
    if census_row:
        rs=_f(census_row.get("relative_strength")); dp=_f((census_row.get("depth_intelligence") or {}).get("pressure"));
        if rs is not None: signed+=_clamp(rs*8,-12,12)
        if dp is not None: signed+=_clamp((dp-50)*.3,-10,10)
        if census_row.get("late_entry"): counter.append("late-entry filter active")
    signed=_clamp(signed,-100,100); side="CE" if signed>=16 else "PE" if signed<=-16 else "WAIT"
    score=abs(signed)
    if compression_state=="SQUEEZE": score+=14
    if divergences: score+=8
    if sweep: score+=10
    score=_clamp(score)
    stage="TRIGGER READY" if score>=72 and side!="WAIT" else "ARMING" if score>=60 and side!="WAIT" else "BUILDING" if score>=45 else "WATCH"
    return {"status":"READY","version":"72.0","symbol":symbol.upper(),"interval":interval,"side":side,"score":round(score,1),"stage":stage,
            "leading_evidence":leading[:10],"counter_evidence":counter[:8],"rsi":{"latest":round(rsi[-1],1) if rsi[-1] is not None else None,"divergences":divergences},
            "liquidity_sweep":sweep,"compression":{"state":compression_state,"range_ratio":round(compression_ratio,3)},
            "patterns":patterns[:10],"fibonacci":fib,"base_v71":base71,"base_v67":base67,
            "policy":"Leading pattern/divergence/liquidity/compression evidence only drives this V72 score. VWAP/EMA remain context in legacy chart modules, not the V72 predictive driver."}


def lead_time_audit(minutes: int = 390, threshold_pct: float = 1.25) -> dict:
    cutoff=time.time()-max(30,int(minutes))*60
    base=missed_move_audit_v71(minutes,threshold_pct)
    try:
        with _db() as c:
            ev=[dict(x) for x in c.execute("SELECT epoch,symbol,stage,side,score,price,trigger_price FROM premove_events_v72 WHERE epoch>=? ORDER BY symbol,epoch",(cutoff,))]
            snaps=[dict(x) for x in c.execute("SELECT epoch,symbol,ltp FROM premove_snapshots_v72 WHERE epoch>=? ORDER BY symbol,epoch",(cutoff,))]
    except Exception as exc:
        return {"status":"UNAVAILABLE","reason":str(exc),"base_v71":base}
    byev=defaultdict(list); bys=defaultdict(list)
    for x in ev: byev[x["symbol"]].append(x)
    for x in snaps: bys[x["symbol"]].append(x)
    rows=[]
    for sym, hist in bys.items():
        if len(hist)<2: continue
        prices=[_f(x.get("ltp")) for x in hist]; prices=[x for x in prices if x is not None]
        if len(prices)<2: continue
        move=(max(prices)-min(prices))/max(min(prices),1e-9)*100
        if move<threshold_pct: continue
        first=next((x for x in byev.get(sym,[]) if x.get("stage") in ("ARMING","TRIGGER READY")),None)
        lead=None
        if first:
            # Lead time to first subsequent 0.7% excursion in signaled direction.
            p0=_f(first.get("price")); t0=_f(first.get("epoch")); side=first.get("side")
            if p0 and t0:
                for s in hist:
                    if s["epoch"]<=t0: continue
                    p=_f(s.get("ltp"));
                    if p is None: continue
                    excursion=(p-p0)/p0*100*(1 if side=="CE" else -1)
                    if excursion>=.7:
                        lead=(s["epoch"]-t0)/60; break
        rows.append({"symbol":sym,"range_move_pct":round(move,2),"early_detected":bool(first),"first_event":first,"lead_time_min":round(lead,1) if lead is not None else None})
    leads=[x["lead_time_min"] for x in rows if x.get("lead_time_min") is not None]
    return {"status":"READY","minutes":minutes,"threshold_pct":threshold_pct,"qualifying_moves":len(rows),"early_detected":sum(1 for x in rows if x["early_detected"]),"median_lead_time_min":round(statistics.median(leads),1) if leads else None,"events":sorted(rows,key=lambda x:x["range_move_pct"],reverse=True),"base_v71":base,"policy":"Lead time measures stored detection before an observed follow-through threshold; it is not a win-rate or execution guarantee."}


def build_v72(snapshot: dict, record: bool = True) -> dict:
    base = build_v71(snapshot, record=record)
    radar = pre_move_radar(snapshot, record=record and not snapshot.get("demo"))
    brain = ai_brain(snapshot, radar)
    rows = radar.get("rows") or []
    latency = _latency_guard(snapshot, rows)
    sectors = sorted(radar.get("sector_stats") or [], key=lambda x: abs(_f(x.get("breadth"),0) or 0), reverse=True)
    best = (radar.get("trigger_ready") or radar.get("arming") or radar.get("building") or radar.get("top") or [None])[0]
    command = {
        "universe_coverage": f"{radar.get('observed',0)}/{radar.get('expected_universe',0)}",
        "fresh_data_pct": radar.get("freshness_pct"),
        "pre_move_candidates": sum(1 for x in rows if x.get("pre_move_stage") in ("EARLY CLUE","BUILDING","ARMING","TRIGGER READY")),
        "arming": len(radar.get("arming") or []), "trigger_ready": len(radar.get("trigger_ready") or []),
        "fast_early": len(radar.get("fast_early") or []), "fast_confirmed": len(radar.get("fast_confirmed") or []),
        "late_movers": len(radar.get("late") or []), "best_candidate": best,
    }
    return {
        "version":"72.0","release":"72.1-fast-signal","name":"Fast Signal + Accuracy Guard • Predictive AI Brain 3.1","generated_at":datetime.now(timezone.utc).isoformat(),
        "read_only":True,"execution_enabled":False,"base_v71":base,"ai_brain":brain,
        "pre_move_radar":{k:v for k,v in radar.items() if k!="rows"},"pre_move_rows":rows,
        "market_heatmap":rows[:60],"sector_heatmap":sectors,"latency_guard":latency,"command_center":command,
        "modules":{
            "leading_first_decision_engine":True,"pre_move_pressure_score":True,"compression_squeeze":True,"relative_strength_acceleration":True,
            "sector_breadth_ignition":True,"leader_follower_cascade":True,"depth_pressure_up_to_30_levels_when_feed_supplies_it":True,
            "order_book_persistence":True,"futures_oi_state":True,"opportunity_decay":True,"late_entry_filter":True,"trigger_countdown":True,
            "predictive_strike_intelligence":True,"pcr_multi_metric":True,"hero_premium_floor_50":True,"multi_strike_confirmation":True,
            "rsi_divergence":True,"liquidity_sweep":True,"auto_fibonacci_context":True,"pattern_lifecycle":True,
            "latency_guard":True,"lead_time_audit":True,"whole_fno_census_preserved":True,
            "fast_signal_two_stage":True,"independent_evidence_accuracy_guard":True,"stale_signal_block":True,
        },
        "truth_policy":[
            "No 100% win or move-capture claim.","Missing data is never invented.","Big Money is behavioural footprint language only; anonymous activity is not assigned to FII/DII/PRO.",
            "Premium Hero candidates require ₹50+ at alert time; there is no hard upper premium cap.","MOVE ALREADY ACTIVE candidates are retained for discovery but marked DO NOT CHASE / retracement only.",
            "VWAP/EMA/MACD can remain chart context in legacy modules but do not drive the V72 leading-first decision score.","No broker execution, no automatic orders, no P&L ledger."
        ],
    }
