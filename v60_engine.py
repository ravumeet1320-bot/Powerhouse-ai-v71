from __future__ import annotations
"""POWERHOUSE AI V60 — Production Intelligence & Self-Audit OS.
Read-only analytics. No broker execution. No fabricated profit/win probability.
Builds on V58 verified snapshot-derived intelligence and adds lifecycle memory,
evidence timelines, metric freshness, signal aging, adaptive decision firewalls,
coverage benchmarks, missed/late detection diagnostics, and rule attribution.
"""
from collections import defaultdict, deque, Counter
from typing import Any, Dict, List, Optional
import math, time

_HISTORY = defaultdict(lambda: deque(maxlen=240))
_TIMELINE = defaultdict(lambda: deque(maxlen=80))
_LAST_STAGE: Dict[str, str] = {}
_FIRST_SEEN: Dict[str, float] = {}
_TRIGGER_SEEN: Dict[str, float] = {}
_AUDIT = deque(maxlen=3000)

ACTIONS = {"BUY","SELL","BUY CE","BUY PE","WAIT"}
STAGE_RANK = {
    "WATCH":0,"DISCOVERED":1,"EARLY MOVER":2,"VOLUME AWAKENING":3,
    "BUILDING":4,"ATTACKING":5,"TRIGGER READY":6,"CONFIRMED":7,
    "RETEST":6,"FAILED":0,"EXTENDED":0,
}

def num(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception:return None

def clamp(x,a=0.0,b=100.0): return max(a,min(b,x))

def _now(market):
    t=num(market.get('last_tick_epoch'))
    return t if t and t>0 else time.time()

def _freshness(age):
    if age is None:return 'UNAVAILABLE'
    if age<=30:return 'FRESH'
    if age<=180:return 'STALE'
    return 'EXPIRED'

def metric_freshness(market:Dict[str,Any], row:Dict[str,Any], now:float)->Dict[str,Any]:
    # Prefer per-row timestamps when present. Fall back to provider last-tick only for live fields.
    provider_ts=num(market.get('last_tick_epoch'))
    mapping={
      'price':['ltp_epoch','price_epoch','tick_epoch'],
      'volume':['volume_epoch','tick_epoch'],
      'depth':['depth_epoch','tick_epoch'],
      'oi':['oi_epoch','futures_oi_epoch'],
      'rvol':['rvol_epoch'],
      'structure':['structure_epoch','historical_epoch'],
      'vwap':['vwap_epoch','tick_epoch'],
    }
    out={}
    dq=(row.get('data_quality') or {}).get('fields') or {}
    for metric, keys in mapping.items():
        ts=None
        for k in keys:
            ts=num(row.get(k))
            if ts is not None: break
        if ts is None and metric in {'price','volume','depth','vwap'}:
            ts=provider_ts
        age=max(0.0,now-ts) if ts else None
        available=bool(dq.get(metric))
        out[metric]={'available':available,'age_sec':round(age,1) if age is not None else None,
                     'state':_freshness(age) if available else 'UNAVAILABLE'}
    return out

def consensus(row:Dict[str,Any])->Dict[str,Any]:
    votes=[]
    cp=num(row.get('change_pct'))
    rs=(row.get('relative_strength') or {})
    rsm=num(rs.get('vs_market')); rss=num(rs.get('vs_sector'))
    rv=num(row.get('rvol')); oiv=num(row.get('oi_velocity_pct_per_min'))
    bidp=num((row.get('liquidity') or {}).get('bid_pressure_pct'))
    vel=num(row.get('price_velocity_pct_per_min'))
    for name,val in [('price',cp),('market_rs',rsm),('sector_rs',rss),('velocity',vel),('oi_velocity',oiv)]:
        if val is None: continue
        votes.append((name, 1 if val>0 else -1 if val<0 else 0))
    if rv is not None and rv>=1.5: votes.append(('rvol', 1 if (cp or 0)>=0 else -1))
    if bidp is not None: votes.append(('depth',1 if bidp>=58 else -1 if bidp<=42 else 0))
    pos=sum(v>0 for _,v in votes); neg=sum(v<0 for _,v in votes); usable=pos+neg
    alignment=round(100*max(pos,neg)/usable,1) if usable else 0
    side='BULLISH' if pos>neg else 'BEARISH' if neg>pos else 'MIXED'
    return {'side':side,'alignment_pct':alignment,'positive_votes':pos,'negative_votes':neg,
            'evidence':[{'name':n,'vote':'BULL' if v>0 else 'BEAR' if v<0 else 'NEUTRAL'} for n,v in votes]}

def signal_half_life(row:Dict[str,Any])->int:
    st=str(row.get('stage') or '').upper()
    eq=str(row.get('entry_quality') or '')
    if eq in {'CHASE','LATE'}: return 60
    if st=='CONFIRMED': return 180
    if st=='TRIGGER READY': return 120
    if st=='ATTACKING': return 300
    return 600

def adaptive_firewall(row:Dict[str,Any], market_health:str)->Dict[str,Any]:
    reasons=[]; hard=[]
    dq=(row.get('data_quality') or {})
    conf=(row.get('conflict_matrix') or {})
    liq=row.get('liquidity') or {}
    c=consensus(row)
    if market_health in {'UNAVAILABLE','DEGRADED'}: reasons.append('scanner data health degraded')
    if dq.get('score',0)<45: hard.append('insufficient verified evidence')
    if conf.get('severity')=='SEVERE': hard.append('severe cross-signal conflict')
    if liq.get('status')=='REJECT': hard.append('liquidity firewall rejected')
    if row.get('entry_quality') in {'CHASE','LATE'}: hard.append('late/chase risk')
    if c['alignment_pct']<55 and c['positive_votes']+c['negative_votes']>=3: reasons.append('weak evidence consensus')
    if row.get('move_maturity')=='EXTENDED': hard.append('move already extended')
    passed=not hard
    return {'passed':passed,'hard_rejects':hard,'warnings':reasons,'consensus':c}

def derive_action(row:Dict[str,Any], fw:Dict[str,Any])->str:
    existing=str(row.get('action') or 'WAIT').upper()
    if existing not in ACTIONS: existing='WAIT'
    if not fw['passed']: return 'WAIT'
    st=str(row.get('stage') or '').upper()
    if STAGE_RANK.get(st,0)<6:return 'WAIT'
    if existing!='WAIT':return existing
    side=fw['consensus']['side']
    if side=='BULLISH': return 'BUY'
    if side=='BEARISH': return 'SELL'
    return 'WAIT'

def update_lifecycle(row:Dict[str,Any], now:float)->Dict[str,Any]:
    sym=str(row.get('symbol') or '').upper()
    if not sym:return {}
    st=str(row.get('stage') or 'WATCH').upper()
    px=num(row.get('ltp'))
    if sym not in _FIRST_SEEN:_FIRST_SEEN[sym]=now
    prev=_LAST_STAGE.get(sym)
    if prev!=st:
        _TIMELINE[sym].append({'t':now,'event':st,'price':px,'score':row.get('early_score')})
        _AUDIT.append({'t':now,'symbol':sym,'type':'STATE_CHANGE','from':prev,'to':st,'price':px})
        _LAST_STAGE[sym]=st
    if STAGE_RANK.get(st,0)>=6 and sym not in _TRIGGER_SEEN:_TRIGGER_SEEN[sym]=now
    _HISTORY[sym].append({'t':now,'stage':st,'price':px,'score':row.get('early_score'),'action':row.get('action')})
    first=_FIRST_SEEN[sym]
    trig=_TRIGGER_SEEN.get(sym)
    return {
      'first_seen_epoch':first,'age_sec':round(max(0,now-first),1),
      'first_trigger_epoch':trig,'lead_to_trigger_sec':round(trig-first,1) if trig else None,
      'timeline':list(_TIMELINE[sym])[-12:]
    }

def rule_attribution(row:Dict[str,Any], fw:Dict[str,Any])->Dict[str,Any]:
    accepted=[]; rejected=[]
    if (num(row.get('rvol')) or 0)>=1.5: accepted.append('RVOL expansion')
    if len(row.get('confluence_map') or [])>=2: accepted.append('multi-level confluence')
    if (num(row.get('micro_burst_score')) or 0)>=50: accepted.append('micro-burst activity')
    if fw['consensus']['alignment_pct']>=70: accepted.append('strong evidence consensus')
    if row.get('stage') in ('TRIGGER READY','CONFIRMED'): accepted.append('trigger lifecycle state')
    rejected.extend(fw['hard_rejects']); rejected.extend(fw['warnings'])
    return {'supporting_rules':accepted,'blocking_rules':rejected}

def benchmark(rows:List[Dict[str,Any]])->Dict[str,Any]:
    # This is a scanner timing benchmark, NOT profitability. It uses observed lifecycle only.
    counts=Counter(); lead=[]
    for r in rows:
        lc=r.get('lifecycle') or {}; st=str(r.get('stage') or '').upper(); age=num(lc.get('age_sec')) or 0
        if st in ('TRIGGER READY','CONFIRMED'):
            l=num(lc.get('lead_to_trigger_sec'))
            if l is not None: lead.append(l)
            counts['on_radar_before_trigger' if l is not None and l>0 else 'trigger_seen_directly']+=1
        elif r.get('entry_quality') in ('CHASE','LATE'): counts['late_or_chase']+=1
        else: counts['developing']+=1
    return {'counts':dict(counts),'avg_lead_to_trigger_sec':round(sum(lead)/len(lead),1) if lead else None,
            'note':'Measures scanner observation timing only. It is not win rate or profit probability.'}

def build_v60(market:Dict[str,Any], v58:Optional[Dict[str,Any]]=None)->Dict[str,Any]:
    v58=v58 or {}; now=_now(market); rows=[]
    market_health=(v58.get('data_coverage') or {}).get('health') or 'UNAVAILABLE'
    for src in v58.get('full_radar') or []:
        r=dict(src)
        fresh=metric_freshness(market,r,now)
        lifecycle=update_lifecycle(r,now)
        fw=adaptive_firewall(r,market_health)
        action=derive_action(r,fw)
        half=signal_half_life(r)
        age=lifecycle.get('age_sec') or 0
        validity='ACTIVE' if age<=half else 'AGING' if age<=half*2 else 'EXPIRED'
        attrib=rule_attribution(r,fw)
        r.update({'metric_freshness':fresh,'lifecycle':lifecycle,'decision_firewall':fw,
                  'final_action':action,'signal_half_life_sec':half,'signal_validity':validity,
                  'rule_attribution':attrib})
        rows.append(r)
    # Rank by actionable lifecycle + evidence + freshness; never by claimed win probability.
    def score(r):
        st=STAGE_RANK.get(str(r.get('stage') or '').upper(),0)*12
        early=num(r.get('early_score')) or 0; micro=num(r.get('micro_burst_score')) or 0
        align=num((r.get('decision_firewall') or {}).get('consensus',{}).get('alignment_pct')) or 0
        penalty=35 if r.get('final_action')=='WAIT' else 0
        penalty+=25 if r.get('signal_validity')=='EXPIRED' else 0
        return st+early*.45+micro*.2+align*.2-penalty
    for r in rows:r['v60_rank_score']=round(score(r),1)
    rows.sort(key=lambda x:x['v60_rank_score'],reverse=True)
    best=[r for r in rows if r['final_action']!='WAIT' and r['signal_validity']=='ACTIVE'][:5]
    about=[r for r in rows if r['final_action']=='WAIT' and str(r.get('stage')) in ('EARLY MOVER','BUILDING','ATTACKING') and r.get('entry_quality') not in ('CHASE','LATE')][:12]
    second=[r for r in rows if len(r.get('confluence_map') or [])>0 and r.get('move_maturity')=='DEVELOPING' and r.get('entry_quality') not in ('CHASE','LATE')][:10]
    avoid=[r for r in rows if not (r.get('decision_firewall') or {}).get('passed') or r.get('signal_validity')=='EXPIRED'][:12]
    coverage=v58.get('data_coverage') or {}
    price_cov=num((coverage.get('pct') or {}).get('price')) or 0
    rvol_cov=num((coverage.get('pct') or {}).get('rvol')) or 0
    oi_cov=num((coverage.get('pct') or {}).get('oi')) or 0
    structure_cov=num((coverage.get('pct') or {}).get('structure')) or 0
    production_readiness=round((price_cov*.30+rvol_cov*.25+oi_cov*.20+structure_cov*.25),1)
    readiness='PRODUCTION READY' if production_readiness>=90 else 'PARTIAL DATA FOUNDATION' if production_readiness>=60 else 'DATA FOUNDATION INCOMPLETE'
    misses=[a for a in list(_AUDIT)[-500:] if a.get('type')=='MISSED_MOVE']
    return {
      'version':'60.0','title':'Powerhouse AI V60 — Production Intelligence & Self-Audit OS',
      'generated_at':now,'read_only':True,'execution_enabled':False,
      'command_center':{'best_now':best,'about_to_move':about,'second_chance':second,'avoid':avoid},
      'radar':rows[:100],
      'production_readiness':{'score':production_readiness,'state':readiness,'coverage':coverage,
          'requirements':{'full_universe':'depends on connected provider universe','true_rvol':'required for 10/10 data readiness','historical_structure':'required','futures_oi':'required'},
          'truth':'10/10 is an engineering target, not a profit guarantee.'},
      'detection_benchmark':benchmark(rows),
      'state_change_feed':list(_AUDIT)[-40:],
      'missed_move_black_box':{'recorded':len(misses),'events':misses[-20:],
          'categories':['DATA_MISS','UNIVERSE_MISS','RULE_MISS','TOO_STRICT_FILTER','LATE_DETECTION','CORRECT_REJECTION'],
          'note':'Events are recorded only when an external/session evaluator supplies a meaningful-move outcome; no hindsight fabrication.'},
      'scanner_health':{'provider':market.get('source'),'websocket_connected':market.get('websocket_connected'),
          'last_tick_epoch':market.get('last_tick_epoch'),'coverage_health':market_health,
          'metric_freshness_policy':{'fresh_sec':30,'stale_sec':180},'tracked_symbols':len(_HISTORY)},
      'implemented_modules':['evidence timeline','candidate lifecycle memory','per-metric freshness','signal aging/half-life','adaptive decision firewall','consensus/conflict matrix','rule attribution','state-change feed','detection timing benchmark','production-readiness score','missed-move black-box schema','read-only final action router'],
      'truth_policy':['No profitable-trade guarantee or fabricated win probability.','No broker execution or automatic orders.','Missing/unverified data remains unavailable or lowers readiness.','FII/DII identity and spoofing are never inferred from anonymous market flow.']
    }

def record_outcome(symbol:str, category:str, detail:str='', move_pct:Optional[float]=None, detected_epoch:Optional[float]=None)->Dict[str,Any]:
    """Diagnostic hook for a verified post-move evaluator/session replay. Read-only; stores no orders."""
    category=str(category or '').upper()
    allowed={'DATA_MISS','UNIVERSE_MISS','RULE_MISS','TOO_STRICT_FILTER','LATE_DETECTION','CORRECT_REJECTION'}
    if category not in allowed: raise ValueError('unsupported outcome category')
    event={'t':time.time(),'symbol':str(symbol or '').upper(),'type':'MISSED_MOVE','category':category,'detail':str(detail or '')[:300],
           'move_pct':num(move_pct),'detected_epoch':num(detected_epoch)}
    _AUDIT.append(event); return event
