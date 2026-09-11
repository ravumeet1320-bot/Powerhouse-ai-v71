from __future__ import annotations
import os, tempfile, time
from pathlib import Path

# Isolate test DB before importing engine.
os.environ['POWERHOUSE_V71_DB_PATH'] = str(Path(tempfile.gettempdir())/'powerhouse_v71_test.sqlite3')
try: Path(os.environ['POWERHOUSE_V71_DB_PATH']).unlink()
except FileNotFoundError: pass

from v71_engine import universal_census, stock_option_hero, chart_intelligence, build_v71

now=time.time()
rows=[]
for i in range(137):
    px=100+i*.7
    rows.append({
        'symbol':f'STK{i:03d}','sector':'F&O','ltp':px,'cp':px/(1+(0.4+i%7*.1)/100),
        'change_pct':0.4+i%7*.1,'live':True,'volume':100000+i*1000,'rvol':1.0+(i%5)*.2,
        'bid':px-.05,'ask':px+.05,'bid_qty':1000+i,'ask_qty':900+i,
        'prev_day_high':px*1.003,'prev_day_low':px*.993,'prev_day_close':px*.996,
        'high_20d':px*1.05,'low_20d':px*.92,'high_50d':px*1.08,'low_50d':px*.88,
        'high_52w':px*1.2,'low_52w':px*.7,'atp':px*.998,
        'futures_oi':1000000+i*100,'futures_oi_change_pct':2.0+(i%4),
        'quote_epoch':now,'instrument_key':f'NSE_EQ|{i}','future_key':f'NSE_FO|F{i}','future_expiry':'2026-09-24'
    })
snapshot={'sector_heatmap':rows,'fno_foundation':{'universe_count':len(rows)},'demo':True,'spot':25000,'option_data':[],'price_series':{},'active_underlying':'NIFTY'}
c=universal_census(snapshot,record=False)
assert c['observed']==137, c['observed']
assert c['expected_universe']==137
assert c['coverage_pct']==100.0
assert len(c['all_rows'])==137, 'full census must not be truncated'
assert all('PDC' in r['nearest_levels']['all'] for r in c['all_rows'])

under=c['all_rows'][0].copy();under['side']='CE';under['evidence_score']=88
chain={'expiry':'2026-09-24','chain':[]}
for k,strike in enumerate(range(90,131,5)):
    chain['chain'].append({'strike':strike,
       'ce':{'ltp':8+k*2,'oi':200000+k*1000,'prev_oi':190000,'volume':50000+k*1000,'bid':7.9+k*2,'ask':8.1+k*2,'iv':22,'delta':.45,'gamma':.012,'theta':-1.2,'vega':2.1,'key':f'CE{k}'},
       'pe':{'ltp':7+k,'oi':180000,'prev_oi':175000,'volume':40000,'bid':6.8+k,'ask':7.2+k,'iv':23,'delta':-.42,'gamma':.011,'theta':-1.1,'vega':2.0,'key':f'PE{k}'}})
# Explicitly test that an option premium above 100 is not excluded by a premium cap.
chain['chain'].append({'strike':150,'ce':{'ltp':145,'oi':300000,'prev_oi':280000,'volume':120000,'bid':144.5,'ask':145.5,'iv':21,'delta':.72,'gamma':.008,'theta':-1.4,'vega':2.5,'key':'CE-HIGH'},'pe':{}})
h=stock_option_hero(under['symbol'],under,chain,record=False)
assert h['contracts_scored']>=10
assert any(x['premium']>100 for x in h['candidates']), 'no premium ceiling'

candles=[]
base=100.0
for i in range(60):
    o=base+i*.12; cl=o+.18 if i%4 else o-.05
    candles.append({'ts':f'2026-09-11T09:{15+i:02d}:00+05:30','open':o,'high':max(o,cl)+.2,'low':min(o,cl)-.15,'close':cl,'volume':10000+i*250})
ci=chart_intelligence(candles,under['symbol'],5,snapshot,under)
assert ci['status']=='READY'
assert ci['volume_profile']['status']=='READY'
assert 'bullish_acceptance_above' in ci['scenario']
assert ci['data_truth']['future_leakage'] is False

b=build_v71(snapshot,record=False)
assert b['version']=='71.0'
assert b['coverage_guard']['coverage_pct']==100.0
print('TEST_V71 PASS')
