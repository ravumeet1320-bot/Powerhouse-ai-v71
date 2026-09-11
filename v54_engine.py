from __future__ import annotations
"""Powerhouse AI V54 — Visual Intelligence & Decision Flow layer.
Read-only analytics. Heatmaps and visual pressure scores are descriptive evidence, not profit probabilities.
Missing inputs stay unavailable rather than being fabricated.
"""
from typing import Any, Dict, List, Optional
import math, time


def num(v):
    try:
        if v is None or v == "": return None
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None

def clamp(x,a=0,b=100): return max(a,min(b,x))
def pct(a,b):
    a=num(a); b=num(b)
    return ((a-b)/b*100) if a is not None and b not in (None,0) else None

def depth_ratio(bq,aq):
    bq=num(bq); aq=num(aq)
    t=(bq or 0)+(aq or 0)
    return round((bq or 0)/t*100,1) if t else None

def leg(row:Dict[str,Any], side:str)->Dict[str,Any]:
    p='c' if side=='CE' else 'p'
    ltp=num(row.get(p+'ltp')); bid=num(row.get(p+'bid')); ask=num(row.get(p+'ask'))
    spread=(ask-bid) if bid is not None and ask is not None and ask>=bid else None
    spread_pct=(spread/ltp*100) if spread is not None and ltp else None
    levels=row.get(p+'depth') or []
    if levels:
        bq=sum(num(z.get('bid_qty')) or 0 for z in levels); aq=sum(num(z.get('ask_qty')) or 0 for z in levels)
    else:
        bq=num(row.get(p+'bidq')); aq=num(row.get(p+'askq'))
    br=depth_ratio(bq,aq)
    oi=num(row.get(p+'oi')); doi=num(row.get(p+'chg')); vol=num(row.get(p+'vol')); iv=num(row.get(p+'iv'))
    v1=num(row.get(p+'v1')); v3=num(row.get(p+'v3')); v5=num(row.get(p+'v5')); oivel=num(row.get(p+'oivel')); prem=num(row.get(p+'prem'))
    delta=num(row.get(p+'_delta')); gamma=num(row.get(p+'_gamma')); theta=num(row.get(p+'_theta')); vega=num(row.get(p+'_vega'))
    # Activity score deliberately describes observable chain quality/activity only.
    act=0.0
    if vol is not None: act += min(28, math.log10(max(vol,1)+1)*7)
    if oi is not None: act += min(24, math.log10(max(oi,1)+1)*5)
    if doi is not None: act += min(14, abs(doi)*0.025)
    if br is not None: act += min(12, abs(br-50)*0.45)
    if spread_pct is not None: act += max(0,12-min(12,spread_pct*8))
    if v1 is not None or v3 is not None or v5 is not None: act += 5
    return {"side":side,"ltp":ltp,"bid":bid,"ask":ask,"spread":round(spread,3) if spread is not None else None,
            "spread_pct":round(spread_pct,3) if spread_pct is not None else None,"bid_qty":bq,"ask_qty":aq,
            "bid_pct":br,"ask_pct":round(100-br,1) if br is not None else None,"depth_levels":levels,"oi":oi,"delta_oi":doi,
            "volume":vol,"iv":iv,"delta":delta,"gamma":gamma,"theta":theta,"vega":vega,
            "v1":v1,"v3":v3,"v5":v5,"oi_velocity":oivel,"premium_momentum":prem,"activity_score":round(clamp(act))}

def option_heatmap(market:Dict[str,Any])->Dict[str,Any]:
    rows=[]; spot=num(market.get('spot'))
    for r in market.get('option_data') or []:
        strike=num(r.get('s') or r.get('strike') or r.get('strike_price'))
        if strike is None: continue
        ce=leg(r,'CE'); pe=leg(r,'PE')
        dist=abs(strike-spot)/spot*100 if spot else None
        rows.append({"strike":strike,"atm":bool(dist is not None and dist<=0.35),"distance_pct":round(dist,2) if dist is not None else None,"ce":ce,"pe":pe})
    rows.sort(key=lambda x:x['strike'])
    if not rows:
        return {"available":False,"rows":[],"note":"Index option chain unavailable."}
    ce_oi=sum(x['ce']['oi'] or 0 for x in rows); pe_oi=sum(x['pe']['oi'] or 0 for x in rows)
    ce_vol=sum(x['ce']['volume'] or 0 for x in rows); pe_vol=sum(x['pe']['volume'] or 0 for x in rows)
    ce_doi=sum(x['ce']['delta_oi'] or 0 for x in rows); pe_doi=sum(x['pe']['delta_oi'] or 0 for x in rows)
    def share(a,b): return round(a/(a+b)*100,1) if a+b else None
    return {"available":True,"rows":rows,"spot":spot,"expiry":market.get('expiry'),
            "summary":{"ce_oi_share":share(ce_oi,pe_oi),"pe_oi_share":share(pe_oi,ce_oi),
                       "ce_volume_share":share(ce_vol,pe_vol),"pe_volume_share":share(pe_vol,ce_vol),
                       "ce_delta_oi":round(ce_doi,2),"pe_delta_oi":round(pe_doi,2)},
            "semantics":"Heatmap intensity reflects observable option-chain metrics; it is not participant identity or win probability."}

def stock_heatmap(market:Dict[str,Any], v53:Optional[Dict[str,Any]])->Dict[str,Any]:
    decisions={x.get('symbol'):x for x in ((v53 or {}).get('one_decision') or [])}
    rows=[]
    for x in market.get('sector_heatmap') or []:
        sym=x.get('symbol'); ch=num(x.get('change_pct')); bq=num(x.get('bid_qty')); aq=num(x.get('ask_qty'))
        d=decisions.get(sym) or {}; q=num(d.get('quality')); br=depth_ratio(bq,aq); rv=num(x.get('rvol'))
        rows.append({"symbol":sym,"sector":x.get('sector') or 'OTHER',"ltp":num(x.get('ltp')),"change_pct":round(ch,3) if ch is not None else None,
                     "volume":num(x.get('volume')),"rvol":rv,"bid_pct":br,"ask_pct":round(100-br,1) if br is not None else None,
                     "setup_quality":round(q) if q is not None else None,"action":d.get('action') or 'WAIT',
                     "volume_state":d.get('volume_state') or ('RVOL N/A' if rv is None else 'NORMAL'),
                     "breakout_52w":(d.get('breakout_52w') or {}).get('state') or 'N/A',"live":bool(x.get('live'))})
    rows.sort(key=lambda z:((z['sector'] or ''),-(z['change_pct'] if z['change_pct'] is not None else -999)))
    return {"available":bool(rows),"rows":rows,"metrics":["move","volume","depth","setup","52w"],
            "note":"RVOL and 52-week fields remain N/A until legitimate baselines/levels are connected."}

def visual_bars(market:Dict[str,Any], v53:Optional[Dict[str,Any]], opt:Dict[str,Any])->List[Dict[str,Any]]:
    bars=[]
    stocks=[x for x in market.get('sector_heatmap') or [] if x.get('live') and num(x.get('change_pct')) is not None]
    if stocks:
        adv=sum(1 for x in stocks if num(x.get('change_pct'))>0); breadth=round(adv/len(stocks)*100,1)
        bars.append({"key":"breadth","label":"Market breadth","left_label":"Bearish","right_label":"Bullish","value":breadth,"source":"connected stock universe"})
    s=(opt.get('summary') or {}) if opt.get('available') else {}
    if s.get('ce_volume_share') is not None:
        bars.append({"key":"option_volume","label":"Option volume share","left_label":"CE","right_label":"PE","value":s.get('pe_volume_share'),"left_value":s.get('ce_volume_share'),"right_value":s.get('pe_volume_share'),"source":"visible index option chain"})
    if s.get('ce_oi_share') is not None:
        bars.append({"key":"option_oi","label":"Option OI share","left_label":"CE","right_label":"PE","value":s.get('pe_oi_share'),"left_value":s.get('ce_oi_share'),"right_value":s.get('pe_oi_share'),"source":"visible index option chain"})
    best=((v53 or {}).get('best_now') or [None])[0]
    if best:
        q=num(best.get('quality'))
        bars.append({"key":"setup","label":f"{best.get('symbol')} setup quality","left_label":"Weak","right_label":"Strong","value":round(q or 0,1),"source":"evidence quality; not profit probability"})
    return bars

def decision_flow(v53:Optional[Dict[str,Any]], market:Dict[str,Any])->Dict[str,Any]:
    best=((v53 or {}).get('best_now') or [None])[0]
    if not best:
        return {"status":"WAIT","symbol":None,"nodes":[
            {"label":"Fresh data","state":"PASS" if market.get('last_tick_epoch') else "WAIT"},
            {"label":"Candidate","state":"WAIT"},{"label":"Volume / structure","state":"WAIT"},{"label":"Liquidity","state":"WAIT"},{"label":"Red team","state":"WAIT"},{"label":"Final action","state":"WAIT"}]}
    fresh=(best.get('freshness') or {}).get('status')=='FRESH'; gate=(best.get('opportunity_filter') or {}).get('pass'); red=(best.get('red_team') or {}).get('verdict')
    dep=(best.get('market_depth') or {}).get('liquidity')
    return {"status":best.get('action') or 'WAIT',"symbol":best.get('symbol'),"nodes":[
        {"label":"Fresh data","state":"PASS" if fresh else "FAIL"},
        {"label":"Opportunity room","state":"PASS" if gate else "FAIL"},
        {"label":"Volume / structure","state":"PASS" if best.get('volume_state') not in (None,'NORMAL') else "REVIEW"},
        {"label":"Liquidity","state":"PASS" if dep=='GOOD' else "REVIEW"},
        {"label":"Red team","state":"PASS" if red=='SURVIVED' else "REVIEW" if red=='NEEDS CONFIRMATION' else "FAIL"},
        {"label":"Final action","state":best.get('action') or 'WAIT'}]}

def build_v54(market:Dict[str,Any], ai:Dict[str,Any], smart_money:Dict[str,Any], radar:Dict[str,Any], v53:Optional[Dict[str,Any]]=None)->Dict[str,Any]:
    opt=option_heatmap(market); stocks=stock_heatmap(market,v53)
    return {"version":"54.0","title":"Powerhouse AI V54 — Visual Intelligence Terminal","generated_at":time.time(),
            "read_only":True,"execution_enabled":False,"stock_heatmap":stocks,"index_options_heatmap":opt,
            "visual_bars":visual_bars(market,v53,opt),"decision_flow":decision_flow(v53,market),
            "stock_options_heatmap":{"mode":"ON_DEMAND","endpoint":"/api/v54/stock-option-heatmap","note":"Loaded only when a user selects an F&O stock; no continuous full-market option-chain polling."},
            "visual_policy":{"animations":"meaningful state transitions only","reduced_motion_supported":True,"scores":"evidence/activity quality only, never profit probability"},
            "truth":{"depth":"Displayed order-book liquidity only; not proof of participant identity or manipulation.","missing":"N/A / UNAVAILABLE rather than fabricated values."}}

def stock_option_heatmap(symbol:str, expiry:str, chain:List[Dict[str,Any]])->Dict[str,Any]:
    rows=[]
    spot=None
    for r in chain or []:
        strike=num(r.get('strike')); spot=num(r.get('spot')) or spot
        if strike is None: continue
        def compact_leg(src, side):
            src=src or {}; ltp=num(src.get('ltp')); bid=num(src.get('bid')); ask=num(src.get('ask'))
            spread=(ask-bid) if bid is not None and ask is not None and ask>=bid else None
            spread_pct=(spread/ltp*100) if spread is not None and ltp else None
            bq=num(src.get('bid_qty')); aq=num(src.get('ask_qty')); br=depth_ratio(bq,aq)
            oi=num(src.get('oi')); vol=num(src.get('volume')); doi=num(src.get('delta_oi')); iv=num(src.get('iv'))
            score=0.0
            if vol is not None: score+=min(30,math.log10(max(vol,1)+1)*7)
            if oi is not None: score+=min(28,math.log10(max(oi,1)+1)*5)
            if spread_pct is not None: score+=max(0,20-min(20,spread_pct*10))
            if br is not None: score+=min(12,abs(br-50)*.45)
            return {"side":side,"ltp":ltp,"bid":bid,"ask":ask,"spread":round(spread,3) if spread is not None else None,
                    "spread_pct":round(spread_pct,3) if spread_pct is not None else None,"bid_qty":bq,"ask_qty":aq,
                    "bid_pct":br,"ask_pct":round(100-br,1) if br is not None else None,"oi":oi,"delta_oi":doi,"volume":vol,"iv":iv,
                    "delta":num(src.get('delta')),"gamma":num(src.get('gamma')),"theta":num(src.get('theta')),"vega":num(src.get('vega')),
                    "activity_score":round(clamp(score))}
        ce=compact_leg(r.get('ce'),'CE'); pe=compact_leg(r.get('pe'),'PE')
        dist=abs(strike-spot)/spot*100 if spot else None
        rows.append({"strike":strike,"atm":bool(dist is not None and dist<=0.5),"distance_pct":round(dist,2) if dist is not None else None,"ce":ce,"pe":pe})
    rows.sort(key=lambda x:x['strike'])
    return {"available":bool(rows),"symbol":symbol,"spot":spot,"expiry":expiry,"rows":rows,"read_only":True,
            "semantics":"On-demand stock option heatmap from returned exchange/broker fields. Missing depth/Greeks remain N/A."}
