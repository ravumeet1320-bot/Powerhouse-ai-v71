from pathlib import Path
import v74_app
import v746_engine as core

ROOT=Path(__file__).parent
UI=(ROOT/'static'/'v746.html').read_text(errors='ignore')
LEGACY5=(ROOT/'static'/'v745.html').read_text(errors='ignore')
LEGACY4=(ROOT/'static'/'v744.html').read_text(errors='ignore')
SW=(ROOT/'static'/'sw.js').read_text(errors='ignore')
app=v74_app.app
assert app.version=='74.6', app.version
paths={getattr(r,'path',None) for r in app.router.routes}
for p in ['/', '/v743','/v744','/v744-light','/v745','/api/v74.5/command-center','/api/v74.6/command-center','/api/v74.6/profiles','/api/v74.6/system']:
    assert p in paths, p
for feature in ['COMMAND','INDEX CALLS','MARKET','SMART MONEY','FII/DII','HEATWAVE','SECTORS','AUTO TRENDER','CIRCUITS','ULTRA CALLS','CHART PRO','SUPPLY/DEMAND','S/R BREAK','ULTRA DERIVATIVES','OPTION CHAIN','OI WALLS','DEPTH/DOM','EXPIRY HERO','ALERTS','WATCHLIST','ACCURACY','REPLAY','AUDIT','SYSTEM','MOVE RADAR','EXECUTION','DERIV PULSE','BEHAVIOUR LAB','V74.4 SYSTEM','ADAPTIVE CORE','VIX/RISK','MARKET MEMORY','V74.6 SYSTEM']:
    assert f'data-feature="{feature}"' in UI, feature
assert 'AGGRESSIVE' in UI and 'TURBO' in UI and 'setTradeProfile' in UI
assert '/api/v74.6/command-center' in UI
assert 'powerhouse-v74-6-aggressive-dynamic-master-final-v1' in SW
assert 'V74.5' in LEGACY5 and 'V74.4' in LEGACY4
assert core.PROFILES['AGGRESSIVE']['ready_signal'] < core.PROFILES['BALANCED']['ready_signal']
assert core.PROFILES['TURBO']['poll_sec'] < core.PROFILES['AGGRESSIVE']['poll_sec']
print('TEST_V74_6_REGRESSION: PASS')
