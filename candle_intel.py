from typing import Any, Dict, List, Optional
import math


def _f(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else 0.0
    except Exception:
        return 0.0


def _ema(values: List[float], period: int) -> List[Optional[float]]:
    if not values: return []
    k=2.0/(period+1.0); out=[]; e=None
    for v in values:
        e=v if e is None else (v*k+e*(1-k))
        out.append(e)
    return out


def _sma(values: List[float], period: int) -> List[Optional[float]]:
    out=[]; s=0.0
    for i,v in enumerate(values):
        s+=v
        if i>=period: s-=values[i-period]
        out.append(s/period if i>=period-1 else None)
    return out


def _std(values: List[float], period: int) -> List[Optional[float]]:
    out=[]
    for i in range(len(values)):
        if i<period-1: out.append(None); continue
        xs=values[i-period+1:i+1]; m=sum(xs)/period
        out.append(math.sqrt(sum((x-m)**2 for x in xs)/period))
    return out


def _rsi(values: List[float], period: int=14) -> Optional[float]:
    if len(values)<=period: return None
    gains=[]; losses=[]
    for i in range(1,len(values)):
        d=values[i]-values[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains[-period:])/period; al=sum(losses[-period:])/period
    if al==0: return 100.0 if ag>0 else 50.0
    rs=ag/al
    return 100.0-(100.0/(1.0+rs))


def _atr(cs: List[Dict[str,float]], period:int=14)->Optional[float]:
    if len(cs)<2: return None
    trs=[]
    for i in range(1,len(cs)):
        h,l,pc=cs[i]['high'],cs[i]['low'],cs[i-1]['close']
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    if len(trs)<period: return sum(trs)/len(trs) if trs else None
    return sum(trs[-period:])/period


def _supertrend(cs: List[Dict[str,float]], period:int=10, multiplier:float=3.0):
    if len(cs)<period+2: return {'value':None,'state':'N/A'}
    trs=[]
    for i,c in enumerate(cs):
        if i==0: trs.append(c['high']-c['low'])
        else: trs.append(max(c['high']-c['low'],abs(c['high']-cs[i-1]['close']),abs(c['low']-cs[i-1]['close'])))
    atrs=[]
    for i in range(len(trs)):
        atrs.append(sum(trs[max(0,i-period+1):i+1])/min(i+1,period))
    fub=flb=None; st=None; state='N/A'
    prev_st=None
    for i,c in enumerate(cs):
        mid=(c['high']+c['low'])/2; bub=mid+multiplier*atrs[i]; blb=mid-multiplier*atrs[i]
        if i==0:
            fub,flb=bub,blb; st=bub; prev_st=st; continue
        pc=cs[i-1]['close']
        fub=bub if bub<(fub if fub is not None else bub) or pc>(fub if fub is not None else bub) else fub
        flb=blb if blb>(flb if flb is not None else blb) or pc<(flb if flb is not None else blb) else flb
        if prev_st==fub:
            st=fub if c['close']<=fub else flb
        else:
            st=flb if c['close']>=flb else fub
        prev_st=st
    if st is not None: state='BULLISH' if cs[-1]['close']>=st else 'BEARISH'
    return {'value':st,'state':state}


def _volume_profile(cs: List[Dict[str,float]], bins:int=12):
    valid=[c for c in cs if c.get('volume') is not None and c.get('volume',0)>0]
    if len(valid)<8: return {'available':False,'poc':None,'vah':None,'val':None,'coverage':0}
    lo=min(c['low'] for c in valid); hi=max(c['high'] for c in valid)
    if hi<=lo: return {'available':False,'poc':None,'vah':None,'val':None,'coverage':0}
    step=(hi-lo)/bins; vols=[0.0]*bins
    for c in valid:
        p=(c['high']+c['low']+c['close'])/3; idx=min(bins-1,max(0,int((p-lo)/step)))
        vols[idx]+=c['volume']
    total=sum(vols); poc_i=max(range(bins),key=lambda i:vols[i]); order=sorted(range(bins),key=lambda i:vols[i],reverse=True)
    chosen=[]; acc=0.0
    for i in order:
        chosen.append(i); acc+=vols[i]
        if acc>=total*.70: break
    val_i=min(chosen); vah_i=max(chosen)
    center=lambda i: lo+(i+.5)*step
    return {'available':True,'poc':center(poc_i),'vah':center(vah_i),'val':center(val_i),'coverage':round(100*len(valid)/max(1,len(cs)))}


def _liquidity(cs: List[Dict[str,float]], atr: Optional[float]):
    if len(cs)<8: return {'state':'N/A','detail':'Need more candles','sweep':False,'retest':False}
    x=cs[-1]; prev=cs[-7:-1]; ph=max(c['high'] for c in prev); pl=min(c['low'] for c in prev)
    tol=(atr or max(ph-pl,1)*.05)*.15
    sweep_up=x['high']>ph and x['close']<ph
    sweep_dn=x['low']<pl and x['close']>pl
    if sweep_up: return {'state':'BEARISH SWEEP','detail':f'High swept {ph:.2f} then closed below','sweep':True,'retest':False}
    if sweep_dn: return {'state':'BULLISH SWEEP','detail':f'Low swept {pl:.2f} then closed above','sweep':True,'retest':False}
    # simple breakout/retest using previous range and prior candle breakout
    p=cs[-2]; base=cs[-8:-2]; bh=max(c['high'] for c in base); bl=min(c['low'] for c in base)
    if p['close']>bh and x['low']<=bh+tol and x['close']>=bh: return {'state':'BULLISH RETEST','detail':f'Breakout level {bh:.2f} held','sweep':False,'retest':True}
    if p['close']<bl and x['high']>=bl-tol and x['close']<=bl: return {'state':'BEARISH RETEST','detail':f'Breakdown level {bl:.2f} held','sweep':False,'retest':True}
    return {'state':'NO FRESH SWEEP/RETEST','detail':f'Recent range {pl:.2f}–{ph:.2f}','sweep':False,'retest':False}


def analyse_candles(rows: List[List[Any]]) -> Dict[str, Any]:
    cs=[]
    for r in rows:
        if not isinstance(r,(list,tuple)) or len(r)<5: continue
        o,h,l,c=_f(r[1]),_f(r[2]),_f(r[3]),_f(r[4])
        if min(o,h,l,c)<=0: continue
        vol=_f(r[5]) if len(r)>5 and r[5] is not None else None
        cs.append({'ts':str(r[0]),'open':o,'high':h,'low':l,'close':c,'volume':vol})
    patterns=[]
    if cs:
        x=cs[-1]; o,h,l,c=x['open'],x['high'],x['low'],x['close']; body=abs(c-o); rng=max(h-l,1e-9); upper=h-max(o,c); lower=min(o,c)-l
        def add(name,side,strength): patterns.append({'name':name,'side':side,'strength':round(strength)})
        if body/rng <= .1:
            add('DOJI','NEUTRAL',70)
            if lower>=rng*.58 and upper<=rng*.12: add('DRAGONFLY DOJI','BULL',82)
            if upper>=rng*.58 and lower<=rng*.12: add('GRAVESTONE DOJI','BEAR',82)
        if lower >= max(body*2, rng*.45) and upper <= rng*.2: add('HAMMER' if c>=o else 'HANGING MAN','BULL' if c>=o else 'BEAR',78)
        if upper >= max(body*2, rng*.45) and lower <= rng*.2: add('INVERTED HAMMER' if c>=o else 'SHOOTING STAR','BULL' if c>=o else 'BEAR',78)
        if len(cs)>=2:
            p=cs[-2]; po,pc=p['open'],p['close']
            if c>o and pc<po and o<=pc and c>=po: add('BULLISH ENGULFING','BULL',86)
            if c<o and pc>po and o>=pc and c<=po: add('BEARISH ENGULFING','BEAR',86)
            if h<=p['high'] and l>=p['low']: add('INSIDE BAR','NEUTRAL',68)
            if h>=p['high'] and l<=p['low']: add('OUTSIDE BAR','NEUTRAL',70)
            # Harami / piercing / dark cloud
            if c>o and pc<po and o>=pc and c<=po: add('BULLISH HARAMI','BULL',74)
            if c<o and pc>po and o<=pc and c>=po: add('BEARISH HARAMI','BEAR',74)
            mid_prev=(po+pc)/2
            if pc<po and c>o and o<pc and c>mid_prev and c<po: add('PIERCING LINE','BULL',80)
            if pc>po and c<o and o>pc and c<mid_prev and c>po: add('DARK CLOUD COVER','BEAR',80)
        if len(cs)>=3:
            a,b,z=cs[-3],cs[-2],cs[-1]
            if a['close']<a['open'] and abs(b['close']-b['open']) < abs(a['close']-a['open'])*.5 and z['close']>z['open'] and z['close']>(a['open']+a['close'])/2: add('MORNING STAR','BULL',88)
            if a['close']>a['open'] and abs(b['close']-b['open']) < abs(a['close']-a['open'])*.5 and z['close']<z['open'] and z['close']<(a['open']+a['close'])/2: add('EVENING STAR','BEAR',88)
            bulls=all(q['close']>q['open'] for q in (a,b,z))
            bears=all(q['close']<q['open'] for q in (a,b,z))
            if bulls and a['close']<b['close']<z['close']: add('THREE WHITE SOLDIERS','BULL',90)
            if bears and a['close']>b['close']>z['close']: add('THREE BLACK CROWS','BEAR',90)
    closes=[x['close'] for x in cs]
    structure='N/A'
    if len(cs)>=6:
        recent=cs[-6:]; highs=[x['high'] for x in recent]; lows=[x['low'] for x in recent]
        if highs[-1]>highs[-3] and lows[-1]>lows[-3]: structure='HIGHER HIGH / HIGHER LOW'
        elif highs[-1]<highs[-3] and lows[-1]<lows[-3]: structure='LOWER HIGH / LOWER LOW'
        else: structure='RANGE / TRANSITION'
    rsi=_rsi(closes,14)
    ema9=_ema(closes,9); ema20=_ema(closes,20); ema50=_ema(closes,50)
    e12=_ema(closes,12); e26=_ema(closes,26); macd_line=[a-b for a,b in zip(e12,e26)] if closes else []
    macd_signal=_ema(macd_line,9) if macd_line else []
    sma20=_sma(closes,20); sd20=_std(closes,20)
    bb_mid=sma20[-1] if sma20 else None; bb_sd=sd20[-1] if sd20 else None
    bb_upper=bb_mid+2*bb_sd if bb_mid is not None and bb_sd is not None else None
    bb_lower=bb_mid-2*bb_sd if bb_mid is not None and bb_sd is not None else None
    atr=_atr(cs,14); st=_supertrend(cs)
    last=closes[-1] if closes else None
    ema_state='N/A'
    if last is not None and ema9 and ema20 and ema50:
        e9,e20,e50=ema9[-1],ema20[-1],ema50[-1]
        if last>e9>e20>e50: ema_state='BULL STACK'
        elif last<e9<e20<e50: ema_state='BEAR STACK'
        else: ema_state='MIXED'
    macd_val=macd_line[-1] if macd_line else None; macd_sig=macd_signal[-1] if macd_signal else None
    macd_state='N/A' if macd_val is None or macd_sig is None else ('BULLISH' if macd_val>macd_sig else 'BEARISH')
    bb_state='N/A'
    if last is not None and bb_upper is not None:
        bb_state='ABOVE UPPER' if last>bb_upper else 'BELOW LOWER' if last<bb_lower else 'INSIDE BANDS'
    vol_profile=_volume_profile(cs[-120:])
    liq=_liquidity(cs,atr)
    # compact directional score from indicators, quality not probability
    votes=[]
    if rsi is not None: votes.append(1 if rsi>=55 else -1 if rsi<=45 else 0)
    if macd_state!='N/A': votes.append(1 if macd_state=='BULLISH' else -1)
    if ema_state!='N/A': votes.append(1 if ema_state=='BULL STACK' else -1 if ema_state=='BEAR STACK' else 0)
    if st['state']!='N/A': votes.append(1 if st['state']=='BULLISH' else -1)
    momentum_score=round(50+50*(sum(votes)/len(votes))) if votes else None
    return {
        'candles':cs[-120:], 'patterns':patterns[:5], 'structure':structure, 'last_close':last,
        'indicators':{
            'rsi14':rsi,'ema9':ema9[-1] if ema9 else None,'ema20':ema20[-1] if ema20 else None,'ema50':ema50[-1] if ema50 else None,'ema_state':ema_state,
            'macd':macd_val,'macd_signal':macd_sig,'macd_state':macd_state,
            'bb_mid':bb_mid,'bb_upper':bb_upper,'bb_lower':bb_lower,'bb_state':bb_state,
            'atr14':atr,'atr_pct':(atr/last*100 if atr and last else None),'supertrend':st.get('value'),'supertrend_state':st.get('state'),
            'momentum_score':momentum_score
        },
        'volume_profile':vol_profile,
        'liquidity':liq,
    }
