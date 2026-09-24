# POWERHOUSE AI V74.8 — FINAL MERGE

Additive upgrade over V74.7. Existing V74.7 and legacy V74.6 stack are preserved.

## Added / restored
- Dedicated top alert dock; fresh alerts only, one-by-one.
- Index workspace for NIFTY, BANKNIFTY, MIDCPNIFTY and SENSEX; index clicks no longer disappear into an unrelated flow.
- Dedicated HEATMAP surface. Missing heatmap data is shown as missing; never fabricated.
- Dedicated EXPIRY HERO / HERO-ZERO surface with WATCH → ARMED → TRIGGERED → INVALIDATED lifecycle.
- Hero engine reuses preserved index/adaptive call authority; expiry alone never forces a trade.
- V74.7 whole-market, pre-move, liquidity, circuits, chart/patterns, smart-money footprint, FII/DII, alerts and blind-spots remain.
- Tabs may be numerous but detailed functions are not intentionally duplicated.

## Upload order
1. v748_app.py
2. static/v748.html
3. Keep existing V74.7/V74.6 files in place.
4. Replace root v74_app.py LAST.

## New endpoints
- /api/v74.8/index-workspace
- /api/v74.8/expiry-hero
- /api/v74.8/system

Read-only decision support. Broker execution remains disabled. No profitable move or Hero trade can be guaranteed.
