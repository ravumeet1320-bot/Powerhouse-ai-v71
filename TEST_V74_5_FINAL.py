from pathlib import Path
import os
import time

import v74_app
import v745_engine as core
import v745_app

ROOT = Path(__file__).parent
UI = (ROOT / 'static' / 'v745.html').read_text(errors='ignore')
SW = (ROOT / 'static' / 'sw.js').read_text(errors='ignore')
RENDER = (ROOT / 'render.yaml').read_text(errors='ignore')
LEGACY_UI = (ROOT / 'static' / 'v744.html').read_text(errors='ignore')

# 1) Current entrypoint is V74.5 while legacy surfaces remain available.
app = v74_app.app
assert app.version == '74.5', app.version
paths = {getattr(r, 'path', None) for r in app.router.routes}
required = {
    '/', '/v743', '/v744', '/v744-light',
    '/api/health', '/api/v74.3/index-command', '/api/v74.3/intelligence/{symbol}',
    '/api/v74.4/command-center', '/api/v74.4/options/{symbol}',
    '/api/v74.5/command-center', '/api/v74.5/vix-risk', '/api/v74.5/setup/{symbol}',
    '/api/v74.5/alerts', '/api/v74.5/accuracy', '/api/v74.5/memory', '/api/v74.5/feature-manifest', '/api/v74.5/system',
}
missing = sorted(required - paths)
assert not missing, missing
assert 'uvicorn v74_app:app' in RENDER

# 2) UI is additive: all prior 24 locked modules + V74.4 + V74.5 modules are represented.
locked24 = [
    'COMMAND','INDEX CALLS','MARKET','SMART MONEY','FII/DII','HEATWAVE','SECTORS',
    'AUTO TRENDER','CIRCUITS','ULTRA CALLS','CHART PRO','SUPPLY/DEMAND','S/R BREAK',
    'ULTRA DERIVATIVES','OPTION CHAIN','OI WALLS','DEPTH/DOM','EXPIRY HERO','ALERTS',
    'WATCHLIST','ACCURACY','REPLAY','AUDIT','SYSTEM'
]
for name in locked24:
    assert f'data-feature="{name}"' in UI, name
for name in ['MOVE RADAR','EXECUTION','DERIV PULSE','BEHAVIOUR LAB','V74.4 SYSTEM',
             'ADAPTIVE CORE','VIX/RISK','MARKET MEMORY','V74.5 SYSTEM']:
    assert f'data-feature="{name}"' in UI, name
assert 'V745_ADAPTIVE_INTELLIGENCE_MASTER_FINAL' in UI
assert 'V743_LOCKED_24_PRESERVED' in UI
assert 'NO_SYNTHETIC_MARKET_VALUES' in UI
assert 'NO_TRADE_ABSTENTION' in UI
assert 'SMART_ALERT_MANAGER' in UI
assert 'INDIA_VIX_INTELLIGENCE' in UI
assert '/api/v74.5/command-center' in UI
assert '/api/v74.5/accuracy' in UI
assert "serviceWorker.register('/static/sw.js?v=8'" in UI
assert 'powerhouse-v74-5-adaptive-intelligence-master-final-v1' in SW
assert "['CRITICAL','TRADE READY','P0','P1']" in SW
assert 'id="decisionStrip"' in UI
assert 'id="alertBell"' in UI
assert 'IMPORTANT_ONLY' in UI
assert 'Only meaningful state changes are shown' in UI
assert 'Production test-alert controls are intentionally hidden' in UI
assert 'price=(v,d=2)' in UI and "Number(v)<=0?'—'" in UI
assert 'V74.4' in LEGACY_UI  # legacy UI remains preserved separately

# 3) Data-quality gate blocks stale/unavailable evidence and passes healthy evidence.
good = core.data_quality({'data_status':'LIVE','tick_age_sec':2,'rest_age_sec':10,'authenticated':True}, {'status':'READY'})
assert good['gate'] == 'PASS' and good['score'] >= 82, good
bad = core.data_quality({'data_status':'UNAVAILABLE','tick_age_sec':200,'rest_age_sec':300,'authenticated':False}, {'status':'ERROR'})
assert bad['gate'] == 'BLOCK' and bad['score'] < 62, bad

# 4) India VIX intelligence is contextual and never a standalone action.
now = time.time()
history = [{'epoch':now-(15-i)*60,'price':15.0+i*.03} for i in range(15)]
markets = [
    {'market':'INDIA VIX','price':17.2,'change_pct':3.5,'source':'TEST'},
    {'market':'GIFT NIFTY','price':25200,'change_pct':0.65},
    {'market':'S&P 500','price':6200,'change_pct':0.3},
    {'market':'DXY','price':98,'change_pct':-0.2},
]
vix = core.vix_intelligence(markets, history)
assert vix['available'] is True
assert vix['level'] == 17.2
assert vix['risk_score'] is not None
assert 'standalone BUY/SELL' in vix['truth']
macro = core.cross_market_context(markets)
assert macro['available_count'] >= 2

# 5) Regime + adaptive qualification: clean setup may qualify; poor execution/data abstains.
indexes = [{'change_pct':.8},{'change_pct':.7},{'change_pct':.65},{'change_pct':.55}]
regime = core.market_regime(indexes, vix, [])
assert regime['regime'] in {'TRENDING UP','HIGH VOLATILITY'}, regime
clean_setup = {
    'symbol':'NIFTY','instrument':'OPTION','action':'BUY CE','option_action':'BUY CE',
    'status':'READY','stage':'TRIGGER NEAR','quality':90,'cmp':100,'buy_above':98,
    'rr':1.9,'why':['trend','structure','participation'],'blocked_by':[],
    'liquidity':{'score':92,'spread_pct':.2},
}
q = core.qualify_setup(clean_setup, good, regime, vix)
a = q['adaptive']
assert a['signal_quality']['score'] >= 70
assert a['execution_quality']['score'] >= 60
assert a['lifecycle'] in {'READY','CONFIRMING'}
assert a['confidence_band'] in {'HIGH','MEDIUM','LOW'}

poor = dict(clean_setup)
poor['liquidity'] = {'score':18,'spread_pct':4.0}
poor['blocked_by'] = ['LOW LIQUIDITY']
qp = core.qualify_setup(poor, bad, regime, vix)
ap = qp['adaptive']
assert ap['qualified'] is False
assert ap['final_action'] in {'NO TRADE','WAIT'}
assert ap['no_trade_reasons']

# 6) Late/overextended entries are explicitly rejected.
late = core.late_entry_check({'instrument':'STOCK','cmp':104,'buy_above':100})
assert late['late'] is True and late['severe'] is True, late

# 7) Temporal confirmation/debounce: first READY observation is held at CONFIRMING.
v745_app._SETUP_CONFIRM.clear()
base = core.qualify_setup(clean_setup, good, regime, vix)
first = v745_app._apply_temporal_confirmation([base])[0]
second = v745_app._apply_temporal_confirmation([base])[0]
assert first['adaptive']['temporal_confirmation']['observed'] == 1
assert first['adaptive']['qualified'] is False
assert first['adaptive']['lifecycle'] == 'CONFIRMING'
assert second['adaptive']['temporal_confirmation']['observed'] == 2
# If the raw setup itself was READY, second snapshot becomes qualified.
if base['adaptive']['qualified']:
    assert second['adaptive']['qualified'] is True

# 8) Smart-alert production safety: test alerts are suppressed, duplicates are cooled down.
v745_app._SMART_ALERTS.clear(); v745_app._ALERT_SIG.clear()
assert v745_app._smart_emit('CRITICAL','TEST','SYSTEM','TEST ALERT','debug') is None
one = v745_app._smart_emit('WATCH','STATE_CHANGE','MARKET','REGIME CHANGED','RANGE → TRENDING',cooldown=60)
two = v745_app._smart_emit('WATCH','STATE_CHANGE','MARKET','REGIME CHANGED','RANGE → TRENDING',cooldown=60)
assert one is not None and two is None
assert all('TEST' not in str(x.get('title','')).upper() for x in v745_app._SMART_ALERTS)

# 9) Missing VIX stays explicit rather than fabricated.
missing_vix = core.vix_intelligence([], [])
assert missing_vix['available'] is False and missing_vix['level'] is None

# 10) Correlation guard identifies non-independent exposures.
rows=[]
for sym in ['BANKNIFTY','HDFCBANK']:
    rows.append({'symbol':sym,'adaptive':{'qualified':True}})
corr=core.correlation_guard(rows)
assert corr['status']=='CAUTION' and corr['warnings']

# 11) Legacy push is opt-in in V74.5 source.
legacy_source=(ROOT/'v744_app.py').read_text(errors='ignore')
assert 'POWERHOUSE_LEGACY_PUSH' in legacy_source
assert '!= "1"' in legacy_source

print('TEST_V74_5_FINAL PASS')
