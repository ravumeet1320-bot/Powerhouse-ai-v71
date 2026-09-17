# POWERHOUSE AI V74.3 — Pro Ultra Accuracy OS

V74.3 is an additive accuracy-first upgrade over V74.2. Discovery stays broad; only the Ultra Accuracy meta-label can promote a candidate to an actionable read-only call.

## New runtime

Start with:

```bash
uvicorn v743_app:app --host 0.0.0.0 --port $PORT
```

## Core additions

- TAKE / SKIP / INSUFFICIENT_DATA meta-label gate
- scout disagreement and agreement scoring
- stricter freshness, liquidity, spread, R:R, premium-response and late-entry checks
- immutable decision snapshot + config SHA-256 hashes
- PostgreSQL production persistence when `DATABASE_URL` is set; SQLite fallback
- fail-closed actionable calls if precision persistence fails
- call retraction events when evidence deteriorates
- empirical calibration only after minimum resolved sample
- subsystem heartbeats + Safe Mode
- true Web Push support when VAPID keys are configured
- dedicated V74.3 UI and precision APIs

## Important truth policy

`meta_score` and `call_quality` are evidence-quality scores, not guaranteed profit probabilities. The software does not place broker orders. Accuracy is reported only from resolved live/shadow calls and is withheld as `INSUFFICIENT_DATA` when the sample is too small.

## Production persistence

For durable call/snapshot memory, configure a managed PostgreSQL `DATABASE_URL`. If absent, V74.3 uses `.runtime/powerhouse_v743_precision.sqlite3`. On ephemeral hosting that fallback can reset across deploys/restarts unless backed by a persistent disk.

## Closed-app push

Set `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, and `VAPID_SUBJECT`. The UI can then register `/static/sw.js` for closed-app push notifications. Without VAPID keys, push remains visibly `NOT CONFIGURED` rather than pretending it works.
