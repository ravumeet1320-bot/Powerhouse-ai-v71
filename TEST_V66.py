import os,tempfile,importlib,time
fd,path=tempfile.mkstemp(suffix='.sqlite3');os.close(fd);os.unlink(path)
os.environ['POWERHOUSE_V66_DB_PATH']=path
import v66_engine as v;importlib.reload(v)
snap={'underlying':'NIFTY','fno_universe':[{'symbol':'TATASTEEL','sector':'METALS','ltp':170,'change_pct':2.1,'rvol':2.0,'futures_oi_change_pct':4.2,'vwap':168,'bid':169.9,'ask':170.1},{'symbol':'JSWSTEEL','sector':'METALS','ltp':1000,'change_pct':1.5,'rvol':1.7,'futures_oi_change_pct':2.5},{'symbol':'HDFCBANK','sector':'BANKS','ltp':1800,'change_pct':.2,'rvol':.9,'futures_oi_change_pct':.1}], 'option_chain':[{'strike':25000,'ce':{'oi':1000,'iv':14,'gamma':.001,'theta':12},'pe':{'oi':1400,'iv':15,'gamma':.0011,'theta':13}}]}
r=v.record_snapshot(snap); assert r['recorded']==3
with v._db() as c:
 c.execute('UPDATE metric_snapshots_v66 SET epoch=epoch-3600'); c.execute('UPDATE option_snapshots_v66 SET epoch=epoch-3600'); c.commit()
snap['fno_universe'][0]['ltp']=173;snap['fno_universe'][0]['change_pct']=3.8;snap['fno_universe'][0]['rvol']=2.8
v.record_snapshot(snap)
h=v.metric_history('TATASTEEL',120);assert h['count']>=2
rot=v.sector_rotation(60);assert 'rows' in rot
rep=v.replay('TATASTEEL',120);assert rep['count']>=2
v.record_detection({'symbol':'TATASTEEL','price':170,'action':'BUY CE','stage':'TRIGGER READY','score':80})
with v._db() as c:c.execute('UPDATE detections_v66 SET epoch=epoch-600');c.commit()
v.evaluate_outcomes(5)
b=v.build_v66(snap);assert b['version']=='66.0' and b['modules']['point_in_time_replay']
print('TEST_V66 PASS')
try:os.unlink(path)
except:pass
