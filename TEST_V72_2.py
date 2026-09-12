from datetime import datetime
from zoneinfo import ZoneInfo

from demo_data import demo_snapshot
from v72_2_engine import (
    _session_mode, _multi_tf_alignment, _crowding, _fast_signal_722,
    _expiry_mode, predictive_strike_selector, build_v72,
)

IST=ZoneInfo('Asia/Kolkata')


def test_opening_mode():
    epoch=datetime(2026,9,14,9,17,tzinfo=IST).timestamp()  # Monday
    assert _session_mode(epoch)['mode']=='OPENING_5'


def test_multi_tf():
    x=_multi_tf_alignment({'velocity_15s':.25,'velocity_60s':.18,'velocity_180s':.12,'acceleration':.09},'CE')
    assert x['state']=='ALIGNED' and x['aligned']>=2


def test_crowding_guard():
    x=_crowding({'change_pct':4.8,'rvol':5.5,'velocity_15s':.1,'velocity_60s':1.2,'opportunity_decay':70,'depth_intelligence':{'spread_pct':.8}},'CE')
    assert x['do_not_chase'] is True


def test_fast_confirmed():
    r={
      'v72_side':'CE','session_mode':'NORMAL','trigger_countdown_detail':{'score':90},'quote_age_sec':2,
      'late_entry':False,'depth_intelligence':{'spread_pct':.2},'directional_evidence':{'aligned_groups':6,'opposed_groups':0},
      'conflict_matrix':{'decision':'ALLOW'},'crowding':{'state':'CLEAN'},
      'persistence':{'samples':3,'evidence_persistence':82,'score_stability':86},
    }
    x=_fast_signal_722(r)
    assert x['tier']=='CONFIRMED' and x['action']=='BUY CE'


def test_expiry_mode():
    # Historical/future date parsing should always return a defined mode/days pair.
    x=_expiry_mode('2099-09-30')
    assert x['mode'] in ('NORMAL','SHORT-DATED','NEXT-DAY GAMMA','EXPIRY GAMMA') and x['days'] is not None


def test_strike_execution_guard():
    underlying={'ltp':25000,'side':'CE','v72_side':'CE','evidence_score':88,'velocity_15s':.25}
    chain={'expiry':'2099-09-30','spot':25000,'chain':[
      {'strike':24950,'ce':{'key':'CE24950','ltp':190,'bid':188,'ask':191,'oi':100000,'prev_oi':90000,'volume':25000,'delta':.58,'gamma':.001,'theta':-5,'iv':18},'pe':{'key':'PE24950','ltp':130,'bid':128,'ask':131,'oi':90000,'prev_oi':88000,'volume':22000,'delta':-.42,'gamma':.001,'theta':-5,'iv':18}},
      {'strike':25000,'ce':{'key':'CE25000','ltp':155,'bid':153,'ask':157,'oi':120000,'prev_oi':105000,'volume':30000,'delta':.50,'gamma':.0012,'theta':-5,'iv':19},'pe':{'key':'PE25000','ltp':150,'bid':148,'ask':152,'oi':118000,'prev_oi':108000,'volume':28000,'delta':-.50,'gamma':.0012,'theta':-5,'iv':19}},
      {'strike':25050,'ce':{'key':'CE25050','ltp':125,'bid':123,'ask':127,'oi':95000,'prev_oi':90000,'volume':26000,'delta':.42,'gamma':.001,'theta':-4,'iv':20},'pe':{'key':'PE25050','ltp':185,'bid':183,'ask':188,'oi':100000,'prev_oi':94000,'volume':24000,'delta':-.58,'gamma':.001,'theta':-5,'iv':20}},
    ]}
    x=predictive_strike_selector('NIFTY',underlying,chain)
    assert x['version']=='72.2'
    assert x['expiry_mode']['mode']=='NORMAL'
    assert len(x['top_candidates'])>0
    assert 'premium_response_pass' in x['top_candidates'][0]


def test_build_modules():
    v=build_v72(demo_snapshot(),record=False)
    assert v['version']=='72.2'
    assert v['release']=='72.2-timing-execution'
    assert v['modules']['reentry_engine'] is True
    assert v['modules']['false_breakout_detector'] is True
    assert v['modules']['bounded_adaptive_thresholds'] is True


if __name__=='__main__':
    test_opening_mode(); test_multi_tf(); test_crowding_guard(); test_fast_confirmed(); test_expiry_mode(); test_strike_execution_guard(); test_build_modules()
    print('TEST_V72_2 PASS')
