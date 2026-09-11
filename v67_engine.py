from __future__ import annotations
from typing import Any, Dict, List, Optional
import math, statistics, time


def _f(v, d=None):
    try:
        x=float(v)
        return x if math.isfinite(x) else d
    except Exception:
        return d

def _clamp(x,a=0.0,b=100.0): return max(a,min(b,x))

def _norm_candles(rows):
    out=[]
    for r in rows or []:
        if isinstance(r,dict):
            o,h,l,c=_f(r.get('open')),_f(r.get('high')),_f(r.get('low')),_f(r.get('close'))
            ts=r.get('ts') or r.get('timestamp')
            vol=_f(r.get('volume'))
        elif isinstance(r,(list,tuple)) and len(r)>=5:
            ts=r[0]; o,h,l,c=_f(r[1]),_f(r[2]),_f(r[3]),_f(r[4]); vol=_f(r[5]) if len(r)>5 else None
        else: continue
        if None in (o,h,l,c) or min(o,h,l,c)<=0: continue
        out.append({'ts':str(ts),'open':o,'high':h,'low':l,'close':c,'volume':vol})
    return out

def _atr(cs, p=14):
    if len(cs)<2:return None
    tr=[]
    for i in range(1,len(cs)):
        x,pc=cs[i],cs[i-1]['close']; tr.append(max(x['high']-x['low'],abs(x['high']-pc),abs(x['low']-pc)))
    z=tr[-p:] if len(tr)>=p else tr
    return sum(z)/len(z) if z else None

def _ema(vals,p):
    if not vals:return None
    k=2/(p+1); e=vals[0]
    for x in vals[1:]: e=x*k+e*(1-k)
    return e

def _pivots(cs,w=2):
    hs=[]; ls=[]
    for i in range(w,len(cs)-w):
        seg=cs[i-w:i+w+1]
        if cs[i]['high']>=max(x['high'] for x in seg):hs.append({'i':i,'v':cs[i]['high']})
        if cs[i]['low']<=min(x['low'] for x in seg):ls.append({'i':i,'v':cs[i]['low']})
    return hs,ls

def candlestick_forming(cs):
    if not cs:return []
    x=cs[-1]; o,h,l,c=x['open'],x['high'],x['low'],x['close']; rng=max(h-l,1e-9); body=abs(c-o); up=h-max(o,c); dn=min(o,c)-l
    out=[]
    def add(name,side,completion,reason):out.append({'name':name,'side':side,'stage':'FORMING / UNCONFIRMED','formation_quality':round(_clamp(completion),1),'reason':reason})
    if body/rng<=.18:add('DOJI CANDIDATE','NEUTRAL',100-(body/rng)*250,'small real body vs total range')
    if dn>=rng*.42 and up<=rng*.28:add('HAMMER FAMILY CANDIDATE','BULL',55+dn/rng*35,'lower wick developing while upper wick remains contained')
    if up>=rng*.42 and dn<=rng*.28:add('SHOOTING/INVERTED-HAMMER FAMILY','BEAR' if c<o else 'BULL',55+up/rng*35,'upper wick developing while lower wick remains contained')
    if len(cs)>=2:
        p=cs[-2]
        if c>=o and p['close']<p['open']:
            cover=max(0,min(c,p['open'])-max(o,p['close']))/max(abs(p['open']-p['close']),1e-9)
            if cover>.35:add('BULLISH ENGULFING CANDIDATE','BULL',45+cover*45,'current green body is progressively covering prior red body')
        if c<=o and p['close']>p['open']:
            cover=max(0,min(o,p['close'])-max(c,p['open']))/max(abs(p['open']-p['close']),1e-9)
            if cover>.35:add('BEARISH ENGULFING CANDIDATE','BEAR',45+cover*45,'current red body is progressively covering prior green body')
    return sorted(out,key=lambda x:x['formation_quality'],reverse=True)[:6]

def fibonacci_intelligence(cs, vwap=None, poc=None):
    if len(cs)<8:return {'available':False,'reason':'Need more candles'}
    z=cs[-80:]; hi=max(x['high'] for x in z); lo=min(x['low'] for x in z); hi_i=max(range(len(z)),key=lambda i:z[i]['high']); lo_i=min(range(len(z)),key=lambda i:z[i]['low'])
    direction='UP IMPULSE' if lo_i<hi_i else 'DOWN IMPULSE'; rng=hi-lo; last=z[-1]['close']
    if rng<=0:return {'available':False,'reason':'Flat range'}
    ratios=[.236,.382,.5,.618,.786]
    ext=[1.272,1.618,2.0,2.618]
    if direction=='UP IMPULSE':
        levels={str(r):hi-rng*r for r in ratios}; exts={str(r):lo+rng*r for r in ext}
    else:
        levels={str(r):lo+rng*r for r in ratios}; exts={str(r):hi-rng*r for r in ext}
    atr=_atr(z) or rng*.02; tol=max(atr*.22,last*.001)
    refs=[('VWAP',_f(vwap)),('POC',_f(poc))]
    clusters=[]
    for k,v in levels.items():
        hits=[n for n,q in refs if q is not None and abs(v-q)<=tol]
        if hits:clusters.append({'fib':k,'level':round(v,4),'confluence':hits})
    nearest=min(levels.items(),key=lambda kv:abs(kv[1]-last))
    return {'available':True,'anchor_low':lo,'anchor_high':hi,'direction':direction,'retracements':{k:round(v,4) for k,v in levels.items()},'extensions':{k:round(v,4) for k,v in exts.items()},'nearest_retracement':{'ratio':nearest[0],'level':round(nearest[1],4),'distance_pct':round(abs(last-nearest[1])/last*100,3)},'clusters':clusters,'swing_quality':'HIGH' if rng/max(atr,1e-9)>=6 else 'MEDIUM','note':'Auto-Fib uses the dominant observed swing in the loaded window; it is not a forecast.'}

def pattern_lifecycle(cs):
    if len(cs)<18:return []
    z=cs[-60:]; hs,ls=_pivots(z); last=z[-1]['close']; atr=_atr(z) or last*.003; tol=max(atr*.4,last*.0013); out=[]
    def add(name,side,stage,q,trigger=None,invalid=None,evidence=None):
        out.append({'pattern':name,'side':side,'stage':stage,'formation_quality':round(_clamp(q),1),'trigger':trigger,'invalidation':invalid,'evidence':evidence or []})
    # compression statistics
    recent=z[-12:]; prior=z[-24:-12] if len(z)>=24 else z[:-12]
    rr=max(x['high'] for x in recent)-min(x['low'] for x in recent); pr=max(x['high'] for x in prior)-min(x['low'] for x in prior) if prior else rr
    compression=1-rr/max(pr,1e-9)
    if compression>.22:add('VOLATILITY COMPRESSION','NEUTRAL','DEVELOPING',55+compression*40,max(x['high'] for x in recent),min(x['low'] for x in recent),[f'range contracted {compression*100:.0f}%'])
    if len(hs)>=3 and len(ls)>=3:
        h=[x['v'] for x in hs[-3:]]; l=[x['v'] for x in ls[-3:]]
        hflat=max(h)-min(h)<=tol*1.6; lflat=max(l)-min(l)<=tol*1.6; lup=l[2]>l[1]>l[0]; hdn=h[2]<h[1]<h[0]
        if hflat and lup:
            trig=sum(h)/3; dist=max(0,(trig-last)/max(last,1))*100; stage='TRIGGER NEAR' if dist<.35 else 'MATURE' if dist<.8 else 'DEVELOPING'; add('ASCENDING TRIANGLE','BULL',stage,86-min(25,dist*16),trig,l[-1],['flat resistance','rising swing lows',f'trigger distance {dist:.2f}%'])
        if lflat and hdn:
            trig=sum(l)/3; dist=max(0,(last-trig)/max(last,1))*100; stage='TRIGGER NEAR' if dist<.35 else 'MATURE' if dist<.8 else 'DEVELOPING'; add('DESCENDING TRIANGLE','BEAR',stage,86-min(25,dist*16),trig,h[-1],['flat support','falling swing highs',f'trigger distance {dist:.2f}%'])
        if hdn and lup:
            top=h[-1]; bot=l[-1]; width=max(top-bot,1e-9); mature=1-width/max(h[0]-l[0],width); add('SYMMETRICAL TRIANGLE','NEUTRAL','MATURE' if mature>.35 else 'DEVELOPING',60+mature*35,None,None,['lower highs','higher lows',f'convergence {mature*100:.0f}%'])
    # range attacks / level fatigue
    h20=max(x['high'] for x in z[-20:]); l20=min(x['low'] for x in z[-20:]); tests_h=sum(abs(x['high']-h20)<=tol for x in z[-20:]); tests_l=sum(abs(x['low']-l20)<=tol for x in z[-20:])
    if tests_h>=3 and last<h20:add('RESISTANCE FATIGUE / BREAKOUT BUILD','BULL','TRIGGER NEAR' if (h20-last)/last*100<.35 else 'DEVELOPING',55+min(35,tests_h*7),h20,l20,[f'{tests_h} resistance attacks'])
    if tests_l>=3 and last>l20:add('SUPPORT FATIGUE / BREAKDOWN BUILD','BEAR','TRIGGER NEAR' if (last-l20)/last*100<.35 else 'DEVELOPING',55+min(35,tests_l*7),l20,h20,[f'{tests_l} support attacks'])
    return sorted(out,key=lambda x:(x['stage']=='TRIGGER NEAR',x['formation_quality']),reverse=True)[:10]

def harmonic_candidates(cs):
    if len(cs)<30:return []
    hs,ls=_pivots(cs[-80:],2); piv=sorted(hs+ls,key=lambda x:x['i'])
    if len(piv)<4:return []
    p=piv[-5:]
    out=[]
    if len(p)>=4:
        vals=[x['v'] for x in p]
        legs=[vals[i+1]-vals[i] for i in range(len(vals)-1)]
        if len(legs)>=3 and abs(legs[0])>1e-9:
            abcd=abs(abs(legs[-1])/abs(legs[0])-1)
            if abcd<.28: out.append({'pattern':'AB=CD CANDIDATE','stage':'PRZ DEVELOPING','formation_quality':round(_clamp(88-abcd*100),1),'points':vals,'note':'Geometric candidate only; completion zone requires final leg confirmation.'})
    return out

def smart_money_advanced(snapshot:dict, base:Optional[dict]=None, chart:Optional[dict]=None):
    base=base or {}
    rows=snapshot.get('option_data') or []
    price=_f(snapshot.get('spot')); vwap=_f(snapshot.get('vwap'))
    bull=[]; bear=[]; unknown=[]
    # option chain evidence
    cb=sum(_f(r.get('coi'),0) or 0 for r in rows); pb=sum(_f(r.get('poi'),0) or 0 for r in rows)
    cd=sum(_f(r.get('cchg'),0) or 0 for r in rows); pd=sum(_f(r.get('pchg'),0) or 0 for r in rows)
    if pb>cb*1.08: bull.append(('PUT OI SUPPORT',12))
    if cb>pb*1.08: bear.append(('CALL OI PRESSURE',12))
    if pd>abs(cd)*1.08: bull.append(('PUT ΔOI ACCELERATION',12))
    if cd>abs(pd)*1.08: bear.append(('CALL ΔOI ACCELERATION',12))
    if price is not None and vwap is not None:
        (bull if price>=vwap else bear).append(('PRICE ABOVE VWAP' if price>=vwap else 'PRICE BELOW VWAP',9))
    # futures universe / stock rows where available
    sym=str(snapshot.get('active_underlying') or snapshot.get('underlying') or '').upper()
    fut_oi=_f(snapshot.get('futures_oi_change_pct'))
    change=_f(snapshot.get('change_pct'))
    if fut_oi is not None and change is not None:
        if fut_oi>0 and change>0: bull.append(('FUTURES LONG BUILDUP',15))
        elif fut_oi>0 and change<0: bear.append(('FUTURES SHORT BUILDUP',15))
        elif fut_oi<0 and change>0: bull.append(('SHORT COVERING',7))
        elif fut_oi<0 and change<0: bear.append(('LONG UNWINDING',7))
    # chart pre-move evidence
    if chart:
        pats=chart.get('forming_patterns') or []
        if pats:
            p=pats[0]
            if p.get('side')=='BULL': bull.append((f"{p.get('pattern')} {p.get('stage')}",10))
            elif p.get('side')=='BEAR': bear.append((f"{p.get('pattern')} {p.get('stage')}",10))
        ci=chart.get('candlestick_forming') or []
        if ci:
            x=ci[0]
            if x.get('side')=='BULL':bull.append((x.get('name'),5))
            elif x.get('side')=='BEAR':bear.append((x.get('name'),5))
    bs=sum(w for _,w in bull); br=sum(w for _,w in bear); den=max(bs+br,1); signed=(bs-br)/den
    pressure=round(_clamp(50+signed*45),1)
    if bs+br<12: state='INSUFFICIENT DATA'
    elif pressure>=76: state='AGGRESSIVE ACCUMULATION'
    elif pressure>=64: state='ACCUMULATION BUILDING'
    elif pressure>=57: state='STEALTH ACCUMULATION'
    elif pressure<=24: state='AGGRESSIVE DISTRIBUTION'
    elif pressure<=36: state='DISTRIBUTION BUILDING'
    elif pressure<=43: state='DISTRIBUTION RISK'
    else: state='CONFLICTED / ABSORPTION'
    counter=[x[0] for x in (bear if pressure>=50 else bull)][:6]
    return {'engine':'Smart Money Intelligence v67','state':state,'pressure_score':pressure,'bull_evidence':[x[0] for x in bull][:10],'bear_evidence':[x[0] for x in bear][:10],'counter_evidence':counter,'evidence_weight':bs+br,'base_footprint_score':base.get('footprint_score'),'identity':'ANONYMOUS MARKET FOOTPRINT','identity_policy':'Anonymous price/volume/OI/depth never identifies FII/DII/PRO. Named identity requires explicit verified disclosure.','lifecycle':['STEALTH ACCUMULATION','ACCUMULATION BUILDING','AGGRESSIVE ACCUMULATION','ABSORPTION','MARKUP / FOLLOW-THROUGH','DISTRIBUTION BUILDING','AGGRESSIVE DISTRIBUTION','SHORT BUILDUP','SHORT COVERING','LONG UNWINDING','CONFLICTED','INSUFFICIENT DATA']}

def build_chart_intelligence(rows, symbol='NIFTY', interval=5, snapshot=None, base_sm=None):
    cs=_norm_candles(rows); snapshot=snapshot or {}
    if not cs:return {'version':'67.0','symbol':symbol,'interval':interval,'candles':[],'status':'NO DATA'}
    closes=[x['close'] for x in cs]; atr=_atr(cs); ema9=_ema(closes,9); ema20=_ema(closes,20); ema50=_ema(closes,50); ema200=_ema(closes,200)
    vol=[x['volume'] for x in cs if x.get('volume') is not None]
    avgv=sum(vol[-20:])/len(vol[-20:]) if vol else None; rvol=(cs[-1].get('volume')/avgv) if avgv and cs[-1].get('volume') is not None else None
    fib=fibonacci_intelligence(cs,snapshot.get('vwap'),None)
    forming=pattern_lifecycle(cs); cforming=candlestick_forming(cs); harmonics=harmonic_candidates(cs)
    last=cs[-1]['close']; structure='BULL' if ema9 and ema20 and last>ema9>ema20 else 'BEAR' if ema9 and ema20 and last<ema9<ema20 else 'MIXED'
    breakout_room=None
    if forming and forming[0].get('trigger'):
        breakout_room=abs(forming[0]['trigger']-last)/last*100
    _vw=_f(snapshot.get('vwap'), last)
    maturity='EXTENDED' if atr and abs(last-_vw)/atr>2 else 'FRESH / NORMAL'
    out={'version':'67.0','symbol':symbol.upper(),'interval':interval,'candles':cs[-240:],'forming_patterns':forming,'candlestick_forming':cforming,'harmonics':harmonics,'fibonacci':fib,'market_structure':{'state':structure,'ema9':ema9,'ema20':ema20,'ema50':ema50,'ema200':ema200,'atr':atr,'rvol_local':rvol,'setup_maturity':maturity,'trigger_distance_pct':breakout_room},'pre_move_radar':{'pattern_stage':forming[0]['stage'] if forming else 'NONE','pattern':forming[0]['pattern'] if forming else None,'compression_present':any(x['pattern']=='VOLATILITY COMPRESSION' for x in forming),'trigger_near':any(x['stage']=='TRIGGER NEAR' for x in forming),'rvol_awakening':rvol is not None and rvol>=1.35,'freshness':maturity}}
    out['smart_money']=smart_money_advanced(snapshot,base_sm,out)
    out['truth_policy']=['Forming patterns are explicitly unconfirmed until rule-defined completion/trigger.','Formation quality is geometry/evidence quality, not win probability.','Fib levels are derived from observed swings, not future targets.','Smart-money identity is never inferred from anonymous exchange data.']
    return out

def build_v67(snapshot:dict, previous:dict|None=None):
    base=previous or {}
    sm=smart_money_advanced(snapshot, snapshot.get('_base_smart_money') or {}, None)
    return {'version':'67.0','name':'Advanced Chart Pattern + Smart Money Intelligence OS','smart_money_advanced':sm,'modules':{'multi_symbol_chart_workspace':True,'forming_candlestick_detection':True,'pre_pattern_lifecycle':True,'auto_fibonacci':True,'harmonic_candidate_scaffold':True,'pattern_trigger_invalidation':True,'smart_money_evidence_stack':True,'truth_safe_identity':True,'full_fno_scan_endpoint':True},'previous_version':base.get('version'),'read_only':True,'execution_enabled':False}
