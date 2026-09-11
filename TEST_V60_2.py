from demo_data import demo_snapshot
from volume_intel import build_volume_intelligence
from daily_plan_engine import build_daily_plan

s=demo_snapshot(); v=build_volume_intelligence(s); p=build_daily_plan(s,None,v)
assert p['version']=='60.2'
assert p['read_only'] and not p['execution_enabled']
assert p['market_snapshot']['spot'] is not None
assert len(p['plan_cards'])==3
assert p['plan_cards'][0]['name']=='BULL SCENARIO'
assert p['plan_cards'][1]['name']=='BEAR SCENARIO'
assert p['plan_cards'][2]['name']=='NO-TRADE ZONE'
assert 'strike_battle' in p['option_context']
assert p['observable_channel_inspiration']['channel']=='@BestTeacher-MA'
print('V60.2 TESTS PASS — daily NIFTY scenario plan, ORB/VWAP, OI walls, strike battle, truth policy')
