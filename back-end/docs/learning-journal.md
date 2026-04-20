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

## Day 4 -- April 9, 2026 — MORNING SNAPSHOT (end-of-day entry to follow)

**The day the learning loop went live.** This section captures the events from market open through ~10:30 ET: commit deploy, backend restart, first-ever THESIS_INVALIDATED exit on CRM, the re-buy edge case resolved by Stage 2 warning signs, PBR-A opened as the first fully Stage-6-tracked position. A second end-of-day entry will be added tonight to capture: how PBR-A + the 5 legacy positions move through the day, any additional brain buys/closes, UI bug fixes, and the day's overall P&L.

### Environment
- Market: VOLATILE (VIX 21.18 at 10:00, 21.01 at 10:10 — elevated but cooling)
- Regime: VOLATILE
- Fear & Greed: 34.4 (fear)
- Scans: 2 full + 1 partial stuck (see incident #1)
- Brain positions: 5 pre-Stage-6 legacy (LYG, LTM, ASML, RRX, META) + 1 new Stage 6-tracked (PBR-A)
- Commit in production: `1ac7c3a` (the Stage 1-7 learning loop)
- Backend restart: ~10am ET to load the new code

### Morning operational sequence

1. **Backend restarted** to load commit 1ac7c3a. The previous uvicorn process had yesterday's pre-commit code in memory; without a restart, all the learning-loop code would sit on disk unused.
2. **Stuck `PRE_MARKET` scan cleanup** — the 6am PRE_MARKET scan had been killed mid-run during the restart. Its row stayed in `RUNNING` status, blocking the concurrency guard. Manually marked as FAILED via a direct Supabase UPDATE. See Day 2 incident #5 for the pattern; it recurred on Day 4 morning. Runbook is in the `feedback_stuck_scans_manual_cleanup.md` memory file now.
3. **First manual scan triggered** after cleanup (labeled MANUAL internally).
4. **Scheduled MORNING scan auto-fired** at 10:09 right after the manual scan completed, because APScheduler had queued it during the stuck-scan block.

### Incidents

**1. Stuck PRE_MARKET scan from restart (resolved)**
- What: After restart, the old 6am PRE_MARKET scan was still marked `RUNNING` in the `scans` table. Its process was long dead.
- Root cause: scan_service starts a scan row with `status='RUNNING'` at the top of `run_scan()`, updates it to `COMPLETE` at the end. When the process gets SIGKILL'd mid-scan (as during a restart), the `COMPLETE` update never runs.
- Fix applied: Manually marked as FAILED via direct DB update.
- Status: CLOSED. Runbook saved to memory.
- Verdict: Fix works. Long-term idea noted: startup sweep that auto-fails RUNNING scans older than 30 min.

**2. THESIS_INVALIDATED exit fires on CRM within 23 seconds of entry**

This is the crown jewel of Day 4 — the first time Stage 6 thesis tracking has ever run on real data in production, and it worked exactly as designed.

- **10:07:38 ET** — Brain opens CRM at $169.48 (score 77, Tier 1 validated, Claude Local synthesis). `entry_thesis` captured at insert time (first ever).

  Claude's entry thesis (verbatim from the DB):
  > *"CRM's forward P/E of 11.38 and 17.9% EPS growth make valuation compelling, but the stock is in a confirmed structural downtrend — 28% below the 200-day SMA with deeply negative MACD histogram (-4.20) and multi-timeframe weakness. Backtest findings show RSI below 30 is falling-knife territory with worse-than-average returns..."*

  **Claude literally wrote its own warning INTO the buy thesis.** It approved the trade on valuation + growth but explicitly flagged the downtrend in the same paragraph. The Stage 6 `entry_thesis_keywords` captured: RSI 30.5, MACD histogram -4.1972, vs_sma200 -27.96, regime VOLATILE, fear_greed 34.

- **10:07:38 ET** — Brain also opens PBR-A at $19.02 (score 76, Tier 1 validated). Different thesis — genuinely bullish on fundamentals (P/E 6.1, 8% yield) and positive momentum (MACD histogram +0.85, RSI sweet spot 65).

- **10:07:40 ET** — Thesis tracker runs on all 6 open brain positions. Correctly skips the 5 pre-Stage-6 legacy trades (LYG, LTM, ASML, RRX, META) because their `entry_thesis` is NULL. Runs parallel Claude re-evals (`asyncio.gather`, semaphore=3) on the 2 new trades.

- **10:07:53 ET** — PBR-A thesis: `valid, confidence=62`. Claude agrees the reason still holds. Hold.

- **10:08:01 ET** — **CRM thesis: `invalid, confidence=85`.** Claude re-read its own entry reasoning and immediately called it out:
  > *"The original thesis explicitly warned against entry at these conditions — it noted RSI below 30 is falling-knife territory per backtest data, the VOLATILE-regime hypothesis warns negative MACD histogr..."*

  **Claude disagreed with itself at confidence 85 within 23 seconds of the original buy.**

- **10:08:01 ET** — `THESIS_INVALIDATED` exit fires. CRM closed at $169.61. P&L: **+0.08%**. Did not lose money, did not wait for a drawdown, did not need a stop-loss or target to trigger. The brain sold a position that was technically still green because the reason for owning was gone. This is the **oil-barrel exit in action**.

- **Audit trail** (from `knowledge_events` table):
  - `thesis_evaluated` × 2 (PBR-A valid, CRM invalid) — `triggered_by=thesis_tracker`
  - `thesis_invalidated_exit` — linked to the CRM trade id, full Claude reasoning preserved
  - `thinking_observation_added [neutral]` — the CRM close was matched against the PYPL/META hypothesis pattern and incremented `observations_neutral: 0 → 1`. Correctly classified as neutral because +0.08% is inside the ±1% deadband. The hypothesis counter didn't move toward graduation or rejection — correct behavior for a sub-deadband close.
- Root cause (of the buy in the first place): Claude's entry synthesis weighted the compelling valuation higher than the structural downtrend warning it wrote into the same paragraph. The score-77 Tier 1 gate passed. Stage 2 warning signs were present in the prompt but didn't override Claude's BUY confidence at entry.
- Fix applied: None needed — this is **exactly how the learning loop is designed to work**. The buy passed the gate, the re-eval caught the contradiction, and the exit fired with confidence.
- Status: WORKING AS DESIGNED
- Verdict: Stage 6 is operational. Every sub-stage (thesis capture, parallel re-eval, confidence floor, exit execution, audit log, hypothesis observation) fired correctly and in order.

**3. Edge case: would the brain re-buy CRM on the very next scan?**

- 10:09:58 ET — Scheduled MORNING scan auto-fires. CRM is in the top-15 AI candidates again (same score 77). Would the brain open ANOTHER CRM position?
- What happened: Claude's analysis for CRM on this scan returned **HOLD with confidence 42** (was BUY at confidence 58 in the previous scan 2 minutes earlier).
- Claude's new reasoning (quoted):
  > *"CRM is in a structural downtrend with multi-timeframe weakness confirmed: price 27.9% below SMA200, deeply negative MACD histogram (-4.20), and RSI at 30.6 which backtest data flags as falling-knife territory rather than a reliable reversal zone..."*
- Between the two scans, Claude's conclusion went from *"downtrend flagged but valuation wins"* to *"downtrend dominates, hold"*. The content of the warning flags hadn't changed (same MACD, same SMA200 distance). **What changed was Claude's reasoning weight.** The Stage 2 warning signs prompt section was present in both scans — the second time, Claude actually prioritized the warnings it named.
- The confidence drop from 58 → 42 pushed it below the 50 threshold, triggering the AI quality guard in `scan_service._process_candidate` which downgraded BUY to HOLD. Brain did NOT re-enter CRM.
- **Verdict: Self-correcting edge case.** The brain didn't need a cooldown or a "recently-closed" block — Claude's own fresh analysis converged on the right answer. This is a great proof point that the warning signs are actually changing model behavior.
- Future note: if this pattern (buy → invalidate → buy → invalidate loop) ever actually happens in practice, add a recently-closed cooldown (e.g., block re-buys of the same symbol for 60 minutes after THESIS_INVALIDATED). Not needed today.

**4. PBR-A tracked cleanly across 2 re-evaluations**

- 10:08:01 re-eval: `valid, confidence=62`. Reason: "position is 0 days old, conditions match entry, regime stable".
- 10:13:08 re-eval (MORNING scan): `valid, confidence=72`. Claude is MORE confident on the second look (confidence up 10 points).
- Both re-evals logged as `thesis_evaluated` events. `thesis_last_status`, `thesis_last_reason`, `thesis_last_checked_at` all updated on the virtual_trades row.
- Position still open at end of day.
- **Verdict:** First fully-Stage-6-tracked brain position is stable. Thesis gate running every scan with no issues.

### UI bugs noticed at end of day

- **Fear & Greed card on dashboard empty** — macro scanner is populating F&G (logs show `score=34.4, label=fear`) but the UI card shows blank dashes. Frontend is not reading the field from the stats API. Needs investigation next session.
- **Closed trades row on brain performance page is sparse** — only shows symbol + exit_reason + P&L %. Missing entry price, exit price, dates. The `trade_outcomes` row has all the data; the frontend isn't rendering it. Needs investigation next session.

### Patterns observed

**1. Claude can disagree with itself on fresh input**
The CRM round-trip (23 seconds, entry thesis to invalidation) proves that when Claude re-reads its own prior reasoning with the same data, it can reach a different conclusion. This is desirable — the thesis tracker catches cases where the entry decision was inconsistent with the evidence it was given. The counter-intuitive lesson: don't trust a single AI call; let the loop run it twice.

**2. The Stage 2 warning signs prompt section demonstrably changes model output**
CRM's second analysis (HOLD confidence 42) explicitly quoted the Stage 2 warning phrasing ("multi-timeframe weakness confirmed", "falling-knife territory"). The first analysis (BUY confidence 58) mentioned the same technical facts but weighted them below the valuation argument. Same warnings, different weighting. **The prompt placement (just before "Your Task") and phrasing matter.**

**3. Claude Local handles the re-eval load for free**
Plan budgeted ~$0.48/day for thesis re-evals via paid Claude API. Actual cost: $0.00. Claude Local CLI handled all calls. The `_run_claude_cli` helper (R3 refactor) is the path every re-eval takes.

**4. Parallel thesis re-evals work as designed**
`asyncio.gather(*, return_exceptions=True)` with `Semaphore(3)` ran 2 concurrent re-evals in ~8 seconds each (partially overlapping). For 5-10 open positions this would be ~30-50 seconds total instead of 2-5 minutes sequential.

### Metrics

| Metric | Value |
|--------|-------|
| Commit | 1ac7c3a |
| Files changed | 32 |
| Lines added | 4017 |
| Lines removed | 188 |
| Pre-test bugs caught (3 review passes) | 14 |
| Post-deploy bugs caught (real scan) | 0 |
| First THESIS_INVALIDATED exit duration | 23 seconds |
| First THESIS_INVALIDATED P&L | +0.08% |
| knowledge_events rows written on Day 4 | 5 |
| Brain trust tier breakdown now in UI | T1: 6 open / 1 closed 100% / +0.1% avg |
| Current brain positions | 6 (5 legacy + 1 Stage 6-tracked) |
| Paid Claude API cost for Stage 6 re-evals | $0.00 |

### Learnings for Brain

1. **The "AI is the decider, not a witness" principle works in practice.** The learning loop feeds Claude a better dossier and re-asks the question; it never overrides the answer. CRM was caught because Claude re-evaluated its own reasoning, not because math or a hard rule vetoed the trade.
2. **Entry thesis capture is load-bearing.** Without the verbatim reasoning stored on the trade row, the re-eval has nothing to check against. Every future brain buy MUST flow through `_extract_thesis_keywords` + `entry_thesis` capture.
3. **The ±1% deadband on `_classify_observation` is correct.** The CRM +0.08% close was correctly classified as neutral (not supporting). Real directional evidence comes from trades that actually move.
4. **Confidence floor 60 is holding up.** CRM was closed at confidence 85 (far above floor). PBR-A was held at 62/72 (above floor but not triggering exit because status=valid). No false positives so far from the floor.
5. **Don't need a "recently-closed cooldown" yet.** The edge case (re-buy same ticker) was handled automatically by Claude's next analysis. If the loop starts churning in production, add the cooldown. Not now.

### Metrics to Track Tomorrow

- [ ] Does PBR-A accumulate more thesis re-evals cleanly? Does its confidence stay stable?
- [ ] Any new brain buys? All new positions should have `entry_thesis` captured.
- [ ] Does the hypothesis counter ever move OUT of the deadband? Need a trade that moves >1%.
- [ ] Does the watchdog fire on PBR-A (the only Stage 6-tracked position)? What happens if it triggers?
- [ ] UI bugs: fix fear-and-greed card + closed trades display
- [ ] Does the Midday 12:00 scheduled scan fire cleanly and run the full loop again?

---

## Day 4 -- April 9, 2026 — END-OF-DAY ENTRY

**The day Claude's non-determinism became impossible to ignore.** The morning entry above captures the celebratory side: Stage 1-7 went live, the first THESIS_INVALIDATED exit fired on CRM in 23 seconds, PBR-A opened cleanly. The afternoon and evening tell the harder story: 7 brain buys, 4 closes (3 thesis-invalidations, 1 watchdog), one stock (BF-B) bought twice and closed twice, one architectural mistake by me that I had to revert, and an audit that pinpointed exactly where the scan pipeline is wasting 80+ seconds.

### End-of-day numbers

| Metric | Value |
|---|---|
| Scans run today | 14 (12 COMPLETE, 2 FAILED — both stuck PRE_CLOSEs cleaned up manually) |
| Brain BUYs today | 7 (CRM, PBR-A, WING ×2, BF-B ×2, VSEC) |
| Brain closes today | 4 (3 THESIS_INVALIDATED + 1 WATCHDOG_EXIT) |
| THESIS_INVALIDATED exits | 3 — CRM (+0.08%), WING #1 (-0.07%), BF-B #2 (+0.13%) |
| WATCHDOG_EXIT | BF-B #1 (-2.29%) |
| OPEN brain positions at EOD | 8 |
| Avg live P&L on open positions | +0.35% (skewed positive by 5 legacy positions: ASML +2.18%, RRX +1.32%, LTM +1.30%, LYG +0.54%, META +0.09%) |
| Stage 6-tracked positions still open | PBR-A -0.68%, VSEC -1.55%, WING #2 -0.38% — all underwater |
| knowledge_events written | 36 (1 thinking_created, 30 thesis_evaluated, 2 thinking_observation_added, 3 thesis_invalidated_exit) |

### Incidents (continued from morning)

**5. UI bug: Fear & Greed card empty on the dashboard**
- What: Macro scanner was correctly populating F&G (`score=34.4 label=fear` in the logs) but the dashboard card showed blank dashes.
- Root cause: `DailyStatsResponse` Pydantic `response_model` was missing a `fear_greed` field. **FastAPI silently strips any field not declared on the response model**, so the backend was computing the value, returning it from the handler, and Pydantic was throwing it away on the way out.
- Fix applied: Added `FearGreedDetail` and `fear_greed` field to `app/models/stats.py`. Also saved the lesson to memory as `feedback_fastapi_response_model_strips_fields.md` so this isn't re-derived next time.
- Status: APPLIED + verified live
- Verdict: WORKING

**6. UI bug: Closed Trades row showing only symbol + reason + P&L%**
- What: The brain performance page's "Closed Trades" widget showed sparse rows missing entry/exit price and dates. The data exists in `trade_outcomes` and `virtual_trades`; the frontend just wasn't getting it.
- Root cause: The `recent_closed` builder in stats was dropping `entry_date`/`exit_date`/`entry_price`/`exit_price` from the emitted rows.
- Fix applied: Added the missing fields to the builder.
- Status: APPLIED
- Verdict: WORKING

**7. UI bug: Track Record by Score not updating after a close**
- What: After a brain trade closed, the dashboard's "Brain Performance" card updated immediately (live query), but "Track Record by Score" stayed stuck on the old numbers for ~1 hour.
- Root cause: `signal_service.get_track_record()` had a 1-hour TTL cache. The Brain Performance card uses a different code path (no cache), so the two displays drifted out of sync until the cache expired.
- Fix applied: Lowered TTL from 3600s → 900s, added `invalidate_track_record_cache()` helper, called it from every brain close path so the table refreshes immediately.
- Status: APPLIED
- Verdict: WORKING

**8. CRITICAL: Pre-filter was excluding HELD brain positions on quiet days**
- What: PBR-A's thesis was supposed to be re-evaluated every scan, but on quieter days when its `day_change` was below the 1% threshold, the pre-filter would drop it from the candidate set entirely. Stage 6 then couldn't re-evaluate a position it never saw. **Stage 6 was silently broken.**
- Root cause: `prefilter.py` filtered everything by `day_change >= min_abs_change`, with no carve-out for symbols the brain currently holds.
- Fix applied: Added `held_brain_symbols` parameter to `prefilter_candidates()`. Held positions bypass the volume/change/price filters and are always included, sitting ADDITIVELY alongside watchlist tickers (don't eat into the 50-slot cap). Added `queries.get_open_brain_symbols()` helper. Wired through `scan_service.run_scan()`.
- Status: APPLIED
- Verdict: WORKING. PBR-A now appears in every scan and gets re-evaluated even on flat days.

**9. The non-determinism problem (the day's most important lesson)**

This is the headline finding of Day 4. Claude is **non-deterministic on borderline trades**. Same dossier, same data, different scan → BUY one time, HOLD the next.

Real cases observed today across the same 4-hour window:
- **CRM**: 4 signals — 3× HOLD (confidence 38, 42, 45) and 1× BUY (confidence 58). The BUY happened at 14:07; the brain bought it; Stage 6 invalidated it 17 seconds later.
- **WING**: 5+ signals — BUY confidence 78 at 17:05 (brain bought it #1), HOLD on later scans, then BUY again at 18:00 (brain bought it #2). WING #1 was invalidated; WING #2 is still open at -0.38%.
- **BF-B**: 4+ signals — BUY conf 72, HOLD, BUY conf 72 again. Brain bought it twice. BF-B #1 hit a watchdog exit at -2.29%; BF-B #2 was invalidated at +0.13%.
- **PBR-A**: across two consecutive scans the structured `self_check_notes` flipped from *"consistent with HOLD"* to *"unambiguously bullish — RSI in sweet spot, positive MACD momentum, strong valuation"*. Same underlying data. Same prompt. Different conclusion. This is the cleanest demonstration of the non-determinism we have on record.

**This is the upstream cause of every bad entry today.** The score-based gate doesn't see the inconsistency because it only sees one snapshot at a time. Stage 6 doesn't catch most of them because Stage 6 asks "have conditions changed since entry" — and the answer for an instantly-non-deterministic flip-flop is "no, conditions are identical, valid".

### Architectural mistake I made (and reverted)

Around mid-afternoon I built a "Claude HOLD ⇒ system HOLD" override in `scan_service._process_candidate`. The reasoning seemed clean: if Claude (the validated AI) says HOLD, we shouldn't override it with a score-derived BUY. I tested it against 9 cases, all passed.

Pedro pushed back immediately: *"but ai cannot win all the time, read the memories and the journal and the claude"*. Reading `feedback_three_witness_consensus.md` made the mistake obvious. The principle "AI is the decider" is about EXITS (Stage 6) and about FEEDING Claude a better dossier. It explicitly says **"do not build hard math vetoes that block trades regardless of the AI's view"** and **"do not build anything that treats math + knowledge as 'checks on' the AI rather than 'inputs to' the AI"** — and what I had built was the same shape, just inverted. A hard Claude-veto over the score-based gate.

Reverted within ~15 minutes. The lesson: **even when the data looks like it justifies a new gate, re-read the principle memory before building the gate.** Saved to memory afterward implicitly via this journal entry — the existing `feedback_three_witness_consensus.md` is the load-bearing principle, no new memory needed.

### What actually shipped today (after the revert)

| Build | What it does | Files |
|---|---|---|
| `## Self-Consistency Requirement` prompt section | Tells Claude not to generate BUY signals while writing reasoning that argues against the trade. First-line defense. | `prompts.py` |
| Bearish hedge phrase regex guard | Substring check on Claude's reasoning text when it says BUY — downgrades to HOLD if any of 38 bearish phrases appear. Whack-a-mole, retired in the next ship as the legacy fallback only. | `scan_service.py` |
| Structured `self_check` block in synthesis output | Forces Claude to answer 3 yes/no questions about its own reasoning consistency in the JSON response. Definitions, failure examples, and a correct-BUY example included in the prompt. | `prompts.py`, all 3 AI clients |
| Shared `normalize_synthesis_result()` + `synthesis_error_response()` helpers | Deduped ~150 LOC of copy-pasted result-builder dicts across `claude_client.py`, `claude_local_client.py`, `gemini_client.py`. Single source of truth for the synthesis schema. | `prompts.py` + 3 clients |
| Persisted `_self_check` in `grok_data` | Writes Claude's structured self-check to the signal record so post-hoc audits can answer "did Claude flag its own reasoning as bearish?" without re-running synthesis. Underscore-prefixed convention; `format_sentiment` ignores it. | `scan_service.py` |
| Persisted `_ai_signal` (Claude's raw signal field) in `grok_data` | The most important diagnostic add of the day. Without this we couldn't distinguish "Claude said BUY" from "Claude said HOLD but score won". Once persisted, the data showed Claude's signal matches the action 5/6 times — the score-override theory was wrong. | `scan_service.py` |
| **THESIS_INVALIDATED re-buy cooldown** | After a brain trade closes with `exit_reason='THESIS_INVALIDATED'`, the symbol is blocked from re-entry for 60 minutes (`brain_thesis_rebuy_cooldown_minutes` config). Loaded once per scan via a single DB query, applied at the brain BUY gate. The Day 4 morning journal explicitly predicted we'd need this within "Future note: if buy → invalidate → buy → invalidate ever happens in practice." Today it happened (WING). | `virtual_portfolio.py`, `config.py` |
| Stuck-scan cleanup runbook applied twice | PRE_MARKET scan stuck after morning restart, then PRE_CLOSE scans stuck after a later restart. Direct DB UPDATE to mark RUNNING → FAILED. Saved to memory as `feedback_stuck_scans_manual_cleanup.md` (already existed from morning). | `feedback_stuck_scans_manual_cleanup.md` |

### The Stage 6 gap (the most important unsolved problem)

Stage 6 thesis re-eval was designed with this question: *"Have conditions materially changed since entry?"* That correctly catches CRM-style cases where the original entry thesis literally contained its own warning ("falling knife with poor risk/reward") and Claude on re-eval reads its own warning and exits.

It does NOT catch the case where:
1. Entry was bad to begin with (bearish setup, Claude flipped to BUY on a non-deterministic moment)
2. Conditions haven't materially changed since entry
3. Stage 6 returns `valid` because *"unchanged from entry"* is its definition of valid
4. Claude on the latest scan says HOLD with bearish self_check

This is the live state of WING #2, BF-B #2 (before it was watchdog-killed), and VSEC right now. All `thesis_last_status: valid`. All bleeding. All would not be entered today from scratch.

The fix is conceptually clear but architecturally non-trivial: **add a second check to Stage 6 that asks "would I enter this position today, fresh, given the current data?"** If the answer is no, exit even though conditions are unchanged. Not built tonight — needs careful design (it's basically running the entry pipeline against the held position) and we just shipped a lot today. Logged here as the #1 thing to design in the morning.

### Performance audit (delivered by another Claude session, summarized here)

Anchor: most recent MORNING scan ran in **~302s** (305.32s wall clock).

The audit found **two structural bottlenecks**, not one:

1. **`Semaphore(3)` at `scan_service.py:814` is doing double duty** — protecting yfinance from DNS exhaustion AND gating Claude Local subprocess concurrency. Claude Local doesn't need gating; it's a free CLI subprocess and 15 in parallel should land in ~25-35s instead of the ~155s we see today. Single highest-leverage change in the codebase: split into `yfinance_sem = Semaphore(3)` + `ai_sem = Semaphore(6-10)`. One file, one function. Estimated savings: **80-110s**.

2. **PASS 1 yfinance data is not cached for PASS 2** — the top 15 candidates re-fetch `get_price_history(1y)` and `get_fundamentals` even though PASS 1 already pulled them. 30 duplicate yfinance calls, all stuck behind the same semaphore. Estimated savings: **25-45s**.

Three more wins on top (parallelize bulk-screening batches, overlap macro/grok phases with bulk-screen, cross-scan caching of bulk-screen output). Audit estimates **target post-fix: 70-100s on cold scans, 30-50s on warm scans**.

Critical preconditions before building:
- **Run sanity Checks A and B from §6 of the audit** — measure `yf.download(threads=True)` vs `threads=False`, and confirm 15 parallel `claude -p` subprocesses don't blow up the laptop. The whole plan rests on these two assumptions.
- **Build fix #1 first**, re-measure, then decide whether the rest is worth shipping. If #1 alone gets us to ~150s, we may not need the others.

NOT in scope tonight. Will review with fresh eyes and start with the sanity checks tomorrow.

### Patterns observed

**1. Non-determinism is the upstream cause of every bad entry today.** Every problem we tried to fix downstream (the regex guard, the structured self_check, the Claude-HOLD override I reverted) was a symptom. The root cause is that Claude returns different signals on near-identical inputs. The two real fixes for this are (a) cross-model verification — send Claude's BUY to Gemini and require agreement, or (b) make the entry decision over multiple Claude calls with majority voting. Both are bigger than tonight's appetite.

**2. Stage 6 catches CHANGES, not BAD STARTING POSITIONS.** Today's data made this gap visible for the first time. Need to design a quality-from-scratch check.

**3. The cooldown was correctly predicted by the Day 4 morning journal.** *"if this pattern (buy → invalidate → buy → invalidate loop) ever actually happens in practice, add a recently-closed cooldown."* It happened today (WING), the cooldown is now built and shipped, and the journal closing the loop on its own prediction is satisfying.

**4. UI bugs come in clusters when a backend feature ships.** Three separate UI bugs (F&G, closed trades, track record) all surfaced today as direct consequences of yesterday's brain learning loop ship. Watch for the pattern: every backend ship probably has a frontend follow-up.

**5. Always re-read the principle memories before adding a new gate.** The "Claude HOLD wins" override I almost shipped would have violated `feedback_three_witness_consensus.md` directly. Pedro caught it within seconds; the lesson is to NOT have to be caught.

### Wins I want to keep in mind

- **3 THESIS_INVALIDATED exits today** (CRM, WING #1, BF-B #2). All three exited near-flat (+0.08%, -0.07%, +0.13%). Stage 6 is doing real work.
- **The legacy positions are quietly winning.** ASML +2.18%, RRX +1.32%, LTM +1.30%. The brain's pre-Stage-6 picks from yesterday are positive across the board.
- **`_ai_signal` persistence settled the architectural debate.** Without it I would still be guessing whether the score was overriding Claude. Once persisted, the data showed 5/6 match. I had been chasing a phantom problem.
- **Three review passes and the review-passes memory continue to pay off.** Today's edits would have shipped with at least 2 dead-code patterns (`_safe_int` ghosts, `format_sentiment` import drift) without an end-of-edit cleanup pass.

### Metrics to track tomorrow

- [ ] Does the THESIS_INVALIDATED cooldown actually fire and block a re-entry? Need a Stage 6 exit followed by another scan within 60 min.
- [ ] How many of today's currently-OPEN bleeding positions (PBR-A, VSEC, WING #2) will Stage 6 catch overnight or in the morning scan?
- [ ] Apply perf audit fixes #1 and #2 after running sanity Checks A + B. Measure scan time before, after #1, after #2.
- [ ] Does the `_ai_signal` field show any new mismatches between Claude's signal and the system action? Watch for the score override pattern I thought existed.
- [ ] Design (NOT necessarily build) the Stage 6 absolute-quality check.
- [ ] Any new brain BUYs at scores 72-79 with bearish `self_check` flags? Those are the cases where we have good visibility now.

---

## Day 5 -- April 10, 2026

**First fully autonomous day.** Pedro didn't touch Signa once. The brain ran all 6 scheduled scans, opened 6 new positions, closed 2, and ended the day with 12 open positions at +7.75% combined live P&L. The AFTER_CLOSE scan had an AI provider degradation (11 of 16 candidates failed synthesis), but it was the only incident in an otherwise clean day.

### Environment
- Market: VOLATILE (continued from Day 4)
- Scans: 6 (MANUAL 3:19am, PRE_MARKET 10am, MORNING 2pm, MIDDAY 4pm, PRE_CLOSE 7pm, AFTER_CLOSE 8:30pm — all UTC)
- All scans COMPLETE — zero stuck, zero manual intervention required
- Budget: $0.00 paid (Claude Local handled nearly everything for free)
- Scan performance: avg **190s** vs Day 4's avg **308s** — **38% improvement** from yesterday's perf audit fixes

### Scan performance (the perf fixes delivered)

| Scan | Duration | Notes |
|---|---|---|
| MANUAL (3:19am) | 180s | Cold scan, no cache |
| PRE_MARKET (10am) | **159s** | Best of day. First real market-hours scan. |
| MORNING (2pm) | 208s | |
| MIDDAY (4pm) | 185s | |
| PRE_CLOSE (7pm) | 254s | Slowest — 58 candidates, higher ticker activity |
| AFTER_CLOSE (8:30pm) | 152s | Fastest but degraded — 11/16 AI synthesis failed |

Yesterday's 5 perf fixes are delivering:
- **Fix #1 (semaphore decouple):** `ai_sem=6` confirmed safe by Check B (6 parallel Claude CLI in 7.83s). The AI synthesis phase dropped from ~155s to ~30-40s.
- **Fix #2 (PASS 1 → PASS 2 cache):** ~30 duplicate yfinance calls eliminated per scan.
- **Fix #3 (parallel bulk-screening):** 3 concurrent batches instead of 21 sequential.
- **Fix #4 (phase overlap):** macro + knowledge load in parallel with screening.
- **Fix #5 (cross-scan cache):** TTL cache with market-hours awareness (15 min during session, 1 hr outside).

Range: 152s → 254s (vs yesterday's 223s → 330s). Even the worst scan today is better than the best scan yesterday.

### Incidents

**1. AFTER_CLOSE scan AI provider degradation**
- What: 11 of 16 AI candidates got `ai_status=failed` ("all AI providers failed or budget exceeded"). Only 2 validated, 3 low_confidence. The `ai_usage` table shows 5 paid Claude API calls attempted (5 failed, 4 succeeded). The remaining ~6 failures happened at the Claude Local CLI tier and weren't logged.
- Root cause (likely): Claude CLI rate limit or concurrency exhaustion. With 6 scans × 15 AI calls + thesis re-evals, the brain made ~100+ Claude CLI invocations on the day. The AFTER_CLOSE scan was the 6th — it's plausible the CLI has an undocumented per-hour or per-day soft cap. Alternatively, a concurrent Claude Code session may have been consuming CLI quota.
- Impact: Low. AFTER_CLOSE runs after market close — no trades execute from it. The failed tickers got tech-only signals, which is correct degraded behavior.
- Fix needed: Not urgent. If it recurs on in-session scans (PRE_MARKET, MORNING, MIDDAY, PRE_CLOSE), investigate CLI rate limits. For now, monitor.
- Status: OBSERVED — no fix applied
- Verdict: Acceptable degradation. The fallback chain worked correctly (Claude Local failed → Claude API attempted → some succeeded, some didn't → Gemini not reached for most). The worst outcome is slightly stale AI analysis for the after-hours scan, which doesn't affect trading.

### Brain trades

**Opened today (6):**

| Symbol | Score | Tier | Entry | Thesis summary |
|---|---|---|---|---|
| TPL | 85 | Tier 2 | $409.01 | Pullback play: 12.6% below SMA50, MACD -4.7, no reversal signs |
| LB | 80 | Tier 2 | $67.97 | Early momentum recovery: MACD turned positive, above SMA50 support |
| AVGO | 81 | Tier 1 | $368.65 | Strong EPS growth 31.6%, forward P/E 20.66, but overextended at 100% BB |
| AGI.TO | 81 | Tier 1 | $66.53 | Massive EPS growth 396%, RSI in sweet spot 59.4, above both SMAs |
| ASML #2 | 80 | Tier 2 | $1480.96 | Overextended at 100% BB, MACD bearish divergence, momentum rolled over |
| REGN | 79 | Tier 1 | $740.85 | Below SMA50, negative MACD, RSI 43.6, weakening short-term momentum |

**Notable:** First time Tier 2 picks appear (TPL, LB, ASML #2). Tier 2 = low_confidence AI + score >= 80. Higher average scores than Day 4 (avg 81 vs avg 74). Entry theses are being captured for all 6 — Stage 6 can track them.

**Thesis quality note:** AVGO and ASML #2 have entry theses that describe overextended/bearish setups — the same pattern as yesterday's BF-B/WING problem. The self_check didn't fire because Claude returned signal=BUY despite the bearish reasoning. Stage 6 will need to catch these if they turn bad.

**Closed today (2):**

| Symbol | Exit reason | P&L | Held since | Notes |
|---|---|---|---|---|
| **ASML #1** | **TARGET_HIT** | **+5.09%** | Apr 8 (2 days) | First ever target-hit exit. Bought $1417.74, target hit at $1489.90. Legacy position (no thesis tracking). |
| VSEC | WATCHDOG_EXIT | -3.18% | Apr 9 (1 day) | The bleeder flagged in yesterday's EOD journal. Stage 6 kept saying "valid" (conditions unchanged). Watchdog caught it. |

**ASML +5.09% is the brain's best trade to date.** It held for 2 days through the volatility and exited on a target hit. This is what the system is designed to do — score-based entry, price-based exit, no panic selling on noise.

**Realized P&L today: +1.91%** (sum of the two closes). Net positive despite the VSEC loss because ASML's win was 1.6x larger.

### Open positions at EOD (12)

| Symbol | Entry | Live | P&L | Score | Thesis | Entered |
|---|---|---|---|---|---|---|
| LTM | $52.42 | $53.20 | +1.49% | 72 | NULL/legacy | Apr 8 |
| LYG | $5.57 | $5.49 | -1.44% | 73 | NULL/legacy | Apr 8 |
| RRX | $204.94 | $208.33 | +1.65% | 74 | NULL/legacy | Apr 8 |
| META | $627.80 | $629.86 | +0.33% | 78 | NULL/legacy | Apr 8 |
| PBR-A | $19.02 | $19.55 | **+2.79%** | 76 | YES/valid | Apr 9 |
| WING | $179.73 | $179.89 | +0.09% | 74 | YES/valid | Apr 9 |
| TPL | $409.01 | $409.97 | +0.23% | 85 | YES/valid | Apr 10 |
| LB | $67.97 | $68.01 | +0.06% | 80 | YES/valid | Apr 10 |
| AVGO | $368.65 | $371.55 | +0.79% | 81 | YES/valid | Apr 10 |
| AGI.TO | $66.53 | $67.10 | +0.86% | 81 | YES/valid | Apr 10 |
| ASML #2 | $1480.96 | $1478.28 | -0.18% | 80 | YES/valid | Apr 10 |
| REGN | $740.85 | $748.87 | +1.08% | 79 | YES/valid | Apr 10 |

**Sum live P&L: +7.75%** | **Avg per position: +0.65%**

10 of 12 positions are green. Only LYG (-1.44%) and ASML #2 (-0.18%) are red. PBR-A (the first Stage 6-tracked position from yesterday) has recovered from -0.68% to +2.79% — a clean vindication of "hold through noise when the thesis is valid."

### Answering Day 4's metrics-to-track

- [x] **Does the THESIS_INVALIDATED cooldown fire?** Not tested — zero thesis-invalidation exits today. Cooldown is wired but unexercised.
- [x] **How many bleeding positions from yesterday recovered?** PBR-A: -0.68% → +2.79% (full recovery + profit). WING: -0.38% → +0.09% (recovered to flat). Both are green now.
- [x] **Perf audit fixes: scan time before/after?** 308s avg → 190s avg. PRE_MARKET best: 159s. Working.
- [x] **Does `_ai_signal` show new mismatches?** 2 mismatches on latest scan: LYG (action=BUY, Claude=HOLD — the same pattern from yesterday) and TVE.TO (action=HOLD, Claude=BUY — the reverse, interesting). Small sample, not alarming.
- [ ] **Stage 6 absolute-quality check design:** NOT started today. Deferred.
- [ ] **New BUYs with bearish self_check:** AVGO and ASML #2 have bearish entry theses but self_check didn't flag them. Same gap as before.

### Knowledge events

22 `thesis_evaluated` events across 5 scans. All returned `valid` — no invalidations today. The brain is holding its positions with conviction, and the positions are (mostly) rewarding that conviction.

### Patterns observed

**1. The brain is expanding its portfolio correctly.** Started the day at 8 positions, ended at 12. First time opening Tier 2 picks (TPL, LB, ASML #2). Average entry score today was 81 vs 74 yesterday — the brain is being more selective.

**2. ASML #1 TARGET_HIT +5.09% is the proof-of-concept trade.** Bought on Day 3 via score + validated AI, held 2 days through VOLATILE regime, exited on target. No thesis tracking (legacy position), no manual intervention. Score-based entry, price-based exit. The simplest path through the brain worked.

**3. Yesterday's bleeders recovered.** PBR-A went from -0.68% to +2.79%. WING went from -0.38% to +0.09%. Stage 6's "hold through noise when thesis is valid" is working — the brain didn't panic-sell, and the market came back.

**4. The AFTER_CLOSE AI degradation is a leading indicator.** If the Claude CLI has an undocumented daily rate limit, 6 scans/day with `ai_sem=6` (= up to 90 parallel CLI calls/day) might be close to the ceiling. If this recurs on in-session scans, we'll need to either lower `ai_sem` to 4 or space out scans differently. Watch this tomorrow.

**5. The brain is all SAFE_INCOME.** 12/12 open positions are SAFE_INCOME. Zero HIGH_RISK. Same pattern as Day 1. The brain's conservative bias is producing consistent green but not catching momentum plays. Not a bug — the SAFE_INCOME bucket has the higher backtest win rate (62% vs 57%). But worth noting for future diversification.

### Day 5 summary

| | Day 4 | Day 5 | Direction |
|---|---|---|---|
| Scans completed | 12 of 14 (2 stuck) | **6 of 6 (perfect)** | Better |
| Avg scan time | 308s | **190s** | **38% faster** |
| Brain BUYs | 7 | 6 | Stable |
| Brain closes | 4 | 2 | Fewer (holding longer) |
| Best trade | +0.13% (BF-B thesis inv.) | **+5.09% (ASML target hit)** | Much better |
| Worst trade | -2.29% (BF-B watchdog) | -3.18% (VSEC watchdog) | Slightly worse |
| Realized P&L | -2.15% | **+1.91%** | Positive for the first time |
| Open positions | 8 | **12** | Growing |
| Live portfolio P&L | +2.82% (avg +0.35%) | **+7.75% (avg +0.65%)** | Growing |
| THESIS_INVALIDATED exits | 3 | 0 | No bad entries today (or not caught yet) |
| Manual interventions | ~8 (manual scans, stuck cleans, code fixes) | **0** | Fully autonomous |

### Metrics to track tomorrow

- [ ] Does the AFTER_CLOSE AI failure recur? If it happens on an in-session scan, investigate Claude CLI rate limits.
- [ ] 12 open positions — has the brain hit brain_max_open? If so, is rotation logic activating?
- [ ] LYG is the only legacy position still red (-1.44%, Day 3 entry). Watch it — no thesis tracking, no Stage 6 protection. If it hits the watchdog threshold, it exits without thesis gate.
- [ ] AVGO and ASML #2 both entered with bearish entry theses. Will Stage 6 catch them if they start bleeding, or will it say "conditions unchanged = valid" (the same gap as VSEC)?
- [ ] Does the cooldown ever fire? Zero thesis-invalidation exits today = zero cooldown triggers. Need a real test.
- [ ] Day 5 was the first net-positive realized P&L day. Track whether Day 6 continues the trend.

---

## Day 7 -- April 13, 2026 (Monday — First Full Week Complete)

**First full week of autonomous operation.** The brain ran all 5 scheduled scans on its own, opened 3 new positions (including the first-ever crypto and HIGH_RISK entries), closed 1, and the portfolio hit +18.03% combined across 14 positions. One significant infrastructure issue discovered: FRED API completely down, leaving the brain blind to all macro fundamentals.

### Environment
- Market: TRENDING (VIX 19.13)
- Environment: favorable (but computed from VIX only — FRED is down)
- VIX term structure: contango at 0.896 (normal)
- Fear & Greed: 41 (fear)
- Scans: 5/5 COMPLETE (PRE_MARKET through AFTER_CLOSE), 188-214s range
- Budget: $0.00 paid (Claude Local handled everything)
- No manual interventions required

### Scan performance

| Scan | Duration |
|---|---|
| PRE_MARKET | 190s |
| MORNING | 192s |
| MIDDAY | 188s |
| PRE_CLOSE | 202s |
| AFTER_CLOSE | 214s |

Consistent ~190-210s range, matching the perf improvements from Day 5. No AI failures today — all scans got full AI synthesis.

### Incidents

**1. CRITICAL: FRED API completely down — ALL macro fundamentals returning None**

All 6 FRED series are returning None: `fed_funds_rate`, `treasury_10y`, `cpi_yoy`, `unemployment_rate`, `yield_curve_10y2y`, `credit_spread_bbb`. Only yfinance-based data (VIX, VIX term structure, intermarket) and CNN Fear & Greed are working.

Impact: `classify_macro_environment()` cannot detect hostile signals from yield curve inversion or credit spread stress. The environment defaults to "favorable" purely based on low VIX + normal VIX term structure. The brain is flying blind on macro fundamentals — fed funds rate, Treasury yields, CPI, unemployment are all invisible.

Root cause candidates:
- FRED API key expired or rate-limited (the key lives in `.env` as `FRED_API_KEY`)
- FRED itself is having an outage
- The `_fetch_fred_series` function is silently swallowing errors (it returns None on failure)

Ship 2's yield curve and credit spread data — the leading recession indicators we just wired up — have NEVER successfully reached Claude in a live market-hours scan because FRED went down at the same time or before we deployed.

**Status: NEEDS INVESTIGATION.** Check the FRED API key, test a manual fetch, add better logging to `_fetch_fred_series` so we can see WHY it's failing instead of just None.

**2. VZ bought at RSI 25.7 despite Claude saying HOLD on every signal today**

VZ's entry: score 73, Tier 1, SAFE_INCOME. But Claude returned `ai_signal=HOLD` with `self_check.bearish=True` on ALL 3 signals today. The self_check notes explicitly say "falling-knife territory" and "bearish descriptors present, consistent with HOLD signal rather than BUY."

How it got bought: the brain's tier model (`_eval_brain_trust_tier`) evaluates INDEPENDENTLY of the user-facing `action` field. It sees `ai_status=validated` + `score >= 72` → Tier 1 → buy. It does NOT check `_ai_signal` or `self_check`.

This is by design (the docstring in virtual_portfolio.py line 1243-1251 explicitly says the brain "bypasses that downgrade because its tier model has stricter criteria"). But VZ is a case where Claude is genuinely warning against the entry, not just being conservative on a borderline call.

**The question:** should the tier model check `_ai_signal`? If Claude explicitly said HOLD (not just low confidence), should the brain still override? Per the Day 4 principle ("AI cannot win all the time"), the answer was no. But VZ's thesis literally contains its own warning. Stage 6 will need to catch this via thesis re-eval — same pattern as CRM Day 4.

**Status: OBSERVATION.** Not changing the architecture. Stage 6 is tracking VZ. If the falling-knife plays out, thesis re-eval should catch it. VZ is currently +0.46% — early days.

**3. First ever crypto entry: ETH-USD (HIGH_RISK)**

ETH-USD entered at $2,252.33, score 73, Tier 1, HIGH_RISK bucket. This is the first HIGH_RISK position and the first crypto position the brain has ever held.

The thesis mentions "healthy short-term momentum with RSI at 58.1 in the sweet spot and strong MACD histogram of 22.22" but also "price pressing against upper Bollinger Band... sitting 23% below SMA200." Claude's latest signal is HOLD with `self_check.wait=True` — the brain entered on an earlier scan where Claude briefly said BUY.

Crypto implications:
- The crypto risk cap is active: stop floored at -8% from entry ($2,072)
- Crypto trades 24/7 — the watchdog monitors even on weekends (if `watchdog_weekend_crypto` is enabled)
- This is HIGH_RISK, so VOLATILE/CRISIS regime multipliers affect its score differently than the SAFE_INCOME positions

**Status: WATCHING.** First crypto position — important to see how the thesis tracker, trailing stop, and watchdog handle it over the next few days.

### Brain trades

**Opened (3):**

| Symbol | Score | Tier | Entry | Bucket | Thesis note |
|---|---|---|---|---|---|
| TSM | 81 | Tier 2 | $368.79 | SAFE_INCOME | Overextended at 94% BB, solid fundamentals |
| VZ | 73 | Tier 1 | $45.21 | SAFE_INCOME | Falling-knife RSI 25.7, compelling valuation |
| ETH-USD | 73 | Tier 1 | $2,252.33 | HIGH_RISK | Momentum in sweet spot, pressing BB resistance |

**Closed (1):**

| Symbol | Exit reason | P&L | Held since | Notes |
|---|---|---|---|---|
| LTM | WATCHDOG_EXIT | -1.24% | Apr 8 (5 days) | Legacy position (NULL thesis). Watchdog caught bearish sentiment + price drop. |

Realized P&L today: -1.24% (single loss).

### Open positions (14)

| Symbol | Entry | Current | P&L | Score | Thesis | Since | Peak |
|---|---|---|---|---|---|---|---|
| PBR-A | $19.02 | $19.87 | **+4.47%** | 76 | weakening | Apr 9 | $19.85 |
| WING | $179.73 | $186.31 | **+3.66%** | 74 | weakening | Apr 9 | $182.82 |
| AVGO | $368.65 | $379.75 | **+3.01%** | 81 | weakening | Apr 10 | $378.14 |
| RRX | $204.94 | $210.01 | +2.47% | 74 | NULL | Apr 8 | $209.02 |
| TPL | $409.01 | $416.77 | +1.90% | 85 | valid | Apr 10 | $418.73 |
| ASML | $1,480.96 | $1,500.20 | +1.30% | 80 | valid | Apr 10 | $1,490.90 |
| META | $627.80 | $634.53 | +1.07% | 78 | NULL | Apr 8 | $632.92 |
| REGN | $740.85 | $746.46 | +0.76% | 79 | valid | Apr 10 | $755.58 |
| VZ | $45.21 | $45.42 | +0.46% | 73 | valid | Apr 13 | — |
| TSM | $368.79 | $369.57 | +0.21% | 81 | valid | Apr 13 | $370.86 |
| ETH-USD | $2,252.33 | $2,254.79 | +0.11% | 73 | valid | Apr 13 | $2,254.08 |
| AGI.TO | $66.53 | $66.58 | +0.08% | 81 | valid | Apr 10 | $67.00 |
| LB | $67.97 | $67.46 | -0.75% | 80 | valid | Apr 10 | $70.38 |
| LYG | $5.57 | $5.53 | -0.72% | 73 | NULL | Apr 8 | — |

**Sum: +18.03% | Avg: +1.29%/position | 12 green, 2 red**

Trailing stop active on PBR-A (+4.47%), WING (+3.66%), AVGO (+3.01%) — all above 3% threshold with peak prices tracking.

### Thesis status distribution

- **valid (8):** ETH-USD, TPL, ASML, LB, VZ, TSM, AGI.TO, REGN
- **weakening (3):** PBR-A, AVGO, WING — all are the best performers. Claude sees overextension, but price keeps running. Trailing stop is the right exit mechanism here, not thesis invalidation.
- **NULL/legacy (3):** RRX, META, LYG — no thesis protection. LYG is the only loser at -0.72%.

### Patterns observed

**1. The best performers have "weakening" theses.** PBR-A (+4.47%), WING (+3.66%), AVGO (+3.01%) are all thesis=weakening. This is Claude's conservative bias — it sees overextension and flags the thesis as weakening, but the price keeps climbing. The trailing stop we built is exactly the right exit for these: it lets them run while protecting gains. Stage 6 thesis invalidation would exit too early on a winner.

**2. FRED outage makes Ship 2 invisible.** We invested significant effort wiring yield curve and credit spread data into the brain. None of it has reached Claude in a real market-hours scan because FRED is down. Priority fix for tomorrow.

**3. The tier model is too permissive on Claude-HOLD entries.** VZ is the third case (after CRM Day 4 and today) where Claude explicitly says HOLD with bearish self_check, but the tier model buys anyway because it only checks score + ai_status, not Claude's actual signal. The `_ai_signal` field we added gives us the data to fix this — but per the Day 4 principle, we chose not to. Worth revisiting if VZ bleeds.

**4. The brain is diversifying naturally.** Started Week 1 with 100% SAFE_INCOME. Now has the first HIGH_RISK (ETH-USD) and the first crypto entry. The brain is finding opportunities across asset classes as the universe expands.

**5. Peak price tracking is working.** Multiple positions show peak_price values in the DB. The trailing stop mechanism has data to work with even though no trailing stop has fired yet (no position has dropped 3% from peak while being above 3% entry profit).

### Week 1 cumulative (Apr 8 - Apr 13)

| Metric | Value |
|---|---|
| Trading days | 4 (Apr 8, 9, 10, 13 — weekend skipped) |
| Total brain entries | 18 |
| Total brain closes | 7 |
| Close win rate | 43% (3W / 4L + 3 near-flat thesis exits) |
| Best trade | ASML #1 TARGET_HIT +5.09% |
| Worst trade | VSEC WATCHDOG -3.18% |
| Currently open | 14 positions |
| Portfolio sum P&L | +18.03% |
| Avg per position | +1.29% |
| THESIS_INVALIDATED exits | 3 (CRM +0.08%, WING #1 -0.07%, BF-B +0.13%) |
| AI cost | ~$0.12 paid total (Claude Local handled >95% free) |
| Scans completed | 22/24 (2 stuck on Day 4, cleaned manually) |

### Metrics to track tomorrow

- [ ] Fix FRED API — test the key, add logging to `_fetch_fred_series`, verify yield curve and credit spread reach Claude
- [ ] VZ trajectory — falling-knife entry, thesis currently valid. If it starts bleeding, does Stage 6 catch it?
- [ ] ETH-USD first 24h — first crypto, first HIGH_RISK. Does watchdog monitor it correctly? Does trailing stop track the peak?
- [ ] Do any trailing stops fire for the first time? PBR-A, WING, AVGO are all above 3% with active trails
- [ ] LB and LYG — the two red positions. LB was at peak $70.38 and is now $67.46 (3.75% below peak but P&L is -0.75% so trailing stop isn't active yet because it was never 3% above entry). LYG is legacy with no protection.

---

## Day 8 -- April 14, 2026 (Tuesday)

**First trailing stops fire in production. First 10%+ winner (WING). Portfolio crosses +32%.** Three closes today (PBR-A trailing +1.13%, LB trailing -1.31%, VZ watchdog -1.80%), four new entries (GOOGL, BLK, HBM, CNQ), and the thesis-gated trailing stop design was validated retroactively — LB would have been saved under the new code.

### Environment
- Market: TRENDING (VIX 18.36)
- Environment: favorable
- Fear & Greed: 47 (neutral — up from 41 fear yesterday)
- Yield curve: 0.52% (normal) — **FRED is back!**
- Credit spread: 1.04% (normal)
- Scans: 4/5 COMPLETE, 1 FAILED (PRE_CLOSE)
- Budget: ~$0 (Claude Local)

### Scan performance

| Scan | Duration | Status |
|---|---|---|
| PRE_MARKET | 209s | COMPLETE |
| MORNING | 201s | COMPLETE |
| MIDDAY | 195s | COMPLETE |
| PRE_CLOSE | 209s | **FAILED** |
| AFTER_CLOSE | 216s | COMPLETE |

PRE_CLOSE failure — first market-hours scan failure since Day 5's AFTER_CLOSE. Same Claude CLI exhaustion pattern likely. Not investigated yet.

### Brain trades

**Opened (4):**

| Symbol | Score | Tier | Entry | Thesis note |
|---|---|---|---|---|
| GOOGL | 81 | T1 | $332.32 | Claude=HOLD, 99% BB, MACD negative, "entry is poor" |
| BLK | 73 | T1 | $1,069.51 | Claude=HOLD, 100% BB, MACD -9.79, "momentum reversed" |
| HBM | 80 | T1 | $25.32 | 545% EPS growth, 6% dividend, "demands patience" |
| CNQ | 77 | T1 | $45.51 | Oil exposure, MACD turning positive, oil -6.1% 5d headwind |

GOOGL and BLK are both Claude-says-HOLD entries with self_check.bearish=True. Both above SMA50 (so the new filter doesn't catch them). The brain buys on score (81 and 73) despite Claude flagging overextended technicals. Same pattern as VZ/LB from last week.

**Closed (3):**

| Symbol | Exit reason | P&L | Peak | Thesis | Notes |
|---|---|---|---|---|---|
| PBR-A | TRAILING_STOP | **+1.13%** | $19.85 | weakening | Soft trail fired. Peak was +4.4%, locked in +1.13%. Thesis was weakening — correct to sell under new rules. |
| LB | TRAILING_STOP | **-1.31%** | $70.38 | valid | Soft trail fired under OLD code. **Under new thesis-gated code: would have been SUPPRESSED** (thesis=valid, drop was 4.7% < 5% hard trail). LB would still be open. |
| VZ | WATCHDOG_EXIT | **-1.80%** | — | valid | Falling knife played out exactly as Claude warned on Day 7. Watchdog bypasses thesis gate. |

**Realized P&L: -1.98%** (negative day — VZ and LB losses outweighed PBR-A gain).

### The LB retroactive validation

LB is the proof that the thesis-gated trailing stop we built yesterday is correct:

- **Old code (still live today):** 3% mechanical trail → LB drops from peak $70.38 to $67.08 (4.7% drop) → auto-sell at -1.31%
- **New code (deployed tonight):** thesis=valid → soft trail SUPPRESSED → hold. Hard trail at 5% ($66.86) not hit. LB stays open.
- **Outcome if held:** LB closed at $67.08 today. If we held, we'd still be at -1.31% but with the thesis valid and a chance to recover vs being locked into a realized loss.

This is the exact scenario Pedro described: "why did it sell? the fundamentals are fine, it's just noise." The thesis-gated trailing stop answers that question correctly.

### Open positions (15) — +32.29% combined

| Symbol | P&L | Thesis | Notes |
|---|---|---|---|
| **WING** | **+10.21%** | weakening | Biggest winner in brain history. Short squeeze playing out (16.8% SI). |
| META | +5.53% | NULL | Legacy, no thesis. Strong recovery. |
| AVGO | +3.29% | valid | Trailing active. |
| TSM | +3.01% | valid | Trailing active. |
| ETH-USD | +2.67% | valid | First crypto still running. |
| ASML | +2.52% | weakening | Re-entry working. |
| RRX | +2.15% | NULL | Legacy. |
| REGN | +1.98% | valid | Steady. |
| AGI.TO | +0.92% | valid | Gold miner. |
| TPL | +0.78% | valid | Recovering from counter-trend. |
| LYG | +0.54% | NULL | Legacy, finally green. |
| CNQ | +0.31% | valid | New today. |
| GOOGL | +0.18% | valid | New today. |
| HBM | -0.39% | valid | New today. |
| BLK | -1.40% | valid | New today, immediately red. |

**Sum: +32.29% | Avg: +2.15%/position | 12 green, 3 red**

### Milestones

1. **WING +10.21%** — first double-digit winner. The brain entered at $179.73, current $198.08. 16.8% short interest squeeze is the driver. Trailing stop protecting gains (thesis=weakening → soft trail would fire on a 3% drop from peak).
2. **First trailing stops fired in production** — PBR-A (correct: thesis weakening, sell) and LB (would be suppressed under new code: thesis valid, hold).
3. **FRED back online** — yield curve 0.52%, credit spread 1.04%. Ship 2's leading indicators are finally reaching Claude.
4. **Portfolio crossed +32%** combined across 15 positions.
5. **thinking_observation_added event** — the PYPL/META hypothesis got updated.

### Patterns observed

**1. The brain keeps buying Claude-says-HOLD stocks above SMA50.** GOOGL and BLK today, same as VZ and LB last week. The SMA50 filter only catches below-SMA50 entries. Stocks AT the Bollinger Band ceiling (99-100%) with negative MACD are a different risk: they're above SMA50 but technically exhausted. The brain sees score 73-81, the AI sees "wait for pullback." Consider: adding a Bollinger Band ceiling check to the tier model (if BB > 95% AND MACD histogram < 0, downgrade to half size).

**2. Trailing stops need to be thesis-gated in production.** Today's LB close proves it. The new code is built but wasn't live yet. After tonight's restart, thesis-gated trailing stops are active.

**3. The watchdog is the last line of defense for thesis=valid positions.** VZ had thesis=valid (the thesis gate would have suppressed stop/target/trail exits) but the watchdog caught the bearish sentiment + price drop and force-closed. The watchdog correctly bypasses the thesis gate. Without it, VZ would still be bleeding.

**4. Energy exposure through CNQ is oil-dependent.** The thesis explicitly notes "oil's sharp 5-day decline of -6.1%." The brain entered despite this headwind because fundamentals are strong. If oil keeps falling, CNQ follows. The intermarket data (oil price) is now in Claude's prompt — the brain CHOSE to enter despite seeing the headwind.

**5. FRED recovery means Ship 2 is finally testable.** First market-hours scan with yield curve + credit spread data reaching Claude. Both are normal/favorable today — the real test comes when one of them deteriorates.

### Features shipped today

| Feature | What it does |
|---|---|
| Thesis-gated trailing stop | Soft trail (3%) suppressed when thesis=valid; hard trail (5%) always fires |
| SMA50 trend filter | Below SMA50 → Tier 1 downgraded to Tier 2 (half size) |
| Short interest warning rules | Bearish (below SMA50 + SI>10%) and squeeze (above SMA50 + SI>10% + MACD+) |
| Opportunities in Claude's prompt | format_warning_signs now surfaces positive signals too (✓ prefix) |
| Exit context on closed trades | Human-readable explanation of why each trade was sold |
| Tier reason stored + shown in UI | "Below SMA50" badge visible in expanded position detail |
| Watchdog monitor grid | Click-to-expand per-symbol watchdog history, closed positions toggle |
| Weakening ≠ sell knowledge entry | Added to signal_knowledge so Claude reads it every scan |

### Metrics to track tomorrow

- [ ] Does the thesis-gated trailing stop work in production? Watch for "TRAILING STOP suppressed — thesis still valid" in logs.
- [ ] BLK entered at -1.40% day one with bearish self_check. Does it recover or continue bleeding? Same pattern as VZ.
- [ ] WING at +10.21% — does the 16.8% SI squeeze continue or does it reverse? This is the trailing stop's biggest test.
- [ ] Consider BB ceiling check: stocks at >95% BB with negative MACD should get reduced size even if above SMA50.
- [ ] PRE_CLOSE scan failure — investigate Claude CLI exhaustion pattern.
- [ ] Polymarket integration exploration — forward-looking crowd consensus on Fed, earnings, geopolitics.

---

## Day 9 -- April 15, 2026 (Tuesday)

**DNS exhaustion broke the app for half the day, but the brain still closed +7.79% realized.** META hit its best trade ever (+7.38%), quality prune fired for the first time, and a critical trailing stop floor bug was discovered and fixed.

### Environment
- Market: TRENDING (VIX 18.17)
- Environment: favorable
- Fear & Greed: **56.5 (greed)** — first time above 50, market shifting bullish
- Scans: 7/15 COMPLETE (8 failed from DNS exhaustion before fix)
- Budget: ~$0 (Claude Local)

### Critical incident: DNS thread exhaustion

**Root cause:** Three new features we added yesterday (SPY crash detection in watchdog, portfolio heat live price fetch, signal list enrichment) all made yfinance calls that competed with the scan for DNS threads. The Mac's DNS pool (~12 threads) was overwhelmed → every API request got `[Errno 8] nodename nor servname provided, or not known` → 500 errors on ALL endpoints including basic auth middleware (`is_token_blacklisted`).

**Impact:** 8 scans failed. The UI was completely broken for ~3 hours (every page showed 500 errors). The brain couldn't trade during this window.

**Fix applied:** Removed the three offending features:
1. SPY crash detection removed from watchdog (2 yfinance calls per 15-min cycle)
2. Portfolio heat live price fetch replaced with position-count heuristic (15 yfinance calls per scan)
3. Signal list enrichment removed — signals served without live prices (50 yfinance calls per API request)
4. Axios timeout increased from 8s to 15s

**Lesson saved:** The system has a hard DNS thread ceiling. Every new feature that adds network calls must be evaluated against this ceiling. The scan + watchdog + API together cannot exceed ~12 concurrent DNS resolutions.

### Also fixed today

**`trailing_stop_price` undefined** — leftover variable from the thesis-gated trailing stop refactor. Caused the PRE_MARKET scan to fail with `NameError`. Fixed by replacing with `soft_trail`.

**yfinance returning None** — `t.history()` sometimes returns `None` instead of an empty DataFrame. Added a None guard in `get_price_history`.

### Brain trades

**Opened (1):** ESE @ $304.95, score 82, Tier 2. Only 1 new entry — portfolio heat at cautious level.

**Closed (4):**

| Symbol | Exit reason | P&L | Peak P&L | Notes |
|---|---|---|---|---|
| **META** | **TARGET_HIT** | **+7.38%** | +7.8% | Brain's best trade. Held 7 days. Target was +5.3% but stock overshot to +7.8%. |
| **AVGO** | **SIGNAL** | **+6.75%** | +3.2% | Scan generated SELL. Thesis was weakening. Strong exit. |
| RRX | TRAILING_STOP | **-3.61%** | +3.9% | ⚠ Was UP +3.9% but closed NEGATIVE. Trail floor bug — see below. |
| ASML | QUALITY_PRUNE | **-2.73%** | +2.5% | First quality prune in production. Thesis weakening + losing. |

**Realized P&L: +7.79%** (2W +14.13% vs 2L -6.34%)

### Improvement discovered: trailing stop floor bug

**RRX was up +3.9% at its peak but exited at -3.61%.** The hard trailing stop (5% below peak) was calculated as `peak * 0.95 = $202.24`, but the entry price was `$204.94`. The trail was BELOW the entry price — so the position went from profit to loss before the trail caught it.

**Rule:** Once a position has been up 3%+ (trailing stop active), it should NEVER close at a loss. The worst exit should be breakeven.

**Fix applied:**
```python
soft_trail = max(peak * 0.97, entry_price)  # never below entry
hard_trail = max(peak * 0.95, entry_price)  # never below entry
```

With this fix, RRX would have exited at $204.94 (breakeven) instead of $197.54 (-3.61%). The entire loss was preventable.

### META target analysis

META's target was set at +5.3% ($661) at entry. The stock peaked at +7.8% ($676.79). The 7-day TARGET_HIT suppression held through the run, but expired on day 7 and the fixed target fired at +7.4%. The trailing stop would have continued managing the exit.

**The target should rise when the stock outperforms.** Currently targets are fixed at entry and never adjust. Future improvement: when peak exceeds the original target by > 2%, raise the target to `peak * 0.97` (same as the trailing stop). This merges the target and trail into one adaptive exit.

### Open positions (12)

| Symbol | P&L | Thesis | Notes |
|---|---|---|---|
| WING | +6.49% | weakening | Still the portfolio's biggest open winner |
| ETH-USD | +4.48% | weakening | Crypto doing well |
| TPL | +2.03% | weakening | Recovering from the counter-trend |
| REGN | +1.77% | valid | Steady |
| TSM | +1.71% | weakening | Semi play |
| GOOGL | +1.44% | valid | Day 2, working |
| ESE | +0.90% | valid | New today |
| LYG | +0.72% | legacy | The last legacy survivor |
| CNQ | +0.57% | valid | Oil play |
| AGI.TO | -1.23% | valid | Gold miner pulling back |
| HBM | -1.74% | valid | Copper miner, early |
| BLK | -1.96% | valid | The overextended entry from yesterday |

**Sum: +15.19% | Avg: +1.27%/position | 9 green, 3 red**

### Features shipped today

| Feature | What it does |
|---|---|
| Trailing stop floor | `max(peak * 0.95, entry_price)` — never exit a winner at a loss |
| DNS fix: remove signal enrichment | List endpoint skips live prices |
| DNS fix: remove SPY watchdog check | Watchdog no longer competes for DNS |
| DNS fix: simplify portfolio heat | Position count heuristic, no price fetch |
| Scan timing instrumentation | `⏱ SCAN TIMING: screening=Xs, pass1=Xs, pass2=Xs, tail=Xs` |
| yfinance None guard | `t.history()` returning None no longer crashes |
| `trailing_stop_price` fix | Stale variable name from refactor |

### Week 2 running totals (Apr 13-15)

| Metric | Value |
|---|---|
| Trading days | 3 (Mon-Wed) |
| Brain entries | 6 |
| Brain closes | 9 |
| Close win rate | 56% (5W / 4L) |
| Best trade | META TARGET_HIT +7.38% |
| Worst trade | RRX TRAILING_STOP -3.61% |
| Total realized | +5.81% |
| Currently open | 12 positions |
| Portfolio sum P&L | +15.19% |
| Scans completed | 12/20 (8 failed from DNS bug) |

### Metrics to track tomorrow

- [ ] Does the trailing stop floor prevent any negative exits on positions that were once up 3%+?
- [ ] Does the DNS fix hold — all scans complete, UI responsive during scans?
- [ ] BLK at -1.96% with thesis=valid — does it recover or approach the quality prune threshold (day 2+)?
- [ ] Fear & Greed at 56.5 (greed) — if it keeps climbing, should the portfolio heat respond?
- [ ] META cooldown active — brain won't re-buy META for 60 minutes after the TARGET_HIT. Watch for re-entry attempts.
- [ ] Scan timing: is pass2 (87s) consistent, or was the 478s morning scan a one-off?

---

## Day 10 -- April 16, 2026 (Thursday)

**First perfect-5/5 scan day since the DNS incident, +7.40% realized on 10 closes, and one live design bug uncovered: three freshly-opened positions got invalidated within 57 seconds of being bought inside the same MORNING scan.**

### Environment
- Market: TRENDING (Claude thesis text notes VIX neighborhood, Fear/Greed flipped to greed 57.6)
- Scans: **5/5 COMPLETE** — PRE_MARKET, MORNING, MIDDAY, PRE_CLOSE, AFTER_CLOSE. First clean day since Day 9's DNS exhaustion.
- Budget: ~$0 (Claude Local still carrying synthesis, 25+ thesis re-evals via thesis_tracker)
- Signals per scan: 55–57 (stable)
- GEMs: 0

### Brain trades

**Opened (6):** ESE @ $297.62 (T1, 82), CCO.TO @ $166.50 (T1, 79), DIR-UN.TO @ $13.99 (T1, 76), HMY @ $17.82 (T2, 72), VZ @ $46.27 (T2, 75), BLK @ $1021.45 (T1, 77 — re-buy, see below).

**Closed (10):**

| Symbol | Scan | Exit reason | P&L % | P&L $ | Peak | Notes |
|---|---|---|---|---|---|---|
| **TPL** | MORNING | THESIS_INVALIDATED | **+4.17%** | **+$17.07** | +2.5% over entry | Held 6 days. Exit at 14:02:54. |
| **WING** | MORNING | THESIS_INVALIDATED | **+4.13%** | **+$7.42** | +8.5% at peak | Held 7 days. Biggest winner by %. |
| **ETH-USD** | MORNING | TRAILING_STOP | **+2.17%** | **+$48.97** | +5.9% at peak | Crypto. Biggest $ winner. |
| ESE | PRE_MARKET | THESIS_INVALIDATED | +0.90% | +$2.75 | n/a | Bought Apr 15, out at 10:02. |
| AGI.TO | (watchdog) | WATCHDOG_EXIT | -0.20% | -$0.13 | n/a | Bearish sentiment, tiny loss. |
| TSM | MORNING | QUALITY_PRUNE | -0.78% | -$2.89 | -- | Weakening thesis, pruned for slot. |
| BLK | MORNING | SIGNAL | **-2.87%** | **-$30.71** | -- | Sold on SELL signal. **Re-bought 5h later at $1021.45.** |
| ESE (#2) | MORNING | THESIS_INVALIDATED | -0.03% | -$0.08 | -- | **Bought and closed inside the SAME scan.** |
| CCO.TO | MORNING | THESIS_INVALIDATED | -0.02% | -$0.03 | -- | **Bought and closed inside the SAME scan.** |
| DIR-UN.TO | MORNING | THESIS_INVALIDATED | -0.07% | -$0.01 | -- | **Bought and closed inside the SAME scan.** |

**Realized today: +7.40% | +$42.36** (4W $76.21 / 6L -$33.85). Win-rate 40% but winners are 2.2x bigger than losers by dollars.

### The intra-scan buy→invalidate bug (new)

Three of today's six new entries — **ESE, CCO.TO, DIR-UN.TO** — were opened at `14:01:57` and closed at `14:02:54`, inside the same MORNING scan. Each carried `THESIS_INVALIDATED` as the exit reason with losses of roughly one penny per share.

Sequence in one scan:
1. Stage 7 (`process_virtual_trades`) opens the three positions from the BUY signals.
2. Stage 6 (`thesis_tracker`) re-evaluates every OPEN brain position — including the three just opened.
3. Claude Local re-reads the entry thesis and returns `invalid` (confidence high enough to trigger exit).
4. `check_virtual_exits` closes them 57 seconds after opening.

Confirmed via `knowledge_events.payload`: `thesis_evaluated` rows with `should_exit=True` exist for ESE, CCO.TO, DIR-UN.TO at timestamps matching the exit clock. The 60-minute re-buy cooldown didn't fire because it only applies *after* a `THESIS_INVALIDATED` close — it doesn't prevent the first invalidation from happening on the same scan that created the position.

**Design gap:** thesis re-eval should skip positions whose `entry_date` is within this scan run. Alternative: a minimum-hold window of one scan cycle before thesis_tracker can invalidate. Either prevents the same-scan flip-flop while keeping the invalidation discipline for real exits (WING, TPL above both exited correctly at +4% after 6–7 days).

### BLK re-buy discipline (not a bug)

BLK closed at `14:01:57` with `SIGNAL` (-2.87%) and re-opened at `19:01:47` at `$1021.45` — **4.5% lower than the original $1069.51 entry**. The 60-min `THESIS_INVALIDATED` cooldown didn't apply (exit_reason was `SIGNAL`, not `THESIS_INVALIDATED`), so re-buy was allowed. The 5-hour gap + the lower entry suggest this was rational — the brain let the sell-signal wash through, then re-entered at a better price when the MIDDAY/PRE_CLOSE scan re-confirmed the setup. Worth watching whether this pattern prints wins.

### Watchdog activity (44 events)

- **HOLD_THROUGH_DIP: 20** — GOOGL 13×, WING 3×, TPL 3×, TSM 1×. GOOGL is burning through the cooldown counter fast; it should be in 1h cooldown by now per the 3-consecutive-holds rule.
- **ALERT: 19** — HBM 9×, TSM 6×, AGI.TO 2×, BLK 2×. HBM was the most alert-heavy name of the day.
- **RECOVERY: 4** — all HBM. So HBM alerted 9× and recovered 4× — volatile but ending the day at `thesis=valid`.
- **CLOSE: 1** — AGI.TO (WATCHDOG_EXIT -0.20%).

GOOGL's 13 HOLD_THROUGH_DIP events in one day are the most for any single ticker this week and suggest the cooldown rule is only partially effective when the name keeps oscillating around thresholds.

### Open positions (8, down from 12 yesterday)

| Symbol | Entry | Score | Tier | Thesis | Notes |
|---|---|---|---|---|---|
| BLK | $1021.45 | 77 | T1 | valid | Re-buy at lower price |
| HMY | $17.82 | 72 | T2 | weakening | New, already weakening |
| VZ | $46.27 | 75 | T2 | valid | New |
| CNQ | $45.51 | 77 | T1 | weakening | Day 2 — CNQ saw 5 weakening re-evals today, didn't invalidate |
| HBM | $25.32 | 80 | T1 | valid | Volatile (9 alerts, 4 recoveries) |
| GOOGL | $332.32 | 81 | T1 | weakening | 13 HOLD_THROUGH_DIP — watchdog magnet |
| REGN | $740.85 | 79 | T1 | valid | Steady, day 6 |
| LYG | $5.57 | 73 | T1 | NULL | The last legacy survivor (pre-Stage-6) |

### Features shipped today

| Feature | Commit | What it does |
|---|---|---|
| Per-scan Telegram toggle | `f9a9f34` | `notify_scans_disabled` + ContextVar in scan_service; UI card in /settings; PRE_MARKET silenced by default |
| Quiet hours to 6:30 AM | `f9a9f34` | `is_quiet_hours()` now minute-aware; window 18:00 → 06:30 ET |
| How-it-works: watchdog events reference | (pending commit) | New card lists ALERT / ESCALATION / HOLD_THROUGH_DIP / CLOSE / RECOVERY definitions |
| How-it-works: quiet-hours + per-scan bullets | (pending commit) | `notif7`, `notif8`, updated `scan1` and `notifNote` (5 scans, not 4) |
| Closed trades load-more | `4fa9f28` | Performance page paginates in 5s; button hides when exhausted |
| Dashboard widget cap | `4fa9f28` | Explicit `slice(0,5)` so widget stays compact |
| Dollar P&L on performance | `9160885` | `total_pnl_amount` + sub-line "+$X @ 1 share/trade" on Total Return stat box |
| Removed `[:5]` cap on recent_closed | `9160885` | Server returns up to 50 closed trades (DB query limit) |

### Week 2 running totals (Apr 13–16)

| Metric | Value |
|---|---|
| Trading days | 4 (Mon–Thu) |
| Brain entries | 12 |
| Brain closes | 18 |
| Close win rate | 39% (7W / 11L) |
| Realized P&L | **+11.97% / +$63.61** |
| Best trade | META +7.38% / +$34.08 (Wed) |
| Worst trade | BLK -2.87% / -$30.71 (today) |
| Currently open | 8 positions |
| Scans completed | 17/20 (85% — up from 60% last week) |

### Metrics to track tomorrow

- [ ] **Same-scan buy→invalidate** — does it fire again? If yes, gate thesis_tracker on `entry_date < scan_start`.
- [ ] BLK at $1021.45 — does the re-buy recover, or is it the BLK-sell-signal being right twice in a row?
- [ ] GOOGL — is the 3-consecutive-holds cooldown actually suppressing Telegram spam? Check alert count vs hold count.
- [ ] HBM — volatile ending today. Does it close day 2 in the green, or alert another 9 times?
- [ ] HMY new entry at `weakening` thesis on day 1 — does it invalidate quickly, or recover?
- [ ] Quiet-hours + per-scan toggle: verify **zero** Telegram messages from tomorrow's PRE_MARKET scan (except the confirmed `urgent=True` OTP path).

---

## Day 11 -- April 17, 2026 (Thursday)

**Quiet day with only 3 closes, but CNQ's -5.89% loss exposed oil-crash risk, and GOOGL's 2-day HOLD_THROUGH_DIP discipline finally paid off at +2.82%. CPA hit the same-scan bug again (fix coded but not deployed). PRE_CLOSE scan missing — scheduler gap.**

### Yesterday's metrics check

- [x] **Same-scan buy→invalidate** — fired again on CPA (opened 16:01:51, closed 16:02:32, -0.04%). Fix coded in `thesis_tracker.py` but **not deployed** — backend not restarted. Priority for tomorrow.
- [x] **BLK at $1021.45** — still open, `thesis=valid`, P&L +0.34% at PRE_MARKET. Recovering slowly.
- [x] **GOOGL** — 6 more HOLD_THROUGH_DIP today, then cleanly exited via THESIS_INVALIDATED at **+2.82% / +$9.36** in the AFTER_CLOSE scan. 19 total hold-through-dip events across 2 days → the discipline paid off.
- [x] **HBM** — zero watchdog events today. Calmed down completely. `thesis=valid`, P&L ranged +1.74% to +3.91%.
- [x] **HMY** — flipped from `weakening` to `valid`. **Massive day: -1.74% → +7.94%** by MIDDAY. Still open.
- [ ] **Quiet-hours / per-scan toggle** — not verified (backend not restarted with new code).

### Environment
- Market: likely TRENDING (GOOGL thesis text notes continued greed sentiment, HMY gold miner surged)
- Scans: **4/5 COMPLETE** — PRE_MARKET, MORNING, MIDDAY, AFTER_CLOSE. **PRE_CLOSE missing** (no row in DB at all — scheduler didn't fire, not a scan failure).
- Budget: ~$0 (Claude Local)
- Signals per scan: 56–59
- GEMs: 0

### Brain trades

**Opened (3):** BBD @ $4.28 (T1, 78), CPA @ $129.34 (T2, 81 — same-scan killed), CNQ #3 @ $42.32 (T2, 79 — re-buy after -5.89% exit).

**Closed (3):**

| Symbol | Scan | Exit reason | P&L % | P&L $ | Notes |
|---|---|---|---|---|---|
| CNQ | MORNING | THESIS_INVALIDATED | **-5.89%** | **-$2.68** | Oil crashed. Held 3 days. Score was 79 at exit — score said fine, thesis said dead. |
| CPA | MIDDAY | THESIS_INVALIDATED | -0.04% | -$0.05 | **Same-scan bug** — opened and closed within 41 seconds. |
| **GOOGL** | AFTER_CLOSE | THESIS_INVALIDATED | **+2.82%** | **+$9.36** | 19 HOLD_THROUGH_DIP events over 2 days. Discipline paid off. |

**Realized today: -3.11% / +$6.63** (1W +$9.36 / 2L -$2.73). Percent says bad day; dollars say green.

### The % vs $ divergence

Today's numbers highlight an important accounting question: the brain closed -3.11% in sum-of-percentages but **+$6.63** in dollars (1 share/trade). This happens because GOOGL trades at $332 while CNQ trades at $42 — a +2.82% GOOGL win is worth $9.36 while a -5.89% CNQ loss costs $2.68. **Dollar P&L is the more meaningful metric** for a portfolio that trades across wildly different price levels. Sum-of-percent is misleading because it gives equal weight to a $4 stock and a $1000 stock.

### CNQ's full lifecycle (bought, crashed, sold, re-bought)

| Date | Event | Price | P&L | Notes |
|---|---|---|---|---|
| Apr 14 | Brain BUY | $45.51 | -- | Tier 1, score 77, oil play |
| Apr 16 PRE_MARKET | thesis=weakening | -- | +1.76% | Still OK |
| Apr 17 PRE_MARKET | thesis=weakening | -- | +1.76% | Holding |
| Apr 17 MORNING | **thesis=invalid** | $42.83 | **-5.89%** | Oil crashed. Thesis dead. Exit. |
| Apr 17 MIDDAY | Brain re-BUY | $42.32 | -- | Tier 2, score 79. 2h after close (cooldown passed). |
| Apr 17 MIDDAY | thesis=weakening | -- | -0.17% | Already weakening on re-entry |
| Apr 17 AFTER_CLOSE | thesis=weakening | -- | +1.61% | Bouncing back |

The thesis invalidation at -5.89% was **correct** — it saved the portfolio from a potential -8% catastrophic stop. But the re-buy 2 hours later at $42.32 is questionable: if oil is crashing, why re-enter? The score (79) and the AI both said BUY, but the invalidation reason ("oil price deterioration") presumably still applies. **Question for the brain:** should THESIS_INVALIDATED for macro reasons (commodity crash, sector rotation) extend the cooldown beyond 60 minutes?

### Watchdog activity (20 events)

- **HOLD_THROUGH_DIP: 14** — REGN 8×, GOOGL 6×. REGN is now the heaviest hold-through-dip ticker, day 7.
- **ALERT: 6** — all CNQ (before and after re-entry). CNQ immediately volatile.
- **CLOSE: 0** — watchdog didn't force-close anything today; all exits were thesis-driven.
- **RECOVERY: 0**

### PRE_CLOSE scan gap

PRE_CLOSE (15:00 ET / 19:00 UTC) didn't fire. No row in the DB = APScheduler didn't trigger it. Previous 2 days both completed successfully. Possible causes: process was busy with the MIDDAY scan aftermath, or a brief scheduler misfire. Worth monitoring — one miss in 10 days is tolerable, but consecutive misses mean a scheduler bug.

### Open positions (8)

| Symbol | Entry | Score | Tier | Thesis | Day | Notes |
|---|---|---|---|---|---|---|
| CNQ | $42.32 | 79 | T2 | weakening | 0 | Re-bought. Bounced to +1.61% by EOD |
| BBD | $4.28 | 78 | T1 | weakening | 0 | New, already weakening |
| BLK | $1021.45 | 77 | T1 | valid | 1 | Re-buy from Day 10, recovering |
| HMY | $17.82 | 72 | T2 | valid | 1 | Massive run (+7.94% at MIDDAY) |
| VZ | $46.27 | 75 | T2 | valid | 1 | Stable |
| HBM | $25.32 | 80 | T1 | valid | 3 | Calmed down, no alerts today |
| REGN | $740.85 | 79 | T1 | weakening | 7 | 8 HOLD_THROUGH_DIP today. Aging. |
| LYG | $5.57 | 73 | T1 | NULL | 9 | The legacy survivor |

### Week 2 running totals (Apr 13–17)

| Metric | Value |
|---|---|
| Trading days | 5 (Mon–Fri) |
| Brain entries | 15 |
| Brain closes | 21 |
| Close win rate | 38% (8W / 13L) |
| Realized P&L | **+8.86% / +$70.24** |
| Best trade (week) | META +7.38% / +$34.08 (Wed) |
| Worst trade (week) | CNQ -5.89% / -$2.68 (today) |
| Currently open | 8 positions |
| Scans completed | 21/25 (84%) |

### All-time running totals (Apr 6–17)

| Metric | Value |
|---|---|
| Trading days | 9 |
| Brain closes | 27 |
| Win rate | 41% (11W / 16L) |
| Total realized P&L | **+8.62% / +$134.69** |
| Best trade | META +7.38% (TARGET_HIT) |
| Worst trade | CNQ -5.89% (THESIS_INVALIDATED) |

### Learnings and things to improve

1. **Deploy the same-scan fix.** CPA was the second occurrence. Restart the backend to activate the `scan_started_at` guard in `thesis_tracker.py`. This should print `"Thesis re-eval skipped for X: opened this scan"` in tomorrow's logs.

2. **Dollar P&L should be the primary display metric**, not sum-of-percent. Today proved the divergence is real. The % metric says "bad day"; the $ metric says "green day." For a mixed-price portfolio, dollars are truth.

3. **THESIS_INVALIDATED for macro reasons (oil crash) → should the cooldown be longer?** CNQ was re-bought 2 hours after being sold for "oil price deterioration." If oil is crashing, 60 minutes isn't long enough for the macro thesis to recover. Proposal: environment variable `brain_thesis_macro_cooldown_minutes` (default 240 = 4 hours) applied when the thesis invalidation reason mentions sector/commodity/macro themes. This is speculative — needs more data before implementing.

4. **REGN at day 7 with 8 HOLD_THROUGH_DIP events** — aging position that the watchdog keeps flagging but never closes. If thesis stays `weakening` without invalidating for 3+ more days, the time-expiry exit (30 days) is the only backstop. Check if the thesis tracker's "weakening" verdict is just Claude being conservative on a position that should be sold.

5. **PRE_CLOSE scan missing** — one-off or recurring? Track tomorrow.

### Metrics to track tomorrow

- [ ] **Same-scan fix deployed?** Restart backend. Verify `"Thesis re-eval skipped"` debug log on first scan with new entries.
- [ ] Quiet-hours + per-scan toggle: verify zero Telegram messages from PRE_MARKET scan.
- [ ] PRE_CLOSE scan: does it fire tomorrow? If missing again → scheduler investigation.
- [ ] REGN (day 8): still weakening? More hold-through-dip events? At what point does this become a dead position?
- [ ] CNQ #3 at $42.32: was the re-buy rational? Is oil recovering or still bleeding?
- [ ] HMY at +7.94%: does the trailing stop activate and lock in the gain, or does it give it all back?
- [ ] BBD at weakening on day 0: invalidation tomorrow, or stabilization?

---

## Day 12 -- April 20, 2026 (Monday)

**No scans ran on Friday (Apr 18) — backend appears to have been down. HMY gapped through its trailing stop over the weekend, losing 5.6% of unrealized gains. Same-scan fix confirmed working. Brain loaded up on 4 Canadian REITs.**

### Day 11 metrics check

- [x] **Same-scan fix deployed and working.** At MIDDAY (16:02), thesis_tracker evaluated REGN and CNQ (existing positions) but skipped JD, CAR-UN.TO, HR-UN.TO, REI-UN.TO (all opened at 16:02:03 in the same MIDDAY scan). Zero same-scan invalidations today. Fix confirmed.
- [ ] **Quiet-hours / per-scan toggle** — PRE_MARKET ran at 10:00 and the scan completed, but unclear if Telegram was suppressed. Need to verify in Telegram history.
- [x] **PRE_CLOSE scan** — ran today at 19:00 UTC (normal). Also: the Apr 17 "missing" PRE_CLOSE actually ran late at 22:04 UTC, so no true gap that day.
- [x] **REGN day 10** — still weakening, 8 more HOLD_THROUGH_DIP today. 16 holds across 2 days. Becoming the new GOOGL pattern.
- [x] **CNQ #3 at $42.32** — re-buy holding, thesis=valid now, +3.24% at MORNING. Bounced.
- [x] **HMY at +7.94%** — see incident below. Closed at +2.33%.
- [?] **BBD at weakening** — confirmed, pruned at -2.34%.

### Environment
- Market: (resumed after weekend gap)
- Scans: **5/5 COMPLETE** — PRE_MARKET, MORNING, MIDDAY, PRE_CLOSE, AFTER_CLOSE. Full clean day.
- **No scans on Apr 18 (Friday)** — 0 rows in DB. Backend appears to have been down. Combined with Saturday/Sunday (no scheduled equity scans), that's a 3-day monitoring gap.
- Budget: ~$0 (Claude Local)
- Signals per scan: 56–59
- GEMs: 0

### Incident: HMY trailing stop gap-through

HMY peaked at **$19.23 (+7.94%)** on Thursday (Apr 17 MIDDAY). With the trailing stop floor fix (Day 9):
- soft_trail = max($19.23 × 0.97, $17.82) = **$18.65**
- hard_trail = max($19.23 × 0.95, $17.82) = **$18.27**

The price should have triggered the soft trail at $18.65 (~+4.7%). Instead:
- **Friday**: no scans (backend down). Price crossed $18.65 undetected.
- **Saturday/Sunday**: no equity scans (by design).
- **Monday MORNING scan**: price at $18.24 — already below **both** trails. Hard trail fired at $18.24.

**Result: exited at +2.33% instead of ~+4.7%.** The trailing stop floor prevented a loss (exit above entry), but the 3-day scan gap cost ~$0.41/share in unrealized gains.

**Lesson:** The trailing stop is only as good as the scan frequency. If the backend goes down on a Friday, positions with active trailing stops can gap through over the weekend. This isn't fixable without continuous monitoring or Friday-afternoon manual checks.

### Brain trades

**Opened (5):** JD @ $31.33 (T1, 74 — closed same day), CAR-UN.TO @ $37.26 (T1, 72), REI-UN.TO @ $21.20 (T1, 72), HR-UN.TO @ $10.37 (T1, 72), DIR-UN.TO @ $13.76 (T1, 76).

**Closed (3):**

| Symbol | Exit reason | P&L % | P&L $ | Held | Notes |
|---|---|---|---|---|---|
| **HMY** | TRAILING_STOP | **+2.33%** | +$0.42 | 4d | Peaked +7.94%, gapped through soft trail over Fri-Sun |
| BBD | QUALITY_PRUNE | -2.34% | -$0.10 | 3d | Weakening, pruned for slot |
| JD | THESIS_INVALIDATED | +0.49% | +$0.15 | 3h | Opened MIDDAY, invalidated PRE_CLOSE. Thesis was shaky at entry. |

**Realized today: +0.48% / +$0.47** (2W / 1L). Marginally green.

### Canadian REIT concentration (new risk)

4 of today's 5 entries are TSX-listed REITs: CAR-UN.TO, REI-UN.TO, HR-UN.TO, DIR-UN.TO. All scored 72–76, all SAFE_INCOME bucket, all Tier 1. If Canadian REITs dip as a sector (rate hike, housing data), the portfolio takes a correlated hit across 4 positions simultaneously.

Currently no sector/correlation limit in the brain. The pre-filter sorts by absolute day change and the brain picks whatever scores highest — it doesn't check what it already holds. **This is the same class of problem as the CNQ macro re-buy:** the brain treats each position independently without portfolio-level awareness.

### JD — thesis invalidated after 3 hours

JD was opened at MIDDAY (16:02) and closed at PRE_CLOSE (19:02) via THESIS_INVALIDATED at +0.49%. This is NOT a same-scan bug (different scans, confirmed by thesis_tracker skip at MIDDAY). But a thesis that dies in one scan cycle was probably weak at entry. The AI synthesized a BUY thesis, then on the very next re-eval said "invalid."

**Question for the brain:** Should there be a minimum thesis confidence at entry? Currently the brain picks anything with score ≥ 72 and target+stop filled. A thesis quality filter (e.g., "Claude's entry confidence must be ≥ 70 for the thesis to count") could prevent these 3-hour flip-flops.

### Watchdog activity (15 events)

- **HOLD_THROUGH_DIP: 9** — REGN 8×, HMY 1× (before close).
- **ALERT: 3** — BBD 2× (before prune), HBM 1×.
- **RECOVERY: 3** — HBM 1×, HMY 1×, BBD 1×.

REGN continues its HOLD_THROUGH_DIP marathon: **16 holds across 3 days** (8+8 on Apr 17+20, noting no scans Apr 18–19). Day 10, thesis=weakening. This position is being held on discipline alone.

### Open positions (10, up from 8)

| Symbol | Entry | Score | Tier | Thesis | Day | Notes |
|---|---|---|---|---|---|---|
| DIR-UN.TO | $13.76 | 76 | T1 | valid | 0 | New REIT |
| REI-UN.TO | $21.20 | 72 | T1 | weakening | 0 | New REIT, already weakening |
| HR-UN.TO | $10.37 | 72 | T1 | valid | 0 | New REIT |
| CAR-UN.TO | $37.26 | 72 | T1 | valid | 0 | New REIT |
| CNQ | $42.32 | 79 | T2 | valid | 3 | Oil re-buy, bounced to +3.24% |
| BLK | $1021.45 | 77 | T1 | valid | 4 | Stable |
| VZ | $46.27 | 75 | T2 | weakening | 4 | Slipping |
| HBM | $25.32 | 80 | T1 | valid | 6 | Calmed, 1 alert today |
| REGN | $740.85 | 79 | T1 | weakening | 10 | 16 hold-through-dips in 3 days |
| LYG | $5.57 | 73 | T1 | NULL | 12 | The legacy survivor |

### All-time running totals (Apr 6–20)

| Metric | Value |
|---|---|
| Trading days | 10 |
| Brain closes | 30 |
| Win rate | 43% (13W / 17L) |
| Total realized P&L | **+9.10% / +$135.16** |
| Best trade | META +7.38% (TARGET_HIT) |
| Worst trade | CNQ -5.89% (THESIS_INVALIDATED) |
| Open positions | 10 |

### Things to improve

1. **Backend uptime on Fridays.** No scans ran Apr 18, causing HMY's gap-through. If the backend crashed or was manually stopped, it needs a keep-alive mechanism (process manager, systemd, or at minimum a cron ping). This is the single biggest preventable loss today.

2. **Sector concentration limit.** 4 Canadian REITs opened in one day. The brain should check what it already holds and limit to ≤ 2 positions in the same sector/sub-sector. This requires a sector classifier on each ticker (the `bucket` field is too coarse — all 4 REITs are SAFE_INCOME just like BLK and VZ).

3. **Thesis quality at entry.** JD's thesis died in 3 hours. A minimum-confidence gate at entry time (not just at re-eval) could prevent these weak entries. Current: any BUY with score ≥ 72 + target + stop. Proposed: also require Claude's thesis confidence ≥ 70 at synthesis time.

4. **REGN at day 10 with 16 holds.** The hold discipline is being tested — this position hasn't meaningfully recovered and keeps alerting. If thesis stays `weakening` through day 15 without invalidating, the 30-day time expiry is the only exit. Should there be a "chronic weakening" exit before 30 days?

### Metrics to track tomorrow

- [ ] **Backend uptime** — did all 5 scans complete?
- [ ] **Canadian REITs** — REI-UN.TO already weakening. Do the other 3 hold valid?
- [ ] **REGN day 11** — more holds, or does it finally invalidate/recover?
- [ ] **VZ at weakening day 4** — approaching the prune zone?
- [ ] **LYG day 12** — the legacy NULL-thesis position. Does it ever close, or does it ride the 30-day expiry?
- [ ] Verify Telegram was suppressed for PRE_MARKET scan (quiet hours + per-scan toggle).

---

## Template for Future Days

**Metrics:** [Did yesterday's fixes work?]
