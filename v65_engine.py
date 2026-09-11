from __future__ import annotations

import csv, io, json, math, os, sqlite3, time, threading, urllib.request, hashlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v62_engine import _f, _symbol_rows
from v63_engine import _sector_name, _change, strongest_sector_today
from v64_engine import DB_PATH, _db as _legacy_db, _norm_participant

ROOT = Path(__file__).parent
V65_DB_PATH = Path(os.getenv('POWERHOUSE_V65_DB_PATH') or os.getenv('POWERHOUSE_DB_PATH') or (ROOT/'.runtime'/'powerhouse_v65.sqlite3'))

SCHEMA = '''
CREATE TABLE IF NOT EXISTS source_registry(
 source_id TEXT PRIMARY KEY, label TEXT NOT NULL, base_url TEXT, trust_level TEXT NOT NULL,
 source_type TEXT NOT NULL, enabled INTEGER DEFAULT 1, created_epoch REAL NOT NULL, meta TEXT);
CREATE TABLE IF NOT EXISTS source_runs(
 id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT, dataset TEXT, started_epoch REAL,
 finished_epoch REAL, status TEXT, rows_seen INTEGER DEFAULT 0, rows_inserted INTEGER DEFAULT 0,
 error TEXT, content_hash TEXT);
CREATE INDEX IF NOT EXISTS idx_source_runs_dataset ON source_runs(dataset,finished_epoch DESC);
CREATE TABLE IF NOT EXISTS inst_activity_v65(
 id INTEGER PRIMARY KEY AUTOINCREMENT, record_key TEXT UNIQUE, epoch REAL NOT NULL, trade_date TEXT,
 participant TEXT NOT NULL, segment TEXT NOT NULL, buy_value REAL, sell_value REAL, net_value REAL,
 source_id TEXT NOT NULL, source_url TEXT, source_timestamp REAL, received_timestamp REAL,
 verified INTEGER DEFAULT 0, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_activity_v65 ON inst_activity_v65(trade_date,participant,segment);
CREATE TABLE IF NOT EXISTS holdings_v65(
 id INTEGER PRIMARY KEY AUTOINCREMENT, record_key TEXT UNIQUE, epoch REAL NOT NULL, as_of TEXT NOT NULL,
 symbol TEXT NOT NULL, category TEXT NOT NULL, entity TEXT, parent_entity TEXT, scheme TEXT,
 holding_pct REAL, shares REAL, market_value REAL, source_id TEXT NOT NULL, source_url TEXT,
 source_timestamp REAL, received_timestamp REAL, verified INTEGER DEFAULT 0, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_hold_v65 ON holdings_v65(symbol,category,as_of DESC);
CREATE INDEX IF NOT EXISTS idx_hold_entity_v65 ON holdings_v65(parent_entity,as_of DESC);
CREATE TABLE IF NOT EXISTS participant_oi_v65(
 id INTEGER PRIMARY KEY AUTOINCREMENT, record_key TEXT UNIQUE, epoch REAL NOT NULL, trade_date TEXT,
 participant TEXT NOT NULL, segment TEXT NOT NULL, long_contracts REAL, short_contracts REAL,
 net_contracts REAL, source_id TEXT NOT NULL, source_url TEXT, source_timestamp REAL,
 received_timestamp REAL, verified INTEGER DEFAULT 0, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_poi_v65 ON participant_oi_v65(trade_date,participant,segment);
CREATE TABLE IF NOT EXISTS deals_v65(
 id INTEGER PRIMARY KEY AUTOINCREMENT, record_key TEXT UNIQUE, epoch REAL NOT NULL, trade_date TEXT,
 symbol TEXT NOT NULL, entity TEXT, parent_entity TEXT, deal_type TEXT, side TEXT, quantity REAL,
 price REAL, value REAL, category TEXT, source_id TEXT NOT NULL, source_url TEXT,
 source_timestamp REAL, received_timestamp REAL, verified INTEGER DEFAULT 0, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_deals_v65 ON deals_v65(symbol,trade_date DESC);
CREATE TABLE IF NOT EXISTS promoter_v65(
 id INTEGER PRIMARY KEY AUTOINCREMENT, record_key TEXT UNIQUE, epoch REAL NOT NULL, as_of TEXT NOT NULL,
 symbol TEXT NOT NULL, promoter_holding_pct REAL, pledge_pct REAL, source_id TEXT NOT NULL,
 source_url TEXT, verified INTEGER DEFAULT 0, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_prom_v65 ON promoter_v65(symbol,as_of DESC);
CREATE TABLE IF NOT EXISTS insider_v65(
 id INTEGER PRIMARY KEY AUTOINCREMENT, record_key TEXT UNIQUE, epoch REAL NOT NULL, trade_date TEXT,
 symbol TEXT NOT NULL, person TEXT, relation TEXT, side TEXT, quantity REAL, price REAL, value REAL,
 source_id TEXT NOT NULL, source_url TEXT, verified INTEGER DEFAULT 0, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_insider_v65 ON insider_v65(symbol,trade_date DESC);
CREATE TABLE IF NOT EXISTS inst_alerts_v65(
 id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, symbol TEXT, alert_type TEXT,
 severity TEXT, title TEXT, fingerprint TEXT UNIQUE, payload TEXT, acknowledged INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_alert_v65 ON inst_alerts_v65(epoch DESC);
CREATE TABLE IF NOT EXISTS saved_inst_screens_v65(
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, created_epoch REAL, rules TEXT);
'''

def _db():
    V65_DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(V65_DB_PATH,timeout=8)
    con.row_factory=sqlite3.Row
    con.executescript(SCHEMA)
    _bootstrap_sources(con)
    return con

def _bootstrap_sources(con):
    now=time.time()
    rows=[
      ('NSE_OFFICIAL','NSE official','https://www.nseindia.com','OFFICIAL','exchange'),
      ('BSE_OFFICIAL','BSE official','https://www.bseindia.com','OFFICIAL','exchange'),
      ('SEBI_OFFICIAL','SEBI official','https://www.sebi.gov.in','OFFICIAL','regulator'),
      ('AMFI_OFFICIAL','AMFI official','https://www.amfiindia.com','OFFICIAL','industry_body'),
      ('MANUAL_USER','Manual user input',None,'UNVERIFIED','manual'),
    ]
    for r in rows:
        con.execute('INSERT OR IGNORE INTO source_registry(source_id,label,base_url,trust_level,source_type,enabled,created_epoch,meta) VALUES(?,?,?,?,?,1,?,?)',(*r,now,'{}'))
    con.commit()

def _canonical_entity(v:str|None)->tuple[str,str]:
    raw=' '.join(str(v or '').upper().replace('&',' AND ').split())
    replacements={'MUTUAL FUND':'MF','ASSET MANAGEMENT COMPANY':'AMC','LIMITED':'LTD','PRIVATE':'PVT','COMPANY':'CO'}
    canon=raw
    for a,b in replacements.items(): canon=canon.replace(a,b)
    parent=canon
    scheme_tokens=[' FUND',' ETF',' DIRECT',' REGULAR',' GROWTH',' DIVIDEND',' PLAN',' SCHEME']
    for t in scheme_tokens:
        if t in parent:
            parent=parent.split(t)[0].strip() or canon
            break
    return canon,parent

def _key(*parts)->str:
    return hashlib.sha256('|'.join('' if p is None else str(p) for p in parts).encode()).hexdigest()

def _trusted_source(con,source_id:str)->bool:
    r=con.execute('SELECT trust_level,enabled FROM source_registry WHERE source_id=?',(source_id,)).fetchone()
    return bool(r and r['enabled'] and r['trust_level'] in {'OFFICIAL','TRUSTED'})

def register_source(source_id:str,label:str,base_url:str|None=None,trust_level:str='UNVERIFIED',source_type:str='custom',meta:dict|None=None):
    sid=str(source_id or '').upper().strip()
    if not sid: raise ValueError('source_id required')
    # API cannot self-elevate to OFFICIAL/TRUSTED unless explicitly allowed by server config.
    allow=os.getenv('POWERHOUSE_ALLOW_SOURCE_ADMIN','0')=='1'
    trust=trust_level.upper() if allow else 'UNVERIFIED'
    with _db() as con:
        con.execute('INSERT INTO source_registry(source_id,label,base_url,trust_level,source_type,enabled,created_epoch,meta) VALUES(?,?,?,?,?,1,?,?) ON CONFLICT(source_id) DO UPDATE SET label=excluded.label,base_url=excluded.base_url,source_type=excluded.source_type,meta=excluded.meta', (sid,label,base_url,trust,source_type,time.time(),json.dumps(meta or {})))
        con.commit()
    return {'source_id':sid,'trust_level':trust,'note':'Server-side source admin is required to grant TRUSTED/OFFICIAL.'}

def ingest_verified(dataset:str, rows:list[dict[str,Any]], source_id:str, source_url:str|None=None, source_ts:float|None=None, trusted_context:bool=False)->dict[str,Any]:
    ds=str(dataset or '').lower().strip(); sid=str(source_id or 'MANUAL_USER').upper().strip(); now=time.time()
    if ds not in {'activity','holding','participant_oi','deal','promoter','insider'}: raise ValueError('unsupported dataset')
    inserted=0; updated=0
    with _db() as con:
        trusted=_trusted_source(con,sid) if trusted_context else False
        for r in rows[:20000]:
            if not isinstance(r,dict): continue
            raw=json.dumps(r,default=str,separators=(',',':')); verified=1 if trusted else 0
            if ds=='activity':
                td=str(r.get('trade_date') or r.get('date') or ''); p=_norm_participant(r.get('participant')); seg=str(r.get('segment') or 'CASH').upper(); buy=_f(r.get('buy_value')); sell=_f(r.get('sell_value')); net=_f(r.get('net_value'))
                if net is None and buy is not None and sell is not None: net=buy-sell
                if not p: continue
                rk=_key(ds,td,p,seg,sid)
                vals=(rk,now,td,p,seg,buy,sell,net,sid,source_url,source_ts,now,verified,raw)
                cur=con.execute('INSERT OR IGNORE INTO inst_activity_v65(record_key,epoch,trade_date,participant,segment,buy_value,sell_value,net_value,source_id,source_url,source_timestamp,received_timestamp,verified,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',vals); inserted+=cur.rowcount
            elif ds=='holding':
                asof=str(r.get('as_of') or r.get('date') or ''); sym=str(r.get('symbol') or '').upper().strip(); cat=_norm_participant(r.get('category')); entity,parent=_canonical_entity(r.get('entity') or r.get('fund') or r.get('institution')); scheme=str(r.get('scheme') or '')
                if not sym or not cat or not asof: continue
                hp=_f(r.get('holding_pct')); shares=_f(r.get('shares')); mv=_f(r.get('market_value')); rk=_key(ds,asof,sym,cat,entity,scheme,sid)
                vals=(rk,now,asof,sym,cat,entity,parent,scheme,hp,shares,mv,sid,source_url,source_ts,now,verified,raw)
                cur=con.execute('INSERT OR REPLACE INTO holdings_v65(record_key,epoch,as_of,symbol,category,entity,parent_entity,scheme,holding_pct,shares,market_value,source_id,source_url,source_timestamp,received_timestamp,verified,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',vals); inserted+=1
            elif ds=='participant_oi':
                td=str(r.get('trade_date') or r.get('date') or ''); p=_norm_participant(r.get('participant')); seg=str(r.get('segment') or '').upper(); lo=_f(r.get('long_contracts')); sh=_f(r.get('short_contracts')); net=_f(r.get('net_contracts'))
                if net is None and lo is not None and sh is not None: net=lo-sh
                if not p or not seg: continue
                rk=_key(ds,td,p,seg,sid); con.execute('INSERT OR REPLACE INTO participant_oi_v65(record_key,epoch,trade_date,participant,segment,long_contracts,short_contracts,net_contracts,source_id,source_url,source_timestamp,received_timestamp,verified,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(rk,now,td,p,seg,lo,sh,net,sid,source_url,source_ts,now,verified,raw)); inserted+=1
            elif ds=='deal':
                td=str(r.get('trade_date') or r.get('date') or ''); sym=str(r.get('symbol') or '').upper().strip(); entity,parent=_canonical_entity(r.get('entity')); side=str(r.get('side') or '').upper(); typ=str(r.get('deal_type') or 'BULK/BLOCK').upper(); qty=_f(r.get('quantity')); price=_f(r.get('price')); val=_f(r.get('value'))
                if val is None and qty is not None and price is not None: val=qty*price
                if not sym: continue
                rk=_key(ds,td,sym,entity,side,qty,price,sid); con.execute('INSERT OR IGNORE INTO deals_v65(record_key,epoch,trade_date,symbol,entity,parent_entity,deal_type,side,quantity,price,value,category,source_id,source_url,source_timestamp,received_timestamp,verified,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(rk,now,td,sym,entity,parent,typ,side,qty,price,val,_norm_participant(r.get('category')),sid,source_url,source_ts,now,verified,raw)); inserted+=1
            elif ds=='promoter':
                asof=str(r.get('as_of') or r.get('date') or ''); sym=str(r.get('symbol') or '').upper().strip(); hp=_f(r.get('promoter_holding_pct')); pledge=_f(r.get('pledge_pct'))
                if not sym or not asof: continue
                rk=_key(ds,asof,sym,sid); con.execute('INSERT OR REPLACE INTO promoter_v65(record_key,epoch,as_of,symbol,promoter_holding_pct,pledge_pct,source_id,source_url,verified,payload) VALUES(?,?,?,?,?,?,?,?,?,?)',(rk,now,asof,sym,hp,pledge,sid,source_url,verified,raw)); inserted+=1
            else:
                td=str(r.get('trade_date') or r.get('date') or ''); sym=str(r.get('symbol') or '').upper().strip(); person=str(r.get('person') or ''); side=str(r.get('side') or '').upper(); qty=_f(r.get('quantity')); price=_f(r.get('price')); val=_f(r.get('value'))
                if val is None and qty is not None and price is not None: val=qty*price
                if not sym: continue
                rk=_key(ds,td,sym,person,side,qty,price,sid); con.execute('INSERT OR IGNORE INTO insider_v65(record_key,epoch,trade_date,symbol,person,relation,side,quantity,price,value,source_id,source_url,verified,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(rk,now,td,sym,person,str(r.get('relation') or ''),side,qty,price,val,sid,source_url,verified,raw)); inserted+=1
        con.commit()
    return {'dataset':ds,'rows_seen':len(rows),'inserted_or_upserted':inserted,'verified':trusted,'source_id':sid,'truth':'Verification comes from server-side source registry, never from caller boolean.'}

def _parse_payload(raw:bytes, fmt:str)->list[dict]:
    text=raw.decode('utf-8-sig','replace')
    if fmt=='json':
        x=json.loads(text)
        if isinstance(x,list): return x
        if isinstance(x,dict):
            for k in ('data','rows','records','result'):
                if isinstance(x.get(k),list): return x[k]
        return [x] if isinstance(x,dict) else []
    return [dict(r) for r in csv.DictReader(io.StringIO(text))]

def collect_url(dataset:str,url:str,source_id:str,fmt:str='csv',mapping:dict[str,str]|None=None,timeout:float=12)->dict:
    started=time.time(); status='ERROR'; err=''; seen=ins=0; digest=''
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 PowerhouseAI/65.0','Accept':'*/*'})
        with urllib.request.urlopen(req,timeout=timeout) as resp: raw=resp.read(8_000_000)
        digest=hashlib.sha256(raw).hexdigest(); parsed=_parse_payload(raw,fmt.lower()); seen=len(parsed)
        if mapping:
            parsed=[{dst:r.get(src) for dst,src in mapping.items()} | {'_raw':r} for r in parsed]
        out=ingest_verified(dataset,parsed,source_id,url,time.time(),trusted_context=True); ins=out['inserted_or_upserted']; status='OK'
    except Exception as exc: err=f'{type(exc).__name__}: {exc}'[:800]
    finally:
        with _db() as con:
            con.execute('INSERT INTO source_runs(source_id,dataset,started_epoch,finished_epoch,status,rows_seen,rows_inserted,error,content_hash) VALUES(?,?,?,?,?,?,?,?,?)',(source_id,dataset,started,time.time(),status,seen,ins,err,digest)); con.commit()
    return {'status':status,'dataset':dataset,'source_id':source_id,'rows_seen':seen,'rows_inserted':ins,'error':err or None}

def run_configured_collectors()->dict:
    """Run JSON-configured official/trusted collectors. No scraping rules are fabricated.
    POWERHOUSE_INSTITUTIONAL_COLLECTORS_JSON example:
    [{"dataset":"activity","url":"https://...csv","source_id":"NSE_OFFICIAL","format":"csv","mapping":{"trade_date":"Date","participant":"Category","buy_value":"Buy Value","sell_value":"Sell Value"}}]
    """
    raw=os.getenv('POWERHOUSE_INSTITUTIONAL_COLLECTORS_JSON','[]')
    try: cfg=json.loads(raw)
    except Exception: return {'status':'CONFIG_ERROR','runs':[]}
    runs=[]
    for c in cfg if isinstance(cfg,list) else []:
        if not isinstance(c,dict) or not c.get('url'): continue
        runs.append(collect_url(c.get('dataset'),c.get('url'),c.get('source_id','MANUAL_USER'),c.get('format','csv'),c.get('mapping')))
    return {'status':'READY' if runs else 'NOT_CONFIGURED','runs':runs}

_collector_thread=None; _collector_stop=threading.Event()
def start_collector_scheduler(interval_seconds:int|None=None):
    global _collector_thread
    if _collector_thread and _collector_thread.is_alive(): return
    interval=max(900,int(interval_seconds or os.getenv('POWERHOUSE_INST_COLLECT_INTERVAL','3600')))
    def loop():
        while not _collector_stop.is_set():
            try: run_configured_collectors()
            except Exception: pass
            _collector_stop.wait(interval)
    _collector_thread=threading.Thread(target=loop,daemon=True,name='v65-institutional-collector'); _collector_thread.start()

def source_health():
    with _db() as con:
        src=[dict(x) for x in con.execute('SELECT source_id,label,base_url,trust_level,source_type,enabled FROM source_registry ORDER BY trust_level,source_id')]
        runs=[dict(x) for x in con.execute('SELECT source_id,dataset,finished_epoch,status,rows_seen,rows_inserted,error FROM source_runs ORDER BY id DESC LIMIT 50')]
        counts={}
        for table,key in [('inst_activity_v65','activity'),('participant_oi_v65','participant_oi'),('holdings_v65','holding'),('deals_v65','deal'),('promoter_v65','promoter'),('insider_v65','insider')]: counts[key]=con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    latest={}
    for r in runs:
        latest.setdefault(r['dataset'],r)
    now=time.time()
    for r in latest.values(): r['age_minutes']=round((now-(r.get('finished_epoch') or now))/60,1)
    return {'sources':src,'dataset_counts':counts,'latest_runs':latest,'collector_configured':bool(os.getenv('POWERHOUSE_INSTITUTIONAL_COLLECTORS_JSON'))}

def _hold_groups(verified_only=True):
    where='WHERE verified=1' if verified_only else ''
    with _db() as con:
        rows=[dict(x) for x in con.execute(f'SELECT * FROM holdings_v65 {where} ORDER BY symbol,category,parent_entity,as_of DESC,id DESC')]
    g=defaultdict(list)
    for r in rows:g[(r['symbol'],r['category'],r.get('parent_entity') or '')].append(r)
    return g

def ownership_trends(limit=100):
    out=[]
    for (sym,cat,parent),arr in _hold_groups(True).items():
        uniq=[]; seen=set()
        for r in arr:
            if r['as_of'] in seen: continue
            seen.add(r['as_of']); uniq.append(r)
            if len(uniq)>=8: break
        vals=[_f(x.get('holding_pct')) for x in uniq]
        deltas=[]
        for i in range(len(vals)-1):
            if vals[i] is not None and vals[i+1] is not None:deltas.append(vals[i]-vals[i+1])
        cur=vals[0] if vals else None; prev=vals[1] if len(vals)>1 else None; delta=(cur-prev) if cur is not None and prev is not None else None
        inc_streak=0; dec_streak=0
        for d in deltas:
            if d>0 and dec_streak==0: inc_streak+=1
            elif d<0 and inc_streak==0: dec_streak+=1
            else: break
        accel=(deltas[0]-deltas[1]) if len(deltas)>1 else None
        new_entry=bool(cur is not None and cur>0 and prev is not None and prev<=0.01)
        complete_exit=bool(cur is not None and cur<=0.01 and prev is not None and prev>0.01)
        if complete_exit:state='COMPLETE EXIT'
        elif new_entry:state='NEW INSTITUTIONAL ENTRY'
        elif inc_streak>=3 and (delta or 0)>0:state='HIGH CONVICTION ACCUMULATION'
        elif inc_streak>=2:state='PERSISTENT ACCUMULATION'
        elif (delta or 0)>0:state='EARLY ACCUMULATION'
        elif dec_streak>=2:state='DISTRIBUTION'
        elif (delta or 0)<0:state='REDUCING'
        elif delta==0:state='HOLDING STABLE'
        else:state='BASELINE NEEDED'
        out.append({'symbol':sym,'category':cat,'institution':parent or None,'as_of':uniq[0]['as_of'] if uniq else None,'holding_pct':cur,'previous_holding_pct':prev,'change_pp':round(delta,4) if delta is not None else None,'periods':len(uniq),'increase_streak':inc_streak,'decrease_streak':dec_streak,'acceleration_pp':round(accel,4) if accel is not None else None,'new_entry':new_entry,'complete_exit':complete_exit,'state':state,'source_id':uniq[0]['source_id'] if uniq else None,'source_url':uniq[0]['source_url'] if uniq else None})
    out.sort(key=lambda x:(x['increase_streak'],x['change_pp'] or -999),reverse=True)
    return {'status':'READY' if out else 'UNAVAILABLE','rows':out[:limit],'new_entries':[x for x in out if x['new_entry']][:limit],'exits':[x for x in out if x['complete_exit']][:limit],'persistent_accumulation':[x for x in out if x['increase_streak']>=2][:limit],'persistent_distribution':[x for x in out if x['decrease_streak']>=2][:limit]}

def promoter_intelligence(limit=100):
    with _db() as con: rows=[dict(x) for x in con.execute('SELECT * FROM promoter_v65 WHERE verified=1 ORDER BY symbol,as_of DESC,id DESC')]
    g=defaultdict(list)
    for r in rows:g[r['symbol']].append(r)
    out=[]
    for sym,arr in g.items():
        uniq=[];seen=set()
        for x in arr:
            if x['as_of'] not in seen:seen.add(x['as_of']);uniq.append(x)
            if len(uniq)>=2:break
        c=uniq[0];p=uniq[1] if len(uniq)>1 else None
        hc=_f(c.get('promoter_holding_pct')); hp=_f(p.get('promoter_holding_pct')) if p else None; pc=_f(c.get('pledge_pct')); pp=_f(p.get('pledge_pct')) if p else None
        out.append({'symbol':sym,'as_of':c['as_of'],'promoter_holding_pct':hc,'holding_change_pp':round(hc-hp,4) if hc is not None and hp is not None else None,'pledge_pct':pc,'pledge_change_pp':round(pc-pp,4) if pc is not None and pp is not None else None,'risk':'PLEDGE RISING' if pc is not None and pp is not None and pc>pp else 'OK/UNKNOWN','source_url':c.get('source_url')})
    return {'status':'READY' if out else 'UNAVAILABLE','rows':out[:limit]}

def deal_timeline(limit=200):
    with _db() as con: rows=[dict(x) for x in con.execute('SELECT * FROM deals_v65 WHERE verified=1 ORDER BY trade_date DESC,id DESC LIMIT ?',(limit,))]
    for r in rows:
        r['signed_value']=(_f(r.get('value'),0) or 0)*(1 if str(r.get('side')).startswith('B') else -1 if str(r.get('side')).startswith('S') else 0)
    return {'status':'READY' if rows else 'UNAVAILABLE','rows':rows}

def participant_trends(limit=200):
    with _db() as con: rows=[dict(x) for x in con.execute('SELECT * FROM participant_oi_v65 WHERE verified=1 ORDER BY participant,segment,trade_date DESC,id DESC LIMIT 5000')]
    g=defaultdict(list)
    for r in rows:g[(r['participant'],r['segment'])].append(r)
    out=[]
    for (p,seg),arr in g.items():
        c=arr[0];pr=arr[1] if len(arr)>1 else None; n=_f(c.get('net_contracts')); pn=_f(pr.get('net_contracts')) if pr else None
        out.append({'participant':p,'segment':seg,'trade_date':c['trade_date'],'net_contracts':n,'previous_net_contracts':pn,'net_change':round(n-pn,2) if n is not None and pn is not None else None,'bias':'NET LONG' if (n or 0)>0 else 'NET SHORT' if (n or 0)<0 else 'BALANCED','source_url':c.get('source_url')})
    return {'status':'READY' if out else 'UNAVAILABLE','rows':out[:limit]}

def _market_map(market):return {str(r.get('symbol') or r.get('tradingsymbol') or '').upper():r for r in _symbol_rows(market) if isinstance(r,dict)}

def stock_consensus(market:dict[str,Any],limit=100):
    trends=ownership_trends(2000).get('rows') or []; by=defaultdict(list)
    for x in trends:by[x['symbol']].append(x)
    deals=deal_timeline(2000).get('rows') or []; dm=defaultdict(float)
    for d in deals:dm[d['symbol']]+=d.get('signed_value') or 0
    prom={x['symbol']:x for x in promoter_intelligence(2000).get('rows') or []}; mm=_market_map(market); rows=[]
    for sym in set(by)|set(dm)|set(prom):
        cats=by.get(sym,[]); fpi=sum((x.get('change_pp') or 0) for x in cats if x['category'] in {'FPI','FII'}); mf=sum((x.get('change_pp') or 0) for x in cats if x['category']=='MF'); dii=sum((x.get('change_pp') or 0) for x in cats if x['category'] in {'DII','INSURANCE'}); streak=max([x.get('increase_streak') or 0 for x in cats] or [0])
        r=mm.get(sym,{}); ch=_change(r); rv=_f(r.get('rvol')); oi=_f(r.get('futures_oi_change_pct'),_f(r.get('oi_change_pct'))); sector=_sector_name(r)
        ident=fpi*12+mf*12+dii*10+min(20,streak*6)
        if dm.get(sym):ident+=max(-15,min(15,math.copysign(math.log10(abs(dm[sym])+1)*1.6,dm[sym])))
        pc=prom.get(sym,{}).get('holding_change_pp'); pledge=prom.get(sym,{}).get('pledge_change_pp')
        if pc is not None:ident+=max(-8,min(8,pc*8))
        if pledge is not None and pledge>0:ident-=min(12,pledge*6)
        confirm=(max(-8,min(8,(ch or 0)*2.5))+ (max(-5,min(8,((rv or 1)-1)*6)) if rv is not None else 0)+ (max(-5,min(8,oi)) if oi is not None else 0))
        score=max(0,min(100,50+ident+confirm*.35)); state='HIGH CONVICTION' if score>=75 and streak>=2 else 'ACCUMULATION' if score>=62 else 'DISTRIBUTION' if score<=38 else 'MIXED / INSUFFICIENT'
        rows.append({'symbol':sym,'sector':sector,'institutional_conviction_score':round(score,1),'state':state,'FPI_change_pp':round(fpi,4),'MF_change_pp':round(mf,4),'DII_change_pp':round(dii,4),'max_accumulation_streak':streak,'verified_deal_net_value':round(dm.get(sym,0),2),'promoter_change_pp':pc,'pledge_change_pp':pledge,'market_confirmation':{'change_pct':ch,'rvol':rv,'futures_oi_change_pct':oi},'score_note':'Evidence/conviction score, not win probability.'})
    rows.sort(key=lambda x:x['institutional_conviction_score'],reverse=True)
    return {'status':'READY' if rows else 'UNAVAILABLE','leaders':rows[:limit],'distribution':sorted(rows,key=lambda x:x['institutional_conviction_score'])[:limit]}

def sector_money_map(market:dict[str,Any]):
    cons=stock_consensus(market,1000).get('leaders') or []; sec=defaultdict(lambda:{'stocks':0,'fpi':0.,'mf':0.,'dii':0.,'deal':0.,'scores':[],'accumulating':0,'distributing':0})
    for x in cons:
        s=x.get('sector') or 'UNKNOWN'; a=sec[s];a['stocks']+=1;a['fpi']+=x['FPI_change_pp'];a['mf']+=x['MF_change_pp'];a['dii']+=x['DII_change_pp'];a['deal']+=x['verified_deal_net_value'];a['scores'].append(x['institutional_conviction_score']);a['accumulating']+=x['state'] in {'ACCUMULATION','HIGH CONVICTION'};a['distributing']+=x['state']=='DISTRIBUTION'
    rows=[]
    for s,a in sec.items():
        avg=sum(a['scores'])/len(a['scores']) if a['scores'] else 50; breadth=(a['accumulating']-a['distributing'])/a['stocks']*100 if a['stocks'] else 0
        rows.append({'sector':s,'institutional_sector_score':round(max(0,min(100,avg+breadth*.12)),1),'stocks_with_data':a['stocks'],'accumulating':a['accumulating'],'distributing':a['distributing'],'institutional_breadth_pct':round(breadth,1),'FPI_change_pp_sum':round(a['fpi'],4),'MF_change_pp_sum':round(a['mf'],4),'DII_change_pp_sum':round(a['dii'],4),'verified_deal_net_value':round(a['deal'],2)})
    rows.sort(key=lambda x:x['institutional_sector_score'],reverse=True)
    return {'status':'READY' if rows else 'UNAVAILABLE','ranking':rows,'strongest_institutional_sector':rows[0] if rows else None,'weakest_institutional_sector':rows[-1] if rows else None}

def institutional_screener(market:dict[str,Any],rules:dict|None=None):
    rules=rules or {}; rows=stock_consensus(market,1000).get('leaders') or []
    out=[]
    for x in rows:
        ok=True
        if x['institutional_conviction_score'] < float(rules.get('min_score',60)):ok=False
        if rules.get('require_fpi_increase') and x['FPI_change_pp']<=0:ok=False
        if rules.get('require_mf_increase') and x['MF_change_pp']<=0:ok=False
        if rules.get('require_rvol') and (_f(x['market_confirmation'].get('rvol')) or 0)<float(rules.get('min_rvol',1.2)):ok=False
        if rules.get('sector') and x.get('sector')!=rules['sector']:ok=False
        if ok:out.append(x)
    return {'status':'READY' if out else 'NO_MATCH','rules':rules,'matches':out}

def create_automatic_alerts(market:dict[str,Any]):
    rows=stock_consensus(market,200).get('leaders') or []; now=time.time(); created=0
    with _db() as con:
        for x in rows:
            typ=None; sev='INFO'
            if x['state']=='HIGH CONVICTION':typ='HIGH_CONVICTION_ACCUMULATION';sev='HIGH'
            elif x['max_accumulation_streak']>=2:typ='PERSISTENT_ACCUMULATION';sev='MEDIUM'
            if not typ:continue
            fp=_key(typ,x['symbol'],datetime.now(timezone.utc).strftime('%Y-%m-%d'))
            title=f"{x['symbol']}: {x['state']} institutional footprint"
            cur=con.execute('INSERT OR IGNORE INTO inst_alerts_v65(epoch,symbol,alert_type,severity,title,fingerprint,payload) VALUES(?,?,?,?,?,?,?)',(now,x['symbol'],typ,sev,title,fp,json.dumps(x,default=str)));created+=cur.rowcount
        con.commit()
    return {'created':created}

def alerts(limit=100):
    with _db() as con: rows=[dict(x) for x in con.execute('SELECT * FROM inst_alerts_v65 ORDER BY epoch DESC LIMIT ?',(min(limit,500),))]
    for r in rows:
        try:r['payload']=json.loads(r['payload'])
        except:pass
    return {'status':'READY' if rows else 'EMPTY','rows':rows,'external_delivery':'NOT_CONNECTED'}

def reports(market:dict[str,Any]):
    activity=[]
    with _db() as con:
        activity=[dict(x) for x in con.execute('SELECT trade_date,participant,segment,buy_value,sell_value,net_value,source_id,source_url FROM inst_activity_v65 WHERE verified=1 ORDER BY trade_date DESC,id DESC LIMIT 50')]
    cons=stock_consensus(market,20); sectors=sector_money_map(market); pt=participant_trends(30); own=ownership_trends(30)
    return {'morning_brief':{'latest_cash_activity':activity[:10],'participant_positioning':pt.get('rows',[])[:10],'top_institutional_sectors':sectors.get('ranking',[])[:5],'top_accumulation':cons.get('leaders',[])[:10]},'eod_flow_report':{'cash_activity':activity[:20],'participant_positioning':pt.get('rows',[])[:20],'sector_money_map':sectors.get('ranking',[])[:10],'stock_footprints':cons.get('leaders',[])[:20]},'quarterly_ownership_report':{'new_entries':own.get('new_entries',[])[:20],'persistent_accumulation':own.get('persistent_accumulation',[])[:20],'exits':own.get('exits',[])[:20],'persistent_distribution':own.get('persistent_distribution',[])[:20]}}

def institution_search(query:str,limit:int=100):
    q='%'+str(query or '').upper().strip()+'%'
    if q=='%%': return {'status':'QUERY_REQUIRED','rows':[]}
    with _db() as con:
        h=[dict(x) for x in con.execute('SELECT as_of,symbol,category,entity,parent_entity,scheme,holding_pct,shares,source_id,source_url,verified FROM holdings_v65 WHERE verified=1 AND (UPPER(entity) LIKE ? OR UPPER(parent_entity) LIKE ? OR UPPER(scheme) LIKE ?) ORDER BY as_of DESC LIMIT ?',(q,q,q,limit))]
        d=[dict(x) for x in con.execute('SELECT trade_date,symbol,entity,parent_entity,deal_type,side,quantity,price,value,category,source_id,source_url FROM deals_v65 WHERE verified=1 AND (UPPER(entity) LIKE ? OR UPPER(parent_entity) LIKE ?) ORDER BY trade_date DESC LIMIT ?',(q,q,limit))]
    return {'status':'READY' if h or d else 'NO_MATCH','holdings':h,'deals':d}

def symbol_footprint_timeline(symbol:str,limit:int=300):
    sym=str(symbol or '').upper().strip()
    with _db() as con:
        holdings=[dict(x) for x in con.execute('SELECT as_of,symbol,category,entity,parent_entity,scheme,holding_pct,shares,market_value,source_id,source_url,verified FROM holdings_v65 WHERE symbol=? ORDER BY as_of DESC,id DESC LIMIT ?',(sym,limit))]
        deals=[dict(x) for x in con.execute('SELECT trade_date,symbol,entity,parent_entity,deal_type,side,quantity,price,value,category,source_id,source_url,verified FROM deals_v65 WHERE symbol=? ORDER BY trade_date DESC,id DESC LIMIT ?',(sym,limit))]
        promoter=[dict(x) for x in con.execute('SELECT as_of,promoter_holding_pct,pledge_pct,source_id,source_url,verified FROM promoter_v65 WHERE symbol=? ORDER BY as_of DESC,id DESC LIMIT ?',(sym,limit))]
        insider=[dict(x) for x in con.execute('SELECT trade_date,person,relation,side,quantity,price,value,source_id,source_url,verified FROM insider_v65 WHERE symbol=? ORDER BY trade_date DESC,id DESC LIMIT ?',(sym,limit))]
    events=[]
    for x in holdings: events.append({'date':x['as_of'],'type':'HOLDING','detail':x})
    for x in deals: events.append({'date':x['trade_date'],'type':'DEAL','detail':x})
    for x in promoter: events.append({'date':x['as_of'],'type':'PROMOTER/PLEDGE','detail':x})
    for x in insider: events.append({'date':x['trade_date'],'type':'INSIDER','detail':x})
    events.sort(key=lambda x:x.get('date') or '',reverse=True)
    return {'status':'READY' if events else 'UNAVAILABLE','symbol':sym,'events':events[:limit]}

def data_completeness():
    h=source_health(); counts=h['dataset_counts']; expected=['activity','participant_oi','holding','deal','promoter','insider']; available=sum(1 for k in expected if counts.get(k,0)>0)
    return {'dataset_readiness_pct':round(available/len(expected)*100,1),'available_datasets':[k for k in expected if counts.get(k,0)>0],'missing_datasets':[k for k in expected if not counts.get(k,0)],'counts':counts,'note':'Readiness measures data presence, not predictive quality.'}

def institutional_money_map(market:dict[str,Any]):
    create_automatic_alerts(market)
    return {'version':'65.0','source_health':source_health(),'data_completeness':data_completeness(),'ownership_trends':ownership_trends(200),'participant_trends':participant_trends(100),'promoter_intelligence':promoter_intelligence(100),'deal_timeline':deal_timeline(100),'stock_consensus':stock_consensus(market,100),'sector_money_map':sector_money_map(market),'strongest_market_sector':strongest_sector_today(market),'institutional_screener_default':institutional_screener(market,{'min_score':60}),'alerts':alerts(50),'reports':reports(market),'truth_policy':['Institution identity requires an explicit trusted/official source.','Caller-supplied verified=true is ignored.','Anonymous depth/volume/OI never becomes FII/DII identity.','Holding changes are reporting-period data, not intraday flow.','Scores are evidence/conviction scores, not win probability.','No broker execution.']}

def build_v65(market:dict[str,Any],v64:dict|None=None):
    mm=institutional_money_map(market)
    return {'version':'65.0','name':'Institutional Data & Money Flow Foundation','read_only':True,'money_map':mm,'implemented_now':['Server-side trusted source registry','Caller verification escalation blocked','Deduplicated/version-safe institutional records','Configurable scheduled CSV/JSON collectors','Source-run telemetry/freshness','Quarter-over-quarter ownership history','New institutional entry / complete exit','Persistent accumulation/distribution streaks','Holding acceleration','Institution/entity normalization','Promoter holding + pledge intelligence','Insider transaction storage','Participant OI day-over-day trend','Bulk/block deal timeline and signed value','Stock institutional consensus','Sector institutional money map + breadth','Institutional conviction states','Institutional screener','Institutional alerts','Morning/EOD/quarterly reports','Source drill-down URLs','Institution/fund search','Per-stock institutional footprint timeline','Dataset completeness/readiness'],'external_readiness':{'official_collectors':'CONFIGURE POWERHOUSE_INSTITUTIONAL_COLLECTORS_JSON with permitted official endpoints/files','licensed_news':'NOT_CONNECTED','hosted_persistent_db':'ADAPTER PATH READY; deployment must supply persistent volume/DB','external_alert_delivery':'NOT_CONNECTED'}}
