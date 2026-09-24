from __future__ import annotations
import time
import v747_engine as e


def hist(base=100.0, up=True):
    now=time.time(); out=[]
    for i in range(7):
        px=base*(1+(0.0009*i if up else -0.0009*i))
        out.append({'t':now-(6-i)*15,'ltp':px,'volume':100000+i*45000})
    return out


def main():
    up={'symbol':'UPTEST','ltp':101.2,'cp':99.5,'change_pct':1.71,'volume':850000,'day_open':99.8,'day_high':101.3,'day_low':99.8,
        'total_buy_qty':900000,'total_sell_qty':250000,'bid':101.18,'ask':101.22,'upper_circuit_limit':109.45,'lower_circuit_limit':89.55,'rvol':2.7}
    dn={'symbol':'DNTEST','ltp':98.1,'cp':100.0,'change_pct':-1.9,'volume':910000,'day_open':100.2,'day_high':100.2,'day_low':98.0,
        'total_buy_qty':210000,'total_sell_qty':880000,'bid':98.08,'ask':98.12,'upper_circuit_limit':110,'lower_circuit_limit':90,'rvol':3.1}
    u=e.autotrender(e.classify_row(up,hist(100,True)),5)
    d=e.autotrender(e.classify_row(dn,hist(100,False)),5)
    assert u['direction']=='UP',u
    assert d['direction']=='DOWN',d
    assert u['signal'] in {'EARLY BUY','BUY','WATCH'}
    assert d['signal'] in {'EARLY SELL','SELL','WATCH'}
    assert u['depth']['pressure']>50 and d['depth']['pressure']<50
    market=e.rank_market([up,dn],{'UPTEST':hist(100,True),'DNTEST':hist(100,False)})
    assert market['counts']['observed']==2
    report=e.blind_spot_report(market,[])
    assert report['silent_misses_allowed'] is False
    print('V74.7 engine tests PASS')

if __name__=='__main__': main()
