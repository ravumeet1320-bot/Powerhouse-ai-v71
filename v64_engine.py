from __future__ import annotations

import json, math, os, sqlite3, time
from pathlib import Path
from typing import Any

from v62_engine import _f, _pct, _symbol_rows, history
from v63_engine import strongest_sector_today, _sector_name, _change

ROOT = Path(__file__).parent
DB_PATH = Path(os.getenv('POWERHOUSE_DB_PATH') or (ROOT / '.runtime' / 'powerhouse_v62.sqlite3'))

SCHEMA = '''
CREATE TABLE IF NOT EXISTS institutional_activity(
 id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, trade_date TEXT,
 participant TEXT NOT NULL, segment TEXT NOT NULL, buy_value REAL, sell_value REAL,
 net_value REAL, source TEXT, verified INTEGER DEFAULT 0, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_inst_activity_date ON institutional_activity(trade_date,participant,segment);
CREATE TABLE IF NOT EXISTS institutional_holdings(
 id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, as_of TEXT NOT NULL,
 symbol TEXT NOT NULL, category TEXT NOT NULL, holding_pct REAL,
 shares REAL, source TEXT, verified INTEGER DEFAULT 0, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_inst_hold_symbol_cat ON institutional_holdings(symbol,category,as_of);
CREATE TABLE IF NOT EXISTS participant_oi(
 id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, trade_date TEXT,
 participant TEXT NOT NULL, segment TEXT NOT NULL, long_contracts REAL,
 short_contracts REAL, net_contracts REAL, source TEXT, verified INTEGER DEFAULT 0, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_part_oi_date ON participant_oi(trade_date,participant,segment);
CREATE TABLE IF NOT EXISTS institutional_deals(
 id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, trade_date TEXT,
 symbol TEXT NOT NULL, entity TEXT, deal_type TEXT, side TEXT, quantity REAL,
 price REAL, value REAL, category TEXT, source TEXT, verified INTEGER DEFAULT 0, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_inst_deals_symbol_date ON institutional_deals(symbol,trade_date);
'''

def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con=sqlite3.connect(DB_PATH,timeout=8)
    con.row_factory=sqlite3.Row
    con.executescript(SCHEMA)
    return con

def _norm_participant(v:str)->str:
    s=str(v or '').strip().upper().replace('FOREIGN INSTITUTIONAL INVESTOR','FII').replace('FOREIGN PORTFOLIO INVESTOR','FPI')
    aliases={'FIIS':'FII','DIIS':'DII','PROPRIETARY':'PRO','PROPRIETARY TRADERS':'PRO','MUTUAL FUNDS':'MF','MUTUAL FUND':'MF'}
    return aliases.get(s,s)

def ingest_institutional(payload:dict[str,Any])->dict[str,Any]:
    """Store only explicitly supplied institutional records. `verified` must be supplied by caller/source adapter.

    Supported type: activity, holding, participant_oi, deal. This endpoint never infers participant identity
    from anonymous order book, price or volume.
    """
    typ=str(payload.get('type') or '').strip().lower()
    rows=payload.get('rows') or []
    if isinstance(rows,dict): rows=[rows]
    if typ not in {'activity','holding','participant_oi','deal'}: raise ValueError('type must be activity, holding, participant_oi, or deal')
    if not isinstance(rows,list): raise ValueError('rows must be a list')
    now=time.time(); inserted=0
    with _db() as con:
        for r in rows[:5000]:
            if not isinstance(r,dict): continue
            verified=1 if bool(r.get('verified',payload.get('verified',False))) else 0
            source=str(r.get('source') or payload.get('source') or '')
            raw=json.dumps(r,default=str,separators=(',',':'))
            if typ=='activity':
                part=_norm_participant(r.get('participant'))
                seg=str(r.get('segment') or 'CASH').upper(); td=str(r.get('trade_date') or r.get('date') or '')
                buy=_f(r.get('buy_value')); sell=_f(r.get('sell_value')); net=_f(r.get('net_value'))
                if net is None and buy is not None and sell is not None: net=buy-sell
                if not part: continue
                con.execute('INSERT INTO institutional_activity(epoch,trade_date,participant,segment,buy_value,sell_value,net_value,source,verified,payload) VALUES(?,?,?,?,?,?,?,?,?,?)',(now,td,part,seg,buy,sell,net,source,verified,raw)); inserted+=1
            elif typ=='holding':
                sym=str(r.get('symbol') or '').upper().strip(); cat=_norm_participant(r.get('category')); asof=str(r.get('as_of') or r.get('date') or '')
                hp=_f(r.get('holding_pct')); shares=_f(r.get('shares'))
                if not sym or not cat or not asof: continue
                con.execute('INSERT INTO institutional_holdings(epoch,as_of,symbol,category,holding_pct,shares,source,verified,payload) VALUES(?,?,?,?,?,?,?,?,?)',(now,asof,sym,cat,hp,shares,source,verified,raw)); inserted+=1
            elif typ=='participant_oi':
                part=_norm_participant(r.get('participant')); seg=str(r.get('segment') or '').upper(); td=str(r.get('trade_date') or r.get('date') or '')
                lo=_f(r.get('long_contracts')); sh=_f(r.get('short_contracts')); net=_f(r.get('net_contracts'))
                if net is None and lo is not None and sh is not None: net=lo-sh
                if not part or not seg: continue
                con.execute('INSERT INTO participant_oi(epoch,trade_date,participant,segment,long_contracts,short_contracts,net_contracts,source,verified,payload) VALUES(?,?,?,?,?,?,?,?,?,?)',(now,td,part,seg,lo,sh,net,source,verified,raw)); inserted+=1
            else:
                sym=str(r.get('symbol') or '').upper().strip(); td=str(r.get('trade_date') or r.get('date') or '')
                if not sym: continue
                qty=_f(r.get('quantity')); price=_f(r.get('price')); value=_f(r.get('value'))
                if value is None and qty is not None and price is not None: value=qty*price
                con.execute('INSERT INTO institutional_deals(epoch,trade_date,symbol,entity,deal_type,side,quantity,price,value,category,source,verified,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(now,td,sym,str(r.get('entity') or ''),str(r.get('deal_type') or 'BULK/BLOCK').upper(),str(r.get('side') or '').upper(),qty,price,value,_norm_participant(r.get('category')),source,verified,raw)); inserted+=1
        con.commit()
    return {'inserted':inserted,'type':typ,'read_only_market_execution':True,'truth':'Participant identity is stored only when supplied by an explicit source.'}

def cash_activity(limit:int=20):
    with _db() as con:
        rr=con.execute('SELECT trade_date,participant,segment,buy_value,sell_value,net_value,source,verified,epoch FROM institutional_activity ORDER BY COALESCE(trade_date,\'\') DESC,id DESC LIMIT ?', (max(1,min(limit,200)),)).fetchall()
    rows=[dict(x) for x in rr]
    latest={}
    for r in rows:
        k=(r['participant'],r['segment'])
        if k not in latest: latest[k]=r
    return {'status':'READY' if rows else 'UNAVAILABLE','latest':list(latest.values()),'history':rows,'policy':'Cash FII/DII totals are market-level aggregates; they do not identify which stock an institution bought.'}

def participant_positioning(limit:int=100):
    with _db() as con:
        rr=con.execute('SELECT trade_date,participant,segment,long_contracts,short_contracts,net_contracts,source,verified,epoch FROM participant_oi ORDER BY COALESCE(trade_date,\'\') DESC,id DESC LIMIT ?', (max(1,min(limit,500)),)).fetchall()
    rows=[dict(x) for x in rr]
    latest={}
    for r in rows:
        k=(r['participant'],r['segment'])
        if k not in latest: latest[k]=r
    out=[]
    for r in latest.values():
        lo=_f(r.get('long_contracts'),0) or 0; sh=_f(r.get('short_contracts'),0) or 0; total=lo+sh
        bias='NET LONG' if (r.get('net_contracts') or 0)>0 else ('NET SHORT' if (r.get('net_contracts') or 0)<0 else 'BALANCED')
        x=dict(r); x['bias']=bias; x['long_share_pct']=round(lo/total*100,1) if total else None; out.append(x)
    return {'status':'READY' if out else 'UNAVAILABLE','positions':out,'policy':'Participant-wise derivatives positioning is segment-level. It must not be converted into stock-level FII/DII identity without an explicit stock-level source.'}

def holding_changes(limit:int=100, verified_only:bool=True):
    where='WHERE verified=1' if verified_only else ''
    with _db() as con:
        rr=con.execute(f'SELECT as_of,symbol,category,holding_pct,shares,source,verified,epoch FROM institutional_holdings {where} ORDER BY symbol,category,as_of DESC,id DESC').fetchall()
    groups={}
    for r in rr:
        d=dict(r); groups.setdefault((d['symbol'],d['category']),[]).append(d)
    changes=[]
    for (sym,cat), arr in groups.items():
        # dedupe same as_of, then compare latest two reporting periods
        uniq=[]; seen=set()
        for x in arr:
            if x['as_of'] in seen: continue
            seen.add(x['as_of']); uniq.append(x)
            if len(uniq)>=2: break
        if not uniq: continue
        cur=uniq[0]; prev=uniq[1] if len(uniq)>1 else None
        hp=_f(cur.get('holding_pct')); php=_f(prev.get('holding_pct')) if prev else None
        delta=(hp-php) if hp is not None and php is not None else None
        direction='INCREASED' if delta is not None and delta>0 else ('DECREASED' if delta is not None and delta<0 else ('UNCHANGED' if delta==0 else 'BASELINE NEEDED'))
        changes.append({'symbol':sym,'category':cat,'as_of':cur['as_of'],'holding_pct':hp,'previous_as_of':prev['as_of'] if prev else None,'previous_holding_pct':php,'change_pp':round(delta,4) if delta is not None else None,'direction':direction,'source':cur['source'],'verified':bool(cur['verified'])})
    changes.sort(key=lambda x:abs(x['change_pp']) if x['change_pp'] is not None else -1,reverse=True)
    inc=[x for x in changes if x['direction']=='INCREASED'][:limit]; dec=[x for x in changes if x['direction']=='DECREASED'][:limit]
    return {'status':'READY' if changes else 'UNAVAILABLE','increased':inc,'decreased':dec,'all':changes[:max(limit,100)],'policy':'Holding changes are reporting-period changes (for example quarterly shareholding), not intraday buying.'}

def deal_footprints(limit:int=100):
    with _db() as con:
        rr=con.execute('SELECT trade_date,symbol,entity,deal_type,side,quantity,price,value,category,source,verified,epoch FROM institutional_deals ORDER BY COALESCE(trade_date,\'\') DESC,id DESC LIMIT ?', (max(1,min(limit,500)),)).fetchall()
    rows=[dict(x) for x in rr]
    by_symbol={}
    for r in rows:
        if not r.get('verified'): continue
        s=r['symbol']; b=by_symbol.setdefault(s,{'symbol':s,'buy_value':0.0,'sell_value':0.0,'deals':0,'entities':set()})
        val=_f(r.get('value'),0) or 0
        if str(r.get('side')).startswith('B'): b['buy_value']+=val
        elif str(r.get('side')).startswith('S'): b['sell_value']+=val
        b['deals']+=1
        if r.get('entity'): b['entities'].add(r['entity'])
    agg=[]
    for b in by_symbol.values():
        agg.append({'symbol':b['symbol'],'buy_value':b['buy_value'],'sell_value':b['sell_value'],'net_value':b['buy_value']-b['sell_value'],'deals':b['deals'],'entity_count':len(b['entities'])})
    agg.sort(key=lambda x:abs(x['net_value']),reverse=True)
    return {'status':'READY' if rows else 'UNAVAILABLE','recent_deals':rows,'symbol_footprints':agg,'policy':'Only verified bulk/block/deal records can be attributed to named entities.'}

def _candidate_row_score(r:dict[str,Any], sector_score:float=50.0):
    ch=_change(r) or 0; rv=_f(r.get('rvol')); oi_ch=_f(r.get('oi_change_pct'),_f(r.get('futures_oi_change_pct'))); ltp=_f(r.get('ltp') or r.get('last_price'))
    stage=str(r.get('stage') or r.get('breakout_stage') or 'WATCH').upper()
    stage_pts={'CONFIRMED':24,'TRIGGER READY':20,'ATTACKING':15,'EARLY MOVER':12,'BUILDING':8,'WATCH':2}.get(stage,4)
    rv_pts=0 if rv is None else max(-5,min(18,(rv-1)*12))
    oi_pts=0 if oi_ch is None else max(-8,min(12,oi_ch*1.5))
    momentum=max(-8,min(18,ch*5))
    score=max(0,min(100,sector_score*.28+stage_pts+rv_pts+oi_pts+momentum+15))
    return round(score,1),{'change_pct':round(ch,3),'rvol':rv,'oi_change_pct':oi_ch,'stage':stage,'ltp':ltp}

def sector_best_opportunities(market:dict[str,Any], n:int=8):
    sec=strongest_sector_today(market)
    lead=sec.get('strongest_sector') or {}
    leader=lead.get('sector')
    if not leader:return {'status':'UNAVAILABLE','reason':'Strongest sector unavailable'}
    rows=[]
    for r in _symbol_rows(market):
        if not isinstance(r,dict) or _sector_name(r)!=leader: continue
        sym=str(r.get('symbol') or r.get('tradingsymbol') or '').upper().strip()
        if not sym: continue
        score,ev=_candidate_row_score(r,_f(lead.get('sector_score'),50) or 50)
        # category separates already-extended leaders from earlier opportunities.
        ch=ev['change_pct']; rv=ev['rvol']; stage=ev['stage']
        if stage in {'TRIGGER READY','ATTACKING','BUILDING','EARLY MOVER'} and ch<4: bucket='ABOUT TO MOVE / SETTING UP'
        elif stage=='CONFIRMED' and ch<3.5: bucket='BREAKOUT CONFIRMED'
        elif ch>=4: bucket='ALREADY EXTENDED / CHASE RISK'
        elif rv is not None and rv>=1.8: bucket='HIGH RVOL'
        else: bucket='WATCH'
        rows.append({'symbol':sym,'sector':leader,'opportunity_score':score,'bucket':bucket,**ev,'action_candidate':r.get('final_action') or r.get('action') or 'WAIT','score_note':'Evidence score, not win probability.'})
    rows.sort(key=lambda x:x['opportunity_score'],reverse=True)
    top_gainer=(lead.get('top_gainer') or {}).get('symbol')
    return {'status':'READY' if rows else 'UNAVAILABLE','sector':leader,'sector_score':lead.get('sector_score'),'top_gainer':top_gainer,'best_opportunities':rows[:n],
            'about_to_move':[x for x in rows if x['bucket']=='ABOUT TO MOVE / SETTING UP'][:n],
            'breakout_ready':[x for x in rows if x['bucket']=='BREAKOUT CONFIRMED'][:n],
            'high_rvol':[x for x in rows if x['rvol'] is not None and x['rvol']>=1.8][:n],
            'oi_buildup':[x for x in rows if x['oi_change_pct'] is not None and x['oi_change_pct']>0][:n],
            'avoid':[x for x in rows if 'CHASE RISK' in x['bucket']][:n],
            'policy':'Top gainer and best opportunity are intentionally separate. A stock that has already run can be downgraded for chase risk.'}

def institutional_footprint_score(market:dict[str,Any], limit:int=30):
    """Stock-level footprint uses explicit holdings/deals for identity + anonymous market evidence separately."""
    hc=holding_changes(500); deals=deal_footprints(500)
    hmap={}
    for x in hc.get('all') or []:
        if x.get('change_pp') is None: continue
        hmap.setdefault(x['symbol'],[]).append(x)
    dmap={x['symbol']:x for x in deals.get('symbol_footprints') or []}
    mrows={str(r.get('symbol') or r.get('tradingsymbol') or '').upper():r for r in _symbol_rows(market) if isinstance(r,dict)}
    syms=set(hmap)|set(dmap)
    rows=[]
    for s in syms:
        verified_delta=sum((_f(x.get('change_pp'),0) or 0) for x in hmap.get(s,[]))
        d=dmap.get(s,{}); netdeal=_f(d.get('net_value'),0) or 0
        r=mrows.get(s,{})
        ch=_change(r); rv=_f(r.get('rvol')); oi=_f(r.get('oi_change_pct'),_f(r.get('futures_oi_change_pct')))
        # identity score only gets points from explicit holdings/deals; market evidence is separate confirmation.
        ident=max(-35,min(35,verified_delta*12))
        if netdeal: ident += max(-25,min(25, math.copysign(math.log10(abs(netdeal)+1)*2,netdeal)))
        market_ev=0
        if ch is not None: market_ev+=max(-10,min(10,ch*3))
        if rv is not None: market_ev+=max(-8,min(10,(rv-1)*6))
        if oi is not None: market_ev+=max(-8,min(10,oi))
        score=max(0,min(100,50+ident+market_ev*.35))
        rows.append({'symbol':s,'footprint_score':round(score,1),'verified_holding_change_pp':round(verified_delta,4),'verified_deal_net_value':round(netdeal,2),'market_confirmation':{'change_pct':ch,'rvol':rv,'futures_oi_change_pct':oi},'interpretation':'ACCUMULATION FOOTPRINT' if score>=62 else ('DISTRIBUTION FOOTPRINT' if score<=38 else 'MIXED / INSUFFICIENT')})
    rows.sort(key=lambda x:x['footprint_score'],reverse=True)
    return {'status':'READY' if rows else 'UNAVAILABLE','leaders':rows[:limit],'laggards':list(reversed(rows[-limit:])) if rows else [],
            'truth_policy':'Named FII/DII/FPI/MF/PRO identity is never inferred from anonymous price, volume, OI or order-book data. Identity requires explicit holdings/deal/participant source.'}

def build_v64(market:dict[str,Any], v63:dict[str,Any]|None=None):
    return {
      'version':'64.0','name':'Sector Opportunity + Institutional Footprints OS','read_only':True,
      'sector_opportunity':sector_best_opportunities(market),
      'cash_institutional_activity':cash_activity(),
      'participant_positioning':participant_positioning(),
      'holding_changes':holding_changes(),
      'bulk_block_footprints':deal_footprints(),
      'institutional_footprints':institutional_footprint_score(market),
      'implemented_now':['Strongest-sector best opportunity ranking','Top gainer vs about-to-move separation','Breakout-ready / high-RVOL / OI-buildup / chase-risk buckets','FII/DII cash activity store','FII/DII/PRO/CLIENT participant derivatives positioning store','FPI/DII/MF/insurance/promoter holding-change engine','Verified bulk/block deal footprint engine','Institutional footprint score with identity-safe separation from anonymous market evidence'],
      'truth_policy':['FII/DII cash totals do not reveal stock-level purchases.','Quarterly/shareholding changes are reporting-period changes, not intraday flows.','PRO/FII/DII derivatives positioning is segment-level unless a verified stock-level source explicitly says otherwise.','Anonymous order book, volume and OI never identify an institution.','No broker execution or guaranteed outcome claims.']
    }
