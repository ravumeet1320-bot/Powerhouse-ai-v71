from pathlib import Path
import v743_app as app

ROOT=Path(__file__).parent
UI=(ROOT/'static'/'v743.html').read_text(errors='ignore')

mf=app._feature_manifest_payload()
assert mf['ui_loaded']==24, mf
assert mf['ui_required']==24, mf
assert mf['regression_guard']=='PASS', mf
assert all(mf['truth_checks'].values()), mf['truth_checks']

paths={getattr(r,'path',None) for r in app.app.router.routes}
assert '/api/v74.3/index-command' in paths
assert '/api/v74.3/intelligence/{symbol}' in paths

# Production UI must calculate indicators from candles, not draw synthetic sine waves.
assert 'computeRSI' in UI and 'computeMACD' in UI
assert 'Math.sin(i/7)' not in UI and 'Math.sin(i/6)' not in UI
assert '0,22 20,20 35,23' not in UI
assert 'NO_SYNTHETIC_MARKET_VALUES' in UI
assert 'CE ΔOI' in UI and 'PE ΔOI' in UI
assert 'LEVEL_WAR_ROOM' in UI

candles=[]
px=24000.0
for i in range(80):
    o=px; c=px+(8 if i%3 else -4); h=max(o,c)+10; l=min(o,c)-9
    candles.append([f't{i}',o,h,l,c,100000+i*1000]); px=c
levels=app._derive_level_map(candles,{},px)
assert levels['support'] is not None and levels['resistance'] is not None
assert levels['demand'] and levels['supply']

chain={'expiry':'2099-01-01','spot':px,'source':'test','chain':[
    {'strike':round(px/50)*50-50,'ce':{'oi':100,'prev_oi':120,'volume':1000},'pe':{'oi':300,'prev_oi':250,'volume':2000}},
    {'strike':round(px/50)*50,'ce':{'oi':500,'prev_oi':550,'volume':3000,'iv':15,'delta':.5,'gamma':.001},'pe':{'oi':450,'prev_oi':400,'volume':3100,'iv':16,'delta':-.5,'gamma':.001}},
    {'strike':round(px/50)*50+50,'ce':{'oi':700,'prev_oi':650,'volume':1800},'pe':{'oi':120,'prev_oi':150,'volume':800}},
]}
ca=app._chain_analytics(chain,px)
assert ca['call_wall']['strike'] is not None and ca['put_wall']['strike'] is not None
assert ca['atm']['ce']['oi_change'] is not None and ca['atm']['pe']['oi_change'] is not None
print('TEST_V74_3_FINAL_LOCKED PASS')
