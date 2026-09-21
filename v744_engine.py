
from __future__ import annotations
import math, statistics
from typing import Any, Iterable, Optional

VERSION="74.4"
RELEASE="POWERHOUSE-AI-V74.4-MASTER-REBUILD"

def f(v:Any, default:Optional[float]=None):
    try:
        if v is None or v=="": return default
        x=float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default

def clamp(v,lo=0.0,hi=100.0):
    x=f(v,0.0) or 0.0
    return max(lo,min(hi,x))

def pct(a,b):
    aa,bb=f(a),f(b)
    if aa is None or bb in (None,0): return None
    return (aa-bb)/abs(bb)*100.0

def normalize_candles(candles:Iterable[Any]):
    out=[]
    for c in candles or []:
        if isinstance(c,dict):
            ts=c.get("timestamp") or c.get("ts") or c.get("time")
            o=f(c.get("open") if c.get("open") is not None else c.get("o"))
            h=f(c.get("high") if c.get("high") is not None else c.get("h"))
            l=f(c.get("low") if c.get("low") is not None else c.get("l"))
            cl=f(c.get("close") if c.get("close") is not None else c.get("c"))
            vol=f(c.get("volume") if c.get("volume") is not None else c.get("v"),0.0) or 0.0
        elif isinstance(c,(list,tuple)) and len(c)>=5:
            ts=c[0]; o=f(c[1]); h=f(c[2]); l=f(c[3]); cl=f(c[4]); vol=f(c[5],0.0) if len(c)>5 else 0.0
            vol=vol or 0.0
        else: continue
        if None in (o,h,l,cl): continue
        if h<l: h,l=l,h
        out.append({"ts":ts,"open":o,"high":h,"low":l,"close":cl,"volume":vol})
    return out

def atr(candles,n=14):
    cs=normalize_candles(candles)
    if len(cs)<2: return None
    tr=[]; prev=cs[0]["close"]
    for x in cs[1:]:
        tr.append(max(x["high"]-x["low"],abs(x["high"]-prev),abs(x["low"]-prev))); prev=x["close"]
    vals=tr[-max(2,int(n)):]
    return statistics.fmean(vals) if vals else None

def compute_vwap(candles):
    cs=normalize_candles(candles); num=den=0.0; series=[]
    for x in cs:
        vol=max(0.0,f(x.get("volume"),0.0) or 0.0); typ=(x["high"]+x["low"]+x["close"])/3.0
        if vol>0: num+=typ*vol; den+=vol
        series.append({"ts":x.get("ts"),"vwap":(num/den if den>0 else None)})
    last=next((r["vwap"] for r in reversed(series) if r["vwap"] is not None),None)
    return {"value":last,"series":series,"source":"CANDLE_DERIVED" if cs else "UNAVAILABLE"}

def _body(x): return abs(x["close"]-x["open"])
def _range(x): return max(1e-12,x["high"]-x["low"])
def _upper(x): return x["high"]-max(x["open"],x["close"])
def _lower(x): return min(x["open"],x["close"])-x["low"]
def _bull(x): return x["close"]>x["open"]
def _bear(x): return x["close"]<x["open"]

def candle_pattern_scan(candles):
    cs=normalize_candles(candles)
    if not cs: return {"latest":[],"recent":[],"behaviour":{},"source":"UNAVAILABLE"}
    vols=[x["volume"] for x in cs[-30:] if x["volume"]>0]; med=statistics.median(vols) if vols else None
    a=atr(cs,14); recent=[]
    def add(name,bias,idx,strength,reason):
        recent.append({"name":name,"bias":bias,"index":idx,"ts":cs[idx].get("ts"),"strength":round(clamp(strength),1),"reason":reason})
    for i in range(max(0,len(cs)-12),len(cs)):
        x=cs[i]; rg=_range(x); body=_body(x); up=_upper(x); lo=_lower(x); br=body/rg
        vr=(x["volume"]/med) if med and x["volume"] else None; bonus=min(18,max(0,((vr or 1)-1)*12))
        if br<=.08: add("Doji","NEUTRAL",i,48+bonus,"Very small body / indecision.")
        if br<=.28 and up>=body*1.2 and lo>=body*1.2: add("Spinning Top","NEUTRAL",i,44+bonus,"Two-sided rejection.")
        if br>=.82 and up<=rg*.08 and lo<=rg*.08:
            add("Bullish Marubozu" if _bull(x) else "Bearish Marubozu" if _bear(x) else "Marubozu","BULLISH" if _bull(x) else "BEARISH" if _bear(x) else "NEUTRAL",i,68+bonus,"Large body with limited wick.")
        if lo>=max(body*2,rg*.45) and up<=rg*.18: add("Hammer / Bull Pin","BULLISH",i,62+bonus,"Strong lower-wick rejection.")
        if up>=max(body*2,rg*.45) and lo<=rg*.18: add("Shooting Star / Bear Pin","BEARISH",i,62+bonus,"Strong upper-wick rejection.")
        if i>=1:
            q=cs[i-1]
            if _bull(x) and _bear(q) and x["open"]<=q["close"] and x["close"]>=q["open"]: add("Bullish Engulfing","BULLISH",i,72+bonus,"Bull body engulfs prior bear body.")
            if _bear(x) and _bull(q) and x["open"]>=q["close"] and x["close"]<=q["open"]: add("Bearish Engulfing","BEARISH",i,72+bonus,"Bear body engulfs prior bull body.")
            if x["high"]<q["high"] and x["low"]>q["low"]: add("Inside Bar","NEUTRAL",i,52+bonus,"Compression inside prior range.")
            if x["high"]>q["high"] and x["low"]<q["low"]: add("Outside Bar","NEUTRAL",i,58+bonus,"Range expansion.")
        if i>=2:
            p2,p1=cs[i-2],cs[i-1]
            if _bear(p2) and _body(p1)<=_range(p1)*.35 and _bull(x) and x["close"]>(p2["open"]+p2["close"])/2: add("Morning Star Behaviour","BULLISH",i,74+bonus,"Three-candle recovery.")
            if _bull(p2) and _body(p1)<=_range(p1)*.35 and _bear(x) and x["close"]<(p2["open"]+p2["close"])/2: add("Evening Star Behaviour","BEARISH",i,74+bonus,"Three-candle rollover.")
        if i>=3 and rg<=min(_range(z) for z in cs[i-3:i+1]): add("NR4","NEUTRAL",i,55,"Narrowest range in 4 bars.")
        if i>=6 and rg<=min(_range(z) for z in cs[i-6:i+1]): add("NR7","NEUTRAL",i,62,"Narrowest range in 7 bars.")
    last=cs[-1]
    behaviour={"body_pct_of_range":round(_body(last)/_range(last)*100,1),"upper_wick_pct":round(_upper(last)/_range(last)*100,1),
               "lower_wick_pct":round(_lower(last)/_range(last)*100,1),"close_location_pct":round((last["close"]-last["low"])/_range(last)*100,1),
               "range_vs_atr":round(_range(last)/a,2) if a else None,"volume_vs_recent_median":round(last["volume"]/med,2) if med and last["volume"] else None,
               "direction":"BULL" if _bull(last) else "BEAR" if _bear(last) else "FLAT"}
    recent.sort(key=lambda z:(z["index"],z["strength"]),reverse=True)
    return {"latest":[z for z in recent if z["index"]==len(cs)-1],"recent":recent[:20],"behaviour":behaviour,"source":"CANDLE_DERIVED"}

def _pivots(cs,w=2):
    hi=[]; lo=[]
    for i in range(w,len(cs)-w):
        seg=cs[i-w:i+w+1]
        if cs[i]["high"]>=max(x["high"] for x in seg): hi.append({"i":i,"price":cs[i]["high"],"ts":cs[i].get("ts")})
        if cs[i]["low"]<=min(x["low"] for x in seg): lo.append({"i":i,"price":cs[i]["low"],"ts":cs[i].get("ts")})
    return hi,lo

def chart_pattern_scan(candles):
    cs=normalize_candles(candles)
    if len(cs)<12: return {"patterns":[],"trend":"INSUFFICIENT_DATA","source":"CANDLE_DERIVED"}
    use=cs[-100:]; highs,lows=_pivots(use,2); a=atr(use,14) or max(abs(use[-1]["close"])*.002,1e-9); patterns=[]
    def add(name,bias,state,strength,evidence,trigger=None):
        patterns.append({"name":name,"bias":bias,"state":state,"strength":round(clamp(strength),1),"evidence":evidence[:6],"trigger":trigger,"source":"CANDLE_DERIVED"})
    trend="RANGE/MIXED"
    if len(highs)>=2 and len(lows)>=2:
        if highs[-1]["price"]>highs[-2]["price"] and lows[-1]["price"]>lows[-2]["price"]: trend="UPTREND"
        elif highs[-1]["price"]<highs[-2]["price"] and lows[-1]["price"]<lows[-2]["price"]: trend="DOWNTREND"
    tol=a*.45
    if len(highs)>=2:
        h1,h2=highs[-2],highs[-1]
        if abs(h1["price"]-h2["price"])<=tol and h2["i"]-h1["i"]>=4:
            mids=[x for x in lows if h1["i"]<x["i"]<h2["i"]]; neck=min((x["price"] for x in mids),default=None)
            add("Double Top","BEARISH","NEAR BREAKDOWN" if neck and use[-1]["close"]<=neck+tol else "FORMING",72,["Twin swing highs","Neckline monitored"],neck)
    if len(lows)>=2:
        l1,l2=lows[-2],lows[-1]
        if abs(l1["price"]-l2["price"])<=tol and l2["i"]-l1["i"]>=4:
            mids=[x for x in highs if l1["i"]<x["i"]<l2["i"]]; neck=max((x["price"] for x in mids),default=None)
            add("Double Bottom","BULLISH","NEAR BREAKOUT" if neck and use[-1]["close"]>=neck-tol else "FORMING",72,["Twin swing lows","Neckline monitored"],neck)
    if len(use)>=12:
        old,new=use[-12:-6],use[-6:]; oldr=max(x["high"] for x in old)-min(x["low"] for x in old); newr=max(x["high"] for x in new)-min(x["low"] for x in new)
        if oldr>0 and newr/oldr<=.68:
            add("Volatility Compression","NEUTRAL","BREAKOUT WATCH",68,[f"Range contracted to {round(newr/oldr*100,1)}%"])
            if len(highs)>=2 and len(lows)>=2 and highs[-1]["price"]<highs[-2]["price"] and lows[-1]["price"]>lows[-2]["price"]:
                add("Symmetrical Triangle Behaviour","NEUTRAL","FORMING",66,["Lower swing highs","Higher swing lows"])
    if len(use)>=20:
        mv=pct(use[-1]["close"],use[-20]["close"]) or 0
        if abs(mv)>=1: add("Directional Channel Behaviour","BULLISH" if mv>0 else "BEARISH","ACTIVE",min(82,58+abs(mv)*7),[f"20-bar move {round(mv,2)}%",f"Swing trend {trend}"])
    patterns.sort(key=lambda z:z["strength"],reverse=True)
    return {"patterns":patterns[:12],"trend":trend,"source":"CANDLE_DERIVED"}

def level_map(candles,context=None):
    cs=normalize_candles(candles); context=context or {}
    if not cs: return {"support":None,"resistance":None,"vwap":None,"source":"UNAVAILABLE"}
    spot=cs[-1]["close"]; a=atr(cs,14) or max(abs(spot)*.002,1e-9); highs,lows=_pivots(cs[-100:],2)
    below=[x["price"] for x in lows if x["price"]<=spot]; above=[x["price"] for x in highs if x["price"]>=spot]
    support=max(below) if below else min(x["low"] for x in cs[-20:]); resistance=min(above) if above else max(x["high"] for x in cs[-20:])
    return {"spot":spot,"support":support,"resistance":resistance,"vwap":compute_vwap(cs)["value"],"prev_day_high":f(context.get("prev_day_high")),
            "prev_day_low":f(context.get("prev_day_low")),"prev_day_close":f(context.get("prev_day_close")),"day_open":f(context.get("day_open"),cs[0]["open"]),
            "day_high":f(context.get("day_high"),max(x["high"] for x in cs)),"day_low":f(context.get("day_low"),min(x["low"] for x in cs)),"atr":a,
            "source":"CANDLE_DERIVED+PROVIDER_CONTEXT"}

def behaviour_summary(candles,context=None):
    cs=normalize_candles(candles)
    if not cs: return {"status":"INSUFFICIENT_DATA","summary":[],"source":"UNAVAILABLE"}
    lv=level_map(cs,context); cp=candle_pattern_scan(cs); ch=chart_pattern_scan(cs); last=cs[-1]; obs=[]
    vw=f(lv.get("vwap")); pdh=f(lv.get("prev_day_high")); pdl=f(lv.get("prev_day_low")); sup=f(lv.get("support")); res=f(lv.get("resistance")); a=f(lv.get("atr"),1) or 1
    if vw is not None: obs.append("Above VWAP" if last["close"]>vw else "Below VWAP" if last["close"]<vw else "At VWAP")
    if pdh is not None and last["close"]>pdh: obs.append("Above previous-day high")
    elif pdl is not None and last["close"]<pdl: obs.append("Below previous-day low")
    if res is not None and 0<=res-last["close"]<=a*.35: obs.append("Resistance attack / breakout-near")
    if sup is not None and 0<=last["close"]-sup<=a*.35: obs.append("Support test / breakdown-near")
    rv=f((cp.get("behaviour") or {}).get("volume_vs_recent_median"))
    if rv is not None and rv>=2: obs.append(f"Volume burst {round(rv,2)}x vs recent median")
    for z in cp.get("latest") or []: obs.append(f"{z.get('name')} ({z.get('bias')})")
    for z in (ch.get("patterns") or [])[:2]: obs.append(f"{z.get('name')} — {z.get('state')}")
    return {"status":"READY","levels":lv,"candle_patterns":cp,"chart_patterns":ch,"summary":obs[:10],"source":"CANDLE_DERIVED+PROVIDER_CONTEXT"}

def liquidity_score(bid,ask,bid_qty=None,ask_qty=None,volume=None,oi=None):
    b,a=f(bid),f(ask); bq,aq=f(bid_qty),f(ask_qty); vol,op=f(volume),f(oi)
    mid=((a+b)/2) if a is not None and b is not None and a>=b and (a+b)>0 else None; spread=((a-b)/mid*100) if mid else None
    ss=35 if spread is None else clamp(100-spread*45); depth=(bq or 0)+(aq or 0); ds=clamp(math.log10(1+depth)*22) if depth>0 else 35
    vs=clamp(math.log10(1+max(0,vol or 0))*14) if vol is not None else 35; os=clamp(math.log10(1+max(0,op or 0))*12) if op is not None else 35
    score=clamp(ss*.46+ds*.22+vs*.18+os*.14)
    ex="MARKET OK" if score>=80 and spread is not None and spread<=.35 else "LIMIT PREFERRED" if score>=62 and spread is not None and spread<=.8 else "LIMIT ONLY" if score>=42 else "DO NOT ENTER"
    return {"score":round(score,1),"spread_pct":round(spread,3) if spread is not None else None,"bid":b,"ask":a,"bid_qty":bq,"ask_qty":aq,"depth_total":depth or None,"execution_class":ex}

def chain_summary(chain,previous=None):
    rows=list((chain or {}).get("chain") or []); spot=f((chain or {}).get("spot")); previous=previous or {}
    prev_by={f(x.get("strike")):x for x in previous.get("strikes",[]) if f(x.get("strike")) is not None}; strikes=[]; tco=tpo=tcd=tpd=tcv=tpv=0.0
    for r in rows:
        strike=f(r.get("strike")); ce,pe=(r.get("ce") or {}),(r.get("pe") or {})
        coi,poi=f(ce.get("oi"),0) or 0,f(pe.get("oi"),0) or 0; cp,pp=f(ce.get("prev_oi"),coi) or coi,f(pe.get("prev_oi"),poi) or poi
        cd,pd=coi-cp,poi-pp; cv,pv=f(ce.get("volume"),0) or 0,f(pe.get("volume"),0) or 0
        tco+=coi;tpo+=poi;tcd+=cd;tpd+=pd;tcv+=cv;tpv+=pv
        old=prev_by.get(strike) or {}; oce,ope=old.get("ce") or {},old.get("pe") or {}
        strikes.append({"strike":strike,"ce":{**ce,"oi_change":cd,"premium_change_since_pulse_pct":pct(ce.get("ltp"),oce.get("ltp")),"liquidity":liquidity_score(ce.get("bid"),ce.get("ask"),ce.get("bid_qty"),ce.get("ask_qty"),cv,coi)},
                        "pe":{**pe,"oi_change":pd,"premium_change_since_pulse_pct":pct(pe.get("ltp"),ope.get("ltp")),"liquidity":liquidity_score(pe.get("bid"),pe.get("ask"),pe.get("bid_qty"),pe.get("ask_qty"),pv,poi)}})
    atm=min(strikes,key=lambda x:abs((x.get("strike") or 0)-spot),default=None) if spot is not None else None
    old_co,old_po=f(previous.get("total_call_oi")),f(previous.get("total_put_oi")); old_cv,old_pv=f(previous.get("total_call_volume")),f(previous.get("total_put_volume"))
    pulse={"call_oi_change_since_pulse":tco-old_co if old_co is not None else None,"put_oi_change_since_pulse":tpo-old_po if old_po is not None else None,
           "call_volume_change_since_pulse":tcv-old_cv if old_cv is not None else None,"put_volume_change_since_pulse":tpv-old_pv if old_pv is not None else None}
    atmce=(atm or {}).get("ce") or {}; atmpe=(atm or {}).get("pe") or {}
    def st(label,oi_delta,prem):
        if oi_delta is None:return f"{label} DATA WARMING"
        if oi_delta>0 and prem is not None and prem>0:return f"{label} BUYING / LONG BUILDUP"
        if oi_delta>0 and prem is not None and prem<0:return f"{label} WRITING / SHORT BUILDUP"
        if oi_delta<0 and prem is not None and prem>0:return f"{label} SHORT COVERING"
        if oi_delta<0 and prem is not None and prem<0:return f"{label} LONG UNWINDING"
        return f"{label} OI BUILDING" if oi_delta>0 else f"{label} OI UNWINDING" if oi_delta<0 else f"{label} STABLE"
    ce_state=st("CALL",pulse["call_oi_change_since_pulse"],f(atmce.get("premium_change_since_pulse_pct"))); pe_state=st("PUT",pulse["put_oi_change_since_pulse"],f(atmpe.get("premium_change_since_pulse_pct")))
    near=sorted(strikes,key=lambda x:abs((x.get("strike") or 0)-(spot or 0)))[:14] if spot is not None else strikes[:14]; near.sort(key=lambda x:x.get("strike") or 0)
    liqs=[f(((x.get(side) or {}).get("liquidity") or {}).get("score")) for x in near for side in ("ce","pe")]; liqs=[x for x in liqs if x is not None]
    return {"spot":spot,"expiry":(chain or {}).get("expiry"),"total_call_oi":tco,"total_put_oi":tpo,"total_call_oi_change":tcd,"total_put_oi_change":tpd,
            "total_call_volume":tcv,"total_put_volume":tpv,"pcr_oi":tpo/tco if tco else None,"pcr_volume":tpv/tcv if tcv else None,
            "oi_diff_put_minus_call":tpo-tco,"oi_change_diff_put_minus_call":tpd-tcd,"atm":atm,
            "call_wall":max(strikes,key=lambda x:f((x.get("ce") or {}).get("oi"),0) or 0,default=None),
            "put_wall":max(strikes,key=lambda x:f((x.get("pe") or {}).get("oi"),0) or 0,default=None),
            "call_state":ce_state,"put_state":pe_state,"pulse":pulse,"liquidity_score":round(statistics.fmean(liqs),1) if liqs else None,
            "strikes":strikes,"near_atm_strikes":near,"source":(chain or {}).get("source") or "PROVIDER_OPTION_CHAIN","read_only":True}

def sudden_activity(current,previous=None):
    previous=previous or {}; sym=str(current.get("symbol") or "").upper(); ltp=f(current.get("ltp")); score=f(current.get("score"),f(current.get("pre_move_score"),0)) or 0
    stage=str(current.get("stage") or current.get("pre_move_stage") or "DISCOVERY").upper(); rvol=f(current.get("rvol")); volume=f(current.get("volume")); oldv=f(previous.get("volume"))
    vp=pct(volume,oldv) if volume is not None and oldv not in (None,0) else None; liq=liquidity_score(current.get("bid"),current.get("ask"),current.get("bid_qty"),current.get("ask_qty"),volume,current.get("futures_oi"))
    oldl=liquidity_score(previous.get("bid"),previous.get("ask"),previous.get("bid_qty"),previous.get("ask_qty"),previous.get("volume"),previous.get("futures_oi")) if previous else {}; ld=liq["score"]-oldl.get("score") if oldl.get("score") is not None else None
    op=pct(current.get("futures_oi"),previous.get("futures_oi")); pp=pct(ltp,previous.get("ltp")); events=[]
    def ev(k,p,t,v=None):events.append({"kind":k,"priority":p,"text":t,"value":v})
    if rvol is not None and rvol>=2:ev("VOLUME_BURST","P1" if rvol>=3 else "P2",f"Relative volume {round(rvol,2)}x",rvol)
    elif vp is not None and vp>=12:ev("VOLUME_ACCELERATION","P2",f"Volume accelerated {round(vp,1)}%",vp)
    if ld is not None and ld>=12:ev("LIQUIDITY_SURGE","P2",f"Liquidity +{round(ld,1)} points",ld)
    if ld is not None and ld<=-15:ev("LIQUIDITY_DRAIN","P1",f"Liquidity -{round(abs(ld),1)} points",ld)
    if op is not None and abs(op)>=.35:ev("FUTURES_OI_SHIFT","P2",f"Futures OI {'+' if op>0 else ''}{round(op,2)}%",op)
    if pp is not None and abs(pp)>=.22:ev("PRICE_VELOCITY","P2",f"Price pulse {'+' if pp>0 else ''}{round(pp,2)}%",pp)
    ps=str(previous.get("stage") or previous.get("pre_move_stage") or "").upper()
    if ps and ps!=stage:ev("STAGE_CHANGE","P1" if stage in {"TRIGGER NEAR","TRIGGER READY","HERO","ENTRY ACTIVE"} else "P2",f"{ps} → {stage}",stage)
    intensity=score*.35+(clamp(rvol/3*100)*.22 if rvol is not None else 0)+(clamp(abs(pp)/.5*100)*.18 if pp is not None else 0)+(clamp(abs(op)*100)*.15 if op is not None else 0)+(clamp(ld*3)*.10 if ld is not None and ld>0 else 0)
    return {"symbol":sym,"ltp":ltp,"stage":stage,"score":score,"intensity":round(clamp(intensity),1),"rvol":rvol,"volume_pulse_pct":round(vp,2) if vp is not None else None,
            "price_pulse_pct":round(pp,3) if pp is not None else None,"futures_oi_pulse_pct":round(op,3) if op is not None else None,
            "liquidity":liq,"liquidity_change":round(ld,1) if ld is not None else None,"events":events,"read_only":True}

def stock_trade_plan(candidate):
    sym=str(candidate.get("symbol") or "").upper(); ltp=f(candidate.get("ltp")); score=f(candidate.get("score"),f(candidate.get("pre_move_score"),0)) or 0
    raw=str(candidate.get("side") or candidate.get("direction") or candidate.get("bias") or "").upper(); ch=f(candidate.get("change_pct"),0) or 0
    side="BUY" if raw in {"CE","BUY","BULL","BULLISH","UP"} else "SELL" if raw in {"PE","SELL","BEAR","BEARISH","DOWN"} else "BUY" if ch>.35 else "SELL" if ch<-.35 else "WAIT"
    if side=="WAIT" or ltp is None:return {"symbol":sym,"instrument":"STOCK","action":"WAIT","reason":"Directional evidence not qualified","read_only":True}
    pdh,pdl=f(candidate.get("prev_day_high")),f(candidate.get("prev_day_low")); dh,dl=f(candidate.get("day_high")),f(candidate.get("day_low")); h20,l20=f(candidate.get("high_20d")),f(candidate.get("low_20d"))
    if side=="BUY":
        a=[x for x in (dh,pdh,h20) if x is not None and x>=ltp]; trigger=min(a) if a else None; b=[x for x in (pdl,dl) if x is not None and x<(trigger or ltp)]; sl=max(b) if b else None
    else:
        a=[x for x in (dl,pdl,l20) if x is not None and x<=ltp]; trigger=max(a) if a else None; b=[x for x in (pdh,dh) if x is not None and x>(trigger or ltp)]; sl=min(b) if b else None
    if trigger is None or sl is None or abs(trigger-sl)<=1e-9:return {"symbol":sym,"instrument":"STOCK","action":"WATCH","direction":side,"ltp":ltp,"score":score,"trigger":trigger,"sl":sl,"reason":"Verified trigger/SL levels incomplete","read_only":True}
    risk=abs(trigger-sl); sign=1 if side=="BUY" else -1; tg={"t1":trigger+sign*risk*1.5,"t2":trigger+sign*risk*2,"t3":trigger+sign*risk*3}
    status="READY" if score>=72 and abs((trigger-ltp)/ltp*100)<=.35 else "TRIGGER NEAR" if score>=60 else "WATCH"
    liq=liquidity_score(candidate.get("bid"),candidate.get("ask"),candidate.get("bid_qty"),candidate.get("ask_qty"),candidate.get("volume"),candidate.get("futures_oi"))
    return {"symbol":sym,"instrument":"STOCK","action":side if status=="READY" else "WATCH","direction":side,"status":status,"ltp":ltp,"trigger":trigger,"sl":sl,"targets":tg,"score":score,"liquidity":liq,"read_only":True}
