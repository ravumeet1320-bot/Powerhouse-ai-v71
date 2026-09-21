from pathlib import Path
import re

import v744_app
import v744_engine as core

ROOT = Path(__file__).parent
UI = (ROOT / 'static' / 'v744.html').read_text(errors='ignore')
LIGHT = (ROOT / 'static' / 'v744_light_draft.html').read_text(errors='ignore')
SW = (ROOT / 'static' / 'sw.js').read_text(errors='ignore')
RENDER = (ROOT / 'render.yaml').read_text(errors='ignore')

# 1) Entrypoint and full cumulative API preservation.
app = v744_app.app
assert app.version == '74.4', app.version
paths = {getattr(r, 'path', None) for r in app.router.routes}
legacy_required = {
    '/', '/api/health', '/api/v74/status', '/api/v74/workspaces', '/api/v74/coverage',
    '/api/v74/radar', '/api/v74/big-move', '/api/v74/alerts', '/api/v74/calls',
    '/api/v74/call/{symbol}', '/api/v74/journal', '/api/v74/missed-moves',
    '/api/v74/performance', '/api/v74/forensics', '/api/v74/replay/{symbol}',
    '/api/v74/hero/{symbol}', '/api/v74/chart/{symbol}', '/api/v74/option-chain/{symbol}',
    '/api/v74/telemetry/ui', '/api/v74.3/status', '/api/v74.3/index-command',
    '/api/v74.3/intelligence/{symbol}', '/api/v74.3/precision', '/api/v74.3/decisions',
    '/api/v74.3/accuracy', '/api/v74.3/sla', '/api/v74.3/config',
    '/api/v74.3/feature-manifest', '/api/v74.3/memory/status', '/api/v74.3/memory/recent',
    '/api/v74.3/push/public-key', '/api/v74.3/push/subscribe', '/api/v74.3/push/unsubscribe',
}
v744_required = {
    '/api/v74.4/command-center', '/api/v74.4/options/{symbol}',
    '/api/v74.4/chart-behaviour/{symbol}', '/api/v74.4/alerts',
    '/api/v74.4/test-alert', '/api/v74.4/system', '/v743', '/v744-light',
}
missing = sorted((legacy_required | v744_required) - paths)
assert not missing, missing
assert 'uvicorn v74_app:app' in RENDER

# 2) Locked V74.3 UI contracts are retained and V74.4 is additive.
locked = [
    'COMMAND','INDEX CALLS','MARKET','SMART MONEY','FII/DII','HEATWAVE','SECTORS',
    'AUTO TRENDER','CIRCUITS','ULTRA CALLS','CHART PRO','SUPPLY/DEMAND','S/R BREAK',
    'ULTRA DERIVATIVES','OPTION CHAIN','OI WALLS','DEPTH/DOM','EXPIRY HERO','ALERTS',
    'WATCHLIST','ACCURACY','REPLAY','AUDIT','SYSTEM'
]
for name in locked:
    assert f'data-feature="{name}"' in UI, name
for name in ['MOVE RADAR','EXECUTION','DERIV PULSE','BEHAVIOUR LAB','V74.4 SYSTEM']:
    assert f'data-feature="{name}"' in UI, name
assert 'V744_MASTER_REBUILD' in UI
assert 'V743_LOCKED_24_PRESERVED' in UI
assert 'NO_SYNTHETIC_MARKET_VALUES' in UI
assert 'computeRSI' in UI and 'computeMACD' in UI
assert 'Math.sin(i/7)' not in UI and 'Math.sin(i/6)' not in UI
assert '/api/v74.4/command-center' in UI
assert '/api/v74.4/options/' in UI
assert '/api/v74.4/chart-behaviour/' in UI
assert '/api/v74.4/test-alert' in UI
assert '/api/v74.3/push/subscribe' in UI
assert "serviceWorker.register('/static/sw.js?v=7'" in UI
assert ('powerhouse-v74-4-master-verified-v2' in SW or 'powerhouse-v74-5-adaptive-intelligence-master-final-v1' in SW)
assert 'Move Capture' in LIGHT  # supplied light draft preserved for reference

# 3) Pure V74.4 engine checks: real candle derivation, no future knowledge.
candles=[]
px=24000.0
for i in range(90):
    o=px
    c=px + (12 if i % 4 else -5)
    h=max(o,c)+8
    l=min(o,c)-7
    v=100000 + i*2500
    candles.append([f't{i}',o,h,l,c,v])
    px=c
b=core.behaviour_summary(candles, {'prev_day_high':23950,'prev_day_low':23600,'prev_day_close':23820})
assert b['status']=='READY', b
assert b['levels']['vwap'] is not None
assert b['levels']['support'] is not None and b['levels']['resistance'] is not None
assert b['candle_patterns']['source']=='CANDLE_DERIVED'
assert b['chart_patterns']['source']=='CANDLE_DERIVED'

chain={'expiry':'2099-01-01','spot':24000,'source':'TEST_PROVIDER','chain':[
    {'strike':23950,'ce':{'ltp':120,'oi':5000,'prev_oi':4500,'volume':2500,'bid':119.8,'ask':120.2,'bid_qty':400,'ask_qty':380},
                    'pe':{'ltp':70,'oi':7500,'prev_oi':7000,'volume':3200,'bid':69.8,'ask':70.2,'bid_qty':500,'ask_qty':450}},
    {'strike':24000,'ce':{'ltp':95,'oi':9000,'prev_oi':8500,'volume':6000,'bid':94.9,'ask':95.1,'bid_qty':900,'ask_qty':850},
                    'pe':{'ltp':92,'oi':10000,'prev_oi':9200,'volume':6500,'bid':91.9,'ask':92.1,'bid_qty':950,'ask_qty':900}},
    {'strike':24050,'ce':{'ltp':73,'oi':12000,'prev_oi':11000,'volume':4100,'bid':72.9,'ask':73.1,'bid_qty':700,'ask_qty':650},
                    'pe':{'ltp':118,'oi':6000,'prev_oi':5800,'volume':2700,'bid':117.8,'ask':118.2,'bid_qty':420,'ask_qty':390}},
]}
first=core.chain_summary(chain)
assert first['spot']==24000
assert first['pcr_oi'] is not None
assert first['call_wall']['strike']==24050
assert first['put_wall']['strike']==24000
assert len(first['near_atm_strikes'])==3
chain2={'expiry':'2099-01-01','spot':24010,'source':'TEST_PROVIDER','chain':chain['chain']}
chain2['chain']=[{**r,'ce':{**r['ce'],'ltp':r['ce']['ltp']*1.03,'oi':r['ce']['oi']+100},'pe':{**r['pe'],'ltp':r['pe']['ltp']*.99,'oi':r['pe']['oi']+150}} for r in chain['chain']]
second=core.chain_summary(chain2,first)
assert second['pulse']['call_oi_change_since_pulse'] == 300
assert second['pulse']['put_oi_change_since_pulse'] == 450
assert second['liquidity_score'] is not None

activity=core.sudden_activity(
    {'symbol':'RELIANCE','ltp':3010,'score':78,'stage':'TRIGGER NEAR','rvol':3.2,'volume':1500000,'futures_oi':1010000,'bid':3009.8,'ask':3010.2,'bid_qty':1500,'ask_qty':1300},
    {'symbol':'RELIANCE','ltp':2998,'score':65,'stage':'BUILDING','rvol':1.3,'volume':1200000,'futures_oi':1000000,'bid':2997.5,'ask':2998.5,'bid_qty':700,'ask_qty':800},
)
assert activity['intensity'] > 0
assert any(e['kind']=='STAGE_CHANGE' for e in activity['events'])
assert any(e['kind']=='VOLUME_BURST' for e in activity['events'])

plan=core.stock_trade_plan({'symbol':'ABC','ltp':100,'score':80,'change_pct':1.1,'side':'BUY','day_high':100.2,'prev_day_high':100.5,'high_20d':101,'day_low':98.5,'prev_day_low':97.8,'bid':99.9,'ask':100.1,'bid_qty':1000,'ask_qty':900,'volume':1000000,'futures_oi':800000})
assert plan['instrument']=='STOCK'
assert plan['status'] in {'READY','TRIGGER NEAR','WATCH'}
assert plan['sl'] is not None and plan['targets']['t1'] is not None

# 4) Four-index derivative coverage is explicit in the V74.4 backend.
source=(ROOT/'v744_app.py').read_text(errors='ignore')
assert 'INDEXES=("NIFTY","BANKNIFTY","MIDCPNIFTY","SENSEX")' in source
assert 'symbol=INDEXES[i%len(INDEXES)]' in source

print('TEST_V74_4_MASTER PASS')
