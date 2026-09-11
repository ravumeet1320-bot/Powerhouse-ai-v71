from demo_data import demo_snapshot
from ai_engine import AIFusionEngine
from smart_money import analyse_smart_money
from opportunity_engine import build_opportunity_radar
from supreme_engine import build_supreme_intelligence
from v53_engine import build_v53
from v55_engine import build_v55
from v56_engine import build_v56
from v57_engine import build_v57

def build():
    s=demo_snapshot(); a=AIFusionEngine().analyse(s,mode='balanced'); sm=analyse_smart_money(s); r=build_opportunity_radar(s,a,sm); v50=build_supreme_intelligence(s,a,sm,r); v53=build_v53(s,a,sm,r,v50); v55=build_v55(s,v53); return build_v57(s,build_v56(s,v55))

def test_v57_contract():
    v=build(); assert v['version']=='57.0'; assert v['read_only'] is True; assert v['execution_enabled'] is False

def test_radar_shapes():
    v=build(); assert 'opportunity_radar' in v and 'market_regime' in v and 'shadow_scanner' in v

def test_no_probability_claim():
    v=build(); assert any('not win probability' in x for x in v['truth_policy'])
