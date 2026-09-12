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
    # Classical reversal/continuation structures. V71.3 scans more than the final pivot pair
    # so a small fresh swing does not erase a still-valid pattern.
    def between_low(a,b):
        aa,bb=sorted((a['i'],b['i'])); return min(x['low'] for x in z[aa:bb+1])
    def between_high(a,b):
        aa,bb=sorted((a['i'],b['i'])); return max(x['high'] for x in z[aa:bb+1])
    if len(hs)>=2:
        pair=None
        for bi in range(len(hs)-1,0,-1):
            for ai in range(bi-1,max(-1,bi-5),-1):
                if hs[bi]['i']-hs[ai]['i']>=3 and abs(hs[bi]['v']-hs[ai]['v'])<=tol*1.8:
                    pair=(hs[ai],hs[bi]); break
            if pair: break
        if pair:
            a,b=pair; neck=between_low(a,b); depth=min(a['v'],b['v'])-neck
            if depth>tol*1.1:
                stage='TRIGGER NEAR' if max(0,(last-neck)/max(last,1)*100)<.35 else 'MATURE'
                add('DOUBLE TOP','BEAR',stage,84,neck,max(a['v'],b['v']),[f'twin resistance {(a["v"]+b["v"])/2:.2f}',f'neckline {neck:.2f}'])
    if len(ls)>=2:
        pair=None
        for bi in range(len(ls)-1,0,-1):
            for ai in range(bi-1,max(-1,bi-5),-1):
                if ls[bi]['i']-ls[ai]['i']>=3 and abs(ls[bi]['v']-ls[ai]['v'])<=tol*1.8:
                    pair=(ls[ai],ls[bi]); break
            if pair: break
        if pair:
            a,b=pair; neck=between_high(a,b); depth=neck-max(a['v'],b['v'])
            if depth>tol*1.1:
                stage='TRIGGER NEAR' if max(0,(neck-last)/max(last,1)*100)<.35 else 'MATURE'
                add('DOUBLE BOTTOM','BULL',stage,84,neck,min(a['v'],b['v']),[f'twin support {(a["v"]+b["v"])/2:.2f}',f'neckline {neck:.2f}'])
    if len(hs)>=3:
        a,b,c=hs[-3],hs[-2],hs[-1]
        if abs(a['v']-c['v'])<=tol*2.1 and b['v']>max(a['v'],c['v'])+tol*.8:
            neck=(between_low(a,b)+between_low(b,c))/2
            add('HEAD & SHOULDERS','BEAR','TRIGGER NEAR' if abs(last-neck)/max(last,1)*100<.45 else 'MATURE',90,neck,b['v'],['balanced shoulders','dominant head',f'neckline {neck:.2f}'])
    if len(ls)>=3:
        a,b,c=ls[-3],ls[-2],ls[-1]
        if abs(a['v']-c['v'])<=tol*2.1 and b['v']<min(a['v'],c['v'])-tol*.8:
            neck=(between_high(a,b)+between_high(b,c))/2
            add('INVERSE H&S','BULL','TRIGGER NEAR' if abs(last-neck)/max(last,1)*100<.45 else 'MATURE',90,neck,b['v'],['balanced shoulders','dominant inverse head',f'neckline {neck:.2f}'])
    if len(z)>=24:
        prior=z[-24:-12]; recent=z[-12:]
        pr=max(x['high'] for x in prior)-min(x['low'] for x in prior)
        rr2=max(x['high'] for x in recent)-min(x['low'] for x in recent)
        if pr>0 and rr2/pr<.72:
            add('VOLATILITY COMPRESSION','NEUTRAL','DEVELOPING',70+min(18,(1-rr2/pr)*35),max(x['high'] for x in recent),min(x['low'] for x in recent),[f'range contracted {(1-rr2/pr)*100:.0f}%'])
        pole=z[-24]['close']; impulse=z[-14]['close']-pole; cons=z[-13:]
        cr=max(x['high'] for x in cons)-min(x['low'] for x in cons)
        if abs(impulse)>max((atr or last*.003)*4, last*.006) and cr<abs(impulse)*.70:
            side='BULL' if impulse>0 else 'BEAR'; name=f'{side} FLAG / PENNANT'
            trig=max(x['high'] for x in cons) if side=='BULL' else min(x['low'] for x in cons)
            inv=min(x['low'] for x in cons) if side=='BULL' else max(x['high'] for x in cons)
            add(name,side,'TRIGGER NEAR' if abs(last-trig)/max(last,1)*100<.35 else 'DEVELOPING',78,trig,inv,[f'impulse {impulse:+.2f}', 'compact consolidation'])
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


def big_money_entry_intelligence(cs):
    """Detect abnormal-volume accumulation/distribution footprints around a price level.

    This is intentionally identity-safe: it detects observable price/volume behaviour only.
    It must never claim that a named institution or "big money" participant traded.
    """
    n=len(cs or [])
    if n < 24:
        return {'available':False,'state':'INSUFFICIENT CANDLES','score':0,'identity_policy':'Price/volume footprint only; participant identity is unknown.'}
    events=[]
    start=max(20,n-72)
    # Exclude the currently-forming last bar as a spike candidate because its volume may be partial.
    for i in range(start,max(start,n-1)):
        x=cs[i]; vol=_f(x.get('volume'))
        if vol is None or vol <= 0: continue
        pv=[_f(q.get('volume')) for q in cs[max(0,i-20):i] if _f(q.get('volume')) is not None and _f(q.get('volume'))>0]
        if len(pv)<8: continue
        baseline=statistics.median(pv)
        if baseline<=0: continue
        rvol=vol/baseline
        atr=_atr(cs[max(0,i-24):i+1]) or max(x['high']-x['low'], x['close']*.003)
        rng=max(x['high']-x['low'],1e-9); body=abs(x['close']-x['open']); close_pos=(x['close']-x['low'])/rng
        pre=cs[max(0,i-12):i]
        if len(pre)<6: continue
        pre_high=max(q['high'] for q in pre); pre_low=min(q['low'] for q in pre)
        bull_impulse=x['close']>x['open'] and close_pos>=.62 and (rng>=atr*1.05 or body/rng>=.58)
        bear_impulse=x['close']<x['open'] and close_pos<=.38 and (rng>=atr*1.05 or body/rng>=.58)
        bull_break=x['close']>pre_high-atr*.08
        bear_break=x['close']<pre_low+atr*.08
        # Allow extreme volume absorption even when the spike candle itself is not a wide-range bar.
        if rvol < 1.8 and not (rvol>=1.5 and rng>=atr*1.6):
            continue
        sides=[]
        if bull_impulse or (rvol>=2.8 and close_pos>=.55): sides.append(('BULL',bull_break))
        if bear_impulse or (rvol>=2.8 and close_pos<=.45): sides.append(('BEAR',bear_break))
        for side,level_break in sides:
            post=cs[i+1:]
            level=(pre_high if side=='BULL' and level_break else pre_low if side=='BEAR' and level_break else (x['open']+x['close'])/2)
            zone_pad=atr*.18
            zone_low=level-zone_pad; zone_high=level+zone_pad
            invalid=(min(x['low'],zone_low-atr*.28) if side=='BULL' else max(x['high'],zone_high+atr*.28))
            hold_n=0; retests=0; valid_n=0
            for q in post:
                valid_n+=1
                if side=='BULL':
                    if q['close']>=zone_low: hold_n+=1
                    if q['low']<=zone_high and q['close']>=zone_low: retests+=1
                else:
                    if q['close']<=zone_high: hold_n+=1
                    if q['high']>=zone_low and q['close']<=zone_high: retests+=1
            hold_ratio=hold_n/max(valid_n,1)
            early=post[:min(7,len(post))]
            early_vol=[_f(q.get('volume')) for q in early if _f(q.get('volume')) is not None and _f(q.get('volume'))>0]
            contraction=(statistics.median(early_vol)/vol) if early_vol else None
            # Trigger is the post-spike balance edge. Require at least two post bars before calling confirmation.
            trigger=None; confirm_i=None
            if len(post)>=2:
                for j in range(i+2,n):
                    balance=cs[i+1:j]
                    if not balance: continue
                    edge=max(q['high'] for q in balance) if side=='BULL' else min(q['low'] for q in balance)
                    q=cs[j]
                    crossed=(q['close']>edge+atr*.04) if side=='BULL' else (q['close']<edge-atr*.04)
                    if crossed:
                        trigger=edge; confirm_i=j; break
                if trigger is None:
                    bal=post[:-1] if len(post)>1 else post
                    trigger=(max(q['high'] for q in bal) if side=='BULL' else min(q['low'] for q in bal)) if bal else level
            else:
                trigger=level
            latest=cs[-1]
            invalidated=(latest['close']<invalid) if side=='BULL' else (latest['close']>invalid)
            confirmed=confirm_i is not None and not invalidated
            # Score evidence quality, never probability of profit.
            score=0.0; evidence=[]; counter=[]
            rv_pts=min(30, max(0,(rvol-1.5)*14)); score+=rv_pts
            evidence.append(f'abnormal volume {rvol:.2f}x median')
            if (bull_impulse if side=='BULL' else bear_impulse): score+=14; evidence.append('directional impulse candle')
            if level_break: score+=14; evidence.append('prior range level attacked/broken')
            if hold_ratio>=.75: score+=12; evidence.append(f'level hold {hold_ratio*100:.0f}% of post-spike bars')
            elif hold_ratio<.55: counter.append(f'weak level hold {hold_ratio*100:.0f}%')
            if contraction is not None and contraction<=.65: score+=10; evidence.append(f'post-spike volume contraction {contraction:.2f}x spike')
            if retests>=1: score+=8; evidence.append(f'{retests} support/resistance retest(s) held')
            if confirmed: score+=12; evidence.append('balance edge breakout confirmed by close')
            if invalidated: score=max(0,score-35); counter.append('footprint invalidated by close through risk level')
            score=round(_clamp(score),1)
            if invalidated:
                state='INVALIDATED'
            elif confirmed and side=='BULL':
                state='BIG MONEY ENTRY CONFIRMED'
            elif confirmed and side=='BEAR':
                state='DISTRIBUTION / EXIT CONFIRMED'
            elif hold_ratio>=.70 and side=='BULL':
                state='ACCUMULATION / ABSORPTION'
            elif hold_ratio>=.70 and side=='BEAR':
                state='DISTRIBUTION / ABSORPTION'
            else:
                state='ABNORMAL VOLUME WATCH'
            events.append({
                'side':side,'state':state,'score':score,'spike_index':i,'spike_ts':x.get('ts'),'spike_price':x['close'],
                'spike_volume':vol,'baseline_volume':baseline,'rvol':round(rvol,2),'range_atr':round(rng/max(atr,1e-9),2),
                'zone_low':round(zone_low,4),'zone_high':round(zone_high,4),'level':round(level,4),
                'trigger':round(trigger,4) if trigger is not None else None,'invalidation':round(invalid,4),
                'hold_ratio_pct':round(hold_ratio*100,1),'retests':retests,'volume_contraction_ratio':round(contraction,2) if contraction is not None else None,
                'confirmed_index':confirm_i,'evidence':evidence,'counter_evidence':counter,
            })
    if not events:
        return {'available':False,'state':'NO QUALIFIED FOOTPRINT','score':0,'identity_policy':'No abnormal-volume accumulation/distribution setup passed the current rule gates.'}
    # Prefer valid confirmed footprints, then valid accumulation/distribution, then raw spike watches.
    def rank(e):
        stage=3 if 'CONFIRMED' in e['state'] else 2 if ('ACCUMULATION' in e['state'] or 'DISTRIBUTION / ABSORPTION' in e['state']) else 1 if e['state']!='INVALIDATED' else 0
        recency=e['spike_index']/max(n-1,1)
        return (stage,e['score'],recency)
    events.sort(key=rank,reverse=True)
    best=events[0].copy();best['available']=True
    best['engine']='Abnormal Volume + Absorption + Breakout Footprint v71.4'
    best['identity_policy']='"Big Money" is a behavioural label only. Anonymous price/volume data cannot identify FII/DII/PRO or any named participant.'
    best['score_policy']='Score measures observed footprint evidence quality, not probability of profit.'
    best['recent_events']=events[:5]
    return best

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
    if chart:
        bm=chart.get('big_money_entry') or {}
        if bm.get('available') and bm.get('state')!='INVALIDATED':
            label=f"{bm.get('state')} • RVOL {bm.get('rvol')}x"
            if bm.get('side')=='BULL': bull.append((label,18 if 'CONFIRMED' in str(bm.get('state')) else 12))
            elif bm.get('side')=='BEAR': bear.append((label,18 if 'CONFIRMED' in str(bm.get('state')) else 12))
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
    out['big_money_entry']=big_money_entry_intelligence(cs)
    out['smart_money']=smart_money_advanced(snapshot,base_sm,out)
    out['truth_policy']=['Forming patterns are explicitly unconfirmed until rule-defined completion/trigger.','Formation quality is geometry/evidence quality, not win probability.','Fib levels are derived from observed swings, not future targets.','Smart-money identity is never inferred from anonymous exchange data.']
    return out

def build_v67(snapshot:dict, previous:dict|None=None):
    base=previous or {}
    sm=smart_money_advanced(snapshot, snapshot.get('_base_smart_money') or {}, None)
    return {'version':'67.0','name':'Advanced Chart Pattern + Smart Money Intelligence OS','smart_money_advanced':sm,'modules':{'multi_symbol_chart_workspace':True,'forming_candlestick_detection':True,'pre_pattern_lifecycle':True,'auto_fibonacci':True,'harmonic_candidate_scaffold':True,'pattern_trigger_invalidation':True,'smart_money_evidence_stack':True,'truth_safe_identity':True,'full_fno_scan_endpoint':True},'previous_version':base.get('version'),'read_only':True,'execution_enabled':False}
