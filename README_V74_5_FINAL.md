# POWERHOUSE AI V74.5 — Adaptive Intelligence Master Final

V74.5 is the accuracy-first additive layer over the locked V74.3/V74.4 POWERHOUSE stack. It does not remove the previous scanners, option-chain intelligence, index calls, chart intelligence, replay/audit, Move Radar, execution reality, derivative pulse or behaviour modules.

## Production entrypoint

`uvicorn v74_app:app --host 0.0.0.0 --port $PORT`

`v74_app.py` now loads `v745_app.py`, which layers over `v744_app.py` and the preserved V74.3/V74.4 stack.

## Main surfaces

- `/` — V74.5 Adaptive Intelligence UI
- `/v744` — preserved V74.4 master UI
- `/v743` — preserved V74.3 locked UI
- `/v744-light` — preserved V74.4 light draft

Key V74.5 APIs:

- `/api/v74.5/command-center`
- `/api/v74.5/vix-risk`
- `/api/v74.5/setup/{symbol}`
- `/api/v74.5/alerts`
- `/api/v74.5/accuracy`
- `/api/v74.5/memory`
- `/api/v74.5/feature-manifest`
- `/api/v74.5/system`

## Accuracy-first decision pipeline

`DATA QUALITY → MARKET REGIME / VIX → ADAPTIVE EVIDENCE → CONTRADICTION → UNCERTAINTY → EXECUTION QUALITY → TEMPORAL CONFIRMATION → LATE/OVEREXTENSION CHECK → FINAL THESIS / NO TRADE`

V74.5 deliberately prefers abstention to a low-quality signal. A high internal confidence score is not a guarantee of direction or profit.

## Alerts

The V74.5 UI defaults to **IMPORTANT_ONLY**. On-screen toast notifications are limited to high-severity state changes, and only one toast is visible at a time. INFO/test events are not shown in the normal stream. Legacy V74.4 server push is opt-in with `POWERHOUSE_LEGACY_PUSH=1`.

## Data truth

Missing data is never filled with invented market values. India VIX and cross-market context are used only when provider rows are actually available. VIX is a risk/context input, never a standalone BUY/SELL trigger.

## Verification

The final package includes `TEST_V74_5_FINAL.py` plus all historical regression tests. See `VERIFICATION_REPORT_V74_5_FINAL.txt` for the build result and limitations.

## Deployment status

This package has **not** been deployed. Live Upstox and Render validation should be performed only after explicit deployment approval.
