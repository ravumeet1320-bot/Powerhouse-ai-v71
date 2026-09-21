POWERHOUSE AI V74.4 - MASTER REBUILD

UPLOAD / REPLACE THESE FILES:
1. v74_app.py -> replace existing bridge
2. v744_app.py -> new
3. v744_engine.py -> new
4. static/v744.html -> new
5. static/sw.js -> replace existing service worker

Render start command stays:
uvicorn v74_app:app --host 0.0.0.0 --port $PORT

Build checks completed locally: Python syntax PASS and pure-engine smoke tests PASS.
Deployment/integration against live Upstox + Render still needs to be verified after upload.

Core build: light premium UI, large fonts, index command center, active option/stock setups, move-before-move radar, sudden volume/liquidity/OI changes, CE/PE derivative pulse states, PCR, vertical pressure bars, strike intelligence, chart behaviour, VWAP/S-R/PDH-PDL, alerts, local notifications, web push integration, execution reality, and preservation of existing V74.3 APIs.

No synthetic market values. No broker order placement. Derived scores/patterns are decision support, not guarantees.
