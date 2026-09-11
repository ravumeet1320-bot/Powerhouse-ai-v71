from __future__ import annotations

import json, math, os, sqlite3, statistics, time, urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
DB_PATH = Path(os.getenv('POWERHOUSE_DB_PATH') or (ROOT / '.runtime' / 'powerhouse_v62.sqlite3'))

SCHEMA = '''
CREATE TABLE IF NOT EXISTS market_ts(
 id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, symbol TEXT NOT NULL,
 ltp REAL, volume REAL, rvol REAL, oi REAL, pcr REAL, max_pain REAL, iv REAL,
 bid_qty REAL, ask_qty REAL, spread REAL, sector TEXT, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_market_ts_symbol_epoch ON market_ts(symbol, epoch DESC);
CREATE TABLE IF NOT EXISTS cross_market_ts(
 id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, market TEXT NOT NULL,
 price REAL, change_pct REAL, source TEXT, verified INTEGER DEFAULT 0, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_cross_market_name_epoch ON cross_market_ts(market, epoch DESC);
CREATE TABLE IF NOT EXISTS outcomes(
 id INTEGER PRIMARY KEY AUTOINCREMENT, epoch REAL NOT NULL, symbol TEXT, detected_epoch REAL,
 detected_price REAL, stage TEXT, action TEXT, horizon_min INTEGER, later_price REAL,
 move_pct REAL, label TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS config(k TEXT PRIMARY KEY, v TEXT, updated_epoch REAL);
'''

def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con=sqlite3.connect(DB_PATH,timeout=8)
    con.row_factory=sqlite3.Row
    con.executescript(SCHEMA)
    return con

def _f(v,d=None):
    try:
        x=float(v)
        return x if math.isfinite(x) else d
    except Exception:return d

def _pct(a,b):
    a=_f(a); b=_f(b)
    if a is None or b in (None,0): return None
    return (a-b)/b*100.0

def _median(xs):
    xs=[_f(x) for x in xs]; xs=[x for x in xs if x is not None]
    return statistics.median(xs) if xs else None

def _symbol_rows(market:dict[str,Any]):
    out=[]
    for key in ('fno_universe','sector_data','stocks','stock_rows'):
        v=market.get(key)
        if isinstance(v,list): out.extend(x for x in v if isinstance(x,dict))
    # index row
    if market.get('spot') is not None:
        out.append({'symbol':market.get('active_underlying') or 'NIFTY','ltp':market.get('spot'),'volume':market.get('volume'),'rvol':market.get('rvol'),'sector':'INDEX'})
    ded={}
    for r in out:
        s=str(r.get('symbol') or r.get('tradingsymbol') or '').strip().upper()
        if s: ded[s]=r
    return list(ded.values())

def _chain(market):
    c=market.get('option_data') or market.get('option_chain') or []
    return c if isinstance(c,list) else []

def _extract_depth(r):
    bid=_f(r.get('total_buy_quantity'),_f(r.get('bid_qty'),_f(r.get('buy_qty'))))
    ask=_f(r.get('total_sell_quantity'),_f(r.get('ask_qty'),_f(r.get('sell_qty'))))
    spread=_f(r.get('spread'))
    if spread is None:
        bp=_f(r.get('bid_price')); ap=_f(r.get('ask_price'))
        if bp is not None and ap is not None: spread=max(0,ap-bp)
    return bid,ask,spread

def persist_timeseries(market:dict[str,Any]):
    now=_f(market.get('last_tick_epoch'),time.time()) or time.time()
    rows=_symbol_rows(market)
    with _db() as con:
        for r in rows[:1000]:
            s=str(r.get('symbol') or r.get('tradingsymbol') or '').upper()
            if not s: continue
            bid,ask,spread=_extract_depth(r)
            con.execute('INSERT INTO market_ts(epoch,symbol,ltp,volume,rvol,oi,pcr,max_pain,iv,bid_qty,ask_qty,spread,sector,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(
              now,s,_f(r.get('ltp'),_f(r.get('last_price'))),_f(r.get('volume')),_f(r.get('rvol')),
              _f(r.get('oi'),_f(r.get('open_interest'))),_f(r.get('pcr')),_f(r.get('max_pain')),_f(r.get('iv')),
              bid,ask,spread,str(r.get('sector') or ''),json.dumps(r,default=str,separators=(',',':'))))
        # index-level chain metrics
        con.execute('INSERT INTO market_ts(epoch,symbol,ltp,volume,rvol,oi,pcr,max_pain,iv,bid_qty,ask_qty,spread,sector,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(
          now,str(market.get('active_underlying') or 'NIFTY').upper(),_f(market.get('spot')),None,None,None,_f(market.get('official_pcr')),_f(market.get('official_max_pain')),_f(market.get('iv_proxy')),None,None,None,'INDEX','{}'))
        # bounded ~ 7 trading days at moderate sampling
        con.execute('DELETE FROM market_ts WHERE id NOT IN (SELECT id FROM market_ts ORDER BY id DESC LIMIT 250000)')
    return {'stored_rows':len(rows)+1,'epoch':now,'db':str(DB_PATH.name)}

def history(symbol:str, seconds:int=3600, limit:int=500):
    cutoff=time.time()-seconds
    with _db() as con:
        rr=con.execute('SELECT epoch,ltp,volume,rvol,oi,pcr,max_pain,iv,bid_qty,ask_qty,spread,sector FROM market_ts WHERE symbol=? AND epoch>=? ORDER BY epoch ASC LIMIT ?', (symbol.upper(),cutoff,limit)).fetchall()
    return [dict(x) for x in rr]

def pivots_and_cpr(market):
    sc=market.get('session_context') or {}
    h=_f(sc.get('previous_day_high'),_f(sc.get('pdh')))
    l=_f(sc.get('previous_day_low'),_f(sc.get('pdl')))
    c=_f(sc.get('last_close'),_f(sc.get('previous_close')))
    if None in (h,l,c):
        return {'status':'UNAVAILABLE','reason':'Previous-day H/L/C not all supplied'}
    pivot=(h+l+c)/3; bc=(h+l)/2; tc=2*pivot-bc
    if tc<bc: tc,bc=bc,tc
    width_pct=(tc-bc)/pivot*100 if pivot else None
    return {'status':'READY','pivot':pivot,'bc':bc,'tc':tc,'cpr_width_pct':width_pct,
            'cpr_type':'NARROW' if width_pct is not None and width_pct<0.2 else ('WIDE' if width_pct is not None and width_pct>0.5 else 'NORMAL'),
            'r1':2*pivot-l,'s1':2*pivot-h,'r2':pivot+(h-l),'s2':pivot-(h-l),
            'camarilla_h3':c+(h-l)*1.1/4,'camarilla_h4':c+(h-l)*1.1/2,'camarilla_l3':c-(h-l)*1.1/4,'camarilla_l4':c-(h-l)*1.1/2}

def gap_opening_intel(market):
    sc=market.get('session_context') or {}
    o=_f(sc.get('day_open')); pc=_f(sc.get('last_close')); spot=_f(market.get('spot'))
    orh=_f(sc.get('opening_range_high')); orl=_f(sc.get('opening_range_low')); vwap=_f(market.get('vwap'))
    gp=_pct(o,pc)
    if gp is None: return {'status':'UNAVAILABLE'}
    gap='GAP UP' if gp>=0.25 else ('GAP DOWN' if gp<=-0.25 else 'FLAT')
    evidence=[]
    if spot is not None and o is not None: evidence.append('ABOVE OPEN' if spot>o else 'BELOW OPEN')
    if spot is not None and vwap is not None: evidence.append('ABOVE VWAP' if spot>vwap else 'BELOW VWAP')
    if spot is not None and orh is not None and spot>orh: evidence.append('ABOVE ORH')
    if spot is not None and orl is not None and spot<orl: evidence.append('BELOW ORL')
    accepted = ('ABOVE VWAP' in evidence and gap=='GAP UP') or ('BELOW VWAP' in evidence and gap=='GAP DOWN')
    failed = ('BELOW OPEN' in evidence and gap=='GAP UP') or ('ABOVE OPEN' in evidence and gap=='GAP DOWN')
    classification='ACCEPTED GAP / DRIVE' if accepted else ('FAILED GAP / RECLAIM RISK' if failed else 'UNCONFIRMED GAP')
    return {'status':'READY','gap_pct':gp,'gap_state':gap,'classification':classification,'evidence':evidence,'orh':orh,'orl':orl,'vwap':vwap}

def _candles(market):
    c=market.get('candles') or market.get('intraday_candles') or []
    if isinstance(c,dict):
        for k in ('5','5m','1','1m'):
            if isinstance(c.get(k),list): return c[k]
        return []
    return c if isinstance(c,list) else []

def volume_profile(market, bins=24):
    cs=_candles(market)
    pts=[]
    for x in cs:
        if not isinstance(x,dict): continue
        h=_f(x.get('high')); l=_f(x.get('low')); cl=_f(x.get('close')); v=_f(x.get('volume'))
        if None in (h,l,cl,v) or v<=0: continue
        pts.append(((h+l+cl)/3,v))
    if len(pts)<10: return {'status':'UNAVAILABLE','reason':'Need intraday candles with volume'}
    lo=min(p for p,_ in pts); hi=max(p for p,_ in pts)
    if hi<=lo:return {'status':'UNAVAILABLE','reason':'No price range'}
    step=(hi-lo)/bins; hist=[0.0]*bins
    for p,v in pts:
        i=min(bins-1,max(0,int((p-lo)/step))); hist[i]+=v
    poc_i=max(range(bins),key=lambda i:hist[i]); total=sum(hist); target=total*.70
    selected={poc_i}; cum=hist[poc_i]; left=poc_i-1; right=poc_i+1
    while cum<target and (left>=0 or right<bins):
        lv=hist[left] if left>=0 else -1; rv=hist[right] if right<bins else -1
        if rv>lv: selected.add(right); cum+=rv; right+=1
        else: selected.add(left); cum+=lv; left-=1
    centers=[lo+(i+.5)*step for i in range(bins)]
    hvn=[centers[i] for i in sorted(range(bins),key=lambda i:hist[i],reverse=True)[:3]]
    nonzero=[i for i,x in enumerate(hist) if x>0]
    lvn=[centers[i] for i in sorted(nonzero,key=lambda i:hist[i])[:3]]
    return {'status':'READY','poc':centers[poc_i],'vah':max(centers[i] for i in selected),'val':min(centers[i] for i in selected),'hvn':hvn,'lvn':lvn,'bins':bins,'coverage_pct':70}

def anchored_vwap(market):
    cs=_candles(market)
    if len(cs)<5:return {'status':'UNAVAILABLE','reason':'Need intraday candles'}
    def avwap(start):
        num=den=0.0
        for x in cs[start:]:
            if not isinstance(x,dict):continue
            h=_f(x.get('high')); l=_f(x.get('low')); c=_f(x.get('close')); v=_f(x.get('volume'))
            if None in (h,l,c,v) or v<=0:continue
            p=(h+l+c)/3; num+=p*v; den+=v
        return num/den if den else None
    highs=[_f(x.get('high')) if isinstance(x,dict) else None for x in cs]; lows=[_f(x.get('low')) if isinstance(x,dict) else None for x in cs]
    hi_i=max((i for i,x in enumerate(highs) if x is not None),key=lambda i:highs[i],default=0)
    lo_i=min((i for i,x in enumerate(lows) if x is not None),key=lambda i:lows[i],default=0)
    spot=_f(market.get('spot'))
    vals={'session':avwap(0),'swing_high_anchor':avwap(hi_i),'swing_low_anchor':avwap(lo_i)}
    vals['spot_vs_session']='ABOVE' if spot is not None and vals['session'] is not None and spot>vals['session'] else 'BELOW' if spot is not None and vals['session'] is not None else 'N/A'
    return {'status':'READY',**vals}

def compression_intel(market):
    cs=_candles(market)
    if len(cs)<8:return {'status':'UNAVAILABLE','reason':'Need >=8 candles'}
    ranges=[]
    for x in cs[-12:]:
        h=_f(x.get('high')) if isinstance(x,dict) else None; l=_f(x.get('low')) if isinstance(x,dict) else None
        if h is not None and l is not None:ranges.append(h-l)
    if len(ranges)<7:return {'status':'UNAVAILABLE'}
    last=ranges[-1]; prev7=ranges[-7:]
    nr7=last<=min(prev7); med=_median(ranges[:-1]); contraction=(last/med) if med else None
    score=0
    if nr7:score+=40
    if contraction is not None and contraction<.7:score+=35
    if contraction is not None and contraction<.5:score+=15
    return {'status':'READY','nr7':nr7,'range_contraction_ratio':contraction,'compression_score':min(100,score),'state':'TIGHT COMPRESSION' if score>=60 else ('BUILDING' if score>=30 else 'NORMAL')}

def option_dynamics(market):
    chain=_chain(market)
    rows=[]
    for r in chain:
        if not isinstance(r,dict):continue
        strike=_f(r.get('strike') or r.get('strike_price'))
        ce=r.get('ce') or r.get('call') or r.get('call_options') or r
        pe=r.get('pe') or r.get('put') or r.get('put_options') or r
        def g(obj,*names):
            if not isinstance(obj,dict):return None
            for n in names:
                if n in obj and obj[n] is not None:return _f(obj[n])
            return None
        rows.append({'strike':strike,'ce_oi':g(ce,'oi','open_interest','ce_oi'),'pe_oi':g(pe,'oi','open_interest','pe_oi'),'ce_vol':g(ce,'volume','ce_volume'),'pe_vol':g(pe,'volume','pe_volume'),'ce_iv':g(ce,'iv','implied_volatility','ce_iv'),'pe_iv':g(pe,'iv','implied_volatility','pe_iv'),'ce_ltp':g(ce,'ltp','last_price','ce_ltp'),'pe_ltp':g(pe,'ltp','last_price','pe_ltp')})
    valid=[r for r in rows if r['strike'] is not None]
    if not valid:return {'status':'UNAVAILABLE','reason':'Option chain unavailable'}
    cw=max(valid,key=lambda r:r['ce_oi'] or -1); pw=max(valid,key=lambda r:r['pe_oi'] or -1)
    ceoi=sum(r['ce_oi'] or 0 for r in valid); peoi=sum(r['pe_oi'] or 0 for r in valid)
    cevol=sum(r['ce_vol'] or 0 for r in valid); pevol=sum(r['pe_vol'] or 0 for r in valid)
    iv_skews=[(r['strike'],(r['pe_iv']-r['ce_iv'])) for r in valid if r['pe_iv'] is not None and r['ce_iv'] is not None]
    return {'status':'READY','call_wall':cw['strike'],'put_wall':pw['strike'],'oi_pcr':peoi/ceoi if ceoi else None,'volume_pcr':pevol/cevol if cevol else None,'iv_skew_median':_median([x[1] for x in iv_skews]),'strike_count':len(valid)}

def chain_migration(market):
    sym=str(market.get('active_underlying') or 'NIFTY').upper(); now=time.time()
    cur=option_dynamics(market)
    h=history(sym,3600,500)
    pcr_hist=[x for x in h if x.get('pcr') is not None]
    mp_hist=[x for x in h if x.get('max_pain') is not None]
    def delta(arr,key):
        return (arr[-1][key]-arr[0][key]) if len(arr)>=2 else None
    return {'status':'READY' if cur.get('status')=='READY' else 'PARTIAL','current':cur,'pcr_1h_change':delta(pcr_hist,'pcr'),'max_pain_1h_change':delta(mp_hist,'max_pain'),'history_points':len(h)}

def depth_persistence(market):
    rows=[]
    for r in _symbol_rows(market):
        s=str(r.get('symbol') or '').upper(); bid,ask,spread=_extract_depth(r)
        if not s or bid is None or ask is None or bid+ask<=0:continue
        hist=history(s,1800,120)
        imbs=[]
        for x in hist:
            b=_f(x.get('bid_qty')); a=_f(x.get('ask_qty'))
            if b is not None and a is not None and b+a>0:imbs.append((b-a)/(b+a)*100)
        cur=(bid-ask)/(bid+ask)*100
        rows.append({'symbol':s,'imbalance_pct':cur,'median_imbalance_pct':_median(imbs),'samples':len(imbs),'spread':spread,'persistence':'BUY' if len(imbs)>=3 and _median(imbs)>15 else ('SELL' if len(imbs)>=3 and _median(imbs)<-15 else 'NEUTRAL')})
    rows.sort(key=lambda x:abs(x['median_imbalance_pct'] or x['imbalance_pct']),reverse=True)
    return {'status':'READY' if rows else 'UNAVAILABLE','leaders':rows[:15],'policy':'Depth imbalance is evidence only; it does not identify institutions or prove spoofing.'}

def breadth_rotation(market):
    rows=_symbol_rows(market)
    vals=[]; sectors={}
    for r in rows:
        ch=_f(r.get('change_pct'),_pct(r.get('ltp'),r.get('prev_close') or r.get('previous_close')))
        if ch is None:continue
        sec=str(r.get('sector') or 'OTHER')
        vals.append(ch); sectors.setdefault(sec,[]).append(ch)
    if not vals:return {'status':'UNAVAILABLE'}
    adv=sum(x>0 for x in vals); dec=sum(x<0 for x in vals)
    secrows=[{'sector':s,'avg_change_pct':sum(xs)/len(xs),'advancers':sum(x>0 for x in xs),'decliners':sum(x<0 for x in xs),'count':len(xs)} for s,xs in sectors.items()]
    secrows.sort(key=lambda x:x['avg_change_pct'],reverse=True)
    return {'status':'READY','advance':adv,'decline':dec,'unchanged':len(vals)-adv-dec,'ad_ratio':adv/dec if dec else None,'breadth_pct':(adv-dec)/len(vals)*100,'sector_leaders':secrows[:6],'sector_laggards':secrows[-6:]}

def symbol_personality(market):
    out=[]
    for r in _symbol_rows(market)[:300]:
        s=str(r.get('symbol') or '').upper(); h=history(s,7*86400,500)
        prices=[x['ltp'] for x in h if x.get('ltp') is not None]; rvols=[x['rvol'] for x in h if x.get('rvol') is not None]; spreads=[x['spread'] for x in h if x.get('spread') is not None]
        if len(prices)<5:continue
        rets=[abs(_pct(prices[i],prices[i-1]) or 0) for i in range(1,len(prices))]
        out.append({'symbol':s,'samples':len(prices),'median_abs_move_pct':_median(rets),'median_rvol':_median(rvols),'median_spread':_median(spreads),'personality_ready':len(prices)>=30})
    return {'status':'READY' if out else 'BUILDING','symbols':out[:100],'note':'Baselines strengthen as live observations accumulate.'}

def _read_json_url(url, timeout=3):
    req=urllib.request.Request(url,headers={'User-Agent':'POWERHOUSE-AI/62 read-only analytics'})
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))

def _dig(obj,path):
    cur=obj
    for part in path.split('.'):
        if isinstance(cur,list): cur=cur[int(part)]
        elif isinstance(cur,dict): cur=cur.get(part)
        else:return None
    return cur

def _external_from_env(name,prefix):
    url=os.getenv(prefix+'_JSON_URL','').strip()
    if not url:return None
    price_path=os.getenv(prefix+'_PRICE_PATH','price')
    change_path=os.getenv(prefix+'_CHANGE_PCT_PATH','change_pct')
    try:
        obj=_read_json_url(url)
        price=_f(_dig(obj,price_path)); ch=_f(_dig(obj,change_path))
        if price is None:return {'market':name,'status':'UNAVAILABLE','reason':'Configured feed returned no numeric price','source':url}
        return {'market':name,'status':'LIVE','price':price,'change_pct':ch,'source':url,'verified':bool(os.getenv(prefix+'_VERIFIED','').lower() in {'1','true','yes'}),'epoch':time.time()}
    except Exception as exc:return {'market':name,'status':'UNAVAILABLE','reason':str(exc)[:140],'source':url}

def record_cross_market(market_name,price,change_pct=None,source='manual',verified=False,epoch=None,payload=None):
    p=_f(price)
    if p is None: raise ValueError('numeric price required')
    ep=_f(epoch,time.time()) or time.time()
    with _db() as con:
        con.execute('INSERT INTO cross_market_ts(epoch,market,price,change_pct,source,verified,payload) VALUES(?,?,?,?,?,?,?)',(ep,market_name.upper(),p,_f(change_pct),source,1 if verified else 0,json.dumps(payload or {},default=str,separators=(',',':'))))
    return {'market':market_name.upper(),'price':p,'change_pct':_f(change_pct),'source':source,'verified':bool(verified),'epoch':ep}

def latest_cross_market(name):
    with _db() as con:
        r=con.execute('SELECT epoch,market,price,change_pct,source,verified FROM cross_market_ts WHERE market=? ORDER BY epoch DESC LIMIT 1',(name.upper(),)).fetchone()
    return dict(r) if r else None

def cross_market_intel(market):
    # GIFT NIFTY requires a configured/licensed feed. Dow futures can also be supplied through a provider URL.
    feeds=[]
    for name,prefix in [('GIFT NIFTY','GIFT_NIFTY'),('DOW FUTURES','DOW_FUTURES')]:
        live=_external_from_env(name,prefix)
        if live and live.get('status')=='LIVE':
            try:record_cross_market(name,live['price'],live.get('change_pct'),live.get('source','configured'),live.get('verified',False),live.get('epoch'),live)
            except Exception:pass
            feeds.append(live)
        else:
            cached=latest_cross_market(name)
            if cached:
                age=time.time()-cached['epoch']; cached['status']='CACHED'; cached['age_sec']=age; feeds.append(cached)
            else:
                feeds.append(live or {'market':name,'status':'UNAVAILABLE','reason':f'Set {prefix}_JSON_URL (and JSON paths) or POST verified data to /api/v62/cross-market/ingest'})
    nifty=_f(market.get('spot'))
    out={'markets':feeds,'nifty_spot':nifty,'read_only':True,'truth_policy':'External markets are shown only from configured/cached sources; values are never fabricated.'}
    gift=next((x for x in feeds if x.get('market')=='GIFT NIFTY'),None); dow=next((x for x in feeds if x.get('market')=='DOW FUTURES'),None)
    if gift and _f(gift.get('change_pct')) is not None and dow and _f(dow.get('change_pct')) is not None:
        g=_f(gift['change_pct']); d=_f(dow['change_pct']);
        out['global_alignment']='RISK-ON ALIGNED' if g>0 and d>0 else ('RISK-OFF ALIGNED' if g<0 and d<0 else 'MIXED GLOBAL CUES')
    else: out['global_alignment']='INSUFFICIENT VERIFIED DATA'
    return out

def readiness(market, modules):
    flags={
      'full_fno_universe':bool(market.get('fno_universe') or market.get('sector_data')),
      'intraday_candles':len(_candles(market))>=10,
      'option_chain':len(_chain(market))>0,
      'pdh_pdl':pivots_and_cpr(market).get('status')=='READY',
      'volume_profile':modules['volume_profile'].get('status')=='READY',
      'anchored_vwap':modules['anchored_vwap'].get('status')=='READY',
      'depth_history':modules['depth_persistence'].get('status')=='READY',
      'cross_market_any':any(x.get('status') in {'LIVE','CACHED'} for x in modules['cross_market'].get('markets',[])),
      'gift_nifty':any(x.get('market')=='GIFT NIFTY' and x.get('status') in {'LIVE','CACHED'} for x in modules['cross_market'].get('markets',[])),
      'dow_futures':any(x.get('market')=='DOW FUTURES' and x.get('status') in {'LIVE','CACHED'} for x in modules['cross_market'].get('markets',[])),
    }
    ready=sum(flags.values()); total=len(flags)
    return {'checks':flags,'ready':ready,'total':total,'readiness_pct':round(ready/total*100,1)}

def build_v62(market:dict[str,Any], v60:dict[str,Any]|None=None, v61:dict[str,Any]|None=None):
    mem=persist_timeseries(market)
    modules={
      'pivots_cpr':pivots_and_cpr(market),
      'gap_opening':gap_opening_intel(market),
      'volume_profile':volume_profile(market),
      'anchored_vwap':anchored_vwap(market),
      'compression':compression_intel(market),
      'option_dynamics':option_dynamics(market),
      'chain_migration':chain_migration(market),
      'depth_persistence':depth_persistence(market),
      'breadth_rotation':breadth_rotation(market),
      'symbol_personality':symbol_personality(market),
      'cross_market':cross_market_intel(market),
      'multi_timeframe':multi_timeframe_intel(market),
      'regime_noise':regime_noise_intel(market),
      'iv_history':iv_history_intel(market),
      'futures_basis':futures_basis_intel(market),
      'exchange_risk_guards':exchange_risk_guards(market),
      'feed_telemetry':feed_telemetry(market),
      'automatic_outcome_audit':auto_outcome_audit(),
    }
    return {'version':'62.0','name':'Consolidated Market Intelligence & Global Futures OS','read_only':True,'memory':mem,'modules':modules,'readiness':readiness(market,modules),
      'implemented_now':['Persistent normalized market time-series','CPR + classic pivots + Camarilla','Gap/opening-drive context','Volume Profile POC/VAH/VAL/HVN/LVN when candles exist','Anchored VWAP from session/swing anchors','Compression/NR7 detector','Option OI/volume PCR + walls + IV skew','PCR/max-pain migration from stored history','Depth persistence and imbalance history','Breadth + sector rotation snapshot','Symbol personality baselines','GIFT NIFTY external-feed adapter/cache','Dow Futures external-feed adapter/cache','Global cue alignment','Multi-timeframe alignment','Regime/noise classification','IV rank/percentile as history accumulates','Futures basis when supplied','Exchange risk guard states','Feed freshness telemetry','Automatic subsequent-move outcome labeling','Provider/source truth states'],
      'external_dependencies':{'gift_nifty':'Requires configured legitimate NSE IX/broker/data-vendor JSON feed or verified ingest; never fabricated.','dow_futures':'Requires configured legitimate futures/data-vendor feed or verified ingest.','licensed_news':'Adapter not auto-connected without provider credentials.','permanent_cloud_db':'Set POWERHOUSE_DB_PATH on persistent disk or migrate SQLite schema to hosted DB.'},
      'truth_policy':['No automatic broker execution.','No guaranteed-profit or win-probability claims.','Unavailable external data remains UNAVAILABLE.','Order-book patterns are evidence only; no spoofing/institution identity claims.']}

def _series_for_tf(market, tf):
    ps=market.get('price_series') or {}
    arr=ps.get(str(tf)) or ps.get(f'{tf}m') or []
    vals=[]
    for x in arr:
        if isinstance(x,dict): v=_f(x.get('close'),_f(x.get('price'),_f(x.get('ltp'))))
        elif isinstance(x,(list,tuple)) and x: v=_f(x[-1])
        else: v=_f(x)
        if v is not None: vals.append(v)
    return vals

def multi_timeframe_intel(market):
    out={}; bulls=bears=0
    for tf in (1,3,5,15,30,60):
        vals=_series_for_tf(market,tf)
        if len(vals)<3: out[f'{tf}m']={'state':'UNAVAILABLE','samples':len(vals)}; continue
        fast=_median(vals[-3:]); slow=_median(vals[-min(10,len(vals)):]); mom=_pct(vals[-1],vals[-min(4,len(vals))])
        state='BULL' if fast is not None and slow is not None and fast>slow and (mom or 0)>=0 else ('BEAR' if fast is not None and slow is not None and fast<slow and (mom or 0)<=0 else 'MIXED')
        bulls+=state=='BULL'; bears+=state=='BEAR'; out[f'{tf}m']={'state':state,'samples':len(vals),'momentum_pct':mom,'last':vals[-1]}
    overall='BULLISH ALIGNMENT' if bulls>=3 and bulls>bears else ('BEARISH ALIGNMENT' if bears>=3 and bears>bulls else 'MIXED / WAIT')
    return {'status':'READY' if bulls+bears else 'UNAVAILABLE','overall':overall,'bullish_frames':bulls,'bearish_frames':bears,'frames':out}

def regime_noise_intel(market):
    vals=_series_for_tf(market,5) or _series_for_tf(market,3) or _series_for_tf(market,1)
    if len(vals)<8:return {'status':'UNAVAILABLE'}
    rets=[(_pct(vals[i],vals[i-1]) or 0) for i in range(1,len(vals))]
    direction=abs((vals[-1]-vals[0]))
    path=sum(abs(vals[i]-vals[i-1]) for i in range(1,len(vals)))
    efficiency=(direction/path) if path else 0
    flips=sum(1 for i in range(1,len(rets)) if rets[i]*rets[i-1]<0)
    flip_ratio=flips/max(1,len(rets)-1)
    noise=max(0,min(100,(1-efficiency)*65+flip_ratio*35))
    regime='TRENDING' if efficiency>=.55 and noise<55 else ('CHOPPY' if noise>=65 else 'TRANSITIONAL')
    return {'status':'READY','regime':regime,'efficiency_ratio':efficiency,'sign_flip_ratio':flip_ratio,'noise_score':noise}

def iv_history_intel(market):
    sym=str(market.get('active_underlying') or 'NIFTY').upper(); cur=_f(market.get('iv_proxy'))
    h=history(sym,30*86400,2000); vals=[_f(x.get('iv')) for x in h]; vals=[x for x in vals if x is not None]
    if cur is None and vals: cur=vals[-1]
    if cur is None:return {'status':'UNAVAILABLE','reason':'Current IV unavailable'}
    if len(vals)<20:return {'status':'BUILDING','current_iv':cur,'samples':len(vals),'reason':'Need >=20 historical IV observations for rank/percentile'}
    lo=min(vals); hi=max(vals); rank=((cur-lo)/(hi-lo)*100) if hi>lo else 50
    pct=sum(x<=cur for x in vals)/len(vals)*100
    return {'status':'READY','current_iv':cur,'iv_rank':rank,'iv_percentile':pct,'samples':len(vals),'range_low':lo,'range_high':hi}

def futures_basis_intel(market):
    spot=_f(market.get('spot')); fut=_f(market.get('futures_price'),_f(market.get('future_ltp')))
    if spot is None or fut is None:return {'status':'UNAVAILABLE','reason':'Spot/futures pair not supplied'}
    basis=fut-spot; bp=basis/spot*100 if spot else None
    return {'status':'READY','spot':spot,'future':fut,'basis_points':basis,'basis_pct':bp,'state':'PREMIUM' if basis>0 else ('DISCOUNT' if basis<0 else 'FLAT')}

def exchange_risk_guards(market):
    guards={
      'fno_ban':market.get('fno_ban_status') or 'UNAVAILABLE',
      'asm_gsm':market.get('asm_gsm_status') or 'UNAVAILABLE',
      'circuit_limits':market.get('circuit_limits') or 'UNAVAILABLE',
      'freeze_quantity':market.get('freeze_quantity') or 'UNAVAILABLE',
      'special_session':market.get('special_session') or 'UNAVAILABLE',
    }
    return {'status':'READY' if any(v!='UNAVAILABLE' for v in guards.values()) else 'UNAVAILABLE','guards':guards,'policy':'Missing exchange-risk data does not default to safe.'}

def feed_telemetry(market):
    now=time.time(); tick=_f(market.get('last_tick_epoch')); age=(now-tick) if tick else None
    ws=market.get('websocket_connected')
    return {'status':'READY','websocket_connected':ws,'last_tick_age_sec':age,'stale':age is None or age>30,'provider_error':market.get('websocket_error'),'source':market.get('source'),'note':'Dropped-message and p95 latency require provider/event instrumentation; not invented.'}

def auto_outcome_audit(horizon_min=15, threshold_pct=0.6):
    now=time.time(); cutoff=now-horizon_min*60
    with _db() as con:
        old=con.execute("SELECT id,epoch,symbol,ltp,payload FROM market_ts WHERE epoch<=? AND ltp IS NOT NULL ORDER BY epoch DESC LIMIT 500",(cutoff,)).fetchall()
        made=0
        for r in old:
            already=con.execute('SELECT 1 FROM outcomes WHERE detected_epoch=? AND symbol=? AND horizon_min=? LIMIT 1',(r['epoch'],r['symbol'],horizon_min)).fetchone()
            if already:continue
            cur=con.execute('SELECT epoch,ltp FROM market_ts WHERE symbol=? AND epoch>? AND ltp IS NOT NULL ORDER BY epoch DESC LIMIT 1',(r['symbol'],r['epoch'])).fetchone()
            if not cur:continue
            mv=_pct(cur['ltp'],r['ltp'])
            if mv is None:continue
            payload={}
            try:payload=json.loads(r['payload'] or '{}')
            except Exception:pass
            action=str(payload.get('final_action') or payload.get('action') or 'WAIT').upper(); stage=str(payload.get('stage') or 'OBSERVED')
            directional=mv if action in {'BUY','BUY CE'} else (-mv if action in {'SELL','BUY PE'} else abs(mv))
            if action=='WAIT': label='MISSED_MOVE_CANDIDATE' if abs(mv)>=threshold_pct else 'CORRECT_WAIT'
            else: label='FOLLOW_THROUGH' if directional>=threshold_pct else ('FAILED_SIGNAL' if directional<=-threshold_pct else 'NO_DECISIVE_MOVE')
            con.execute('INSERT INTO outcomes(epoch,symbol,detected_epoch,detected_price,stage,action,horizon_min,later_price,move_pct,label,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(now,r['symbol'],r['epoch'],r['ltp'],stage,action,horizon_min,cur['ltp'],mv,label,'{}'))
            made+=1
        con.commit()
        dist={x['label']:x['c'] for x in con.execute('SELECT label,COUNT(*) c FROM outcomes GROUP BY label').fetchall()}
        total=sum(dist.values())
    return {'status':'READY','generated_now':made,'total_labeled':total,'label_counts':dist,'horizon_min':horizon_min,'threshold_pct':threshold_pct,'note':'Outcome labels measure subsequent price behavior, not P&L or win probability.'}
