from __future__ import annotations
from datetime import date, datetime
from math import isfinite


def _n(v, d=0.0):
    try:
        x=float(v); return x if isfinite(x) else d
    except Exception: return d

def _ok(v):
    try: return v is not None and isfinite(float(v))
    except Exception: return False

def _clamp(v,a=0.0,b=100.0): return max(a,min(b,v))

def _series_slope(values):
    vals=[_n(x) for x in (values or []) if x is not None]
    if len(vals)<2 or vals[0]==0: return None
    return (vals[-1]-vals[0])/abs(vals[0])*100

def _dir_label(x, flat=.035):
    if x is None:return 'N/A'
    return 'UP' if x>flat else 'DOWN' if x<-flat else 'FLAT'

def _iv_regime(iv):
    if iv is None:return 'N/A'
    v=_n(iv); return 'VERY HIGH' if v>=30 else 'HIGH' if v>=22 else 'NORMAL' if v>=15 else 'LOW'

def _expiry_days(expiry):
    if not expiry or str(expiry).upper()=='DEMO': return None
    raw=str(expiry)[:10]
    try:return (datetime.fromisoformat(raw).date()-date.today()).days
    except Exception:return None

def _expiry_mode(days):
    if days is None:return 'N/A'
    if days<0:return 'EXPIRED'
    if days==0:return 'EXPIRY DAY'
    if days==1:return 'T-1 EXPIRY'
    if days<=3:return 'NEAR EXPIRY'
    return 'NORMAL EXPIRY'

def _greek_intel(rows,spot):
    if not rows:return {'available':False,'coverage_pct':0.0,'gamma_pressure':'N/A','theta_pressure':'N/A','delta_balance':None}
    near=sorted(rows,key=lambda r:abs(_n(r.get('s'))-spot))[:7] if spot else rows[:7]
    valid=[r for r in near if _ok(r.get('c_delta')) and _ok(r.get('p_delta'))]
    cov=len(valid)/max(len(near),1)*100
    if not valid:return {'available':False,'coverage_pct':round(cov,1),'gamma_pressure':'N/A','theta_pressure':'N/A','delta_balance':None}
    gamma=sum(abs(_n(r.get('c_gamma')))+abs(_n(r.get('p_gamma'))) for r in valid)
    theta=sum(abs(_n(r.get('c_theta')))+abs(_n(r.get('p_theta'))) for r in valid)
    bal=sum(_n(r.get('c_delta'))+_n(r.get('p_delta')) for r in valid)/len(valid)
    gamma_state='ELEVATED' if gamma>0.035 else 'MODERATE' if gamma>0.015 else 'LOW'
    theta_state='HEAVY' if theta>70 else 'MODERATE' if theta>35 else 'LIGHT'
    return {'available':True,'coverage_pct':round(cov,1),'gamma_pressure':gamma_state,'gamma_sum':round(gamma,5),'theta_pressure':theta_state,'theta_sum':round(theta,2),'delta_balance':round(bal,3)}

def _premium_divergence(rows,spot,trend):
    if not rows or trend is None:return {'available':False,'state':'N/A'}
    near=sorted(rows,key=lambda r:abs(_n(r.get('s'))-spot))[:3]
    cps=[_n(r.get('cp')) for r in near if _ok(r.get('cp'))]
    pps=[_n(r.get('pp')) for r in near if _ok(r.get('pp'))]
    if not cps or not pps:return {'available':False,'state':'N/A'}
    ce=sum(cps)/len(cps); pe=sum(pps)/len(pps)
    state='CONFIRMED'
    if trend>.035 and ce<=0: state='BULLISH PRICE / CE PREMIUM DIVERGENCE'
    elif trend<-.035 and pe<=0: state='BEARISH PRICE / PE PREMIUM DIVERGENCE'
    elif trend>.035 and pe>ce: state='PUT PREMIUM RESILIENCE'
    elif trend<-.035 and ce>pe: state='CALL PREMIUM RESILIENCE'
    return {'available':True,'state':state,'ce_change_pct':round(ce,3),'pe_change_pct':round(pe,3)}



def _coverage_intel(snapshot, rows, greek, brain):
    total=len(rows or [])
    if not total:
        return {'score':0.0,'grade':'INSUFFICIENT','option_rows':0,'greeks_pct':0.0,'premium_change_pct':0.0,'prev_oi_pct':0.0,'index_brain_pct':0.0}
    prem=sum(1 for r in rows if _ok(r.get('cp')) and _ok(r.get('pp')))/total*100
    poi=sum(1 for r in rows if (_ok(r.get('c_prev_oi')) or _ok(r.get('p_prev_oi')) or _ok(r.get('cdoi')) or _ok(r.get('pdoi'))))/total*100
    idx=_n(brain.get('coverage_pct')) if brain else 0.0
    g=_n(greek.get('coverage_pct'))
    score=_clamp(.34*g+.26*prem+.22*poi+.18*idx)
    grade='A' if score>=85 else 'B' if score>=70 else 'C' if score>=55 else 'D' if score>=35 else 'INSUFFICIENT'
    return {'score':round(score,1),'grade':grade,'option_rows':total,'greeks_pct':round(g,1),'premium_change_pct':round(prem,1),'prev_oi_pct':round(poi,1),'index_brain_pct':round(idx,1)}

def _intraday_position(sc, spot):
    dh=sc.get('day_high'); dl=sc.get('day_low'); op=sc.get('day_open'); orh=sc.get('opening_range_high'); orl=sc.get('opening_range_low')
    out={'available':False,'range_position_pct':None,'from_open_pct':None,'day_range_pct':None,'or_expansion':None,'state':'N/A'}
    if not spot or not (_ok(dh) and _ok(dl)): return out
    hi=_n(dh); lo=_n(dl); width=max(hi-lo,1e-9)
    pos=_clamp((spot-lo)/width*100); dayrng=width/spot*100
    fromopen=((spot-_n(op))/_n(op)*100) if _ok(op) and _n(op) else None
    orexp=None
    if _ok(orh) and _ok(orl):
        orw=max(_n(orh)-_n(orl),1e-9); orexp=width/orw
    state='UPPER RANGE CONTROL' if pos>=70 else 'LOWER RANGE CONTROL' if pos<=30 else 'MID-RANGE / BALANCE'
    return {'available':True,'range_position_pct':round(pos,1),'from_open_pct':round(fromopen,3) if fromopen is not None else None,'day_range_pct':round(dayrng,3),'or_expansion':round(orexp,2) if orexp is not None else None,'state':state}

def _momentum_intel(slopes):
    s3=slopes.get('3'); s5=slopes.get('5'); s15=slopes.get('15')
    vals=[x for x in (s3,s5,s15) if x is not None]
    if len(vals)<2:return {'available':False,'state':'N/A','acceleration':None,'impulse_score':50.0}
    accel=(s3-s15) if s3 is not None and s15 is not None else (vals[-1]-vals[0])
    impulse=_clamp(50 + (_n(s3)*380 if s3 is not None else 0)*.45 + (_n(s5)*260 if s5 is not None else 0)*.35 + (_n(s15)*180 if s15 is not None else 0)*.20)
    if accel>.08 and impulse>=58: state='BULLISH ACCELERATION'
    elif accel<-.08 and impulse<=42: state='BEARISH ACCELERATION'
    elif abs(accel)<.035: state='STEADY / NO ACCELERATION'
    elif accel>0: state='IMPROVING MOMENTUM'
    else: state='FADING MOMENTUM'
    return {'available':True,'state':state,'acceleration':round(accel,3),'impulse_score':round(impulse,1)}

def _derivative_pressure(rows, spot):
    if not rows:return {'available':False,'state':'N/A','ce_volume_share_pct':None,'pe_volume_share_pct':None,'oi_concentration_pct':None,'atm_skew_pct':None}
    cv=sum(max(0,_n(r.get('cv'))) for r in rows); pv=sum(max(0,_n(r.get('pv'))) for r in rows); tv=cv+pv
    coi=[max(0,_n(r.get('coi'))) for r in rows]; poi=[max(0,_n(r.get('poi'))) for r in rows]; toi=sum(coi)+sum(poi)
    topoi=sorted(coi+poi,reverse=True)[:4]; conc=(sum(topoi)/toi*100) if toi else None
    near=sorted(rows,key=lambda r:abs(_n(r.get('s'))-spot))[:5] if spot else rows[:5]
    civ=[_n(r.get('c_iv')) for r in near if _ok(r.get('c_iv'))]; piv=[_n(r.get('p_iv')) for r in near if _ok(r.get('p_iv'))]
    skew=(sum(piv)/len(piv)-sum(civ)/len(civ)) if civ and piv else None
    ces=(cv/tv*100) if tv else None; pes=(pv/tv*100) if tv else None
    if ces is None: state='N/A'
    elif pes>=60: state='PUT ACTIVITY DOMINANT'
    elif ces>=60: state='CALL ACTIVITY DOMINANT'
    else: state='BALANCED ACTIVITY'
    return {'available':bool(tv or toi),'state':state,'ce_volume_share_pct':round(ces,1) if ces is not None else None,'pe_volume_share_pct':round(pes,1) if pes is not None else None,'oi_concentration_pct':round(conc,1) if conc is not None else None,'atm_skew_pct':round(skew,2) if skew is not None else None}

def _conflict_matrix(ai_side, flow, mtf_score, vwap_dist, opening_state, sector_state):
    def vote(label, direction, available=True): return {'label':label,'direction':direction,'available':available}
    out=[]
    out.append(vote('AI','BULL' if ai_side=='CE' else 'BEAR' if ai_side=='PE' else 'NEUTRAL',True))
    out.append(vote('BIG MONEY','BULL' if flow=='BULLISH FOOTPRINT' else 'BEAR' if flow=='BEARISH FOOTPRINT' else 'NEUTRAL',flow!='INSUFFICIENT DATA'))
    out.append(vote('MTF','BULL' if mtf_score>=60 else 'BEAR' if mtf_score<=40 else 'NEUTRAL',True))
    out.append(vote('VWAP','BULL' if vwap_dist is not None and vwap_dist>.03 else 'BEAR' if vwap_dist is not None and vwap_dist<-.03 else 'NEUTRAL',vwap_dist is not None))
    out.append(vote('OPENING RANGE','BULL' if opening_state=='ABOVE OR HIGH' else 'BEAR' if opening_state=='BELOW OR LOW' else 'NEUTRAL',opening_state!='N/A'))
    out.append(vote('SECTORS','BULL' if sector_state=='BROAD BULL LEADERSHIP' else 'BEAR' if sector_state=='BROAD BEAR LEADERSHIP' else 'NEUTRAL',sector_state!='N/A'))
    bull=sum(1 for x in out if x['available'] and x['direction']=='BULL'); bear=sum(1 for x in out if x['available'] and x['direction']=='BEAR'); avail=sum(1 for x in out if x['available'])
    state='BULLISH AGREEMENT' if bull>=4 and bull>=bear+2 else 'BEARISH AGREEMENT' if bear>=4 and bear>=bull+2 else 'CONFLICT / MIXED'
    return {'state':state,'bull':bull,'bear':bear,'available':avail,'votes':out}

def analyse_market_intel(snapshot:dict, ai:dict|None=None, smart:dict|None=None)->dict:
    ai=ai or {}; smart=smart or {}; spot=_n(snapshot.get('spot')); vwap=_n(snapshot.get('vwap'))
    ps=snapshot.get('price_series') or {}; slopes={k:_series_slope(ps.get(k)) for k in ('3','5','15')}; labels={k:_dir_label(v) for k,v in slopes.items()}
    votes=[]
    for k,w in [('3',1.0),('5',1.2),('15',1.5)]:
        s=slopes[k]
        if s is not None:votes.append((1 if s>.035 else -1 if s<-.035 else 0,w))
    mtf=sum(v*w for v,w in votes)/sum(w for _,w in votes) if votes else 0; mtf_score=_clamp(50+mtf*42)
    mtf_label='BULLISH ALIGNMENT' if mtf_score>=65 else 'BEARISH ALIGNMENT' if mtf_score<=35 else 'MIXED / RANGE'
    vwap_dist=((spot-vwap)/vwap*100) if spot and vwap else None; vwap_state='ABOVE VWAP' if vwap_dist is not None and vwap_dist>.03 else 'BELOW VWAP' if vwap_dist is not None and vwap_dist<-.03 else 'AT VWAP'
    mp=snapshot.get('official_max_pain'); mp=_n(mp) if mp is not None else None; mp_dist=((spot-mp)/spot*100) if mp and spot else None
    pcr=snapshot.get('official_pcr'); pcr=_n(pcr) if pcr is not None else None; pcr_state='N/A' if pcr is None else 'PUT-HEAVY' if pcr>=1.25 else 'CALL-HEAVY' if pcr<=.80 else 'BALANCED'
    iv=snapshot.get('iv_proxy'); iv=_n(iv) if iv is not None else None
    cw=smart.get('call_wall'); pw=smart.get('put_wall'); wall_state='N/A'; wall_width=None
    if cw is not None and pw is not None and spot:
        cw=_n(cw);pw=_n(pw);wall_width=abs(cw-pw);wall_state='BETWEEN WALLS' if pw<spot<cw else 'ABOVE CALL WALL' if spot>=cw else 'BELOW PUT WALL'
    # Opening range / session geometry
    sc=snapshot.get('session_context') or {}; orh=sc.get('opening_range_high'); orl=sc.get('opening_range_low'); dh=sc.get('day_high'); dl=sc.get('day_low'); dop=sc.get('day_open')
    opening_state='N/A'; or_dist=None
    if _ok(orh) and _ok(orl) and spot:
        orh=_n(orh);orl=_n(orl);width=max(orh-orl,1e-9)
        opening_state='ABOVE OR HIGH' if spot>orh else 'BELOW OR LOW' if spot<orl else 'INSIDE OPENING RANGE'
        or_dist=(spot-(orh if spot>=orh else orl if spot<=orl else (orh+orl)/2))/spot*100
    # Expiry brain
    ed=_expiry_days(snapshot.get('expiry')); em=_expiry_mode(ed); pin=None
    if mp and spot: pin=abs(spot-mp)/spot*100
    expiry_risk=0
    if ed is not None: expiry_risk += 45 if ed==0 else 28 if ed==1 else 12 if ed<=3 else 0
    if pin is not None: expiry_risk += max(0,35-min(35,pin*120))
    if iv is not None and iv>=25: expiry_risk+=12
    expiry_risk=_clamp(expiry_risk)
    rows=snapshot.get('option_data') or []; greek=_greek_intel(rows,spot); prem=_premium_divergence(rows,spot,slopes.get('5'))
    active=str(snapshot.get('active_underlying') or 'NIFTY').upper(); brain=((snapshot.get('index_brain') or {}).get(active) or {})
    sectors=brain.get('sectors') or []; sector_bulls=sum(1 for x in sectors if x.get('state')=='BULL'); sector_bears=sum(1 for x in sectors if x.get('state')=='BEAR')
    sector_state='N/A' if not sectors else 'BROAD BULL LEADERSHIP' if sector_bulls>=max(2,sector_bears*1.5) else 'BROAD BEAR LEADERSHIP' if sector_bears>=max(2,sector_bulls*1.5) else 'ROTATION / MIXED'
    ai_side=str(ai.get('side') or 'WAIT').upper(); flow=str(smart.get('direction') or 'INSUFFICIENT DATA'); quality=_n(smart.get('data_quality'));trap=_n(smart.get('trap_risk'));ai_conf=_n(ai.get('confidence'))
    directional=0
    if ai_side=='CE':directional+=1
    elif ai_side=='PE':directional-=1
    if flow=='BULLISH FOOTPRINT':directional+=1
    elif flow=='BEARISH FOOTPRINT':directional-=1
    if mtf_score>=65:directional+=1
    elif mtf_score<=35:directional-=1
    if vwap_dist is not None:directional+=.5 if vwap_dist>.03 else -.5 if vwap_dist<-.03 else 0
    if opening_state=='ABOVE OR HIGH':directional+=.5
    elif opening_state=='BELOW OR LOW':directional-=.5
    if sector_state=='BROAD BULL LEADERSHIP':directional+=.5
    elif sector_state=='BROAD BEAR LEADERSHIP':directional-=.5
    alignment=abs(directional)/4.5*100; confluence=_clamp(.30*ai_conf+.24*quality+.25*alignment+.13*(100-trap)+.08*(100-expiry_risk))
    risk_flags=[]
    if quality<55:risk_flags.append('LOW DATA QUALITY')
    if trap>=65:risk_flags.append('HIGH TRAP RISK')
    if expiry_risk>=65:risk_flags.append('EXPIRY / PIN RISK')
    if flow=='INSUFFICIENT DATA':risk_flags.append('FLOW DATA INSUFFICIENT')
    if ai_side=='CE' and flow=='BEARISH FOOTPRINT' or ai_side=='PE' and flow=='BULLISH FOOTPRINT':risk_flags.append('AI / FLOW CONFLICT')
    if prem.get('available') and prem.get('state')!='CONFIRMED':risk_flags.append('PREMIUM DIVERGENCE')
    if labels.get('3')!='N/A' and labels.get('15')!='N/A' and labels['3']!=labels['15'] and 'FLAT' not in (labels['3'],labels['15']):risk_flags.append('SHORT/LONG HORIZON DIVERGENCE')
    gates={'data_quality':quality>=55,'trap':trap<65,'flow':flow!='INSUFFICIENT DATA','mtf':mtf_score>=60 or mtf_score<=40,'premium':not prem.get('available') or prem.get('state')=='CONFIRMED','expiry':expiry_risk<75}
    gates_passed=sum(gates.values()); gates_total=len(gates)
    coverage=_coverage_intel(snapshot, rows, greek, brain)
    intraday=_intraday_position(sc, spot)
    momentum=_momentum_intel(slopes)
    derivatives=_derivative_pressure(rows, spot)
    conflicts=_conflict_matrix(ai_side, flow, mtf_score, vwap_dist, opening_state, sector_state)
    if coverage['score']<40: risk_flags.append('INPUT COVERAGE LOW')
    if derivatives.get('oi_concentration_pct') is not None and derivatives['oi_concentration_pct']>=55: risk_flags.append('OI HIGHLY CONCENTRATED')
    if intraday.get('or_expansion') is not None and intraday['or_expansion']>=2.5: risk_flags.append('RANGE EXPANSION ELEVATED')
    if coverage['score']<40: regime_v13='DATA-LIMITED'
    elif expiry_risk>=75: regime_v13='EXPIRY / PIN DOMINATED'
    elif momentum.get('state') in ('BULLISH ACCELERATION','BEARISH ACCELERATION') and mtf_score>=65 or momentum.get('state') in ('BULLISH ACCELERATION','BEARISH ACCELERATION') and mtf_score<=35: regime_v13='TREND DRIVE'
    elif opening_state in ('ABOVE OR HIGH','BELOW OR LOW') and intraday.get('or_expansion') is not None and intraday['or_expansion']>=1.35: regime_v13='BREAKOUT / RANGE EXPANSION'
    elif abs(_n(vwap_dist))<.04 and mp_dist is not None and abs(mp_dist)<.18: regime_v13='MEAN REVERSION / PIN'
    else: regime_v13='BALANCED / DEVELOPING'

    if quality<55:desk_verdict='DATA GATE / WAIT'
    elif trap>=75 or expiry_risk>=85:desk_verdict='RISK GATE / WAIT'
    elif abs(directional)<1.75:desk_verdict='MIXED / WAIT'
    else:desk_verdict='BULLISH CONFLUENCE' if directional>0 else 'BEARISH CONFLUENCE'
    return {
      'engine':'Ultimate Market Intelligence v13','regime_v13':regime_v13,'data_coverage':coverage,'intraday_position':intraday,'momentum_brain':momentum,'derivative_pressure':derivatives,'conflict_matrix':conflicts,'active_underlying':active,'desk_verdict':desk_verdict,'confluence_score':round(confluence,1),'decision_stack':{'gates':gates,'passed':gates_passed,'total':gates_total,'directional_score':round(directional,2)},
      'multi_timeframe':{'score':round(mtf_score,1),'label':mtf_label,'slopes_pct':{k:(round(v,3) if v is not None else None) for k,v in slopes.items()},'labels':labels},
      'vwap':{'state':vwap_state,'distance_pct':round(vwap_dist,3) if vwap_dist is not None else None,'value':vwap or None},
      'opening_range':{'state':opening_state,'high':orh if _ok(orh) else None,'low':orl if _ok(orl) else None,'day_open':_n(dop) if _ok(dop) else None,'day_high':_n(dh) if _ok(dh) else None,'day_low':_n(dl) if _ok(dl) else None,'distance_pct':round(or_dist,3) if or_dist is not None else None},
      'max_pain':{'value':mp,'distance_pct':round(mp_dist,3) if mp_dist is not None else None},'pcr':{'value':pcr,'state':pcr_state},'iv':{'value':iv,'regime':_iv_regime(iv)},
      'expiry_brain':{'days_to_expiry':ed,'mode':em,'pin_distance_pct':round(pin,3) if pin is not None else None,'risk_score':round(expiry_risk,1)},
      'greeks_brain':greek,'premium_divergence':prem,'sector_rotation':{'state':sector_state,'bull_sectors':sector_bulls,'bear_sectors':sector_bears,'leaders':sectors[:5]},
      'walls':{'state':wall_state,'call_wall':cw if cw is not None else None,'put_wall':pw if pw is not None else None,'width':wall_width},'risk_flags':risk_flags,
      'note':'Confluence measures agreement/quality of observed inputs; it is not probability of profit and does not execute orders.'}
