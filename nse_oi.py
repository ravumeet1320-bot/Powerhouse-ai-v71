from __future__ import annotations
import time
from typing import Any, Dict
import httpx

NSE_PAGE = "https://www.nseindia.com/market-data/oi-spurts"
NSE_API = "https://www.nseindia.com/api/live-analysis-oi-spurts-underlyings"
_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}


def fetch_nse_oi_spurts(max_rows: int = 30) -> Dict[str, Any]:
    """Best-effort reader for NSE's public OI Spurts page data.

    NSE can rate-limit/block automated requests. Failure is returned as unavailable;
    callers must never convert that to zero or invent values.
    """
    now = time.time()
    if _CACHE.get("data") is not None and now - float(_CACHE.get("ts") or 0) < 45:
        return _CACHE["data"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": NSE_PAGE,
    }
    out: Dict[str, Any] = {
        "available": False,
        "source": "NSE India — OI Spurts",
        "source_url": NSE_PAGE,
        "rows": [],
        "note": "NSE public OI Spurts layer unavailable; no zero-value substitution is used.",
    }
    try:
        with httpx.Client(timeout=8.0, follow_redirects=True, headers=headers) as c:
            c.get("https://www.nseindia.com/")
            r = c.get(NSE_API)
            r.raise_for_status()
            payload = r.json()
        rows = payload.get("data") if isinstance(payload, dict) else []
        clean = []
        for x in (rows or [])[:max_rows]:
            if not isinstance(x, dict):
                continue
            clean.append({
                "symbol": x.get("symbol") or x.get("underlying"),
                "latest_oi": x.get("latestOI") or x.get("openInterest") or x.get("oi"),
                "prev_oi": x.get("prevOI") or x.get("previousOI"),
                "change_oi": x.get("changeInOI") or x.get("changeOI") or x.get("change") or x.get("percentChange"),
                "volume": x.get("volume") or x.get("latestVolume"),
                "raw": x,
            })
        out.update({"available": bool(clean), "rows": clean,
                    "note": "Official NSE OI Spurts public-page layer. Values are exchange-published market data, not participant identity."})
    except Exception as exc:
        out["error"] = str(exc)[:240]
    _CACHE["ts"] = now
    _CACHE["data"] = out
    return out
