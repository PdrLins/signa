# Brain Training Suggestions — Market Prediction Research

> Research compiled for Signa's AI signal engine. Each section covers what professional quant systems use, how Signa can learn it, and practical implementation details for a solo developer.
>
> **Current Signa stack:** Technical indicators (RSI, MACD, Bollinger, SMA), fundamentals (P/E, dividend, EPS), macro data (VIX, Fed rate, F&G Index), AI sentiment analysis (Grok/Gemini/Claude), two-pass scoring pipeline with market regime detection.

---

## Table of Contents

1. [Factor Investing Models](#1-factor-investing-models)
2. [Alternative Data Signals](#2-alternative-data-signals)
3. [Mean Reversion vs Momentum Strategies](#3-mean-reversion-vs-momentum-strategies)
4. [Earnings-Based Signals](#4-earnings-based-signals)
5. [Seasonality Patterns](#5-seasonality-patterns)
6. [Intermarket Signals](#6-intermarket-signals)
7. [Machine Learning Approaches](#7-machine-learning-approaches)
8. [Risk Parity and Portfolio Construction](#8-risk-parity-and-portfolio-construction)
9. [Sentiment Quantification](#9-sentiment-quantification)
10. [Crypto-Specific Signals](#10-crypto-specific-signals)

---

## 1. Factor Investing Models

**What it is:** Factor investing identifies persistent, systematic drivers of returns across stocks. The Fama-French model identifies market risk, size (small vs large), value (high vs low book-to-market), profitability (robust vs weak), and investment (conservative vs aggressive) as the five core factors. AQR adds momentum and quality-minus-junk (QMJ). Two Sigma uses hundreds of ML-derived micro-factors.

**Which factors have the highest alpha:**

| Factor | Historical Annual Premium | Current Status |
|--------|--------------------------|----------------|
| Momentum (12-1 month) | 6-8% | Still works, but with crash risk |
| Quality (QMJ) | 3-5% | Very consistent, low drawdowns |
| Value (HML) | 3-5% | Underperformed 2010-2020, rebounding |
| Size (SMB) | 2-3% | Weak in recent decades |
| Low Volatility (BAB) | 4-6% | Works well, especially risk-adjusted |
| Profitability (RMW) | 3-4% | Robust and persistent |

**How the brain can learn it:**

Signa already uses fundamentals (P/E, EPS, dividend) but doesn't explicitly compute factor exposures. The implementation would add a `factor_score` component to the scoring engine:

```
Implementation plan:
1. Download Fama-French factor data from Kenneth French Data Library
   (mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html)
   - Free, updated monthly, available via pandas-datareader
2. Compute per-stock factor exposures:
   - Momentum: 12-month return minus last month (already have price history)
   - Quality: ROE + earnings stability + low leverage (from yfinance fundamentals)
   - Value: Book-to-market, earnings yield (from yfinance)
   - Profitability: Gross profit / total assets (from yfinance)
3. Score each stock's multi-factor profile (0-100)
4. Add as ~10-15% weight in signal_engine.py scoring
```

**Data source:** `pandas-datareader` has built-in `FamaFrenchReader` that pulls directly from the Kenneth French Data Library. For per-stock factor computation, yfinance already provides the needed fundamentals.

- **Priority:** HIGH — significant alpha, uses data Signa already fetches
- **Cost:** FREE (Kenneth French Library + yfinance)
- **Expected edge improvement:** +3-5% annual alpha; reduces drawdowns via quality/profitability tilt
- **Integration point:** New `app/signals/factors.py` module, added as a scoring component in `signal_engine.py`

---

## 2. Alternative Data Signals

**What it is:** Non-traditional data sources that provide information before it shows up in price or fundamentals. Quant funds use options flow (sweep detection, unusual volume), dark pool activity (institutional accumulation), congressional trading (5-10% annual outperformance documented in academic studies), insider buying, and government contract data.

**Signal-by-signal breakdown:**

### Congressional Trading
- Academic studies show congressional portfolios outperform S&P 500 by 5-10% annually
- STOCK Act requires disclosure within 45 days
- **Data:** QuiverQuant API (`pip install quiverquant`) — free tier limited, $10/mo for full access
- **Implementation:** Track buys by members with best historical accuracy; add as a catalyst signal in Claude synthesis prompt ("Congress member X bought $50K-$100K of {ticker} on {date}")
- **Edge:** 3-5% when filtered for high-conviction trades (>$50K purchases)

### Insider Buying
- CEO/CFO open-market purchases are the strongest signal (not options exercises)
- Cluster buys (3+ insiders buying within 30 days) are especially predictive
- **Data:** SEC EDGAR Form 4 filings (free), or Finnhub insider transactions API (free tier: 60 calls/min)
- **Implementation:** Check insider transactions for each ticker in Pass 1; flag cluster buys as a score booster (+5 points)
- **Edge:** 2-4% for cluster insider buys

### Options Flow (Unusual Activity)
- Sweep orders (large orders split across exchanges for urgency) before earnings are a classic institutional tell
- Out-of-the-money call sweeps signal informed bullish bets
- **Data:** Unusual Whales ($30-40/mo), FlowAlgo ($50/mo), or QuantData ($30/mo)
- **Implementation:** Would require paid subscription; could add as optional enrichment in Pass 2
- **Edge:** 2-3% but noisy; best combined with other signals

### Dark Pool Activity
- Sustained institutional accumulation (buy volume > sell volume over multiple days) precedes breakouts
- **Data:** FINRA ADF data (free but delayed), or FlowAlgo/Unusual Whales (paid)
- **Implementation:** Difficult to get free real-time data; lower priority for solo developer
- **Edge:** 1-2% standalone, better as confirmation

**How the brain can learn it:**

```
Phase 1 (FREE):
- Add SEC EDGAR Form 4 parser for insider buying signals
- Add insider_score to scoring: cluster buys = +5, single CEO buy = +3
- Feed insider data into Claude synthesis prompt for context

Phase 2 (LOW COST - $10/mo):
- QuiverQuant API for congressional trades
- Add congress_following flag to GEM detection criteria
- Track which congress members have best hit rates

Phase 3 (MEDIUM COST - $30-50/mo):
- Unusual Whales or QuantData for options flow
- Sweep detection as confirmation signal in Pass 2
```

- **Priority:** HIGH (insider buying FREE tier), MEDIUM (congressional, options flow)
- **Cost:** FREE (SEC EDGAR) / LOW $10/mo (QuiverQuant) / MEDIUM $30-50/mo (options flow)
- **Expected edge improvement:** +2-5% depending on which signals are combined
- **Integration point:** New `app/signals/alternative_data.py`, insider data added to Pass 1 pre-filter

---

## 3. Mean Reversion vs Momentum Strategies

**What it is:** Two opposing market forces — momentum says winners keep winning (3-12 month horizon), mean reversion says overextended prices snap back (1-5 day horizon). Professional quant systems dynamically switch between them based on market regime and timeframe.

**When each works:**

| Timeframe | Strategy | Why |
|-----------|----------|-----|
| < 1 week | Mean reversion | Short-term overreaction, bid-ask bounce |
| 1-4 weeks | Mixed / transition zone | Depends on catalyst |
| 1-12 months | Momentum | Trend continuation, institutional herding |
| > 12 months | Mean reversion | Long-term fundamental anchoring |

**Market regime interaction:**

| Regime | Best Strategy |
|--------|---------------|
| Trending (VIX < 20) | Momentum works well |
| Volatile (VIX 20-30) | Mean reversion on dips |
| Crisis (VIX > 30) | Neither — cash or inverse |
| Range-bound (low ADX) | Mean reversion dominates |

**How the brain can learn it:**

Signa already has market regime detection (TRENDING/VOLATILE/CRISIS) and contrarian detection (which is essentially mean reversion). The improvement is making this dynamic:

```
Implementation plan:
1. Add ADX (Average Directional Index) to technical indicators
   - ADX > 25 = trending → favor momentum signals
   - ADX < 20 = range-bound → favor mean reversion (contrarian)
2. Compute 3-month and 6-month momentum scores per ticker
   - Already have price history; just need returns calculation
3. Modify signal_engine.py to adjust weights dynamically:
   - In TRENDING regime with ADX > 25: increase technical momentum weight by 10%
   - In VOLATILE regime with ADX < 20: increase contrarian weight, lower BUY threshold
4. Add momentum_score (3mo + 6mo relative returns) to scoring
5. Track which regime produced best signals in learning journal
```

- **Priority:** HIGH — directly enhances existing regime system
- **Cost:** FREE (all data already available from yfinance)
- **Expected edge improvement:** +2-4% by avoiding momentum trades in choppy markets and vice versa
- **Integration point:** Enhance `app/signals/regime.py` with ADX, modify weights in `signal_engine.py`

---

## 4. Earnings-Based Signals

**What it is:** Post-Earnings Announcement Drift (PEAD) is one of the most documented anomalies in finance — stocks continue drifting in the direction of an earnings surprise for 20-60 trading days after the announcement. Standardized Unexpected Earnings (SUE) measures the surprise magnitude.

**Key findings from research:**

- PEAD generates 3-7% annualized alpha historically
- Strongest in small/mid-cap stocks (less analyst coverage = slower information diffusion)
- Text-based earnings surprise (analyzing earnings call transcripts) produces even larger drift than numeric SUE
- Effect has diminished in large-caps since ~2006 due to algorithmic arbitrage
- Still very much alive in stocks with < 10 analyst coverage
- Optimal holding period: 5-20 trading days post-announcement

**How the brain can learn it:**

```
Implementation plan:
1. Track earnings dates for universe tickers (yfinance .calendar property)
2. Compute SUE for each earnings report:
   SUE = (Actual EPS - Consensus EPS) / std(historical surprises)
   - Consensus from yfinance analyst estimates (free)
3. Post-earnings drift signal:
   - SUE > 1.0 = positive surprise → BUY bias for 20 days
   - SUE < -1.0 = negative surprise → AVOID for 20 days
   - Add earnings_drift_score to signal scoring (+10 points for strong positive SUE)
4. Guidance revision tracking:
   - If analysts revise estimates up after earnings → additional +5 points
   - yfinance provides analyst recommendations and target prices
5. Pre-earnings volatility signal:
   - Flag tickers with earnings in next 7 days
   - Reduce position size (Kelly adjustment) for pending earnings
6. Feed earnings surprise data into Claude synthesis prompt
```

- **Priority:** HIGH — well-documented alpha, free data, fits naturally into scan pipeline
- **Cost:** FREE (yfinance earnings data, FRED)
- **Expected edge improvement:** +3-5% especially for small/mid-cap HIGH_RISK tickers
- **Integration point:** New `app/signals/earnings.py`, modify scan_service.py to check earnings calendar

---

## 5. Seasonality Patterns

**What it is:** Calendar-based patterns in stock returns. While many have been arbitraged away in large-caps, some persist as structural features of the market.

**What the evidence shows:**

| Pattern | Evidence Strength | Current Status |
|---------|------------------|----------------|
| Sell in May (Nov-Apr > May-Oct) | Strong — persists in 300 years of data | Still works ~80% of 5-year periods |
| January Effect | Weak — declining since 1988 | Mostly gone in large-caps |
| FOMC drift (pre-meeting rally) | Moderate | Diminished but still measurable |
| Options expiration week volatility | Moderate | Structural (pin risk) |
| End-of-month inflows | Moderate | 401k/pension flows create real demand |
| Santa Claus rally (last 5 + first 2 trading days) | Moderate | ~75% positive historically |
| September weakness | Moderate | Worst month on average historically |

**How the brain can learn it:**

```
Implementation plan:
1. Add seasonality_modifier to signal_engine.py:
   - November-April: +3 points (favorable season)
   - May-October: -2 points (unfavorable season)
   - September: additional -3 points
   - FOMC meeting week: reduce position sizes 10% (increased vol)
2. Track FOMC meeting dates (published yearly by Fed, available on FRED)
3. Options expiration detection:
   - Third Friday of each month = monthly opex
   - Quarterly opex (March, June, Sept, Dec) = larger impact
   - Flag in scan reasoning: "Quarterly options expiration this week — expect elevated volatility"
4. Feed calendar context into Claude synthesis prompt
```

**Important caveat:** Seasonality should never be a primary signal — it's a modifier. Weight should be small (2-5% of total score at most). The real value is in position sizing adjustments (smaller positions during historically volatile periods).

- **Priority:** LOW — small edge, mostly useful as a position sizing modifier
- **Cost:** FREE (FRED for FOMC dates, standard calendar logic)
- **Expected edge improvement:** +0.5-1% from avoiding seasonal traps
- **Integration point:** Small modifier in `signal_engine.py`, FOMC dates in `app/signals/regime.py`

---

## 6. Intermarket Signals

**What it is:** Financial markets are interconnected — bonds, currencies, commodities, and equities move in systematic relationships. John Murphy's four pillars framework tracks how shifts in one market predict changes in others.

**Core relationships Signa should track:**

| Signal | Relationship | What It Predicts |
|--------|-------------|-----------------|
| 10Y Treasury yield rising | Negative for growth stocks, positive for financials | Sector rotation |
| 10Y-2Y spread inverting | Recession in 12-18 months | Defensive positioning |
| USD Index (DXY) rising | Negative for commodities, multinationals, EM | Sector/stock selection |
| Oil rising | Positive energy, negative transports/airlines | Sector filter |
| Gold rising | Risk-off signal, inflation hedge demand | Reduce HIGH_RISK exposure |
| Copper/Gold ratio falling | Economic slowdown signal | Defensive tilt |
| Credit spreads widening | Stress in corporate debt, risk-off | Reduce exposure broadly |

**How the brain can learn it:**

Signa already fetches VIX and Fed funds rate. The enhancement adds more intermarket signals:

```
Implementation plan:
1. Expand macro snapshot in scan_service.py:
   - 10Y-2Y spread (FRED: T10Y2Y) — already have 10Y, add 2Y
   - DXY approximation (FRED: DTWEXBGS trade-weighted dollar)
   - Crude oil (yfinance: CL=F or USO)
   - Gold (yfinance: GC=F or GLD)
   - Copper/Gold ratio (yfinance: HG=F / GC=F)
   - Investment-grade credit spread (FRED: BAMLC0A4CBBB)

2. Create intermarket_regime() function:
   - RISK_ON: yield curve normal, DXY stable/falling, copper/gold rising
   - RISK_OFF: curve inverted, DXY surging, gold outperforming
   - INFLATIONARY: oil surging, gold rising, yields rising

3. Sector sensitivity mapping:
   - Rising yields → boost financials (XLF), reduce tech (XLK) weight
   - Rising oil → boost energy (XLE), penalize airlines
   - Rising gold → flag as risk-off, boost utilities/staples

4. Integrate into scoring:
   - intermarket_score as 10-15% of macro component
   - Feed intermarket context into Claude synthesis prompt:
     "10Y yield rose 20bps this week, yield curve steepening, DXY weakening —
      favorable for growth, unfavorable for defensive"
```

- **Priority:** HIGH — all data is free, significantly improves macro scoring
- **Cost:** FREE (FRED + yfinance futures/ETF data)
- **Expected edge improvement:** +2-4% from better macro context and sector rotation signals
- **Integration point:** Expand `app/signals/regime.py`, new `app/signals/intermarket.py`

---

## 7. Machine Learning Approaches

**What it is:** Using ML models to find non-linear patterns in market data that traditional rule-based systems miss. Recent research (2025-2026) shows hybrid models (gradient boosting + LSTM) outperform either approach alone.

**What works in practice:**

| Approach | Pros | Cons | Best For |
|----------|------|------|----------|
| **LightGBM/XGBoost** | Fast, interpretable, handles tabular data well, R^2 > 99% on price prediction | Overfitting risk, needs good features | Feature-rich scoring (combine all indicators) |
| **LSTM** | Captures temporal dependencies, good at sequence patterns | Slow to train, needs GPU, black box | Price direction prediction |
| **Transformer (TFT)** | State-of-art for time series, attention mechanism | Complex, resource-heavy | Multi-horizon forecasting |
| **Hybrid LSTM+LightGBM** | Best of both worlds — temporal + feature-based | More complex pipeline | Production systems |
| **LLM-generated alpha** | Uses GPT/Claude to generate formulaic alpha factors | Experimental, noisy | Novel feature discovery |

**Practical recommendation for Signa:**

LightGBM is the best starting point — it's fast, works on CPU, handles the tabular feature data Signa already computes, and can replace or augment the rule-based scoring system.

```
Implementation plan:

Phase 1 — LightGBM Scoring Model:
1. Collect training data from Signa's signal history:
   - Features: RSI, MACD, Bollinger position, SMA distance, P/E, EPS growth,
     dividend yield, VIX, Fed rate, sentiment score, volume ratio, ADX
   - Label: 20-day forward return (or binary: >5% gain = 1, else 0)
2. Train LightGBM classifier with walk-forward validation:
   - Train on 12 months, validate on next 3 months, roll forward
   - Key hyperparameters: max_depth=6, num_leaves=31, learning_rate=0.05
3. Use model probability as ml_confidence_score (0-100)
4. Blend with existing rule-based score:
   - final_score = 0.7 * rule_score + 0.3 * ml_score (initially)
   - Gradually increase ML weight as model proves itself

Phase 2 — Feature Importance Analysis:
1. Use LightGBM feature importance to identify which signals matter most
2. Feed importance rankings into brain's self-learning loop
3. Automatically adjust scoring weights based on what the model learns

Phase 3 — LSTM for Direction (optional, needs GPU):
1. Train LSTM on 60-day price windows → predict 5-day direction
2. Use as additional confirmation signal, not primary
3. Consider cloud GPU (Google Colab free tier for training)
```

**Key packages:** `lightgbm`, `scikit-learn`, `optuna` (for hyperparameter tuning)

- **Priority:** HIGH (LightGBM Phase 1) / LOW (LSTM Phase 3)
- **Cost:** FREE (LightGBM runs on CPU, training data from Signa's own history)
- **Expected edge improvement:** +5-10% — ML can find non-linear interactions between indicators that rule-based scoring misses
- **Integration point:** New `app/ai/ml_model.py`, blended scoring in `signal_engine.py`

---

## 8. Risk Parity and Portfolio Construction

**What it is:** Professional position sizing goes beyond simple Kelly criterion. Risk parity equalizes risk contributions from each position; half-Kelly reduces the aggressive Kelly bet by 50% to protect against estimation errors; and volatility-targeting adjusts position size inversely to recent volatility.

**Methods ranked by sophistication:**

| Method | Description | Signa Has? |
|--------|-------------|-----------|
| Kelly Criterion | Optimal growth rate sizing: f* = (bp-q)/b | Yes (kelly.py) |
| Half-Kelly | Kelly * 0.5 for safety | Partial (halved in VOLATILE regime) |
| Volatility Targeting | Size inversely to realized vol | No |
| Risk Parity | Equal risk contribution per position | No |
| VIX-Adjusted Kelly | Reduce Kelly when VIX elevated | Partial |
| Max Drawdown Constraint | Cap position so max loss < X% of portfolio | No |
| Correlation-Aware Sizing | Reduce positions in correlated assets | No |

**How the brain can learn it:**

```
Implementation plan:

1. Volatility-targeted position sizing:
   - Compute 20-day realized volatility for each ticker
   - Target a fixed daily risk per position (e.g., 0.5% of portfolio)
   - position_size = target_risk / (realized_vol * sqrt(252))
   - Cap at Kelly size (don't exceed optimal)

2. Correlation guard:
   - Before issuing multiple BUY signals, compute pairwise correlation
     of top candidates (using 60-day returns from yfinance)
   - If correlation > 0.7, reduce combined allocation by 30%
   - Prevent the portfolio from becoming a concentrated sector bet

3. Maximum drawdown constraint:
   - Define max acceptable loss per position: 2% of portfolio
   - position_size = min(kelly_size, 0.02 / expected_max_drawdown)
   - Use ATR (Average True Range) * 2 as expected max drawdown proxy

4. VIX-regime Kelly scaling:
   - VIX < 15: Kelly * 1.0 (full size)
   - VIX 15-20: Kelly * 0.8
   - VIX 20-25: Kelly * 0.5
   - VIX 25-30: Kelly * 0.3
   - VIX > 30: Kelly * 0.1 (minimal exposure)

5. Portfolio-level risk budget:
   - Total portfolio heat = sum of all position risks
   - Cap at 6% total daily risk
   - If adding a new position would exceed budget, skip or reduce size
```

- **Priority:** MEDIUM — improves risk management, prevents blow-ups
- **Cost:** FREE (all computations from existing data)
- **Expected edge improvement:** +1-3% alpha, but more importantly -30-50% drawdown reduction
- **Integration point:** Enhance `app/signals/kelly.py`, new `app/signals/risk_parity.py`

---

## 9. Sentiment Quantification

**What it is:** Beyond Signa's current X/Twitter sentiment (via Grok), professional quant systems use multiple quantitative sentiment indicators that measure where real money is being positioned, not just what people are saying.

**Sentiment signals ranked by predictive power:**

| Signal | What It Measures | Contrarian? | Data Source |
|--------|-----------------|-------------|-------------|
| VIX term structure | Institutional fear/complacency | Yes — backwardation = buy signal | Free (CBOE, vixcentral.com) |
| Put/Call ratio (equity-only) | Retail speculation vs hedging | Yes — extreme puts = buy | Free (CBOE) |
| AAII Sentiment Survey | Individual investor mood | Yes — extreme bearish = buy | Free (aaii.com, weekly) |
| Fund flow data | Money moving in/out of sectors | Trend-following | Partial free (ETF flows) |
| Short interest | Bearish positioning | Contrarian at extremes | Free (FINRA, delayed) |
| CNN Fear & Greed Index | Multi-factor sentiment composite | Yes | Already in Signa |

**VIX term structure is the highest-value addition:**
- When VIX futures are in backwardation (short-term > long-term), subsequent S&P 500 returns are consistently positive
- When in contango (normal state), no meaningful signal
- Backwardation + extreme fear = strongest buy signal in the quant playbook

**How the brain can learn it:**

```
Implementation plan:

1. VIX term structure (HIGHEST PRIORITY):
   - Fetch VIX spot + VIX futures (VX1, VX2) from yfinance or CBOE
   - Compute: vix_term_slope = (VX2 - VIX_spot) / VIX_spot
   - Backwardation (slope < 0): bullish signal (+5 to macro score)
   - Steep contango (slope > 0.15): complacency warning (-3 to macro score)
   - Add to regime.py as additional regime signal

2. Put/Call ratio:
   - CBOE publishes daily equity put/call ratio (free, downloadable)
   - 5-day moving average > 1.0 = extreme fear (contrarian buy)
   - 5-day moving average < 0.6 = extreme greed (contrarian caution)
   - Add to macro component of scoring

3. AAII Sentiment Survey:
   - Weekly data, free from aaii.com
   - Bull% - Bear% spread: below -20 = extreme bearish (contrarian buy)
   - Above +30 = extreme bullish (contrarian caution)
   - Can scrape weekly or use as manual input

4. Short interest:
   - yfinance provides short_percent_of_float for each ticker
   - Short interest > 20% = potential short squeeze candidate
   - Combine with positive momentum = flag as high-reward setup
   - Already accessible in yfinance .info dict

5. Composite sentiment index:
   - Blend: 30% VIX term structure + 25% put/call + 25% F&G + 20% AAII
   - 0-100 scale, extreme readings (<20 or >80) trigger contrarian logic
   - Replace or augment current F&G-only macro sentiment
```

- **Priority:** HIGH (VIX term structure, short interest), MEDIUM (put/call, AAII)
- **Cost:** FREE (all data publicly available)
- **Expected edge improvement:** +3-5% from better contrarian timing
- **Integration point:** Enhance `app/signals/regime.py`, new `app/signals/sentiment_quant.py`

---

## 10. Crypto-Specific Signals

**What it is:** Cryptocurrency markets have unique on-chain data not available in traditional finance — every transaction is recorded on the blockchain, providing transparent flow data, whale positioning, and derivatives market structure.

**Key crypto signals:**

| Signal | What It Measures | Predictive Power |
|--------|-----------------|-----------------|
| Exchange net flow | Coins moving to/from exchanges | HIGH — inflow = selling pressure |
| Funding rate | Cost of leveraged long positions | MODERATE — extreme = mean reversion |
| Open interest | Total derivatives exposure | MODERATE — divergence from price = warning |
| Whale wallet movements | Large holder behavior | MODERATE — sustained flow > individual txns |
| Stablecoin exchange inflows | Buying power arriving at exchanges | HIGH — dry powder for buying |
| Miner outflows (BTC) | Miner selling pressure | MODERATE — increases at cycle tops |
| MVRV ratio | Market value vs realized value | HIGH — valuation metric for crypto |
| NVT ratio | Network value to transactions | MODERATE — crypto P/E equivalent |

**How the brain can learn it:**

```
Implementation plan:

1. Exchange flow signals (FREE):
   - CryptoQuant free tier: basic exchange flow data
   - CoinGlass free tier: funding rates, open interest, liquidations
   - Aggregate exchange inflow/outflow for BTC, ETH
   - Net inflow > 2 std dev above mean = bearish signal
   - Net outflow sustained 7+ days = accumulation (bullish)

2. Funding rate signal (FREE):
   - CoinGlass API: real-time funding rates across exchanges
   - Funding rate > 0.05% = overleveraged longs (mean reversion risk)
   - Funding rate < -0.02% = overleveraged shorts (potential squeeze)
   - Add as modifier for crypto tickers in HIGH_RISK scoring

3. MVRV ratio (FREE/LOW):
   - CryptoQuant or Glassnode free tier
   - MVRV > 3.0 = historically overvalued (top signal)
   - MVRV < 1.0 = historically undervalued (bottom signal)
   - Use as macro-level crypto cycle indicator

4. Stablecoin flows (FREE):
   - Track USDT/USDC market cap changes (CoinGecko API, free)
   - Rising stablecoin supply = dry powder entering crypto
   - Stablecoin exchange deposits = imminent buying
   
5. Integration with Signa's crypto scoring:
   - Signa already reserves 5 crypto slots in scans
   - Add crypto_onchain_score as 15-20% of crypto HIGH_RISK scoring
   - Breakdown: 40% exchange flow + 30% funding rate + 30% MVRV
```

**Free crypto data APIs:**
- CoinGecko API: free tier (30 calls/min) — prices, market caps, volumes
- CoinGlass: free tier — funding rates, open interest, liquidation data
- CryptoQuant: free tier — basic on-chain metrics
- Blockchain.com API: free — BTC-specific on-chain data

- **Priority:** MEDIUM — valuable for the 5 crypto slots, but lower volume than equity signals
- **Cost:** FREE (CoinGecko + CoinGlass free tiers) / LOW $10-30/mo for CryptoQuant pro
- **Expected edge improvement:** +3-6% on crypto signals specifically
- **Integration point:** New `app/signals/crypto_onchain.py`, modify scan_service.py crypto scoring

---

## Implementation Roadmap

### Phase 1 — Quick Wins (1-2 weeks, all FREE)

| Enhancement | Module | Impact |
|-------------|--------|--------|
| Momentum + ADX scoring | `signals/regime.py` | +2-4% |
| VIX term structure | `signals/regime.py` | +2-3% |
| Short interest from yfinance | `signal_engine.py` | +1-2% |
| Intermarket signals (10Y-2Y, DXY, oil, gold) | `signals/intermarket.py` | +2-4% |
| Earnings surprise (SUE) tracking | `signals/earnings.py` | +3-5% |
| Insider buying from SEC EDGAR | `signals/alternative_data.py` | +2-3% |
| Factor scores (momentum, quality, value) | `signals/factors.py` | +3-5% |
| Seasonality modifier | `signal_engine.py` | +0.5-1% |

**Total estimated improvement: +15-27% composite edge**

### Phase 2 — ML Integration (2-4 weeks, FREE)

| Enhancement | Module | Impact |
|-------------|--------|--------|
| LightGBM scoring model | `ai/ml_model.py` | +5-10% |
| Feature importance → auto weight tuning | `ai/signal_engine.py` | +2-3% |
| Volatility-targeted position sizing | `signals/kelly.py` | -30% drawdown |
| Correlation guard | `signals/risk_parity.py` | -20% drawdown |

### Phase 3 — Paid Data (ongoing, $10-50/mo)

| Enhancement | Cost | Impact |
|-------------|------|--------|
| QuiverQuant congressional trades | $10/mo | +2-3% |
| CryptoQuant pro on-chain data | $30/mo | +3-5% crypto |
| Unusual Whales options flow | $30-40/mo | +2-3% |

### Phase 4 — Advanced ML (4-8 weeks, FREE with cloud GPU)

| Enhancement | Module | Impact |
|-------------|--------|--------|
| LSTM price direction model | `ai/ml_model.py` | +2-5% |
| Transformer (TFT) multi-horizon | `ai/ml_model.py` | +3-5% |
| LLM-generated alpha factors | `ai/provider.py` | Experimental |

---

## Scoring System Enhancement Proposal

Current Signa scoring uses fixed weights per category. With the above enhancements, the proposed new scoring breakdown:

### Safe Income (Enhanced)
| Component | Current | Proposed |
|-----------|---------|----------|
| Dividend reliability | 35% | 25% |
| Fundamental health | 30% | 20% |
| Macro environment | 25% | 15% |
| Sentiment (Grok) | 10% | 10% |
| Factor score (quality + value) | — | 10% |
| Intermarket context | — | 10% |
| Earnings/insider signals | — | 5% |
| ML confidence | — | 5% |

### High Risk (Enhanced)
| Component | Current | Proposed |
|-----------|---------|----------|
| X/Twitter sentiment (Grok) | 35% | 25% |
| Catalyst detection (Claude) | 30% | 20% |
| Technical momentum | 25% | 15% |
| Fundamentals | 10% | 5% |
| Factor score (momentum + quality) | — | 10% |
| Intermarket context | — | 5% |
| Earnings/insider/alt data | — | 10% |
| ML confidence | — | 10% |

### Crypto High Risk (New)
| Component | Weight |
|-----------|--------|
| X/Twitter sentiment (Grok) | 25% |
| Catalyst detection (Claude) | 15% |
| Technical momentum | 15% |
| On-chain metrics | 20% |
| Funding rate + OI | 10% |
| Intermarket (DXY, gold correlation) | 10% |
| ML confidence | 5% |

---

## Key Data Sources Summary

| Source | Cost | What It Provides | Python Access |
|--------|------|-----------------|---------------|
| yfinance | FREE | Price, fundamentals, short interest, earnings | `pip install yfinance` |
| FRED | FREE | Macro data, yield curves, credit spreads | `fredapi` or `pandas-datareader` |
| Kenneth French Library | FREE | Factor returns data | `pandas-datareader` |
| SEC EDGAR | FREE | Insider transactions (Form 4) | REST API + parser |
| CBOE | FREE | Put/call ratio, VIX futures | CSV download |
| AAII | FREE | Sentiment survey | Web scrape (weekly) |
| CoinGecko | FREE | Crypto prices, market caps | `pycoingecko` |
| CoinGlass | FREE tier | Funding rates, open interest | REST API |
| Finnhub | FREE tier | Alternative data, insider txns | `finnhub-python` |
| Alpha Vantage | FREE tier | Technical indicators, fundamentals | REST API |
| QuiverQuant | $10/mo | Congressional trades, gov contracts | `quiverquant` |
| CryptoQuant | $30/mo | On-chain analytics | REST API |
| Unusual Whales | $30-40/mo | Options flow, sweep detection | REST API |

---

## References

- [Fama-French 5-Factor Model Analysis — Robeco](https://www.robeco.com/en-int/insights/2024/10/fama-french-5-factor-model-why-more-is-not-always-better)
- [Kenneth French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html)
- [Factor Investing Insights — Alpha Architect](https://alphaarchitect.com/factor-investing-insights-you-wont-hear-from-fama-and-french/)
- [Alternative Data Strategies — TenderAlpha](https://www.tenderalpha.com/blog/post/quantitative-analysis/3-quantitative-strategies-based-on-alternative-data)
- [QuiverQuant Congressional Trading](https://www.quiverquant.com/congresstrading/)
- [Mean Reversion Trading Strategies — Quantified Strategies](https://www.quantifiedstrategies.com/mean-reversion-trading-strategy/)
- [Slow Mean Reversion — Systematic Trading Blog](https://qoppac.blogspot.com/2025/03/very-slow-mean-reversion-and-some.html)
- [PEAD — Quantpedia](https://quantpedia.com/strategies/post-earnings-announcement-effect/)
- [PEAD Text Analysis — Philadelphia Fed](https://www.philadelphiafed.org/-/media/frbp/assets/working-papers/2021/wp21-07.pdf)
- [Seasonality in the S&P 500 — Investing.com](https://www.investing.com/analysis/seasonality-in-the-sp-500-revisiting-calendar-effects-in-a-modern-market-200672384)
- [Sell in May — Wharton Research](http://www-stat.wharton.upenn.edu/~steele/Courses/434/434Context/Calendar%20Effects/SellInMayGoAway.pdf)
- [Intermarket Analysis — StockCharts](https://chartschool.stockcharts.com/table-of-contents/market-analysis/intermarket-analysis)
- [Bond Yields Impact on Markets — ATFX](https://www.atfx.com/en/analysis/trading-strategies/how-us-bond-yields-impact-forex-market-stock-markets-gold-oil-prices)
- [LSTM Stock Prediction — arXiv 2025](https://arxiv.org/html/2505.05325v1)
- [Gradient Boosting + LSTM Hybrid — arXiv 2025](https://arxiv.org/html/2505.23084v1)
- [Transformer + LLM Alpha — arXiv 2025](https://arxiv.org/html/2508.04975v1)
- [Kelly Criterion in Practice — Alpha Theory](https://www.alphatheory.com/blog/kelly-criterion-in-practice-1)
- [Risk-Constrained Kelly — QuantInsti](https://blog.quantinsti.com/risk-constrained-kelly-criterion/)
- [Position Sizing for Algo Traders — Medium](https://medium.com/@jpolec_72972/position-sizing-strategies-for-algo-traders-a-comprehensive-guide-c9a8fc2443c8)
- [VIX Term Structure as Trading Signal — Macrosynergy](https://macrosynergy.com/research/vix-term-structure-as-a-trading-signal/)
- [AAII Sentiment Survey](https://www.aaii.com/sentimentsurvey)
- [VIX Futures Market Timing — MDPI](https://www.mdpi.com/1911-8074/12/3/113)
- [On-Chain Crypto Analysis Tools 2026 — BingX](https://bingx.com/en/learn/article/what-are-the-top-on-chain-analysis-tools-for-crypto-traders)
- [CoinGlass Crypto Data](https://www.coinglass.com/)
- [CryptoQuant On-Chain Analytics](https://cryptoquant.com)
- [Awesome Quant — GitHub](https://github.com/wilsonfreitas/awesome-quant)
- [Finnhub API Documentation](https://finnhub.io/docs/api)
