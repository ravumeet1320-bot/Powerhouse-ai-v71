from v72_engine import _fast_signal_profile, build_v72
from demo_data import demo_snapshot


def strong_row():
    return {
        'v72_side':'CE','pre_move_score':82,'quote_age_sec':2.0,'late_entry':False,
        'opportunity_decay':12,'depth_intelligence':{'spread_pct':0.2},
        'directional_evidence':{'aligned_groups':6,'opposed_groups':0},
        'persistence':{'samples':3,'evidence_persistence':80,'score_stability':88},
    }


def test_confirmed_fast_signal():
    x=_fast_signal_profile(strong_row())
    assert x['tier']=='CONFIRMED'
    assert x['action']=='BUY CE'
    assert x['freshness_pass'] is True


def test_stale_block():
    r=strong_row(); r['quote_age_sec']=16
    x=_fast_signal_profile(r)
    assert x['tier']=='NONE' and x['action']=='WAIT'


def test_conflict_block():
    r=strong_row(); r['directional_evidence']={'aligned_groups':6,'opposed_groups':2}
    x=_fast_signal_profile(r)
    assert x['tier']=='NONE'


def test_build_flags():
    v=build_v72(demo_snapshot(),record=False)
    assert v['version']=='72.0'
    assert v['release']=='72.1-fast-signal'
    assert v['modules']['fast_signal_two_stage'] is True
    assert v['modules']['independent_evidence_accuracy_guard'] is True


if __name__=='__main__':
    test_confirmed_fast_signal(); test_stale_block(); test_conflict_block(); test_build_flags()
    print('TEST_V72_1 PASS')
