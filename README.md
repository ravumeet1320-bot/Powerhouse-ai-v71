# POWERHOUSE AI V71 — Intelligence Chart + Universal Opportunity Radar OS

V71 is a cumulative read-only upgrade over V70 focused on observation coverage and early discovery. It scores every discovered F&O underlying before UI ranking, uses a lightweight LTPC WebSocket census with richer feed promotion, adds stock-option Zero-to-Hero deep scanning, persistent discovery/missed-move audit, and upgrades Chart into an Intelligence Chart with structure, VWAP, volume profile, confluence and conditional scenarios.

## V71 core
- Full discovered F&O underlying census before ranking; no internal top-30/40/50/80 discovery gate.
- 15s/30s/60s/180s velocity + acceleration + RVOL + futures OI + liquidity/level proximity.
- WATCH → BUILDING → EARLY MOVER → TRIGGER READY → HERO READY lifecycle.
- Stock option Hero radar with no premium ceiling and hot + round-robin deep scan.
- Intelligence Chart API/UI: HH/HL, LH/LL, BOS/CHOCH, ATR, session VWAP, opening range, gap vs previous close, POC/VAH/VAL, level confluence, scenario boundaries.
- Persistent discovery snapshots/events and retrospective missed-move recall audit.
- Explicit expected/observed/fresh quote coverage guard; no false 100% win claim.
- Read-only analytics; no order execution.

See `CHANGELOG_v71.txt` and `TEST_V71.py`.

---

# POWERHOUSE AI V69 — Market Depth + Bulk/Block Smart Money OS

# POWERHOUSE AI V56 — Advanced Screener & OI Intelligence

V56 adds an actual read-only advanced screening layer to the existing V55/V54 stack. It includes breakout/volume/52W/depth presets, a safe custom screener API, futures OI-spurt classification when verified OI change is present, option-chain OI/volume intelligence, and live scanner-health diagnostics. Missing provider fields remain N/A and no broker execution is enabled.

# Powerhouse AI V54 — Visual Intelligence Terminal

V54 is a cumulative read-only upgrade over V53. It adds a dedicated live visual intelligence layer: stock/sector heatmaps, index option strike heatmaps, on-demand stock option heatmaps, animated evidence/pressure bars, decision-flow visualization, and displayed market-depth views when the connected Upstox feed supplies depth.

**Safety / truth rules:** no broker execution, no automatic orders, no P&L or paper trading. Heatmap intensity and setup/activity scores are descriptive evidence quality, not probability of profit. Anonymous order-book or option-chain activity is not labelled as FII/DII/institutional identity without a legitimate categorized source. Missing RVOL, 52-week, news or depth fields remain N/A.

## V54 highlights
- Market + sector stock heatmap with switchable % move, volume/RVOL, depth, setup-quality and 52W views.
- Index options CE ↔ strike ↔ PE heatmap with OI, ΔOI, volume, IV, activity, depth and spread modes.
- On-demand F&O stock option heatmap with expiry selection, avoiding wasteful continuous full-market option-chain polling.
- Up to 20 displayed depth levels are captured from Upstox full WebSocket market-level data when supplied.
- Animated market breadth, CE/PE volume/OI, setup-quality bars, plus Decision Firewall flow visualization.
- Reduced-motion support and meaningful-state animation policy.

---

# Powerhouse AI v22

Advanced Pattern Intelligence + AutoTrender V2. Read-only analytics for NIFTY / BANKNIFTY / SENSEX using Upstox market data.

## V22 highlights
- Advanced chart formations with completion, breakout and invalidation context.
- Expanded candlestick pattern recognition.
- AutoTrender V2 mild/strong bands, explainable bias, cross-index lead/lag and PCR velocity.
- Retains Flow Intelligence, OI flow, sector breadth, premium response, wall migration, score history, X-Ray, Pitch Report and option analytics.

No order placement, no execution, no P&L and no paper-trading ledger.

# Powerhouse AI v13 — Ultimate Market Intelligence

# NIFTY Powerhouse AI Index Brain v5 — Android + iPhone

Mobile-first, read-only NIFTY options signal intelligence using Upstox market data, now with a dedicated **weightage-aware Index Brain** for NIFTY 50 and BANK NIFTY.

## Core output

The app generates analytics only:

- **BUY CE / BUY PE / WAIT**
- exact ranked option strike when a clean directional setup qualifies
- AI confidence / confluence score
- signal lifecycle: NEW, BUILDING, CONFIRMED, WEAKENING, REVERSAL, FILTERED
- signal grade: A+ / A / B+ / B / C / FILTERED
- top same-side backup strikes
- reasons, rejection reasons and what changed since the previous refresh
- weighted heavyweight confirmation score
- NIFTY / BANK NIFTY divergence warning

There is **no broker order workflow, no account P&L, no paper trading and no automated trade execution**.

## NEW — AI Index Brain v5

The app now analyses the stocks that can matter most to an index instead of treating all constituents equally.

### NIFTY heavyweight intelligence

Tracked high-impact basket includes:

- HDFC Bank
- ICICI Bank
- Reliance
- Bharti Airtel
- L&T
- Infosys
- SBI
- Axis Bank
- Kotak Bank
- ITC

For every tracked stock the mobile app shows:

- configured index weight
- live change %
- BULL / BEAR / NEUTRAL state
- first-order weighted contribution proxy
- approximate contribution points to the index
- momentum score
- leader / drag ranking

### BANK NIFTY heavyweight intelligence

Tracked high-impact basket includes:

- HDFC Bank
- ICICI Bank
- SBI
- Kotak Bank
- Axis Bank
- Federal Bank
- IndusInd Bank
- AU Small Finance Bank
- IDFC First Bank
- Bank of Baroda

The Bank Nifty Brain is independent from the NIFTY Brain, so the app can detect when banks are strongly confirming or contradicting the broader NIFTY move.

### Index Brain outputs

Each index gets:

- weighted heavyweight move
- tracked-weight coverage
- live feed coverage
- bull-weight vs bear-weight split
- heavyweight agreement score
- confirmation score /100
- fragility risk /100
- divergence risk /100
- leader and drag stocks
- sector pulse
- approximate contribution points
- top-3 heavyweight consensus

The **Divergence Shield** flags cases such as NIFTY moving higher while high-weight constituents are not confirming the move.

> Contribution points are a first-order approximation from tracked weights and constituent returns. The app does not reconstruct the official index divisor and does not claim exact NSE index attribution.

## Weight data included in this build

- NIFTY 50 heavyweight baseline: NSE Indices factsheet dated **29 May 2026**
- NIFTY Bank heavyweight baseline: NSE Indices factsheet dated **31 Aug 2026**

The exact metadata exposed by the app is available at:

`GET /api/index/weights`

Weights are kept separate from the AI rules so they can be refreshed without rewriting the signal engine.

## Adaptive AI Fusion v5

The explainable regime-aware fusion system now combines **eight** specialist experts:

1. Trend — spot vs VWAP plus 3m/5m/15m price slope
2. OI — PCR, signed change-in-OI balance and near-ATM positioning
3. Flow — premium momentum plus 1m/3m/5m volume acceleration
4. Microstructure — bid/ask spread quality and market-depth imbalance
5. **Index Brain — weightage-aware NIFTY heavyweight confirmation and divergence**
6. Breadth — simpler weighted heavyweight breadth cross-check
7. Greeks / Volatility — Delta, IV skew and volatility context
8. Structure — call wall, put wall and max-pain location

The engine first classifies the market as TREND, RANGE, BREAKOUT WATCH or VOLATILE and changes expert weights for that regime. The Index Brain is a first-class AI vote, not a cosmetic dashboard card.

## Signal defence

- Multi-horizon AI map: 1–3m, 5–15m and 15–30m directional bias
- false-signal risk score
- anomaly score from unusual volume, spread, IV and expert conflict
- signal stability score
- expert consensus count
- Index Brain divergence penalty inside false-signal risk
- AI Watch Conditions
- conservative online self-calibration from observed 5-minute moves
- data-quality gate
- trap-risk gate
- contract-quality gate

AI confidence is internal confluence, **not a probability of profit**.

## Mobile screens

- **HOME** — NIFTY, AI signal, exact strike, backups, reasons, next-move map and risk shield
- **AI** — expert votes, adaptive learning and AI watch conditions
- **INDEX** — NIFTY Brain, Bank Nifty Brain, heavyweight stocks, sector pulse and divergence shield
- **RADAR** — ranked CE/PE contracts plus market structure
- **CHAIN** — compact mobile option chain with AI-selected strike highlighting
- **CONNECT** — Upstox token/OAuth, expiry, AI mode, alerts, diagnostics and PWA install

## Live market-data design

- NIFTY option chain is bootstrapped by Upstox REST and updated by MarketDataStreamerV3 when available.
- High-impact constituent analysis uses live current-month stock-futures feeds when discovered by Upstox.
- NIFTY and BANK NIFTY index levels are subscribed separately for divergence analysis.
- If the WebSocket is unavailable the option-chain engine can fall back to REST; constituent live coverage is shown explicitly instead of being invented.

## AI modes

- **STRICT** — fewer, higher-conviction signals
- **BALANCED** — moderate filtering
- **FAST** — earlier/noisier signal changes

## Android + iPhone

This build is a Progressive Web App (PWA). Host it on HTTPS and install it from the browser:

- Android: Chrome → Install app / Add to Home screen
- iPhone: Safari → Share → Add to Home Screen

## Upstox connection

Use your own Upstox market-data access. Paste a valid token inside your privately hosted app or configure OAuth in `.env`.

Never send access tokens, API keys or API secrets in chat.

Example `.env`:

```env
UPSTOX_API_KEY=
UPSTOX_API_SECRET=
UPSTOX_REDIRECT_URI=https://YOUR-DOMAIN/api/upstox/callback
UPSTOX_UNDERLYING_KEY=NSE_INDEX|Nifty 50
UPSTOX_ENABLE_WEBSOCKET=true
UPSTOX_ENABLE_BREADTH=true
```

## Local / LAN test

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8787`. On the same Wi-Fi, Android/iPhone can open the computer's LAN IP.

For normal phone installation and notifications, deploy behind HTTPS.

## Demo and self-test

`/api/ai/demo` uses clearly synthetic market data and now includes synthetic NIFTY + BANK NIFTY constituent feeds so the entire Index Brain UI can be previewed without an Upstox token.

Run:

```bash
python SELF_TEST_AI.py
```

The test verifies:

- eight-agent AI fusion
- Index Brain agent
- NIFTY heavyweight analysis
- BANK NIFTY heavyweight analysis
- divergence/confirmation scores
- multi-horizon forecasts
- risk shield
- execution/P&L flags remain disabled


## v10 Command Center
Adds a one-screen command view, data-integrity scoring, price+OI build-up classification, strike battle map, session flow timeline and wall-shift tracking. All outputs remain read-only analytics and are not order instructions.


## v20 Flow Intelligence

V20 adds magnitude-calibrated AutoTrender bars, OI Flow, Sector Breadth, Trend Acceleration, persistence, Strike Shift Radar, ATM premium response, session score history and a read-only No-Trade/Wait quality gate. Missing values are shown as N/A and excluded from scoring.

## V63 Market Command Center
V63 adds a TradingView-inspired (information architecture only) market overview with dynamic sector leadership. `Today's Strongest Sector` is computed from current provider rows using equal-weight sector return, breadth and available RVOL confirmation. It also shows the current top gainer inside the strongest sector. No daily sector or stock result is hard-coded.

Optional global-market adapters support GIFT NIFTY, Dow Futures, S&P 500 Futures, Nasdaq Futures, India VIX, Nikkei 225, Hang Seng, DAX and FTSE 100. These remain UNAVAILABLE until a legitimate feed is configured or verified values are ingested through the read-only analytics API.

## V65 — Institutional Data & Money Flow
V65 adds source-verified institutional history, ownership trend states, FII/DII/PRO participant positioning storage, promoter/pledge intelligence, bulk/block deal timelines, sector institutional money maps, stock conviction consensus, institutional screeners/alerts/reports, source provenance and dataset readiness. Official/trusted verification is controlled server-side; callers cannot self-mark records verified. External official collectors must be configured with permitted endpoints/files and missing data remains unavailable.

## V68 — Verified global feed engine

The Market Command Center now consumes authenticated Upstox Global Instruments for supported global indices/indicators and keeps provider latency visible. It also loads official Federal Reserve FRED daily Treasury yields (US 2Y/5Y/10Y/30Y) and calculates the 10Y-2Y curve spread.

Important source-truth rule: Dow Jones / S&P 500 / US Tech 100 cash/global indices are never renamed as futures. Dow/S&P/Nasdaq futures remain separate external adapters and stay UNAVAILABLE unless a legitimate futures feed is configured. No Moneycontrol or TradingView scraping is used.


## V69 Market Depth + Bulk/Block Intelligence

- Up to 30-level Upstox market depth when the connected entitlement/SDK supports `full_d30`; automatic fallback to `full`.
- Bid/ask imbalance, largest walls, spread bps, depth quality and anonymous order-book pressure scoring.
- Verified bulk/block deal intelligence reuses the V65 trusted-source registry and deal ledger.
- No institution identity is inferred from anonymous order-book activity.
- New APIs: `/api/v69/status`, `/api/v69/depth?symbol=...`, `/api/v69/bulk-block`.
- Read-only analytics; no automated execution.
