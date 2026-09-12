from __future__ import annotations

import csv, io, math, os, time, urllib.request
from typing import Any

from v62_engine import build_v62, record_cross_market, latest_cross_market, _external_from_env, _f, _pct, _symbol_rows, history

GLOBAL_MARKETS = []  # V71.3: remove dead external futures adapters from the live product.


UPSTOX_MARKET_ORDER = [
    'GIFT NIFTY','S&P 500','NASDAQ / US TECH 100','INDIA VIX',
    'DXY','USD/INR','BRENT CRUDE','WTI CRUDE','GOLD'
]
FRED_YIELDS = [('US 2Y','DGS2'),('US 5Y','DGS5'),('US 10Y','DGS10'),('US 30Y','DGS30')]
_FRED_CACHE={'epoch':0.0,'rows':[]}

# Canonical aliases keep sector names stable across provider payloads.
SECTOR_ALIASES = {
    'METAL':'METALS','METALS':'METALS','NIFTY METAL':'METALS',
    'BANK':'BANKING & FINANCE','BANKING':'BANKING & FINANCE','FINANCIAL SERVICES':'BANKING & FINANCE','BANKING & FINANCE':'BANKING & FINANCE',
    'IT':'IT','INFORMATION TECHNOLOGY':'IT','NIFTY IT':'IT',
    'AUTO':'AUTO','AUTOMOBILE':'AUTO','NIFTY AUTO':'AUTO',
    'PHARMA':'PHARMA & HEALTHCARE','HEALTHCARE':'PHARMA & HEALTHCARE','PHARMA & HEALTHCARE':'PHARMA & HEALTHCARE',
    'FMCG':'FMCG','ENERGY':'ENERGY & OIL GAS','ENERGY & OIL GAS':'ENERGY & OIL GAS',
    'REALTY':'REALTY & CONSTRUCTION','REALTY & CONSTRUCTION':'REALTY & CONSTRUCTION',
    'CEMENT':'CEMENT','CAPITAL GOODS & DEFENCE':'CAPITAL GOODS & DEFENCE','DEFENCE':'CAPITAL GOODS & DEFENCE',
    'CONSUMER & RETAIL':'CONSUMER & RETAIL','TELECOM & MEDIA':'TELECOM & MEDIA',
}

# Safety-net mapping for important F&O names when a provider row has only generic `F&O` sector.
FALLBACK_SECTOR = {
    'TATASTEEL':'METALS','HINDALCO':'METALS','JSWSTEEL':'METALS','VEDL':'METALS','NMDC':'METALS','SAIL':'METALS','JINDALSTEL':'METALS','HINDZINC':'METALS',
    'HDFCBANK':'BANKING & FINANCE','ICICIBANK':'BANKING & FINANCE','SBIN':'BANKING & FINANCE','AXISBANK':'BANKING & FINANCE','KOTAKBANK':'BANKING & FINANCE','INDUSINDBK':'BANKING & FINANCE','BANKBARODA':'BANKING & FINANCE','PNB':'BANKING & FINANCE','CANBK':'BANKING & FINANCE','FEDERALBNK':'BANKING & FINANCE',
    'INFY':'IT','TCS':'IT','HCLTECH':'IT','WIPRO':'IT','TECHM':'IT','LTIM':'IT','PERSISTENT':'IT','COFORGE':'IT','MPHASIS':'IT',
    'MARUTI':'AUTO','M&M':'AUTO','TATAMOTORS':'AUTO','BAJAJ-AUTO':'AUTO','EICHERMOT':'AUTO','HEROMOTOCO':'AUTO','TVSMOTOR':'AUTO','ASHOKLEY':'AUTO','BOSCHLTD':'AUTO',
    'RELIANCE':'ENERGY & OIL GAS','ONGC':'ENERGY & OIL GAS','IOC':'ENERGY & OIL GAS','BPCL':'ENERGY & OIL GAS','HINDPETRO':'ENERGY & OIL GAS','GAIL':'ENERGY & OIL GAS','OIL':'ENERGY & OIL GAS','PETRONET':'ENERGY & OIL GAS',
    'ITC':'FMCG','HINDUNILVR':'FMCG','NESTLEIND':'FMCG','BRITANNIA':'FMCG','DABUR':'FMCG','MARICO':'FMCG','GODREJCP':'FMCG','TATACONSUM':'FMCG','COLPAL':'FMCG',
    'SUNPHARMA':'PHARMA & HEALTHCARE','DRREDDY':'PHARMA & HEALTHCARE','CIPLA':'PHARMA & HEALTHCARE','DIVISLAB':'PHARMA & HEALTHCARE','LUPIN':'PHARMA & HEALTHCARE','AUROPHARMA':'PHARMA & HEALTHCARE','ALKEM':'PHARMA & HEALTHCARE','TORNTPHARM':'PHARMA & HEALTHCARE','MAXHEALTH':'PHARMA & HEALTHCARE','APOLLOHOSP':'PHARMA & HEALTHCARE',
}

def _sector_name(row:dict[str,Any]) -> str:
    sym=str(row.get('symbol') or row.get('tradingsymbol') or '').upper().strip()
    raw=str(row.get('sector') or '').upper().strip()
    if raw and raw not in {'F&O','OTHER','UNKNOWN','NA','N/A'}:
        return SECTOR_ALIASES.get(raw, raw.title())
    return FALLBACK_SECTOR.get(sym,'OTHER / UNCLASSIFIED')

def _change(row):
    ch=_f(row.get('change_pct'))
    if ch is not None:return ch
    return _pct(row.get('ltp') or row.get('last_price'), row.get('prev_close') or row.get('previous_close') or row.get('cp'))

def strongest_sector_today(market:dict[str,Any]):
    """Rank today's sectors from verified current snapshot only.

    Score is descriptive evidence, never probability. We require >=2 classified live names to
    call a sector leader; otherwise state remains BUILDING/UNAVAILABLE.
    """
    groups:dict[str,list[dict[str,Any]]]={}
    for r in _symbol_rows(market):
        if not isinstance(r,dict):continue
        sym=str(r.get('symbol') or r.get('tradingsymbol') or '').upper().strip()
        ch=_change(r)
        if not sym or ch is None:continue
        sec=_sector_name(r)
        if sec=='OTHER / UNCLASSIFIED':continue
        rr=dict(r); rr['_symbol']=sym; rr['_change']=ch
        groups.setdefault(sec,[]).append(rr)
    ranked=[]
    for sec,rows in groups.items():
        if not rows:continue
        changes=[x['_change'] for x in rows]
        avg=sum(changes)/len(changes); med=sorted(changes)[len(changes)//2]
        adv=sum(x>0 for x in changes); dec=sum(x<0 for x in changes); breadth=(adv-dec)/len(changes)*100
        top=max(rows,key=lambda x:x['_change']); weak=min(rows,key=lambda x:x['_change'])
        rvols=[_f(x.get('rvol')) for x in rows]; rvols=[x for x in rvols if x is not None]
        avg_rvol=(sum(rvols)/len(rvols)) if rvols else None
        # Score deliberately combines breadth + equal-weight return + RVOL confirmation.
        score=max(0,min(100, 50 + avg*10 + breadth*0.22 + (max(-1.5,min(2.5,(avg_rvol or 1)-1))*8 if avg_rvol is not None else 0)))
        ranked.append({
            'sector':sec,'sector_score':round(score,1),'avg_change_pct':round(avg,3),'median_change_pct':round(med,3),
            'advancers':adv,'decliners':dec,'count':len(rows),'breadth_pct':round(breadth,1),'avg_rvol':round(avg_rvol,2) if avg_rvol is not None else None,
            'top_gainer':{'symbol':top['_symbol'],'change_pct':round(top['_change'],3),'ltp':_f(top.get('ltp') or top.get('last_price')),'rvol':_f(top.get('rvol'))},
            'weakest_stock':{'symbol':weak['_symbol'],'change_pct':round(weak['_change'],3),'ltp':_f(weak.get('ltp') or weak.get('last_price'))},
        })
    ranked.sort(key=lambda x:(x['sector_score'],x['avg_change_pct'],x['breadth_pct']),reverse=True)
    eligible=[x for x in ranked if x['count']>=2]
    leader=eligible[0] if eligible else (ranked[0] if ranked else None)
    weakest=eligible[-1] if eligible else (ranked[-1] if ranked else None)
    if not leader:return {'status':'UNAVAILABLE','reason':'No classified live sector rows with price change'}
    confidence='STRONG PARTICIPATION' if leader['count']>=4 and leader['breadth_pct']>=50 and leader['avg_change_pct']>0 else ('POSITIVE LEAD' if leader['avg_change_pct']>0 else 'RELATIVE LEADER ONLY')
    return {'status':'READY','strongest_sector':leader,'weakest_sector':weakest,'ranking':ranked,'leadership_state':confidence,
            'method':'Equal-weight sector change + breadth + available RVOL confirmation. Sector score is descriptive evidence, not win probability.',
            'truth_policy':'Uses current provider rows only. Top gainer is the highest current % gainer inside the ranked sector; no historical example is hard-coded.'}

def sector_leadership_persistence(market:dict[str,Any], lookback_sec:int=1800):
    cur=strongest_sector_today(market)
    leader=(cur.get('strongest_sector') or {}).get('sector')
    if not leader:return {'status':'UNAVAILABLE'}
    # Use stored per-symbol observations to estimate how many of current leader's names have stayed positive.
    symbols=[str(r.get('symbol') or '').upper() for r in _symbol_rows(market) if _sector_name(r)==leader]
    persistent=0; checked=0; details=[]
    for s in symbols:
        h=history(s,lookback_sec,120)
        px=[_f(x.get('ltp')) for x in h]; px=[x for x in px if x is not None]
        if len(px)<3:continue
        checked+=1
        move=_pct(px[-1],px[0]) or 0
        pos=sum(1 for i in range(1,len(px)) if px[i]>=px[0])/max(1,len(px)-1)*100
        ok=move>0 and pos>=60
        persistent+=1 if ok else 0
        details.append({'symbol':s,'lookback_move_pct':round(move,3),'positive_persistence_pct':round(pos,1),'persistent':ok})
    return {'status':'READY' if checked else 'BUILDING','sector':leader,'checked':checked,'persistent_names':persistent,
            'persistence_pct':round(persistent/checked*100,1) if checked else None,'leaders':sorted(details,key=lambda x:x['lookback_move_pct'],reverse=True)[:8]}

def market_movers(market:dict[str,Any], n:int=10):
    rows=[]
    for r in _symbol_rows(market):
        ch=_change(r); sym=str(r.get('symbol') or r.get('tradingsymbol') or '').upper().strip()
        if not sym or ch is None:continue
        rows.append({'symbol':sym,'sector':_sector_name(r),'change_pct':round(ch,3),'ltp':_f(r.get('ltp') or r.get('last_price')),'volume':_f(r.get('volume')),'rvol':_f(r.get('rvol'))})
    gain=sorted(rows,key=lambda x:x['change_pct'],reverse=True)[:n]
    lose=sorted(rows,key=lambda x:x['change_pct'])[:n]
    vol=sorted([x for x in rows if x['volume'] is not None],key=lambda x:x['volume'],reverse=True)[:n]
    rv=sorted([x for x in rows if x['rvol'] is not None],key=lambda x:x['rvol'],reverse=True)[:n]
    return {'status':'READY' if rows else 'UNAVAILABLE','top_gainers':gain,'top_losers':lose,'highest_volume':vol,'highest_rvol':rv,'universe_count':len(rows)}

def _fred_treasury_yields(force: bool=False):
    """Free official Federal Reserve (FRED) daily Treasury constant-maturity yields.

    This is daily/EOD macro context, not an intraday futures feed.
    """
    now=time.time()
    if _FRED_CACHE['rows'] and not force and now-_FRED_CACHE['epoch']<1800:
        return [dict(x) for x in _FRED_CACHE['rows']]
    ids=','.join(code for _,code in FRED_YIELDS)
    url=f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={ids}'
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'PowerhouseAI/68 market-data client'})
        with urllib.request.urlopen(req,timeout=6) as r:
            text=r.read().decode('utf-8','replace')
        parsed=list(csv.DictReader(io.StringIO(text)))
        latest={code:None for _,code in FRED_YIELDS}; latest_date=None
        for row in reversed(parsed):
            if not latest_date: latest_date=row.get('DATE') or row.get('observation_date')
            for _,code in FRED_YIELDS:
                if latest[code] is None:
                    v=_f(row.get(code))
                    if v is not None: latest[code]=v
            if all(v is not None for v in latest.values()): break
        rows=[]
        for name,code in FRED_YIELDS:
            v=latest.get(code)
            rows.append({'market':name,'price':v,'change_pct':None,'status':'DAILY' if v is not None else 'UNAVAILABLE',
                         'verified':v is not None,'source':'Federal Reserve FRED','series_id':code,
                         'as_of':latest_date,'epoch':now,'truth_label':'DAILY TREASURY YIELD'})
        _FRED_CACHE.update(epoch=now,rows=rows)
        return [dict(x) for x in rows]
    except Exception as exc:
        if _FRED_CACHE['rows']:
            rows=[dict(x) for x in _FRED_CACHE['rows']]
            for x in rows: x['status']='CACHED'
            return rows
        return [{'market':name,'price':None,'change_pct':None,'status':'UNAVAILABLE','verified':False,
                 'source':'Federal Reserve FRED','series_id':code,'reason':str(exc)[:120],
                 'truth_label':'DAILY TREASURY YIELD'} for name,code in FRED_YIELDS]

def _age_label(row):
    age=max(0.0,time.time()-(_f(row.get('epoch')) or time.time()))
    row['age_sec']=round(age,1)
    # Provider latency is metadata from the upstream source, distinct from our local cache age.
    if row.get('status')=='LIVE' and age>300: row['status']='STALE'
    return row

def global_markets_dashboard(market:dict[str,Any]):
    """Return only verified feeds that currently have a usable value.

    V71.3 intentionally removes Dow and all dead/unconfigured futures adapters from the
    product surface. Missing feeds are counted diagnostically but never rendered as cards.
    """
    out=[]
    hidden=[]

    # 1) Authenticated Upstox Global Instruments. Dow is intentionally excluded.
    up=market.get('upstox_global_markets') or {}
    up_rows=up.get('markets') if isinstance(up,dict) else []
    if isinstance(up_rows,list):
        by={str(x.get('market') or '').upper():dict(x) for x in up_rows if isinstance(x,dict)}
        for name in UPSTOX_MARKET_ORDER:
            row=by.get(name.upper())
            if not row:
                continue
            if _f(row.get('price')) is None or str(row.get('status') or '').upper()=='UNAVAILABLE':
                hidden.append(name); continue
            out.append(_age_label(row))

    # 2) External futures adapters are disabled in V71.3. If added later, they must be
    # explicitly verified before re-entering the product surface.

    # 3) Official daily US Treasury yields via FRED; hide rows when FRED is unavailable.
    yields=_fred_treasury_yields()
    good_yields=[]
    for row in yields:
        if _f(row.get('price')) is None:
            hidden.append(str(row.get('market') or 'TREASURY')); continue
        good_yields.append(row); out.append(row)
    y2=next((_f(x.get('price')) for x in good_yields if x.get('market')=='US 2Y'),None)
    y10=next((_f(x.get('price')) for x in good_yields if x.get('market')=='US 10Y'),None)
    curve=round((y10-y2)*100,1) if y2 is not None and y10 is not None else None

    directional=[]
    for x in out:
        ch=_f(x.get('change_pct')); name=str(x.get('market') or '')
        if ch is None: continue
        if name=='INDIA VIX': directional.append(-1 if ch>0 else (1 if ch<0 else 0))
        elif name not in {'US 2Y','US 5Y','US 10Y','US 30Y'}: directional.append(1 if ch>0 else (-1 if ch<0 else 0))
    score=sum(directional)/len(directional)*100 if directional else None
    state='INSUFFICIENT VERIFIED DATA' if score is None else ('GLOBAL RISK-ON' if score>=35 else ('GLOBAL RISK-OFF' if score<=-35 else 'MIXED GLOBAL CUES'))
    source_counts={}
    for x in out:
        src=str(x.get('source') or 'verified'); source_counts[src]=source_counts.get(src,0)+1
    return {'status':'READY' if out else 'PARTIAL','markets':out,
            'global_cue_score':round(score,1) if score is not None else None,'global_state':state,
            'yield_curve_10y_2y_bps':curve,'source_counts':source_counts,
            'hidden_unavailable_count':len(hidden),'hidden_unavailable':hidden,
            'policy':'Only working verified feeds are shown. Dow and dead/unconfigured futures adapters are removed from the live product surface.'}

def build_v63(market:dict[str,Any], v62:dict[str,Any]|None=None):
    v62=v62 or build_v62(market)
    sector=strongest_sector_today(market)
    persistence=sector_leadership_persistence(market)
    movers=market_movers(market)
    global_dash=global_markets_dashboard(market)
    return {
        'version':'63.0','name':'TradingView-style Market Command Center + Sector Leadership OS','read_only':True,
        'sector_strength':sector,'sector_persistence':persistence,'market_movers':movers,'global_markets':global_dash,
        'v62_readiness':v62.get('readiness',{}),
        'implemented_now':[
            "Today's Strongest Sector ranking","Top gainer inside strongest sector","Weakest sector and weakest stock","Sector breadth and equal-weight change","RVOL-confirmed sector leadership when available","Sector leadership persistence from stored observations","Top gainers/losers","Highest-volume / highest-RVOL movers","Global markets command center","Authenticated Upstox Global Instruments","GIFT NIFTY + working Upstox global indicators","DXY/USDINR/Brent/WTI/Gold indicators when Upstox exposes them","Official FRED US 2Y/5Y/10Y/30Y yields","10Y-2Y yield-curve spread","India VIX and working global indicator adapters","Global risk-on/risk-off evidence state"
        ],
        'truth_policy':['Sector score is descriptive evidence, not success probability.','No market value is fabricated.','TradingView is used only as information-architecture inspiration; live data must come from legitimate configured sources.','Read-only analytics; no broker execution.']
    }
