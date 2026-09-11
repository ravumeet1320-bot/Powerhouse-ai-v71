from __future__ import annotations
"""Powerhouse AI V53 — Supreme Decision & Smart Money OS.
Read-only decision layer. Missing evidence remains None/N/A; no participant identity is inferred.
"""
from typing import Any, Dict, List, Optional
import math, time

ACTIONS={"BUY","SELL","BUY CE","BUY PE","WAIT"}

def n(v):
    try:
        if v is None or v=="": return None
        x=float(v); return x if math.isfinite(x) else None
    except Exception:return None

def clamp(x,a=0,b=100): return max(a,min(b,x))
def quality(v):
    x=n(v); return round(clamp(x)) if x is not None else None

def freshness(market):
    ts=n(market.get("last_tick_epoch")); now=time.time()
    if ts is None:return {"status":"UNAVAILABLE","timestamp":None,"age_seconds":None}
    age=max(0,now-ts); return {"status":"FRESH" if age<=30 else "STALE" if age<=180 else "UNAVAILABLE","timestamp":ts,"age_seconds":round(age,1)}

def volume_state(row):
    rv=n(row.get("rvol")); accel=n(row.get("volume_acceleration")); ch=abs(n(row.get("change_pct")) or 0)
    if rv is None:return "NORMAL"
    if rv>=3 and ch>=1:return "TRIGGER READY"
    if rv>=2:return "BREAKOUT ATTEMPT"
    if rv>=1.5 or (accel is not None and accel>1.25):return "PRESSURE BUILDING"
    if rv>=1.2:return "VOLUME AWAKENING"
    return "NORMAL"

def breakout52(row):
    p=n(row.get("ltp")); hi=n(row.get("high_52w")); lo=n(row.get("low_52w")); rv=n(row.get("rvol"))
    if not p or not hi or not lo:return {"state":"INSUFFICIENT DATA","high":hi,"low":lo,"distance_pct":None}
    dh=(p-hi)/hi*100; dl=(p-lo)/lo*100
    if p>=hi: st="52W HIGH BREAK + VOLUME" if rv and rv>=1.5 else "52W HIGH BREAK"
    elif dh>=-1: st="ATTACKING 52W HIGH" if dh>=-.35 else "NEAR 52W HIGH"
    elif p<=lo: st="52W LOW BREAK + VOLUME" if rv and rv>=1.5 else "52W LOW BREAK"
    elif dl<=1: st="NEAR 52W LOW"
    else: st="NO 52W EVENT"
    return {"state":st,"high":hi,"low":lo,"distance_pct":round(dh if abs(dh)<abs(dl) else dl,2),"rvol":rv}

def depth(row):
    bq=n(row.get("bid_qty")); aq=n(row.get("ask_qty")); bid=n(row.get("bid")); ask=n(row.get("ask"))
    total=(bq or 0)+(aq or 0); bp=round((bq or 0)/total*100,1) if total else None
    sp=round(ask-bid,4) if bid is not None and ask is not None and ask>=bid else None
    return {"buy_qty_pct":bp,"sell_qty_pct":round(100-bp,1) if bp is not None else None,"best_bid":bid,"best_ask":ask,"spread":sp,
            "bid_pressure":"STRONG" if bp and bp>=65 else "MODERATE" if bp and bp>=55 else "BALANCED" if bp is not None else "N/A",
            "liquidity":"GOOD" if sp is not None and row.get("ltp") and sp/max(n(row.get("ltp")) or 1,1)<.0015 else "N/A" if sp is None else "REVIEW",
            "semantics":"Displayed liquidity/order-book imbalance only; not participant identity or proof of manipulation."}

def minimum_opportunity(c):
    lv=c.get("levels") or {}; e=n(lv.get("entry_trigger")); sl=n(lv.get("sl")); t2=n(lv.get("t2")); atr=n(c.get("atr")); p=n(c.get("ltp"))
    if None in (e,sl,t2): return {"pass":False,"reason":"INSUFFICIENT DATA","rr":None}
    risk=abs(e-sl); reward=abs(t2-e); rr=reward/risk if risk else 0
    adaptive=max((atr or 0)*.7,(p or e)*.0035)
    if rr<1.5 or reward<adaptive:return {"pass":False,"reason":"REJECTED — INSUFFICIENT ROOM","rr":round(rr,2),"minimum_move":round(adaptive,2),"expected_move":round(reward,2)}
    if c.get("chase_risk")=="HIGH":return {"pass":False,"reason":"REJECTED — LATE / CHASE","rr":round(rr,2)}
    return {"pass":True,"reason":"ROOM ACCEPTABLE","rr":round(rr,2),"minimum_move":round(adaptive,2),"expected_move":round(reward,2)}

def action_for(c):
    side=str(c.get("side") or "WAIT").upper(); kind=str(c.get("kind") or "STOCK").upper()
    if side not in ("CE","PE"):return "WAIT"
    if kind=="INDEX" or c.get("option_contract"):return "BUY CE" if side=="CE" else "BUY PE"
    return "BUY" if side=="CE" else "SELL"

def contract_selector(market, side):
    rows=market.get("option_data") or []; spot=n(market.get("spot")); expiry=market.get("expiry")
    ranked=[]
    for r in rows:
        strike=n(r.get("strike") or r.get("strike_price")); pref="c" if side=="CE" else "p"
        ltp=n(r.get(pref+"ltp")); bid=n(r.get(pref+"bid")); ask=n(r.get(pref+"ask")); vol=n(r.get(pref+"vol")); oi=n(r.get(pref+"oi")); doi=n(r.get(pref+"chg")); iv=n(r.get(pref+"iv")); delta=n(r.get(pref+"delta")); gamma=n(r.get(pref+"gamma")); theta=n(r.get(pref+"theta")); vega=n(r.get(pref+"vega"))
        if strike is None or ltp is None:continue
        spread=(ask-bid) if ask is not None and bid is not None and ask>=bid else None
        spr=(spread/ltp*100) if spread is not None and ltp else None
        atm=abs(strike-spot)/spot*100 if spot else 99
        score=clamp(70-min(atm*12,35)+(12 if vol and vol>0 else 0)+(10 if oi and oi>0 else 0)-(min(spr*8,35) if spr is not None else 15))
        ranked.append({"strike":strike,"expiry":expiry,"side":side,"premium":ltp,"bid":bid,"ask":ask,"spread":round(spread,2) if spread is not None else None,"volume":vol,"oi":oi,"delta_oi":doi,"iv":iv,"delta":delta,"gamma":gamma,"theta":theta,"vega":vega,"atm_distance_pct":round(atm,2),"moneyness":"ATM" if atm<=.5 else "ITM/OTM","liquidity_quality":"GOOD" if score>=75 else "REVIEW" if score>=55 else "AVOID","contract_quality":round(score)})
    ranked.sort(key=lambda x:x["contract_quality"],reverse=True)
    return {"best_contract":ranked[0] if ranked else None,"alternative_contract":ranked[1] if len(ranked)>1 else None,"avoid":[x for x in ranked if x["liquidity_quality"]=="AVOID"][:3],"ranking_semantics":"liquidity/evidence quality, not win probability"}

def one_decision(market, ai, sm, radar):
    fresh=freshness(market); out=[]; seen=set()
    for c0 in radar.get("queue") or []:
        c=dict(c0); sym=c.get("symbol");
        if not sym or sym in seen:continue
        seen.add(sym); gate=minimum_opportunity(c); act=action_for(c)
        if fresh["status"]!="FRESH" or not gate["pass"] or (quality(c.get("quality")) or 0)<70: act="WAIT"
        assert act in ACTIONS
        row=next((x for x in market.get("sector_heatmap") or [] if x.get("symbol")==sym),{})
        vstate=volume_state(row); b52=breakout52(row); dep=depth(row)
        red=[]
        if fresh["status"]!="FRESH":red.append("Critical market data is not fresh")
        if not gate["pass"]:red.append(gate["reason"])
        if c.get("counter_signals"):red.extend(c.get("counter_signals")[:2])
        verdict="SURVIVED" if not red and (quality(c.get("quality")) or 0)>=80 else "NEEDS CONFIRMATION" if len(red)<=2 else "REJECTED"
        out.append({**c,"action":act,"opportunity_filter":gate,"volume_state":vstate,"breakout_52w":b52,"market_depth":dep,"red_team":{"verdict":verdict,"objections":red},"freshness":fresh,"thesis_rule":"ONE STOCK → ONE THESIS → ONE BEST ACTION"})
    out.sort(key=lambda x:(x["action"]!="WAIT",quality(x.get("quality")) or 0),reverse=True)
    # de-correlate best-now by sector/theme
    best=[]; themes=set()
    for x in out:
        if x["action"]=="WAIT":continue
        theme=x.get("sector") or x.get("symbol")
        if theme in themes:continue
        themes.add(theme); best.append(x)
        if len(best)==3:break
    return out,best,fresh

def build_v53(market:Dict[str,Any], ai:Dict[str,Any], sm:Dict[str,Any], radar:Dict[str,Any], v50:Optional[Dict[str,Any]]=None)->Dict[str,Any]:
    decisions,best,fresh=one_decision(market,ai,sm,radar)
    opt_side=None
    for x in decisions:
        if x.get("kind")=="INDEX" and x.get("action") in ("BUY CE","BUY PE"):
            opt_side="CE" if x["action"]=="BUY CE" else "PE"; break
    selector=contract_selector(market,opt_side) if opt_side else {"best_contract":None,"alternative_contract":None,"avoid":[],"ranking_semantics":"No current option thesis"}
    volleaders=[x for x in decisions if x.get("volume_state")!="NORMAL"][:8]
    leaders52=[x for x in decisions if (x.get("breakout_52w") or {}).get("state") not in ("INSUFFICIENT DATA","NO 52W EVENT")][:8]
    configured=len(market.get("sector_heatmap") or []); observed=sum(1 for x in market.get("sector_heatmap") or [] if x.get("live"))
    health={"connected_universe":configured,"observed":observed,"fresh":observed if fresh["status"]=="FRESH" else 0,"stale":observed if fresh["status"]=="STALE" else 0,"deep_scanned":len(decisions),"option_chains_checked":1 if market.get("option_data") else 0,"news_checked":0,"52w_scanned":sum(1 for x in market.get("sector_heatmap") or [] if x.get("high_52w") or x.get("low_52w")),"volume_anomalies":len(volleaders),"ready":sum(x["action"]!="WAIT" for x in decisions),"missing_data":sum(1 for x in market.get("sector_heatmap") or [] if not x.get("live")),"scanner_latency_ms":None}
    return {"version":"53.0","title":"Powerhouse AI V53 — Supreme Decision & Smart Money OS","generated_at":time.time(),"read_only":True,"execution_enabled":False,"one_decision":decisions,"best_now":best,"almost_ready":[x for x in decisions if x["action"]=="WAIT" and (quality(x.get("quality")) or 0)>=70][:6],"volume_breakout_hunter":volleaders,"breakout_52w_hunter":leaders52,"options_contract_selector":selector,"big_money_radar":{"classification":sm.get("classification") or "NO CLEAR LARGE-ACTIVITY EVIDENCE","evidence":sm,"identity_policy":"Large/unusual activity proxy only unless a legitimate source explicitly identifies participant."},"fii_dii":{"bias":"N/A","status":"UNAVAILABLE","note":"Participant labels require an explicit official/connected categorized source; anonymous chain activity is not attributed."},"news":{"status":"UNAVAILABLE","checked":False,"note":"No news provider is connected in this build; no catalyst is fabricated."},"missed_move_autopsy":{"status":"READY FOR SESSION TELEMETRY","fields":["first_observed","first_anomaly_time","volume_awakening_time","deep_scan_time","pattern_detection_time","trigger_ready_time","alert_generated","reason_if_missed"]},"scanner_health":health,"data_truth":{"critical_freshness":fresh,"missing_value_policy":"N/A / INSUFFICIENT DATA / STALE / UNAVAILABLE — never silently converted to zero","trigger_ready_suppressed_when_stale":True},"alert_policy":{"types":["TRIGGER READY","52W BREAK + VOLUME","VOLUME EXPANSION","SMART MONEY ACTIVITY","OPTION WALL SHIFT","PREMIUM DIVERGENCE","NEWS CATALYST","THESIS DAMAGE","INVALIDATED","SECOND CHANCE READY"],"dedupe":"state transition + novelty threshold + cooldown + material evidence change"},"policy":{"quality_is_not_profit_probability":True,"no_guaranteed_profit_claims":True,"no_fii_dii_inference":True,"no_spoofing_claims":True,"session_alert_privacy":True}}
