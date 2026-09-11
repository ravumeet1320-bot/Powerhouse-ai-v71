from v58_engine import build_v58
v57={'opportunity_radar':[{'symbol':'AAA','sector':'METAL','ltp':101,'change_pct':2.2,'volume':100000,'rvol':2.1,'prev_day_high':101.1,'vwap':99.8,'oi_change_pct':5,'relative_strength':{'vs_market':1.2,'vs_sector':.8},'liquidity':{'spread_pct':.04,'bid_pressure_pct':67,'status':'HEALTHY'},'stage':'TRIGGER READY','early_score':84},{'symbol':'BBB','sector':'IT','ltp':200,'change_pct':6,'volume':50000,'relative_strength':{'vs_market':4,'vs_sector':3},'liquidity':{'spread_pct':.3,'status':'REJECT'},'stage':'ATTACKING','early_score':70}]}
r=build_v58({},v57)
assert r['version']=='58.0' and r['read_only'] and not r['execution_enabled']
assert r['command_center']['best_now'][0]['symbol']=='AAA'
assert r['full_radar'][0]['data_quality']['fields']['rvol'] is True
assert 'counter_evidence' in r['full_radar'][0]['conflict_matrix']
assert r['data_coverage']['scanned']==2
print('V58 TESTS PASS — command center, anomaly, confluence, conflict, coverage')
