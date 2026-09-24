# POWERHOUSE AI V74.7 — Whole-Market Move Intelligence Master

V74.7 is an additive layer over the existing V74.6/V74.5/V74.4/V74.3 stack. No broker order placement is enabled.

## Core behaviour

- Whole NSE cash-market discovery using the official Upstox NSE instrument master plus batched Full Market Quote V3 snapshots.
- Upside and downside are symmetric: Open≈Low/Open≈High, recovery/fall, acceleration, circuit pressure, depth imbalance and liquidity/turnover anomalies.
- Liquidity Fast Lane: turnover velocity, volume/RVOL where baseline is available, spread, total buy/sell quantity, top depth and hot-candidate historical baseline hydration.
- Discover-first architecture: a large observed anomaly may be surfaced even when execution quality is poor; trade quality is shown separately.
- Pre-move lifecycle: DISCOVERY → PRE-MOVE → BUILDING → ACCELERATING → TRIGGER NEAR → ENTRY READY → MOVE ACTIVE → PULLBACK/RETEST → SECOND LEG → EXHAUSTION.
- Auto Trender NXT for Index + Stocks with 3m/5m/15m views, EARLY BUY/SELL, BUY/SELL, strength, acceleration and read-only entry/SL/target planning.
- Circuit Hunter covers both upper and lower circuit pressure and uses early pressure states rather than only already-near-circuit rows.
- Blind-Spot Sentinel compares meaningful observed movers with the alerted set and forces unalerted large movers into audit/hot-lane visibility.
- One-by-one FIFO alerts: the frontend queues every fresh backend alert and shows one toast at a time; same-stock lifecycle states are deduplicated/upgraded.
- Chart redesign: candle-only autoscale, right price axis, time axis, readable candles, pattern trigger/invalidation overlays and smart-money-like footprint zone/trigger/invalidation overlays.
- Existing advanced pattern and big-money footprint engines are surfaced from the preserved V67/V72 chart intelligence stack.
- FII/DII page attempts official NSE provisional cash data and NSE participant-OI archives, then falls back to the existing verified local institutional store with an explicit status/reason.
- WHY MOVING? adapter checks recent NSE corporate announcements for the selected symbol; if no verified catalyst exists it returns UNKNOWN/FLOW rather than inventing a reason.
- Per-module health replaces a misleading blanket “100% healthy” state.

## Important truth/safety rules

V74.7 is decision support, not guaranteed forecasting. “Smart money” labels describe anonymous observable flow footprints and never claim a named FII/DII/PRO participant without an explicit verified source. Generic entry/SL/target bands are planning aids; selected-symbol candle structure should supersede them. Missing data stays missing instead of becoming zero.

## Files to upload

1. `v747_engine.py`
2. `v747_app.py`
3. `static/v747.html`
4. Replace root `v74_app.py` with the supplied file **last**.

Do not remove the existing V74.6 files. `/v746` is preserved as a fallback UI.

## New endpoints

- `/api/v74.7/command-center?profile=AGGRESSIVE`
- `/api/v74.7/market-scout`
- `/api/v74.7/auto-trender?scope=ALL&timeframe=5`
- `/api/v74.7/setup/{symbol}`
- `/api/v74.7/why/{symbol}`
- `/api/v74.7/fii-dii`
- `/api/v74.7/alerts`
- `/api/v74.7/system`
- `/v746` preserved legacy UI

## Runtime tuning

- `V747_CASH_BATCH_SIZE` default 450 (bounded 100–450)
- `V747_CASH_BATCH_PAUSE_SEC` default 1.6 seconds (bounded 0.8–5.0)
- `V747_BASELINE_INTERVAL_SEC` default 8 seconds (bounded 5–30)

These defaults intentionally use a rotating low-cost census plus hot-candidate baseline hydration rather than expensive historical requests for the entire exchange every cycle.
