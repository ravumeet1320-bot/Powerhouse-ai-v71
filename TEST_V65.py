import os, tempfile, importlib, json
fd,path=tempfile.mkstemp(suffix='.sqlite3'); os.close(fd); os.unlink(path)
os.environ['POWERHOUSE_V65_DB_PATH']=path
import v65_engine as v
importlib.reload(v)
market={'fno_universe':[{'symbol':'TATASTEEL','sector':'METALS','change_pct':2.1,'rvol':1.8,'futures_oi_change_pct':5.2},{'symbol':'JSWSTEEL','sector':'METALS','change_pct':1.2,'rvol':1.4,'futures_oi_change_pct':3.0},{'symbol':'HDFCBANK','sector':'BANKS','change_pct':.4,'rvol':1.0,'futures_oi_change_pct':.5}]}
# Caller cannot self-verify even with official source id.
r=v.ingest_verified('holding',[{'as_of':'2026-06-30','symbol':'TATASTEEL','category':'FPI','holding_pct':10.0}], 'NSE_OFFICIAL')
assert r['verified'] is False
# Internal trusted adapter can verify.
v.ingest_verified('holding',[{'as_of':'2026-03-31','symbol':'TATASTEEL','category':'FPI','holding_pct':8.0},{'as_of':'2025-12-31','symbol':'TATASTEEL','category':'FPI','holding_pct':7.0}], 'NSE_OFFICIAL',trusted_context=True)
v.ingest_verified('holding',[{'as_of':'2026-06-30','symbol':'TATASTEEL','category':'FPI','holding_pct':10.0},{'as_of':'2026-03-31','symbol':'JSWSTEEL','category':'MF','holding_pct':5.0},{'as_of':'2026-06-30','symbol':'JSWSTEEL','category':'MF','holding_pct':5.7}], 'NSE_OFFICIAL',trusted_context=True)
v.ingest_verified('participant_oi',[{'trade_date':'2026-09-10','participant':'FII','segment':'INDEX FUTURES','long_contracts':120000,'short_contracts':90000},{'trade_date':'2026-09-09','participant':'FII','segment':'INDEX FUTURES','long_contracts':110000,'short_contracts':95000}], 'NSE_OFFICIAL',trusted_context=True)
v.ingest_verified('deal',[{'trade_date':'2026-09-09','symbol':'TATASTEEL','entity':'ABC Mutual Fund','side':'BUY','quantity':100000,'price':170}], 'NSE_OFFICIAL',trusted_context=True)
v.ingest_verified('promoter',[{'as_of':'2026-06-30','symbol':'TATASTEEL','promoter_holding_pct':33.2,'pledge_pct':0.0},{'as_of':'2026-03-31','symbol':'TATASTEEL','promoter_holding_pct':33.0,'pledge_pct':0.2}], 'NSE_OFFICIAL',trusted_context=True)
ot=v.ownership_trends(); assert ot['status']=='READY'; assert any(x['symbol']=='TATASTEEL' for x in ot['rows'])
pt=v.participant_trends(); assert pt['rows'][0]['net_change']==15000
sm=v.sector_money_map(market); assert sm['status']=='READY'; assert sm['strongest_institutional_sector']['sector']=='METALS'
sc=v.stock_consensus(market); assert sc['status']=='READY' and sc['leaders'][0]['symbol'] in {'TATASTEEL','JSWSTEEL'}
b=v.build_v65(market); assert b['version']=='65.0'; assert 'money_map' in b
print('TEST_V65 PASS')
try: os.unlink(path)
except: pass
