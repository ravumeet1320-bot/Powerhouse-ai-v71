from v67_engine import build_chart_intelligence, smart_money_advanced

rows=[]
base=100.0
# build contraction with rising lows / flat-ish highs
for i in range(60):
    lo=98.0 + min(i,50)*0.025
    hi=103.0 - min(i,50)*0.006
    o=lo+(hi-lo)*0.42
    c=lo+(hi-lo)*(0.48 + (i%3)*0.03)
    rows.append([f'2026-09-10T{9+i//60:02d}:{15+i%60:02d}:00+05:30',o,hi,lo,c,1000+i*20,0])
snap={'spot':rows[-1][4],'vwap':100.7,'option_data':[{'s':100,'coi':1000,'poi':1500,'cchg':50,'pchg':180},{'s':105,'coi':1300,'poi':900,'cchg':80,'pchg':40}], 'active_underlying':'NIFTY'}
out=build_chart_intelligence(rows,'TEST',5,snap,{'footprint_score':58})
assert out['version']=='67.0'
assert out['fibonacci']['available']
assert 'forming_patterns' in out
assert out['smart_money']['identity']=='ANONYMOUS MARKET FOOTPRINT'
assert out['smart_money']['pressure_score']>=0
print('TEST_V67 PASS')
