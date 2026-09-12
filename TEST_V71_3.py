from v67_engine import pattern_lifecycle

# Synthetic double-top geometry with neckline near 100.
cs=[]
vals=[100,103,106,110,107,103,101,104,108,110.4,107,103,101.5,100.8,99.7,99.2,98.8,98.4]
for i,c in enumerate(vals):
    cs.append({'ts':str(i),'open':c-0.3,'high':c+0.7,'low':c-0.8,'close':c,'volume':1000+i*10})
p=pattern_lifecycle(cs)
assert isinstance(p,list)
assert any(x.get('pattern') in {'DOUBLE TOP','RESISTANCE FATIGUE / BREAKOUT BUILD','VOLATILITY COMPRESSION'} for x in p), p
print('TEST_V71_3 PASS — adaptive backend chart-pattern lifecycle active')
