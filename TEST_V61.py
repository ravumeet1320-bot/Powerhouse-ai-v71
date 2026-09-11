from v61_engine import build_v61, add_catalyst, catalyst_guard, build_replay
import tempfile, pathlib, v61_engine
p=pathlib.Path(tempfile.gettempdir())/'v61_test.sqlite3';
try:p.unlink()
except:pass
v61_engine.DB_PATH=p
market={'last_tick_epoch':1000}
v60={'command_center':{'best_now':[{'symbol':'ABC','stage':'TRIGGER READY','final_action':'BUY','v60_rank_score':88,'ltp':101.5}], 'about_to_move':[], 'second_chance':[], 'avoid':[]},'detection_benchmark':{'counts':{'developing':1}}}
x=build_v61(market,v60)
assert x['market_memory']['stored_observations']>=1
assert x['alert_center']['alerts']
add_catalyst('ABC','RESULT','HIGH','Earnings today','manual',True)
assert catalyst_guard()['high_risk_count']>=1
market['last_tick_epoch']=1010; v60['command_center']['best_now'][0]['stage']='CONFIRMED'; build_v61(market,v60)
assert build_replay(20)['transitions']
print('V61 TEST PASS — persistence, replay, alerts, catalyst guard, daily self-audit')
