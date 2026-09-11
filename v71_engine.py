from __future__ import annotations

"""POWERHOUSE AI V71 — Universal Opportunity Radar + Intelligence Chart.

Read-only market intelligence. The V71 layer is designed around observation coverage:
- every discovered F&O underlying is scored before UI ranking/truncation,
- fast in-memory state tracks price/volume/OI acceleration across snapshots,
- optional SQLite event store records census/detection history for audit/replay,
- stock-option Hero scoring is evidence-based and never labelled guaranteed profit,
- chart intelligence adds structure/profile/scenario overlays without drawing fake future candles.
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
from typing import Any, Dict, Iterable, List, Optional

from v70_engine import build_v70

ROOT = Path(__file__).parent
DB_PATH = Path(os.getenv("POWERHOUSE_V71_DB_PATH") or (ROOT / ".runtime" / "powerhouse_v71.sqlite3"))
SNAPSHOT_SECONDS = max(5, int(os.getenv("POWERHOUSE_V71_SNAPSHOT_SECONDS", "15")))

_LOCK = threading.RLock()
_STOCK_STATE: Dict[str, deque] = defaultdict(lambda: deque(maxlen=900))
_OPTION_STATE: Dict[str, deque] = defaultdict(lambda: deque(maxlen=600))
_LAST_STAGE: Dict[str, str] = {}
_LAST_DB_EPOCH = 0.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS universal_snapshots_v71(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 epoch REAL NOT NULL,
 symbol TEXT NOT NULL,
 ltp REAL,
 change_pct REAL,
 volume REAL,
 rvol REAL,
 futures_oi REAL,
 futures_oi_change_pct REAL,
 velocity_15s REAL,
 velocity_30s REAL,
 velocity_60s REAL,
 acceleration REAL,
 signed_score REAL,
 evidence_score REAL,
 stage TEXT,
 side TEXT,
 quote_age_sec REAL,
 payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_v71_us_symbol_epoch ON universal_snapshots_v71(symbol, epoch DESC);
CREATE INDEX IF NOT EXISTS idx_v71_us_epoch ON universal_snapshots_v71(epoch DESC);
CREATE TABLE IF NOT EXISTS discovery_events_v71(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 epoch REAL NOT NULL,
 symbol TEXT NOT NULL,
 event_type TEXT NOT NULL,
 stage TEXT,
 side TEXT,
 score REAL,
 price REAL,
 payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_v71_de_symbol_epoch ON discovery_events_v71(symbol, epoch DESC);
CREATE TABLE IF NOT EXISTS option_hero_snapshots_v71(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 epoch REAL NOT NULL,
 symbol TEXT NOT NULL,
 expiry TEXT,
 contract_key TEXT,
 strike REAL,
 side TEXT,
 premium REAL,
 score REAL,
 stage TEXT,
 liquidity REAL,
 premium_velocity REAL,
 oi_velocity REAL,
 payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_v71_oh_symbol_epoch ON option_hero_snapshots_v71(symbol, epoch DESC);
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


def _pct(a: Any, b: Any):
    a = _f(a); b = _f(b)
    if a is None or b in (None, 0):
        return None
    return (a - b) / abs(b) * 100.0


def _mean(vals: Iterable[Any], default=None):
    xs = [_f(x) for x in vals]
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else default


def _velocity(hist: List[dict], seconds: int) -> Optional[float]:
    if len(hist) < 2:
        return None
    cur = hist[-1]
    old = None
    for x in reversed(hist[:-1]):
        if cur["t"] - x["t"] >= seconds:
            old = x
            break
    old = old or hist[0]
    if not old.get("px"):
        return None
    dt = max(1.0, cur["t"] - old["t"])
    return (cur["px"] - old["px"]) / abs(old["px"]) * 100.0 * 60.0 / dt


def _delta_velocity(hist: List[dict], key: str, seconds: int) -> Optional[float]:
    vals = [x for x in hist if _f(x.get(key)) is not None]
    if len(vals) < 2:
        return None
    cur = vals[-1]
    old = None
    for x in reversed(vals[:-1]):
        if cur["t"] - x["t"] >= seconds:
            old = x
            break
    old = old or vals[0]
    a = _f(cur.get(key)); b = _f(old.get(key))
    if a is None or b in (None, 0):
        return None
    dt = max(1.0, cur["t"] - old["t"])
    return (a - b) / abs(b) * 100.0 * 60.0 / dt


def _nearest_levels(row: dict, px: float) -> dict:
    levels = {
        "PDH": _f(row.get("prev_day_high")),
        "PDL": _f(row.get("prev_day_low")),
        "PDC": _f(row.get("prev_day_close")),
        "20D_HIGH": _f(row.get("high_20d")),
        "20D_LOW": _f(row.get("low_20d")),
        "50D_HIGH": _f(row.get("high_50d")),
        "50D_LOW": _f(row.get("low_50d")),
        "52W_HIGH": _f(row.get("high_52w")),
        "52W_LOW": _f(row.get("low_52w")),
        "ATP": _f(row.get("atp")),
    }
    levels = {k: v for k, v in levels.items() if v is not None and v > 0}
    above = [(k, v, (v - px) / px * 100.0) for k, v in levels.items() if v >= px]
    below = [(k, v, (px - v) / px * 100.0) for k, v in levels.items() if v <= px]
    above.sort(key=lambda z: z[2]); below.sort(key=lambda z: z[2])
    return {
        "above": {"name": above[0][0], "value": above[0][1], "distance_pct": round(above[0][2], 3)} if above else None,
        "below": {"name": below[0][0], "value": below[0][1], "distance_pct": round(below[0][2], 3)} if below else None,
        "all": levels,
    }


def _scan_stock(row: dict, now: float) -> Optional[dict]:
    sym = str(row.get("symbol") or "").upper().strip()
    px = _f(row.get("ltp"))
    if not sym or px is None or px <= 0:
        return None
    cp = _f(row.get("change_pct"), 0.0) or 0.0
    vol = _f(row.get("volume")); rv = _f(row.get("rvol")); oi = _f(row.get("futures_oi")); oic = _f(row.get("futures_oi_change_pct"))
    bid = _f(row.get("bid")); ask = _f(row.get("ask")); bq = _f(row.get("bid_qty")); aq = _f(row.get("ask_qty"))
    spread_pct = ((ask - bid) / px * 100.0) if ask is not None and bid is not None and ask >= bid and px else None
    bid_pressure = (100.0 * bq / (bq + aq)) if bq is not None and aq is not None and bq + aq > 0 else None

    with _LOCK:
        hist = _STOCK_STATE[sym]
        if not hist or now - hist[-1]["t"] >= 1.0:
            hist.append({"t": now, "px": px, "vol": vol, "oi": oi, "cp": cp})
        h = list(hist)
    v15 = _velocity(h, 15); v30 = _velocity(h, 30); v60 = _velocity(h, 60); v180 = _velocity(h, 180)
    volvel = _delta_velocity(h, "vol", 60)
    oivel = _delta_velocity(h, "oi", 60)
    accel = None if v15 is None or v60 is None else v15 - v60
    lv = _nearest_levels(row, px)
    above = lv.get("above"); below = lv.get("below")

    # Signed directional score, deliberately bounded and transparent.
    signed = _clamp(cp * 12.0, -34, 34)
    if v15 is not None: signed += _clamp(v15 * 10.0, -18, 18)
    if v60 is not None: signed += _clamp(v60 * 5.0, -12, 12)
    if oic is not None:
        # OI increase amplifies current price direction; OI decrease slightly tempers it.
        signed += _clamp(math.copysign(min(abs(oic) * 1.5, 13), cp if abs(cp) > .03 else (v60 or 0.01)), -13, 13)
    atp = _f(row.get("atp"))
    if atp:
        av = _pct(px, atp) or 0
        signed += _clamp(av * 18, -12, 12)
    signed = _clamp(signed, -100, 100)

    score = abs(signed) * .58
    if rv is not None: score += _clamp((rv - 1.0) * 22, 0, 20)
    if volvel is not None and volvel > 0: score += _clamp(volvel * .25, 0, 10)
    if accel is not None: score += _clamp(abs(accel) * 8, 0, 8)
    near = min([z["distance_pct"] for z in (above, below) if z], default=None)
    if near is not None: score += 12 if near <= .20 else 8 if near <= .50 else 4 if near <= 1.0 else 0
    if spread_pct is not None: score += 7 if spread_pct <= .08 else 4 if spread_pct <= .20 else -8 if spread_pct > .75 else 0
    if bid_pressure is not None and abs(bid_pressure - 50) >= 12: score += 5
    score = _clamp(score)

    side = "CE" if signed >= 12 else "PE" if signed <= -12 else "WAIT"
    if score >= 86 and side != "WAIT": stage = "HERO READY"
    elif score >= 74 and side != "WAIT": stage = "TRIGGER READY"
    elif score >= 61 and side != "WAIT": stage = "EARLY MOVER"
    elif score >= 47: stage = "BUILDING"
    else: stage = "WATCH"

    evidence, counter = [], []
    if abs(cp) >= .7: evidence.append(f"price {cp:+.2f}%")
    if v15 is not None and abs(v15) >= .25: evidence.append(f"15s velocity {v15:+.2f}%/min")
    if accel is not None and abs(accel) >= .18: evidence.append(f"acceleration {accel:+.2f}")
    if rv is not None and rv >= 1.35: evidence.append(f"RVOL {rv:.2f}x")
    if oic is not None and abs(oic) >= 1.0: evidence.append(f"futures OI {oic:+.2f}%")
    if near is not None and near <= .5: evidence.append(f"key level {near:.2f}% away")
    if spread_pct is not None and spread_pct <= .20: evidence.append("tight top-of-book spread")
    if spread_pct is not None and spread_pct > .75: counter.append(f"wide spread {spread_pct:.2f}%")
    if side == "CE" and bid_pressure is not None and bid_pressure < 40: counter.append("displayed depth conflicts")
    if side == "PE" and bid_pressure is not None and bid_pressure > 60: counter.append("displayed depth conflicts")
    age = now - (_f(row.get("quote_epoch"), now) or now)
    if age > 30: counter.append(f"quote age {age:.0f}s")

    return {
        "symbol": sym, "sector": row.get("sector") or "F&O", "ltp": px, "change_pct": round(cp, 3),
        "volume": vol, "rvol": rv, "futures_oi": oi, "futures_oi_change_pct": oic,
        "velocity_15s": round(v15, 4) if v15 is not None else None,
        "velocity_30s": round(v30, 4) if v30 is not None else None,
        "velocity_60s": round(v60, 4) if v60 is not None else None,
        "velocity_180s": round(v180, 4) if v180 is not None else None,
        "volume_velocity": round(volvel, 3) if volvel is not None else None,
        "oi_velocity": round(oivel, 3) if oivel is not None else None,
        "acceleration": round(accel, 4) if accel is not None else None,
        "signed_score": round(signed, 1), "evidence_score": round(score, 1), "side": side, "stage": stage,
        "spread_pct": round(spread_pct, 4) if spread_pct is not None else None,
        "bid_pressure_pct": round(bid_pressure, 1) if bid_pressure is not None else None,
        "nearest_levels": lv, "evidence": evidence[:8], "counter_evidence": counter[:6],
        "quote_age_sec": round(max(0, age), 1), "live": bool(row.get("live")),
        "instrument_key": row.get("instrument_key"), "future_key": row.get("future_key"), "future_expiry": row.get("future_expiry"),
        "data_fields": {
            "price": px is not None, "volume": vol is not None, "rvol": rv is not None,
            "oi": oi is not None, "structure": bool(lv.get("all")), "top_book": bid is not None and ask is not None,
        },
    }


def _record_census(rows: List[dict], now: float) -> None:
    global _LAST_DB_EPOCH
    if not rows or now - _LAST_DB_EPOCH < SNAPSHOT_SECONDS:
        return
    vals = []
    events = []
    with _LOCK:
        for r in rows:
            sym = r["symbol"]
            payload = json.dumps({"evidence": r.get("evidence"), "counter": r.get("counter_evidence"), "levels": r.get("nearest_levels")}, default=str)[:12000]
            vals.append((now, sym, r.get("ltp"), r.get("change_pct"), r.get("volume"), r.get("rvol"), r.get("futures_oi"), r.get("futures_oi_change_pct"), r.get("velocity_15s"), r.get("velocity_30s"), r.get("velocity_60s"), r.get("acceleration"), r.get("signed_score"), r.get("evidence_score"), r.get("stage"), r.get("side"), r.get("quote_age_sec"), payload))
            prev = _LAST_STAGE.get(sym)
            if prev != r.get("stage") and r.get("stage") in ("EARLY MOVER", "TRIGGER READY", "HERO READY"):
                events.append((now, sym, "STAGE_PROMOTION", r.get("stage"), r.get("side"), r.get("evidence_score"), r.get("ltp"), payload))
            _LAST_STAGE[sym] = str(r.get("stage") or "")
    try:
        with _db() as c:
            c.executemany("INSERT INTO universal_snapshots_v71(epoch,symbol,ltp,change_pct,volume,rvol,futures_oi,futures_oi_change_pct,velocity_15s,velocity_30s,velocity_60s,acceleration,signed_score,evidence_score,stage,side,quote_age_sec,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", vals)
            if events:
                c.executemany("INSERT INTO discovery_events_v71(epoch,symbol,event_type,stage,side,score,price,payload) VALUES(?,?,?,?,?,?,?,?)", events)
            c.execute("DELETE FROM universal_snapshots_v71 WHERE epoch<?", (now - 45 * 86400,))
            c.execute("DELETE FROM discovery_events_v71 WHERE epoch<?", (now - 90 * 86400,))
            c.commit()
        _LAST_DB_EPOCH = now
    except Exception:
        pass


def universal_census(snapshot: dict, record: bool = True) -> dict:
    now = time.time()
    src = snapshot.get("sector_heatmap") or []
    rows = []
    for raw in src:
        if not isinstance(raw, dict):
            continue
        x = _scan_stock(raw, now)
        if x:
            rows.append(x)
    priority = {"HERO READY": 5, "TRIGGER READY": 4, "EARLY MOVER": 3, "BUILDING": 2, "WATCH": 1}
    rows.sort(key=lambda r: (priority.get(r["stage"], 0), r["evidence_score"], abs(r["signed_score"])), reverse=True)
    expected = int(((snapshot.get("fno_foundation") or {}).get("universe_count") or len(src) or 0))
    observed = len(rows)
    fresh = sum(1 for r in rows if r.get("quote_age_sec") is not None and r["quote_age_sec"] <= 10)
    live = sum(1 for r in rows if r.get("live"))
    field_names = ("price", "volume", "rvol", "oi", "structure", "top_book")
    fields = {k: sum(1 for r in rows if (r.get("data_fields") or {}).get(k)) for k in field_names}
    if record:
        _record_census(rows, now)
    coverage_pct = round(100.0 * observed / expected, 1) if expected else 0.0
    freshness_pct = round(100.0 * fresh / observed, 1) if observed else 0.0
    return {
        "status": "READY" if rows else "UNAVAILABLE",
        "expected_universe": expected, "observed": observed, "live_quotes": live, "fresh_under_10s": fresh,
        "coverage_pct": coverage_pct, "freshness_pct": freshness_pct, "field_coverage": fields,
        "coverage_state": "COMPLETE" if expected and observed >= expected else "PARTIAL" if observed else "UNAVAILABLE",
        "all_rows": rows,
        "hero_ready": [r for r in rows if r["stage"] == "HERO READY"],
        "trigger_ready": [r for r in rows if r["stage"] == "TRIGGER READY"],
        "early_movers": [r for r in rows if r["stage"] == "EARLY MOVER"],
        "building": [r for r in rows if r["stage"] == "BUILDING"],
        "top": rows[:30],
        "policy": "Every discovered F&O underlying is scored before ranking. Coverage means observation coverage, not guaranteed trade/win coverage.",
    }


def _option_leg(symbol: str, expiry: str, strike: float, side: str, leg: dict, underlying: dict, now: float) -> Optional[dict]:
    premium = _f(leg.get("ltp") or leg.get("premium"))
    if premium is None or premium <= 0:
        return None
    key = str(leg.get("key") or leg.get("instrument_key") or f"{symbol}:{expiry}:{strike}:{side}")
    oi = _f(leg.get("oi")); prev_oi = _f(leg.get("prev_oi")); volume = _f(leg.get("volume")); bid = _f(leg.get("bid")); ask = _f(leg.get("ask"))
    iv = _f(leg.get("iv")); delta = _f(leg.get("delta")); gamma = _f(leg.get("gamma")); theta = _f(leg.get("theta")); vega = _f(leg.get("vega"))
    with _LOCK:
        h = _OPTION_STATE[key]
        if not h or now - h[-1]["t"] >= 1.0:
            h.append({"t": now, "px": premium, "oi": oi, "vol": volume})
        hist = list(h)
    p15 = _velocity(hist, 15); p30 = _velocity(hist, 30); p60 = _velocity(hist, 60); oiv = _delta_velocity(hist, "oi", 60); vv = _delta_velocity(hist, "vol", 60)
    spread_pct = ((ask - bid) / premium * 100.0) if ask is not None and bid is not None and ask >= bid else None
    liquidity = 45.0
    if spread_pct is not None: liquidity += 28 if spread_pct <= 2 else 18 if spread_pct <= 5 else 5 if spread_pct <= 10 else -22
    if volume is not None and volume > 0: liquidity += min(18, math.log10(max(volume, 1)) * 3.5)
    if oi is not None and oi > 0: liquidity += min(9, math.log10(max(oi, 1)) * 1.5)
    liquidity = _clamp(liquidity)
    underlying_side = underlying.get("side") or "WAIT"
    align = 100 if underlying_side == side else 48 if underlying_side == "WAIT" else 0
    premium_momentum = _clamp(50 + (p15 or p30 or 0) * 7.5, 0, 100)
    oi_momentum = _clamp(50 + (oiv or 0) * 1.2, 0, 100)
    volume_wakeup = _clamp(45 + (vv or 0) * .25, 0, 100)
    gamma_response = _clamp(abs(gamma or 0) * max(_f(underlying.get("ltp"), 1) or 1, 1) * 700, 0, 100)
    delta_response = _clamp(abs(delta or 0) * 120, 0, 100)
    cheap_elasticity = 80 if premium <= 20 else 68 if premium <= 50 else 55 if premium <= 100 else 45
    raw = align * .24 + underlying.get("evidence_score", 0) * .22 + premium_momentum * .16 + liquidity * .14 + volume_wakeup * .08 + oi_momentum * .06 + gamma_response * .05 + delta_response * .03 + cheap_elasticity * .02
    if spread_pct is not None and spread_pct > 15: raw -= 18
    score = _clamp(raw)
    if score >= 88 and liquidity >= 60 and align >= 90: stage = "HERO ACTIVE"
    elif score >= 80 and liquidity >= 55: stage = "HERO READY"
    elif score >= 70: stage = "HERO FORMING"
    elif score >= 58: stage = "HERO WATCH"
    else: stage = "OBSERVE"
    evidence = []
    if align >= 90: evidence.append("underlying direction aligned")
    if p15 is not None and p15 > .8: evidence.append(f"premium velocity {p15:+.2f}%/min")
    if vv is not None and vv > 0: evidence.append("option volume accelerating")
    if oiv is not None and oiv > 0: evidence.append("option OI expanding")
    if liquidity >= 70: evidence.append("liquidity acceptable")
    if gamma_response >= 55: evidence.append("gamma sensitivity elevated")
    counter = []
    if spread_pct is not None and spread_pct > 10: counter.append(f"spread {spread_pct:.1f}%")
    if align == 0: counter.append("underlying master side conflicts")
    return {
        "symbol": symbol, "expiry": expiry, "contract_key": key, "strike": strike, "side": side,
        "premium": premium, "bid": bid, "ask": ask, "spread_pct": round(spread_pct, 2) if spread_pct is not None else None,
        "oi": oi, "prev_oi": prev_oi, "volume": volume, "iv": iv, "delta": delta, "gamma": gamma, "theta": theta, "vega": vega,
        "premium_velocity_15s": round(p15, 3) if p15 is not None else None,
        "premium_velocity_30s": round(p30, 3) if p30 is not None else None,
        "premium_velocity_60s": round(p60, 3) if p60 is not None else None,
        "oi_velocity": round(oiv, 3) if oiv is not None else None, "volume_velocity": round(vv, 3) if vv is not None else None,
        "liquidity_score": round(liquidity, 1), "premium_momentum": round(premium_momentum, 1),
        "score": round(score, 1), "stage": stage, "evidence": evidence, "counter_evidence": counter,
    }


def stock_option_hero(symbol: str, underlying: dict, chain_payload: dict, record: bool = True) -> dict:
    now = time.time(); expiry = str(chain_payload.get("expiry") or "")
    rows = chain_payload.get("chain") or []
    candidates = []
    for r in rows:
        strike = _f(r.get("strike"))
        if strike is None: continue
        for side, name in (("CE", "ce"), ("PE", "pe")):
            leg = r.get(name) or {}
            c = _option_leg(symbol, expiry, strike, side, leg, underlying, now)
            if c: candidates.append(c)
    candidates.sort(key=lambda x: (x["stage"] == "HERO ACTIVE", x["stage"] == "HERO READY", x["score"]), reverse=True)
    aligned = [x for x in candidates if underlying.get("side") in (x["side"], "WAIT")]
    winner = (aligned or candidates or [None])[0]
    if record and winner:
        try:
            with _db() as c:
                c.execute("INSERT INTO option_hero_snapshots_v71(epoch,symbol,expiry,contract_key,strike,side,premium,score,stage,liquidity,premium_velocity,oi_velocity,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (now, symbol, expiry, winner.get("contract_key"), winner.get("strike"), winner.get("side"), winner.get("premium"), winner.get("score"), winner.get("stage"), winner.get("liquidity_score"), winner.get("premium_velocity_15s"), winner.get("oi_velocity"), json.dumps(winner, default=str)[:20000]))
                c.execute("DELETE FROM option_hero_snapshots_v71 WHERE epoch<?", (now - 45 * 86400,)); c.commit()
        except Exception:
            pass
    return {
        "status": "READY" if candidates else "UNAVAILABLE", "symbol": symbol, "expiry": expiry,
        "underlying": underlying, "winner": winner, "candidates": candidates[:40], "contracts_scored": len(candidates),
        "policy": "Zero-to-Hero is an early expansion detector, not a guarantee. Wide/illiquid contracts are penalized and every score is evidence quality.",
    }


def _norm_candles(candles: List[Any]) -> List[dict]:
    out=[]
    for c in candles or []:
        if isinstance(c, dict):
            o=_f(c.get("open")); h=_f(c.get("high")); l=_f(c.get("low")); cl=_f(c.get("close")); v=_f(c.get("volume")); ts=c.get("ts") or c.get("timestamp")
        elif isinstance(c, (list,tuple)) and len(c)>=5:
            ts=c[0]; o=_f(c[1]); h=_f(c[2]); l=_f(c[3]); cl=_f(c[4]); v=_f(c[5]) if len(c)>5 else None
        else: continue
        if None in (o,h,l,cl): continue
        out.append({"ts":ts,"open":o,"high":h,"low":l,"close":cl,"volume":v})
    return out


def _atr(cs: List[dict], n: int = 14):
    if len(cs)<2: return None
    trs=[]
    prev=cs[0]["close"]
    for c in cs[1:]:
        trs.append(max(c["high"]-c["low"], abs(c["high"]-prev), abs(c["low"]-prev))); prev=c["close"]
    return _mean(trs[-n:])


def _swings(cs: List[dict], window: int = 2):
    highs=[]; lows=[]
    for i in range(window, len(cs)-window):
        seg=cs[i-window:i+window+1]
        if cs[i]["high"] >= max(x["high"] for x in seg): highs.append({"i":i,"price":cs[i]["high"],"ts":cs[i]["ts"]})
        if cs[i]["low"] <= min(x["low"] for x in seg): lows.append({"i":i,"price":cs[i]["low"],"ts":cs[i]["ts"]})
    return highs, lows


def _volume_profile(cs: List[dict], bins: int = 24):
    rows=[c for c in cs if _f(c.get("volume")) is not None and c["volume"]>0]
    if not rows: return {"status":"UNAVAILABLE"}
    lo=min(c["low"] for c in rows); hi=max(c["high"] for c in rows)
    if hi<=lo: return {"status":"UNAVAILABLE"}
    step=(hi-lo)/bins; vols=[0.0]*bins
    for c in rows:
        typ=(c["high"]+c["low"]+c["close"])/3.0
        idx=min(bins-1,max(0,int((typ-lo)/step)))
        vols[idx]+=c["volume"]
    total=sum(vols); poc_idx=max(range(bins),key=lambda i:vols[i]); poc=lo+(poc_idx+.5)*step
    order=sorted(range(bins),key=lambda i:vols[i],reverse=True); taken=[]; acc=0.0
    for i in order:
        taken.append(i); acc+=vols[i]
        if total and acc/total>=.70: break
    vah=lo+(max(taken)+1)*step if taken else None; val=lo+min(taken)*step if taken else None
    return {"status":"READY","poc":round(poc,4),"vah":round(vah,4) if vah is not None else None,"val":round(val,4) if val is not None else None,"bins":bins,"coverage":0.70}


def chart_intelligence(candles: List[Any], symbol: str, interval: int, snapshot: dict, census_row: Optional[dict] = None) -> dict:
    cs=_norm_candles(candles)
    if len(cs)<6:
        return {"status":"UNAVAILABLE","symbol":symbol,"interval":interval,"reason":"Need at least 6 valid candles"}
    last=cs[-1]["close"]; atr=_atr(cs); highs,lows=_swings(cs)
    structure="RANGE / UNCONFIRMED"
    if len(highs)>=2 and len(lows)>=2:
        if highs[-1]["price"]>highs[-2]["price"] and lows[-1]["price"]>lows[-2]["price"]: structure="HH/HL BULLISH"
        elif highs[-1]["price"]<highs[-2]["price"] and lows[-1]["price"]<lows[-2]["price"]: structure="LH/LL BEARISH"
    bos=None; choch=None
    if len(highs)>=2 and last>highs[-1]["price"]: bos={"side":"BULL","level":highs[-1]["price"]}
    if len(lows)>=2 and last<lows[-1]["price"]: bos={"side":"BEAR","level":lows[-1]["price"]}
    if structure.startswith("HH/HL") and len(lows)>=2 and last<lows[-1]["price"]: choch={"side":"BEAR","level":lows[-1]["price"]}
    if structure.startswith("LH/LL") and len(highs)>=2 and last>highs[-1]["price"]: choch={"side":"BULL","level":highs[-1]["price"]}
    volsum=sum((_f(c.get("volume"),0) or 0) for c in cs)
    vwap=None
    if volsum>0:
        vwap=sum(((c["high"]+c["low"]+c["close"])/3.0)*(_f(c.get("volume"),0) or 0) for c in cs)/volsum
    avwap_open=vwap
    profile=_volume_profile(cs)
    first5=cs[:max(1,round(5/max(interval,1)))]; first15=cs[:max(1,round(15/max(interval,1)))]; first30=cs[:max(1,round(30/max(interval,1)))]
    def rr(rows): return {"high":max(x["high"] for x in rows),"low":min(x["low"] for x in rows)} if rows else None
    opening={"5m":rr(first5),"15m":rr(first15),"30m":rr(first30)}
    gap=None
    if census_row:
        pdc=_f(((census_row.get("nearest_levels") or {}).get("all") or {}).get("PDC"))
        if pdc: gap=_pct(cs[0]["open"],pdc)
    levels=[]
    if census_row:
        for name,val in ((census_row.get("nearest_levels") or {}).get("all") or {}).items():
            if val: levels.append({"name":name,"value":val,"distance_pct":round(abs(last-val)/last*100,3)})
    if vwap: levels.append({"name":"SESSION_VWAP","value":vwap,"distance_pct":round(abs(last-vwap)/last*100,3)})
    if profile.get("status")=="READY":
        for k in ("poc","vah","val"):
            val=_f(profile.get(k))
            if val: levels.append({"name":k.upper(),"value":val,"distance_pct":round(abs(last-val)/last*100,3)})
    levels.sort(key=lambda x:x["distance_pct"])
    confluence=[]
    for i,x in enumerate(levels):
        group=[x]
        for y in levels[i+1:]:
            if abs(y["value"]-x["value"])/last*100 <= .18: group.append(y)
        if len(group)>=2:
            confluence.append({"zone":round(_mean([g["value"] for g in group]),4),"members":[g["name"] for g in group],"strength":len(group)})
    seen=set(); confluence=[x for x in confluence if not (tuple(x["members"]) in seen or seen.add(tuple(x["members"])))]
    trend_signed=0
    if structure.startswith("HH/HL"): trend_signed+=32
    elif structure.startswith("LH/LL"): trend_signed-=32
    if vwap: trend_signed += 20 if last>vwap else -20
    if bos: trend_signed += 25 if bos["side"]=="BULL" else -25
    if choch: trend_signed += 18 if choch["side"]=="BULL" else -18
    if census_row: trend_signed += _clamp(_f(census_row.get("signed_score"),0) or 0,-30,30)
    trend_signed=_clamp(trend_signed,-100,100)
    trend_stage="CONFIRMED" if abs(trend_signed)>=70 else "FORMING" if abs(trend_signed)>=45 else "EARLY" if abs(trend_signed)>=25 else "CHOP / WAIT"
    side="CE" if trend_signed>=25 else "PE" if trend_signed<=-25 else "WAIT"
    above=[x for x in levels if x["value"]>last]; below=[x for x in levels if x["value"]<last]
    bullish_above=min(above,key=lambda x:x["value"])["value"] if above else (last+(atr or last*.002))
    bearish_below=max(below,key=lambda x:x["value"])["value"] if below else (last-(atr or last*.002))
    evidence=[]; counter=[]
    if structure!="RANGE / UNCONFIRMED": evidence.append(structure)
    if vwap: evidence.append(f"price {'above' if last>vwap else 'below'} session VWAP")
    if bos: evidence.append(f"BOS {bos['side']} {bos['level']:.2f}")
    if choch: counter.append(f"CHOCH {choch['side']} {choch['level']:.2f}")
    if census_row:
        evidence.extend((census_row.get("evidence") or [])[:4]); counter.extend((census_row.get("counter_evidence") or [])[:4])
    return {
        "status":"READY","version":"71.0","symbol":symbol.upper(),"interval":interval,"last":last,"candles":len(cs),
        "structure":{"state":structure,"bos":bos,"choch":choch,"last_swing_high":highs[-1] if highs else None,"last_swing_low":lows[-1] if lows else None,"atr":round(atr,4) if atr is not None else None},
        "vwap":{"session":round(vwap,4) if vwap is not None else None,"anchored_open":round(avwap_open,4) if avwap_open is not None else None,"truth":"Derived from returned candle typical-price × volume when volume is present."},
        "volume_profile":profile,"opening_range":opening,"gap_pct":round(gap,3) if gap is not None else None,
        "levels":levels[:20],"confluence_zones":confluence[:8],
        "trend":{"side":side,"signed_score":round(trend_signed,1),"score":round(abs(trend_signed),1),"stage":trend_stage,"evidence":evidence[:10],"counter_evidence":counter[:8]},
        "scenario":{"bullish_acceptance_above":round(bullish_above,4),"bearish_acceptance_below":round(bearish_below,4),"inside":"WAIT / RANGE","policy":"Conditional paths only; no fake future candles."},
        "overlays":{"support_resistance":levels[:12],"confluence":confluence[:6],"bos":bos,"choch":choch,"vwap":vwap,"poc":profile.get("poc"),"vah":profile.get("vah"),"val":profile.get("val")},
        "data_truth":{"source":"Upstox historical/intraday candles + current universal census","future_leakage":False,"profit_probability":False},
    }


def missed_move_audit(minutes: int = 390, threshold_pct: float = 1.25) -> dict:
    cutoff=time.time()-max(5,int(minutes))*60
    try:
        with _db() as c:
            rows=[dict(x) for x in c.execute("SELECT epoch,symbol,ltp,stage,side,evidence_score FROM universal_snapshots_v71 WHERE epoch>=? ORDER BY symbol,epoch",(cutoff,))]
            evs=[dict(x) for x in c.execute("SELECT epoch,symbol,stage,side,score,price FROM discovery_events_v71 WHERE epoch>=? ORDER BY symbol,epoch",(cutoff,))]
    except Exception as exc:
        return {"status":"UNAVAILABLE","reason":str(exc),"events":[]}
    by=defaultdict(list); de=defaultdict(list)
    for r in rows: by[r["symbol"]].append(r)
    for e in evs: de[e["symbol"]].append(e)
    found=[]
    for sym,h in by.items():
        prices=[_f(x.get("ltp")) for x in h]; prices=[x for x in prices if x is not None]
        if len(prices)<2: continue
        lo=min(prices); hi=max(prices); move=(hi-lo)/max(lo,1e-9)*100
        if move<threshold_pct: continue
        events=de.get(sym,[])
        early=next((e for e in events if e.get("stage") in ("EARLY MOVER","TRIGGER READY","HERO READY")),None)
        found.append({"symbol":sym,"range_move_pct":round(move,2),"first_price":prices[0],"low":lo,"high":hi,"detected":bool(early),"first_detection":early})
    missed=[x for x in found if not x["detected"]]
    detected=len(found)-len(missed)
    return {"status":"READY","minutes":minutes,"threshold_pct":threshold_pct,"qualifying_moves":len(found),"detected":detected,"missed":len(missed),"detection_recall_pct":round(100*detected/len(found),1) if found else None,"events":sorted(found,key=lambda x:x["range_move_pct"],reverse=True),"missed_events":missed,"policy":"Retrospective qualifying-move recall; it is not win rate and does not prove every move was tradable."}


def build_v71(snapshot: dict, record: bool = True) -> dict:
    v70=build_v70(snapshot, record=False)
    census=universal_census(snapshot, record=record and not snapshot.get("demo"))
    best=(census.get("hero_ready") or census.get("trigger_ready") or census.get("early_movers") or census.get("top") or [None])[0]
    return {
        "version":"71.0","name":"Intelligence Chart + Universal Opportunity Radar OS","generated_at":datetime.now(timezone.utc).isoformat(),
        "read_only":True,"execution_enabled":False,"base_v70":v70,
        "universal_census":{k:v for k,v in census.items() if k!="all_rows"},
        "universal_rows":census.get("all_rows") or [],"best_stock_now":best,
        "coverage_guard":{"expected":census.get("expected_universe"),"observed":census.get("observed"),"coverage_pct":census.get("coverage_pct"),"freshness_pct":census.get("freshness_pct"),"state":census.get("coverage_state"),"zero_miss_badge":bool(census.get("coverage_state")=="COMPLETE" and (census.get("freshness_pct") or 0)>=99.5)},
        "architecture":["ALL F&O UNDERLYINGS OBSERVED BEFORE RANKING","LTPC CENSUS + REST RECONCILIATION","RICH FEED PROMOTION FOR ACTIVE/OPTION CANDIDATES","NO INTERNAL TOP-30/40/50/80 SCAN TRUNCATION","PERSISTENT DISCOVERY EVENTS","ZERO-HINDSIGHT MISSED-MOVE AUDIT","INTELLIGENCE CHART CONDITIONAL SCENARIOS"],
        "truth_policy":["Coverage is measured observation coverage, not guaranteed profit coverage.","No engine claims 100% winning trades.","Missing/stale data remains explicit.","No broker execution or automatic orders."],
    }
