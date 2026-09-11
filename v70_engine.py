from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
DB_PATH = Path(os.getenv('POWERHOUSE_V70_DB_PATH') or (ROOT/'.runtime'/'powerhouse_v70.sqlite3'))

SCHEMA = '''
CREATE TABLE IF NOT EXISTS hero_snapshots_v70(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 epoch REAL NOT NULL,
 underlying TEXT NOT NULL,
 expiry TEXT,
 spot REAL,
 direction TEXT,
 hero_state TEXT,
 hero_score REAL,
 strike REAL,
 option_type TEXT,
 premium REAL,
 data_quality REAL,
 payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_v70_hero_u_epoch ON hero_snapshots_v70(underlying, epoch DESC);
CREATE TABLE IF NOT EXISTS hero_signals_v70(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 epoch REAL NOT NULL,
 underlying TEXT NOT NULL,
 signal_id TEXT NOT NULL,
 state TEXT,
 side TEXT,
 strike REAL,
 premium REAL,
 score REAL,
 invalidation REAL,
 ttl_seconds INTEGER,
 evidence TEXT,
 counter_evidence TEXT,
 payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_v70_signal_u_epoch ON hero_signals_v70(underlying, epoch DESC);
'''


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=8)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def _f(v, default=None):
    try:
        if v is None or v == '': return default
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def _mean(xs):
    xs=[_f(x) for x in xs]
    xs=[x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def _stdev(xs):
    xs=[_f(x) for x in xs]
    xs=[x for x in xs if x is not None]
    return statistics.pstdev(xs) if len(xs) >= 2 else None


def _pct(a,b):
    a=_f(a); b=_f(b)
    if a is None or b in (None,0): return None
    return (a-b)/abs(b)*100


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _series(snapshot:dict, minutes:int):
    ps=snapshot.get('price_series') or {}
    vals=ps.get(str(minutes)) or ps.get(minutes) or []
    return [_f(x) for x in vals if _f(x) is not None]


def _trend_score(vals:list[float]):
    if len(vals)<2: return 0.0
    base=max(abs(vals[0]),1e-9)
    ret=(vals[-1]-vals[0])/base*100
    mono=sum(1 if vals[i]>vals[i-1] else -1 if vals[i]<vals[i-1] else 0 for i in range(1,len(vals)))
    mono=mono/max(len(vals)-1,1)
    return _clamp(ret*75 + mono*28, -100, 100)


def _chain(snapshot:dict):
    rows=snapshot.get('option_data') or snapshot.get('option_chain') or []
    return [r for r in rows if isinstance(r,dict) and _f(r.get('s') or r.get('strike') or r.get('strike_price')) is not None]


def data_truth(snapshot:dict)->dict[str,Any]:
    rows=_chain(snapshot)
    now=time.time(); last=_f(snapshot.get('last_tick_epoch'))
    age=(now-last) if last else None
    ws=bool(snapshot.get('websocket_connected'))
    source=str(snapshot.get('source') or 'UNKNOWN')
    checks={
        'spot': _f(snapshot.get('spot')) is not None,
        'option_chain': len(rows)>=3,
        'greeks': any(abs(_f(r.get('c_gamma'),0) or 0)>0 or abs(_f(r.get('p_gamma'),0) or 0)>0 for r in rows),
        'bid_ask': any((_f(r.get('cbid')) or 0)>0 and (_f(r.get('cask')) or 0)>0 for r in rows),
        'oi': any((_f(r.get('coi')) or 0)>0 or (_f(r.get('poi')) or 0)>0 for r in rows),
        'price_history': any(len(_series(snapshot,m))>=2 for m in (3,5,15)),
        'websocket': ws,
        'fresh_tick': age is not None and age <= 30,
        'breadth': bool(snapshot.get('sector_heatmap') or snapshot.get('pitch') or snapshot.get('index_brain')),
        'global': bool(((snapshot.get('upstox_global_markets') or {}).get('markets'))),
    }
    # Do not make WS mandatory outside market hours; score breadth of evidence instead.
    weights={'spot':16,'option_chain':18,'greeks':12,'bid_ask':8,'oi':12,'price_history':12,'websocket':8,'fresh_tick':6,'breadth':5,'global':3}
    score=sum(weights[k] for k,v in checks.items() if v)
    freshness='LIVE' if ws and age is not None and age<=10 else 'STALE' if age is not None and age>60 else 'REST/DELAYED' if not ws else 'PARTIAL'
    if snapshot.get('demo'): freshness='DEMO'
    return {'score':round(score,1),'checks':checks,'source':source,'freshness':freshness,'last_tick_age_sec':round(age,1) if age is not None else None,
            'policy':'Missing/stale inputs reduce confidence or force NO TRADE; no fabricated live values.'}


def breadth_intelligence(snapshot:dict)->dict[str,Any]:
    rows=snapshot.get('sector_heatmap') or []
    live=[r for r in rows if _f(r.get('change_pct')) is not None]
    if not live:
        code=str(snapshot.get('active_underlying') or 'NIFTY')
        ib=(snapshot.get('index_brain') or {}).get(code) or {}
        live=[r for r in (ib.get('stocks') or []) if _f(r.get('change_pct')) is not None]
    if not live:
        return {'status':'UNAVAILABLE','score':0,'advance':0,'decline':0,'avg_change_pct':None,'acceleration':None}
    adv=sum(1 for r in live if _f(r.get('change_pct'),0)>0); dec=sum(1 for r in live if _f(r.get('change_pct'),0)<0)
    avg=_mean([r.get('change_pct') for r in live]) or 0
    score=_clamp((adv-dec)/max(len(live),1)*62 + avg*22,-100,100)
    bysec=defaultdict(list)
    for r in live: bysec[str(r.get('sector') or 'OTHER')].append(_f(r.get('change_pct'),0) or 0)
    secs=[{'sector':s,'avg_change_pct':round(_mean(v) or 0,3),'members':len(v)} for s,v in bysec.items()]
    secs.sort(key=lambda x:x['avg_change_pct'],reverse=True)
    return {'status':'READY','score':round(score,1),'advance':adv,'decline':dec,'total':len(live),'avg_change_pct':round(avg,3),'leaders':secs[:5],'laggards':list(reversed(secs[-5:]))}


def market_regime(snapshot:dict)->dict[str,Any]:
    spot=_f(snapshot.get('spot')); vwap=_f(snapshot.get('vwap'))
    t3=_trend_score(_series(snapshot,3)); t5=_trend_score(_series(snapshot,5)); t15=_trend_score(_series(snapshot,15))
    scores=[x for x in (t3,t5,t15) if x is not None]
    direction=_mean(scores) or 0
    agree=sum(1 for x in scores if x>15)-sum(1 for x in scores if x<-15)
    vol=[]
    for m in (3,5,15):
        vals=_series(snapshot,m)
        if len(vals)>=3:
            rets=[_pct(vals[i],vals[i-1]) or 0 for i in range(1,len(vals))]
            vol.extend(rets)
    rv=_stdev(vol) or 0
    vwdev=_pct(spot,vwap) if spot is not None and vwap else None
    sc=snapshot.get('session_context') or {}; hi=_f(sc.get('day_high')); lo=_f(sc.get('day_low'))
    location=None
    if spot is not None and hi is not None and lo is not None and hi>lo: location=(spot-lo)/(hi-lo)
    if abs(direction)>=52 and abs(agree)>=2: state='TREND'
    elif rv>=0.18: state='HIGH VOLATILITY'
    elif abs(direction)<=14: state='RANGE / CHOP'
    else: state='TRANSITION'
    side='BULL' if direction>15 else 'BEAR' if direction<-15 else 'NEUTRAL'
    return {'state':state,'side':side,'score':round(direction,1),'t3':round(t3,1),'t5':round(t5,1),'t15':round(t15,1),'realized_vol_proxy':round(rv,4),'vwap_deviation_pct':round(vwdev,3) if vwdev is not None else None,'day_location':round(location,3) if location is not None else None}


def option_chain_intelligence(snapshot:dict)->dict[str,Any]:
    rows=_chain(snapshot); spot=_f(snapshot.get('spot'))
    if not rows: return {'status':'UNAVAILABLE','rows':0}
    ceoi=sum(_f(r.get('coi'),0) or 0 for r in rows); peoi=sum(_f(r.get('poi'),0) or 0 for r in rows)
    ced=sum(_f(r.get('cchg'),0) or 0 for r in rows); ped=sum(_f(r.get('pchg'),0) or 0 for r in rows)
    pcr=peoi/ceoi if ceoi>0 else None
    call=max(rows,key=lambda r:_f(r.get('coi'),-1) or -1); put=max(rows,key=lambda r:_f(r.get('poi'),-1) or -1)
    call_d=max(rows,key=lambda r:_f(r.get('cchg'),-1e99) or -1e99); put_d=max(rows,key=lambda r:_f(r.get('pchg'),-1e99) or -1e99)
    atm=min(rows,key=lambda r:abs((_f(r.get('s')) or 0)-(spot or 0))) if spot is not None else rows[len(rows)//2]
    straddle=(_f(atm.get('cltp'),0) or 0)+(_f(atm.get('pltp'),0) or 0)
    ivs=[]
    for r in rows:
        for k in ('civ','piv'):
            v=_f(r.get(k))
            if v is not None and v>0: ivs.append(v)
    civ=[_f(r.get('civ')) for r in rows if _f(r.get('civ')) is not None]
    piv=[_f(r.get('piv')) for r in rows if _f(r.get('piv')) is not None]
    skew=(_mean(piv) or 0)-(_mean(civ) or 0) if civ and piv else None
    oi_balance=(ped-ced)/(abs(ped)+abs(ced)+1e-9)*100 if (ped or ced) else 0
    return {'status':'READY','rows':len(rows),'pcr':round(pcr,3) if pcr is not None else None,'ce_oi':round(ceoi,3),'pe_oi':round(peoi,3),'ce_doi':round(ced,3),'pe_doi':round(ped,3),
            'call_wall':_f(call.get('s')),'put_wall':_f(put.get('s')),'call_doi_wall':_f(call_d.get('s')),'put_doi_wall':_f(put_d.get('s')),
            'atm_strike':_f(atm.get('s')),'atm_straddle':round(straddle,2),'expected_move_proxy_points':round(straddle,2),'mean_iv':round(_mean(ivs),3) if ivs else None,'iv_skew_put_minus_call':round(skew,3) if skew is not None else None,
            'oi_balance_score':round(_clamp(oi_balance,-100,100),1),'max_pain':_f(snapshot.get('official_max_pain')),
            'truth':'ATM straddle is an intraday expected-move proxy, not a guaranteed range. OI is open contracts, not identified buyer/seller intent.'}


def global_risk(snapshot:dict)->dict[str,Any]:
    g=snapshot.get('upstox_global_markets') or {}; mk=g.get('markets') or []
    if not mk: return {'status':'UNAVAILABLE','state':'UNKNOWN','score':0,'markets':[]}
    vals=[]; out=[]
    for x in mk:
        ch=_f(x.get('change_pct'))
        name=str(x.get('market') or x.get('name') or x.get('label') or '')
        if ch is not None:
            w=1.0
            if any(q in name.upper() for q in ('DOW','S&P','NASDAQ','US TECH','GIFT NIFTY')): w=1.3
            vals.append(ch*w)
        out.append({'market':name,'price':_f(x.get('price') or x.get('ltp')),'change_pct':ch,'status':x.get('status'),'latency':x.get('latency'),'source':x.get('source')})
    score=_clamp((_mean(vals) or 0)*28,-100,100)
    return {'status':'READY' if vals else 'PARTIAL','state':'RISK ON' if score>18 else 'RISK OFF' if score<-18 else 'MIXED','score':round(score,1),'markets':out[:20]}


def master_decision(snapshot:dict)->dict[str,Any]:
    reg=market_regime(snapshot); chain=option_chain_intelligence(snapshot); br=breadth_intelligence(snapshot); glob=global_risk(snapshot)
    spot=_f(snapshot.get('spot')); vwap=_f(snapshot.get('vwap'))
    votes=[]
    def add(name,score,weight,evidence): votes.append({'name':name,'score':round(score,1),'weight':weight,'evidence':evidence})
    add('MTF PRICE',reg['score'],1.5,f"3/5/15 = {reg['t3']}/{reg['t5']}/{reg['t15']}")
    if spot is not None and vwap:
        vw=_clamp((_pct(spot,vwap) or 0)*150,-80,80); add('VWAP',vw,1.1,f"spot-vwap {(_pct(spot,vwap) or 0):.3f}%")
    if chain.get('status')=='READY':
        oi=_f(chain.get('oi_balance_score'),0) or 0; add('OI MIGRATION',oi,1.1,f"ΔOI balance {oi:.1f}")
        pcr=_f(chain.get('pcr'))
        if pcr is not None: add('PCR',_clamp((pcr-1)*90,-55,55),.7,f"PCR {pcr:.2f}")
    if br.get('status')=='READY': add('BREADTH',_f(br.get('score'),0) or 0,1.0,f"A {br['advance']} / D {br['decline']}")
    if glob.get('status') in ('READY','PARTIAL'): add('GLOBAL',_f(glob.get('score'),0) or 0,.45,glob.get('state'))
    den=sum(x['weight'] for x in votes) or 1; score=sum(x['score']*x['weight'] for x in votes)/den
    side='CE' if score>=22 else 'PE' if score<=-22 else 'WAIT'
    evidence=[x['evidence'] for x in votes if (score>=0 and x['score']>12) or (score<0 and x['score']<-12)]
    counter=[x['evidence'] for x in votes if (score>=0 and x['score']<-12) or (score<0 and x['score']>12)]
    return {'side':side,'score':round(_clamp(abs(score),0,100),1),'signed_score':round(score,1),'votes':votes,'evidence':evidence[:8],'counter_evidence':counter[:8],
            'conflict':len(counter)>=2,'policy':'One master thesis; conflicting engines reduce conviction rather than issuing opposite trades.'}


def _depth_stats(levels):
    if not isinstance(levels,list) or not levels: return {'levels':0,'imbalance':None,'persistence_proxy':None}
    bq=0; aq=0
    for x in levels[:30]:
        if not isinstance(x,dict): continue
        bq+=_f(x.get('bid_qty') or x.get('bidQ') or x.get('bid_quantity') or x.get('quantity'),0) or 0
        aq+=_f(x.get('ask_qty') or x.get('askQ') or x.get('ask_quantity'),0) or 0
    tot=bq+aq; imb=(bq-aq)/tot*100 if tot else None
    return {'levels':len(levels[:30]),'imbalance':round(imb,1) if imb is not None else None,'bid_qty':round(bq,2),'ask_qty':round(aq,2)}


def _candidate(snapshot:dict,row:dict,side:str,master:dict,chain:dict)->dict[str,Any]:
    isce=side=='CE'; pre='c' if isce else 'p'; strike=_f(row.get('s')); spot=_f(snapshot.get('spot'))
    ltp=_f(row.get(pre+'ltp')); bid=_f(row.get(pre+'bid')); ask=_f(row.get(pre+'ask')); oi=_f(row.get(pre+'oi')); doi=_f(row.get(pre+'chg')); vol=_f(row.get(pre+'vol'))
    iv=_f(row.get(pre+'iv')); delta=_f(row.get(pre+'_delta')); gamma=_f(row.get(pre+'_gamma')); theta=_f(row.get(pre+'_theta')); vega=_f(row.get(pre+'_vega'))
    v1=_f(row.get(pre+'v1')); v3=_f(row.get(pre+'v3')); v5=_f(row.get(pre+'v5')); oiv=_f(row.get(pre+'oivel')); prem=_f(row.get(pre+'prem'))
    spread=(ask-bid) if ask is not None and bid is not None else None; spread_pct=(spread/ltp*100) if spread is not None and ltp and ltp>0 else None
    dist=(strike-spot) if (strike is not None and spot is not None) else None
    directional_dist=max(0,dist) if isce and dist is not None else max(0,-dist) if dist is not None else None
    exp=_f(chain.get('expected_move_proxy_points')) or 0
    reach=100 if directional_dist is not None and directional_dist<=0 else _clamp((exp/max(directional_dist or 1,1))*48,0,100) if directional_dist is not None else 0
    absdelta=abs(delta or 0); gamma_abs=abs(gamma or 0); theta_abs=abs(theta or 0)
    gamma_score=_clamp(gamma_abs*(spot or 1)*850,0,100)
    delta_wakeup=_clamp(absdelta*115,0,100)
    theta_cost=_clamp((theta_abs/max(ltp or 1,1))*100*2.2,0,100) if theta is not None else 35
    liq=55
    if spread_pct is not None: liq+=25 if spread_pct<=2 else 12 if spread_pct<=5 else -15 if spread_pct>12 else 0
    if vol is not None: liq+=min(20,math.log10(max(vol,1))*3)
    liq=_clamp(liq)
    volsur=max([x for x in (v1,v3,v5) if x is not None],default=1.0); vol_score=_clamp((volsur-1)*45+45,0,100)
    oi_score=_clamp(50+(oiv or 0)*450 + (doi or 0)*2.5,0,100)
    prem_score=_clamp(50+(prem or 0)*18,0,100)
    levels=row.get('cdepth' if isce else 'pdepth') or []; depth=_depth_stats(levels); dimb=_f(depth.get('imbalance'))
    depth_score=50 if dimb is None else _clamp(50+(dimb if isce else dimb)*.5,0,100)
    side_align=100 if master.get('side')==side else 40 if master.get('side')=='WAIT' else 0
    opposite_prem=_f(row.get(('p' if isce else 'c')+'prem'))
    opp_confirm=_clamp(50-(opposite_prem or 0)*15,0,100)
    elasticity=_clamp(prem_score*.55+gamma_score*.45,0,100)
    raw=(side_align*.19+reach*.15+gamma_score*.12+delta_wakeup*.08+vol_score*.11+oi_score*.10+prem_score*.10+liq*.08+depth_score*.04+opp_confirm*.03)
    raw-=theta_cost*.08
    score=_clamp(raw)
    band='SAFETY' if directional_dist is not None and directional_dist<=0 else 'POWER' if reach>=60 else 'EXPLOSION' if (ltp or 999)<=40 and gamma_score>=35 else 'SPECULATIVE'
    evidence=[]; counter=[]
    for cond,text in [(reach>=65,'strike reachable vs ATM-straddle proxy'),(gamma_score>=55,'gamma sensitivity elevated'),(vol_score>=65,'volume acceleration'),(oi_score>=60,'OI flow supportive'),(prem_score>=62,'premium momentum/resurrection'),(liq>=72,'liquidity/spread acceptable'),(depth_score>=60,'depth pressure supportive'),(opp_confirm>=60,'opposite premium weakening')]:
        if cond:evidence.append(text)
    for cond,text in [(reach<35,'strike reachability weak'),(theta_cost>=65,'theta burn extreme'),(liq<50,'liquidity/spread weak'),(master.get('side') not in (side,'WAIT'),'master direction conflicts'),(spread_pct is not None and spread_pct>12,'spread too wide')]:
        if cond:counter.append(text)
    return {'strike':strike,'side':side,'premium':ltp,'bid':bid,'ask':ask,'spread_pct':round(spread_pct,2) if spread_pct is not None else None,'oi':oi,'oi_change':doi,'volume':vol,'iv':iv,'delta':delta,'gamma':gamma,'theta':theta,'vega':vega,
            'distance_points':round(directional_dist,2) if directional_dist is not None else None,'band':band,'reachability':round(reach,1),'gamma_score':round(gamma_score,1),'delta_wakeup':round(delta_wakeup,1),'theta_risk':round(theta_cost,1),'liquidity':round(liq,1),'volume_surprise':round(vol_score,1),'oi_flow':round(oi_score,1),'premium_momentum':round(prem_score,1),'premium_elasticity':round(elasticity,1),'depth':depth,'depth_score':round(depth_score,1),'opposite_confirmation':round(opp_confirm,1),'score':round(score,1),'evidence':evidence,'counter_evidence':counter}


def strike_ladder(snapshot:dict,master:dict|None=None,chain:dict|None=None)->dict[str,Any]:
    rows=_chain(snapshot); master=master or master_decision(snapshot); chain=chain or option_chain_intelligence(snapshot)
    if not rows: return {'status':'UNAVAILABLE','candidates':[]}
    cand=[]
    for r in rows:
        cand.append(_candidate(snapshot,r,'CE',master,chain)); cand.append(_candidate(snapshot,r,'PE',master,chain))
    # Reject zero/invalid premiums, but no arbitrary upper/lower premium cap.
    cand=[x for x in cand if x.get('premium') is not None and x['premium']>0]
    cand.sort(key=lambda x:x['score'],reverse=True)
    return {'status':'READY','candidates':cand[:24],'best_ce':next((x for x in cand if x['side']=='CE'),None),'best_pe':next((x for x in cand if x['side']=='PE'),None),'policy':'Premium is not capped; quality, reachability, gamma response, liquidity and confirmation decide the winner.'}


def before_blast(snapshot:dict,ladder:dict|None=None)->dict[str,Any]:
    ladder=ladder or strike_ladder(snapshot)
    c=(ladder.get('candidates') or [None])[0]
    if not c: return {'status':'UNAVAILABLE','state':'NO DATA','score':0,'candidate':None}
    flags={
      'gamma_wakeup':c['gamma_score']>=45,
      'delta_wakeup':c['delta_wakeup']>=35,
      'volume_surprise':c['volume_surprise']>=62,
      'oi_surprise':c['oi_flow']>=58,
      'premium_resurrection':c['premium_momentum']>=58,
      'reachability':c['reachability']>=50,
      'liquidity':c['liquidity']>=65,
      'depth_support':c['depth_score']>=56,
      'opposite_collapse':c['opposite_confirmation']>=58,
    }
    passed=sum(flags.values()); score=round(passed/len(flags)*100,1)
    state='BLAST BUILDING' if passed>=7 else 'WATCH' if passed>=5 else 'NO BLAST'
    return {'status':'READY','state':state,'score':score,'candidate':c,'flags':flags,'passed':passed,'required':len(flags)}


def pin_escape(snapshot:dict,chain:dict|None=None,regime:dict|None=None)->dict[str,Any]:
    chain=chain or option_chain_intelligence(snapshot); regime=regime or market_regime(snapshot); spot=_f(snapshot.get('spot'))
    if chain.get('status')!='READY' or spot is None:return {'status':'UNAVAILABLE'}
    walls=[x for x in (_f(chain.get('call_wall')),_f(chain.get('put_wall')),_f(chain.get('max_pain'))) if x is not None]
    if not walls:return {'status':'PARTIAL','pin_zone':None,'escape_score':None}
    nearest=min(walls,key=lambda x:abs(x-spot)); dist=abs(spot-nearest); exp=max(_f(chain.get('expected_move_proxy_points'),0) or 0,1)
    pin_strength=_clamp(100-dist/exp*100,0,100); escape=_clamp(abs(_f(regime.get('score'),0) or 0)*.65+(100-pin_strength)*.35,0,100)
    return {'status':'READY','pin_zone':nearest,'distance_points':round(dist,2),'pin_strength':round(pin_strength,1),'escape_score':round(escape,1),'state':'PIN ESCAPE WATCH' if escape>=65 else 'PINNING RISK' if pin_strength>=65 else 'OPEN'}


def volatility_brain(snapshot:dict,chain:dict|None=None)->dict[str,Any]:
    chain=chain or option_chain_intelligence(snapshot); rows=_chain(snapshot)
    if not rows:return {'status':'UNAVAILABLE'}
    atm=_f(chain.get('atm_strike')); spot=_f(snapshot.get('spot'))
    surface=[]
    for r in rows:
        s=_f(r.get('s')); surface.append({'strike':s,'call_iv':_f(r.get('civ')),'put_iv':_f(r.get('piv')),'distance':abs((s or 0)-(spot or 0)) if spot is not None else None})
    near=sorted(surface,key=lambda x:x['distance'] if x['distance'] is not None else 1e99)[:7]
    return {'status':'READY','atm':atm,'mean_iv':chain.get('mean_iv'),'skew':chain.get('iv_skew_put_minus_call'),'surface':near,'vol_of_vol_proxy':'BUILDING' if any((_f(r.get('cv1')) or 0)>1.5 or (_f(r.get('pv1')) or 0)>1.5 for r in rows) else 'NORMAL/UNCONFIRMED'}


def expiry_precision_hero(snapshot:dict)->dict[str,Any]:
    truth=data_truth(snapshot); master=master_decision(snapshot); chain=option_chain_intelligence(snapshot); ladder=strike_ladder(snapshot,master,chain); blast=before_blast(snapshot,ladder); reg=market_regime(snapshot); pin=pin_escape(snapshot,chain,reg)
    candidates=ladder.get('candidates') or []
    preferred=[x for x in candidates if master['side']=='WAIT' or x['side']==master['side']]
    winner=preferred[0] if preferred else (candidates[0] if candidates else None)
    if not winner:
        state='NO TRADE'; score=0
    else:
        score=winner['score']*.72+blast.get('score',0)*.18+truth['score']*.10
        hard_block=(truth['score']<55 or winner['liquidity']<42 or winner['reachability']<22 or (winner.get('spread_pct') is not None and winner['spread_pct']>18))
        if hard_block: state='NO TRADE'
        elif master['conflict'] and score<86: state='WAIT'
        elif score>=88 and blast.get('state')=='BLAST BUILDING': state='HERO ACTIVE'
        elif score>=80: state='HERO READY'
        elif score>=70: state='ARMED'
        elif score>=58: state='WATCH'
        else: state='NO TRADE'
    ttl=45 if state=='HERO ACTIVE' else 90 if state=='HERO READY' else 180
    spot=_f(snapshot.get('spot')); inv=None
    if winner and spot is not None:
        exp=_f(chain.get('expected_move_proxy_points'),0) or 0
        inv=spot-(exp*.12) if winner['side']=='CE' else spot+(exp*.12)
    sig=f"V70-{str(snapshot.get('active_underlying') or 'INDEX')}-{int(time.time())}"
    out={'signal_id':sig,'underlying':str(snapshot.get('active_underlying') or 'NIFTY'),'expiry':snapshot.get('expiry'),'spot':spot,'state':state,'side':winner.get('side') if winner and state not in ('NO TRADE','WAIT') else 'WAIT','score':round(_clamp(score if winner else 0),1),'winner':winner,'top_candidates':candidates[:8],'master':master,'blast':blast,'data_truth':truth,'regime':reg,'pin_escape':pin,'ttl_seconds':ttl,'invalidation_spot':round(inv,2) if inv is not None else None,
         'entry_policy':'Signal is evidence-gated and read-only. No outcome is guaranteed. Premium has no fixed cap.','one_side_rule':True}
    return out


def _last_snapshot(underlying:str):
    try:
        with _db() as c:
            r=c.execute('SELECT * FROM hero_snapshots_v70 WHERE underlying=? ORDER BY epoch DESC LIMIT 1',(underlying,)).fetchone()
            return dict(r) if r else None
    except Exception:return None


def record_hero(hero:dict)->dict[str,Any]:
    now=time.time(); u=str(hero.get('underlying') or 'INDEX'); w=hero.get('winner') or {}; prev=_last_snapshot(u)
    with _db() as c:
        c.execute('INSERT INTO hero_snapshots_v70(epoch,underlying,expiry,spot,direction,hero_state,hero_score,strike,option_type,premium,data_quality,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(
            now,u,hero.get('expiry'),_f(hero.get('spot')),str((hero.get('master') or {}).get('side') or 'WAIT'),hero.get('state'),_f(hero.get('score')),_f(w.get('strike')),w.get('side'),_f(w.get('premium')),_f((hero.get('data_truth') or {}).get('score')),json.dumps(hero,default=str)[:120000]))
        if hero.get('state') in ('HERO READY','HERO ACTIVE'):
            c.execute('INSERT INTO hero_signals_v70(epoch,underlying,signal_id,state,side,strike,premium,score,invalidation,ttl_seconds,evidence,counter_evidence,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(
                now,u,hero.get('signal_id'),hero.get('state'),hero.get('side'),_f(w.get('strike')),_f(w.get('premium')),_f(hero.get('score')),_f(hero.get('invalidation_spot')),int(hero.get('ttl_seconds') or 0),json.dumps(w.get('evidence') or []),json.dumps(w.get('counter_evidence') or []),json.dumps(hero,default=str)[:120000]))
        c.execute('DELETE FROM hero_snapshots_v70 WHERE epoch<?',(now-45*86400,)); c.commit()
    changed=[]
    if prev:
        for key,new in [('hero_state',hero.get('state')),('strike',_f(w.get('strike'))),('option_type',w.get('side'))]:
            old=prev.get(key)
            if str(old)!=str(new):changed.append({'field':key,'from':old,'to':new})
        oldscore=_f(prev.get('hero_score')); newscore=_f(hero.get('score'))
        if oldscore is not None and newscore is not None and abs(newscore-oldscore)>=5:changed.append({'field':'hero_score','from':round(oldscore,1),'to':round(newscore,1)})
    return {'recorded':True,'epoch':now,'what_changed':changed,'zero_hindsight':True}


def module_states(snapshot:dict,hero:dict)->dict[str,Any]:
    truth=hero['data_truth']; chain=option_chain_intelligence(snapshot); global_=global_risk(snapshot); br=breadth_intelligence(snapshot)
    live_hist=truth['checks']['price_history']; depth=any((r.get('cdepth') or r.get('pdepth')) for r in _chain(snapshot))
    modules={
      'Expiry Precision Hero':'READY' if chain.get('status')=='READY' else 'UNAVAILABLE',
      'Before The Blast':'READY' if chain.get('status')=='READY' else 'UNAVAILABLE',
      'Master Conflict Resolver':'READY',
      'Market Regime Brain':'READY' if live_hist else 'PARTIAL',
      'Opening 30-Minute Brain':'READY' if (snapshot.get('session_context') or {}).get('opening_range_high') else 'PARTIAL',
      'Pre-Breakout Radar':'READY' if live_hist else 'PARTIAL',
      'Auto Trender Pro':'READY' if live_hist else 'PARTIAL',
      'Sector Rotation AI':'READY' if br.get('status')=='READY' else 'UNAVAILABLE',
      'Index Contribution / Heavyweight Pulse':'READY' if snapshot.get('index_brain') else 'PARTIAL',
      'Options Command Center':'READY' if chain.get('status')=='READY' else 'UNAVAILABLE',
      'Gamma / Strike Magnet Map':'READY' if truth['checks']['greeks'] else 'PARTIAL',
      'IV Surface / Skew':'READY' if truth['checks']['greeks'] else 'PARTIAL',
      'OI Movie / Wall Migration':'READY' if truth['checks']['oi'] else 'UNAVAILABLE',
      'Premium Resurrection':'READY' if any(_f(r.get('cv1')) is not None or _f(r.get('pv1')) is not None for r in _chain(snapshot)) else 'PARTIAL',
      'Liquidity Vacuum / Spread Brain':'READY' if truth['checks']['bid_ask'] else 'PARTIAL',
      '30-Level Depth Promotion':'READY' if depth else 'PARTIAL',
      'Breadth Acceleration':'READY' if br.get('status')=='READY' else 'UNAVAILABLE',
      'Global Risk Brain':'READY' if global_.get('status') in ('READY','PARTIAL') else 'UNAVAILABLE',
      'Event Shock Engine':'SCAFFOLD / NEED VERIFIED EVENT FEED',
      'CAS Shock Brain':'SCAFFOLD / ACTIVATES WHEN CAS FIELDS PRESENT',
      'False Breakout / Trap Detector':'READY',
      'Reversal Radar':'READY' if live_hist else 'PARTIAL',
      'Second Chance Engine':'READY' if live_hist else 'PARTIAL',
      'What Changed':'READY',
      'Signal TTL / Invalidation':'READY',
      'Opportunity Ranker':'READY',
      'Replay / Zero-Hindsight':'READY',
      'Self Calibration':'WARMING UP / NEED STORED EXPIRIES',
      'False Positive Database':'READY / POPULATES WITH SIGNAL HISTORY',
      'Latency Audit':'PARTIAL',
      'Source Health / Data Truth':'READY',
      'Graceful Degradation':'READY',
      'Correlation Guard':'READY',
      'One-Trade Lock':'READY',
      'Dynamic Subscription Manager':'PARTIAL / ACTIVE FEED MANAGED BY UPSTOX SERVICE',
      'Historical Zero-to-Hero Lab':'SCAFFOLD / REQUIRES EXPIRED-CONTRACT INGEST JOB',
      'Champion / Challenger Shadow Mode':'SCAFFOLD',
    }
    return {'modules':modules,'ready':sum(1 for v in modules.values() if v=='READY'),'partial':sum(1 for v in modules.values() if 'PARTIAL' in v or 'WARMING' in v or 'SCAFFOLD' in v),'total':len(modules)}


def build_v70(snapshot:dict, record:bool=True)->dict[str,Any]:
    hero=expiry_precision_hero(snapshot)
    chain=option_chain_intelligence(snapshot); reg=hero['regime']; br=breadth_intelligence(snapshot); glob=global_risk(snapshot); vol=volatility_brain(snapshot,chain); pin=hero['pin_escape']
    rec=record_hero(hero) if record and not snapshot.get('demo') else {'recorded':False,'what_changed':[],'zero_hindsight':True}
    mods=module_states(snapshot,hero)
    return {
      'version':'70.0','name':'Precision Expiry & Market Intelligence OS','read_only':True,'execution_enabled':False,'generated_at':_now_iso(),
      'expiry_precision_hero':hero,'strike_ladder':{'status':'READY' if hero.get('top_candidates') else 'UNAVAILABLE','candidates':hero.get('top_candidates') or []},
      'before_the_blast':hero.get('blast'),'master_decision':hero.get('master'),'market_regime':reg,'option_chain':chain,'volatility_brain':vol,'pin_escape':pin,'breadth':br,'global_risk':glob,
      'what_changed':rec.get('what_changed') or [],'zero_hindsight':rec.get('zero_hindsight',True),'module_status':mods,
      'risk_policy':['No 100% profit guarantee is displayed.','No arbitrary premium cap; higher-premium options may outrank cheap OTM contracts.','One-side rule prevents simultaneous CE/PE recommendations.','Stale/incomplete data can force WAIT/NO TRADE.','Anonymous OI/depth never identifies institutions.'],
    }

def hero_history(underlying:str='NIFTY', minutes:int=390, limit:int=1000)->dict[str,Any]:
    cutoff=time.time()-max(1,int(minutes))*60
    with _db() as c:
        rows=[dict(r) for r in c.execute('SELECT epoch,underlying,expiry,spot,direction,hero_state,hero_score,strike,option_type,premium,data_quality FROM hero_snapshots_v70 WHERE underlying=? AND epoch>=? ORDER BY epoch ASC LIMIT ?', (underlying.upper(),cutoff,min(max(int(limit),1),5000)))]
        signals=[dict(r) for r in c.execute('SELECT epoch,underlying,signal_id,state,side,strike,premium,score,invalidation,ttl_seconds,evidence,counter_evidence FROM hero_signals_v70 WHERE underlying=? AND epoch>=? ORDER BY epoch ASC LIMIT ?', (underlying.upper(),cutoff,min(max(int(limit),1),5000)))]
    return {'underlying':underlying.upper(),'minutes':minutes,'rows':rows,'signals':signals,'zero_hindsight':True}


def all_index_rank(results:list[dict[str,Any]])->dict[str,Any]:
    board=[]
    for x in results:
        h=(x or {}).get('expiry_precision_hero') or {}
        w=h.get('winner') or {}
        board.append({'underlying':h.get('underlying'),'expiry':h.get('expiry'),'state':h.get('state'),'side':h.get('side'),'score':_f(h.get('score'),0) or 0,'strike':w.get('strike'),'premium':w.get('premium'),'data_quality':(h.get('data_truth') or {}).get('score'),'source':(h.get('data_truth') or {}).get('source'),'freshness':(h.get('data_truth') or {}).get('freshness')})
    board.sort(key=lambda z:(z['state']=='HERO ACTIVE',z['state']=='HERO READY',z['score']),reverse=True)
    best=next((x for x in board if x['state'] in ('HERO ACTIVE','HERO READY','ARMED','WATCH')), board[0] if board else None)
    return {'status':'READY' if board else 'UNAVAILABLE','best_now':best,'board':board,'policy':'Four indices compete; only the highest-quality current candidate is surfaced as BEST NOW. Scores are evidence quality, not profit probability.'}
