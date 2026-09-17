from v743_precision import ultra_accuracy_gate, apply_precision_gate, VERSION

def good_underlying():
    scouts={k:{'status':'READY','score':v} for k,v in {
        'price':84,'volume':78,'oi':76,'sector':73,'order_flow':81,'pattern':72,'options':80}.items()}
    return {'symbol':'TEST','stage':'TRIGGER READY','quote_age_sec':1.2,'scout_pack':{'ready_count':7,'scouts':scouts},'late_entry':False}

def good_plan():
    return {'symbol':'TEST','status':'READY','action':'BUY CE','underlying_side':'CE','stage':'TRIGGER READY','call_quality':84,
            'entry_zone':{'low':100,'ideal':101,'high':102},'sl':96,'structural_sl':999,'targets':{'t1':108,'t2':112,'t3':118},
            'risk_reward':{'t1':1.4,'t2':2.2,'t3':3.4},'strike':100,'expiry':'2099-01-01','premium':101,
            'liquidity_score':85,'spread_pct':0.45,'blocked_by':[],'valid_until_epoch':9999999999,'valid_for_sec':180}

u=good_underlying(); p=good_plan(); sp={'winner':{'scores':{'premium_response':78}}}
g=ultra_accuracy_gate(u,p,sp,None)
assert g['decision']=='TAKE',g
assert g['meta_score']>=78,g

u2=good_underlying(); u2['scout_pack']['scouts']['oi']['score']=5; u2['scout_pack']['scouts']['sector']['score']=5
p2=good_plan(); p2['spread_pct']=3.4
g2=ultra_accuracy_gate(u2,p2,sp,None)
assert g2['decision']=='SKIP',g2

out=apply_precision_gate(u,p,sp,None)
assert out['version']==VERSION
assert out['meta_label']=='TAKE',out
assert out['action']=='BUY CE',out
print('TEST_V74_3_PRECISION PASS')
