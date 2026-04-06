Show the Signa frontend signal display system — how signals flow from API to UI.

## Signal Data Flow

```
Backend scan → API response → useAllSignals hook → React Query cache → Page component → SignalCard
```

## Signal Scoring & Display

### Score Ring
- 0-100 score displayed in SVG ring
- Colors: >=80 green (theme.colors.up), >=60 yellow (theme.colors.warning), <60 red (theme.colors.down)
- Always shows numeric score (colorblind accessible)

### Action Badges
- **BUY** → green badge (variant='buy')
- **HOLD** → yellow badge (variant='hold')
- **SELL** → red badge (variant='sell')
- **AVOID** → red badge (variant='avoid')

### Signal Styles
- **MOMENTUM** — following the trend
- **CONTRARIAN** — against the trend (shows contrarian_score)
- **NEUTRAL** — balanced approach

### Buckets
- **SAFE_INCOME** — dividend stocks, ETFs, lower volatility
- **HIGH_RISK** — growth stocks, crypto, higher volatility
- Different scoring weights per bucket (displayed in ticker detail)

## Signal List Page (`src/app/(dashboard)/signals/page.tsx`)

### 6 Filter Groups (all with aria-pressed)
1. **Asset Type**: All, Stocks, Crypto
2. **Signal Style**: All, Momentum, Contrarian
3. **Bucket**: All, Safe Income, High Risk
4. **Action**: All, Buy, Hold, Sell, Avoid
5. **Score**: All, 80+, 60+
6. **Sort**: Score (desc), Recent, Alphabetical

### Search
- Text input with 300ms debounce
- Filters by symbol match
- `aria-label="Search signals"`

### Scan Now Button
- Triggers `POST /scans/trigger?scan_type=MORNING`
- Shows progress: polling every 2.5s via `GET /scans/{scanId}/progress`
- Displays current phase and ticker being analyzed
- On complete: invalidates signals, scans, stats queries + toast notification

### Summary Stats
- Memoized: total count, buy count, gem count, market regime
- Market regime badge: TRENDING/VOLATILE/CRISIS with color

## Signal Card (`src/components/signals/SignalCard.tsx`)

### Collapsed View
- Symbol, action badge, score ring, price, target price
- Watchlist star toggle
- Gem indicator (if is_gem)

### Expanded View (click to toggle)
- Full reasoning text (AI-generated, top 15 signals only)
- Sentiment bar (hidden when grok_data.confidence === 0)
- Technical data summary
- Catalyst and entry window
- Account recommendation (TFSA/RRSP/TAXABLE)
- Superficial loss warning flag (CRA 30-day rule)
- Link to ticker detail page

### Performance
- Wrapped in `React.memo()` — only re-renders when signal prop changes
- `role="button"`, `tabIndex={0}`, `aria-expanded` for accessibility
- Enter/Space keyboard support

## Ticker Detail Page (`src/app/(dashboard)/signals/[ticker]/page.tsx`)

### 3 Independent Queries
1. `tickersApi.getDetail(ticker)` → TickerDetail (fundamentals, price)
2. `signalsApi.getTicker(ticker)` → Signal history
3. `client.get('/brain/highlights')` → Brain insights (60s stale)

### Sections
1. **Header**: Symbol, company name, exchange, watchlist star
2. **Price**: Current price, day change %, format via `formatPrice()`
3. **Score Weights**: Visual breakdown (momentum vs fundamentals vs sentiment)
   - SAFE_INCOME: Technical 35%, Fundamental 30%, Macro 20%, Sentiment 15%
   - HIGH_RISK: Sentiment 35%, Catalyst 30%, Technical 25%, Fundamental 10%
4. **Price Chart**: PriceChart component (1D/1W/1M/3M)
5. **Fundamentals**: PE, EPS, market cap, dividend yield, 52-week range
6. **Brain Insights**: AI analysis summary (if available)
7. **Signal History**: Previous signals for this ticker

### Error Handling
- Loading skeleton while detail loads
- Inline error cards for failed brain insights / signal history (non-blocking)

## GEM Detection
- `is_gem: true` signals get special treatment
- Gem badge on card
- `gem_reason` displayed when available
- `useGemSignals()` hook: 5min stale, 5min refetch
- Dashboard "Quick Actions" prioritizes gems

## Two-Pass Scan Display
- **Top 15** signals (by score): Show full `reasoning` text (AI-generated)
- **Bottom 35** signals: Show "tech-only" label (no AI reasoning)
- Signals page shows reasoning in expanded card view
- Ticker detail shows reasoning in dedicated section

## Market Regime
- Displayed as colored badge: TRENDING (green), VOLATILE (yellow), CRISIS (red)
- Comes from `signal.market_regime` field
- Shown in overview page and signal list summary
