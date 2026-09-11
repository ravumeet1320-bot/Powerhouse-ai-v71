from v53_engine import minimum_opportunity, build_v53

def c(symbol='ABC', side='CE', sector='Metal', q=90):
    return {'symbol':symbol,'side':side,'kind':'STOCK','sector':sector,'quality':q,'ltp':100,'levels':{'entry_trigger':100,'sl':99,'t1':102,'t2':103},'chase_risk':'LOW','reasons':[],'counter_signals':[]}

def test_room_rejects_tiny():
    x=c(); x['levels']={'entry_trigger':100,'sl':99.8,'t1':100.1,'t2':100.2}
    assert not minimum_opportunity(x)['pass']

def test_one_thesis_and_decorrelation():
    m={'last_tick_epoch':__import__('time').time(),'sector_heatmap':[{'symbol':'A','sector':'Bank','ltp':100,'change_pct':1,'live':True},{'symbol':'B','sector':'Bank','ltp':100,'change_pct':1,'live':True}]}
    r={'queue':[c('A','CE','Bank'),c('A','PE','Bank'),c('B','CE','Bank')]}
    v=build_v53(m,{}, {},r,{})
    assert len([x for x in v['one_decision'] if x['symbol']=='A'])==1
    assert len(v['best_now'])==1

def test_stale_suppresses_action():
    m={'last_tick_epoch':1,'sector_heatmap':[]}; r={'queue':[c()]}
    v=build_v53(m,{}, {},r,{})
    assert v['one_decision'][0]['action']=='WAIT'

def test_option_exact_contract():
    import time
    m={'last_tick_epoch':time.time(),'spot':100,'expiry':'2026-09-17','option_data':[{'strike':100,'cltp':5,'cbid':4.9,'cask':5.1,'cvol':1000,'coi':5000,'c_delta':.5}], 'sector_heatmap':[]}
    x=c('NIFTY','CE','INDEX'); x['kind']='INDEX'; r={'queue':[x]}
    v=build_v53(m,{}, {},r,{})
    assert v['options_contract_selector']['best_contract']['strike']==100

if __name__=='__main__':
    for f in [test_room_rejects_tiny,test_one_thesis_and_decorrelation,test_stale_suppresses_action,test_option_exact_contract]: f()
    print('V53 TESTS PASS — 4/4')
