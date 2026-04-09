# Signa Brain Learning Journal

Tracks lessons learned from each day of operation. Each entry records what happened, what we learned, what was fixed, and later -- whether the fix actually worked.

---

## Day 1 -- April 6, 2026

### Environment
- Market: VOLATILE (VIX ~25)
- Scans: 9 (4 scheduled + 5 manual)
- Signals: 435 total (85 AI-analyzed, 350 tech-only)
- Budget: Claude $1.02, Grok $0.012, Gemini exhausted
- Brain positions: 10 open, 1 closed (HUM +0.77%)

### Incidents

**1. HUM false sell (score 75 -> 37)**
- What: HUM scored 75 (BUY) with AI at 10 AM, then 37 (AVOID) tech-only at 12:26 PM. Brain sold at +0.77%.
- Root cause: Ticker lost AI analysis in second scan (fell out of top 15), tech-only score collapsed. Also bucket flipped SAFE_INCOME -> HIGH_RISK due to day_change heuristic.
- Analyst target: $212 (we sold at $183.60 -- left 15% on the table)
- Fix applied: Score drop guard (25+ point drops block auto-sell), forced AI on open positions, stable bucket (stored in DB), removed day_change from bucket classification
- Status: APPLIED
- Verdict: TBD (need to see if guard prevents false sells without blocking real ones)

**2. AI vs tech-only score gap**
- What: Same ticker scores 30 points higher with AI than without. BCE.TO: AI=75, tech=45. HUM: AI=75, tech=50.
- Root cause: Tech-only scoring has no sentiment/catalyst input (defaults to 0), but the scoring model weights these at 25-35%. AI analysis adds the missing context.
- Fix proposed: Calibrate tech-only base scores +10 for SAFE_INCOME
- Status: PENDING
- Verdict: TBD

**3. IFC.TO watchdog noise**
- What: 15 watchdog events in one day, all on IFC.TO. 11 HOLD_THROUGH_DIP, 4 ALERT. Sentiment bullish 13/15 times.
- Root cause: IFC.TO hovered near the 2% alert threshold all day. Watchdog correctly held but kept logging.
- Fix proposed: After 3 consecutive holds with bullish sentiment, reduce check frequency
- Status: PENDING
- Verdict: TBD

**4. yfinance DNS/SQLite errors**
- What: 69+ failed downloads per scan. "getaddrinfo() thread failed to start", "unable to open database file"
- Root cause: Too many concurrent yfinance connections exhausting macOS DNS threads. yfinance internal SQLite cache corrupting under async access.
- Fix applied: threads=False on all yf.download calls, disabled yfinance SQLite cache (YF_CACHE=0), batch size 20 (from 50), semaphore=3, pre-scoring in batches of 10
- Status: APPLIED
- Verdict: WORKING (errors reduced from 97 to ~3 delisted tickers only)

**5. Gemini free tier exhaustion**
- What: Gemini hit daily quota mid-scan, causing 90+ second delays per ticker (3 retries with 15/30/45s waits)
- Fix applied: Fast-fail on quota exhaustion (skip retries when error says "FreeTier" or "quota")
- Status: APPLIED
- Verdict: WORKING (scan time dropped from 288s to ~136s)

**6. Dividend yield data error**
- What: HUM showed 199% dividend yield in AI reasoning (real yield is 1.99%). yfinance sometimes returns decimals vs percentages inconsistently.
- Fix applied: _normalize_pct() function -- values > 1 get divided by 100
- Status: APPLIED
- Verdict: TBD (need to verify on next scan)

### Patterns Observed

**Score clustering at confidence=45**
- 12 BUYs had confidence exactly 45%. Claude may be defaulting to this when uncertain.
- Current guard: BUY downgraded to HOLD if confidence < 40%
- Suggestion: raise to 50% (below majority confidence should not be BUY)
- Status: PENDING

**All brain picks are SAFE_INCOME**
- 10/10 brain positions are SAFE_INCOME. Zero HIGH_RISK.
- Reason: HIGH_RISK scoring weights sentiment at 35%, but Grok data is sparse for many tickers. SAFE_INCOME weights fundamentals heavier which tech-only can partially capture.
- Not necessarily bad -- conservative portfolio. But brain is not finding momentum plays.
- Status: OBSERVATION (no fix needed yet)

**Discovery yield is low**
- 80 tickers discovered per scan, 4 produced signals, 0 reached brain-quality (72+)
- All discovered tickers scored 58-65 (HOLD range)
- Suggestion: Add minimum market cap filter ($5B+) to discovery to exclude small/micro caps
- Status: PENDING

### Brain Knowledge Added
1. `score_consistency_guard` -- teaches AI about methodology changes vs real signal changes
2. `data_quality_validation` -- teaches AI to flag extreme data values (199% dividend etc)

### Brain Rules Added
1. `score_drop_guard` -- blocks auto-sell on 25+ point score drops when new score < 50

### Infrastructure Changes
1. Brain watchdog (every 15 min during market hours)
2. MIDDAY scan (12:00 PM ET)
3. Missed scan catch-up on startup
4. Ticker discovery (Yahoo screeners)
5. Auto-add brain picks to tickers table
6. Stable bucket classification (DB-backed)
7. Token refresh (silent JWT renewal on 401)

### Metrics to Track Tomorrow
- [ ] Does the score drop guard correctly block false sells?
- [ ] Do discovered tickers ever score 72+?
- [ ] Does IFC.TO recover or should the brain have sold?
- [ ] Are all 5 scheduled scans completing?
- [ ] Is the watchdog 2% threshold generating appropriate alerts?
- [ ] Does the confidence=45 clustering continue?
- [ ] Any new bucket flip incidents?

---

### Backtest Results (run end of Day 1)

Backtest: 18,759 signals across ~18 months of historical data (tech-only, no AI).

| Metric | SAFE_INCOME | HIGH_RISK | Overall |
|--------|------------|-----------|---------|
| Signals | 3,148 | 2,339 | 5,487 |
| 5d win rate | 58.4% | 53.6% | 56.4% |
| 10d win rate | 59.1% | 53.8% | 56.8% |
| 20d win rate | 62.2% | 56.7% | 59.9% |
| 20d avg return | +1.47% | +1.75% | +1.59% |

Key findings:
1. SAFE_INCOME has higher win rate (62%) -- brain's bias toward SAFE_INCOME is correct
2. HIGH_RISK has higher avg returns (+1.75%) but lower consistency -- high variance
3. Best/worst trades are ALL crypto (DOGE +84%, SOL -29%) -- crypto needs the watchdog
4. Score distribution bottom-heavy: 9,355 in 60-70 range, only 1,810 at 70+, zero above 80 -- validates tech-only calibration need
5. 20-day hold outperforms 5-day (60% vs 56% win rate) -- current 30-day max hold is reasonable
6. Zero GEMs found -- GEM conditions (85+ score) are very strict, needs real AI sentiment to trigger

Impact on pending suggestions:
- low_confidence_guard: SUPPORTED (too many marginal BUYs)
- discovery_market_cap_filter: SUPPORTED (best trades are established names)
- tech_only_score_calibration: SUPPORTED (scores cluster low without AI)
- brain_bucket_diversification: WAIT (HIGH_RISK lower win rate, let brain find balance)
- watchdog_cooldown: NOT TESTABLE (needs real-time data)

### Suggestions Status (end of Day 1)

| Suggestion | Confidence | Decision | Rationale |
|-----------|-----------|----------|-----------|
| low_confidence_guard (40->50%) | 80% | APPLIED | Backtest shows too many marginal BUYs |
| discovery_market_cap_filter ($5B+) | 70% | APPLIED | Day 1 found 80 tickers, 0 scored 72+ |
| tech_only_score_calibration (+10) | 75% | WAIT | See if forced AI on open positions is enough first |
| watchdog_cooldown (3 holds -> hourly) | 65% | WAIT | Only 1 day of data |
| brain_bucket_diversification | 50% | REJECT | Brain naturally picks quality, don't force it |

---

## Day 2 -- April 7, 2026

### Environment
- Market: VOLATILE (VIX ~26.5)
- Fear & Greed: 21.4 (Extreme Fear)
- Scans: 13 (5 scheduled + 8 manual during development)
- Signals: 522 total (31 BUY, 226 HOLD, 265 AVOID)
- Budget: Claude $0.18, Grok $0.02, Total $0.20
- Brain positions: 11 open (was 10, added AVGO), 2 closed total
- Universe: expanded to 282 tickers (added 34 Canadian ETFs)

### Portfolio Performance (End of Day 2)
- **Realized P&L: -2.2%** (HUM +0.8%, PYPL -3.0%)
- **Unrealized P&L: +0.46% avg** (+6.0% total across 13 positions)
- **Winners: 10/13** (77% of open positions are green)
- **Best position: VLO +3.7%**
- **Worst position: CCO.TO -2.2%** (under watchdog monitoring)

### Incidents

**1. PYPL watchdog exit (-3.0%)**
- What: PYPL entered at score 72 (lowest brain pick), gradually dropped to -3.0%. Watchdog detected slow bleed at -3%, fetched sentiment, sentiment was bearish, auto-sold.
- Root cause: Marginal entry (score 72 is the minimum threshold). PYPL had weak fundamentals for the bucket it was in.
- Lesson: Score 72 picks have higher failure rate. Consider raising BRAIN_MIN_SCORE to 73-74 to reduce marginal entries.
- Status: CLOSED (watchdog worked correctly)
- Verdict: CORRECT EXIT. The -3.0% loss was better than holding to the stop at $43 (-7.1%).

**2. discovered_set bug crashed all AI signals**
- What: After code refactoring, `_process_candidate()` became a module-level function but still referenced `discovered_set` via closure. All 15 AI-analyzed signals failed silently.
- Root cause: Variable scoping -- `discovered_set` was defined in `run_scan()` but not passed as parameter.
- Fix: Added `discovered_set` as explicit parameter to `_process_candidate()`.
- Status: APPLIED
- Verdict: FIXED

**3. CNN Fear & Greed HTTP 418**
- What: CNN blocked our generic "Mozilla/5.0" User-Agent, returning HTTP 418 ("I'm a teapot").
- Fix: Updated to full Chrome User-Agent string.
- Status: APPLIED
- Verdict: WORKING (F&G = 21.4, Extreme Fear)

**4. Supabase HTTP/2 disconnections (recurring)**
- What: Multiple 500 errors from stale HTTP/2 connections dropping. stats, virtual-portfolio, and positions-summary endpoints affected.
- Fix: Added `@with_retry` decorator that catches RemoteProtocolError, resets client, retries once.
- Status: APPLIED
- Verdict: SIGNIFICANTLY REDUCED (not eliminated)

**5. Stuck scans from code reloads**
- What: 9 scans stuck in RUNNING status from server restarts during development, blocking new scan triggers.
- Fix: Manual cleanup (set to FAILED), no code change needed.
- Status: RESOLVED
- Verdict: Expected during development, not a production issue

**6. Hardcoded open_trades[:10] limit**
- What: Brain performance page showed 9 positions when 11 existed. The `get_virtual_summary()` function had `open_trades[:10]` hardcoded from when max was 10.
- Fix: Removed the slice, now enriches all open trades.
- Status: APPLIED
- Verdict: FIXED

### Features Shipped (Day 2)

**Brain Intelligence:**
1. Quality factor scoring (Fama-French QMJ) -- +6 bonus for high-quality SAFE_INCOME
2. Momentum factor scoring (UMD) -- +6 bonus for strong 3m/6m trend on HIGH_RISK
3. Short squeeze detection -- up to +20 bonus for high short float + bullish momentum
4. ADX indicator (trend strength) for dynamic strategy selection
5. SMA200 overextension blocker (>50% above = blocked)
6. Crypto volatility scaling (half Kelly, 8% max stop)
7. Portfolio rotation (replace weakest with stronger when full, +5 threshold)
8. Composite concern rule (weakest + losing + held 1d+ = auto-escalate)
9. Force-sell on catastrophic events (-8% total, score < 50, SELL signal + negative P&L)
10. Watchdog slow bleed detection (-3% total)
11. Watchdog cooldown (3 bullish holds -> 1hr pause)
12. ETF-specific scoring weights (15% dividend instead of 35%)
13. Fear & Greed Index in scoring + AI prompts
14. VIX term structure (contango/backwardation)
15. Intermarket signals (gold, oil, copper/gold ratio)
16. PEAD earnings drift module (new file)
17. Brain Telegram notifications (buy/sell/force-sell)

**Frontend:**
1. Market status floating pill (top-right, hover for details)
2. ETF badge on signal cards
3. Asset type filter (Stock/ETF/Crypto)
4. Sub-score pills on signal detail page
5. Probability chip ("70% vs SPY") on signal cards
6. Fear & Greed in stats bar
7. Track record table on brain performance page
8. Short interest in fundamentals grid
9. Settings: Watchdog section (min notify, P&L alert, max positions sliders)
10. How It Works: 7 new sections + updated card/detail reading guides

**Performance:**
1. All stats endpoints wrapped in asyncio.to_thread (was blocking event loop)
2. Supabase retry-on-disconnect decorator
3. Overview signals 200 -> 50, sidebar 200 -> 50
4. Price cache TTL 5min -> 10min
5. Stats cache TTL 30s -> 120s
6. Virtual portfolio + charts: 5-min TTL cache added
7. New DB indexes: signals(created_at DESC), signals(action, created_at DESC)

**Infrastructure:**
1. 34 Canadian ETFs added to universe (XEQT, VEQT, VFV, TEC, etc.)
2. Asset class detection (STOCK/ETF/CRYPTO)
3. Brain knowledge: 13 new entries seeded
4. Backtest regression tracker (`python -m backtest.compare_runs`)
5. Backtest scorer ported: quality, momentum, short squeeze, SMA200 guard

### Backtest Comparison (Day 2 vs Day 1)

| Metric | Day 1 Baseline | Day 2 (Phase 1) | Change |
|--------|---------------|-----------------|--------|
| 10d Win Rate | 56.8% | 58.4% | +1.6% |
| 10d Avg Return | +0.57% | +0.75% | +0.18% |
| 20d Win Rate | 59.9% | 61.5% | +1.6% |
| 20d Avg Return | +1.59% | +1.89% | +0.30% |
| SAFE_INCOME WR | 59.1% | 60.1% | +1.0% |
| HIGH_RISK WR | 53.8% | 55.8% | +2.0% |
| Signals 70+ | 1,810 | 2,882 | +59% |
| Signals 80+ | 0 | 30 | New tier |

### Patterns Observed

**1. All brain picks are still SAFE_INCOME**
- 11/11 positions are SAFE_INCOME. Zero HIGH_RISK. Same as Day 1.
- VIX at 26.5 (VOLATILE regime) reduces HIGH_RISK scores by 15%, making them harder to reach 72+.
- This is the regime system working correctly -- conservative in volatile markets.

**2. AVGO is the standout**
- Scored 77-79 across 4 scans. Strong fundamentals, momentum in sweet spot.
- Brain correctly identified and picked it.

**3. Fear & Greed at 21 (Extreme Fear) is contrarian bullish**
- Historical data: F&G below 25 has preceded market rallies ~70% of the time.
- The brain's macro score incorporates this, but current positions are all SAFE_INCOME which is appropriate for extreme fear.

**4. Watchdog noise on IFC.TO continues**
- 24 events today, mostly HOLD_THROUGH_DIP. Cooldown should reduce this.
- IFC.TO is a Contrarian pick hovering near thresholds -- the brain correctly holds.

**5. PYPL was the only loss**
- Entry score 72 (minimum). Lost -3.0%.
- Lesson: marginal picks (72) fail more often than strong picks (75+).

### Metrics to Track Tomorrow
- [ ] Did the composite concern rule catch any positions early?
- [ ] Is the watchdog cooldown reducing IFC.TO noise?
- [ ] Are ETFs getting scanned and scored correctly (XEQT in watchlist)?
- [ ] Does portfolio rotation trigger when a new 77+ signal appears and brain is full?
- [ ] Net P&L trajectory -- are we heading toward +1-2% monthly?
- [ ] Does Fear & Greed persist in stats bar across sessions?

### Learnings for Brain

1. **Score 72 picks have higher failure rate** -- PYPL was the only loss, and it was the lowest entry score. Consider raising BRAIN_MIN_SCORE to 73.
2. **Slow bleed detection works** -- PYPL was caught at -3.0% instead of hitting stop at -7.1%. Saved ~4% loss.
3. **The brain is conservative in volatile markets** -- all SAFE_INCOME picks, which is correct behavior.
4. **10/13 positions are winners** (77%) -- the brain's stock picking is working, the issue was one marginal entry.
5. **VLO +3.7% is covering PYPL's -3.0% loss** -- diversification across 11 positions means one bad pick doesn't kill the portfolio.

---

## Day 3 -- April 8, 2026

### Environment
- Market: VOLATILE (VIX still elevated -- 3rd day running)
- Scans: 8 (5 scheduled: PRE_MARKET, MORNING, MIDDAY, PRE_CLOSE, AFTER_CLOSE + 3 manual)
- Signals: 306 total -- 73 BUY, 112 HOLD, 121 AVOID
- AI status mix: 33 validated, 57 low_confidence, 216 skipped (tech-only)
- Score distribution: **0 at 82+, 46 at 72-81, 46 at 65-71, 108 at 55-64, 106 below 55**
- GEMs found: **0** (3rd day in a row)
- Bucket mix: 268 SAFE_INCOME / 38 HIGH_RISK
- Brain positions: **5 OPEN, all opened today** (no holdovers from Day 2)

### State Reset Notice
**virtual_trades was wiped between Day 2 and Day 3.** The 11 brain positions from Day 2 (PNC, AVGO, etc.) no longer exist in the table -- only the 5 positions opened today. No history of yesterday's closes or watchdog events survives. Confirm with user whether this was intentional.

### Today's Brain Picks (live P&L at 19:56 ET)

| Symbol | Entry $ | Live $ | P&L % | Score | Tier | Trust | Entered (ET) |
|--------|--------:|-------:|------:|------:|-----:|------:|--------------|
| LTM    |   52.42 |  52.64 | **+0.42%** | 72 | 1 | 1.0 | 10:59 |
| ASML   | 1417.74 | 1421.51| **+0.27%** | 78 | 1 | 1.0 | 12:03 |
| LYG    |    5.57 |   5.55 | -0.27% | 73 | 1 | 1.0 | 10:59 |
| RRX    |  204.94 | 204.21 | -0.36% | 74 | 1 | 1.0 | 12:03 |
| META   |  627.80 | 612.69 | **-2.41%** | 78 | 1 | 1.0 | 12:59 |

- **Realized P&L today:** +0.00% (0 closed trades)
- **Unrealized P&L:** avg **-0.47%**, total **-2.35%**
- **Winners:** 2 / 5 (40%)
- **Best:** LTM +0.42%   **Worst:** META -2.41%

### Incidents

**1. META slow bleed (-2.41% in 3h since entry)**
- What: META opened at $627.80 at 12:59 ET (after the 16:56 UTC manual scan). By 14:45 ET it was already at -2.13%. As of 15:55 ET, it's been bouncing between -2.34% and -2.81% for 75 minutes. 13 watchdog ALERT events fired on META alone.
- Why we bought it: Tier 1 validated AI signal, score 78 (top of today's stack), bullish sentiment 65, MACD histogram **negative (-19.66)**, vs SMA200 -8% (not stretched).
- What's worrying: We bought a SAFE_INCOME pick whose **MACD histogram was already negative** at entry. The momentum was rolling over before we hit BUY. AI validation didn't catch this -- the score model doesn't penalize negative MACD histogram on the bucket where we land most often.
- Watchdog action: All 13 events = `action="warned"` -- the slow_bleed_exit threshold (-3.0%) has not yet been crossed. Sentiment stayed bullish (55-75) so the watchdog correctly held instead of panicking.
- Status: OPEN, monitoring. If META prints -3.0% the brain will likely auto-sell.
- Verdict: **TBD** -- watchdog rules are working as designed. The question is whether the *entry* should have happened at all.

**2. Late entries -- brain bought mid-day after the move**
- What: First brain buys at 10:59 ET (90 min after open), last buy at 12:59 ET. The 10:00 ET MORNING scan completed but did not produce brain entries -- the 10:56 ET MANUAL scan did.
- Why this matters: Buying 90+ minutes into the session means the early-day move is already priced in. By 12:59 ET (META entry), we're in lunchtime chop where reversals start. META's -2.4% bleed began within minutes of entry.
- Hypothesis: Either (a) the 10:00 ET scan's signals weren't yet BUY (scores climbed during the morning), or (b) tier qualification failed at 10:00 and only passed at 10:56. Need to log scan-by-scan tier evaluations to confirm.
- Status: NEEDS INVESTIGATION
- Verdict: TBD

**3. Score ceiling stuck at 78 -- Tier 2 and Tier 3 are dead branches**
- What: 0 signals at score 82+. 46 signals in the 72-81 band. The brain's Tier 2 (80+, low-confidence AI) and Tier 3 (82+, tech-only) gates produced **zero picks**. Only Tier 1 (validated AI, 72+) is firing.
- Why this matters: The 3-tier model exists to widen the brain's net. If only Tier 1 ever fires, we're effectively running a 1-tier model and the brain's daily pick count is hard-capped at "however many tickers Claude validated today" (today: 5).
- Pattern across Days 1-3: zero signals at 80+ score on any day so far. Either the scoring weights need recalibration (the +6 quality bonus and short-squeeze bonus aren't pushing anything past 80), or the universe genuinely lacks 80+ setups in this regime.
- Status: PATTERN
- Suggested fix: Inspect why zero signals reach 80+. Check the scorer ceiling logic and whether there's a quiet cap somewhere.

**4. Near-miss cluster at score 67 (16 signals)**
- What: SEI, LYB, SQQQ, TQQQ, CCL, CUK all clustered at 67 -- five points below the 72 floor. Several are validated AI BUYs.
- Why this matters: A 5-point gap between "AI says BUY" and "brain agrees" is large. If those tickers later print winners we should know -- the journal already noted "low_confidence_guard" was applied (raised confidence floor 40->50%) on Day 1 which may have pushed scores down.
- Status: OBSERVATION
- Suggested fix: Track the 7d outcome of the 67-cluster as a control group. If they outperform our actual picks, the floor is too high.

**5. Watchdog cooldown not visibly reducing META alert spam**
- What: 13 alerts in 75 minutes = one every ~5 min. Day 2 added a "3 bullish holds -> 1hr cooldown" rule. Either the rule isn't activating on bleed events (only on HOLD_THROUGH_DIP), or the cooldown counter resets when P&L crosses thresholds.
- Status: NEEDS INVESTIGATION
- Verdict: TBD

### Patterns Observed

**1. Three-day SAFE_INCOME monoculture continues**
- Day 1: 10/10 brain picks SAFE_INCOME
- Day 2: 11/11 brain picks SAFE_INCOME
- Day 3: 5/5 brain picks SAFE_INCOME
- 26 brain picks across 3 days, **zero HIGH_RISK**. The VIX-VOLATILE regime adjustment (-15% on HIGH_RISK scores) is too punishing -- it makes the bucket statistically inaccessible during volatile months.

**2. Marginal entries (score 72-74) keep losing**
- Day 2: PYPL (score 72) closed -3.0%
- Day 3: LYG (73), RRX (74) currently red; LTM (72) flat
- Day 3: META (78) is the worst loser today -- score is NOT the protective signal we assumed

**3. AI validation is not catching deteriorating momentum**
- META was validated at score 78 with `macd_histogram = -19.66`. Negative MACD histogram = momentum is rolling over. The scorer didn't flag it. The AI didn't downgrade it. The brain bought it. Within 2 hours it was -2.4%.
- This is a **scoring model gap**: SAFE_INCOME bucket weights fundamentals heavily and treats MACD histogram as a tiebreaker, not a blocker. For mega-cap tech (META, ASML), momentum reversal is a much stronger signal than dividend yield.

**4. Brain is buying late, not early**
- All 5 entries between 10:59 ET and 12:59 ET. The PRE_MARKET scan at 06:00 ET produces signals but the brain can't act outside RTH. By the time market opens, the brain has to re-validate during the MORNING scan -- and apparently the first MORNING scan (10:00 ET) didn't qualify any of today's picks. We need 60+ minutes after open before tier 1 fires. That's a structural lag that costs us the morning move.

**5. Discovery still finds nothing brain-quality**
- 8 scans, 0 GEMs, 0 picks above score 78. Discovery yield remains at the level Day 1 noted: lots of tickers added, none reach the brain's bar.

### Why Are We Losing? (Day 3 answer to Pedro's question)

We're not losing big -- we're bleeding **-0.47% on average across 5 fresh positions**, with one outsized loser (META -2.41%) dragging the basket. Specifically:

1. **META is the only material loss.** Without META, the basket is approximately flat (+0.02% avg across the other 4). One bad pick is dragging the whole day.
2. **The bad pick was a "good" score.** META had score 78 (top of today's stack) and validated AI -- it should have been our highest-conviction trade. It's the worst loser. **Score is not predicting outcome.**
3. **The bad pick had a visible warning sign that we ignored.** MACD histogram = -19.66 at entry. Momentum was already breaking down. The scoring model treats this as ~10% weight; we should treat it as a hard blocker for SAFE_INCOME picks above $200 share price.
4. **Late entry compounded the damage.** META was bought 3.5h after open, when the bounce had faded.

### Why Didn't We Pick "Better" Things?

We picked **everything we were allowed to pick.** The brain's tier gates produced exactly 5 unique tickers. The bottleneck is upstream:

1. **Scoring ceiling is stuck below 80.** Three days, zero signals at 80+. Tier 2 and Tier 3 contributed zero picks. The brain has only one effective gate (Tier 1) and only acts on whatever Claude validates above 72.
2. **Universe cap.** 408 tickers scanned, but only 33 got `validated` AI status -- that's the top-15-per-scan cap × 8 scans, minus dedupe and downgrades. Of those 33, only 5 unique symbols passed Tier 1. Widening the AI cap would add candidates.
3. **Regime suppression.** VOLATILE VIX = HIGH_RISK score penalty = no momentum picks. We've been entirely defensive for 3 days.
4. **No GEM conditions met.** 0 GEMs across 24 scans (Days 1-3 combined). The 85+ score + bullish sentiment + catalyst combo is statistically rare in this regime.

### What Can We Learn From Today?

**Actionable for Day 4:**

1. **Add a MACD histogram blocker for SAFE_INCOME large caps.** If `share_price > $100` AND `macd_histogram < -5` AND `bucket == SAFE_INCOME` -> downgrade BUY to HOLD. META and ASML would have both been HOLD; only LTM/LYG/RRX would have entered. We'd be holding less, but cleaner.
2. **Investigate why the 10:00 ET MORNING scan didn't produce brain entries.** Log per-scan tier evaluation results so we can see whether the issue is "signals weren't BUY yet" or "tier eval rejected them at that hour".
3. **Stop trusting "score 78" as protection.** Three days of data: the worst losers (PYPL, META) had middle-of-the-pack scores, not the lowest. The score-to-outcome correlation is weak in the 72-78 band. Either calibrate the scorer or stop treating 5-point score gaps as meaningful.
4. **Get the 80+ ceiling unstuck.** Audit the scorer for an unexpected ceiling -- with quality bonus (+6), short squeeze bonus (+up to 20), and momentum bonus (+6), at least *some* tickers should reach 80. None have. Find the cap.
5. **Confirm the virtual_trades wipe was intentional.** If accidental, we need a backup/audit trail. If intentional, document why.

**Lower-priority observations:**

6. The watchdog correctly held META through 13 -2.x% prints with bullish sentiment. The slow-bleed rule is working. Don't change it.
7. The "near-miss" cluster at score 67 is worth tracking as a control group -- if those tickers outperform our score-72+ picks over 7 days, the floor is too high.
8. No HIGH_RISK picks for 3 days running. Either accept that volatile regimes mean defensive-only, or unwind the -15% regime penalty on HIGH_RISK and let the brain take some momentum bets.

### Metrics to Track Tomorrow

- [ ] Did META auto-sell at -3.0% or recover?
- [ ] Did the 10:00 ET MORNING scan produce brain entries? (Log times of all brain buys)
- [ ] Any signal score 80+? (Count daily until this changes)
- [ ] Score distribution for the 67-cluster -- did SEI/LYB/etc. recover to 72+ on Day 4?
- [ ] Did watchdog cooldown reduce META alert frequency?
- [ ] Avg P&L of open brain positions at end of Day 4

### Brain Knowledge / Rules Suggestions (Day 3)

| Suggestion | Confidence | Status | Rationale |
|-----------|-----------|--------|-----------|
| **Three-witness consensus engine** (replaces tier gate) | **95%** | **APPROVED -- BUILDING NOW** | Day 3 META loss proved single-witness gate is broken |
| MACD histogram blocker for SAFE_INCOME large caps | 75% | SUBSUMED | Will be encoded as a Math-witness veto inside the consensus engine |
| Investigate Tier 2/3 starvation (no 80+ signals in 3 days) | 90% | DEFERRED | Consensus engine removes the tier model entirely |
| Audit late-entry pattern (no brain buys before ~11:00 ET) | 70% | PROPOSED | Costs us the morning move |
| Unwind HIGH_RISK regime penalty during VOLATILE | 40% | WAIT | 3 days isn't enough; HIGH_RISK lower win rate per backtest |
| Track score-67 cluster as control group | 60% | PROPOSED | If they outperform, our floor is too high |

### Architectural Insight -- Three-Witness Consensus

Pedro flagged a fundamental architecture problem after seeing today's META loss: **the brain trusts AI as the gatekeeper.** If Claude says "validated", we go to Tier 1 and buy. The math (formulas) and the knowledge (brain rules) are just inputs that fed Claude -- they don't get an independent vote at the gate. That's why META was bought at score 78 even though MACD histogram = -19.66 and Day 2's PYPL lesson said "marginal entries during VOLATILE bleed".

**The principle (saved as `feedback_three_witness_consensus.md` in memory):**

The brain has three independent witnesses for every decision -- AI, Math, Knowledge -- and no single witness should dominate. When witnesses disagree, the disagreement *itself* is the most important data point. The brain must understand *why* they disagree before acting.

Pedro's gun analogy makes the bidirectional point: a man would never normally shoot, but if his kids are being attacked he must -- context overrides default rules. The brain needs the same flexibility:

  - **Veto direction:** when the default rule says BUY but witnesses disagree, the brain holds fire even though the gate would normally let it through. (META today.)
  - **Override direction:** when the default rule says HOLD (e.g., score below 72 floor) but witnesses align on a hard catalyst, the brain takes a small position even though the gate would normally block it. (Score-67 cluster like SEI/LYB if a catalyst lights up.)

**How META would have been blocked under consensus:**

| Witness | Reading on META | Verdict |
|---------|------------------|---------|
| AI (Claude) | Score 78, validated, sentiment bullish 65 | BUY |
| Math (MACD histogram) | -19.66 -- momentum rolled over | AVOID |
| Math (vs SMA200) | -8% -- below trend, weak structure | AVOID |
| Knowledge (PYPL pattern) | Marginal-pick bleed in VOLATILE regime | AVOID |

3 of 4 readings against. Consensus engine vetoes. We'd be holding 4 positions today instead of 5, and the bleeding one would be the one we didn't take.

**Build plan:**

1. New module `back-end/app/ai/consensus.py` -- `evaluate_consensus(sig: dict) -> ConsensusResult` returning `(action, position_size_multiplier, witness_votes, reasoning)`.
2. Three witness functions:
   - `_ai_witness(sig)` -- reads `ai_status`, Claude confidence, sentiment score from grok_data
   - `_math_witness(sig)` -- reads technical_data (RSI, MACD histogram + direction, vs_sma200, volume z-score, ADX) and applies hard vetoes
   - `_knowledge_witness(sig)` -- queries `signal_knowledge` and recent `virtual_trades` outcomes for matching patterns
3. Decision matrix:
   - 3/3 agree positive -> full position, lower score floor to 70
   - 2/3 agree positive AND no strong negative -> half position
   - 2/3 agree positive AND one strong negative -> BLOCK (the META fix)
   - 1/3 agree -> BLOCK
   - 2/3 disagree but Math screams positive (vol z-score >= 2 + RSI sweet spot + catalyst <= 7d) -> 1/4-size override entry (the gun-analogy case)
4. Hard vetoes encoded as Math-witness rules:
   - `macd_histogram < -5 AND bucket == SAFE_INCOME AND share_price > 100` (the META blocker)
   - `rsi > 75` (already exists but explicit here)
   - `vs_sma200 > 30 AND ai_status != validated` (overextended without AI cover)
5. Replace call site at `app/services/virtual_portfolio.py:884` -- `_eval_brain_trust_tier` becomes `evaluate_consensus`.
6. **Shadow mode first:** run both gates in parallel for 7 days, log every disagreement to a new `consensus_disagreements` table, do not actually swap until backtest + shadow agree it's better.
7. Backtest the consensus engine against the existing tier gate over the 18,759-signal historical dataset. Reject if 10d/20d win rate or avg return regresses.

**Why this matters more than the individual rule tweaks:** The MACD blocker, the Tier 2/3 audit, the late-entry investigation -- they're all symptoms of the same disease. The brain has *no mechanism* to weigh disagreeing witnesses today. Every fix we ship in the current architecture is a band-aid on the wrong wound. Consensus engine is the correct surgery.

---

## Template for Future Days

### Day N -- [Date]

**Environment:** [regime, VIX, scans count, budget]

**Incidents:**
1. [What happened, root cause, fix, status, verdict]

**Patterns:** [Recurring observations]

**Fixes Applied:** [What was changed]

**Backtest comparison:** [Did metrics improve from previous backtest?]

**Metrics:** [Did yesterday's fixes work?]
