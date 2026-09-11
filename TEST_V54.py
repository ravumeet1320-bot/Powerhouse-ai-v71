from demo_data import demo_snapshot
from ai_engine import AIFusionEngine
from smart_money import analyse_smart_money
from opportunity_engine import build_opportunity_radar
from supreme_engine import build_supreme_intelligence
from v53_engine import build_v53
from v54_engine import build_v54, stock_option_heatmap

snap=demo_snapshot(); ai=AIFusionEngine().analyse(snap, mode='balanced'); sm=analyse_smart_money(snap); radar=build_opportunity_radar(snap,ai,sm); v50=build_supreme_intelligence(snap,ai,sm,radar); v53=build_v53(snap,ai,sm,radar,v50); v54=build_v54(snap,ai,sm,radar,v53)
assert v54['version']=='54.0'
assert v54['read_only'] and not v54['execution_enabled']
assert 'stock_heatmap' in v54 and 'index_options_heatmap' in v54
assert 'visual_bars' in v54 and 'decision_flow' in v54
# Exact stock option heatmap normalization test
m=stock_option_heatmap('TEST','2026-09-24',[{'strike':100,'spot':101,'ce':{'ltp':4,'oi':1000,'volume':200,'bid':3.9,'ask':4.1,'bid_qty':500,'ask_qty':300},'pe':{'ltp':3,'oi':900,'volume':180,'bid':2.9,'ask':3.1,'bid_qty':250,'ask_qty':450}}])
assert m['available'] and m['rows'][0]['ce']['activity_score']>=0
print('V54 TESTS PASS — heatmaps, visual bars, decision flow, on-demand stock options')
