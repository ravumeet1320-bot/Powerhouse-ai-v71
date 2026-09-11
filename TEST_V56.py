from v56_engine import build_v56, apply_custom_scan

market={
 'spot':23500,'official_pcr':0.92,'official_max_pain':23400,
 'sector_heatmap':[
   {'symbol':'ALPHA','sector':'BANK','ltp':100,'change_pct':1.8,'live':True,'volume':500000,'rvol':2.2,'high_52w':105,'low_52w':70,'prev_day_high':100.15,'bid_qty':6000,'ask_qty':3000,'futures_oi_change_pct':7.0},
   {'symbol':'BETA','sector':'IT','ltp':200,'change_pct':-1.2,'live':True,'volume':200000,'rvol':1.1,'high_52w':250,'low_52w':150,'prev_day_high':205,'bid_qty':2000,'ask_qty':6000,'futures_oi_change_pct':5.0}
 ],
 'option_data':[
   {'strike':23400,'coi':100,'poi':200,'cvol':50,'pvol':90,'cltp':140,'pltp':60},
   {'strike':23500,'coi':250,'poi':300,'cvol':100,'pvol':120,'cltp':90,'pltp':85},
   {'strike':23600,'coi':500,'poi':120,'cvol':150,'pvol':70,'cltp':50,'pltp':140}
 ]
}
v55={'breakout_hunter':{'rows':[{'symbol':'ALPHA','stage':'TRIGGER READY'},{'symbol':'BETA','stage':'DISCOVERED'}]}}
v=build_v56(market,v55)
assert v['version']=='56.0' and v['read_only'] and not v['execution_enabled']
assert v['trade_finder']['breakout_now']>=1
assert v['advanced_screener']['presets']['high_rvol'][0]['symbol']=='ALPHA'
assert v['oi_spurts'][0]['state']=='LONG BUILDUP'
assert any(x['state']=='SHORT BUILDUP' for x in v['oi_spurts'])
assert v['option_chain_intelligence']['summary']['max_call_oi']['strike']==23600
rows=v['advanced_screener']['universe']
assert apply_custom_scan(rows,'rvol','gte',2)[0]['symbol']=='ALPHA'
print('V56 TESTS PASS — advanced screener, breakout presets, OI spurts, option-chain intelligence, custom filters')
