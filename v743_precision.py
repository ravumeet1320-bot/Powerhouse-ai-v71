from __future__ import annotations

"""POWERHOUSE AI V74.3 — Ultra Accuracy precision layer.

Additive layer over V74.2. It is intentionally conservative: discovery may be broad,
but actionable calls require independent evidence, freshness, liquidity, R:R, low
scout disagreement and a meta-label TAKE decision. No broker order execution exists.

The module also provides immutable decision snapshots, calibration statistics,
subsystem heartbeats and optional closed-app Web Push delivery. PostgreSQL is used
when DATABASE_URL + psycopg are available; SQLite is the zero-config fallback.
"""

import hashlib
import json
import math
import os
import sqlite3
import statistics
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # Optional production store.
    import psycopg  # type: ignore
    from psycopg.rows import dict_row  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    psycopg = None
    dict_row = None

try:  # Optional closed-app Web Push.
    from pywebpush import webpush, WebPushException  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    webpush = None
    WebPushException = Exception

VERSION = "74.3"
RELEASE = "74.3-pro-ultra-accuracy"
ENGINE = "CALL ENGINE 2.0 — ULTRA ACCURACY"
ROOT = Path(__file__).parent
SQLITE_PATH = Path(os.getenv("POWERHOUSE_V743_DB_PATH") or (ROOT / ".runtime" / "powerhouse_v743_precision.sqlite3"))
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POWERHOUSE_DATABASE_URL")

# Accuracy gates are configuration, not claims of future hit-rate.
CFG: Dict[str, float] = {
    "min_meta_score": float(os.getenv("V743_MIN_META_SCORE", "78")),
    "min_base_quality": float(os.getenv("V743_MIN_BASE_QUALITY", "74")),
    "min_ready_scouts": float(os.getenv("V743_MIN_READY_SCOUTS", "5")),
    "max_disagreement": float(os.getenv("V743_MAX_DISAGREEMENT", "22")),
    "max_quote_age_sec": float(os.getenv("V743_MAX_QUOTE_AGE_SEC", "7")),
    "min_liquidity": float(os.getenv("V743_MIN_LIQUIDITY", "68")),
    "max_spread_pct": float(os.getenv("V743_MAX_SPREAD_PCT", "1.50")),
    "min_rr_t1": float(os.getenv("V743_MIN_RR_T1", "1.25")),
    "min_premium_response": float(os.getenv("V743_MIN_PREMIUM_RESPONSE", "48")),
    "min_stage_rank": float(os.getenv("V743_MIN_STAGE_RANK", "5")),  # TRIGGER NEAR
    "decision_ttl_sec": float(os.getenv("V743_DECISION_TTL_SEC", "180")),
    "calibration_min_n": float(os.getenv("V743_CALIBRATION_MIN_N", "30")),
}

CONFIG_HASH = hashlib.sha256(json.dumps(CFG, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]

_LOCK = threading.RLock()
_DECISION_CACHE: deque = deque(maxlen=5000)
_HEARTBEATS: Dict[str, dict] = {}
_LAST_DECISION_BY_KEY: Dict[str, dict] = {}
_PUSH_STOP = threading.Event()
_PUSH_THREAD: Optional[threading.Thread] = None
_PUSH_QUEUE: deque = deque(maxlen=2000)

LIFECYCLE = [
    "DISCOVERY", "EARLY CLUE", "BUILDING", "ACCELERATING", "ARMING",
    "TRIGGER NEAR", "TRIGGER READY", "HERO", "ENTRY ACTIVE", "T1", "T2",
    "T3", "RUNNER", "EXIT / RE-ENTRY",
]


def _f(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(v)))


def _json(v: Any) -> str:
    return json.dumps(v, default=str, sort_keys=True, separators=(",", ":"))


def _sha(payload: Any) -> str:
    return hashlib.sha256(_json(payload).encode()).hexdigest()


def heartbeat(name: str, status: str = "GREEN", latency_ms: Optional[float] = None, **details: Any) -> None:
    now = time.time()
    with _LOCK:
        _HEARTBEATS[name] = {
            "subsystem": name,
            "status": status,
            "observed_epoch": now,
            "latency_ms": round(float(latency_ms), 2) if latency_ms is not None else None,
            "details": details,
        }


def heartbeat_snapshot() -> dict:
    now = time.time()
    with _LOCK:
        rows = [dict(v) for v in _HEARTBEATS.values()]
    for row in rows:
        row["age_sec"] = round(now - float(row.get("observed_epoch") or now), 2)
        if row["age_sec"] > 90 and row.get("status") == "GREEN":
            row["status"] = "AMBER"
    critical = {"V74_SCANNER", "PRECISION_STORE", "CALL_ENGINE"}
    state = "GREEN"
    for row in rows:
        if row.get("subsystem") in critical and row.get("status") == "RED":
            state = "RED"
            break
        if row.get("status") in ("AMBER", "RED") and state == "GREEN":
            state = "AMBER"
    return {"version": VERSION, "system_state": state, "subsystems": sorted(rows, key=lambda x: x.get("subsystem") or "")}


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS v743_decisions(
  decision_id TEXT PRIMARY KEY,
  epoch REAL NOT NULL,
  symbol TEXT NOT NULL,
  decision TEXT NOT NULL,
  candidate_action TEXT,
  final_action TEXT,
  stage TEXT,
  meta_score REAL,
  base_quality REAL,
  disagreement REAL,
  ready_scouts INTEGER,
  quote_age_sec REAL,
  liquidity REAL,
  spread_pct REAL,
  rr_t1 REAL,
  config_hash TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL,
  outcome TEXT,
  outcome_epoch REAL,
  mfe_pct REAL,
  mae_pct REAL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_v743_decisions_epoch ON v743_decisions(epoch DESC);
CREATE INDEX IF NOT EXISTS idx_v743_decisions_symbol ON v743_decisions(symbol, epoch DESC);
CREATE INDEX IF NOT EXISTS idx_v743_decisions_decision ON v743_decisions(decision, epoch DESC);

CREATE TABLE IF NOT EXISTS v743_transitions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  epoch REAL NOT NULL,
  symbol TEXT NOT NULL,
  old_state TEXT,
  new_state TEXT NOT NULL,
  reason TEXT,
  decision_id TEXT,
  payload_json TEXT
);

CREATE TABLE IF NOT EXISTS v743_push_subscriptions(
  endpoint TEXT PRIMARY KEY,
  p256dh TEXT,
  auth TEXT,
  created_epoch REAL NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  label TEXT,
  payload_json TEXT NOT NULL
);
"""


class PrecisionStore:
    def __init__(self) -> None:
        self._pg = bool(DATABASE_URL and psycopg is not None)
        self._init_error: Optional[str] = None
        try:
            self.init()
            heartbeat("PRECISION_STORE", "GREEN", backend=self.backend)
        except Exception as exc:  # fail visible, never fabricate persistence
            self._init_error = str(exc)[:240]
            heartbeat("PRECISION_STORE", "RED", error=self._init_error, backend=self.backend)

    @property
    def backend(self) -> str:
        return "postgresql" if self._pg else "sqlite"

    @property
    def durable(self) -> bool:
        return self._pg or bool(os.getenv("POWERHOUSE_V743_DB_PATH"))

    def _sqlite(self) -> sqlite3.Connection:
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(SQLITE_PATH, timeout=8)
        c.row_factory = sqlite3.Row
        return c

    def init(self) -> None:
        if self._pg:
            assert psycopg is not None
            with psycopg.connect(DATABASE_URL, autocommit=True) as c:
                with c.cursor() as cur:
                    cur.execute("""
                    CREATE TABLE IF NOT EXISTS v743_decisions(
                      decision_id TEXT PRIMARY KEY, epoch DOUBLE PRECISION NOT NULL, symbol TEXT NOT NULL,
                      decision TEXT NOT NULL, candidate_action TEXT, final_action TEXT, stage TEXT,
                      meta_score DOUBLE PRECISION, base_quality DOUBLE PRECISION, disagreement DOUBLE PRECISION,
                      ready_scouts INTEGER, quote_age_sec DOUBLE PRECISION, liquidity DOUBLE PRECISION,
                      spread_pct DOUBLE PRECISION, rr_t1 DOUBLE PRECISION, config_hash TEXT NOT NULL,
                      snapshot_hash TEXT NOT NULL, outcome TEXT, outcome_epoch DOUBLE PRECISION,
                      mfe_pct DOUBLE PRECISION, mae_pct DOUBLE PRECISION, payload_json JSONB NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_v743_decisions_epoch ON v743_decisions(epoch DESC);
                    CREATE INDEX IF NOT EXISTS idx_v743_decisions_symbol ON v743_decisions(symbol, epoch DESC);
                    CREATE TABLE IF NOT EXISTS v743_transitions(
                      id BIGSERIAL PRIMARY KEY, epoch DOUBLE PRECISION NOT NULL, symbol TEXT NOT NULL,
                      old_state TEXT, new_state TEXT NOT NULL, reason TEXT, decision_id TEXT, payload_json JSONB
                    );
                    CREATE TABLE IF NOT EXISTS v743_push_subscriptions(
                      endpoint TEXT PRIMARY KEY, p256dh TEXT, auth TEXT, created_epoch DOUBLE PRECISION NOT NULL,
                      enabled INTEGER NOT NULL DEFAULT 1, label TEXT, payload_json JSONB NOT NULL
                    );
                    """)
        else:
            with self._sqlite() as c:
                c.executescript(_SQLITE_SCHEMA)

    def save_decision(self, item: dict) -> None:
        payload = _json(item)
        values = (
            item.get("decision_id"), item.get("epoch"), item.get("symbol"), item.get("decision"),
            item.get("candidate_action"), item.get("final_action"), item.get("stage"),
            _f(item.get("meta_score")), _f(item.get("base_quality")), _f(item.get("disagreement")),
            int(item.get("ready_scouts") or 0), _f(item.get("quote_age_sec")), _f(item.get("liquidity")),
            _f(item.get("spread_pct")), _f(item.get("rr_t1")), item.get("config_hash"),
            item.get("snapshot_hash"), item.get("outcome"), _f(item.get("outcome_epoch")),
            _f(item.get("mfe_pct")), _f(item.get("mae_pct")), payload,
        )
        t0 = time.perf_counter()
        if self._pg:
            assert psycopg is not None
            with psycopg.connect(DATABASE_URL, autocommit=True) as c:
                with c.cursor() as cur:
                    cur.execute("""
                    INSERT INTO v743_decisions(decision_id,epoch,symbol,decision,candidate_action,final_action,stage,
                      meta_score,base_quality,disagreement,ready_scouts,quote_age_sec,liquidity,spread_pct,rr_t1,
                      config_hash,snapshot_hash,outcome,outcome_epoch,mfe_pct,mae_pct,payload_json)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT(decision_id) DO UPDATE SET final_action=EXCLUDED.final_action,outcome=EXCLUDED.outcome,
                      outcome_epoch=EXCLUDED.outcome_epoch,mfe_pct=EXCLUDED.mfe_pct,mae_pct=EXCLUDED.mae_pct,
                      payload_json=EXCLUDED.payload_json
                    """, values)
        else:
            with self._sqlite() as c:
                c.execute("""
                    INSERT INTO v743_decisions(decision_id,epoch,symbol,decision,candidate_action,final_action,stage,
                      meta_score,base_quality,disagreement,ready_scouts,quote_age_sec,liquidity,spread_pct,rr_t1,
                      config_hash,snapshot_hash,outcome,outcome_epoch,mfe_pct,mae_pct,payload_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(decision_id) DO UPDATE SET final_action=excluded.final_action,outcome=excluded.outcome,
                      outcome_epoch=excluded.outcome_epoch,mfe_pct=excluded.mfe_pct,mae_pct=excluded.mae_pct,
                      payload_json=excluded.payload_json
                """, values)
        heartbeat("PRECISION_STORE", "GREEN", (time.perf_counter() - t0) * 1000.0, backend=self.backend)

    def transition(self, symbol: str, old_state: Optional[str], new_state: str, reason: str, decision_id: Optional[str], payload: Optional[dict] = None) -> None:
        vals = (time.time(), symbol, old_state, new_state, reason, decision_id, _json(payload or {}))
        try:
            if self._pg:
                assert psycopg is not None
                with psycopg.connect(DATABASE_URL, autocommit=True) as c:
                    with c.cursor() as cur:
                        cur.execute("INSERT INTO v743_transitions(epoch,symbol,old_state,new_state,reason,decision_id,payload_json) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)", vals)
            else:
                with self._sqlite() as c:
                    c.execute("INSERT INTO v743_transitions(epoch,symbol,old_state,new_state,reason,decision_id,payload_json) VALUES(?,?,?,?,?,?,?)", vals)
        except Exception as exc:
            heartbeat("PRECISION_STORE", "AMBER", error=str(exc)[:180], backend=self.backend)

    def recent(self, limit: int = 200) -> List[dict]:
        limit = max(1, min(int(limit), 2000))
        try:
            if self._pg:
                assert psycopg is not None
                with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
                    with c.cursor() as cur:
                        cur.execute("SELECT * FROM v743_decisions ORDER BY epoch DESC LIMIT %s", (limit,))
                        rows = list(cur.fetchall())
                        for r in rows:
                            if isinstance(r.get("payload_json"), dict):
                                r["payload"] = r.pop("payload_json")
                            else:
                                try: r["payload"] = json.loads(r.pop("payload_json") or "{}")
                                except Exception: r["payload"] = {}
                        return rows
            with self._sqlite() as c:
                rows = [dict(r) for r in c.execute("SELECT * FROM v743_decisions ORDER BY epoch DESC LIMIT ?", (limit,)).fetchall()]
            for r in rows:
                try: r["payload"] = json.loads(r.pop("payload_json") or "{}")
                except Exception: r["payload"] = {}
            return rows
        except Exception:
            return []

    def subscribe(self, sub: dict, label: Optional[str] = None) -> None:
        endpoint = str(sub.get("endpoint") or "").strip()
        keys = sub.get("keys") or {}
        if not endpoint:
            raise ValueError("push endpoint missing")
        vals = (endpoint, keys.get("p256dh"), keys.get("auth"), time.time(), 1, label, _json(sub))
        if self._pg:
            assert psycopg is not None
            with psycopg.connect(DATABASE_URL, autocommit=True) as c:
                with c.cursor() as cur:
                    cur.execute("""
                    INSERT INTO v743_push_subscriptions(endpoint,p256dh,auth,created_epoch,enabled,label,payload_json)
                    VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)
                    ON CONFLICT(endpoint) DO UPDATE SET p256dh=EXCLUDED.p256dh,auth=EXCLUDED.auth,enabled=1,label=EXCLUDED.label,payload_json=EXCLUDED.payload_json
                    """, vals)
        else:
            with self._sqlite() as c:
                c.execute("""
                    INSERT INTO v743_push_subscriptions(endpoint,p256dh,auth,created_epoch,enabled,label,payload_json)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh,auth=excluded.auth,enabled=1,label=excluded.label,payload_json=excluded.payload_json
                """, vals)

    def unsubscribe(self, endpoint: str) -> None:
        if self._pg:
            assert psycopg is not None
            with psycopg.connect(DATABASE_URL, autocommit=True) as c:
                with c.cursor() as cur:
                    cur.execute("UPDATE v743_push_subscriptions SET enabled=0 WHERE endpoint=%s", (endpoint,))
        else:
            with self._sqlite() as c:
                c.execute("UPDATE v743_push_subscriptions SET enabled=0 WHERE endpoint=?", (endpoint,))

    def subscriptions(self) -> List[dict]:
        try:
            if self._pg:
                assert psycopg is not None
                with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
                    with c.cursor() as cur:
                        cur.execute("SELECT payload_json FROM v743_push_subscriptions WHERE enabled=1")
                        out=[]
                        for r in cur.fetchall():
                            p=r.get("payload_json")
                            out.append(p if isinstance(p,dict) else json.loads(p or "{}"))
                        return out
            with self._sqlite() as c:
                rows=c.execute("SELECT payload_json FROM v743_push_subscriptions WHERE enabled=1").fetchall()
                return [json.loads(r["payload_json"] or "{}") for r in rows]
        except Exception:
            return []


    def update_outcome(self, decision_id: str, outcome: str, mfe_pct: Optional[float] = None, mae_pct: Optional[float] = None) -> None:
        if not decision_id or not outcome:
            return
        now=time.time()
        try:
            if self._pg:
                assert psycopg is not None
                with psycopg.connect(DATABASE_URL, autocommit=True) as c:
                    with c.cursor() as cur:
                        cur.execute("UPDATE v743_decisions SET outcome=%s,outcome_epoch=%s,mfe_pct=%s,mae_pct=%s WHERE decision_id=%s", (outcome,now,mfe_pct,mae_pct,decision_id))
            else:
                with self._sqlite() as c:
                    c.execute("UPDATE v743_decisions SET outcome=?,outcome_epoch=?,mfe_pct=?,mae_pct=? WHERE decision_id=?", (outcome,now,mfe_pct,mae_pct,decision_id))
        except Exception as exc:
            heartbeat("PRECISION_STORE", "AMBER", error=str(exc)[:180], backend=self.backend)

    def status(self) -> dict:
        return {
            "backend": self.backend,
            "durable": self.durable,
            "path": None if self._pg else str(SQLITE_PATH),
            "configured_database_url": bool(DATABASE_URL),
            "init_error": self._init_error,
        }


STORE = PrecisionStore()


def _scout_pack(underlying: dict) -> dict:
    return underlying.get("scout_pack") or {}


def _scout_scores(underlying: dict) -> Dict[str, float]:
    pack = _scout_pack(underlying)
    scouts = pack.get("scouts") or {}
    out: Dict[str, float] = {}
    for name, info in scouts.items():
        if isinstance(info, dict) and str(info.get("status") or "").upper() == "READY":
            score = _f(info.get("score"))
            if score is not None:
                out[name] = score
    return out


def _weighted_disagreement(scores: Dict[str, float]) -> Optional[float]:
    vals = list(scores.values())
    if len(vals) < 2:
        return None
    return statistics.pstdev(vals)


def _stage_rank(stage: str) -> int:
    aliases = {"WATCH":"EARLY CLUE","SCANNING":"DISCOVERY","HERO READY":"HERO","HERO ACTIVE":"ENTRY ACTIVE"}
    s = aliases.get(str(stage or "").upper(), str(stage or "").upper())
    return {x:i for i,x in enumerate(LIFECYCLE)}.get(s, 0)


def _quote_age(underlying: dict) -> Tuple[Optional[float], str]:
    for k in ("quote_age_sec", "age_sec", "feed_age_sec"):
        x = _f(underlying.get(k))
        if x is not None:
            return x, k
    # Index REST rows are retrieved immediately by the deep inspector. This is retrieval
    # freshness, not exchange timestamp freshness, so it receives a penalty below.
    if underlying.get("index_underlying") and str(underlying.get("source") or "").lower().find("rest") >= 0:
        return 0.0, "rest_retrieval_time"
    return None, "unknown"


def _premium_response(underlying: dict, strike_pack: dict) -> Optional[float]:
    try:
        opt = (((underlying.get("scout_pack") or {}).get("scouts") or {}).get("options") or {})
        for v in (opt.get("premium_response"), ((strike_pack.get("winner") or {}).get("scores") or {}).get("premium_response"), (strike_pack.get("winner") or {}).get("premium_response")):
            x=_f(v)
            if x is not None:
                return x
    except Exception:
        pass
    return None


def _directional_alignment(underlying: dict) -> Tuple[Optional[float], dict]:
    """Evidence independence proxy: strong families vs weak/contradictory families.

    This is not a win probability. It prevents a high average created by a few extreme
    scouts while other independent evidence families are weak.
    """
    scores = _scout_scores(underlying)
    if not scores:
        return None, {"strong": [], "weak": [], "neutral": []}
    strong=[k for k,v in scores.items() if v>=65]
    weak=[k for k,v in scores.items() if v<45]
    neutral=[k for k,v in scores.items() if 45<=v<65]
    score = 100.0 * (len(strong) + 0.45*len(neutral)) / max(1,len(scores))
    score -= 12.0*len(weak)
    return _clamp(score), {"strong":strong,"weak":weak,"neutral":neutral}


def ultra_accuracy_gate(underlying: dict, base_plan: dict, strike_pack: dict, chart: Optional[dict] = None) -> dict:
    scores = _scout_scores(underlying)
    ready_count = len(scores) or int((_scout_pack(underlying).get("ready_count") or 0))
    disagreement = _weighted_disagreement(scores)
    agreement, agreement_detail = _directional_alignment(underlying)
    age, age_basis = _quote_age(underlying)
    liquidity = _f(base_plan.get("liquidity_score"))
    spread = _f(base_plan.get("spread_pct"))
    rr1 = _f((base_plan.get("risk_reward") or {}).get("t1"))
    base_quality = _f(base_plan.get("call_quality"), 0.0) or 0.0
    premium_response = _premium_response(underlying, strike_pack)
    stage = str(base_plan.get("stage") or underlying.get("stage") or "DISCOVERY").upper()
    stage_rank = _stage_rank(stage)
    candidate_action = str(base_plan.get("action") or "WAIT").upper()
    blockers = list(dict.fromkeys(str(x) for x in (base_plan.get("blocked_by") or []) if x))
    insuff: List[str] = []

    required_scouts = 4 if underlying.get("index_underlying") else int(CFG["min_ready_scouts"])
    if ready_count < required_scouts:
        insuff.append(f"SCOUT COVERAGE {ready_count}/7 < {required_scouts}")
    if age is None:
        insuff.append("FRESHNESS UNKNOWN")
    elif age > CFG["max_quote_age_sec"]:
        blockers.append(f"STALE QUOTE {age:.1f}s")
    if liquidity is None:
        insuff.append("LIQUIDITY UNKNOWN")
    elif liquidity < CFG["min_liquidity"]:
        blockers.append(f"LIQUIDITY {liquidity:.1f} < {CFG['min_liquidity']:.0f}")
    if spread is None:
        insuff.append("SPREAD UNKNOWN")
    elif spread > CFG["max_spread_pct"]:
        blockers.append(f"SPREAD {spread:.2f}%")
    if rr1 is None:
        insuff.append("R:R UNKNOWN")
    elif rr1 < CFG["min_rr_t1"]:
        blockers.append(f"R:R T1 {rr1:.2f}")
    if disagreement is None:
        insuff.append("DISAGREEMENT UNKNOWN")
    elif disagreement > CFG["max_disagreement"]:
        blockers.append(f"SCOUT DISAGREEMENT {disagreement:.1f}")
    if stage_rank < int(CFG["min_stage_rank"]):
        blockers.append(f"STAGE {stage} NOT READY")
    if base_quality < CFG["min_base_quality"]:
        blockers.append(f"BASE QUALITY {base_quality:.1f}")
    if underlying.get("late_entry") or str(underlying.get("move_quality") or "").upper() in {"LATE","CROWDED","EXHAUSTED"}:
        blockers.append("LATE / EXTENDED")
    if underlying.get("false_breakout"):
        blockers.append("FALSE BREAKOUT EVIDENCE")
    if underlying.get("mtf_conflict") or bool((chart or {}).get("mtf_conflict")):
        blockers.append("MTF CONFLICT")
    if premium_response is not None and premium_response < CFG["min_premium_response"]:
        blockers.append(f"PREMIUM RESPONSE {premium_response:.1f}")
    if underlying.get("premium_failure"):
        blockers.append("PREMIUM DECOUPLING")

    evidence_mean = statistics.fmean(scores.values()) if scores else 0.0
    freshness_score = 45.0 if age is None else _clamp(100 - max(0.0, age - 1.0) * 13.0)
    # REST retrieval time is useful but less trustworthy than an exchange/provider tick timestamp.
    if age_basis == "rest_retrieval_time":
        freshness_score = min(freshness_score, 82.0)
    liquidity_score = 45.0 if liquidity is None else _clamp(liquidity)
    spread_score = 42.0 if spread is None else _clamp(100 - max(0.0, spread - 0.20) * 42.0)
    rr_score = 42.0 if rr1 is None else _clamp(rr1 / 2.0 * 100.0)
    agreement_score = 42.0 if agreement is None else agreement
    disagreement_penalty = 18.0 if disagreement is None else min(34.0, max(0.0, disagreement - 8.0) * 1.7)
    insuff_penalty = min(28.0, 5.0 * len(insuff))
    blocker_penalty = min(45.0, 7.0 * len(blockers))

    meta_score = (
        base_quality * .20 + evidence_mean * .20 + agreement_score * .15 +
        liquidity_score * .12 + spread_score * .10 + freshness_score * .10 +
        rr_score * .08 + (premium_response if premium_response is not None else 50.0) * .05
        - disagreement_penalty - insuff_penalty - blocker_penalty
    )
    meta_score = round(_clamp(meta_score), 1)

    if candidate_action in ("BUY CE", "BUY PE") and not blockers and not insuff and meta_score >= CFG["min_meta_score"]:
        decision = "TAKE"
    elif insuff and not blockers:
        decision = "INSUFFICIENT_DATA"
    else:
        decision = "SKIP"

    # Empirical probability stays hidden until enough resolved TAKE calls exist.
    calibration = calibration_summary()
    return {
        "version": VERSION,
        "engine": ENGINE,
        "decision": decision,
        "meta_score": meta_score,
        "base_quality": round(base_quality, 1),
        "ready_scouts": ready_count,
        "scout_scores": scores,
        "disagreement": round(disagreement, 2) if disagreement is not None else None,
        "agreement_score": round(agreement, 1) if agreement is not None else None,
        "agreement_detail": agreement_detail,
        "quote_age_sec": age,
        "freshness_basis": age_basis,
        "liquidity": liquidity,
        "spread_pct": spread,
        "rr_t1": rr1,
        "premium_response": premium_response,
        "stage": stage,
        "stage_rank": stage_rank,
        "hard_blockers": list(dict.fromkeys(blockers)),
        "insufficient": list(dict.fromkeys(insuff)),
        "config_hash": CONFIG_HASH,
        "calibration": calibration,
        "policy": "Meta-label TAKE/SKIP/INSUFFICIENT_DATA. Precision is measured from resolved live calls; meta_score is not profit probability.",
    }


def _decision_key(symbol: str, plan: dict) -> str:
    return f"{symbol}|{plan.get('underlying_side')}|{plan.get('strike')}|{plan.get('expiry')}"


def apply_precision_gate(underlying: dict, base_plan: dict, strike_pack: dict, chart: Optional[dict] = None, now_epoch: Optional[float] = None) -> dict:
    now = float(now_epoch or time.time())
    plan = dict(base_plan)
    symbol = str(plan.get("symbol") or underlying.get("symbol") or "").upper()
    candidate_action = str(plan.get("action") or "WAIT")
    gate = ultra_accuracy_gate(underlying, plan, strike_pack, chart)
    decision = gate["decision"]

    final_action = candidate_action if decision == "TAKE" else "WAIT"
    final_status = "READY" if decision == "TAKE" else "ULTRA WAIT" if candidate_action in ("BUY CE","BUY PE") else str(plan.get("status") or "WAIT")
    valid_for = min(float(plan.get("valid_for_sec") or CFG["decision_ttl_sec"]), CFG["decision_ttl_sec"])

    plan.update({
        "version": VERSION,
        "release": RELEASE,
        "engine": ENGINE,
        "candidate_action": candidate_action,
        "status": final_status,
        "action": final_action,
        "valid_until_epoch": min(float(plan.get("valid_until_epoch") or now + valid_for), now + valid_for),
        "valid_for_sec": int(valid_for),
        "ultra_accuracy": gate,
        "meta_label": decision,
        "meta_score": gate["meta_score"],
        "config_hash": CONFIG_HASH,
        "quality_is_probability": False,
        "read_only": True,
        "execution_enabled": False,
        "policy": "Discovery may be aggressive; actionable calls are conservative. TAKE requires Ultra Accuracy meta-label + hard gates. No broker orders.",
    })
    if decision != "TAKE":
        extra = gate.get("hard_blockers") or gate.get("insufficient") or ["Ultra Accuracy gate did not pass"]
        plan["blocked_by"] = list(dict.fromkeys(list(plan.get("blocked_by") or []) + list(extra)))
        plan["why_now"] = [f"Ultra Accuracy: {decision}"] + [f"Blocked: {x}" for x in extra[:5]]

    snapshot = {
        "version": VERSION,
        "epoch": now,
        "iso": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "symbol": symbol,
        "underlying": underlying,
        "strike_pack": strike_pack,
        "chart": chart,
        "base_plan": base_plan,
        "final_plan": {k:v for k,v in plan.items() if k not in ("snapshot",)},
        "config": CFG,
        "config_hash": CONFIG_HASH,
    }
    snapshot_hash = _sha(snapshot)
    decision_id = f"V743-{symbol}-{uuid.uuid4().hex[:12]}"
    plan["decision_id"] = decision_id
    plan["snapshot_hash"] = snapshot_hash

    item = {
        "decision_id": decision_id, "epoch": now, "symbol": symbol, "decision": decision,
        "candidate_action": candidate_action, "final_action": final_action, "stage": plan.get("stage"),
        "meta_score": gate.get("meta_score"), "base_quality": gate.get("base_quality"),
        "disagreement": gate.get("disagreement"), "ready_scouts": gate.get("ready_scouts"),
        "quote_age_sec": gate.get("quote_age_sec"), "liquidity": gate.get("liquidity"),
        "spread_pct": gate.get("spread_pct"), "rr_t1": gate.get("rr_t1"),
        "config_hash": CONFIG_HASH, "snapshot_hash": snapshot_hash, "payload": snapshot,
    }
    try:
        STORE.save_decision(item)
    except Exception as exc:
        # Fail closed for actionable calls when immutable persistence fails.
        heartbeat("PRECISION_STORE", "RED", error=str(exc)[:180])
        if decision == "TAKE":
            plan["action"] = "WAIT"
            plan["status"] = "SAFE MODE"
            plan["meta_label"] = "SKIP"
            plan["blocked_by"] = list(dict.fromkeys(list(plan.get("blocked_by") or []) + ["SNAPSHOT PERSISTENCE FAILED"]))
            gate["decision"] = "SKIP"
            gate.setdefault("hard_blockers", []).append("SNAPSHOT PERSISTENCE FAILED")
            decision = "SKIP"

    with _LOCK:
        _DECISION_CACHE.append(item)
        key = _decision_key(symbol, plan)
        old = _LAST_DECISION_BY_KEY.get(key)
        _LAST_DECISION_BY_KEY[key] = {"decision": decision, "epoch": now, "decision_id": decision_id, "meta_score": gate.get("meta_score")}
    if old and old.get("decision") == "TAKE" and decision != "TAKE":
        reason = ", ".join((gate.get("hard_blockers") or gate.get("insufficient") or ["evidence deteriorated"])[:4])
        plan["retraction"] = {"state":"THESIS INVALIDATED","reason":reason,"previous_decision_id":old.get("decision_id")}
        STORE.transition(symbol, "TAKE", "RETRACTED", reason, old.get("decision_id"), {"new_decision_id":decision_id})
        queue_push({"title": f"{symbol} CALL RETRACTED", "body": reason, "priority":"P0", "url":"/"})
    elif decision == "TAKE" and (not old or old.get("decision") != "TAKE"):
        STORE.transition(symbol, old.get("decision") if old else None, "TAKE", "Ultra Accuracy gates passed", decision_id, {"meta_score":gate.get("meta_score")})
        ez=plan.get("entry_zone") or {}; tg=plan.get("targets") or {}
        queue_push({"title": f"{symbol} {plan.get('action')} READY", "body": f"Entry {ez.get('low')}-{ez.get('high')} | SL {plan.get('sl')} | T1 {tg.get('t1')}", "priority":"P0", "url":"/"})

    heartbeat("CALL_ENGINE", "GREEN", decision=decision, symbol=symbol, meta_score=gate.get("meta_score"))
    return plan


def _resolve_rows(rows: List[dict]) -> List[dict]:
    return [r for r in rows if str(r.get("decision") or "") == "TAKE" and r.get("outcome")]


def calibration_summary(limit: int = 1000) -> dict:
    rows = STORE.recent(limit)
    resolved = _resolve_rows(rows)
    wins = [r for r in resolved if str(r.get("outcome") or "").upper() in {"T1 HIT","T2 HIT","T3 HIT","TARGET_FIRST"}]
    losses = [r for r in resolved if str(r.get("outcome") or "").upper() in {"SL HIT","STOP_FIRST"}]
    n = len(wins) + len(losses)
    # Jeffreys prior Beta(0.5,0.5); mean only. Credible interval intentionally omitted
    # without scipy to avoid a fake approximation in production UI.
    posterior_mean = (len(wins)+0.5)/(n+1.0) if n else None
    enough = n >= int(CFG["calibration_min_n"])
    return {
        "resolved_take_calls": n,
        "wins": len(wins), "losses": len(losses),
        "posterior_mean": round(posterior_mean, 4) if enough and posterior_mean is not None else None,
        "status": "CALIBRATED_SAMPLE" if enough else "INSUFFICIENT_DATA",
        "minimum_sample": int(CFG["calibration_min_n"]),
        "policy": "Observed live resolved TAKE calls only; historical reliability is not a guarantee of future outcomes.",
    }


def accuracy_report(limit: int = 1000) -> dict:
    rows=STORE.recent(limit)
    take=[r for r in rows if str(r.get("decision") or "") == "TAKE"]
    skip=[r for r in rows if str(r.get("decision") or "") in {"SKIP","INSUFFICIENT_DATA"}]
    resolved=_resolve_rows(rows)
    target=[r for r in resolved if str(r.get("outcome") or "").upper() in {"T1 HIT","T2 HIT","T3 HIT","TARGET_FIRST"}]
    sl=[r for r in resolved if str(r.get("outcome") or "").upper() in {"SL HIT","STOP_FIRST"}]
    late=[r for r in rows if "LATE" in " ".join((r.get("payload") or {}).get("final_plan",{}).get("blocked_by") or [])]
    def med(key: str) -> Optional[float]:
        vals=[_f(r.get(key)) for r in resolved if _f(r.get(key)) is not None]
        return round(statistics.median(vals),3) if vals else None
    n=len(target)+len(sl)
    return {
        "version":VERSION,
        "decisions":len(rows),"take":len(take),"abstained":len(skip),"resolved_take":n,
        "execution_adjusted_precision_proxy_pct":round(100*len(target)/n,1) if n else None,
        "target_first":len(target),"stop_first":len(sl),"late_or_extended_rejections":len(late),
        "median_mfe_pct":med("mfe_pct"),"median_mae_pct":med("mae_pct"),
        "calibration":calibration_summary(limit),
        "config_hash":CONFIG_HASH,
        "truth":"Until enough live resolved calls exist, the software must show INSUFFICIENT DATA instead of a claimed win probability.",
    }


def recent_decisions(limit: int = 200) -> dict:
    rows=STORE.recent(limit)
    return {"version":VERSION,"rows":rows,"count":len(rows),"storage":STORE.status(),"read_only":True}


def observe_scanner(meta: dict) -> None:
    age=_f(meta.get("last_scan_age_sec"))
    fresh=bool(meta.get("fresh"))
    running=bool(meta.get("running"))
    status="GREEN" if running and fresh else "AMBER" if running else "RED"
    heartbeat("V74_SCANNER", status, meta.get("last_scan_ms"), last_scan_age_sec=age, scan_count=meta.get("scan_count"), hot_lane_running=meta.get("hot_lane_running"), hot_age_sec=meta.get("last_hot_age_sec"))
    if meta.get("hot_lane_running"):
        heartbeat("HOT_LANE", "GREEN", last_hot_age_sec=meta.get("last_hot_age_sec"), hot_symbols=meta.get("hot_symbols"))
    else:
        heartbeat("HOT_LANE", "AMBER", last_hot_age_sec=meta.get("last_hot_age_sec"))


def safe_mode() -> dict:
    hb=heartbeat_snapshot()
    red=[x for x in hb["subsystems"] if x.get("status")=="RED"]
    return {"enabled":bool(red),"reasons":[x.get("subsystem") for x in red],"system_state":hb.get("system_state")}


def push_config() -> dict:
    pub=os.getenv("VAPID_PUBLIC_KEY") or ""
    priv=os.getenv("VAPID_PRIVATE_KEY") or ""
    subject=os.getenv("VAPID_SUBJECT") or "mailto:admin@example.invalid"
    return {"configured":bool(pub and priv),"public_key":pub or None,"subject":subject,"library_available":webpush is not None}


def queue_push(payload: dict) -> None:
    with _LOCK:
        _PUSH_QUEUE.append({**payload,"epoch":time.time()})


def _send_push(sub: dict, payload: dict) -> Tuple[bool, Optional[str]]:
    cfg=push_config()
    if not cfg["configured"] or webpush is None:
        return False,"Web Push not configured"
    try:
        webpush(
            subscription_info=sub,
            data=_json(payload),
            vapid_private_key=os.getenv("VAPID_PRIVATE_KEY"),
            vapid_claims={"sub":cfg["subject"]},
            ttl=90,
        )
        return True,None
    except Exception as exc:
        return False,str(exc)[:200]


def _push_loop() -> None:
    heartbeat("PUSH_WORKER", "GREEN", configured=push_config().get("configured"))
    while not _PUSH_STOP.is_set():
        item=None
        with _LOCK:
            if _PUSH_QUEUE:
                item=_PUSH_QUEUE.popleft()
        if item is None:
            _PUSH_STOP.wait(0.8)
            continue
        subs=STORE.subscriptions()
        sent=failed=0; last_error=None
        for sub in subs:
            ok,err=_send_push(sub,item)
            if ok: sent+=1
            else: failed+=1; last_error=err
        heartbeat("PUSH_WORKER", "GREEN" if failed==0 else "AMBER", configured=push_config().get("configured"), subscriptions=len(subs), sent=sent, failed=failed, last_error=last_error)


def start_push_worker() -> None:
    global _PUSH_THREAD
    if _PUSH_THREAD and _PUSH_THREAD.is_alive():
        return
    _PUSH_STOP.clear()
    _PUSH_THREAD=threading.Thread(target=_push_loop,name="v743-push-worker",daemon=True)
    _PUSH_THREAD.start()


def stop_push_worker() -> None:
    _PUSH_STOP.set()


def register_push_subscription(subscription: dict, label: Optional[str] = None) -> dict:
    STORE.subscribe(subscription,label)
    return {"ok":True,"version":VERSION,"configured":push_config().get("configured")}


def revoke_push_subscription(endpoint: str) -> dict:
    STORE.unsubscribe(endpoint)
    return {"ok":True,"version":VERSION}


def pro_status() -> dict:
    return {
        "version":VERSION,"release":RELEASE,"engine":ENGINE,"config_hash":CONFIG_HASH,
        "storage":STORE.status(),"safe_mode":safe_mode(),"push":push_config(),
        "calibration":calibration_summary(),"heartbeats":heartbeat_snapshot(),
        "orders_enabled":False,"execution_enabled":False,"read_only":True,
        "mission":"MAXIMIZE EXECUTION-ADJUSTED PRECISION SUBJECT TO MEASURED MOVE COVERAGE",
    }
