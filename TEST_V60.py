from v60_engine import build_v60
m={'last_tick_epoch':__import__('time').time(),'source':'test','websocket_connected':True}
v58={'data_coverage':{'health':'HEALTHY','pct':{'price':100,'volume':100,'rvol':100,'oi':100,'structure':100}},'full_radar':[
 {'symbol':'AAA','ltp':101,'change_pct':2.2,'rvol':2.1,'stage':'TRIGGER READY','early_score':88,'micro_burst_score':70,'move_maturity':'DEVELOPING','entry_quality':'IDEAL / WATCH','confluence_map':[{'level':'PDH'}],'data_quality':{'score':90,'fields':{'price':True,'volume':True,'rvol':True,'structure':True,'depth':True,'oi':True,'vwap':True}},'conflict_matrix':{'severity':'LOW'},'relative_strength':{'vs_market':1.2,'vs_sector':.8},'oi_velocity_pct_per_min':.5,'price_velocity_pct_per_min':.4,'liquidity':{'status':'HEALTHY','bid_pressure_pct':66},'action':'BUY'},
 {'symbol':'BBB','ltp':200,'change_pct':6,'stage':'ATTACKING','early_score':70,'micro_burst_score':40,'move_maturity':'EXTENDED','entry_quality':'CHASE','confluence_map':[],'data_quality':{'score':50,'fields':{'price':True,'volume':True,'rvol':False,'structure':False,'depth':True,'oi':False,'vwap':True}},'conflict_matrix':{'severity':'SEVERE'},'relative_strength':{'vs_market':-1,'vs_sector':-1},'liquidity':{'status':'REJECT','bid_pressure_pct':35},'action':'WAIT'}]}
r=build_v60(m,v58)
assert r['version']=='60.0' and r['read_only'] and not r['execution_enabled']
assert r['command_center']['best_now'][0]['symbol']=='AAA'
assert r['command_center']['best_now'][0]['final_action']=='BUY'
assert r['command_center']['avoid'][0]['symbol']=='BBB'
assert 'timeline' in r['radar'][0]['lifecycle']
assert r['production_readiness']['score']==100.0
print('V60 TESTS PASS — lifecycle, freshness, firewall, benchmark, readiness, read-only action router')
