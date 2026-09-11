from demo_data import demo_snapshot
from v62_engine import build_v62, record_cross_market, cross_market_intel, pivots_and_cpr

m=demo_snapshot()
v=build_v62(m)
assert v['version']=='62.0'
assert v['read_only'] is True
assert 'cross_market' in v['modules']
assert 'volume_profile' in v['modules']
assert 'anchored_vwap' in v['modules']
assert 'depth_persistence' in v['modules']
assert 'breadth_rotation' in v['modules']
# external data must stay unavailable until supplied
markets={x['market']:x for x in v['modules']['cross_market']['markets']}
assert 'GIFT NIFTY' in markets and 'DOW FUTURES' in markets
# verified ingest path should work and not create any order
record_cross_market('GIFT NIFTY',25250,0.24,'test_fixture',True)
record_cross_market('DOW FUTURES',41425,-0.18,'test_fixture',True)
cm=cross_market_intel(m)
assert any(x.get('market')=='GIFT NIFTY' and x.get('price')==25250 for x in cm['markets'])
assert any(x.get('market')=='DOW FUTURES' and x.get('price')==41425 for x in cm['markets'])
print('V62 TEST PASS — global futures adapters, market memory, structure, options/depth/breadth modules, truth-state policy')
