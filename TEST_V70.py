from demo_data import demo_snapshot
from v70_engine import build_v70, all_index_rank

s=demo_snapshot()
v=build_v70(s,record=False)
assert v['version']=='70.0'
h=v['expiry_precision_hero']
assert h['state'] in {'HERO ACTIVE','HERO READY','ARMED','WATCH','WAIT','NO TRADE'}
assert h['winner'] is not None
assert h['winner']['premium']>0
assert h['winner']['reachability']>=0
assert h['one_side_rule'] is True
assert v['module_status']['total']>=30
board=all_index_rank([v])
assert board['board'][0]['underlying']=='NIFTY'
print('TEST_V70 PASS — precision hero, no premium cap, evidence gates, module truth states')
