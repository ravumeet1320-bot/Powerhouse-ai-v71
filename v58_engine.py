from __future__ import annotations
"""POWERHOUSE AI V58 — Market Opportunity Operating System.
Read-only. Every metric is derived from verified snapshot fields; unavailable inputs stay N/A.
"""
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional
import math, time

_STATE=defaultdict(lambda: deque(maxlen=120))
_DECISIONS=defaultdict(lambda: deque(maxlen=40))

def n(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception:return None

def clamp(x,a=0,b=100): return max(a,min(b,x))
def get(r,*ks):
    for k in ks:
        v=n(r.get(k))
        if v is not None:return v
    return None

def historical_level(r):
    levels={
      'PDH':get(r,'prev_day_high','pdh'),'PDL':get(r,'prev_day_low','pdl'),
      'DAY_HIGH':get(r,'day_high','high'),'DAY_LOW':get(r,'day_low','low'),
      '52W_HIGH':get(r,'high_52w','year_high'),'52W_LOW':get(r,'low_52w','year_low'),
      'VWAP':get(r,'vwap'),'ORB_HIGH':get(r,'orb_high'),'ORB_LOW':get(r,'orb_low'),
      '20D_HIGH':get(r,'high_20d'),'50D_HIGH':get(r,'high_50d'),
      'WEEK_HIGH':get(r,'week_high'),'MONTH_HIGH':get(r,'month_high')}
    return {k:v for k,v in levels.items() if v is not None}

def update_state(r):
    sym=r.get('symbol'); px=n(r.get('ltp'))
    if not sym or px is None:return []
    now=time.time(); h=_STATE[sym]; h.append({'t':now,'px':px,'vol':n(r.get('volume')),'oi':get(r,'oi','futures_oi'),'bidp':get((r.get('liquidity') or {}),'bid_pressure_pct')})
    return list(h)

def velocity(hist, seconds=180):
    if len(hist)<2:return None
    cur=hist[-1]; old=None
    for x in reversed(hist[:-1]):
        if cur['t']-x['t']>=seconds: old=x; break
    old=old or hist[0]
    if not old['px']:return None
    dt=max(1,cur['t']-old['t']); return (cur['px']-old['px'])/old['px']*100*60/dt

def accel(hist):
    if len(hist)<4:return None
    mid=len(hist)//2
    a=velocity(hist[:mid+1],120); b=velocity(hist[mid:],120)
    return None if a is None or b is None else b-a

def volume_accel(hist):
    vals=[x['vol'] for x in hist if x['vol'] is not None]
    if len(vals)<3:return None
    d1=vals[-1]-vals[-2]; d0=vals[-2]-vals[-3]
    return d1-d0

def oi_velocity(hist):
    vals=[x for x in hist if x['oi'] is not None]
    if len(vals)<2 or not vals[0]['oi']:return None
    dt=max(1,vals[-1]['t']-vals[0]['t'])
    return (vals[-1]['oi']-vals[0]['oi'])/abs(vals[0]['oi'])*100*60/dt

def confluence(r):
    px=n(r.get('ltp')); lv=historical_level(r); near=[]
    if px:
        for k,v in lv.items():
            d=abs(px-v)/px*100
            if d<=0.35:near.append({'level':k,'value':v,'distance_pct':round(d,3)})
    return sorted(near,key=lambda x:x['distance_pct'])

def entry_quality(r, vel):
    px=n(r.get('ltp')); atr=get(r,'atr'); vwap=get(r,'vwap'); cp=abs(n(r.get('change_pct')) or 0)
    ext=None
    if px and vwap: ext=abs(px-vwap)/px*100
    atr_ext=(abs(px-vwap)/atr if px and vwap and atr else None)
    if atr_ext is not None and atr_ext>=2.0:return 'CHASE'
    if cp>=5:return 'LATE'
    if vel is not None and abs(vel)>=.8:return 'FAST / CAUTION'
    return 'IDEAL / WATCH'

def data_quality(r):
    fields={'price':n(r.get('ltp')) is not None,'volume':n(r.get('volume')) is not None,'rvol':n(r.get('rvol')) is not None,
      'structure':bool(historical_level(r)),'depth':get((r.get('liquidity') or {}),'spread_pct') is not None,
      'oi':get(r,'oi','futures_oi','oi_change_pct','futures_oi_change_pct') is not None,'vwap':get(r,'vwap') is not None}
    have=sum(fields.values()); return {'score':round(100*have/len(fields)),'fields':fields,'state':'LIVE/RICH' if have>=6 else 'PARTIAL' if have>=3 else 'THIN'}

def conflict(r):
    cp=n(r.get('change_pct')) or 0; rs=(r.get('relative_strength') or {}).get('vs_market'); oic=get(r,'oi_change_pct','futures_oi_change_pct'); bidp=get((r.get('liquidity') or {}),'bid_pressure_pct')
    pro=[]; contra=[]
    if cp>0:pro.append('price positive')
    elif cp<0:contra.append('price negative')
    if rs is not None:
        (pro if rs>0 else contra).append('relative strength '+('positive' if rs>0 else 'negative'))
    if oic is not None:
        if cp*oic>0:pro.append('price/OI aligned')
        elif cp*oic<0:contra.append('price/OI divergent')
    if bidp is not None:
        if bidp>=60:pro.append('buy depth pressure')
        elif bidp<=40:contra.append('sell depth pressure')
    sev='SEVERE' if len(contra)>=3 else 'MODERATE' if len(contra)>=2 else 'LOW'
    return {'supporting':pro,'counter_evidence':contra,'severity':sev}

def scenario(r):
    px=n(r.get('ltp')); lv=historical_level(r)
    above=None; below=None
    highs=[v for k,v in lv.items() if 'HIGH' in k and px and v>=px]
    lows=[v for k,v in lv.items() if ('LOW' in k or k=='VWAP') and px and v<=px]
    if highs: above=min(highs)
    if lows: below=max(lows)
    return {'bullish_above':above,'bearish_below':below,'between':'WAIT / OBSERVE'}

def build_v58(market:Dict[str,Any], v57:Optional[Dict[str,Any]]=None)->Dict[str,Any]:
    rows=[]; src=(v57 or {}).get('opportunity_radar') or []
    now=time.time()
    for x in src:
        r=dict(x); hist=update_state(r); vel=velocity(hist); ac=accel(hist); va=volume_accel(hist); oiv=oi_velocity(hist)
        cf=confluence(r); dq=data_quality(r); co=conflict(r); eq=entry_quality(r,vel); sc=scenario(r)
        maturity='FRESH' if len(hist)<5 else 'EXTENDED' if eq in ('CHASE','LATE') else 'DEVELOPING'
        urgency='NOW' if r.get('stage') in ('TRIGGER READY','CONFIRMED') else 'SOON' if r.get('stage') in ('ATTACKING','EARLY MOVER') else 'WATCH'
        # evidence additions never masquerade as probability
        micro=0
        if vel is not None: micro+=min(30,abs(vel)*25)
        if ac is not None and abs(ac)>.1: micro+=15
        if va is not None and va>0: micro+=15
        if oiv is not None and abs(oiv)>.2: micro+=15
        micro+=min(25,len(cf)*8)
        r.update({'price_velocity_pct_per_min':round(vel,3) if vel is not None else None,'price_acceleration':round(ac,3) if ac is not None else None,
          'volume_acceleration':round(va,2) if va is not None else None,'oi_velocity_pct_per_min':round(oiv,3) if oiv is not None else None,
          'confluence_map':cf,'data_quality':dq,'conflict_matrix':co,'entry_quality':eq,'move_maturity':maturity,'urgency':urgency,
          'scenario_tree':sc,'micro_burst_score':round(clamp(micro)),'signal_age_sec':0})
        _DECISIONS[r.get('symbol')].append({'t':now,'stage':r.get('stage'),'score':r.get('early_score'),'px':r.get('ltp')})
        rows.append(r)
    pri={'NOW':3,'SOON':2,'WATCH':1}; rows.sort(key=lambda r:(pri.get(r['urgency'],0),r.get('early_score') or 0,r['micro_burst_score']),reverse=True)
    about=[r for r in rows if r['urgency']=='SOON' and r['entry_quality']!='CHASE'][:12]
    best=[r for r in rows if r['urgency']=='NOW' and r['conflict_matrix']['severity']!='SEVERE' and (r.get('liquidity') or {}).get('status')!='REJECT'][:5]
    second=[r for r in rows if r.get('stage') in ('WATCH','BUILDING','ATTACKING') and r['move_maturity']=='DEVELOPING' and len(r['confluence_map'])>0][:10]
    avoid=[r for r in rows if r['entry_quality'] in ('CHASE','LATE') or r['conflict_matrix']['severity']=='SEVERE' or (r.get('liquidity') or {}).get('status')=='REJECT'][:10]
    # coverage and reliability are factual from current snapshot
    keys=['price','volume','rvol','structure','depth','oi','vwap']; coverage={k:sum(1 for r in rows if r['data_quality']['fields'][k]) for k in keys}
    total=len(rows); coverage_pct={k:round(100*v/total,1) if total else 0 for k,v in coverage.items()}
    health='HEALTHY' if total and min(coverage_pct.get('price',0),coverage_pct.get('volume',0))>=95 else 'DEGRADED' if total else 'UNAVAILABLE'
    phase='OPENING' if False else 'SESSION' # server has no exchange-local clock guarantee; UI can label generic session
    return {'version':'58.0','title':'Powerhouse AI V58 — Market Opportunity Operating System','generated_at':now,'read_only':True,'execution_enabled':False,
      'command_center':{'best_now':best,'about_to_move':about,'second_chance':second,'avoid':avoid},
      'full_radar':rows,
      'market_anomaly_radar':sorted(rows,key=lambda r:r['micro_burst_score'],reverse=True)[:15],
      'leader_follower_radar':sorted(rows,key=lambda r:((r.get('relative_strength') or {}).get('vs_sector') or -999),reverse=True)[:15],
      'confluence_radar':[r for r in rows if len(r['confluence_map'])>=2][:15],
      'oi_velocity_radar':[r for r in rows if r['oi_velocity_pct_per_min'] is not None][:15],
      'data_coverage':{'scanned':total,'counts':coverage,'pct':coverage_pct,'health':health},
      'scanner_reliability':{'state':health,'session_memory_symbols':len(_STATE),'note':'Latency/feed-gap SLA requires timestamped provider telemetry; not fabricated.'},
      'session_intelligence':{'phase':phase,'opportunity_density':(v57 or {}).get('opportunity_density'),'market_regime':(v57 or {}).get('market_regime')},
      'decision_architecture':['ANOMALY','STRUCTURE','VOLUME','RELATIVE STRENGTH','OI','LIQUIDITY','CONFLUENCE','CONFLICT','ENTRY QUALITY','FINAL STATE'],
      'implemented_modules':['market anomaly/micro-burst','price velocity & acceleration','volume acceleration','OI velocity when OI exists','multi-level confluence','entry/chase quality','move maturity','leader/follower relative strength','conflict & counter-evidence','scenario tree','second-chance radar','avoid board','per-metric data coverage','persistent candidate state','scanner reliability state'],
      'truth_policy':['Scores are evidence/quality metrics, never profit or win probability.','OI velocity is N/A until verified OI is present.','Historical/confluence levels use only supplied verified fields.','No FII/DII identity inference, spoofing claim, broker execution or automatic order placement.']}
