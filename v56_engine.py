from __future__ import annotations
"""V56 Screener + OI Intelligence Engine.

Feature-equivalent research workflow inspired by common Indian-market screeners.
Read-only. It never places orders and never labels setup score as win probability.
"""
from typing import Any, Dict, List, Optional
import math, time


def num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def clamp(x,a=0,b=100): return max(a,min(b,x))


def _depth(row):
    b=num(row.get('bid_qty')); a=num(row.get('ask_qty'))
    if b is None or a is None or b+a<=0: return None
    return 100*b/(b+a)


def enrich_stock(x:Dict[str,Any], v55row:Optional[Dict[str,Any]]=None)->Dict[str,Any]:
    px=num(x.get('ltp')); cp=num(x.get('change_pct')); vol=num(x.get('volume')); rv=num(x.get('rvol'))
    h52=num(x.get('high_52w')); l52=num(x.get('low_52w')); dh=num(x.get('day_high') or x.get('high')); pdh=num(x.get('prev_day_high') or x.get('pdh'))
    res=next((z for z in (pdh,dh,h52) if z is not None and px is not None and z>=px*.98),None)
    dist=((res-px)/res*100) if res and px else None
    dp=_depth(x)
    score=0.0
    score += min(24,abs(cp or 0)*6)
    if rv is not None: score += min(26,max(0,(rv-1)*22))
    if dist is not None: score += 20 if dist <= .20 else 15 if dist <= .50 else 9 if dist <= 1 else 0
    if dp is not None: score += min(8,abs(dp-50)/4)
    if vol is not None and vol>0: score += 5
    score=round(clamp(score))
    stage=(v55row or {}).get('stage') or ('ATTACKING' if dist is not None and dist<=.25 else 'BUILDING' if dist is not None and dist<=1 else 'DISCOVERED')
    return {
        'symbol':x.get('symbol'),'sector':x.get('sector') or 'OTHER','ltp':px,'change_pct':cp,'volume':vol,'rvol':rv,
        'high_52w':h52,'low_52w':l52,'resistance':res,'distance_pct':round(dist,3) if dist is not None else None,
        'bid':num(x.get('bid')),'ask':num(x.get('ask')),'bid_qty':num(x.get('bid_qty')),'ask_qty':num(x.get('ask_qty')),
        'bid_pressure_pct':round(dp,1) if dp is not None else None,'stage':stage,'setup_score':score,
        'live':bool(x.get('live')),'data_ready':{'rvol':rv is not None,'52w':h52 is not None and l52 is not None,'structure':res is not None,'depth':dp is not None}
    }


def preset_scans(rows:List[Dict[str,Any]])->Dict[str,List[Dict[str,Any]]]:
    def top(fn,n=20): return sorted([r for r in rows if fn(r)], key=lambda r:r['setup_score'], reverse=True)[:n]
    return {
      'breakout_now': top(lambda r:r['stage'] in ('CONFIRMED','TRIGGER READY','BREAKOUT ATTEMPT')),
      'breakout_building': top(lambda r:r['stage'] in ('ATTACKING','BUILDING') or (r['distance_pct'] is not None and 0<=r['distance_pct']<=1)),
      'volume_surge': top(lambda r:r['rvol'] is not None and r['rvol']>=1.5),
      'high_rvol': top(lambda r:r['rvol'] is not None and r['rvol']>=2.0),
      'near_52w_high': top(lambda r:r['high_52w'] is not None and r['ltp'] is not None and 0 <= (r['high_52w']-r['ltp'])/r['high_52w']*100 <= 3),
      'depth_buy_pressure': top(lambda r:r['bid_pressure_pct'] is not None and r['bid_pressure_pct']>=60),
      'depth_sell_pressure': top(lambda r:r['bid_pressure_pct'] is not None and r['bid_pressure_pct']<=40),
      'momentum_up': top(lambda r:(r['change_pct'] or 0)>=1),
      'momentum_down': top(lambda r:(r['change_pct'] or 0)<=-1),
    }


def oi_spurts(market:Dict[str,Any])->List[Dict[str,Any]]:
    out=[]
    # Stock/futures rows if provider exposes OI change.
    for x in market.get('sector_heatmap') or []:
        p=num(x.get('change_pct')); oi=num(x.get('oi_change_pct') or x.get('futures_oi_change_pct'))
        if p is None or oi is None: continue
        if p>0 and oi>0: state='LONG BUILDUP'
        elif p<0 and oi>0: state='SHORT BUILDUP'
        elif p>0 and oi<0: state='SHORT COVERING'
        else: state='LONG UNWINDING'
        out.append({'symbol':x.get('symbol'),'price_change_pct':p,'oi_change_pct':oi,'state':state,'score':round(clamp(abs(oi)*6+abs(p)*10))})
    return sorted(out,key=lambda z:z['score'],reverse=True)


def option_chain_intel(market:Dict[str,Any])->Dict[str,Any]:
    chain=market.get('option_data') or []
    spot=num(market.get('spot'))
    rows=[]; ce_oi=pe_oi=ce_vol=pe_vol=0.0
    max_ce=max_pe=None
    for r in chain:
        strike=num(r.get('strike')); coi=num(r.get('coi')) or 0; poi=num(r.get('poi')) or 0; cv=num(r.get('cvol')) or 0; pv=num(r.get('pvol')) or 0
        cdoi=num(r.get('cdo') or r.get('c_delta_oi')); pdoi=num(r.get('pdo') or r.get('p_delta_oi'))
        ce_oi+=coi; pe_oi+=poi; ce_vol+=cv; pe_vol+=pv
        if max_ce is None or coi>max_ce['oi']: max_ce={'strike':strike,'oi':coi}
        if max_pe is None or poi>max_pe['oi']: max_pe={'strike':strike,'oi':poi}
        rows.append({'strike':strike,'atm': bool(spot and strike and abs(strike-spot)==min([abs((num(z.get('strike')) or 1e99)-spot) for z in chain] or [1e99])),
                     'ce_oi':coi,'pe_oi':poi,'ce_delta_oi':cdoi,'pe_delta_oi':pdoi,'ce_volume':cv,'pe_volume':pv,
                     'ce_iv':num(r.get('civ')),'pe_iv':num(r.get('piv')),'ce_ltp':num(r.get('cltp')),'pe_ltp':num(r.get('pltp')),
                     'ce_bid':num(r.get('cbid')),'ce_ask':num(r.get('cask')),'pe_bid':num(r.get('pbid')),'pe_ask':num(r.get('pask'))})
    pcr=(pe_oi/ce_oi) if ce_oi else None
    vpcr=(pe_vol/ce_vol) if ce_vol else None
    return {'rows':rows,'summary':{'spot':spot,'pcr_oi':round(pcr,3) if pcr is not None else None,'pcr_volume':round(vpcr,3) if vpcr is not None else None,
            'max_call_oi':max_ce,'max_put_oi':max_pe,'official_pcr':market.get('official_pcr'),'official_max_pain':market.get('official_max_pain')},
            'truth':'OI walls are context, not guaranteed support/resistance.'}


def apply_custom_scan(rows:List[Dict[str,Any]], field:str, op:str, value:float)->List[Dict[str,Any]]:
    allowed={'change_pct','rvol','volume','distance_pct','setup_score','bid_pressure_pct','ltp'}
    if field not in allowed: return []
    def ok(r):
        x=num(r.get(field))
        if x is None:return False
        return {'gt':x>value,'gte':x>=value,'lt':x<value,'lte':x<=value,'eq':x==value}.get(op,False)
    return sorted([r for r in rows if ok(r)], key=lambda r:r['setup_score'], reverse=True)


def build_v56(market:Dict[str,Any], v55:Optional[Dict[str,Any]]=None)->Dict[str,Any]:
    v55map={r.get('symbol'):r for r in (((v55 or {}).get('breakout_hunter') or {}).get('rows') or [])}
    rows=[enrich_stock(x,v55map.get(x.get('symbol'))) for x in (market.get('sector_heatmap') or []) if x.get('symbol')]
    rows.sort(key=lambda r:r['setup_score'],reverse=True)
    scans=preset_scans(rows)
    live=sum(1 for r in rows if r['live']); rvol=sum(1 for r in rows if r['data_ready']['rvol']); h52=sum(1 for r in rows if r['data_ready']['52w']); depth=sum(1 for r in rows if r['data_ready']['depth'])
    return {
      'version':'56.0','title':'Powerhouse AI V56 — Advanced Screener & OI Intelligence','generated_at':time.time(),'read_only':True,'execution_enabled':False,
      'advanced_screener':{'universe':rows,'presets':scans,'available_fields':['change_pct','rvol','volume','distance_pct','setup_score','bid_pressure_pct','ltp'],
          'operators':['gt','gte','lt','lte','eq'],'note':'Custom rules operate only on verified fields present in the live snapshot.'},
      'oi_spurts':oi_spurts(market),'option_chain_intelligence':option_chain_intel(market),
      'scanner_health':{'configured_symbols':len(rows),'live_quotes':live,'rvol_ready':rvol,'52w_ready':h52,'depth_ready':depth,
          'coverage_pct':round(100*live/len(rows),1) if rows else 0},
      'trade_finder':{'breakout_now':len(scans['breakout_now']),'building':len(scans['breakout_building']),'volume_surge':len(scans['volume_surge']),
          'best_now':scans['breakout_now'][:3] or scans['breakout_building'][:3]},
      'truth_policy':['Setup score is evidence quality, not win probability.','Missing RVOL/52W/OI remains unavailable.','No broker execution or automatic orders.']
    }
