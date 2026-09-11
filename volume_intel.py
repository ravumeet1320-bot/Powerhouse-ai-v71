from __future__ import annotations
"""POWERHOUSE Volume Intelligence — read-only volume shocker / sustained activity radar.
Uses only verified snapshot fields. True RVOL is emitted only when the provider snapshot supplies it.
"""
from collections import defaultdict, deque
from typing import Any, Dict
import math, time

_HIST = defaultdict(lambda: deque(maxlen=24))

def num(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception: return None

def clamp(v,a=0,b=100): return max(a,min(b,v))

def build_volume_intelligence(market: Dict[str,Any]) -> Dict[str,Any]:
    now=time.time(); rows=[]
    src=market.get('sector_heatmap') or market.get('stocks') or []
    for raw in src:
        r=dict(raw); sym=str(r.get('symbol') or '').upper(); px=num(r.get('ltp')); vol=num(r.get('volume')); cp=num(r.get('change_pct'))
        if not sym or px is None: continue
        h=_HIST[sym]
        if vol is not None: h.append((now,vol,px))
        increments=[]
        for i in range(1,len(h)):
            dv=h[i][1]-h[i-1][1]
            if dv>=0: increments.append(dv)
        burst=None; sustained=None
        if len(increments)>=3:
            base=sum(increments[:-1])/max(1,len(increments)-1)
            burst=(increments[-1]/base) if base>0 else None
            sustained=sum(1 for x in increments[-3:] if x>0)==3
        rv=num(r.get('rvol'))
        bid=num(r.get('bid')); ask=num(r.get('ask')); spread=None
        if bid is not None and ask is not None and px: spread=max(0,(ask-bid)/px*100)
        score=0
        if rv is not None: score += min(45,max(0,(rv-1)*30))
        if burst is not None: score += min(30,max(0,(burst-1)*18))
        if cp is not None: score += min(15,abs(cp)*4)
        if sustained: score += 10
        state='NORMAL'
        if rv is not None and rv>=5: state='EXTREME VOLUME'
        elif rv is not None and rv>=3: state='VOLUME SHOCKER'
        elif rv is not None and rv>=2: state='VOLUME SURGE'
        elif burst is not None and burst>=2.5: state='LIVE VOLUME BURST'
        elif burst is not None and burst>=1.5: state='VOLUME AWAKENING'
        direction='UP' if (cp or 0)>0 else 'DOWN' if (cp or 0)<0 else 'FLAT'
        rows.append({
            'symbol':sym,'sector':r.get('sector'),'ltp':px,'change_pct':cp,'volume':vol,'rvol':rv,
            'live_burst_ratio':round(burst,2) if burst is not None else None,'sustained_volume':sustained,
            'spread_pct':round(spread,3) if spread is not None else None,'direction':direction,'state':state,
            'volume_quality_score':round(clamp(score)),'verified_rvol':rv is not None,
            'note':'RVOL uses provider field only; live burst compares recent observed volume increments in this server session.'
        })
    rows.sort(key=lambda x:(x['volume_quality_score'], x['rvol'] or 0, x['live_burst_ratio'] or 0), reverse=True)
    shock=[x for x in rows if x['state']!='NORMAL']
    bullish=[x for x in shock if x['direction']=='UP']
    bearish=[x for x in shock if x['direction']=='DOWN']
    return {
        'version':'60.1','read_only':True,'generated_at':now,
        'summary':{'scanned':len(rows),'active':len(shock),'bullish':len(bullish),'bearish':len(bearish),'true_rvol_ready':sum(1 for x in rows if x['verified_rvol'])},
        'shockers':shock[:60],'bullish_shockers':bullish[:30],'bearish_shockers':bearish[:30],'all_rows':rows[:120],
        'truth_policy':['High volume is not automatically bullish.','True RVOL is never fabricated.','Live burst is session-observed acceleration, not historical average volume.','No participant identity is inferred from anonymous volume.']
    }
