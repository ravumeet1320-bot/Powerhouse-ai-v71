# POWERHOUSE AI V73 LTS — Institutional Intelligence OS

Final locked cumulative build on top of V72.2. It is a **read-only market-intelligence system**; it does not place broker orders.

## What changed

V73 adds a unified LTS orchestration layer, final 8-group navigation, Opportunity Coverage Sentinel, candidate memory/resurrection, pre-circuit detection from numeric live circuit limits, Volume/Depth intelligence, Hero entry/SL/target plans with conditional target expansion, alert priorities, data-quality gating, and a dual-theme pro UI.

The V71/V72.2 engines are preserved rather than replaced. Missing/stale data is never invented or labelled live.

## Core V73 endpoints

- `/api/v73/status`
- `/api/v73/tabs`
- `/api/v73/coverage`
- `/api/v73/circuit-hunter`
- `/api/v73/alerts`
- `/api/v73/hero/{symbol}`
- `/api/v72/status` remains for compatibility.

See `DEPLOY_V73_LTS.txt` for exact live deployment steps and `V73_LTS_LOCKED_ARCHITECTURE.txt` for the frozen product architecture.
