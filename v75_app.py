from fastapi.responses import FileResponse
import v748_app as base
app=base.app
ROOT=base.ROOT
VERSION="75.0"
RELEASE="V75 DYNAMITE — OLD-GOOD LOCKED"
base.base._remove_get("/")
@app.get("/")
def home():
    p=ROOT/"static"/"v75.html"
    return FileResponse(p,headers={"Cache-Control":"no-store","X-Powerhouse-Build":"V75-DYNAMITE"}) if p.exists() else base.v748_home()
def market():
    try:return base.base._rebuild_market()
    except:return getattr(base.base,"_LAST_MARKET",{}) or {}
def rows():
    m=market(); r=list(m.get("ranked") or m.get("rows") or [])
    if not r:r=list(m.get("fast_lane") or [])+list(m.get("pre_move") or [])
    return m,r
@app.get("/api/v75/cash-war-room")
def cash():
    m,r=rows(); return {"version":VERSION,"rows":r[:300],"coverage":m.get("coverage",{}),"old_good_locked":True,"execution_enabled":False}
@app.get("/api/v75/volume-shockers")
def volume():
    _,r=rows()
    r=sorted(r,key=lambda x:float(x.get("rvol") or 0)*30+abs(float(x.get("change_pct") or 0))*8+abs(float((x.get("price_velocity") or {}).get("30s_pct") or 0))*20,reverse=True)
    return {"version":VERSION,"rows":r[:100],"execution_enabled":False}
@app.get("/api/v75/silent-shockers")
def silent():
    _,r=rows(); z=[x for x in r if abs(float(x.get("change_pct") or 0))<=2 and (float(x.get("rvol") or 0)>=2 or abs(float((x.get("price_velocity") or {}).get("30s_pct") or 0))>=.25)]
    return {"version":VERSION,"rows":z[:100]}
@app.get("/api/v75/alert-desk")
def alerts():
    a=list(getattr(base.base,"_ALERTS",[]) or []); latest={}
    for x in a:latest[(x.get("symbol"),x.get("kind"))]=x
    return {"version":VERSION,"rows":sorted(latest.values(),key=lambda x:float(x.get("epoch") or 0),reverse=True)[:250],"duplicate_policy":"one evolving card per symbol/event"}
@app.get("/api/v75/system")
def system():
    return {"version":VERSION,"release":RELEASE,"inheritance":["V74.6","V74.7","V74.8","V75 additive"],"locked":["whole NSE cash","pre-move","auto trender","liquidity/depth","circuits","smart-flow","charts","FII/DII","index","expiry hero"],"added":["cash war room","volume shockers","silent shockers","dedicated alert desk"],"execution_enabled":False}
