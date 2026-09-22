from __future__ import annotations
import v746_engine as e

DQ={"score":96,"gate":"ALLOW"}
REG={"regime":"TRENDING UP","bias":"BULLISH","confidence":86}
VIX={"available":True,"risk_score":42,"regime":"NORMAL"}
SET={"symbol":"TEST","instrument":"OPTION","action":"BUY CE","option_action":"BUY CE","status":"TRIGGER NEAR","stage":"TRIGGER NEAR","cmp":101,"buy_above":100,"quality":76,"rr":1.8,"why":["trend","oi","volume"],"blocked_by":[],"liquidity":{"score":78,"spread_pct":0.35}}

def main():
    a=e.qualify_dynamic(SET,DQ,REG,VIX,"AGGRESSIVE")["adaptive"]
    assert a["profile"]=="AGGRESSIVE"
    assert a["signal_quality"]["score"]>=60
    assert a["execution_quality"]["score"]>=50
    assert a["lifecycle"] in {"READY","EARLY READY","ARMED"}
    assert 0<=a["urgency_score"]<=100
    assert 0<=a["aggression_score"]<=100
    assert e.temporal_required({"adaptive":a}) in {1,2}
    hard=e.qualify_dynamic(SET,{"score":15,"gate":"BLOCK"},REG,VIX,"TURBO")["adaptive"]
    assert hard["lifecycle"]=="INVALIDATED"
    assert hard["final_action"]=="WAIT"
    extreme=e.qualify_dynamic(SET,DQ,REG,{"available":True,"risk_score":99,"regime":"EXTREME"},"AGGRESSIVE")["adaptive"]
    assert extreme["lifecycle"]=="INVALIDATED"
    assert "VIX EXTREME RISK" in extreme["no_trade_reasons"]
    print('TEST_V74_6_FINAL: PASS')

if __name__=='__main__': main()
