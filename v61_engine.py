from __future__ import annotations

import json, sqlite3, time, threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
DB_PATH = ROOT / '.runtime' / 'powerhouse_v61.sqlite3'
_LOCK = threading.RLock()

SCHEMA = '''
CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, symbol TEXT, stage TEXT, action TEXT, score REAL, price REAL, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_snap_symbol_epoch ON snapshots(symbol, epoch DESC);
CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, symbol TEXT, severity TEXT, title TEXT, detail TEXT, status TEXT DEFAULT 'NEW');
CREATE TABLE IF NOT EXISTS catalysts(id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, symbol TEXT, category TEXT, severity TEXT, title TEXT, source TEXT, verified INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, category TEXT, symbol TEXT, detail TEXT, payload TEXT);
'''

def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con

def _f(v, d=None):
    try: return float(v)
    except Exception: return d

def _rows(v60: dict[str,Any] | None):
    if not isinstance(v60, dict): return []
    cc=v60.get('command_center') or {}
    out=[]; seen=set()
    for key in ('best_now','about_to_move','second_chance','avoid'):
        for r in cc.get(key) or []:
            s=str(r.get('symbol') or '').strip()
            if not s or s in seen: continue
            seen.add(s); out.append(r)
    return out

def _snapshot_row(r):
    return {
      'symbol': r.get('symbol'), 'stage': r.get('stage') or 'WATCH',
      'action': r.get('final_action') or r.get('action') or 'WAIT',
      'score': _f(r.get('v60_rank_score'), _f(r.get('early_score'),0)) or 0,
      'price': _f(r.get('ltp')), 'payload': r
    }

def persist_market_memory(market:dict[str,Any], v60:dict[str,Any]|None) -> dict[str,Any]:
    now=_f(market.get('last_tick_epoch'), time.time()) or time.time()
    candidates=[_snapshot_row(r) for r in _rows(v60)]
    with _LOCK:
        con=_db()
        try:
            for x in candidates:
                con.execute('INSERT INTO snapshots(epoch,symbol,stage,action,score,price,payload) VALUES(?,?,?,?,?,?,?)',
                    (now,x['symbol'],x['stage'],x['action'],x['score'],x['price'],json.dumps(x['payload'],default=str,separators=(',',':'))))
            # bounded retention ~ 20k observations
            con.execute('DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT 20000)')
            con.commit()
            count=con.execute('SELECT COUNT(*) c FROM snapshots').fetchone()['c']
            syms=con.execute('SELECT COUNT(DISTINCT symbol) c FROM snapshots').fetchone()['c']
        finally: con.close()
    return {'stored_observations':count,'tracked_symbols':syms,'db_path':str(DB_PATH.name),'durable':True}

def build_replay(limit:int=50)->dict[str,Any]:
    with _LOCK:
        con=_db()
        try:
            rr=con.execute('SELECT epoch,symbol,stage,action,score,price FROM snapshots ORDER BY id DESC LIMIT ?', (max(1,min(limit,250)),)).fetchall()
        finally: con.close()
    rows=[dict(x) for x in reversed(rr)]
    transitions=[]; last={}
    for r in rows:
        s=r['symbol']; sig=(r['stage'],r['action'])
        if s in last and last[s]!=sig:
            transitions.append({'epoch':r['epoch'],'symbol':s,'from':f'{last[s][0]} / {last[s][1]}','to':f"{r['stage']} / {r['action']}"})
        last[s]=sig
    return {'observations':rows,'transitions':transitions[-30:],'read_only':True}

def _create_internal_alerts(v60):
    now=time.time(); made=0
    rows=_rows(v60)
    with _LOCK:
        con=_db()
        try:
            for r in rows:
                stage=str(r.get('stage') or '')
                action=str(r.get('final_action') or 'WAIT')
                if stage not in {'TRIGGER READY','CONFIRMED','ATTACKING'} or action=='WAIT': continue
                sym=str(r.get('symbol') or '')
                recent=con.execute('SELECT 1 FROM alerts WHERE symbol=? AND title=? AND epoch>? LIMIT 1',(sym,stage,now-300)).fetchone()
                if recent: continue
                score=_f(r.get('v60_rank_score'),0) or 0
                con.execute('INSERT INTO alerts(epoch,symbol,severity,title,detail) VALUES(?,?,?,?,?)',(now,sym,'HIGH' if stage=='CONFIRMED' else 'MEDIUM',stage,f'{action} • score {score:.1f} • read-only analytics'))
                made+=1
            con.commit()
        finally: con.close()
    return made

def alert_center(v60=None, limit=50):
    made=_create_internal_alerts(v60 or {}) if v60 else 0
    with _LOCK:
        con=_db()
        try: rr=con.execute('SELECT id,epoch,symbol,severity,title,detail,status FROM alerts ORDER BY id DESC LIMIT ?', (max(1,min(limit,100)),)).fetchall()
        finally: con.close()
    return {'generated_now':made,'alerts':[dict(x) for x in rr],'delivery':{'in_app':True,'external_channels':'NOT_CONNECTED'},'read_only':True}

def add_catalyst(symbol:str, category:str, severity:str, title:str, source:str='', verified:bool=False):
    if not title: raise ValueError('title required')
    now=time.time()
    with _LOCK:
        con=_db();
        try:
            cur=con.execute('INSERT INTO catalysts(epoch,symbol,category,severity,title,source,verified) VALUES(?,?,?,?,?,?,?)',(now,(symbol or '').upper(),category or 'EVENT',severity or 'INFO',title,source,1 if verified else 0)); con.commit(); rid=cur.lastrowid
        finally: con.close()
    return {'id':rid,'epoch':now,'symbol':(symbol or '').upper(),'category':category or 'EVENT','severity':severity or 'INFO','title':title,'source':source,'verified':bool(verified)}

def catalyst_guard(limit=30):
    now=time.time()
    with _LOCK:
        con=_db();
        try: rr=con.execute('SELECT id,epoch,symbol,category,severity,title,source,verified FROM catalysts WHERE epoch>? ORDER BY id DESC LIMIT ?', (now-7*86400,max(1,min(limit,100)))).fetchall()
        finally: con.close()
    rows=[dict(x) for x in rr]
    high=[r for r in rows if str(r['severity']).upper() in {'HIGH','CRITICAL'}]
    return {'events':rows,'high_risk_count':len(high),'policy':'Unverified catalysts are context only and cannot create a trade signal.','read_only':True}

def daily_self_audit(v60=None):
    now=time.time(); start=now-(now%86400)
    with _LOCK:
        con=_db()
        try:
            total=con.execute('SELECT COUNT(*) c FROM snapshots WHERE epoch>=?',(start,)).fetchone()['c']
            syms=con.execute('SELECT COUNT(DISTINCT symbol) c FROM snapshots WHERE epoch>=?',(start,)).fetchone()['c']
            stages={r['stage']:r['c'] for r in con.execute('SELECT stage,COUNT(*) c FROM snapshots WHERE epoch>=? GROUP BY stage',(start,)).fetchall()}
            alert_n=con.execute('SELECT COUNT(*) c FROM alerts WHERE epoch>=?',(start,)).fetchone()['c']
        finally: con.close()
    bm=(v60 or {}).get('detection_benchmark') or {}
    return {'observations_today':total,'symbols_today':syms,'stage_counts':stages,'alerts_today':alert_n,'detection_benchmark':bm,'note':'Detection timing and coverage metrics are not win rate or profit probability.'}

def build_v61(market:dict[str,Any], v60:dict[str,Any]|None)->dict[str,Any]:
    mem=persist_market_memory(market,v60)
    replay=build_replay(80)
    alerts=alert_center(v60,50)
    guard=catalyst_guard(30)
    audit=daily_self_audit(v60)
    return {
      'version':'61.0','name':'Persistent Market Memory, Replay & Alert OS','read_only':True,
      'market_memory':mem,'replay':replay,'alert_center':alerts,'catalyst_guard':guard,'daily_self_audit':audit,
      'modules':{
        'persistent_sqlite_memory':True,'state_change_replay':True,'in_app_alert_center':True,'catalyst_guard':True,'daily_self_audit':True,
        'external_push_delivery':False,'licensed_news_feed':False,'automatic_profit_scoring':False
      },
      'truth_policy':['Durable memory survives process restarts when persistent filesystem is available.','Alerts are analytics notifications only; no broker execution.','Catalysts do not become trade signals unless verified market evidence independently confirms them.']
    }
