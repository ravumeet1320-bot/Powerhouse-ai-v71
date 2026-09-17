from __future__ import annotations

"""Persistent market-memory layer for POWERHOUSE AI V74.3.

This module stores *observed evidence and decision snapshots* only. It does not
fabricate market facts and it does not auto-tune production thresholds. PostgreSQL
is preferred when DATABASE_URL is configured; SQLite is a zero-config fallback.
"""

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import psycopg  # type: ignore
    from psycopg.rows import dict_row  # type: ignore
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None

ROOT = Path(__file__).parent
SQLITE_PATH = Path(os.getenv("POWERHOUSE_V743_MEMORY_PATH") or (ROOT / ".runtime" / "powerhouse_v743_memory.sqlite3"))
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("POWERHOUSE_DATABASE_URL")
_LOCK = threading.RLock()

MEMORY_TYPES = (
    "LEVEL", "SYMBOL_DNA", "INDEX_DNA", "EXPIRY", "OI_WALL", "SMART_MONEY",
    "SECTOR_ROTATION", "SETUP", "FAILURE", "MISSED_MOVE", "CALL_SNAPSHOT",
    "REGIME", "TIME_OF_DAY", "STRIKE", "PATTERN", "CALIBRATION", "VERSION",
    "DATA_QUALITY", "REENTRY", "TRAP", "SCENARIO", "SIGNAL_DECAY",
    "CONFLICT", "OPPORTUNITY", "REPLAY", "SYSTEM",
)

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS v743_memory_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  epoch REAL NOT NULL,
  memory_type TEXT NOT NULL,
  symbol TEXT,
  scope_key TEXT,
  event_key TEXT,
  payload_json TEXT NOT NULL,
  source TEXT,
  config_hash TEXT,
  immutable INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_v743_memory_epoch ON v743_memory_events(epoch DESC);
CREATE INDEX IF NOT EXISTS idx_v743_memory_symbol ON v743_memory_events(symbol, epoch DESC);
CREATE INDEX IF NOT EXISTS idx_v743_memory_type ON v743_memory_events(memory_type, epoch DESC);
CREATE INDEX IF NOT EXISTS idx_v743_memory_scope ON v743_memory_events(scope_key, epoch DESC);
"""

_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS v743_memory_events(
  id BIGSERIAL PRIMARY KEY,
  epoch DOUBLE PRECISION NOT NULL,
  memory_type TEXT NOT NULL,
  symbol TEXT,
  scope_key TEXT,
  event_key TEXT,
  payload_json JSONB NOT NULL,
  source TEXT,
  config_hash TEXT,
  immutable BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_v743_memory_epoch ON v743_memory_events(epoch DESC);
CREATE INDEX IF NOT EXISTS idx_v743_memory_symbol ON v743_memory_events(symbol, epoch DESC);
CREATE INDEX IF NOT EXISTS idx_v743_memory_type ON v743_memory_events(memory_type, epoch DESC);
CREATE INDEX IF NOT EXISTS idx_v743_memory_scope ON v743_memory_events(scope_key, epoch DESC);
"""


def _clean_text(value: Any, limit: int = 120) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


class MarketMemory:
    def __init__(self) -> None:
        self.pg = bool(DATABASE_URL and psycopg is not None)
        self.backend = "postgresql" if self.pg else "sqlite"
        self.last_error: Optional[str] = None
        self.last_write_epoch = 0.0
        self._init_schema()

    def _sqlite(self):
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(SQLITE_PATH, timeout=8)
        c.row_factory = sqlite3.Row
        return c

    def _init_schema(self) -> None:
        try:
            if self.pg:
                assert psycopg is not None
                with psycopg.connect(DATABASE_URL, autocommit=True) as c:
                    c.execute(_PG_SCHEMA)
            else:
                with self._sqlite() as c:
                    c.executescript(_SQLITE_SCHEMA)
            self.last_error = None
        except Exception as exc:
            self.last_error = str(exc)[:240]

    def record(
        self,
        memory_type: str,
        payload: Dict[str, Any],
        *,
        symbol: Optional[str] = None,
        scope_key: Optional[str] = None,
        event_key: Optional[str] = None,
        source: Optional[str] = None,
        config_hash: Optional[str] = None,
        epoch: Optional[float] = None,
    ) -> Dict[str, Any]:
        mt = str(memory_type or "SYSTEM").upper().strip()
        if mt not in MEMORY_TYPES:
            mt = "SYSTEM"
        ts = float(epoch or time.time())
        sym = _clean_text(symbol, 48)
        scope = _clean_text(scope_key, 120)
        event = _clean_text(event_key, 160)
        src = _clean_text(source, 120)
        cfg = _clean_text(config_hash, 96)
        body = payload if isinstance(payload, dict) else {"value": payload}
        try:
            with _LOCK:
                if self.pg:
                    assert psycopg is not None
                    with psycopg.connect(DATABASE_URL, autocommit=True) as c:
                        c.execute(
                            "INSERT INTO v743_memory_events(epoch,memory_type,symbol,scope_key,event_key,payload_json,source,config_hash,immutable) VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s,TRUE)",
                            (ts, mt, sym, scope, event, json.dumps(body, separators=(",", ":"), default=str), src, cfg),
                        )
                else:
                    with self._sqlite() as c:
                        c.execute(
                            "INSERT INTO v743_memory_events(epoch,memory_type,symbol,scope_key,event_key,payload_json,source,config_hash,immutable) VALUES(?,?,?,?,?,?,?,?,1)",
                            (ts, mt, sym, scope, event, json.dumps(body, separators=(",", ":"), default=str), src, cfg),
                        )
                        c.commit()
                self.last_write_epoch = ts
                self.last_error = None
            return {"ok": True, "backend": self.backend, "epoch": ts, "memory_type": mt}
        except Exception as exc:
            self.last_error = str(exc)[:240]
            return {"ok": False, "backend": self.backend, "error": self.last_error, "memory_type": mt}

    def recent(self, limit: int = 100, symbol: Optional[str] = None, memory_type: Optional[str] = None) -> Dict[str, Any]:
        limit = max(1, min(1000, int(limit)))
        sym = _clean_text(symbol, 48)
        mt = _clean_text(memory_type, 48)
        try:
            if self.pg:
                assert psycopg is not None and dict_row is not None
                where, args = [], []
                if sym:
                    where.append("symbol=%s"); args.append(sym)
                if mt:
                    where.append("memory_type=%s"); args.append(mt.upper())
                sql = "SELECT id,epoch,memory_type,symbol,scope_key,event_key,payload_json,source,config_hash,immutable FROM v743_memory_events"
                if where:
                    sql += " WHERE " + " AND ".join(where)
                sql += " ORDER BY epoch DESC LIMIT %s"; args.append(limit)
                with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
                    rows = [dict(x) for x in c.execute(sql, tuple(args)).fetchall()]
            else:
                where, args = [], []
                if sym:
                    where.append("symbol=?"); args.append(sym)
                if mt:
                    where.append("memory_type=?"); args.append(mt.upper())
                sql = "SELECT id,epoch,memory_type,symbol,scope_key,event_key,payload_json,source,config_hash,immutable FROM v743_memory_events"
                if where:
                    sql += " WHERE " + " AND ".join(where)
                sql += " ORDER BY epoch DESC LIMIT ?"; args.append(limit)
                with self._sqlite() as c:
                    rows = [dict(x) for x in c.execute(sql, tuple(args)).fetchall()]
            for row in rows:
                if isinstance(row.get("payload_json"), str):
                    try:
                        row["payload"] = json.loads(row.pop("payload_json"))
                    except Exception:
                        row["payload"] = {"raw": row.pop("payload_json")}
                else:
                    row["payload"] = row.pop("payload_json", {})
            return {"ok": True, "backend": self.backend, "rows": rows, "count": len(rows)}
        except Exception as exc:
            self.last_error = str(exc)[:240]
            return {"ok": False, "backend": self.backend, "rows": [], "count": 0, "error": self.last_error}

    def summary(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        total = 0
        try:
            if self.pg:
                assert psycopg is not None
                with psycopg.connect(DATABASE_URL) as c:
                    for mt, cnt in c.execute("SELECT memory_type,COUNT(*) FROM v743_memory_events GROUP BY memory_type").fetchall():
                        counts[str(mt)] = int(cnt)
            else:
                with self._sqlite() as c:
                    for row in c.execute("SELECT memory_type,COUNT(*) AS n FROM v743_memory_events GROUP BY memory_type").fetchall():
                        counts[str(row["memory_type"])] = int(row["n"])
            total = sum(counts.values())
            self.last_error = None
        except Exception as exc:
            self.last_error = str(exc)[:240]
        return {
            "backend": self.backend,
            "durable": bool(self.pg),
            "configured_database_url": bool(DATABASE_URL),
            "sqlite_path": str(SQLITE_PATH) if not self.pg else None,
            "event_count": total,
            "counts": counts,
            "memory_types": list(MEMORY_TYPES),
            "last_write_epoch": self.last_write_epoch or None,
            "last_error": self.last_error,
            "policy": "Observed evidence only; production thresholds are never auto-mutated from memory.",
        }


MEMORY = MarketMemory()
