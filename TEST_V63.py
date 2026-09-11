from v63_engine import strongest_sector_today, market_movers, build_v63

m={
 'spot':25000,'active_underlying':'NIFTY','last_tick_epoch':1,
 'sector_data':[
   {'symbol':'TATASTEEL','sector':'Metals','ltp':170,'previous_close':160,'volume':1000,'rvol':2.1},
   {'symbol':'HINDALCO','sector':'Metals','ltp':700,'previous_close':680,'volume':900,'rvol':1.6},
   {'symbol':'JSWSTEEL','sector':'Metals','ltp':1000,'previous_close':990,'volume':800,'rvol':1.3},
   {'symbol':'INFY','sector':'IT','ltp':1500,'previous_close':1495,'volume':700,'rvol':1.0},
   {'symbol':'TCS','sector':'IT','ltp':4000,'previous_close':4020,'volume':500,'rvol':0.9},
 ],
 'candles':[], 'option_chain':[]
}
s=strongest_sector_today(m)
assert s['status']=='READY'
assert s['strongest_sector']['sector']=='METALS'
assert s['strongest_sector']['top_gainer']['symbol']=='TATASTEEL'
assert market_movers(m)['top_gainers'][0]['symbol']=='TATASTEEL'
v=build_v63(m,{'readiness':{}})
assert v['version']=='63.0'
print('V63 TEST PASS — strongest sector + top gainer + movers + global market command center')
