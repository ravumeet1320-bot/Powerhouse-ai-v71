from fastapi import FastAPI, Request, Query
from fastapi.responses import FileResponse, JSONResponse
import v748_app as legacy

# Isolated V75 ASGI shell: do NOT reuse legacy.app as the root application.
# Legacy engine remains mounted under /legacy and its functions/data stay available.
app = FastAPI(title="POWERHOUSE AI V75 DYNAMITE", version="75.1")
ROOT = legacy.ROOT
VERSION = "75.1"
RELEASE = "V75 DYNAMITE ISOLATED SHELL"

@app.get("/", include_in_schema=False)
def root():
    return FileResponse(ROOT/"static"/"v75_isolated.html", headers={
        "Cache-Control":"no-store, no-cache, must-revalidate, max-age=0",
        "Pragma":"no-cache","Expires":"0",
        "X-Powerhouse-Build":"V75.1-ISOLATED"
    })

@app.get("/v75", include_in_schema=False)
def v75():
    return root()

@app.get("/api/v75/health")
def health():
    return {"ok":True,"version":VERSION,"release":RELEASE,"isolated_shell":True,
            "legacy_mounted":True,"execution_enabled":False}

def _market():
    try:
        return legacy.base._rebuild_market()
    except Exception:
        return getattr(legacy.base,"_LAST_MARKET",{}) or {}

def _rows():
    m=_market()
    r=list(m.get("ranked") or m.get("rows") or [])
    if not r:
        r=list(m.get("fast_lane") or [])+list(m.get("pre_move") or [])
    return m,r

@app.get("/api/v75/cash-war-room")
def cash():
    m,r=_rows()
    return {"version":VERSION,"rows":r[:300],"coverage":m.get("coverage",{}),
            "execution_enabled":False}

@app.get("/api/v75/volume-shockers")
def volume():
    _,r=_rows()
    r=sorted(r,key=lambda x: float(x.get("rvol") or 0)*30+
             abs(float(x.get("change_pct") or 0))*8+
             abs(float((x.get("price_velocity") or {}).get("30s_pct") or 0))*20,
             reverse=True)
    return {"version":VERSION,"rows":r[:120],"execution_enabled":False}

@app.get("/api/v75/silent-shockers")
def silent():
    _,r=_rows()
    z=[x for x in r if abs(float(x.get("change_pct") or 0))<=2 and
       (float(x.get("rvol") or 0)>=2 or
        abs(float((x.get("price_velocity") or {}).get("30s_pct") or 0))>=.25)]
    return {"version":VERSION,"rows":z[:120]}

@app.get("/api/v75/alerts")
def alerts():
    a=list(getattr(legacy.base,"_ALERTS",[]) or [])
    latest={}
    for x in a:
        latest[(x.get("symbol"),x.get("kind"))]=x
    return {"version":VERSION,"rows":sorted(latest.values(),
            key=lambda x:float(x.get("epoch") or 0),reverse=True)[:250]}

@app.get("/api/v75/index")
def index(request:Request, profile:str=Query("AGGRESSIVE")):
    return legacy.index_workspace(request,profile)

@app.get("/api/v75/expiry-hero")
def hero(request:Request, profile:str=Query("AGGRESSIVE")):
    return legacy.expiry_hero(request,profile)

@app.get("/api/v75/system")
def system():
    return {"version":VERSION,"release":RELEASE,"isolated_shell":True,
            "surfaces":["COMMAND","INDEX","AUTO TRENDER","PRE-MOVE","HEATMAP",
            "EXPIRY HERO","CASH STOCKS","VOLUME SHOCKERS","SILENT SHOCKERS",
            "LIQUIDITY","CIRCUITS","CHART","SMART MONEY","FII/DII","ALERTS","SYSTEM"],
            "legacy_path":"/legacy","execution_enabled":False}

# Preserve the entire old application without allowing its '/' route to own V75 '/'.
app.mount("/legacy", legacy.app)
