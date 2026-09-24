from fastapi.responses import FileResponse
import v748_app as base

app = base.app
ROOT = base.ROOT
VERSION = "75.0"
RELEASE = "V75 DYNAMITE — OLD-GOOD LOCKED"

# ROOT HOTFIX: remove every inherited GET/HEAD homepage route.
# Legacy APIs/features remain untouched.
def _force_single_v75_root():
    kept = []
    for route in app.router.routes:
        path = getattr(route, "path", None)
        methods = set(getattr(route, "methods", set()) or set())
        if path == "/" and ("GET" in methods or "HEAD" in methods):
            continue
        kept.append(route)
    app.router.routes[:] = kept

_force_single_v75_root()

@app.get("/", include_in_schema=False)
def home():
    p = ROOT / "static" / "v75.html"
    if p.exists():
        return FileResponse(
            p,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
                "X-Powerhouse-Build": "V75-DYNAMITE-ROOT-HOTFIX",
            },
        )
    return base.v748_home()

def market():
    try:
        return base.base._rebuild_market()
    except Exception:
        return getattr(base.base, "_LAST_MARKET", {}) or {}

def rows():
    m = market()
    r = list(m.get("ranked") or m.get("rows") or [])
    if not r:
        r = list(m.get("fast_lane") or []) + list(m.get("pre_move") or [])
    return m, r

@app.get("/api/v75/cash-war-room")
def cash():
    m, r = rows()
    return {"version": VERSION, "rows": r[:300], "coverage": m.get("coverage", {}),
            "old_good_locked": True, "execution_enabled": False}

@app.get("/api/v75/volume-shockers")
def volume():
    _, r = rows()
    r = sorted(r, key=lambda x:
        float(x.get("rvol") or 0) * 30 +
        abs(float(x.get("change_pct") or 0)) * 8 +
        abs(float((x.get("price_velocity") or {}).get("30s_pct") or 0)) * 20,
        reverse=True)
    return {"version": VERSION, "rows": r[:100], "execution_enabled": False}

@app.get("/api/v75/silent-shockers")
def silent():
    _, r = rows()
    z = [x for x in r if abs(float(x.get("change_pct") or 0)) <= 2 and (
        float(x.get("rvol") or 0) >= 2 or
        abs(float((x.get("price_velocity") or {}).get("30s_pct") or 0)) >= .25)]
    return {"version": VERSION, "rows": z[:100]}

@app.get("/api/v75/alert-desk")
def alerts():
    a = list(getattr(base.base, "_ALERTS", []) or [])
    latest = {}
    for x in a:
        latest[(x.get("symbol"), x.get("kind"))] = x
    return {"version": VERSION,
            "rows": sorted(latest.values(), key=lambda x: float(x.get("epoch") or 0),
                           reverse=True)[:250],
            "duplicate_policy": "one evolving card per symbol/event"}

@app.get("/api/v75/system")
def system():
    return {
        "version": VERSION,
        "release": RELEASE,
        "root_hotfix": True,
        "inheritance": ["V74.6", "V74.7", "V74.8", "V75 additive"],
        "locked": ["whole NSE cash", "pre-move", "auto trender", "liquidity/depth",
                   "circuits", "smart-flow", "charts", "FII/DII", "index", "expiry hero"],
        "added": ["cash war room", "volume shockers", "silent shockers",
                  "dedicated alert desk"],
        "execution_enabled": False,
    }
