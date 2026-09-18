# POWERHOUSE AI V74.3 — Final Research Lock

Research pass completed against current official Upstox and NSE documentation before the final locked build.

## Data-source rules locked into the final build

1. Upstox Option Chain is the primary option-chain source. It exposes LTP, volume, OI, previous OI, bid/ask quantities and option Greeks. POWERHOUSE therefore computes CE/PE ΔOI from actual OI minus previous OI rather than inventing OI change.
2. Upstox Market Data Feed V3 supports `full` (5-level depth) and `full_d30` (30-level depth, subscription limits apply). POWERHOUSE uses depth only when the upstream service actually provides it; otherwise Depth/DOM stays N/A.
3. Upstox option contracts are discovered dynamically from the underlying. Expiry and strike availability are not hard-coded.
4. Upstox expired-contract APIs can support future Hero/Expiry historical replay and back-testing where the account plan/API entitlement allows it.
5. NSE Participant-wise Open Interest and FII Derivatives Statistics are exchange-level participant reports. They must not be converted into a claim that a named institution bought a particular stock/strike unless an explicit source identifies it.
6. NSE FII/FPI & DII cash activity is aggregate/provisional market activity. POWERHOUSE labels it aggregate and does not infer stock-level institutional identity from it.
7. NSE F&O MWPL ban begins once aggregate OI crosses the exchange threshold; the system should treat ban/MWPL as an event/risk guard rather than a bullish/bearish signal.
8. NSE cash-market price bands differ by security; derivative-eligible securities do not use ordinary static cash price bands and instead operate with exchange operating-range controls. Circuit Hunter therefore uses provider/exchange-supplied live limits rather than assuming a universal percentage.
9. Current NSE index/stock derivative expiries are exchange-calendar driven. POWERHOUSE discovers contracts from the provider/exchange and never hard-codes a weekday for signal logic.

## Truth policy

- No demo market values in production panels.
- No synthetic sparklines, RSI, MACD, OI, zones or depth.
- RSI/MACD are calculated only from real provider candles.
- Demand/Supply and Support/Resistance may be candle-derived when the chart engine does not supply them; the UI explicitly labels the source `CANDLE_DERIVED`.
- Break Pressure is an evidence-strength score, not a guaranteed breakout probability.
- 100% trading accuracy is not claimed. Accuracy is empirical and requires resolved live/shadow samples.
- WAIT / N/A / STALE / CLOSED are valid outputs.
- Read-only decision support; no broker order execution.

## Official references used for this lock

- Upstox Market Data Feed V3: https://upstox.com/developer/api-documentation/v3/get-market-data-feed/
- Upstox Put/Call Option Chain: https://upstox.com/developer/api-documentation/get-pc-option-chain/
- Upstox Option Greeks: https://upstox.com/developer/api-documentation/option-greek/
- Upstox Option Contracts: https://upstox.com/developer/api-documentation/get-option-contracts/
- Upstox Open Interest API: https://upstox.com/developer/api-documentation/get-oi/
- NSE Contract Specifications: https://www.nseindia.com/static/products-services/equity-derivatives-contract-specifications
- NSE Derivatives Reports: https://www.nseindia.com/all-reports-derivatives
- NSE FII/FPI & DII activity: https://www.nseindia.com/reports/fii-dii/
- NSE Market Wide Position Limit / Ban: https://www.nseindia.com/static/products-services/equity-derivatives-risk-management-sec-ban
- NSE Price Bands: https://www.nseindia.com/static/products-services/equity-market-price-bands
