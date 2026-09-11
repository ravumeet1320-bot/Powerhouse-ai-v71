from __future__ import annotations
from typing import Any, Dict, List
import time


def safe(v, default=0.0):
    try:
        if v is None or v == "": return default
        return float(v)
    except Exception: return default

def clamp(x, lo, hi): return max(lo, min(hi, x))

def grade(q):
    return "A+" if q >= 88 else "A" if q >= 80 else "B+" if q >= 70 else "B" if q >= 60 else "WATCH"

def lifecycle(q, live=True):
    if not live: return "DATA WAIT"
    if q >= 88: return "TRIGGER READY"
    if q >= 82: return "READY"
    if q >= 70: return "ARMING"
    if q >= 60: return "BUILDING"
    return "WATCH"

def scenario_levels(spot, chg, side):
    if not spot: return {"entry_trigger":None,"sl":None,"t1":None,"t2":None,"note":"Spot unavailable"}
    risk_pct=clamp(.35+abs(chg)*.10,.35,.85); trigger_pct=clamp(.08+abs(chg)*.025,.08,.20); s=1 if side=="CE" else -1
    entry=spot*(1+s*trigger_pct/100); sl=entry*(1-s*risk_pct/100)
    return {"entry_trigger":round(entry,2),"sl":round(sl,2),"t1":round(entry*(1+s*(risk_pct*1.4)/100),2),"t2":round(entry*(1+s*(risk_pct*2.2)/100),2),"risk_pct":round(risk_pct,2),"note":"Analytical scenario levels; confirm live structure before use."}

def _market_state(bull, bear, moves):
    n=bull+bear
    if not n: return "DATA WAIT"
    breadth=(bull-bear)/n; avg=sum(abs(x) for x in moves)/max(1,len(moves))
    if abs(breadth)<.18 and avg<.55: return "COMPRESSION / RANGE"
    if breadth>.42: return "TRENDING UP"
    if breadth<-.42: return "TRENDING DOWN"
    if avg>1.25: return "VOLATILE / EXPANSION"
    return "MIXED / ROTATION"

def _maturity(q, move):
    a=abs(move)
    if q<60: return "WATCH"
    if q<70: return "FORMING"
    if a>2.8: return "LATE / CHASE RISK"
    if q>=88: return "MATURE"
    return "FRESH / ACTIVE"

def _flip(side, secavg):
    if side=="CE": return "Weakens if price loses trigger/VWAP context and sector breadth turns negative."
    return "Weakens if price reclaims trigger/VWAP context and sector breadth turns positive."

def build_opportunity_radar(market: Dict[str,Any], ai: Dict[str,Any], smart_money: Dict[str,Any]) -> Dict[str,Any]:
    raw=market.get("sector_heatmap") or []
    rows=[x for x in raw if x and x.get("live") and x.get("change_pct") is not None and x.get("ltp")]
    groups={}
    for r in rows: groups.setdefault(r.get("sector") or "Other",[]).append(r)
    sector_avg={k:sum(safe(x.get("change_pct")) for x in v)/max(1,len(v)) for k,v in groups.items()}
    bull=sum(safe(x.get("change_pct"))>0 for x in rows); bear=sum(safe(x.get("change_pct"))<0 for x in rows)
    breadth_ratio=(bull-bear)/max(1,len(rows)); candidates=[]
    for r in rows:
        chg=safe(r.get("change_pct")); side="CE" if chg>0 else "PE" if chg<0 else "WAIT"
        if side=="WAIT": continue
        sec=r.get("sector") or "Other"; sa=sector_avg.get(sec,0); aligned=(chg>0 and sa>0) or (chg<0 and sa<0)
        momentum=clamp(abs(chg)*24,0,45); q=clamp(38+momentum+(16 if aligned else 4)+clamp(abs(sa)*8,0,12),0,96)
        conflict=0 if aligned else 35
        reasons=[f"{chg:+.2f}% live move",f"{sec} {sa:+.2f}%"]+(["sector confirmation"] if aligned else ["sector divergence"])+(["momentum expansion"] if abs(chg)>=1 else [])
        candidates.append({"symbol":r.get("symbol"),"kind":"STOCK","sector":sec,"ltp":r.get("ltp"),"change_pct":round(chg,2),"side":side,"quality":round(q),"grade":grade(q),"lifecycle":lifecycle(q),"maturity":_maturity(q,chg),"chase_risk":"HIGH" if abs(chg)>2.8 else "MEDIUM" if abs(chg)>1.8 else "LOW","conflict":conflict,"reasons":reasons,"counter_signals":[] if aligned else ["sector not confirming stock direction"],"flip_condition":_flip(side,sa),"option_preference":f"{side} • ATM/near-ATM • liquid contract only","levels":scenario_levels(safe(r.get("ltp")),chg,side),"data_trust":100,"freshness":"LIVE"})
    code=market.get("active_underlying") or "NIFTY"; spot=safe(market.get("spot")); ai_side=ai.get("side") or "WAIT"
    if ai_side in ("CE","PE"):
        aq=clamp(safe(ai.get("confidence")),0,100); dq=clamp(safe(ai.get("data_quality"),90),0,100)
        candidates.append({"symbol":code,"kind":"INDEX","sector":"INDEX","ltp":spot,"change_pct":None,"side":ai_side,"quality":round(aq),"grade":grade(aq),"lifecycle":lifecycle(aq),"maturity":"MATURE" if aq>=88 else "FRESH / ACTIVE" if aq>=70 else "FORMING","chase_risk":"LOW","conflict":round(clamp(100-safe(ai.get("stability"),70),0,100)),"reasons":[str(x) for x in (ai.get("reasons") or [])[:4]] or ["multi-agent index confluence"],"counter_signals":[str(x) for x in (ai.get("risk_flags") or [])[:3]],"flip_condition":"Bias changes only after the opposing structure/flow confirmation stack takes control.","option_preference":f"{ai_side} • ranked liquid index option","levels":scenario_levels(spot,.8 if ai_side=='CE' else -.8,ai_side),"data_trust":round(dq),"freshness":"LIVE"})
    candidates.sort(key=lambda x:(x["quality"],abs(safe(x.get("change_pct")))),reverse=True)
    # Correlation-aware shortlist: one representative per sector+direction, plus active index.
    independent=[]; seen=set()
    for x in candidates:
        key=(x["sector"],x["side"]) if x["kind"]=="STOCK" else (x["symbol"],x["side"])
        if key in seen: continue
        seen.add(key); independent.append(x)
        if len(independent)>=5: break
    ready=[x for x in candidates if x["quality"]>=80]
    state=_market_state(bull,bear,[safe(x.get("change_pct")) for x in rows])
    market_bias="BULLISH" if breadth_ratio>.25 else "BEARISH" if breadth_ratio<-.25 else "MIXED"
    top=independent[0] if independent else None
    funnel={"observed":len(raw),"live":len(rows),"interesting":sum(x["quality"]>=60 for x in candidates),"high_quality":len(ready),"independent":len(independent),"best":(top or {}).get("symbol")}
    return {"version":"36.0","generated_at":time.time(),"market_state":state,"market_bias":market_bias,"breadth_score":round(breadth_ratio*100),"funnel":funnel,"coverage":{"live_stocks":len(rows),"configured_universe":len(raw),"sectors":len(groups)},"breadth":{"bullish":bull,"bearish":bear,"neutral":max(0,len(rows)-bull-bear)},"best_now":independent[:3],"independent":independent,"queue":candidates[:16],"alert_candidates":ready[:12],"decision":{"action":"WAIT" if not top or top["quality"]<80 else "REVIEW SETUP","reason":"No A/A+ independent setup passes the current quality gate." if not top or top["quality"]<80 else f"{top['symbol']} {top['side']} is the strongest independent analytical setup.","data_safe":bool(rows)},"policy":{"execution_enabled":False,"orders_enabled":False,"pnl_enabled":False,"quality_not_profit_probability":True,"coverage_note":"Ranks the connected live universe only; it does not claim complete NSE/F&O coverage or guaranteed opportunity detection."}}
