import tempfile, os, importlib, sys
from pathlib import Path
fd, path=tempfile.mkstemp(suffix='.sqlite3'); os.close(fd); os.unlink(path)
os.environ['POWERHOUSE_DB_PATH']=path
import v64_engine as v
# explicit verified data only
v.ingest_institutional({'type':'activity','rows':[{'trade_date':'2026-09-09','participant':'FII','segment':'CASH','buy_value':100,'sell_value':80,'verified':True,'source':'OFFICIAL TEST'},{'trade_date':'2026-09-09','participant':'DII','segment':'CASH','buy_value':70,'sell_value':90,'verified':True,'source':'OFFICIAL TEST'}]})
v.ingest_institutional({'type':'participant_oi','rows':[{'trade_date':'2026-09-09','participant':'PRO','segment':'INDEX FUTURES','long_contracts':120,'short_contracts':80,'verified':True,'source':'OFFICIAL TEST'}]})
v.ingest_institutional({'type':'holding','rows':[{'as_of':'2026-06-30','symbol':'TATASTEEL','category':'FPI','holding_pct':18.2,'verified':True,'source':'SHAREHOLDING TEST'},{'as_of':'2026-03-31','symbol':'TATASTEEL','category':'FPI','holding_pct':17.4,'verified':True,'source':'SHAREHOLDING TEST'}]})
v.ingest_institutional({'type':'deal','rows':[{'trade_date':'2026-09-09','symbol':'TATASTEEL','entity':'Fund X','deal_type':'BLOCK','side':'BUY','quantity':1000,'price':150,'category':'FPI','verified':True,'source':'DEAL TEST'}]})
market={'sector_data':[{'symbol':'TATASTEEL','sector':'METALS','ltp':150,'prev_close':145,'change_pct':3.45,'rvol':2.1,'futures_oi_change_pct':5.0,'stage':'TRIGGER READY'},{'symbol':'HINDALCO','sector':'METALS','ltp':700,'prev_close':690,'change_pct':1.45,'rvol':1.4,'futures_oi_change_pct':2.0,'stage':'BUILDING'},{'symbol':'INFY','sector':'IT','ltp':1500,'prev_close':1498,'change_pct':0.13,'rvol':0.9}], 'last_tick_epoch':1}
so=v.sector_best_opportunities(market); assert so['sector']=='METALS' and so['best_opportunities'][0]['symbol']=='TATASTEEL'
h=v.holding_changes(); assert h['increased'][0]['symbol']=='TATASTEEL' and h['increased'][0]['change_pp']>0
p=v.participant_positioning(); assert p['positions'][0]['participant']=='PRO' and p['positions'][0]['bias']=='NET LONG'
f=v.institutional_footprint_score(market); assert f['leaders'][0]['symbol']=='TATASTEEL'
b=v.build_v64(market); assert b['read_only'] and b['version']=='64.0'
print('V64 TEST PASS — strongest-sector opportunities + FII/DII/PRO positioning + holdings changes + verified institutional footprints')
try: os.unlink(path)
except: pass
