from __future__ import annotations

import copy
import csv
import gzip
import io
import json
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse

import v746_app as legacy
import v747_engine as core
import v64_engine
from app import request_service, service_for, _auth_detail
from upstox_service import safe_float, pct_change

VERSION = core.VERSION
RELEASE = core.RELEASE
ROOT = Path(__file__).parent
UI = ROOT / "static" / "v747.html"
app = legacy.app
app.title = "POWERHOUSE AI V74.7 — Whole-Market Move Intelligence"
app.version = VERSION
IST = ZoneInfo("Asia/Kolkata")

_LOCK = threading.RLock()
_CASH_UNIVERSE: Dict[str, Dict[str, Any]] = {}
_CASH_ROWS: Dict[str, Dict[str, Any]] = {}
_HISTORY: Dict[str, deque] = defaultdict(lambda: deque(maxlen=180))
_BASELINES: Dict[str, Dict[str, Any]] = {}
_ALERTS = deque(maxlen=2500)
_ALERT_SIG: Dict[str, float] = {}
_ALERT_STATE: Dict[str, str] = {}
_ALERTED_SYMBOLS: set[str] = set()
_LAST_MARKET: Dict[str, Any] = {"rows": [], "counts": {}}
_SCANNER_META: Dict[str, Any] = {
    "running": False, "universe_ready": False, "universe_size": 0, "observed": 0,
    "last_batch_epoch": 0.0, "last_full_sweep_epoch": 0.0, "batch_cursor": 0,
    "batch_size": 450, "last_error": None, "sweep_count": 0,
}
_STOP = threading.Event()
_SCAN_THREAD = None
_BASELINE_THREAD = None
_FII_CACHE: Dict[str, Any] = {"epoch": 0.0, "payload": None}
_PART_CACHE: Dict[str, Any] = {"epoch": 0.0, "payload": None}

FEATURES = {
    "whole_nse_cash_discovery": "IMPLEMENTED",
    "up_and_down_symmetric_detection": "IMPLEMENTED",
    "liquidity_fast_lane": "IMPLEMENTED",
    "turnover_velocity": "IMPLEMENTED",
    "market_depth_order_book": "IMPLEMENTED",
    "open_low_open_high": "IMPLEMENTED",
    "intraday_recovery_fall": "IMPLEMENTED",
    "pre_move_lifecycle": "IMPLEMENTED",
    "smart_flow_footprint": "IMPLEMENTED",
    "smc_style_autotrender_index_and_stock": "IMPLEMENTED",
    "circuit_hunter_both_directions": "IMPLEMENTED",
    "blind_spot_sentinel": "IMPLEMENTED",
    "one_by_one_alert_queue": "IMPLEMENTED_UI_AND_API",
    "official_fii_dii_cash_adapter": "IMPLEMENTED_WITH_FALLBACK",
    "participant_oi_adapter": "IMPLEMENTED_WITH_FALLBACK",
    "advanced_chart_existing_engine": "PRESERVED_AND_SURFACED",
    "broker_order_placement": "DISABLED_BY_DESIGN",
}


def _remove_get(path: str) -> None:
    app.router.routes[:] = [r for r in app.router.routes if not (getattr(r, "path", None) == path and "GET" in (getattr(r, "methods", None) or set()))]


_remove_get("/")


@app.get("/")
def home():
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache", "Expires": "0",
        "X-Powerhouse-Build": "V74.7-WHOLE-MARKET-MOVE-INTELLIGENCE-MASTER-FINAL",
    }
    if UI.exists():
        return FileResponse(UI, headers=headers)
    return legacy.home()


@app.get("/v746")
def v746_preserved():
    ui = ROOT / "static" / "v746.html"
    if ui.exists():
        return FileResponse(ui, headers={"Cache-Control":"no-store","X-Powerhouse-Build":"V74.6-PRESERVED"})
    raise HTTPException(status_code=404, detail="V74.6 UI unavailable")


def _emit(severity: str, kind: str, symbol: str, title: str, body: str, payload: Optional[dict] = None, cooldown: int = 40) -> None:
    now = time.time(); sym = str(symbol or "MARKET").upper(); sig = f"{kind}|{sym}|{body}"
    with _LOCK:
        if now - _ALERT_SIG.get(sig, 0.0) < cooldown:
            return
        _ALERT_SIG[sig] = now
        item = {
            "id": f"V747-{int(now*1000)}-{len(_ALERTS)}", "epoch": now,
            "severity": severity, "kind": kind, "symbol": sym, "title": title,
            "body": body, "payload": payload or {}, "read_only": True,
        }
        _ALERTS.append(item); _ALERTED_SYMBOLS.add(sym)


def _rank_stage(stage: str) -> int:
    order = {x:i for i,x in enumerate(core.STAGES)}
    return order.get(str(stage or "DISCOVERY"), 0)


def _transition_alerts(market: Dict[str, Any]) -> None:
    # Only meaningful fast/pre-move states enter the queue. Same symbol upgrades instead of spamming.
    rows = list(market.get("fast_lane") or []) + list(market.get("pre_move") or []) + list(market.get("circuits") or [])
    seen = set()
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if not sym or sym in seen: continue
        seen.add(sym)
        stage = str(row.get("stage") or "DISCOVERY"); direction = str(row.get("direction") or "NEUTRAL")
        state = f"{direction}|{stage}|{row.get('circuit_state') or ''}"
        old = _ALERT_STATE.get(sym); _ALERT_STATE[sym] = state
        if old == state: continue
        old_stage = old.split("|")[1] if old and "|" in old else "DISCOVERY"
        improved = old is None or direction not in old or _rank_stage(stage) > _rank_stage(old_stage) or bool(row.get("circuit_state"))
        if not improved: continue
        severity = core.ALERT_SEVERITY.get(stage, "WATCH")
        sig = str(row.get("signal") or "WATCH")
        reasons = " · ".join((row.get("reasons") or [])[:3]) or str(row.get("large_flow_state") or "observable anomaly")
        _emit(severity, "MOVE_LIFECYCLE", sym, f"{sym} — {sig} / {stage}", reasons, row, 25)


def _parse_depth(q: Dict[str, Any]) -> Dict[str, Any]:
    depth = q.get("depth") or {}; buys = depth.get("buy") or []; sells = depth.get("sell") or []
    bid = safe_float((buys[0] or {}).get("price")) if buys else 0.0
    ask = safe_float((sells[0] or {}).get("price")) if sells else 0.0
    bq = safe_float((buys[0] or {}).get("quantity")) if buys else 0.0
    aq = safe_float((sells[0] or {}).get("quantity")) if sells else 0.0
    levels = []
    for i in range(max(len(buys), len(sells), 0)):
        b = (buys[i] if i < len(buys) else {}) or {}; a = (sells[i] if i < len(sells) else {}) or {}
        level = {
            "bid": safe_float(b.get("price")) or None, "bid_qty": safe_float(b.get("quantity")) or None,
            "bid_orders": int(safe_float(b.get("orders"),0) or 0) or None,
            "ask": safe_float(a.get("price")) or None, "ask_qty": safe_float(a.get("quantity")) or None,
            "ask_orders": int(safe_float(a.get("orders"),0) or 0) or None,
        }
        if any(v is not None for v in level.values()): levels.append(level)
    return {"bid":bid or None,"ask":ask or None,"bid_qty":bq or None,"ask_qty":aq or None,"depth_levels":levels}


def _load_cash_universe(svc, force: bool = False) -> int:
    global _CASH_UNIVERSE
    with _LOCK:
        if _CASH_UNIVERSE and not force:
            return len(_CASH_UNIVERSE)
    url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
    resp = svc.client.get(url, timeout=25.0); resp.raise_for_status()
    raw = resp.content
    try: raw = gzip.decompress(raw)
    except OSError: pass
    rows = json.loads(raw.decode("utf-8"))
    best: Dict[str, Dict[str, Any]] = {}
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict) or str(item.get("segment") or "") != "NSE_EQ": continue
        key = str(item.get("instrument_key") or "").strip()
        sym = str(item.get("trading_symbol") or item.get("tradingsymbol") or item.get("symbol") or "").upper().strip()
        if not key or not sym: continue
        typ = str(item.get("instrument_type") or "").upper()
        if typ in {"INDEX","INDICES"}: continue
        candidate = {
            "symbol": sym, "instrument_key": key, "name": item.get("name") or item.get("short_name") or sym,
            "instrument_type": typ, "isin": item.get("isin"), "source_universe":"NSE CASH",
        }
        score = 2 if typ == "EQ" else 1
        prev = best.get(sym)
        if prev is None or score > int(prev.get("_pref") or 0):
            candidate["_pref"] = score; best[sym] = candidate
    found = {v["instrument_key"]:{k:x for k,x in v.items() if k!="_pref"} for v in best.values()}
    with _LOCK:
        _CASH_UNIVERSE = found
        _SCANNER_META.update({"universe_ready":bool(found),"universe_size":len(found)})
    return len(found)


def _quote_to_row(base: Dict[str, Any], q: Dict[str, Any], now: float) -> Dict[str, Any]:
    row = dict(base); ohlc = q.get("ohlc") or {}; ltp = safe_float(q.get("last_price")); cp = safe_float(q.get("prev_close_price") or ohlc.get("close"))
    dep = _parse_depth(q)
    row.update({
        "ltp": ltp or None, "cp": cp or None, "change_pct": pct_change(ltp, cp) if ltp and cp else None,
        "volume": safe_float(q.get("volume") or ohlc.get("volume")) or None,
        "day_open": safe_float(ohlc.get("open")) or None, "day_high": safe_float(ohlc.get("high")) or None,
        "day_low": safe_float(ohlc.get("low")) or None, "high_52w": safe_float(q.get("year_high")) or None,
        "low_52w": safe_float(q.get("year_low")) or None, "atp": safe_float(q.get("average_price")) or None,
        "total_buy_qty": safe_float(q.get("total_buy_quantity")) or None,
        "total_sell_qty": safe_float(q.get("total_sell_quantity")) or None,
        "lower_circuit_limit": safe_float(q.get("lower_circuit_limit")) or None,
        "upper_circuit_limit": safe_float(q.get("upper_circuit_limit")) or None,
        "reference_price": safe_float(q.get("reference_price")) or None,
        "indicative_equilibrium_price": safe_float(q.get("indicative_equilibrium_price")) or None,
        "indicative_equilibrium_quantity": safe_float(q.get("indicative_equilibrium_quantity")) or None,
        "indicative_imbalance_quantity_total": safe_float(q.get("indicative_imbalance_quantity_total")) or None,
        "quote_epoch": now, "live": bool(ltp and cp), **dep,
    })
    base_line = _BASELINES.get(str(row.get("symbol") or "")) or {}
    row.update({k:v for k,v in base_line.items() if v is not None})
    return row


def _rebuild_market() -> Dict[str, Any]:
    global _LAST_MARKET
    with _LOCK:
        rows = [dict(x) for x in _CASH_ROWS.values() if x.get("ltp")]
        histories = {k:list(v) for k,v in _HISTORY.items()}
    market = core.rank_market(rows, histories, 220)
    market["coverage"] = {
        "universe_size": int(_SCANNER_META.get("universe_size") or 0),
        "observed": len(rows),
        "coverage_pct": round(100*len(rows)/max(1,int(_SCANNER_META.get("universe_size") or 1)),1),
        "baseline_ready": len(_BASELINES),
    }
    _transition_alerts(market)
    with _LOCK:
        _LAST_MARKET = market
        _SCANNER_META["observed"] = len(rows)
    return market


def _scan_loop() -> None:
    batch_size = max(100, min(450, int(os.getenv("V747_CASH_BATCH_SIZE", "450"))))
    pause = max(.8, min(5.0, float(os.getenv("V747_CASH_BATCH_PAUSE_SEC", "1.6"))))
    _SCANNER_META["batch_size"] = batch_size; _SCANNER_META["running"] = True
    cursor = 0
    while not _STOP.is_set():
        try:
            svc = service_for("default")
            if not svc.authenticated or getattr(svc,"token_invalid",False):
                _SCANNER_META["last_error"] = "Upstox authentication required"; _STOP.wait(2.0); continue
            if not _CASH_UNIVERSE:
                _load_cash_universe(svc)
            with _LOCK: keys = list(_CASH_UNIVERSE.keys())
            if not keys:
                _STOP.wait(3.0); continue
            if cursor >= len(keys): cursor = 0
            batch = keys[cursor:cursor+batch_size]
            if not batch: cursor = 0; continue
            quotes = svc._full_quotes_v3(batch)
            now = time.time()
            with _LOCK:
                for key in batch:
                    base = _CASH_UNIVERSE.get(key) or {}; q = quotes.get(key) or {}
                    if not q: continue
                    row = _quote_to_row(base,q,now); _CASH_ROWS[key] = row
                    sym = str(row.get("symbol") or "")
                    hist = _HISTORY[sym]
                    point = {"t":now,"ltp":row.get("ltp"),"volume":row.get("volume"),"buy":row.get("total_buy_qty"),"sell":row.get("total_sell_qty")}
                    if not hist or point["ltp"] != hist[-1].get("ltp") or point["volume"] != hist[-1].get("volume") or now-float(hist[-1].get("t") or 0)>=10:
                        hist.append(point)
                cursor += len(batch)
                _SCANNER_META.update({"last_batch_epoch":now,"batch_cursor":cursor,"last_error":None})
                if cursor >= len(keys):
                    _SCANNER_META["last_full_sweep_epoch"] = now; _SCANNER_META["sweep_count"] = int(_SCANNER_META.get("sweep_count") or 0)+1
            _rebuild_market()
        except Exception as exc:
            _SCANNER_META["last_error"] = str(exc)[:240]
            _STOP.wait(2.5)
        _STOP.wait(pause)
    _SCANNER_META["running"] = False


def _baseline_loop() -> None:
    interval = max(5.0, min(30.0, float(os.getenv("V747_BASELINE_INTERVAL_SEC", "8"))))
    while not _STOP.is_set():
        try:
            svc = service_for("default")
            if svc.authenticated and hasattr(svc,"_hydrate_fno_baseline"):
                with _LOCK:
                    ranked = list((_LAST_MARKET or {}).get("fast_lane") or []) + list((_LAST_MARKET or {}).get("pre_move") or [])
                    row_map = {str(x.get("symbol") or ""):x for x in _CASH_ROWS.values()}
                target = None
                for m in ranked[:40]:
                    sym = str(m.get("symbol") or "")
                    b = _BASELINES.get(sym) or {}
                    if time.time()-float(b.get("baseline_epoch") or 0)>1800 and sym in row_map:
                        target = row_map[sym]; break
                if target:
                    base = svc._hydrate_fno_baseline(target)
                    if base:
                        with _LOCK: _BASELINES[str(target.get("symbol") or "")] = base
        except Exception:
            pass
        _STOP.wait(interval)


def _ensure_threads() -> None:
    global _SCAN_THREAD, _BASELINE_THREAD
    if _SCAN_THREAD is None or not _SCAN_THREAD.is_alive():
        _STOP.clear(); _SCAN_THREAD=threading.Thread(target=_scan_loop,name="v747-cash-scout",daemon=True); _SCAN_THREAD.start()
    if _BASELINE_THREAD is None or not _BASELINE_THREAD.is_alive():
        _BASELINE_THREAD=threading.Thread(target=_baseline_loop,name="v747-baseline",daemon=True); _BASELINE_THREAD.start()


@app.on_event("startup")
def v747_startup() -> None:
    _ensure_threads()


@app.on_event("shutdown")
def v747_shutdown() -> None:
    _STOP.set()


def _module_health(base_snap: Optional[Dict[str,Any]]=None) -> Dict[str,Any]:
    now=time.time(); observed=int(_SCANNER_META.get("observed") or 0); universe=int(_SCANNER_META.get("universe_size") or 0)
    cash_age=now-float(_SCANNER_META.get("last_batch_epoch") or 0) if _SCANNER_META.get("last_batch_epoch") else None
    with _LOCK:
        depth_ready=sum(1 for x in _CASH_ROWS.values() if x.get("depth_levels") or x.get("total_buy_qty") is not None)
    return {
        "market_feed":{"state":"LIVE" if cash_age is not None and cash_age<15 else "DELAYED" if observed else "WARMING","age_sec":round(cash_age,1) if cash_age is not None else None},
        "whole_cash":{"state":"LIVE" if observed else "WARMING","observed":observed,"universe":universe,"coverage_pct":round(100*observed/max(1,universe),1)},
        "depth":{"state":"LIVE" if depth_ready else "PARTIAL","ready":depth_ready},
        "historical_baselines":{"state":"PARTIAL" if len(_BASELINES)<max(1,observed) else "LIVE","ready":len(_BASELINES)},
        "chart":{"state":"ON_DEMAND","source":"/api/v74.3/intelligence/{symbol}"},
        "fii_dii":{"state":"ON_DEMAND","source":"NSE official adapter + local verified fallback"},
        "news_catalyst":{"state":"ON_DEMAND","source":"NSE corporate announcements adapter"},
        "scanner_error":_SCANNER_META.get("last_error"),
    }


def _index_autotrend(base_snap: Dict[str,Any]) -> List[Dict[str,Any]]:
    out=[]
    for x in base_snap.get("setups") or []:
        sym=str(x.get("symbol") or "").upper()
        if sym not in {"NIFTY","BANKNIFTY","MIDCPNIFTY","SENSEX"}: continue
        a=x.get("adaptive") or {}; action=str(a.get("final_action") or a.get("probe_action") or x.get("option_action") or x.get("action") or "WATCH").upper()
        if action in {"CE","CALL","BUY CALL"}: signal="BUY"
        elif action in {"PE","PUT","BUY PUT"}: signal="SELL"
        elif "BUY" in action: signal="BUY"
        elif "SELL" in action: signal="SELL"
        else: signal="WATCH"
        stage=a.get("lifecycle") or x.get("stage") or "DISCOVERY"
        exe=((a.get("execution_quality") or {}).get("score")) or 70
        direction="UP" if signal=="BUY" else "DOWN" if signal=="SELL" else "NEUTRAL"
        generic_plan=core.plan_entry({"ltp":x.get("ltp"),"direction":direction,"stage":stage,"execution_quality":exe})
        out.append({"symbol":sym,"scope":"INDEX","signal":signal,"stage":stage,"strength":a.get("confidence_score") or x.get("score"),"urgency":a.get("urgency_score"),"ltp":x.get("ltp"),"change_pct":x.get("change_pct"),"plan":x.get("call") or x.get("hero5") or generic_plan,"source":"V74.6 adaptive index engine + V74.7 planning overlay","read_only":True})
    return out


def _official_fii_dii(force: bool=False) -> Dict[str,Any]:
    now=time.time()
    if not force and _FII_CACHE.get("payload") and now-float(_FII_CACHE.get("epoch") or 0)<300:
        return copy.deepcopy(_FII_CACHE["payload"])
    error=None; rows=[]
    try:
        svc=service_for("default"); headers={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*","Referer":"https://www.nseindia.com/reports/fii-dii"}
        try: svc.client.get("https://www.nseindia.com/reports/fii-dii",headers=headers,timeout=10.0)
        except Exception: pass
        r=svc.client.get("https://www.nseindia.com/api/fiidiiTradeReact",headers=headers,timeout=12.0)
        r.raise_for_status(); data=r.json()
        for x in data if isinstance(data,list) else []:
            rows.append({"category":x.get("category"),"date":x.get("date"),"buy_value":x.get("buyValue") or x.get("buy_value"),"sell_value":x.get("sellValue") or x.get("sell_value"),"net_value":x.get("netValue") or x.get("net_value"),"source":"NSE official provisional FII/DII cash activity","verified":True})
    except Exception as exc:
        error=str(exc)[:220]
    if not rows:
        local=v64_engine.cash_activity(40); rows=list(local.get("latest") or [])
        payload={"status":"READY_FALLBACK" if rows else "UNAVAILABLE","latest":rows,"source":"Local verified institutional store" if rows else "NSE official adapter","reason":error or "Official report not published/available yet","provisional":True}
    else:
        payload={"status":"READY","latest":rows,"source":"NSE official provisional FII/DII cash activity","provisional":True,"note":"Official cash activity is aggregate; it does not identify stock-level institutional trades."}
    _FII_CACHE.update({"epoch":now,"payload":payload}); return copy.deepcopy(payload)


def _participant_oi(force: bool=False) -> Dict[str,Any]:
    now=time.time()
    if not force and _PART_CACHE.get("payload") and now-float(_PART_CACHE.get("epoch") or 0)<900:
        return copy.deepcopy(_PART_CACHE["payload"])
    rows=[]; error=None
    try:
        svc=service_for("default"); headers={"User-Agent":"Mozilla/5.0","Accept":"text/csv,*/*","Referer":"https://www.nseindia.com/all-reports-derivatives"}
        today=datetime.now(IST).date()
        for back in range(0,8):
            d=today-timedelta(days=back)
            if d.weekday()>=5: continue
            ds=d.strftime("%d%m%Y")
            url=f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{ds}.csv"
            r=svc.client.get(url,headers=headers,timeout=12.0)
            if r.status_code!=200 or len(r.content)<80: continue
            txt=r.content.decode("utf-8-sig",errors="replace")
            rr=list(csv.DictReader(io.StringIO(txt)))
            if rr:
                for x in rr:
                    clean={str(k or "").strip():str(v or "").strip() for k,v in x.items()}
                    clean["report_date"]=d.isoformat(); clean["source"]="NSE Participant-wise Open Interest"; rows.append(clean)
                break
    except Exception as exc:
        error=str(exc)[:220]
    if not rows:
        local=v64_engine.participant_positioning(100); rows=list(local.get("positions") or [])
        payload={"status":"READY_FALLBACK" if rows else "UNAVAILABLE","positions":rows,"source":"Local participant store" if rows else "NSE participant OI archive","reason":error or "Latest participant report unavailable"}
    else:
        payload={"status":"READY","positions":rows,"source":"NSE Participant-wise Open Interest","policy":"Participant positioning is segment-level; it is not stock-level FII/DII identity."}
    _PART_CACHE.update({"epoch":now,"payload":payload}); return copy.deepcopy(payload)


def _nse_announcements(symbol: str) -> Dict[str,Any]:
    sym=str(symbol or "").upper().strip(); rows=[]; error=None
    try:
        svc=service_for("default"); headers={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*","Referer":"https://www.nseindia.com/companies-listing/corporate-filings-announcements"}
        today=datetime.now(IST).date(); fr=(today-timedelta(days=3)).strftime("%d-%m-%Y"); to=today.strftime("%d-%m-%Y")
        try: svc.client.get("https://www.nseindia.com/companies-listing/corporate-filings-announcements",headers=headers,timeout=8.0)
        except Exception: pass
        url=f"https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={fr}&to_date={to}"
        r=svc.client.get(url,headers=headers,timeout=10.0); r.raise_for_status(); data=r.json()
        for x in data if isinstance(data,list) else []:
            xs=str(x.get("symbol") or "").upper()
            if xs==sym:
                rows.append({"symbol":xs,"subject":x.get("subject") or x.get("desc") or x.get("sm_name"),"details":x.get("attchmntText") or x.get("description") or x.get("desc"),"timestamp":x.get("an_dt") or x.get("sort_date"),"source":"NSE Corporate Announcements"})
    except Exception as exc: error=str(exc)[:220]
    return {"status":"READY" if rows else "NO_VERIFIED_CATALYST","symbol":sym,"items":rows[:20],"source":"NSE Corporate Announcements","reason":error if not rows else None}


@app.get("/api/v74.7/command-center")
def command_center(request: Request, profile: str=Query("AGGRESSIVE")):
    _ensure_threads(); base=legacy._build(request,profile)
    with _LOCK: market=copy.deepcopy(_LAST_MARKET); alerts=[dict(x) for x in list(_ALERTS)[-250:]][::-1]
    market["blind_spot"]=core.blind_spot_report(market,_ALERTED_SYMBOLS)
    out=core.merge_with_v746(base,market,alerts,_module_health(base)); out["auto_trender"]["indices"]=_index_autotrend(base); out["scanner"]=dict(_SCANNER_META)
    return out


@app.get("/api/v74.7/market-scout")
def market_scout(request: Request, limit:int=Query(180,ge=20,le=500)):
    svc=request_service(request)
    if not svc.authenticated or getattr(svc,"token_invalid",False): raise HTTPException(status_code=401,detail=_auth_detail(svc))
    _ensure_threads()
    with _LOCK: market=copy.deepcopy(_LAST_MARKET)
    market["rows"]=(market.get("rows") or [])[:limit]; market["scanner"]=dict(_SCANNER_META); market["health"]=_module_health(); market["blind_spot"]=core.blind_spot_report(market,_ALERTED_SYMBOLS); return market


@app.get("/api/v74.7/auto-trender")
def auto_trender(request: Request, scope:str=Query("ALL"), profile:str=Query("AGGRESSIVE"), timeframe:int=Query(5,ge=3,le=15), limit:int=Query(100,ge=10,le=300)):
    base=legacy._build(request,profile); scope=str(scope).upper()
    with _LOCK: base_stocks=copy.deepcopy((_LAST_MARKET or {}).get("rows") or [])
    stocks=[core.autotrender(x,timeframe) for x in base_stocks]
    stocks.sort(key=lambda x:(x.get("signal") in {"BUY","SELL"}, core.f(x.get("strength"),0) or 0), reverse=True)
    indices=_index_autotrend(base)
    for x in indices: x["timeframe_min"]=timeframe
    if scope=="INDEX": rows=indices
    elif scope in {"STOCK","STOCKS","CASH","F&O","FNO"}: rows=stocks
    else: rows=indices+stocks
    return {"version":VERSION,"scope":scope,"timeframe_min":timeframe,"rows":rows[:limit],"indices":indices,"stocks":stocks[:limit],"read_only":True,"execution_enabled":False}


@app.get("/api/v74.7/setup/{symbol}")
def setup(symbol:str, request:Request, profile:str=Query("AGGRESSIVE")):
    sym=str(symbol or "").upper().strip(); base=legacy._build(request,profile)
    idx=next((x for x in _index_autotrend(base) if x.get("symbol")==sym),None)
    with _LOCK:
        stock=next((x for x in (_LAST_MARKET.get("rows") or []) if x.get("symbol")==sym),None)
    return {"version":VERSION,"symbol":sym,"index_setup":idx,"stock_setup":stock,"why_move":_nse_announcements(sym),"read_only":True}


@app.get("/api/v74.7/why/{symbol}")
def why_move(symbol:str, request:Request):
    _=request_service(request); sym=str(symbol or "").upper().strip()
    with _LOCK: stock=next((x for x in (_LAST_MARKET.get("rows") or []) if x.get("symbol")==sym),None)
    catalyst=_nse_announcements(sym)
    classification="UNKNOWN"
    if catalyst.get("items"): classification="CATALYST + FLOW" if stock and stock.get("fast_lane") else "CATALYST"
    elif stock and stock.get("fast_lane"): classification="FLOW / LIQUIDITY DRIVEN"
    elif stock and abs(core.f(stock.get("change_pct"),0) or 0)>=2: classification="PRICE / TECHNICAL MOVE — NO VERIFIED CATALYST FOUND"
    return {"version":VERSION,"symbol":sym,"classification":classification,"market_evidence":stock,"catalyst":catalyst,"read_only":True}


@app.get("/api/v74.7/fii-dii")
def fii_dii(request:Request, force:bool=Query(False)):
    _=request_service(request); return {"version":VERSION,"cash":_official_fii_dii(force),"participant_oi":_participant_oi(force),"read_only":True}


@app.get("/api/v74.7/alerts")
def alerts(since_epoch:float=Query(0.0),limit:int=Query(300,ge=1,le=1000)):
    with _LOCK: rows=[dict(x) for x in _ALERTS if float(x.get("epoch") or 0)>since_epoch]
    return {"version":VERSION,"items":rows[-limit:],"delivery":"FIFO_ONE_BY_ONE_CLIENT_QUEUE","lost_alert_policy":"PRESERVE_ALL_WITHIN_RING_BUFFER","read_only":True}


@app.get("/api/v74.7/system")
def system(request:Request):
    _=request_service(request); paths={getattr(r,"path",None) for r in app.router.routes}
    return {"version":VERSION,"release":RELEASE,"features":FEATURES,"scanner":dict(_SCANNER_META),"module_health":_module_health(),"feature_contract":{"v746_preserved":"/v746" in paths,"v747_command_center":"/api/v74.7/command-center" in paths,"v747_market_scout":"/api/v74.7/market-scout" in paths},"production_safety":{"broker_execution":False,"missing_data_as_zero":False,"smart_money_identity_inference":False},"read_only":True}


# Keep static mounts last so the V74.7 root/API routes win.
try:
    from starlette.routing import Mount
    mounts=[r for r in app.router.routes if isinstance(r,Mount)]
    normal=[r for r in app.router.routes if not isinstance(r,Mount)]
    app.router.routes[:]=normal+mounts
except Exception:
    pass
