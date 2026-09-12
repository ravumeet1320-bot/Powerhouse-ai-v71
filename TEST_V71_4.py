from v67_engine import big_money_entry_intelligence, build_chart_intelligence

cs=[]
# Quiet baseline / prior resistance near 101.
for i in range(24):
    o=99.8 + (i%4)*0.12
    c=o + (0.10 if i%2==0 else -0.04)
    cs.append({'ts':f'b{i}','open':o,'high':max(o,c)+0.35,'low':min(o,c)-0.28,'close':c,'volume':1000+(i%5)*60})
# Abnormal-volume breakout candle.
cs.append({'ts':'spike','open':100.4,'high':104.7,'low':100.2,'close':104.2,'volume':9800})
# Absorption / support hold with contracting volume.
for i,(o,c,h,l,v) in enumerate([
    (103.9,104.0,104.6,103.1,2500),(104.0,103.7,104.5,103.2,2100),(103.7,104.1,104.4,103.3,1800),
    (104.0,104.2,104.5,103.5,1700),(104.1,104.0,104.4,103.4,1600)
]):
    cs.append({'ts':f'hold{i}','open':o,'high':h,'low':l,'close':c,'volume':v})
# Balance-edge breakout.
cs.append({'ts':'confirm','open':104.2,'high':106.4,'low':104.0,'close':106.0,'volume':4200})
cs.append({'ts':'follow','open':106.0,'high':106.8,'low':105.4,'close':106.3,'volume':3000})

b=big_money_entry_intelligence(cs)
assert b['available'], b
assert b['side']=='BULL', b
assert 'CONFIRMED' in b['state'], b
assert b['rvol']>5, b
assert b['score']>=70, b
assert b['trigger'] is not None and b['invalidation'] is not None
pack=build_chart_intelligence(cs,'TEST',5,{}, {})
assert pack['big_money_entry']['available']
assert pack['smart_money']['state'] in ('AGGRESSIVE ACCUMULATION','ACCUMULATION BUILDING','STEALTH ACCUMULATION','CONFLICTED / ABSORPTION')
print('TEST_V71_4 PASS — abnormal-volume accumulation + hold + breakout detector active')
