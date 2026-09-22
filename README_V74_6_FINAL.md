# POWERHOUSE AI V74.6 — Aggressive Dynamic Master Final

V74.6 is an additive aggressive/dynamic layer over the verified V74.5 stack. Existing V74.3/V74.4/V74.5 routes and features are preserved.

## Default behavior
- Default profile: **AGGRESSIVE**
- Optional profiles: BALANCED / AGGRESSIVE / TURBO
- Faster dynamic command-center refresh
- Dynamic thresholds based on regime, VIX, data quality and execution quality
- EARLY READY state for near-qualified setups
- Urgency score and aggression score
- One-snapshot confirmation allowed only for strong AGGRESSIVE/TURBO setups
- Wider but bounded late-entry tolerance
- Extreme VIX, corrupt/stale data, severe overextension and very poor execution remain hard blocks
- Broker order placement remains disabled

## Main endpoints
- `/` — V74.6 UI
- `/v745` — preserved V74.5 UI
- `/api/v74.6/command-center?profile=AGGRESSIVE`
- `/api/v74.6/setup/{symbol}?profile=AGGRESSIVE`
- `/api/v74.6/profiles`
- `/api/v74.6/alerts`
- `/api/v74.6/system`

Aggressive means earlier/more frequent qualification, not guaranteed accuracy or profit.
