from ai_engine import AIFusionEngine
from demo_data import demo_snapshot

snap = demo_snapshot()
r = AIFusionEngine().analyse(snap, 'balanced')
assert r['ok'] is True
assert r['orders_enabled'] is False
assert r['pnl_enabled'] is False
assert r['execution_enabled'] is False
assert r['signal'] in {'BUY CE','BUY PE','WAIT'}
assert len(r['agents']) == 8
assert any(x['name'] == 'Index Brain' for x in r['agents'])
assert len(r['radar']) > 0
assert r['signal_grade'] in {'A+','A','B+','B','C','FILTERED'}
assert len(r['forecast']) == 3
assert 0 <= r['false_signal_risk'] <= 100
assert 0 <= r['anomaly_score'] <= 100
assert 0 <= r['stability_score'] <= 100
assert isinstance(r['watch_conditions'], list) and r['watch_conditions']
for code in ('NIFTY','BANKNIFTY'):
    brain = snap['index_brain'][code]
    assert brain['stocks']
    assert 0 <= brain['confirmation_score'] <= 100
    assert 0 <= brain['divergence_risk'] <= 100
    assert brain['leaders'] and brain['drags']
print('SELF TEST PASS — AI Index Brain v5')
print('Signal:', r['signal'])
print('Confidence:', r['confidence'])
print('NIFTY Index Brain:', r['index_confirmation']['direction'], r['index_confirmation']['confirmation_score'])
print('BANKNIFTY Brain:', r['banknifty_brain']['direction'], r['banknifty_brain']['confirmation_score'])
print('Agents:', ', '.join(x['name'] for x in r['agents']))
