from __future__ import annotations
import json, math, os, sqlite3, time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).parent
DB_PATH=Path(os.getenv('POWERHOUSE_V66_DB_PATH') or os.getenv('POWERHOUSE_DB_PATH') or (ROOT/'.runtime'/'powerhouse_v66.sqlite3'))
WINDOWS=(60,180,300,900,1800,3600)
SCHEMA='''
CREATE TABLE IF NOT EXISTS metric_snapshots_v66(
 id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, symbol TEXT NOT NULL, sector TEXT,
 price REAL, change_pct REAL, volume REAL, rvol REAL, futures_oi REAL, futures_oi_change_pct REAL,
 pcr REAL, max_pain REAL, atm REAL, iv REAL, vwap REAL, bid REAL, ask REAL, spread_bps REAL,
 depth_imbalance REAL, breadth_score REAL, sector_score REAL, source TEXT, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_v66_metric_symbol_epoch ON metric_snapshots_v66(symbol,epoch DESC);
CREATE INDEX IF NOT EXISTS idx_v66_metric_sector_epoch ON metric_snapshots_v66(sector,epoch DESC);
CREATE TABLE IF NOT EXISTS option_snapshots_v66(
 id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, underlying TEXT NOT NULL, strike REAL,
 option_type TEXT, oi REAL, oi_change REAL, volume REAL, ltp REAL, iv REAL, delta REAL, gamma REAL,
 theta REAL, vega REAL, bid REAL, ask REAL, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_v66_opt_u_epoch ON option_snapshots_v66(underlying,epoch DESC);
CREATE TABLE IF NOT EXISTS detections_v66(
 id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, symbol TEXT NOT NULL, stage TEXT,
 action TEXT, score REAL, price REAL, sector TEXT, evidence TEXT, outcome_class TEXT,
 max_favourable_pct REAL, max_adverse_pct REAL, evaluated_epoch REAL, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_v66_det_symbol_epoch ON detections_v66(symbol,epoch DESC);
CREATE TABLE IF NOT EXISTS config_experiments_v66(
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, variant TEXT NOT NULL, created_epoch REAL,
 enabled INTEGER DEFAULT 0, config TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS telemetry_v66(
 id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, event TEXT NOT NULL, value REAL,
 symbol TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS idx_v66_tel_epoch ON telemetry_v66(epoch DESC);
'''

def _db():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB_PATH,timeout=8); c.row_factory=sqlite3.Row; c.executescript(SCHEMA); return c

def _f(x):
    try:
        if x is None or x=='': return None
        y=float(x); return y if math.isfinite(y) else None
    except: return None

def _sym_rows(snap:dict)->list[dict]:
    for k in ('fno_universe','stocks','universe'):
        if isinstance(snap.get(k),list) and snap[k]: return [x for x in snap[k] if isinstance(x,dict)]
    return []

def _g(r,*keys):
    for k in keys:
        if r.get(k) is not None:return r.get(k)
    return None

def record_snapshot(snap:dict, source='runtime')->dict:
    now=time.time(); rows=_sym_rows(snap); inserted=0
    sector_changes=defaultdict(list)
    for r in rows:
        sec=str(_g(r,'sector','sector_name') or 'UNKNOWN').upper(); ch=_f(_g(r,'change_pct','pct_change','changePercent'))
        if ch is not None: sector_changes[sec].append(ch)
    sector_scores={s:(sum(v)/len(v) if v else None) for s,v in sector_changes.items()}
    with _db() as c:
        for r in rows:
            sym=str(_g(r,'symbol','trading_symbol','name') or '').upper().strip()
            if not sym: continue
            sec=str(_g(r,'sector','sector_name') or 'UNKNOWN').upper()
            bid=_f(_g(r,'bid','best_bid')); ask=_f(_g(r,'ask','best_ask')); px=_f(_g(r,'ltp','price','last_price'))
            spread=None
            if bid is not None and ask is not None and px and px>0: spread=(ask-bid)/px*10000
            imb=_f(_g(r,'depth_imbalance','orderbook_imbalance'))
            vals=(now,sym,sec,px,_f(_g(r,'change_pct','pct_change')),_f(r.get('volume')),_f(r.get('rvol')),
                  _f(_g(r,'futures_oi','future_oi')),_f(_g(r,'futures_oi_change_pct','oi_change_pct')),
                  _f(_g(r,'pcr','oi_pcr')),_f(r.get('max_pain')),_f(_g(r,'atm','atm_strike')),_f(_g(r,'iv','atm_iv')),
                  _f(r.get('vwap')),bid,ask,spread,imb,_f(r.get('breadth_score')),_f(sector_scores.get(sec)),source,json.dumps(r,default=str)[:30000])
            c.execute('INSERT INTO metric_snapshots_v66(epoch,symbol,sector,price,change_pct,volume,rvol,futures_oi,futures_oi_change_pct,pcr,max_pain,atm,iv,vwap,bid,ask,spread_bps,depth_imbalance,breadth_score,sector_score,source,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',vals); inserted+=1
        chain=snap.get('option_chain') or snap.get('chain') or []
        if isinstance(chain,list):
            und=str(snap.get('underlying') or snap.get('symbol') or 'NIFTY').upper()
            for x in chain[:500]:
                if not isinstance(x,dict):continue
                strike=_f(_g(x,'strike','strike_price'))
                for side,prefix in [('CE','ce'),('PE','pe')]:
                    d=x.get(prefix) if isinstance(x.get(prefix),dict) else x
                    typ=str(_g(d,'option_type','type') or side).upper()
                    if side not in typ and prefix not in x: continue
                    c.execute('INSERT INTO option_snapshots_v66(epoch,underlying,strike,option_type,oi,oi_change,volume,ltp,iv,delta,gamma,theta,vega,bid,ask,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(
                        now,und,strike,side,_f(_g(d,'oi','open_interest')),_f(_g(d,'oi_change','change_oi','delta_oi')),_f(d.get('volume')),_f(_g(d,'ltp','last_price')),_f(d.get('iv')),
                        _f(d.get('delta')),_f(d.get('gamma')),_f(d.get('theta')),_f(d.get('vega')),_f(d.get('bid')),_f(d.get('ask')),json.dumps(d,default=str)[:16000]))
        # retention: ~30 days of high frequency data; configurable
        keep_days=max(1,int(os.getenv('POWERHOUSE_V66_RETENTION_DAYS','30'))); cutoff=now-keep_days*86400
        c.execute('DELETE FROM metric_snapshots_v66 WHERE epoch<?',(cutoff,)); c.execute('DELETE FROM option_snapshots_v66 WHERE epoch<?',(cutoff,)); c.commit()
    return {'recorded':inserted,'epoch':now,'retention_days':keep_days}

def _delta(cur,old):
    if cur is None or old is None:return None
    return cur-old

def metric_history(symbol:str, minutes=60, limit=1000):
    cutoff=time.time()-max(1,minutes)*60
    with _db() as c: rows=[dict(x) for x in c.execute('SELECT * FROM metric_snapshots_v66 WHERE symbol=? AND epoch>=? ORDER BY epoch ASC LIMIT ?', (symbol.upper(),cutoff,min(limit,5000)))]
    return {'symbol':symbol.upper(),'minutes':minutes,'rows':rows,'count':len(rows)}

def _window_metrics(symbol:str):
    now=time.time(); out={}
    with _db() as c:
        cur=c.execute('SELECT * FROM metric_snapshots_v66 WHERE symbol=? ORDER BY epoch DESC LIMIT 1',(symbol,)).fetchone()
        if not cur:return out
        cur=dict(cur)
        for sec in WINDOWS:
            old=c.execute('SELECT * FROM metric_snapshots_v66 WHERE symbol=? AND epoch<=? ORDER BY epoch DESC LIMIT 1',(symbol,now-sec)).fetchone()
            old=dict(old) if old else None
            label=f'{sec//60}m'
            out[label]={}
            for k in ('price','change_pct','rvol','futures_oi_change_pct','pcr','max_pain','atm','iv','vwap','spread_bps','depth_imbalance','sector_score'):
                out[label][k+'_delta']=_delta(_f(cur.get(k)),_f(old.get(k)) if old else None)
    return out

def sector_rotation(minutes=60):
    now=time.time(); cutoff=now-minutes*60
    with _db() as c:
        cur=[dict(x) for x in c.execute('SELECT sector, AVG(change_pct) avg_change, AVG(rvol) avg_rvol, AVG(futures_oi_change_pct) avg_oi, COUNT(*) n FROM (SELECT * FROM metric_snapshots_v66 WHERE epoch>(?)) GROUP BY sector',(now-300,))]
        old=[dict(x) for x in c.execute('SELECT sector, AVG(change_pct) avg_change, AVG(rvol) avg_rvol, AVG(futures_oi_change_pct) avg_oi, COUNT(*) n FROM metric_snapshots_v66 WHERE epoch BETWEEN ? AND ? GROUP BY sector',(cutoff,cutoff+300))]
    om={x['sector']:x for x in old}; rows=[]
    for r in cur:
        o=om.get(r['sector'],{})
        score=(_f(r['avg_change']) or 0)*0.5+((_f(r['avg_rvol']) or 1)-1)*0.8+(_f(r['avg_oi']) or 0)*0.08
        oldscore=(_f(o.get('avg_change')) or 0)*0.5+((_f(o.get('avg_rvol')) or 1)-1)*0.8+(_f(o.get('avg_oi')) or 0)*0.08
        rows.append({**r,'leadership_score':round(score,3),'rotation_delta':round(score-oldscore,3),'state':'ACCELERATING' if score-oldscore>.2 else 'DECAYING' if score-oldscore<-.2 else 'STABLE'})
    rows.sort(key=lambda x:x['leadership_score'],reverse=True)
    return {'minutes':minutes,'rows':rows,'leader':rows[0] if rows else None}

def option_migration(underlying='NIFTY',minutes=60):
    now=time.time(); cutoff=now-minutes*60
    with _db() as c: rows=[dict(x) for x in c.execute('SELECT * FROM option_snapshots_v66 WHERE underlying=? AND epoch>=? ORDER BY epoch ASC',(underlying.upper(),cutoff))]
    if not rows:return {'status':'INSUFFICIENT_HISTORY','underlying':underlying.upper(),'rows':0}
    buckets=defaultdict(list)
    for r in rows:buckets[int(r['epoch']//300)*300].append(r)
    series=[]
    for ep,arr in sorted(buckets.items()):
        ce=sum((_f(x['oi']) or 0) for x in arr if x['option_type']=='CE'); pe=sum((_f(x['oi']) or 0) for x in arr if x['option_type']=='PE')
        pcr=pe/ce if ce>0 else None
        call=max((x for x in arr if x['option_type']=='CE'),key=lambda x:_f(x['oi']) or -1,default=None)
        put=max((x for x in arr if x['option_type']=='PE'),key=lambda x:_f(x['oi']) or -1,default=None)
        ivs=[_f(x['iv']) for x in arr if _f(x['iv']) is not None]
        series.append({'epoch':ep,'pcr':round(pcr,3) if pcr is not None else None,'call_wall':call['strike'] if call else None,'put_wall':put['strike'] if put else None,'mean_iv':round(sum(ivs)/len(ivs),3) if ivs else None})
    return {'status':'READY','underlying':underlying.upper(),'series':series,'rows':len(rows)}

def record_detection(candidate:dict):
    sym=str(candidate.get('symbol') or '').upper(); px=_f(candidate.get('price') or candidate.get('ltp'))
    if not sym:return {'status':'SKIPPED'}
    with _db() as c:
        c.execute('INSERT INTO detections_v66(epoch,symbol,stage,action,score,price,sector,evidence,payload) VALUES(?,?,?,?,?,?,?,?,?)',(time.time(),sym,candidate.get('stage'),candidate.get('action'),_f(candidate.get('score')),px,candidate.get('sector'),json.dumps(candidate.get('evidence') or []),json.dumps(candidate,default=str)[:30000])); c.commit()
    return {'status':'RECORDED','symbol':sym}

def evaluate_outcomes(min_age_minutes=5,max_age_minutes=390):
    now=time.time(); updated=0
    with _db() as c:
        det=[dict(x) for x in c.execute('SELECT * FROM detections_v66 WHERE evaluated_epoch IS NULL AND epoch<?',(now-min_age_minutes*60,))]
        for d in det:
            end=min(now,d['epoch']+max_age_minutes*60)
            prices=[_f(x[0]) for x in c.execute('SELECT price FROM metric_snapshots_v66 WHERE symbol=? AND epoch BETWEEN ? AND ? AND price IS NOT NULL',(d['symbol'],d['epoch'],end))]
            prices=[x for x in prices if x is not None]
            if not prices or not d['price']:continue
            p0=float(d['price']); fav=(max(prices)-p0)/p0*100; adv=(min(prices)-p0)/p0*100
            action=str(d.get('action') or '').upper()
            signed_fav=fav if ('BUY' in action or 'CE' in action) else -adv if ('SELL' in action or 'PE' in action) else max(fav,-adv)
            signed_adv=adv if ('BUY' in action or 'CE' in action) else -fav if ('SELL' in action or 'PE' in action) else min(fav,adv)
            oc='ON-TIME' if signed_fav>=1 and abs(signed_adv)<1 else 'EARLY' if signed_fav>=1 and abs(signed_adv)>=1 else 'FALSE BREAKOUT' if signed_adv<=-1 else 'NO FOLLOW-THROUGH'
            c.execute('UPDATE detections_v66 SET outcome_class=?,max_favourable_pct=?,max_adverse_pct=?,evaluated_epoch=? WHERE id=?',(oc,round(signed_fav,3),round(signed_adv,3),now,d['id'])); updated+=1
        c.commit()
    return {'evaluated':updated}

def missed_move_audit(minutes=390,threshold_pct=2.0):
    cutoff=time.time()-minutes*60
    with _db() as c:
        syms=[x[0] for x in c.execute('SELECT DISTINCT symbol FROM metric_snapshots_v66 WHERE epoch>=?',(cutoff,))]
        det={x[0] for x in c.execute('SELECT DISTINCT symbol FROM detections_v66 WHERE epoch>=?',(cutoff,))}
        out=[]
        for s in syms:
            p=[_f(x[0]) for x in c.execute('SELECT price FROM metric_snapshots_v66 WHERE symbol=? AND epoch>=? AND price IS NOT NULL ORDER BY epoch',(s,cutoff))]; p=[x for x in p if x]
            if len(p)<2:continue
            move=(max(p)-min(p))/min(p)*100
            if move>=threshold_pct:out.append({'symbol':s,'range_move_pct':round(move,2),'detected':s in det,'classification':'COVERED' if s in det else 'MISSED'})
    out.sort(key=lambda x:x['range_move_pct'],reverse=True)
    return {'threshold_pct':threshold_pct,'rows':out,'missed':sum(1 for x in out if not x['detected']),'covered':sum(1 for x in out if x['detected'])}

def replay(symbol:str,minutes=390,speed=10):
    h=metric_history(symbol,minutes,5000)['rows']
    points=[]; prev=None
    for r in h:
        state='OBSERVE'
        if (_f(r.get('rvol')) or 0)>=1.5 and (_f(r.get('change_pct')) or 0)>=1:state='MOMENTUM'
        if (_f(r.get('rvol')) or 0)>=2 and (_f(r.get('futures_oi_change_pct')) or 0)>=3:state='TRIGGER READY'
        points.append({'epoch':r['epoch'],'price':r['price'],'rvol':r['rvol'],'oi_change_pct':r['futures_oi_change_pct'],'sector_score':r['sector_score'],'state':state,'transition':state!=prev}); prev=state
    return {'symbol':symbol.upper(),'speed':speed,'points':points,'count':len(points),'truth':'Replay uses only stored point-in-time observations; missing history remains missing.'}

def expiry_intelligence(snap:dict):
    now=datetime.now(timezone.utc); chain=snap.get('option_chain') or []
    exp=str(snap.get('expiry') or snap.get('selected_expiry') or '')
    is_expiry=False
    try:is_expiry=datetime.fromisoformat(exp[:10]).date()==now.date()
    except:pass
    atm_iv=[]; gammas=[]; thetas=[]
    if isinstance(chain,list):
        for x in chain:
            if not isinstance(x,dict):continue
            for k in ('ce','pe'):
                d=x.get(k) if isinstance(x.get(k),dict) else {}
                if _f(d.get('iv')) is not None:atm_iv.append(_f(d['iv']))
                if _f(d.get('gamma')) is not None:gammas.append(abs(_f(d['gamma'])))
                if _f(d.get('theta')) is not None:thetas.append(abs(_f(d['theta'])))
    return {'expiry':exp or None,'is_expiry_day':is_expiry,'gamma_concentration':round(max(gammas),6) if gammas else None,'theta_intensity':round(sum(thetas)/len(thetas),6) if thetas else None,'mean_iv':round(sum(atm_iv)/len(atm_iv),3) if atm_iv else None,'mode':'EXPIRY RISK' if is_expiry else 'NORMAL','guard':'Tighten false-breakout filters on expiry day; this is risk context, not a directional signal.'}

def provenance_status():
    now=time.time()
    with _db() as c:
        cnt=c.execute('SELECT COUNT(*) FROM metric_snapshots_v66').fetchone()[0]; syms=c.execute('SELECT COUNT(DISTINCT symbol) FROM metric_snapshots_v66').fetchone()[0]; last=c.execute('SELECT MAX(epoch) FROM metric_snapshots_v66').fetchone()[0]
        oc=[dict(x) for x in c.execute('SELECT outcome_class,COUNT(*) n FROM detections_v66 WHERE outcome_class IS NOT NULL GROUP BY outcome_class')]
    return {'metric_rows':cnt,'symbols':syms,'last_snapshot_epoch':last,'age_seconds':round(now-last,1) if last else None,'outcomes':oc,'db_path':str(DB_PATH),'durability':'DURABLE only when deployment storage itself is persistent.'}

def build_v66(snap:dict, previous:dict|None=None):
    rec=record_snapshot(snap)
    evaluate_outcomes()
    rows=_sym_rows(snap)
    focus=[]
    for r in sorted(rows,key=lambda x:abs(_f(x.get('change_pct')) or 0),reverse=True)[:20]:
        s=str(r.get('symbol') or '').upper()
        if s:focus.append({'symbol':s,'windows':_window_metrics(s)})
    return {'version':'66.0','name':'Historical Intelligence, Replay & Self-Learning OS','recording':rec,'provenance':provenance_status(),'sector_rotation':sector_rotation(60),'option_migration':option_migration(str(snap.get('underlying') or 'NIFTY'),60),'expiry_intelligence':expiry_intelligence(snap),'missed_move_audit':missed_move_audit(390,2.0),'focus_history':focus,'chart_workspace':chart_workspace(focus[0]['symbol'],390) if focus else {'points':[],'symbol':None},'modules':{'normalized_time_series':True,'1_3_5_15_30_60m_deltas':True,'sector_rotation_history':True,'option_oi_pcr_iv_migration':True,'point_in_time_replay':True,'automatic_outcome_labelling':True,'missed_move_audit':True,'expiry_risk_mode':True,'telemetry_provenance':True,'shadow_ab_scaffold':True},'truth_policy':['No missing history is fabricated.','Replay uses only data that was stored at that historical timestamp.','Outcome labels measure subsequent price behavior, not profit probability.','Institution identity still requires explicit verified disclosures.'],'previous_version':(previous or {}).get('version')}

def chart_workspace(symbol:str, minutes=390):
    h=metric_history(symbol,minutes,5000)['rows']
    pts=[]
    prices=[]; vols=[]
    cum_pv=0.0; cum_v=0.0
    for r in h:
        px=_f(r.get('price')); vol=_f(r.get('volume'))
        if px is not None: prices.append(px)
        if vol is not None: vols.append(vol)
        if px is not None and vol is not None and vol>=0:
            cum_pv+=px*vol; cum_v+=vol
        vw=cum_pv/cum_v if cum_v>0 else _f(r.get('vwap'))
        pts.append({'epoch':r['epoch'],'price':px,'vwap':round(vw,4) if vw is not None else None,'rvol':_f(r.get('rvol')),'oi_change_pct':_f(r.get('futures_oi_change_pct')),'iv':_f(r.get('iv')),'sector_score':_f(r.get('sector_score'))})
    support=min(prices) if prices else None; resistance=max(prices) if prices else None
    return {'symbol':symbol.upper(),'minutes':minutes,'points':pts,'overlays':{'session_vwap':pts[-1]['vwap'] if pts else None,'observed_support':support,'observed_resistance':resistance},'panels':['PRICE+VWAP','RVOL','FUTURES OI Δ%','IV','SECTOR SCORE'],'truth':'Observed support/resistance are range extrema in stored history, not predictive levels.'}
