from __future__ import annotations
"""POWERHOUSE AI V57 — Opportunity Radar & Missed-Move Prevention Engine.

Read-only analytics. Designed to reduce missed liquid opportunities without
pretending that setup quality is a win probability. Uses only fields actually
present in snapshots. Keeps a small in-process shadow history to diagnose moves
that were rejected earlier in the session.
"""
from typing import Any, Dict, List, Optional
from collections import defaultdict, deque
import math, time

_HISTORY: Dict[str, deque] = defaultdict(lambda: deque(maxlen=40))
_REJECTS: Dict[str, Dict[str, Any]] = {}
_AUTOPSIES: deque = deque(maxlen=100)


def num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None

def clamp(x,a=0,b=100): return max(a,min(b,x))

def pct(a,b):
    if a is None or b in (None,0): return None
    return (a-b)/b*100

def market_regime(rows: List[Dict[str,Any]]) -> Dict[str,Any]:
    ch=[num(r.get('change_pct')) for r in rows]; ch=[x for x in ch if x is not None]
    if not ch: return {'state':'UNKNOWN','breadth_up_pct':None,'dispersion':None}
    up=sum(1 for x in ch if x>0); breadth=100*up/len(ch); mean=sum(ch)/len(ch)
    var=sum((x-mean)**2 for x in ch)/len(ch); disp=var**0.5
    if disp>=2.2: state='HIGH VOLATILITY'
    elif breadth>=68 or breadth<=32: state='TRENDING'
    elif disp<=0.75 and 42<=breadth<=58: state='RANGE / CHOPPY'
    else: state='MIXED'
    return {'state':state,'breadth_up_pct':round(breadth,1),'dispersion':round(disp,2),'mean_change_pct':round(mean,2)}

def sector_relative_strength(rows):
    sec=defaultdict(list)
    vals=[]
    for r in rows:
        c=num(r.get('change_pct'))
        if c is None: continue
        vals.append(c); sec[r.get('sector') or 'OTHER'].append(c)
    market=sum(vals)/len(vals) if vals else 0
    secavg={k:sum(v)/len(v) for k,v in sec.items() if v}
    out={}
    for r in rows:
        c=num(r.get('change_pct'))
        if c is None: continue
        s=r.get('sector') or 'OTHER'; sa=secavg.get(s,market)
        out[r.get('symbol')]={'vs_market':round(c-market,2),'vs_sector':round(c-sa,2),'sector_avg':round(sa,2)}
    return out

def liquidity(row):
    bid=num(row.get('bid')); ask=num(row.get('ask')); bq=num(row.get('bid_qty')); aq=num(row.get('ask_qty')); px=num(row.get('ltp'))
    spread=None
    if bid is not None and ask is not None and px:
        spread=max(0,(ask-bid)/px*100)
    depth=None
    if bq is not None and aq is not None and bq+aq>0: depth=100*bq/(bq+aq)
    if spread is None: status='UNKNOWN'
    elif spread<=0.08: status='HEALTHY'
    elif spread<=0.20: status='CAUTION'
    else: status='REJECT'
    return {'spread_pct':round(spread,3) if spread is not None else None,'bid_pressure_pct':round(depth,1) if depth is not None else None,'status':status}

def early_score(r, rs):
    cp=num(r.get('change_pct')) or 0; rv=num(r.get('rvol')); dist=num(r.get('distance_pct')); base=num(r.get('setup_score')) or 0
    score=0.30*base + min(18,abs(cp)*7)
    if rv is not None: score += min(22,max(0,(rv-1)*20))
    if dist is not None:
        score += 18 if 0<=dist<=.25 else 13 if 0<=dist<=.75 else 7 if 0<=dist<=1.5 else 0
    score += min(8,max(0,(rs or {}).get('vs_market',0)*3))
    score += min(6,max(0,(rs or {}).get('vs_sector',0)*3))
    return round(clamp(score))

def stage(r, score, liq):
    old=(r.get('stage') or '').upper(); dist=num(r.get('distance_pct')); rv=num(r.get('rvol'))
    if liq.get('status')=='REJECT': return 'LIQUIDITY REJECT'
    if old in ('CONFIRMED','BREAKOUT ATTEMPT'): return 'CONFIRMED' if (rv is None or rv>=1.3) else 'BREAKOUT ATTEMPT'
    if dist is not None and 0<=dist<=.20 and (rv is None or rv>=1.25): return 'TRIGGER READY'
    if dist is not None and 0<=dist<=.60: return 'ATTACKING'
    if score>=68: return 'EARLY MOVER'
    if score>=52: return 'BUILDING'
    return 'WATCH'

def reason_list(r, rs, liq):
    z=[]; rv=num(r.get('rvol')); d=num(r.get('distance_pct')); cp=num(r.get('change_pct'))
    if rv is not None and rv>=1.5: z.append(f'RVOL {rv:.1f}x')
    if d is not None and 0<=d<=1: z.append(f'{d:.2f}% to resistance')
    if rs and rs.get('vs_market',0)>=.5: z.append(f"RS +{rs['vs_market']:.2f}% vs market")
    if rs and rs.get('vs_sector',0)>=.4: z.append(f"RS +{rs['vs_sector']:.2f}% vs sector")
    if cp is not None and abs(cp)>=1: z.append(f'price momentum {cp:+.2f}%')
    if liq.get('status')=='HEALTHY': z.append('healthy spread')
    if not z: z.append('insufficient aligned evidence')
    return z[:5]

def shadow_update(rows):
    now=time.time(); aut=[]
    for r in rows:
        sym=r.get('symbol'); px=num(r.get('ltp'))
        if not sym or px is None: continue
        hist=_HISTORY[sym]; hist.append({'t':now,'px':px,'stage':r.get('stage'),'score':r.get('early_score')})
        qualified=r.get('stage') in ('EARLY MOVER','ATTACKING','TRIGGER READY','CONFIRMED') and r.get('liquidity',{}).get('status')!='REJECT'
        if not qualified and sym not in _REJECTS:
            _REJECTS[sym]={'t':now,'px':px,'score':r.get('early_score'),'stage':r.get('stage'),'reasons':r.get('reject_reasons') or []}
        rej=_REJECTS.get(sym)
        if rej and rej['px']:
            move=(px-rej['px'])/rej['px']*100
            if abs(move)>=1.25 and (now-rej['t'])>=30:
                a={'symbol':sym,'move_since_reject_pct':round(move,2),'rejected_stage':rej.get('stage'),'rejected_score':rej.get('score'),'reject_reasons':rej.get('reasons'), 'seconds_to_move':round(now-rej['t'])}
                _AUTOPSIES.appendleft(a); aut.append(a); _REJECTS.pop(sym,None)
        if qualified: _REJECTS.pop(sym,None)
    return aut

def build_v57(market:Dict[str,Any], v56:Optional[Dict[str,Any]]=None)->Dict[str,Any]:
    base=((v56 or {}).get('advanced_screener') or {}).get('universe') or []
    rsmap=sector_relative_strength(base); rows=[]
    for b in base:
        r=dict(b); rs=rsmap.get(r.get('symbol'),{}); liq=liquidity(r); es=early_score(r,rs); st=stage(r,es,liq)
        rejects=[]
        if liq['status']=='REJECT': rejects.append('wide spread')
        if num(r.get('rvol')) is None: rejects.append('RVOL unavailable')
        if num(r.get('distance_pct')) is None: rejects.append('structure level unavailable')
        r.update({'relative_strength':rs,'liquidity':liq,'early_score':es,'stage':st,'why_now':reason_list(r,rs,liq),'reject_reasons':rejects})
        rows.append(r)
    priority={'CONFIRMED':7,'TRIGGER READY':6,'ATTACKING':5,'EARLY MOVER':4,'BUILDING':3,'WATCH':2,'BREAKOUT ATTEMPT':1,'LIQUIDITY REJECT':0}
    rows.sort(key=lambda r:(priority.get(r['stage'],0),r['early_score']),reverse=True)
    shadow_update(rows)
    regime=market_regime(rows)
    opp=[r for r in rows if r['stage'] in ('CONFIRMED','TRIGGER READY','ATTACKING','EARLY MOVER') and r['liquidity']['status']!='REJECT']
    density=100*len(opp)/len(rows) if rows else 0
    density_state='HIGH' if density>=12 else 'NORMAL' if density>=5 else 'LOW'
    funnel={s:sum(1 for r in rows if r['stage']==s) for s in ['WATCH','BUILDING','EARLY MOVER','ATTACKING','TRIGGER READY','CONFIRMED','LIQUIDITY REJECT']}
    return {
      'version':'57.0','title':'Powerhouse AI V57 — Opportunity Radar & Missed-Move Prevention','generated_at':time.time(),'read_only':True,'execution_enabled':False,
      'market_regime':regime,'opportunity_density':{'pct':round(density,1),'state':density_state,'qualified':len(opp),'scanned':len(rows)},
      'funnel':funnel,'opportunity_radar':rows,'best_now':opp[:5],
      'early_movers':[r for r in rows if r['stage']=='EARLY MOVER'][:15],
      'attacking':[r for r in rows if r['stage']=='ATTACKING'][:15],
      'trigger_ready':[r for r in rows if r['stage']=='TRIGGER READY'][:15],
      'confirmed':[r for r in rows if r['stage']=='CONFIRMED'][:15],
      'shadow_scanner':{'tracked_symbols':len(_HISTORY),'active_rejects':len(_REJECTS),'autopsies':list(_AUTOPSIES)[:20], 'note':'In-process session memory; resets when service restarts.'},
      'no_trade_quality':{'state':'GOOD TO WAIT' if density_state=='LOW' else 'SELECTIVE' if density_state=='NORMAL' else 'ACTIVE','reason':f'{density_state} opportunity density; do not force trades.'},
      'truth_policy':['Early score is evidence alignment, not win probability.','Missing RVOL/structure remains explicit and lowers explainability.','Shadow autopsy is diagnostic only and does not imply the rejected move was tradable.','No broker execution or automatic orders.']
    }
