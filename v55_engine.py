from __future__ import annotations
"""V55 Breakout Intelligence Engine — read-only discovery/diagnostics layer."""
from typing import Any, Dict, Optional
import math, time

def n(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception:return None

def clamp(x,a=0,b=100): return max(a,min(b,x))

def breakout_row(x:Dict[str,Any], d:Dict[str,Any])->Dict[str,Any]:
    px=n(x.get('ltp')); ch=n(x.get('change_pct')); rv=n(x.get('rvol')); vol=n(x.get('volume'))
    hi=n(x.get('high_52w')); pdh=n(x.get('prev_day_high') or x.get('pdh')); dayh=n(x.get('day_high') or x.get('high'))
    resistance=next((z for z in (pdh,dayh,hi) if z is not None and px is not None and z>=px*.985), None)
    dist=((resistance-px)/resistance*100) if resistance and px else None
    q=n(d.get('quality')) or 0
    score=q*.42
    if rv is not None: score += min(25,max(0,(rv-1)*18))
    if ch is not None: score += min(12,abs(ch)*3)
    if dist is not None: score += 16 if dist<=.25 else 12 if dist<=.5 else 7 if dist<=1 else 0
    dep=d.get('market_depth') or {}; bp=n(dep.get('buy_pct'))
    if bp is not None: score += min(5,abs(bp-50)/10)
    score=round(clamp(score))
    if dist is None: stage='DISCOVERED' if score>=45 else 'WATCH'
    elif dist<-.15: stage='CONFIRMED' if rv is not None and rv>=1.5 else 'BREAKOUT ATTEMPT'
    elif dist<=.25: stage='TRIGGER READY' if rv is not None and rv>=1.5 else 'ATTACKING'
    elif dist<=.75: stage='BUILDING'
    else: stage='DISCOVERED'
    return {'symbol':x.get('symbol'),'sector':x.get('sector') or 'OTHER','ltp':px,'change_pct':ch,'rvol':rv,'volume':vol,
            'resistance':resistance,'distance_pct':round(dist,3) if dist is not None else None,'stage':stage,'evidence_score':score,
            'action':d.get('action') or 'WAIT','volume_state':d.get('volume_state') or ('RVOL N/A' if rv is None else 'NORMAL'),
            'data_ready':{'price':px is not None,'rvol':rv is not None,'structure':resistance is not None,'depth':bool(dep)},
            'note':'Evidence score, not win probability.'}

def oi_spurts(market:Dict[str,Any]):
    out=[]
    for x in market.get('sector_heatmap') or []:
        p=n(x.get('change_pct')); oi=n(x.get('oi_change_pct') or x.get('futures_oi_change_pct')); v=n(x.get('volume'))
        if p is None or oi is None: continue
        if p>0 and oi>0:s='LONG BUILDUP'
        elif p<0 and oi>0:s='SHORT BUILDUP'
        elif p>0 and oi<0:s='SHORT COVERING'
        else:s='LONG UNWINDING'
        out.append({'symbol':x.get('symbol'),'price_change_pct':p,'oi_change_pct':oi,'volume':v,'state':s,'score':round(clamp(abs(oi)*5+abs(p)*8))})
    return sorted(out,key=lambda z:z['score'],reverse=True)[:25]

def build_v55(market:Dict[str,Any], v53:Optional[Dict[str,Any]]=None)->Dict[str,Any]:
    dec={x.get('symbol'):x for x in ((v53 or {}).get('one_decision') or [])}
    rows=[breakout_row(x,dec.get(x.get('symbol')) or {}) for x in (market.get('sector_heatmap') or []) if x.get('live')]
    rows.sort(key=lambda z:z['evidence_score'],reverse=True)
    stages=['CONFIRMED','TRIGGER READY','ATTACKING','BUILDING','DISCOVERED','WATCH']
    counts={s:sum(1 for r in rows if r['stage']==s) for s in stages}
    coverage={'universe':len(market.get('sector_heatmap') or []),'live_quotes':len(rows),'rvol_ready':sum(r['data_ready']['rvol'] for r in rows),
              'structure_ready':sum(r['data_ready']['structure'] for r in rows),'depth_ready':sum(r['data_ready']['depth'] for r in rows)}
    return {'version':'55.0','title':'Powerhouse AI V55 — Breakout Intelligence Engine','generated_at':time.time(),'read_only':True,
            'breakout_hunter':{'rows':rows,'counts':counts,'best_now':[r for r in rows if r['stage'] in ('CONFIRMED','TRIGGER READY','ATTACKING')][:5]},
            'oi_spurts':oi_spurts(market),'scanner_health':coverage,
            'diagnostics':{'rvol_missing':coverage['live_quotes']-coverage['rvol_ready'],'structure_missing':coverage['live_quotes']-coverage['structure_ready'],
              'message':'Zero breakout is trustworthy only when live/RVOL/structure coverage is healthy.'},
            'rules':{'stages':['DISCOVERED','BUILDING','ATTACKING','TRIGGER READY','CONFIRMED'],'truth':'Missing RVOL/OI/levels remain unavailable; no fabricated signals.'}}
