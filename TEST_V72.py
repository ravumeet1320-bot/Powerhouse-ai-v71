from demo_data import demo_snapshot
from v72_engine import build_v72, pre_move_radar, predictive_strike_selector, predictive_chart_intelligence


def fake_chain(symbol='TEST'):
    return {
        'symbol': symbol, 'expiry': '2026-09-24', 'expiries':['2026-09-24','2026-10-29'], 'spot': 1000,
        'chain': [
            {'strike': 980, 'ce': {'ltp': 62,'oi':120000,'prev_oi':110000,'volume':22000,'bid':61.5,'ask':62.5,'iv':22,'delta':.62,'gamma':.003,'theta':-2.1,'key':'CE980'}, 'pe': {'ltp':52,'oi':90000,'prev_oi':92000,'volume':16000,'bid':51.5,'ask':52.5,'iv':23,'delta':-.28,'gamma':.0027,'theta':-1.8,'key':'PE980'}},
            {'strike':1000, 'ce': {'ltp':58,'oi':150000,'prev_oi':130000,'volume':36000,'bid':57.5,'ask':58.5,'iv':24,'delta':.51,'gamma':.0035,'theta':-2.4,'key':'CE1000'}, 'pe': {'ltp':60,'oi':170000,'prev_oi':150000,'volume':38000,'bid':59.5,'ask':60.5,'iv':24,'delta':-.49,'gamma':.0036,'theta':-2.3,'key':'PE1000'}},
            {'strike':1020, 'ce': {'ltp':51,'oi':105000,'prev_oi':95000,'volume':25000,'bid':50.5,'ask':51.5,'iv':25,'delta':.37,'gamma':.0031,'theta':-2.0,'key':'CE1020'}, 'pe': {'ltp':68,'oi':130000,'prev_oi':118000,'volume':26000,'bid':67.5,'ask':68.5,'iv':25,'delta':-.63,'gamma':.003,'theta':-2.2,'key':'PE1020'}},
        ]
    }


def test_build():
    snap=demo_snapshot(); v=build_v72(snap,record=False)
    assert v['version']=='72.0'
    assert v['execution_enabled'] is False
    assert 'ai_brain' in v and 'pre_move_rows' in v
    assert v['modules']['late_entry_filter'] is True


def test_strike_floor_and_pcr():
    u={'symbol':'TEST','ltp':1000,'v72_side':'CE','side':'CE','pre_move_score':82,'evidence_score':82}
    x=predictive_strike_selector('TEST',u,fake_chain())
    assert x['status']=='READY'
    assert x['pcr']['oi_pcr'] is not None
    if x['winner']:
        assert x['winner']['premium']>=50
        assert x['winner']['side']=='CE'


def test_chart():
    candles=[]
    px=100.0
    for i in range(80):
        drift=(i-40)*0.01
        o=px+drift; c=o+(0.2 if i%3 else -0.08); h=max(o,c)+0.3; l=min(o,c)-0.3
        candles.append({'ts':str(i),'open':o,'high':h,'low':l,'close':c,'volume':1000+i*15})
        px=c
    x=predictive_chart_intelligence(candles,'TEST',5,{},None)
    assert x['status']=='READY'
    assert x['side'] in ('CE','PE','WAIT')
    assert 'compression' in x and 'rsi' in x


if __name__=='__main__':
    test_build(); test_strike_floor_and_pcr(); test_chart(); print('TEST_V72 PASS')
