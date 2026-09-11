from __future__ import annotations
"""V60.2 Daily NIFTY Plan / level-and-scenario intelligence.
Inspired by the publicly observable daily/next-day NIFTY planning format of @BestTeacher-MA.
This module does not copy proprietary rules or claim to know unavailable video-only methods.
All outputs are read-only and use only verified fields in the current market snapshot.
"""
from typing import Any, Dict, List, Optional
import math, time


def n(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception: return None

def pct(a,b):
    if a is None or b in (None,0): return None
    return (a-b)/b*100

def _option_rows(market:Dict[str,Any])->List[Dict[str,Any]]:
    out=[]
    for r in market.get('option_data') or []:
        strike=n(r.get('s') if 's' in r else r.get('strike'))
        if strike is None: continue
        out.append({
            'strike':strike,
            'coi':n(r.get('coi')) or n((r.get('ce') or {}).get('oi')) or 0,
            'poi':n(r.get('poi')) or n((r.get('pe') or {}).get('oi')) or 0,
            'cchg':n(r.get('cchg')) or n((r.get('ce') or {}).get('delta_oi')),
            'pchg':n(r.get('pchg')) or n((r.get('pe') or {}).get('delta_oi')),
            'cvol':n(r.get('cvol')) or n((r.get('ce') or {}).get('volume')) or 0,
            'pvol':n(r.get('pvol')) or n((r.get('pe') or {}).get('volume')) or 0,
            'cltp':n(r.get('cltp')) or n((r.get('ce') or {}).get('ltp')),
            'pltp':n(r.get('pltp')) or n((r.get('pe') or {}).get('ltp')),
            'cbid':n(r.get('cbid')) or n((r.get('ce') or {}).get('bid')),
            'cask':n(r.get('cask')) or n((r.get('ce') or {}).get('ask')),
            'pbid':n(r.get('pbid')) or n((r.get('pe') or {}).get('bid')),
            'pask':n(r.get('pask')) or n((r.get('pe') or {}).get('ask')),
            'coivel':n(r.get('coivel')),
            'poivel':n(r.get('poivel')),
            'cprem':n(r.get('cprem')),
            'pprem':n(r.get('pprem')),
        })
    return out


def build_daily_plan(market:Dict[str,Any], v60:Optional[Dict[str,Any]]=None, volume:Optional[Dict[str,Any]]=None)->Dict[str,Any]:
    spot=n(market.get('spot'))
    vwap=n(market.get('vwap'))
    ctx=market.get('session_context') or {}
    day_open=n(ctx.get('day_open')); day_high=n(ctx.get('day_high')); day_low=n(ctx.get('day_low'))
    last_close=n(ctx.get('last_close')); orh=n(ctx.get('opening_range_high')); orl=n(ctx.get('opening_range_low'))
    chain=_option_rows(market)
    call_wall=max(chain,key=lambda r:r['coi']) if chain else None
    put_wall=max(chain,key=lambda r:r['poi']) if chain else None
    call_doi=max([r for r in chain if r['cchg'] is not None],key=lambda r:r['cchg'],default=None)
    put_doi=max([r for r in chain if r['pchg'] is not None],key=lambda r:r['pchg'],default=None)
    totc=sum(r['coi'] for r in chain); totp=sum(r['poi'] for r in chain)
    pcr=(totp/totc) if totc else n(market.get('official_pcr'))
    max_pain=n(market.get('official_max_pain'))

    ib=(market.get('index_brain') or {}).get(str(market.get('active_underlying') or 'NIFTY')) or {}
    direction=str(ib.get('direction') or 'NEUTRAL').upper()
    agreement=n(ib.get('agreement_pct')); fragility=n(ib.get('fragility_risk')); divergence=n(ib.get('divergence_risk'))

    bull_candidates=[x for x in (vwap,orh,day_open,last_close) if x is not None and (spot is None or x>=spot*0.995)]
    bear_candidates=[x for x in (vwap,orl,day_open,last_close) if x is not None and (spot is None or x<=spot*1.005)]
    # Prefer ORB when available, then VWAP/open. The zones are scenarios, not guaranteed support/resistance.
    bull_trigger=orh if orh is not None else (vwap if vwap is not None else (day_high if day_high is not None else spot))
    bear_trigger=orl if orl is not None else (vwap if vwap is not None else (day_low if day_low is not None else spot))
    if bull_trigger is not None and bear_trigger is not None and bull_trigger<bear_trigger:
        bull_trigger,bear_trigger=bear_trigger,bull_trigger

    gap=pct(day_open,last_close)
    gap_state='N/A' if gap is None else 'GAP UP' if gap>0.15 else 'GAP DOWN' if gap<-0.15 else 'FLAT OPEN'

    evidence=[]; bull=0; bear=0
    if spot is not None and vwap is not None:
        if spot>vwap: bull+=2; evidence.append('spot above VWAP')
        elif spot<vwap: bear+=2; evidence.append('spot below VWAP')
    if spot is not None and day_open is not None:
        if spot>day_open: bull+=1; evidence.append('spot above day open')
        elif spot<day_open: bear+=1; evidence.append('spot below day open')
    if direction=='BULL': bull+=2; evidence.append('index heavyweight brain bullish')
    elif direction=='BEAR': bear+=2; evidence.append('index heavyweight brain bearish')
    if pcr is not None:
        if pcr>=1.15: bull+=1; evidence.append('put OI share elevated')
        elif pcr<=0.85: bear+=1; evidence.append('call OI share elevated')
    cdoi=sum((r['cchg'] or 0) for r in chain); pdoi=sum((r['pchg'] or 0) for r in chain)
    if pdoi>cdoi*1.15: bull+=1; evidence.append('put ΔOI activity stronger')
    elif cdoi>pdoi*1.15: bear+=1; evidence.append('call ΔOI activity stronger')
    bias='BULLISH' if bull>=bear+2 else 'BEARISH' if bear>=bull+2 else 'BALANCED / WAIT'

    no_trade_low=min([x for x in (bear_trigger,vwap) if x is not None],default=None)
    no_trade_high=max([x for x in (bull_trigger,vwap) if x is not None],default=None)
    if no_trade_low is not None and no_trade_high is not None and no_trade_low==no_trade_high:
        pad=(spot or no_trade_low)*0.0015
        no_trade_low-=pad; no_trade_high+=pad

    strike_battle=[]
    if chain and spot is not None:
        nearest=sorted(chain,key=lambda r:abs(r['strike']-spot))[:7]
        for r in sorted(nearest,key=lambda x:x['strike']):
            ce_act=r['coi']+(r['cvol']*.25)+max(0,r['cchg'] or 0)
            pe_act=r['poi']+(r['pvol']*.25)+max(0,r['pchg'] or 0)
            side='CALL' if ce_act>pe_act*1.1 else 'PUT' if pe_act>ce_act*1.1 else 'BALANCED'
            strike_battle.append({'strike':r['strike'],'call_activity':round(ce_act,1),'put_activity':round(pe_act,1),'dominant':side,'ce_oi':r['coi'],'pe_oi':r['poi'],'ce_doi':r['cchg'],'pe_doi':r['pchg'],'ce_vol':r['cvol'],'pe_vol':r['pvol']})

    volsum=(volume or {}).get('summary') or {}
    premium_state='N/A'
    if chain:
        near=min(chain,key=lambda r:abs(r['strike']-(spot or r['strike'])))
        cp=near.get('cprem'); pp=near.get('pprem')
        if cp is not None or pp is not None:
            premium_state='EXPANDING' if max(cp or -999,pp or -999)>0 else 'COMPRESSING/FLAT'

    risk=[]
    if fragility is not None and fragility>=50:risk.append('heavyweight participation fragile')
    if divergence is not None and divergence>=50:risk.append('index divergence elevated')
    if agreement is not None and agreement<55:risk.append('heavyweight agreement weak')
    if spot is not None and vwap is not None and abs(spot-vwap)/spot<0.0015:risk.append('price too close to VWAP / chop risk')
    if not chain:risk.append('option-chain confirmation unavailable')

    plan_cards=[
        {'name':'BULL SCENARIO','trigger':bull_trigger,'condition':'Sustain above trigger + VWAP/structure confirmation','action':'BUY / BUY CE candidate only after firewall confirmation'},
        {'name':'BEAR SCENARIO','trigger':bear_trigger,'condition':'Sustain below trigger + VWAP/structure confirmation','action':'SELL / BUY PE candidate only after firewall confirmation'},
        {'name':'NO-TRADE ZONE','low':no_trade_low,'high':no_trade_high,'condition':'Inside zone or conflicting evidence','action':'WAIT'},
    ]

    return {
        'version':'60.2','title':'Daily NIFTY Plan & Scenario Intelligence','generated_at':time.time(),'read_only':True,'execution_enabled':False,
        'observable_channel_inspiration':{'channel':'@BestTeacher-MA','observed_public_pattern':'frequent NIFTY today/tomorrow view videos','implementation':'scenario-based daily/next-session plan; proprietary/unseen rules are not copied or invented'},
        'market_snapshot':{'spot':spot,'vwap':vwap,'day_open':day_open,'day_high':day_high,'day_low':day_low,'last_close':last_close,'opening_range_high':orh,'opening_range_low':orl,'gap_pct':round(gap,3) if gap is not None else None,'gap_state':gap_state,'max_pain':max_pain,'pcr':round(pcr,3) if pcr is not None else None},
        'bias':{'state':bias,'bull_votes':bull,'bear_votes':bear,'evidence':evidence,'heavyweight_agreement_pct':agreement,'fragility_risk':fragility,'divergence_risk':divergence},
        'plan_cards':plan_cards,
        'option_context':{'call_wall':call_wall['strike'] if call_wall else None,'put_wall':put_wall['strike'] if put_wall else None,'call_doi_wall':call_doi['strike'] if call_doi else None,'put_doi_wall':put_doi['strike'] if put_doi else None,'pcr':round(pcr,3) if pcr is not None else None,'max_pain':max_pain,'premium_state':premium_state,'strike_battle':strike_battle},
        'volume_context':{'active_shockers':volsum.get('active',0),'bullish_shockers':volsum.get('bullish',0),'bearish_shockers':volsum.get('bearish',0),'true_rvol_ready':volsum.get('true_rvol_ready',0)},
        'risk_flags':risk,
        'next_session_checklist':['Check gap vs previous close','Mark ORB high/low and VWAP','Confirm call/put OI walls and ΔOI migration','Check heavyweight direction/agreement','Check volume shockers and breadth','Avoid entry inside no-trade zone','Require liquidity + freshness + no-chase firewall'],
        'truth_policy':['This is a scenario plan, not a guaranteed forecast.','OI walls are context, not guaranteed support/resistance.','Public channel titles were observable; unavailable video-only proprietary rules were not inferred.','No automatic orders or broker execution.']
    }
