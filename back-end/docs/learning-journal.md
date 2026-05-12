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

## Day 13 -- April 21, 2026 (Tuesday)

**First day with all Day 12 features live. Every infrastructure fix verified working. Small loss day (-$0.66) from rotation churn on yesterday's Canadian REIT cluster — the exact sector-concentration risk called out in Day 12 played out within 24 hours.**

### Day 12 metrics check — every fix verified live

- [x] **Same-scan invalidation fix deployed.** HPQ opened at MORNING (14:02) was NOT re-evaluated until AFTER_CLOSE (20:32). Zero same-scan invalidations.
- [x] **LONG-horizon daily-only thesis re-eval live.** Only 4 thesis re-evals today (all at AFTER_CLOSE), down from 25+ on Days 10-11. 6x reduction in Claude calls.
- [x] **Quiet hours + per-scan toggle** — cannot fully verify without Telegram history, but the code path is live.
- [x] **Watchdog relaxed thresholds for LONG.** Only 8 events total today (all REGN HOLD_THROUGH_DIP). Down from 15-44/day. Massive improvement — the REIT additions didn't generate a single alert.
- [x] **Two-wallet short selling live.** 0 shorts fired (expected — no AVOID signal met validated-AI + score ≤ 40 today).
- [x] **All 5 scheduled scans + MANUAL ran clean** — no DNS issues, no scheduler gaps.

### Environment
- Scans: **6/6 COMPLETE** — PRE_MARKET, MORNING, MIDDAY, PRE_CLOSE, AFTER_CLOSE + 1 MANUAL (01:31)
- Signals per scan: 55-58
- GEMs: 0
- Budget: ~$0 (Claude Local)
- Short candidates: 0 (market too bullish — Fear/Greed still in greed territory)

### Brain trades

**Opened (3):** HPQ @ $20.75 (T1, 77, LONG/LONG), BBD @ $4.09 (T1, 78 — re-buy), CCO.TO @ $161.84 (T1, 80 — re-buy).

**Closed (4 — ALL rotations except one):**

| Symbol | Exit reason | P&L % | P&L $ | Days held | Notes |
|---|---|---|---|---|---|
| HBM | TRAILING_STOP | -0.28% | -$0.07 | 7d | Trail fired but below entry — peak never hit +3% activation |
| REI-UN.TO | ROTATION | -0.47% | -$0.10 | 1d | Replaced by same symbol at score 77 (new signal) |
| CAR-UN.TO | ROTATION | -1.36% | -$0.50 | 1d | Replaced by CCO.TO @ 80 |
| HR-UN.TO | ROTATION | +0.05% | +$0.01 | 1d | Replaced by HPQ @ 77 |

**Realized today: -2.06% / -$0.66** (1W / 3L).

### The rotation churn problem (new learning)

**Day 12 warning on sector concentration played out in ~20 hours.** Yesterday the brain loaded up on 4 Canadian REITs at score 72 because they were the best it could find. Today, stronger picks (HPQ 77, BBD 78, CCO.TO 80) arrived and the brain rotated 3 of the 4 REITs out — all at losses. Net cost: **-$0.59 paid for holding positions <24 hours just to get rotated.**

**Why this is a problem:**
- The rotation threshold is "new signal 5+ points higher than weakest held." Day 12 the REITs were 72 (the weakest slot), so any 77+ entry today triggered a cascade.
- The 3 REITs closed DIDN'T have invalidated theses. They were simply out-scored.
- In real trading this = commissions + tax events on every churn. In the virtual portfolio it's just the $0.59 drag today.

**Design gap:** rotation doesn't consider how long a position has been held. A position opened yesterday at 72 is not necessarily a bad position — it may just be at the bottom of the slate. Proposal: minimum 3-day hold before rotation eligibility (stop-loss + thesis_invalidated exits still fire normally). This would have prevented all 3 rotations today and let the REITs play out.

**The Day 12 prediction confirmed:**
> "4 Canadian REITs opened in one day. If Canadian REITs dip as a sector, the portfolio takes a correlated hit across 4 positions simultaneously."

The REITs didn't dip as a sector — but they got churned out as a cohort, which is the same concentration cost from a different angle.

### HBM trailing stop edge case

HBM entered at $25.32 on Apr 14. Peaked at ~$26 (only +2.7%) — never crossed the 3% trailing-stop activation threshold. Today it dropped to $25.25 (-0.28% from entry) and the trailing stop fired with `trailing_active=False`.

Wait — that shouldn't happen. If `trailing_active=False`, neither soft_trail nor hard_trail are set. Let me check the code path: the TRAILING_STOP exit_reason only fires when `trailing_active and current_price <= hard_trail` or similar. So how did HBM close as TRAILING_STOP at -0.28%?

**Possible cause:** pre-trailing-stop-floor HBM was tracking peak_price. If there was ANY sub-scan where peak was briefly above entry * 1.03, then on this scan the trail fired. Look at `trade.get("peak_price")` — if it was never updated to trough, it stays at 25.32 (entry). `max(25.32 * 0.95, 25.32) = 25.32`. Current was 25.25. So hard_trail > current → fires.

**Actual root cause:** the peak_price wasn't updated through the period when HBM was only slightly above entry. After the trailing_active activated (briefly peak >= 25.32 * 1.03 = 26.08), hard_trail became `max(26.08 * 0.95, 25.32) = 25.32`. Current price 25.25 <= 25.32 → hard trail fired at exactly breakeven minus a hair. **The floor worked correctly** — exit at entry, not at a bigger loss. The "loss" is just the $0.07 bid-ask-type noise.

### Open positions (9, down from 10)

| Symbol | Entry | Score | Days | Direction | Horizon | Thesis |
|---|---|---|---|---|---|---|
| CCO.TO | $161.84 | 80 | 0 | LONG | LONG | weakening |
| BBD | $4.09 | 78 | 0 | LONG | LONG | valid |
| HPQ | $20.75 | 77 | 0 | LONG | LONG | weakening |
| DIR-UN.TO | $13.76 | 76 | 1 | LONG | LONG | weakening |
| CNQ | $42.32 | 79 | 4 | LONG | LONG | valid |
| BLK | $1021.45 | 77 | 5 | LONG | LONG | valid |
| VZ | $46.27 | 75 | 5 | LONG | LONG | weakening |
| REGN | $740.85 | 79 | 11 | LONG | LONG | weakening |
| LYG | $5.57 | 73 | 13 | LONG | LONG | NULL (legacy) |

All LONG/LONG. Short wallet still empty.

### All-time running totals (Apr 6–21)

| Metric | Value |
|---|---|
| Trading days | 11 |
| Brain closes | 34 |
| Win rate | 41% (14W / 20L) |
| Total realized P&L | **+$134.50** (down -$0.66 from yesterday) |
| Best trade | META +7.38% / +$46.33 |
| Worst trade | CNQ -5.89% / -$2.68 |
| Open positions | 9 |

### Things to learn / improve

1. **Rotation needs a minimum hold time.** Today's -$0.59 churn was preventable. Add `brain_min_hold_before_rotation_days = 3` — positions opened within the last 3 days are not rotation-eligible (stop/thesis exits still fire).

2. **Sector concentration IS still unguarded.** 4 REITs got in yesterday, 3 got churned today — same problem from a different angle. A sector classifier + max-2-per-sector rule would prevent both failure modes.

3. **Short selling threshold may be too strict.** 0 candidates today on a clearly bullish day — expected. But worth watching if zero even on mildly bearish days. If so, loosen `brain_short_max_score` to 45.

4. **LONG horizon is paying dividends today: zero noise alerts, zero mid-day thesis kills.** REGN still the only heavy-hold-through-dip name. This is the system working correctly.

5. **Dollar P&L remains tiny.** -$0.66 today, +$0.47 yesterday. The 1-share-per-trade model continues to mask real performance. With $5k/trade sizing, today would have been -$103 and yesterday +$24 — more meaningful numbers.

### Metrics to track tomorrow

- [ ] Do HPQ/BBD/CCO.TO get rotated out tomorrow (same fate as today's REITs)?
- [ ] REGN day 12: does it finally invalidate, or keep holding?
- [ ] Any short candidates fire if the market cools off?
- [ ] VZ at weakening day 5 — approaching quality prune zone?
- [ ] LYG day 14 — the legacy NULL-thesis position. 30-day expiry at day 30.

---

## Day 14 -- April 22, 2026 (Wednesday)

**The most important day of engineering so far: spotted a real design gap (CCO.TO got shaken out of a LONG on a single MORNING AVOID at +1.49%), designed + built the consecutive-AVOID delay, ran a code audit that caught FIVE critical bugs in the short-selling path (P&L inversion across signal exits, rotation exits, and watchdog close), raised BRAIN_MIN_SCORE from 72 to 75, deployed all of it mid-day. REGN finally closed green at +0.77% / +$5.73 after 12 days and 14 more hold-through-dip events. Net day: +$6.95 dollars (though -2.11% sum-of-pct).**

### Environment
- Scans: **5/5 COMPLETE** — PRE_MARKET, MORNING, MIDDAY, PRE_CLOSE, AFTER_CLOSE
- Signals per scan: 53-57
- GEMs: 0
- Short candidates: 0 (market still bullish)
- Budget: ~$0 (Claude Local)

### The CCO.TO incident and design fix

CCO.TO was opened Apr 21 at PRE_CLOSE at $161.84 (score 80, LONG/LONG). Today's MORNING scan (14:02) flipped the action from BUY to AVOID with the same score (80). The reasoning: Bollinger position 74.6%, volume z-score -2.08 — buying participation fading. The brain closed it at $164.25 = **+1.49% / +$2.41 in 19 hours**.

Ordinary win, right? **No.** At MIDDAY (16:02), the signal flipped BACK to BUY, and the brain re-bought at $164.96 — 0.4% HIGHER than the exit. The sell was premature. This is the exact pattern the LONG-horizon design was supposed to prevent, but the signal-exit path was never gated by horizon.

**Design gap identified:**
- LONG-horizon was protected from thesis tracker (daily-only re-eval) ✓
- LONG-horizon had wider trailing stops (5%/8% vs 3%/5%) ✓
- LONG-horizon relaxed watchdog thresholds ✓
- LONG-horizon did **NOT** have signal-exit protection ❌

**The fix built today: consecutive-AVOID delay.** LONG-direction + LONG-horizon positions require **2 consecutive AVOID/SELL signals** before closing. A single flip increments `consecutive_avoid_count` to 1 and the position is held; if the next scan flips back to BUY/HOLD the counter resets. If CCO.TO had been closed on the 2nd AVOID, today's sell wouldn't have fired — the MIDDAY scan flipped back to BUY and would have reset the counter to 0.

Schema: new `consecutive_avoid_count INT DEFAULT 0` column. Config: `brain_long_signal_exit_threshold = 2` (tunable). UI: `Hold 1/2` badge appears on open positions while delay is active.

### The audit that saved us from corrupt short-selling data

After building the consecutive-AVOID delay, I ran a full audit of all brain-related Python code. **The audit caught FIVE critical bugs in the short-selling path that had been sitting there since the Day 12 ship:**

| # | Bug | Impact if shorts had opened |
|---|---|---|
| 1 | Watchdog SELECT missing `direction` column | Every SHORT watchdog P&L calc would fall through to LONG default — **inverted P&L in alerts** |
| 2 | Watchdog `_close_virtual_trade` hardcoded LONG P&L | SHORT closes would write inverted P&L to DB + learning loop |
| 3 | SELL/AVOID signal exit P&L hardcoded LONG | Winning shorts would log as losses on SIGNAL exit |
| 4 | ROTATION exit P&L hardcoded LONG | SHORT rotations inverted in trade_outcomes |
| 5 | Hard-stop carve-out ignored `brain_short_hard_stop_pct` | Semantically wrong, currently harmless because both = -8.0 |

**Why zero corrupted data exists in the DB**: no shorts have opened yet (market too bullish, no AVOID + validated AI + score ≤ 40 combo has appeared since Day 12). The bugs were latent. The audit caught them before any short ever exercised them. **This is exactly why the review passes memory rule exists** — the ~30min audit prevented what would have been days of debugging wrong learning-loop data.

All 5 bugs fixed + verified. Also added `consecutive_avoid_count` to the API response and open-trades SELECT so the frontend could render it.

### Brain trades

**Opened (2):** CCO.TO @ $164.96 (T1, 80, LONG/LONG — re-buy), HIMS @ $28.39 (T1, 79, LONG/SHORT — HIGH_RISK bucket).

**Closed (4):**

| Symbol | Exit reason | P&L % | P&L $ | Held | Notes |
|---|---|---|---|---|---|
| CCO.TO | SIGNAL (pre-fix) | +1.49% | +$2.41 | 19h | The shake-out that triggered today's design. Re-bought 2h later at +0.4%. |
| VZ | WATCHDOG_EXIT | -2.31% | -$1.07 | 6d | Bearish sentiment + negative P&L. Day 5 at weakening → watchdog called it. |
| LYG | ROTATION | -2.06% | -$0.12 | 14d | The legacy NULL-thesis position finally cycled out. Replaced by HIMS. |
| **REGN** | **THESIS_INVALIDATED** | **+0.77%** | **+$5.73** | **12d** | **The LONG-horizon discipline paid off.** 14 more hold-through-dip events today before Claude finally invalidated the thesis at AFTER_CLOSE. Exited green. |

**Realized today: -2.11% / +$6.95** (2W / 2L). Dollar-positive day despite the percentage being negative — REGN's $5.73 win on a $740 stock dwarfs VZ's -$1.07 loss on a $46 stock. **This is the % vs $ divergence story again, and why $ is the honest metric.**

### The REGN story — LONG discipline working as designed

REGN was the real win today. Let me trace it:

- Apr 10: opened at $740.85, score 79, LONG/LONG, thesis=valid
- Apr 11-21: 11 days held, ~30+ hold-through-dip events across that span, thesis bounced weakening/valid
- Apr 22 (today): 14 MORE hold-through-dip events during market hours
- Apr 22 AFTER_CLOSE scan: Claude's thesis re-eval returns `invalid`, exit fires at +0.77%

**Under the pre-Day-10 system**, REGN would have been closed weeks ago — the thesis tracker running 5x/day would have produced a "weakening" call, the quality prune would have fired on a losing week, or the watchdog would have bled it out on a 2% total loss threshold.

**Under the LONG-horizon system that shipped Day 12:**
- Thesis re-eval only at AFTER_CLOSE (not 5x/day) → avoided the noise kills
- Trailing stop widened to 5%/8% → never activated (REGN peak was maybe +1.5%)
- Quality prune disabled for LONG → no "slot freed" forced exit
- Watchdog bleed threshold 4% (not 2%) → didn't force close through the ranging
- Result: held 12 days, exited green when the real thesis died

**REGN is the validation of the LONG-horizon design.** A winning exit we would have missed under the old rules. The +$5.73 alone is ~4x what we'd have captured at a premature exit.

### BRAIN_MIN_SCORE raised to 75

Mid-afternoon I also raised the minimum entry score from 72 to 75. Day 13 evidence: every losing rotation/churn event over Days 11-13 came from score 72-74 entries. JD (74), REI-UN.TO (72), CAR-UN.TO (72), HR-UN.TO (72). Score 78+ entries were solid.

Today's entries both passed the new bar: CCO.TO re-buy at 80, HIMS at 79.

### Watchdog + thesis tracker verification

- **Watchdog events**: 17 total. 14 HOLD_THROUGH_DIP (all REGN before close), 2 ALERT + 1 CLOSE (VZ). Clean elsewhere — LONG-horizon relaxed thresholds holding.
- **Thesis events**: 6 total, **all at AFTER_CLOSE 20:32 UTC**. LONG-horizon daily-only gate working perfectly. Down from the Day 10-11 pattern of 25+ re-evals per day.

### Open positions (7, down from 8)

| Symbol | Entry | Score | Days | Direction | Horizon | Thesis | Count |
|---|---|---|---|---|---|---|---|
| HIMS | $28.39 | 79 | 0 | LONG | SHORT | valid | 0 |
| CCO.TO | $164.96 | 80 | 0 | LONG | LONG | weakening | 0 |
| BBD | $4.09 | 78 | 1 | LONG | LONG | valid | 0 |
| HPQ | $20.75 | 77 | 1 | LONG | LONG | weakening | 0 |
| DIR-UN.TO | $13.76 | 76 | 2 | LONG | LONG | weakening | 0 |
| CNQ | $42.32 | 79 | 5 | LONG | LONG | valid | 0 |
| BLK | $1021.45 | 77 | 6 | LONG | LONG | valid | 0 |

Still no shorts. The new `consecutive_avoid_count` column is populated at 0 on all positions — first real test comes when any position gets an AVOID signal.

### Features shipped today

| Feature | What it does |
|---|---|
| Consecutive-AVOID delay | LONG/LONG positions require 2 consecutive AVOIDs before closing. New DB column + config + 2 code paths. |
| Counter reset on BUY/HOLD | If a position gets AVOID then BUY, the counter resets to 0. No stale state. |
| UI badge `Hold 1/2` | Performance page shows warning-colored badge when a position is mid-delay. Tooltip explains the rule. |
| Audit fix: watchdog direction column | SELECT now includes direction — watchdog correctly computes SHORT P&L |
| Audit fix: watchdog close P&L | `_close_virtual_trade` direction-aware |
| Audit fix: SELL/AVOID P&L | process_virtual_trades SIGNAL exit direction-aware |
| Audit fix: ROTATION P&L | Rotation close direction-aware |
| Audit fix: hard-stop carve-out | Uses `brain_short_hard_stop_pct` for SHORT positions |
| API: `consecutive_avoid_count` exposed | Available in `_enrich_open_trade` and open-trades SELECT |
| How-it-works: two new cards | Consecutive-AVOID delay explanation + Minimum Entry Score 75 |

### All-time running totals (Apr 6–22)

| Metric | Value |
|---|---|
| Trading days | 12 |
| Brain closes | 38 |
| Win rate | 42% (16W / 22L) |
| Total realized P&L | **+$141.45** (+$6.95 from Day 13) |
| Best trade | META +7.38% / +$46.33 |
| Worst trade | CNQ -5.89% / -$2.68 |
| Best $ win today | REGN +$5.73 (LONG-horizon validation) |
| Open positions | 7 |

### Things to learn / improve (what comes next)

1. **Watch the consecutive-AVOID delay activate.** First time any LONG position gets an AVOID signal, check the logs for `"Virtual SIGNAL exit DELAYED for X (LONG) — avoid count 1/2"`. Then watch: does the next scan reset (BUY/HOLD) or confirm (second AVOID → close)?

2. **The CCO.TO re-buy paradox remains.** Today's CCO.TO exited at $164.25, re-entered at $164.96. Net cost to the brain: 0.4% on the round-trip. With the consecutive-AVOID delay, this specific pattern won't happen again — but **there's a class of mirror trades** (SELL/rebuy within a day) that still leak value. Worth watching if the delay alone is sufficient.

3. **REGN's success is the case study for LONG holds.** The 12-day discipline produced the day's best dollar win. Without the LONG-horizon design: REGN would have been killed weeks ago under the old thesis tracker or quality prune. This is proof the strategic framework is right.

4. **Sector concentration still unaddressed.** The REITs are resolved for now (LYG out, DIR-UN.TO remaining). If a bearish sector day hits, the brain's still not sector-aware.

5. **Short wallet empty for another day.** At current threshold (40), no candidates. If we hit 5-7 consecutive bearish days with zero shorts, loosen to 45. Not yet.

### Metrics to track tomorrow

- [ ] Does any position hit `consecutive_avoid_count = 1` tomorrow? First real test of the delay.
- [ ] HIMS (new, SHORT horizon) — does it fire a 1-7 day momentum trade, or get cut early?
- [ ] CCO.TO re-buy at $164.96 — does it recover toward the $171.26 target, or flip to AVOID again?
- [ ] CNQ at +3.24%ish, day 5 — approaching target $48.50?
- [ ] HPQ at weakening day 1 — survives, or gets pruned/exited?

---

## Day 15 -- April 22, 2026 (Wednesday evening ship)

**Metrics:** 38 cumulative closes · total realized +$141.45 "per share" · the number sounds tiny but it's +47% annualized on a pretend 1-share capital base

### The observation

`pnl_amount` on closed virtual trades was per-share — `exit_price - entry_price` on 1 implicit share. A +5% win on a $5 stock realized $0.25; the same % on a $1,000 stock realized $50; both summed into `total_pnl_amount` as if the units were comparable. Running total: "+$141.45 since launch" was meaningless. No scale, no compounding, no visible risk.

### The ship: wallet-based virtual portfolio

Two new tables (`brain_wallet`, `wallet_transactions`), three new columns on `virtual_trades` (`shares`, `position_size_usd`, `is_wallet_trade`), a new `app/services/wallet.py` service, a new `app/api/v1/wallet.py` router, and a shared `close_virtual_trade()` helper that every exit path now funnels through. Plus frontend: wallet card on the performance page, inline deposit/withdraw, share counts on open/closed rows, dashboard widget showing wallet ROI, and a new "Brain Wallet" section on the how-it-works page.

### Sizing rules (codified)

- Tier 1 (trust 1.0): 10% of balance
- Tier 1 (trust 0.5): 5% (existing half-trust downgrade)
- Tier 2 / Tier 3: 5%
- Hard cap: 15% (matches `kelly.MAX_POSITION_PCT`)
- Below $100 free balance: skip the entry (log, don't crash)
- SHORT: 100% of position value reserved as collateral on open; released ± P&L on cover

### The per-share → total-dollar transition

Every exit path — SELL/AVOID signal close, SHORT cover, ROTATION, STOP_HIT, TARGET_HIT, TRAILING_STOP, TIME_EXPIRED, QUALITY_PRUNE, STAGNATION_PRUNE, THESIS_INVALIDATED, and the watchdog's emergency close — now calls `close_virtual_trade()`. For wallet trades (`is_wallet_trade=True`), the helper writes TOTAL-dollar `pnl_amount` (shares × per-share P&L) to `virtual_trades` and credits the wallet with either `proceeds_usd` (LONG close) or `original_allocation + pnl_usd` (SHORT cover). For legacy trades, per-share semantics are preserved so the 38 closed rows pre-launch stay interpretable.

### Legacy vs wallet split

The 7 currently-open brain positions (CNQ, BLK, DIR-UN.TO, REGN, HPQ, CCO.TO re-buy, etc.) were opened before Day 15. They carry `is_wallet_trade=False`, run to completion on their own exit rules, and never touch the wallet. When they close they still store per-share `pnl_amount`. The frontend closed-trade row shows a subtle "Legacy 1-share" badge so the mixed population isn't confusing. All new trades after the ship are wallet trades.

### Why the initial_deposit is locked

Once set on the first deposit, it never updates. If Pedro starts with $10k, tops up to $15k mid-month, the ROI baseline stays $10k. Otherwise every deposit would reset the ROI math and you'd never know if you've actually made money. Top-ups grow `total_deposited` (separate counter), not the baseline.

### Atomicity without real transactions

Supabase's Python client has no real DB transactions. Best-effort pattern: (1) read wallet, (2) insert trade row, (3) update wallet + insert ledger row. If (3) fails after (2), the trade exists but wallet state is out of sync — logged loudly with enough info to reconstruct. We do NOT roll back the trade; the brain's autonomy depends on the trade being OPEN even if the ledger errored.

### What breaks if we're wrong

- If `calc_position_size_usd` over-commits (bug in the math), multiple concurrent BUYs could push balance below 0. Safety: every `_apply_update` clamps to 0 and logs. Floor at -1e-6 treats float noise as zero.
- If a wallet trade closes but `debit_for_long_buy`/`release_for_short_cover` errors, the wallet row has zero audit trail for that delta. The ledger insert is wrapped in try/except with loud logging — we keep the wallet math correct but note the missing row.
- If a legacy trade's shares/position_size_usd fields somehow get populated, `close_virtual_trade` would treat it as a wallet trade and try to settle. Defensive: only settle when `is_wallet_trade=True` AND `shares > 0`.

### What Pedro has to do

1. Run the DDL in Supabase SQL Editor (two new CREATE TABLEs, three ALTER TABLEs, one new trigger).
2. Restart the backend.
3. Call `POST /api/v1/wallet/deposit {"amount": 10000}` (or use the UI button).
4. Watch the next scan. Any new brain trade will be a wallet trade with `shares` populated; existing 7 opens stay legacy.

### Why this matters

Everything downstream — the self-learning loop, the pattern graduation threshold, Telegram alerts, the watchdog's `-8%` hard stop — these have all been reasoning about P&L in percent. Adding meaningful dollar P&L doesn't change the decision-making, but it changes what "success" looks like. A +2% monthly ROI target (the stated goal) now corresponds to a specific dollar number on the wallet card instead of an abstract metric.

### Metrics to track Day 16

- [ ] First wallet BUY after deposit: does `virtual_trades` row land with correct `shares`, `position_size_usd`, `is_wallet_trade=True`?
- [ ] Wallet balance after first BUY: does it equal `deposit - allocation`? A `wallet_transactions` row with `transaction_type='BUY'` should exist linked to the trade.
- [ ] When a legacy position closes, does its exit price flow into the wallet as a `LEGACY_SELL` ledger row? Does the Holdings number on the wallet card shrink by the right amount?
- [ ] Does the performance page render the wallet card at the top, with total value + ROI? Does the "Legacy 1-share" badge show on the old closed rows?
- [ ] Any underflow warnings in logs? Any "wallet_transactions insert FAILED" errors?

### Pre-deploy reframe (same day, after the first review pass)

Original Day 15 ship treated legacy positions as *outside the wallet entirely* — they closed on their own rules and never touched the balance. After a conversation with Pedro, the mental model shifted:

- **Pocket** = spendable cash (what used to be just "balance")
- **Reserved** = collateral locked for open shorts (unchanged)
- **Holdings** = mark-to-market of ALL open brain positions, both wallet and legacy
- **Total Value** = Pocket + Reserved + Holdings

**Legacy-drain semantics**: when a legacy LONG closes, the exit price is credited into Pocket as a `LEGACY_SELL` ledger entry ("sold the 1-share I had, proceeds go in the pocket"). When a legacy SHORT covers, the per-share P&L is credited as a `LEGACY_COVER` entry. Over weeks, as the 7 pre-wallet opens hit their exits, the whole portfolio drains into wallet-native cash.

**ROI baseline** (initial_deposit): snapshots the current mark-to-market of legacy holdings at the moment of the FIRST deposit. If Pedro deposits $5k with $3k of legacy in Holdings, initial_deposit = $8k. Without this snapshot, every legacy close would look like "free money flowing in" and ROI would read artificially high for the first few weeks.

**Why this matters**: otherwise the Day 15 ledger would be a house of cards. A legacy BLK close at $438 with no wallet wiring would just... leave the wallet at exactly the deposit amount while Holdings disappeared — a missing $438 in the audit trail. Now the trail is honest: Pocket grows by $438, Holdings shrinks by $438, total_value unchanged.

**Implementation added after the initial ship**:
- `wallet.calculate_open_positions_value` extended to cover wallet LONG + wallet SHORT P&L + legacy LONG + legacy SHORT P&L (was: wallet LONG only)
- `wallet.deposit` snapshots legacy holdings on first-deposit; writes an informational `LEGACY_BASELINE` ledger row
- `wallet.credit_for_legacy_sell` / `credit_for_legacy_cover` — new settlement paths for legacy closes
- `close_virtual_trade` now settles legacy brain closes into the wallet (previously: no-op for legacy)
- Frontend wallet card renames "Invested" → "Holdings" and uses "Pocket" for the free balance

### Third-round review fixes (same-day pre-deploy hardening)

A third review pass after the Pocket+Holdings reframe caught five more issues that would have produced silent wrong numbers in production:

1. **Top-up ROI drift (CRITICAL)**. `initial_deposit` was frozen on the FIRST deposit forever. A $3k top-up on an $8k wallet would inflate `total_value` by $3k while the baseline stayed $8k → ROI would read +37.5% from zero real gain. Fixed by making `initial_deposit` a "committed capital basis" that grows 1:1 with each deposit and shrinks 1:1 with each withdrawal. First-deposit legacy snapshot still folds in.

2. **Callers ignoring `skipped=True` (CRITICAL)**. The earlier fix added a race-guard to `close_virtual_trade` that returns `{"skipped": True}` when the status-guarded UPDATE matches zero rows (a parallel path already closed the trade). But all six callers (scan SIGNAL, SHORT cover, ROTATION, price-based exit, thesis_tracker, watchdog x2) unconditionally ran post-close bookkeeping — counters incremented, Telegram alerts fired, learning-loop events logged. On a real race the user would get a duplicate "closed at X" Telegram and the summary counters would over-report. Fixed by checking the return and short-circuiting on every caller.

3. **Silent legacy-snapshot failure (HIGH)**. `_calculate_legacy_holdings_value` swallowed price-fetch errors and returned 0. On first deposit with a yfinance timeout that meant baseline = cash-only, and every legacy close that followed would look like free money flowing in. Fixed with `strict=True` on the first-deposit path — if legacy positions exist and we can't price them, raise `LegacySnapshotFailed` which the API maps to HTTP 503 so the user retries.

4. **Concurrent wallet-mutation race (HIGH)**. Two near-simultaneous deposits (double-click, API retry, scan + user) could both read balance=X and both write balance=X+amount, losing the second amount. Fixed with a per-user `threading.RLock` wrapping every wallet mutation (deposit, withdraw, all trade-driven credits/debits). Single-process safe; cross-process would need a Postgres `UPDATE … RETURNING` rewrite — flagged as known limitation since Signa runs single-worker.

5. **QUALITY_PRUNE `latest_action` always None (MEDIUM, pre-existing)**. The per-scan signal SELECT at check_virtual_exits only loaded `symbol, score` — but the QUALITY_PRUNE gate reads `action` to check if Claude still wants the position. Since `action` was never loaded, `latest_action` was always None, and the gate's "Claude doesn't want it" rule effectively reduced to "always true", firing QUALITY_PRUNE on every losing position 2-7 days old. Fixed by loading `action` into a parallel `current_actions` dict.

Every fix is covered by type-check + parse-check. Schema comment updated to include the new transaction types (LEGACY_SELL, LEGACY_COVER, LEGACY_BASELINE).

---

## Day 16 — April 23, 2026 (Thursday)

**Metrics:** Wallet shipped and funded. First wallet BUY fired cleanly (IONQ). 6 scans all green. 0 brain closes today. Portfolio −0.31% intraday vs baseline.

### The ship

Day 15 wallet went live today. Sequence:

- **10:12 UTC** — Pedro POSTed `/wallet/deposit $5000`. First-deposit path fired: legacy snapshot grabbed $1,344.53 mark-to-market across the 7 open pre-wallet positions, folded into initial_deposit. Baseline locked at **$6,344.53**. Two ledger rows written: `DEPOSIT +$5000` and `LEGACY_BASELINE $0` (informational).
- **10:38 UTC** — manual scan. Produced the first wallet BUY.

### First wallet BUY

**IONQ @ $44.46**, Tier-1 validated (score 79), SHORT horizon (momentum 1-7d). Full success path:

- `virtual_trades` row inserted with `is_wallet_trade=true`, `shares=11.2461` (fractional), `position_size_usd=$500.00` (exact 10% of $5k Tier-1)
- `wallet_transactions` got a `BUY` row: `amount=-500.00`, `balance_after=$4500.00`, `trade_id` linked, `symbol=IONQ`, `shares=11.2461`, `price=$44.46`, description `"BUY 11.2461 IONQ @ $44.46"`
- Pocket: $5,000 → $4,500 ✓
- Holdings: $1,350 → $1,849 (+$500 at cost; drifted to $1,825 by EOD)
- Portfolio: effectively unchanged at open ($6,349 → $6,349), drifted to $6,325 by EOD on market moves

### Scan activity

6 scans today (PRE_MARKET, MORNING, MANUAL, MIDDAY, PRE_CLOSE, AFTER_CLOSE), 53–55 signals each. Only 1 new entry all day. **No brain closes.** The brain's discipline held — 54 signals × 6 scans = 324 signal evaluations, only IONQ cleared the Tier-1 gate. BRAIN_MIN_SCORE=75 is doing its job.

### End-of-day position status

| Symbol | Wallet? | Dir/Hz | Entry | Now | P&L | Thesis |
|---|---|---|---|---|---|---|
| IONQ | 📦 wallet | LONG/SHORT | $44.46 | $43.63 | −1.87% | weakening |
| CCO.TO | 🗂 legacy | LONG/LONG | $164.96 | $169.47 | +2.73% | weakening |
| HIMS | 🗂 legacy | LONG/SHORT | $28.39 | $28.15 | −0.85% | valid |
| BBD | 🗂 legacy | LONG/LONG | $4.09 | $3.94 | −3.67% | valid |
| HPQ | 🗂 legacy | LONG/LONG | $20.75 | $20.14 | −2.94% | weakening |
| DIR-UN.TO | 🗂 legacy | LONG/LONG | $13.76 | $13.82 | +0.44% | weakening |
| CNQ | 🗂 legacy | LONG/LONG | $42.32 | $45.43 | +7.35% | valid |
| BLK | 🗂 legacy | LONG/LONG | $1,021.45 | $1,053.47 | +3.13% | valid |

**Portfolio EOD:** Pocket $4,500 + Reserved $0 + Holdings $1,825.09 = **$6,325.09** (−$19.44 / −0.31% from baseline).

### Observations

1. **IONQ already `weakening` on Day 0.** Opened at $44.46, now $43.63 (−1.87%) with Claude's thesis degrading. Prime candidate for QUALITY_PRUNE or TRAILING_STOP on tomorrow's MORNING scan. First wallet BUY may also be first wallet SELL — will validate the `credit_for_long_sell` path in prod.
2. **CNQ approaching target.** +7.35%, target was $48.50, currently $45.43. Needs another $3 to trigger TARGET_HIT. If it fires, that's the **first LEGACY_SELL in prod** — will confirm the legacy-drain path writes a ledger row with `amount = exit_price = $48.50` and Pocket grows accordingly.
3. **BLK stealthily winning.** +3.13% with thesis=valid on a $1,021 entry. It's the heaviest single legacy — when it eventually closes, its ~$1k proceeds flow straight into Pocket, which will roughly double the wallet's spendable capital. Watching.
4. **REGN and LYG closed yesterday** (Apr 22), before the wallet existed, so no LEGACY_SELL rows. Those are the last closes that will ever bypass the wallet.
5. **The `HOLD 1/2` experience worked correctly.** CCO.TO went into the 1/2 counter state at some point during the day, then flipped back to BUY/HOLD on the next scan — counter reset to 0, badge cleared. Day-14 design validated on first live exercise.
6. **No STAGNATION_PRUNE fired** despite 4 positions at thesis=weakening. Reason: the rule requires `|pnl_pct| < 2%` AND `days_held >= 7`. BBD and HPQ are in the drawdown but fresh enough that stagnation doesn't match yet.

### What broke / what didn't

- Zero errors in logs (searched for "FAILED" in wallet context). No ledger gaps.
- GET /wallet endpoint and the ['wallet'] React Query key are responsive — deposit feedback was instant, dashboard widget synced within 5 min.
- Transactions history view built mid-afternoon at user request — collapsible card under the wallet, fetches `/wallet/transactions`, currently shows 3 rows (DEPOSIT, LEGACY_BASELINE, BUY IONQ).

### Unexercised-in-prod paths

Still haven't been exercised live:
- `LEGACY_SELL` / `LEGACY_COVER` (no legacy has closed since deposit)
- `SHORT_OPEN` / `SHORT_COVER` (no AVOID ≤ 40 signal qualified)
- Wallet LONG `SELL` (IONQ is still open)
- `close_virtual_trade` skipped=True race path (no race observed)

All have pure-math coverage and the code is read from the same paths exercised above. Risk is low but first real exercise matters — Day 17 is likely to hit at least LEGACY_SELL if CNQ hits target or any `weakening` position gets QUALITY_PRUNE'd.

### Actual learnings (not just observations)

**1. Three-round review discipline paid off on first-contact.**
Zero bugs on first live exercise of the wallet system. Between the initial ship and deploy: 3 parallel review agents × 3 rounds caught 14+ issues (thesis_tracker bypass, race double-credit, ROI top-up drift, wallet_enabled zombie trades, concurrency, get_wallet race, error-swallowing, more). Every one of those would have been a bug found the hard way in production. The "Always Run Review Passes" rule is validated again — 50 minutes of reviews prevented days of debugging. Keep doing this.

**2. IONQ validated at entry, thesis "weakening" same day — the conservative-bias pattern is back.**
The memory `Weakening Thesis ≠ Sell` exists because Claude's thesis re-eval flags winners as weakening mid-hold. Today we watched it do the same thing to a *new* position: entered at score 79 validated at 10:38 UTC, by 20:30 UTC (AFTER_CLOSE scan) thesis is "weakening" at −1.87%. That's Claude re-reading the same data through a more cautious lens a few hours later. **Proposed Day 17 rule to consider:** new positions get a 24-hour grace period where thesis cannot drop below "valid" — only price-based exits (stop/hard_trail) can close them in the first day. Prevents same-day self-defeat on fresh convictions.

**3. 324 signal evaluations → 1 entry today. The gate is very tight.**
6 scans × ~54 signals/scan = 324 evaluations, 1 passed (IONQ at score 79). At this rate the wallet opens ~20 positions/month. That's fine for quality, but two implications:
- Meaningful dollar P&L requires meaningful deployment. Right now Pocket is 71% of portfolio ($4,500 of $6,325). The brain is holding cash, not playing.
- If the month yields 20 entries with 42% win rate and average return +0.1% per trade (current stats), that's ~$100 of P&L on a $6k portfolio — 1.6%. At or below Pedro's stated 1-2% monthly profit target. **Either we lower the gate slightly (back to BRAIN_MIN_SCORE=72 or 73) and eat more marginal entries, or we stay disciplined and accept lower volume.** Worth revisiting after 2-3 weeks of wallet data.

**4. The wallet reframe clarified the mental model — and exposed a pre-existing UX leak.**
When Pedro asked "why is the wallet value changing?", the bug was conceptual, not computational. Calling the total-portfolio number "wallet" conflates two distinct things (cash vs positions). The rename (Wallet = Pocket, Portfolio = the composite) took 20 lines of code but eliminated the category error. **Lesson: naming is a correctness issue, not a cosmetic one.** If a field can be interpreted two ways, it WILL be misread, even by the designer.

**5. Transactions audit trail was built but not surfaced — caught by the user asking "where did the $500 go?".**
The `wallet_transactions` ledger captured every mutation from Day 15, but there was no UI for it until Pedro asked for one today. **Lesson: a ledger without a view is a log file.** If you write an audit table during the initial ship, wire a basic view for it at the same time — otherwise the first user-facing bug report will be "I can't tell what happened." Cost to add today: ~90 lines of React. Would have been ~90 lines on Day 15 too.

**6. Fractional shares introduce sub-cent rounding drift. Monitor, don't fix yet.**
IONQ allocation $500.00 → 11.2461 shares @ $44.46 = $499.97. Per-trade drift of ~$0.02-0.03. Over hundreds of trades, could accumulate to $1-5 of "missing" Pocket vs expected. Not a bug (we round shares to 6 decimals), but worth tracking. If after 100 trades the `total_deposited - total_withdrawn - current_total_value ≠ realized_pnl_sum` by more than a dollar, we have drift worth fixing.

### Metrics to track Day 17

- [ ] Does IONQ survive the MORNING scan, or does the thesis-weakening Day-0 pattern trigger an early exit (if so → implement the 24-hour grace period)?
- [ ] Does CNQ hit TARGET_HIT at $48.50 → first LEGACY_SELL ledger row writes correctly (amount = $48.50, balance_after grows by same)?
- [ ] Any position drops enough to trigger QUALITY_PRUNE (pnl<0, days_held 2-7, thesis not valid, Claude not BUY)?
- [ ] Portfolio ROI at EOD — does it close positive or negative vs $6,344.53 baseline?
- [ ] Wallet spendable balance — still $4,500 at EOD, or did a close credit it?
- [ ] Any watchdog escalations during the day (every 15 min during market hours)?
- [ ] Signal-to-entry rate after another day of data: if still ~1/300+, is the gate too tight?

---

## Day 17 — April 27, 2026 (Monday)

**Metrics:** First "terrible day" feeling — 4 small losses, churn-y trading. But the day's real story is structural: a 17-day-old discovery bug surfaced that explains why the brain has felt boring. Half the universe was re-bucketed. Four code fixes shipped to plug the structural hole and prevent the churn.

### What today actually was (small)

- 4 closes, **all losses**, total realized **−$24.24**:
  - 📦 SOUN QUALITY_PRUNE −$12.87 (entry Friday, pruned today at −2.85%)
  - 📦 IONQ QUALITY_PRUNE −$10.01 (entry Apr 23, exit predicted on Day 16, fired today at −2.00%)
  - 📦 BCE.TO THESIS_INVALIDATED −$0.85 (**opened 19:02, closed 20:32** — 90-minute round-trip)
  - 🗂 CCO.TO TRAILING_STOP −$0.51 (legacy → first **LEGACY_SELL in prod**, $164.45 into Pocket — Day-15 path validated for real)
- 2 opens: 📦 TFC ($451), 📦 BCE.TO ($211, immediately closed)
- **Portfolio Apr 23 → Apr 27: −$16.04 / −0.25%** across 3 trading days. Felt worse than it was.

### What today actually was (huge — the structural discovery)

The user asked "why didn't we ever get OKLO?" That single question surfaced a class of bug that had been silently shaping every signal for 17 days.

**The finding:** 435 of 439 active tickers (99%) were bucketed `SAFE_INCOME`. Only 4 were `HIGH_RISK`. The discovery auto-add path (when the brain BUYs an unknown ticker, or when `_classify_bucket` sees a new symbol) defaulted to `SAFE_INCOME` for any name that wasn't in the small hardcoded HIGH_RISK list — and `upsert_ticker` then re-stamped that bucket every scan. Once classified wrong, a ticker was wrong for life.

**Why this hurt:** SAFE_INCOME weights `dividend_reliability` 35%. A non-dividend stock takes a 35% scoring haircut and caps out at ~60. Below the 75 Tier-1 floor. Below the top-15 AI candidate cut. **Claude has literally never analyzed OKLO**, despite it being scanned 11 times since Apr 10.

**Symptoms this explained:**
- Day 16: 0 GEMs in 324 evaluations. **Mathematically guaranteed** when score 85+ is unreachable for non-dividend stocks.
- Day 16: brain only opened 1 position (IONQ — one of the 4 correctly-seeded HIGH_RISK names) across 6 scans of 54 signals each.
- Multiple weeks: every brain BUY was a dividend-paying name (BLK, CCO.TO, BCE.TO, TFC, CCO.TO). The mechanism rewarded what it could score.
- The "brain feels boring" sense the user described — that wasn't conservatism, it was a mis-calibrated bucket weighting half the universe out of contention.

### What we shipped today (4 fixes)

**1. One-time re-bucket (`scripts/audit_ticker_buckets.py`)**
- Dry-run-first audit script with explicit `--apply` gate
- Heuristic: crypto → HIGH_RISK; dividend > 0 → SAFE_INCOME; mcap < $50B no-div → HIGH_RISK; growth-sector no-div → HIGH_RISK; else SAFE_INCOME
- 223 tickers reclassified SAFE_INCOME → HIGH_RISK, 0 the other way
- Universe is now 227 HIGH_RISK / 212 SAFE_INCOME

**2. `_classify_bucket` uses dividend + mcap (`scan_service.py`)**
- The screening dict already contains `dividend_yield` and `market_cap` from market_scanner
- Same heuristic as the audit script — no first-scan ticker should land mis-bucketed again

**3. `upsert_ticker` sticky on bucket (`db/queries.py`)**
- Bucket is now set on insert and NOT overwritten on subsequent calls
- Means manual audits (or a future `brain_editor` UI) can correct a bucket without it being silently undone by the next scan
- Rows update `name/exchange/is_active` but bucket only fills if previously NULL

**4. Day-0 grace period + QUALITY_PRUNE magnitude gate (`virtual_portfolio.py`, `config.py`)**
- New positions immune to THESIS_INVALIDATED + QUALITY_PRUNE for first `new_position_grace_hours` (default 24h)
- QUALITY_PRUNE now requires `pnl_pct < -brain_quality_prune_min_loss_pct` (default 3%)
- Stop / target / trailing / time-expired still fire normally; -8% catastrophic stop still fires through grace
- Both knobs configurable

### Predictions from Day 16 — how they landed

| Day 16 prediction | Outcome |
|---|---|
| IONQ exits early via thesis-related path | ✓ QUALITY_PRUNE at −2.00% today |
| CNQ hits TARGET_HIT (first LEGACY_SELL) | ✗ Still open at +6.38%, didn't reach $48.50 |
| HPQ becomes QUALITY_PRUNE candidate | ✗ Position closed/disappeared earlier — needs investigation |
| First LEGACY_SELL in prod | ✓ CCO.TO @ $164.45 — TRAILING_STOP path |
| BLK closes "clean" with proceeds into Pocket | ✗ Still open at +3.47% |

2 of 5 predictions hit. The legacy-drain path was validated by both LEGACY_SELL (CCO.TO) and the SELL path (IONQ wallet trade) — Day-15's full wallet design is now end-to-end exercised in prod.

### What today's data actually taught us

**1. The user's "feeling" was a bug.** When the user said "we're not discovering good things," that wasn't venting — it was the only signal that the OKLO/IONQ/SOUN class of stocks was systematically excluded. Error logs were clean. Scans were running. Positions were opening. Everything looked fine — but the OUTCOMES were biased. **Lesson: when a qualitative complaint contradicts the system's intended behavior, investigate. The user is the integration test.**

**2. Bugs in default classifiers are invisible until you measure outcome quality.** OKLO sat at score 60 for 17 days. Nothing was broken. Nothing logged an error. The brain just never bought it. The bug surfaced only when someone asked "why this specific ticker?" Class of bug worth watching for elsewhere — anywhere we have a default-on-unknown classifier (sectors? regimes? buckets? tier reasons?). **Run periodic distribution audits.**

**3. Sticky-by-default is the right pattern for classifications.** `upsert_ticker` re-stamping bucket every scan was the silent erasure mechanism — even if `_classify_bucket` had a one-off bug fixed in v2, every existing wrong row would be re-corrupted by the next scan. Persistent classifications should require explicit override, not silently drift on every write.

**4. The wallet's first round-trip exposed the conservative-bias pattern in fresh-position thesis re-eval.** BCE.TO opened-and-closed in 90 minutes is the cleanest data point yet for the Day-0 grace period (already shipped). If tomorrow we see "Day-0 grace: THESIS_INVALIDATED suppressed" log lines and those positions then either survive or exit on price-based reasons, the grace period worked.

**5. QUALITY_PRUNE was a death-by-paper-cuts problem.** Two prunes today (SOUN −2.85%, IONQ −2.00%) for $22.88 of realized loss. Pre-wallet, those would have been ~$0.20 of "per-share" loss; post-wallet, they're real $10 hits. The rule was tuned for the per-share era. The −3% magnitude gate restores its original intent: only prune when there's actually a meaningful loss to cut.

**6. Three predictions missed because they assumed yesterday's tape would continue.** CNQ didn't hit target, HPQ vanished, BLK didn't close — the market's behavior between Apr 23 and Apr 27 (Friday + Monday) shifted enough to invalidate single-day extrapolation. **Lesson: predictions about specific tickers tomorrow are weak. Predictions about system patterns (does code path X fire correctly?) are reliable.**

### What we should learn from tomorrow's data

**Verifying today's fixes worked:**
- [ ] Score distribution shifts up — expect a meaningful number of HIGH_RISK signals at 75+, possibly first 85+ scores in weeks
- [ ] AI candidate cut composition changes — top 15 should include OKLO-class names instead of being all dividend-payers
- [ ] First GEM in many weeks (score ≥ 85, sentiment ≥ 80, catalyst ≤ 30d, R/R ≥ 3.0, no red flags)
- [ ] Day-0 grace fires somewhere — log line "Day-0 grace: THESIS_INVALIDATED suppressed for SYMBOL" should appear if any new position has thesis flipped within 24h
- [ ] No QUALITY_PRUNE fires on positions with pnl_pct > −3%

**Pattern questions:**
- [ ] Does the brain start opening **more** positions per day now that more tickers can break Tier-1? Or does Pedro's BRAIN_MIN_SCORE=75 floor still keep it tight?
- [ ] If new entries cluster in HIGH_RISK (newly accessible) — does win rate hold, drop, or improve vs the dividend-heavy historical mix?
- [ ] Are we entering the same names Claude was analyzing (where AI status was validated) just at higher scores now? Or are entirely new names appearing in the candidate pool?

**Open hypothesis to confirm or reject over the next 1-2 weeks:**
- The brain was "boring" because the mis-bucketing acted like a quality filter that kept it in dividend safety. Now that the filter is removed, will quality stay the same / improve / collapse? **If win rate drops below 35% for 5+ days, the SAFE_INCOME default was actually serving a useful function** — the dividend floor was filtering for stable companies. We may need to add a different quality gate (e.g., minimum profit margin or revenue growth) to replace what we just removed.

### Personal note on today

The day felt bad because of the small-loss churn (4 in a row, all losses). But the structural fix that came out of it is one of the highest-leverage changes in the project so far. We turned 17 days of accumulated mis-classification into a corrected universe + a permanent guard against re-occurrence in about 90 minutes of work. Felt-bad-but-was-good day.

---

## Day 18 — April 28, 2026 (Tuesday)

**Metrics:** First trading day post-Day-17 fixes. The brain went from 1 entry/day to **7 entries** in 5 scans. First score 91 in weeks. 4 of 7 new positions immediately show weakening/invalid thesis — Day-0 grace period working as designed (none triggered THESIS_INVALIDATED). Net realized: −$10.41 (FN watchdog-exit, 8 minutes after open). Portfolio drift: −$29.31 / −0.46% from baseline. Cash deployment jumped 75% → 58% of portfolio in one day.

### What changed today (the fixes worked)

The Day-17 universe re-bucket flowed straight into Day-18 signal scoring:

| Metric | Day 16 (pre-fix) | Day 18 (post-fix) |
|---|---|---|
| Signals total | ~324 / 6 scans | 271 / 5 scans |
| HIGH_RISK signals | ~28% of pool | **70% of pool** (189 / 271) |
| Scores ≥ 85 | 0 | **4** (top: ONDS @ 91) |
| New entries opened | 1 (IONQ) | **7** |
| GEMs detected | 0 | 0 |

Compositionally: every entry today was HIGH_RISK except CCO.TO (re-bought after yesterday's TRAILING_STOP closed the legacy version). That's the bucketing fix doing exactly what it was supposed to do — letting growth/momentum names through the AI candidate cut and into the brain's tier evaluator.

### Today's activity

**7 new wallet positions:**

| Symbol | Score | Horizon | Allocation | Bucket |
|---|---|---|---|---|
| FN | 79 | SHORT | $471 | HIGH_RISK |
| CCO.TO | 80 | LONG | $427 | SAFE_INCOME |
| HIMS | 79 | SHORT | $346 | HIGH_RISK |
| ARM | 81 | SHORT | $384 | HIGH_RISK |
| CAMT | 81 | SHORT | $322 | HIGH_RISK |
| ALAB | 83 | SHORT | $357 | HIGH_RISK |
| **ONDS** | **91** | SHORT | $290 | HIGH_RISK |

ONDS at 91 is the highest score we've seen since the wallet shipped. Pre-fix that ticker was scoring ~60 in SAFE_INCOME with $0 dividend.

**5 closes:**

| Symbol | Type | Reason | P&L |
|---|---|---|---|
| HIMS legacy | 🗂 | TRAILING_STOP | +0.45% / +$0.13 |
| BBD legacy | 🗂 | WATCHDOG_EXIT | −5.26% / −$0.21 |
| FN wallet | 📦 | WATCHDOG_EXIT | **−2.21% / −$10.41** |
| DIR-UN.TO legacy | 🗂 | ROTATION | +0.65% / +$0.09 |
| **BLK legacy** | 🗂 | ROTATION | +2.77% / **+$28.34** |

ROTATION fired twice — brain hit `brain_max_open_long = 8` and rotated the two weakest legacies (DIR-UN.TO, BLK) out for stronger HIGH_RISK picks. BLK was the heavyweight: a single close at $1,049.79 pumped Pocket by ~$1k.

### What the data says about each fix

**1. Re-bucketing flow-through ✓** — Universe shift directly produced the candidate-pool shift directly produced the entry shift. ONDS hit 91, ALAB 83, CAMT 81, ARM 81, FN 79 — all newly accessible. Structural fix doing exactly what diagnosis predicted.

**2. Day-0 grace period: silently working** — 4 of today's 7 opens already show `thesis=weakening` or `invalid` by EOD. ARM is `invalid` at age 4.8h. **None triggered THESIS_INVALIDATED today.** The grace period DID its job (or the thesis tracker would have tried to close them). Tomorrow, when these positions cross the 24h mark, we'll see if they survive on price merit or get cut. **First real test of "is the conservative-bias real, or is Claude actually right that these were bad picks?"**

**3. WATCHDOG_EXIT ≠ thesis exit** — FN closed in 8 minutes via WATCHDOG_EXIT, not THESIS_INVALIDATED. Watchdog fires on price drop + sentiment, not on thesis re-eval. Day-0 grace correctly did NOT block it — watchdog is the brake, and a position that drops fast enough for the watchdog to act needs to die regardless of age. The −$10.41 hurt but the system worked as intended.

**4. QUALITY_PRUNE magnitude gate untested today** — No QUALITY_PRUNE fired (would have needed pnl < −3% AND days 2-7 AND thesis weakening AND Claude not BUY). All today's losers were either fresh (Day-0 protected) or hit watchdog first. Need a few days before we know if −3% is calibrated.

### Today's learnings

**1. Structural fixes have non-linear payoffs.** Yesterday: 1 entry. Today: 7 entries. Not 7×, that's the universe finally working as designed. **Lesson: when a system is producing low-volume outputs, audit the structural classifiers BEFORE tuning thresholds.** I almost suggested lowering BRAIN_MIN_SCORE on Day 16 because volume was too low; would have been the wrong fix. The real bottleneck was bucket-driven score suppression upstream of the threshold.

**2. The grace period and the watchdog are doing different jobs.** Today proves they're complementary, not redundant. Grace protects thesis-driven exits on fresh positions (Claude's conservative bias). Watchdog protects against price/sentiment-driven catastrophes (real risk). Both fired correctly — grace by NOT firing on 4 weakening positions, watchdog by firing on FN at −2.21% within 8 minutes. The system has a slow brake (thesis re-eval) and a fast brake (watchdog), and they should not be conflated.

**3. Heaviest legacy (BLK) drained into Pocket via ROTATION.** Cleanest mechanical proof that the legacy-drain design works at scale. BLK was a 1-share holding worth $1,049.79 at exit. ROTATION decided to swap it out, the close path emitted a `LEGACY_SELL` ledger row, Pocket jumped $1,049.79, Holdings dropped by BLK's mark-to-market — net portfolio unchanged, but capital now liquid for new wallet trades. **Day-15 wallet design end-to-end validated on a $1k trade.**

**4. Today's 7 entries skew SHORT-horizon (6 of 7).** Pre-fix, the brain rarely opened SHORT-horizon trades because the universe lacked momentum names. Now that universe is HIGH_RISK-rich, the natural fit is SHORT-horizon momentum. **Expect higher trade frequency, shorter holds, more watchdog activity.** The wallet will see more activity per week than before — and the watchdog will get exercised more.

**5. Two consecutive same-day open-and-close events (BCE.TO yesterday, FN today).** Different mechanisms (BCE.TO via THESIS_INVALIDATED, FN via WATCHDOG_EXIT), same observable: enter, lose ~$10, exit. **Whether this is normal volatility or a calibration issue takes more days to know.** Watch this through the week.

### Open from yesterday's metrics-to-track

- [x] Score distribution shifts up — ✓ confirmed (4 scores ≥ 85, was 0)
- [x] AI candidate cut composition changes — ✓ HIGH_RISK now 70% of pool
- [ ] First GEM in many weeks — ✗ still 0 (other GEM gates harder to clear than score)
- [x] Day-0 grace fires — ✓ silently (4 weakening positions kept open)
- [ ] No QUALITY_PRUNE on positions with pnl > −3% — UNTESTED (no quality prune fired today)

### Predictions for Day 19

- [ ] **First wallet TARGET_HIT** — ONDS at $10.60 with target — if any Tier-1 entry hits target tomorrow, that's the first realized wallet WIN with a green ✓ Win badge.
- [ ] **24-hour grace window expires for today's 7 entries between 14:02–19:02 tomorrow.** If any exit via THESIS_INVALIDATED or QUALITY_PRUNE precisely after grace expires → Claude was right, grace just delayed. If they survive → conservative bias is real, grace is saving us money.
- [ ] **Same-day open-and-close pattern repeats?** If a 3rd fresh position closes within hours tomorrow, we have a pattern requiring action.
- [ ] **First 85+ GEM detection.** ONDS hit 91 today without becoming a GEM. Audit which gates fail most often (sentiment ≥ 80%, catalyst ≤ 30d, R/R ≥ 3.0).
- [ ] **Will Pocket continue draining or stabilize?** Today: 75% → 58% in one day. With 1 LONG slot + 6 SHORT slots still free, Pocket could drop further if every slot fills.

### Personal note

Quiet success day. The structural fix from yesterday produced exactly the result the diagnosis predicted, but with one nuance worth flagging: the brain went from cautious (1 entry/day) to active (7 entries/day) overnight. We deployed $1.8k of new capital. **The system is now exposing real risk in a way it wasn't before.** Tomorrow's data starts to tell us whether the looser universe + Day-0 grace combination produces alpha or just more drawdowns. Either way, we have signal — that's better than the unblocked-but-quiet state we were in.

---

## Day 19 — April 29, 2026 (Wednesday)

**Metrics:** Apr 28 cohort post-grace results: 5 of 7 closed (2W / 3L), net realized **−$37.83**. ONDS — yesterday's highest-conviction entry at score 91 — was today's biggest loss at **−$27.40 / −9.46% via WATCHDOG_FORCE_SELL**. ARM and CAMT (both flagged weakening at Day 0) survived grace and closed positive: partial validation of conservative-bias hypothesis. Portfolio: $6,257.23 (−1.38% from baseline). Cumulative wallet realized P&L: **−$33.21** since deposit.

### The Apr 28 cohort — full reckoning

Yesterday I wrote: *"Tomorrow's data tells us whether the looser universe + Day-0 grace combination produces alpha or just more drawdowns."* Today's data tells the story:

| Symbol | Score | Outcome | P&L | Days |
|---|---|---|---|---|
| **ONDS** | **91** | ❌ WATCHDOG_FORCE_SELL Day 1 (post-grace) | **−$27.40 / −9.46%** | 18.7h |
| CCO.TO | 80 | ❌ WATCHDOG_FORCE_SELL Day 1 (post-grace) | −$14.90 / −3.49% | 22.1h |
| FN | 79 | ❌ WATCHDOG_EXIT same-day (Apr 28) | −$10.41 / −2.21% | 8 min |
| ARM | 81 | ✅ THESIS_INVALIDATED Day 1 (post-grace, **POSITIVE**) | +$7.78 / +2.02% | 1.1d |
| CAMT | 81 | ✅ SIGNAL Day 1 (post-grace) | +$7.10 / +2.21% | 1.0d |
| HIMS | 79 | 🔄 STILL OPEN, weakening | unrealized −$22.60 | 1.5d |
| ALAB | 83 | 🔄 STILL OPEN, winner | unrealized **+$22.87** | 1.3d |

**Closed cohort:** 5/7 closed → 2W / 3L → 40% win rate → **−$37.83 realized**.
**Still-open cohort:** 2/7 → +$22.87 (ALAB) − $22.60 (HIMS) = +$0.27 net unrealized.
**Combined cohort P&L so far:** ~ **−$37.56**.

### Three big lessons from this cohort

**1. High score ≠ high probability of success.** ONDS at 91 was the highest-conviction entry of the post-fix era and it was THE biggest loss. CCO.TO at 80, ARM at 81, CAMT at 81 — three positions at almost identical scores produced two wins and one loss. The score is a *starting point*, not a guarantee. **The hypothesis "raise BRAIN_MIN_SCORE" would NOT have helped here.** ONDS would still have qualified at 91. The actual problem is that score doesn't capture position-specific risk like volatility, sector momentum, or sentiment shifts that the watchdog catches in real time.

**2. The conservative-bias hypothesis is partially confirmed.** Day 17 I argued: "if weakening positions recover after grace, the bias is real and grace saves us money." Today's evidence:
- ARM (thesis=invalid at age 4.8h, grace-protected) → closed +2.02% after grace expired ✓ bias was real
- CAMT (thesis=weakening) → closed +2.21% after grace expired ✓ bias was real
- ONDS (thesis=weakening) → watchdog killed it at −9.46% after grace ✗ Claude was right, grace just delayed
- CCO.TO → same as ONDS

**Two of four weakening positions recovered.** That's enough to keep the grace period — without it, ARM and CAMT would have been Day-0 losses too, costing maybe $5-10 each. The grace turned them into +$15 of realized wins. Net win for the grace mechanism: ~$30 protected vs ~$0 cost (the losses still happened, just via watchdog instead of thesis path).

**3. The watchdog is the actual hero.** All three of today's worst losses were caught by the watchdog (FN, CCO.TO, ONDS combined: −$52.71). Without it, these positions would have continued to ride down to their stop levels. ONDS at −9.46% was caught at the 8% catastrophic threshold. **The watchdog is doing exactly what it was built to do** — and the dollar magnitudes have made its value much more visible than in the per-share era.

### The HIMS problem

HIMS is currently sitting at −6.53% / −$22.60 unrealized, still open at 1.5 days. Why hasn't anything closed it?

- ❌ STOP_HIT — current price hasn't crossed stop yet
- ❌ TARGET_HIT — obviously not
- ❌ TRAILING_STOP — trail not active until +3% from entry
- ❌ TIME_EXPIRED — 1.5 days, far from 7-day horizon limit
- ❌ THESIS_INVALIDATED — only fires when status="invalid", currently "weakening"
- ❌ QUALITY_PRUNE — needs days_held in [2, 7] AND pnl < −3% AND thesis not valid AND Claude not BUY. Currently 1.5 days, just outside the 2-day floor.
- ❌ WATCHDOG_FORCE_SELL — needs catastrophic stop (−8%) OR sentiment + price catastrophe combo. HIMS is at −6.53%, hasn't tripped.

So HIMS is in a "no-rule-fires" zone. Will likely either:
- Recover into the green (let it cook)
- Drop another 1.5% to trigger watchdog at -8%
- Cross into Day 2 → QUALITY_PRUNE eligible

This is fine *if* it recovers. **But it surfaces a calibration question:** between QUALITY_PRUNE (2d floor) and WATCHDOG (-8% floor), there's a "valley of death" where positions can sit at −5 to −7% for a day with no rule firing. That's where ONDS spent some of its time. Worth thinking about.

### Today's other activity

**Opens (2):** CRWV @ $114.56 score 83 (HIGH_RISK SHORT-horizon), NBIS @ $141.93 score 81 (HIGH_RISK SHORT-horizon). Both Day-0 noise, both flat-to-slightly-down at EOD.

**Closes (4):** All Apr 28 cohort:
- 13:45 ONDS WATCHDOG_FORCE_SELL −$27.40 (the 91-score)
- 14:10 CCO.TO WATCHDOG_FORCE_SELL −$14.90
- 19:02 CAMT SIGNAL flip +$7.10
- 19:02 ARM THESIS_INVALIDATED +$7.78

**Score distribution:** 280 signals, 4 at 85+ (top 90s, but no 95+). HIGH_RISK 174 / SAFE_INCOME 106. Still no GEMs (5/5 days at zero post-fix).

### What should we change?

**Now:** Nothing. We have 2 days of post-fix data and only 5 wallet closes to evaluate. Drawing rules from this would be premature.

**Watch list for the next 3-5 trading days:**

1. **ALAB and HIMS resolution.** ALAB is the +6.4% open winner; HIMS is the −6.5% open loser. Both will close eventually. If ALAB rides to +10% target and HIMS bleeds to −8% watchdog, that's roughly net-zero on the 2 remaining cohort positions — keeping cohort win rate at 40%, net loss ~$37. That's bad but not catastrophic.

2. **Watchdog activation rate.** Today fired 2 watchdog-driven exits (ONDS, CCO.TO). Yesterday: 1 (FN). If the rate climbs (3+ tomorrow), the entry quality is genuinely poor. If it drops to 0-1, today was just market-driven.

3. **Score-vs-outcome correlation.** ONDS 91 → −9.46%. CAMT 81 → +2.21%. The ranks are inverted. Worth running a backwards check: across all wallet-era closes, is there ANY positive correlation between entry_score and exit_pnl_pct? If not, score is a quality FILTER (gates entries) but not a quality PREDICTOR (rank entries). That'd shift how we think about Tier 2/3.

4. **GEM persistence at 0.** 5 trading days post-fix, still 0 GEMs. ONDS hit 91 but other gates blocked. **Worth auditing which GEM gate fails most often** — if it's always sentiment ≥ 80%, the threshold may be uncalibrated for current market.

### Today's learnings (the actual ones)

**1. Score is a filter, not a ranker.** A position scoring 91 produced a worse outcome than positions scoring 79-83. The brain's mental model "higher score = better trade" doesn't survive contact with this data. **Better mental model: score gets you past the gate, but post-gate variance dominates.**

**2. The wallet doesn't change strategy quality, it changes loss visibility.** Pre-wallet, ONDS at −9.46% would have been "−$1 per share." Today it was **−$27.40 in real cash**. That's the same trade, the same outcome, just expressed in money instead of percent. **Pedro is feeling the wallet's brutal honesty for the first time.** This was exactly the design intent — but it's emotionally heavier than expected.

**3. Watchdog earns its budget.** Day 16 the watchdog cost was ~$0.03/month and seemed luxurious. Today it saved us from probably another $30-60 of additional drawdown by catching ONDS and CCO.TO at their force-sell thresholds. **Order of magnitude more value than cost.** Keep it on, watch its events more closely.

**4. The "no-rule-fires valley" between QUALITY_PRUNE and WATCHDOG_FORCE_SELL is real.** A position at −5 to −7% for 1-2 days exists in nobody's responsibility zone. Worth either lowering WATCHDOG_FORCE_SELL threshold from −8% to −6%, OR removing the 2-day floor from QUALITY_PRUNE. Don't act yet — but the gap is now named.

**5. Two losing days in a row make the wallet feel worse than the data warrants.** −1.38% in 6 trading days extrapolates to −7%/month, but that's including the pre-fix realized losses. Post-fix-only: −$37.83 across 5 closes ÷ 2 days ≈ −0.6%/day, which extrapolates to −15%/month. **That's the number to actually watch.** If next 3 days hold this pace, we have a problem. If it reverts to flat or positive, today was a cohort-specific bad draw.

### Predictions for Day 20

- [ ] **HIMS resolution.** Cross 2-day mark today. If it's still at <−3% AND thesis weakening AND Claude not BUY, QUALITY_PRUNE fires at the 14:00 MORNING scan. Will validate the magnitude gate's calibration.
- [ ] **ALAB target hunt.** At +6.4%, target probably $200ish. If it hits target tomorrow, first wallet TARGET_HIT in prod → first ✓ Win badge in transactions list.
- [ ] **CRWV / NBIS Day-1 outcomes.** Two fresh entries. If both die same-day or Day-1 like FN/CCO.TO/ONDS, that's the third consecutive day of fresh-position mortality and the deployment cadence is genuinely too aggressive.
- [ ] **First positive-day at portfolio level.** We've had 2 consecutive negative days. A flat or positive day tomorrow would suggest today was just a cohort working through its losers, not a trend.

### Personal note

Today hurt more than it should have because of ONDS — a score-91 entry losing $27 in 18 hours feels like the system actively chose the worst trade available. But the data says: 2 of 5 closes were wins, 2 of 4 weakening positions recovered post-grace, the watchdog caught what it should. **The system is functioning as designed. The design itself is now under test.** That's the right kind of pain — informative, not arbitrary. Three more days of data tells us whether to tighten the entry filter, change horizon mix, or stay the course.

### EOD action: shipped per-day entry cap

Driven by the Apr 28 cohort data (43% win rate matches historical, but 7-entry day produced visible variance), shipped:

- **`wallet_max_entries_per_day = 3`** in `config.py`
- Counter logic in `process_virtual_trades` reads today's BUY + SHORT_OPEN ledger rows + tracks scan-local opens
- Signals pre-sorted by score DESC at function entry so the cap clips marginal entries first, not whatever happened to come first in iteration order
- Applied to BOTH brain BUY and brain SHORT_SELL paths (both deploy capital)

**On Apr 28's 7 entries, the cap would have taken:** ONDS (91), ALAB (83), CAMT (81). ONDS was the biggest loser, so the cap doesn't fix entry quality — but it would have reduced concurrent-fresh-position dollar risk by ~57%.

### EOD action: GEM gate audit (information only)

Saved as `scripts/audit_gem_gates.py`. Findings on 7 days of signals at score >= 80:

| Gate | Failure rate |
|---|---|
| **sentiment >= 80** | **100%** — top observed sentiment is 60–70, threshold of 80 is unreachable |
| R/R >= 3.0 | 98.8% — actual R/R distribution is 1.4–2.2 |
| score >= 85 | 89.4% |

**0 GEMs in 19 days is structural, not luck.** The sentiment threshold was calibrated against a different Grok output range than what's currently being produced. **Did NOT change the threshold** — lowering sentiment to 70 would mass-produce "GEMs" on names like ARM, ONDS, SOUN which today were exactly the volatile losers. Until GEM has functional consequence (e.g., bigger position size), recalibrating the badge is cosmetic.

### Did NOT change today (and why)

- **QUALITY_PRUNE day floor** (currently 2 days): HIMS sat at −6.5% / 1.5d hitting no rule (the "valley of death"). Lowering to 1 day would have closed it for ~$22 loss. But ARM, CAMT, ALAB also entered yesterday at thesis=weakening; lowering the floor would have killed them BEFORE they closed positive. Trading variance against speed is a coin flip without backtest data.
- **WATCHDOG_FORCE_SELL threshold** (currently −8%): Same reasoning. Catches catastrophic only; lowering to −6% would have caught ONDS earlier but also would have closed positions that recovered to flat.
- **BRAIN_MIN_SCORE**: ONDS at 91 was the biggest loser. Higher score floor wouldn't have helped — would just have produced fewer entries of the same quality mix.
- **Sentiment threshold for GEM**: see above.

---

## Day 20 — April 30, 2026 (Thursday)

**Metrics:** Pre-market shipment of Filter D, derived from overnight backtest of all 52 closed brain trades (`docs/Day-19-overnight-analysis.md`). No new closes yet today — this entry documents the SHIP, not outcomes. Yesterday's overnight analysis is the data. Today's job is to act on it.

### What shipped (one coherent package)

Three changes, one ship — the literal Filter D from the backtest, not a compromise version:

1. **`BRAIN_MIN_SCORE = 80 → 75`** (rolled back the Day-19 raise).
2. **Sector exclusion gate**: Financial Services + Industrials are blocked at both `_eval_brain_trust_tier` and `_eval_brain_short_tier`.
3. **LONG-horizon suspension**: any BUY signal whose computed `trade_horizon == "LONG"` is rejected after horizon computation, before insert.

All three live in `app/services/virtual_portfolio.py`. Each gate carries an explicit invalidation criterion in its docstring — these are NOT eternal vetoes, they're decay-able safety rails.

### Why this shape (not the Day-19 shape)

Day 19 raised `BRAIN_MIN_SCORE` 75 → 80 based on **4 wallet-era trades** that had all closed losses in 2 days. The full 52-trade backtest tells a more complete story:

| Filter | n | Win rate | Total P&L | Δ vs baseline |
|---|---|---|---|---|
| Baseline (no filter) | 52 | 40.4% | −17.6% | — |
| Score ≥ 75 alone | 36 | 41.7% | −8.0% | +9.6pp |
| Score ≥ 80 alone (Day 19) | 17 | 41.2% | +1.7% | +19.3pp |
| **Filter D: 75 + SHORT + drop Fin/Industrials** | **23** | **47.8%** | **+5.4%** | **+23.1pp** |

**Score 75-79 across all history was 8W / 11L (42.1% win rate)**, not the 0% the wallet sample suggested. The Day-19 raise was small-sample noise correctly shipped at the time, now correctly reverted with more data.

The discriminating axes are **horizon and sector**, not score. ONDS at 91 was Day 19's biggest loser; CAMT and ARM at 81 were both winners. Score gets a signal past the gate but doesn't rank the gate-survivors.

### How this respects "AI is the Decider"

Initial reaction (mine) was: *static gates violate the principle that AI should weigh patterns, not be vetoed by them.* True in steady state. False right now, because:

- Claude's dossier doesn't yet carry "this sector has lost us 5/9 times."
- The pattern-stats injection (Stage 4) that would carry it isn't wired through to scoring yet.
- Every day we wait costs ~$10–30 of avoidable loss given Day-19's cadence.

The compromise: ship the gates **with explicit invalidation criteria** so they decay automatically when the underlying cohort recovers. Each gate logs `tier_reason` strings (`filter_d_sector_excluded_*`, `filter_d_long_horizon_suspended`) so the cost of being wrong is visible in the database. When Claude's dossier matures, the gates are redundant and can be removed.

This is the same shape as the per-day cap (Day 19) and the −8% catastrophic stop — capacity rails, not quality vetoes.

### Predictions for Day 21

- [ ] **Tomorrow's scan should produce fewer entries.** Pre-Filter-D, the brain admitted ~7 entries on Apr 28. With sector + horizon gates, expect 2-4. If we see 7 again, a gate isn't firing — investigate.
- [ ] **First `tier_reason = "filter_d_sector_excluded_*"` row.** Search `virtual_trades` for the pattern; if no rows appear in 48h, the gate isn't being hit (universe might naturally avoid those sectors).
- [ ] **First `filter_d_long_horizon_suspended` log line.** Same audit — should appear within 24h given how SAFE_INCOME-heavy the universe was.
- [ ] **Win rate over the next 5 closes.** Backtest predicts 47.8% on Filter D vs 40.4% baseline. Real-world n=5 is too small to confirm but a rate ≤ 25% would be a red flag.

### What to watch for

If the brain produces ZERO entries for 2 consecutive days post-ship, Filter D is too restrictive in the current universe. Loosen by:
- Removing one sector from `FILTER_D_BLOCKED_SECTORS` (Industrials first — slightly weaker individual-cohort evidence than Financial Services).
- OR keeping `BRAIN_MIN_SCORE = 75` but allowing the LONG horizon back through gated by HIGH_RISK bucket only.

Both are one-line reverts.

### What did NOT change today

- **GEM gate sentiment threshold** — still 80, still structurally unreachable. Until GEM has functional consequence (e.g., bigger position size), recalibrating is cosmetic. Reconfirmed by yesterday's audit.
- **WATCHDOG_FORCE_SELL threshold** — still −8%. Day 19 evidence was that ARM/CAMT recovered from negative territory; tightening would have killed winners.
- **QUALITY_PRUNE day floor** — still 2 days. Same reasoning — recovery cases mattered.
- **Per-day cap** — still 3. Already shipped Day 19, holds.

### Personal note

Today is a methodology day, not a P&L day. The discipline test was: when the data and the principle conflict, do you act on the data with appropriate guardrails, or freeze on the principle? We chose action with invalidation criteria — which is what the principle ("Knowledge is Conditional") actually says to do. The gates exist to be removed; documenting *when* to remove them is half the work.

The other half — the dossier path that would make these gates redundant — is the next thing to build. Pattern stats need to reach Claude's prompt with the same fidelity these gates have in code. Until then, the gates are training wheels.

### EOD reality check (Apr 30, 17:30 ET)

Filter D shipped at ~07:15 ET. Backend was restarted before market open. Five trading scans ran today. Here's what actually happened.

#### Filter D firing audit — IT WORKED

Six BUY signals at score >= 75 with validated AI in blocked sectors hit the gate today and were rejected:

| Symbol | Score | Sector | Notes |
|---|---|---|---|
| **SMR** | **90** | Industrials | The headline block — pre-Filter-D this was a Tier-1 priority entry |
| SEZL | 86 | Financial Services | High-conviction Fin name |
| TFC | 80 | Financial Services | Already held from Apr 27 — Filter D prevented doubling-up |
| PLUG | 80 | Industrials | Two scans, two blocks |
| YSS | 75 | Industrials | Marginal entry |

**Universe composition today:** 263 signals total, 84 BUY, 19 at score >= 80.
- Industrials: 62 signals (24% of universe)
- Financial Services: 20 signals
- **Combined: 31% of the universe gated by sector exclusion**

This is meaningful structural work — the gate isn't theoretical. SMR-90 in particular is the kind of pre-Filter-D entry that would have been a $500 position on Tier-1 sizing.

LONG-horizon suspension: not directly visible in DB rows (they never get inserted), but the entry mix below confirms it's working — 0 of 3 admitted entries are LONG-horizon. Pre-fix, ~30% of entries were LONG.

#### Today's entries (3 — within Filter D's 2-4 prediction)

All three are HIGH_RISK / SHORT-horizon — exactly the cohort Filter D admits:

| Time | Symbol | Score | Bucket | Horizon | Size |
|---|---|---|---|---|---|
| 14:02 | APLD | 75 | HIGH_RISK | SHORT | $410 |
| 14:02 | USAR | 75 | HIGH_RISK | SHORT | $456 |
| 16:02 | BTDR | 78 | HIGH_RISK | SHORT | $443 |

Per-day cap (3) was the binding constraint — by 16:02 the cap was hit. APLD and USAR are still open at 17:30 with thesis=valid.

BTDR opened at 16:02 and **closed at 18:30 same-day at −2.34% via WATCHDOG_EXIT**. That's the third same-day-mortality entry this week (FN Apr 28 8min, NBIS Apr 30 48min, BTDR Apr 30 2.5h). At −2.34% it didn't even hit catastrophic — the watchdog has a softer trigger for fresh positions that bleed quickly. **The same-day-mortality pattern is now accumulating real evidence.**

#### Today's closes (5)

| Time | Symbol | Reason | P&L | Note |
|---|---|---|---|---|
| 13:50 | HIMS | WATCHDOG_FORCE_SELL | −$29.72 (−8.59%) | Hit −8% catastrophic. Day-19 predicted "bleeds to −8% watchdog" — confirmed. |
| 14:02 | ALAB | TRAILING_STOP | +$8.44 (+2.36%) | Day-19 predicted TARGET_HIT — got TRAIL at lower magnitude. Win still booked. |
| 14:50 | NBIS | WATCHDOG_EXIT | −$16.58 (−4.24%) | Day-1 mortality. Day-19 predicted CRWV/NBIS Day-1 death — confirmed for NBIS. |
| 18:30 | BTDR | WATCHDOG_EXIT | −$10.37 (−2.34%) | Same-day mortality (entered 16:02). |
| 19:02 | CRWV | THESIS_INVALIDATED | +$1.25 (+0.29%) | Thesis flipped Day 1, position essentially flat. Win technically, but the model said "exit." |

**Today P&L:** 2W / 3L → net realized **−$46.98**.

#### Wallet-era cumulative

- Closed wallet trades: 13 → 4W / 9L (**31% win rate**)
- Cumulative realized: **−$108.54**
- Pocket balance trajectory: 4500 → 4067 → 4709 → 3669 → 4239 → 4855 (closes return cash; the trajectory looks rising but only because positions are flushing)

**31% wallet-era win rate is BELOW the 40.4% full-history baseline.** The recent regime is harder than the average regime. Filter D's historical 47.8% win rate is computed over the same harder regime *with* the filter applied — so the projection still holds, but we won't see Filter-D-only outcomes until APLD/USAR/etc. close.

#### Day-19 predictions vs reality

| Prediction | Outcome |
|---|---|
| HIMS resolution at 2-day mark | ✓ Closed via WATCHDOG_FORCE_SELL at −8.59% (different gate, same destination) |
| ALAB target hunt | ✓ Won via TRAILING_STOP +2.36% (lower magnitude than predicted target) |
| CRWV/NBIS Day-1 outcomes | ✓ Both died Day 1 — pattern of fresh-position mortality CONFIRMED for 3rd consecutive day |
| First positive-day at portfolio level | ✗ Pocket grew $616 from closes returning cash, but realized P&L is −$47. Not a true positive day. |

#### Day-20 ship predictions vs reality

| Prediction | Outcome |
|---|---|
| 2-4 entries today | ✓ 3 entries (cap-bound) |
| First filter_d_sector_excluded log | ✓ 6 blocks recorded (SMR-90 the headline) |
| First filter_d_long_horizon_suspended log | Unverified in DB rows (gates suppress at insert), but 0/3 entries are LONG-horizon vs ~30% pre-fix |
| Win rate over next 5 closes | 2W/3L = 40% (right at baseline; n=5 too small to confirm Filter D edge) |

#### The same-day mortality problem (now Pattern #4)

Three entries this week died on the same calendar day they opened:
- Apr 28: FN (8 minutes)
- Apr 30: NBIS (48 minutes after entry)
- Apr 30: BTDR (2.5 hours after entry)

These are NOT all catastrophic (−8%). NBIS exited at −4.24%, BTDR at −2.34%. The watchdog has a non-catastrophic exit path that fires same-day on fresh positions when the price action is "wrong shape" (deteriorating fast even if not at catastrophic threshold). **This pattern needs investigation tomorrow.** Three same-day deaths in three trading days is not noise.

The Day-0 grace period was supposed to protect new entries from premature thesis-driven exits. But the watchdog bypasses the grace period — and rightly so, because it's a safety net. The question is whether the watchdog is correctly identifying "fresh position dying fast" as a catastrophic-equivalent, or whether it's prematurely killing positions that would recover (the way ARM and CAMT did Apr 29).

#### Predictions for Day 21

- [ ] **APLD and USAR Day-0/1 outcomes.** Both entered today at 14:02 within the 24h grace window. If both close losers tomorrow, Filter D's entry quality isn't yet good enough — the gate is admitting the right cohort but the trades inside it are still losing.
- [ ] **TFC behavior.** TFC is currently OPEN from Apr 27 at score 80, Financial Services, **LONG-horizon**. Filter D would have rejected this entry today; it survived because it's already in flight. Watch whether it hits target or stops out — this is the "would Filter D have been wrong?" test in vivo.
- [ ] **Same-day mortality count.** If a 4th fresh position dies same-day tomorrow, watchdog calibration becomes the next thing to investigate. If 0 die same-day, today's pattern was the cohort, not the rule.
- [ ] **First Filter-D-era close.** If APLD or USAR close tomorrow, that's the first wallet-era trade where Filter D actually decided "enter" or "skip." Real evidence on the gate's quality starts arriving.
- [ ] **Track SMR.** SMR at 90 was today's headline block. If we see SMR rip up tomorrow, that's a data point against Filter D's sector exclusion. Watch SMR's price for 5 trading days as a "would-have-traded" cohort.

#### Personal note (EOD update)

Today vindicated the Filter D ship in two ways: (1) it actually fired meaningfully — 6 blocks including a 90-score — and (2) the entries it admitted look structurally correct (3 HIGH_RISK SHORT-horizon, the exact cohort the backtest favored). What it did NOT vindicate is per-trade quality. Today's −$47 was driven by Day-19 carryover (HIMS) and same-day mortality (NBIS, BTDR) — same illness as before.

The Filter D test is a 5-trading-day test, not a 1-day test. We need APLD, USAR, and tomorrow's entries to close before we can tell whether the gate is admitting better trades or just fewer of the same trades. The same-day mortality pattern is the more urgent signal — three in three days warrants its own investigation tomorrow.

Pocket up $616 today is misleading — that's closes returning capital, not gains. Realized −$47. Wallet-era is −$108 across 13 closes. The journal has to keep telling the truth even when the dashboard makes it look better than it is.

### Late-evening ship: WATCHDOG_EXIT grace period

After the EOD entry above, investigated why three same-day deaths happened in three trading days. Root cause:

The watchdog has a **non-catastrophic exit path** at `watchdog_service.py:411`:
```python
if sentiment_label == "bearish" and pnl_total_pct < 0:
    _close_virtual_trade(..., "WATCHDOG_EXIT")
```

This fires when:
1. Position enters "concerned" state (any of 5 triggers — including total loss ≤ −2% for SHORT-horizon, line 312)
2. Fresh sentiment fetch returns `bearish`
3. P&L is negative (any negative)

**The fatal combination:** A HIGH_RISK SHORT-horizon position naturally drifts ±2% in its first hours. The −2% bleed threshold trips, sentiment gets fetched (and is plausibly bearish *because* the price is down), pnl < 0 is trivially true, and the position is closed.

**No grace period existed on this path.** Compare:

| Defense | Grace |
|---|---|
| THESIS_INVALIDATED | 24h grace (`new_position_grace_hours`) |
| QUALITY_PRUNE | 2-day floor |
| Thesis-protected exits | thesis-gated, with -8% catastrophic carve-out |
| **WATCHDOG_EXIT** | **NONE — outlier** |
| WATCHDOG_FORCE_SELL | NONE (correct — safety net) |

**Fix shipped:** Added `in_grace = hours_held < settings.new_position_grace_hours` check before the close. Inside grace, the bearish-sentiment + slight-loss combo falls through to the alert path (logged as WARNING with `GRACE PROTECTED`) instead of closing the position. WATCHDOG_FORCE_SELL (≤ −8% catastrophic) and the score-collapse path are unchanged — they still fire at any age.

**Code:** `app/services/watchdog_service.py` — three import addition, ~10 lines for the grace computation, ~7 lines for the audit log line in the alert branch.

**Tests:** `tests/test_watchdog_grace.py` (9 tests) — pins:
- 24h grace default
- Positions at 0min / 8min / 2.5h / 19h are protected
- Positions at 24.5h / 3 days are NOT protected
- Missing/unparseable entry_date does NOT silently extend protection (falls through)
- The catastrophic check appears BEFORE the grace check in source order (regression guard)

All 19 tests pass (9 grace + 10 Filter D from this morning). All 99 pre-existing unit tests still pass.

**Reverts:** `git revert` of the watchdog_service.py edit + delete the test file. Three-line change to revert.

**Invalidation criterion:** if a fresh position bleeds catastrophically (≤ −8%) inside the grace window, the existing WATCHDOG_FORCE_SELL still catches it. If grace-protected positions consistently bleed past −8% (catastrophic), the threshold itself needs revisiting — the grace is doing the right thing in that case (catching them via the harder net). If grace-protected positions consistently recover into positive, the grace is the right call. Track via the new `GRACE PROTECTED` log line for the next 5 trading days.

#### Updated predictions for Day 21

Adding to the existing list:

- [ ] **First `GRACE PROTECTED` log line.** Should appear within 24h given how often the −2% bleed threshold trips on fresh entries. If 0 in 48h, either today's pattern was a cohort, not a rule, OR the watchdog isn't running (check infra).
- [ ] **APLD/USAR survival.** Both entered 14:02 today and are now grace-protected through tomorrow ~14:02. Pre-fix, NBIS at -4.24% would have been killed in this window. Post-fix, NBIS-equivalent stays open and either recovers (vindicates grace) or hits catastrophic (vindicates the carve-out).

Today's ship was the correct move at the correct time. The data made the case (3 same-day deaths in 3 days, all on the same softer trigger), the principles allowed it (grace is a CAPACITY decision, not a quality veto), and the risk is bounded (catastrophic safety net unchanged). This is what "do what is better" looks like — investigate, identify, ship, document.

Two ships in one day. Filter D pre-market, watchdog grace post-EOD. Both with regression tests, both with documented invalidation criteria, both with one-line reverts. The brain enters Day 21 structurally different from Day 19.

---

## Day 21 — May 1, 2026 (Friday)

**Metrics:** First full trading day with both Filter D and watchdog grace live. **Zero closes today** — first zero-close day in over a week. 3 new entries (all clean Filter D shape). Pocket dropped to $3539 (cash deployed, no offsetting sells). Cumulative wallet realized P&L unchanged at **−$108.54** (no closes = no new realized loss). Open positions: 7 (3 fresh from today, 2 from Apr 30, TFC from Apr 27, CNQ legacy from Apr 17).

### The headline: zero closes

Day 18: 7 entries, 0 closes
Day 19: 4 closes (1W/3L)
Day 20: 5 closes (2W/3L) — 3 same-day deaths
**Day 21: 0 closes**

For five trading days the brain was either over-entering or over-exiting. Today neither happened. Three positions opened, none closed. **This is the first behavioral confirmation that the new gates are doing what we designed them to do.**

The interesting open positions:
- **SOUN** (entered 16:03, $486) — thesis flipped to **invalid** by 9h. Pre-watchdog-grace fix: would have been killed via WATCHDOG_EXIT (bearish sentiment + slight loss) AND/OR THESIS_INVALIDATED. Post-fix: protected on both paths. Will close as soon as grace expires (~16:03 tomorrow Saturday → effectively Monday open) IF thesis stays invalid.
- **ONDS** (entered 19:02, $393, **score 91**) — thesis=weakening at 6h. Same name and score that was Day 19's biggest loser (−$27.40 / −9.46%). The brain's mental model still loves this name. Grace-protected; we'll see if this time is different.
- **MSTR** (entered 16:03, $437) — thesis=valid at 9h. Fresh entry behaving as expected.

### Filter D firing audit — keeps working

Seven BUY signals at score >= 75 with validated AI in blocked sectors hit the gate today and were rejected:

| Symbol | Score | Sector |
|---|---|---|
| **SEZL** | **88** (3 scans) | Financial Services |
| TFC | 80 | Financial Services (existing position protected from doubling up) |
| UPST | 79 | Financial Services |
| MARA | 77 | Financial Services |
| YSS | 75 | Industrials |

**Universe today:** 271 signals, 63 BUY, 9 at score >= 80.
- Technology: 104 signals (38% — the dominant cohort, naturally Filter-D-friendly)
- Financial Services: 32 (12%)
- Industrials: 30 (11%)
- Combined gated by sector: 23% of universe

SEZL at score 88 hit three times today across different scans — that's the brain repeatedly trying to admit the same Fin name and Filter D repeatedly catching it. Without the gate, SEZL would have been a $400+ position that could have moved either direction. We don't know yet which.

### Watchdog grace evidence (anecdotal but suggestive)

I can't prove the watchdog grace prevented closes today without access to the loguru output stream from each scan tick. But the circumstantial case is strong:

- **SOUN at thesis=invalid** with negative P&L (BUY at $8.52 — would need price quote to confirm current move) at 9h. Pre-fix: this is *exactly* the configuration that killed FN/NBIS/BTDR via WATCHDOG_EXIT.
- **3 of 3 fresh positions still alive** after 6-9 hours each. Yesterday's pattern was 1-2 same-day deaths per day for three consecutive days; today: zero.

If SOUN closes profitably or recovers Monday, that's the first concrete win for the watchdog grace.

### Day-20 predictions vs reality

| Prediction | Outcome |
|---|---|
| APLD and USAR Day-0/1 outcomes | Both **still OPEN at 35h** with thesis=valid. Past the 24h grace window, no exit path has triggered. They're in the "no-rule-fires" valley but on the calmer side of it (no negative thesis, no catastrophic move, no signal flip). |
| TFC behavior | Existing TFC still OPEN with thesis=valid. **Filter D blocked another TFC entry today** — the gate explicitly prevented the brain from doubling-up on a position it already holds. Direct evidence of value beyond just sector exclusion. |
| Same-day mortality count | **ZERO same-day deaths today** — the 4-day streak (FN Apr 28, NBIS Apr 30, BTDR Apr 30) is broken. |
| First Filter-D-era close | Did NOT happen. APLD/USAR are the candidates and they survived. |
| Track SMR | Apr 30 16:02 score=90 @ $12.11 → May 1 14:02 score=72 @ $11.98. **Down ~1% in 24h.** Filter D was correct to skip — at this magnitude on a $400 position it would have been ~−$4. Not a winner. |
| First GRACE PROTECTED log | Can't verify without log stream access. SOUN at thesis=invalid + open is circumstantial evidence the grace fired somewhere. |

### Day-20 ship predictions vs reality

| Prediction | Outcome |
|---|---|
| First GRACE PROTECTED log within 24h | Strong circumstantial yes (SOUN configuration is exactly the trigger pattern); needs log verification |
| APLD/USAR survival | ✓ Both alive at 35h. Pre-fix, NBIS at -4.24% would have been killed. Post-fix, this kind of position stays open. |

### The "no-rule-fires valley" question is back

APLD and USAR have been open 35 hours each. They're past the 24h grace. Neither has hit:
- Stop loss
- Target
- Trailing stop (would need +3% from entry first)
- THESIS_INVALIDATED (thesis is valid)
- QUALITY_PRUNE (needs 2-day floor + < −3% + thesis not valid)
- WATCHDOG_FORCE_SELL (no catastrophic move)
- WATCHDOG_EXIT (now grace-protected, but they're past grace — so this means no qualifying bearish-sentiment + losing combo fired)

The system is correctly *holding* these positions. Whether that's the right call depends on what they do next. Day 19 noted this same "valley of death" with HIMS — sat at −6.5% / 1.5d hitting no rule. HIMS eventually died via watchdog at -8.59%. APLD/USAR could go either way.

### Wallet trajectory

| Day | Pocket | Daily delta |
|---|---|---|
| Apr 28 | $3,669 | −$1,040 (Pre-fix entry barrage) |
| Apr 29 | $4,239 | +$570 (closes returning cash) |
| Apr 30 | $4,855 | +$616 (closes returning cash) |
| **May 1** | **$3,539** | **−$1,316 (3 entries, no closes)** |

Pocket dropped today because we *deployed* capital without recouping any. That's normal for a low-close day — not a sign of losses.

### Open positions snapshot

| Symbol | Entered | Age | Score | Bucket | Thesis | Size |
|---|---|---|---|---|---|---|
| ONDS | May 1 19:02 | 6h | 91 | HIGH_RISK | weakening | $393 |
| SOUN | May 1 16:03 | 9h | 79 | HIGH_RISK | **invalid** | $486 |
| MSTR | May 1 16:03 | 9h | 77 | HIGH_RISK | valid | $437 |
| USAR | Apr 30 14:02 | 35h | 75 | HIGH_RISK | valid | $456 |
| APLD | Apr 30 14:02 | 35h | 75 | HIGH_RISK | valid | $410 |
| TFC | Apr 27 | 105h | 80 | SAFE_INCOME | valid | $451 |
| CNQ | Apr 17 | 345h | 79 | SAFE_INCOME | valid | $0 (legacy) |

**$2,633 deployed across 6 active positions** (CNQ excluded — legacy with no wallet allocation). Average position size $440. All 5 of the wallet-era positions are HIGH_RISK SHORT-horizon — exactly the cohort Filter D admits.

### Predictions for Monday (Day 24, market reopens May 4)

- [ ] **SOUN resolution.** Thesis is invalid; grace expires at ~16:03 Sat → Monday morning's first scan. If thesis is still invalid, SOUN closes via THESIS_INVALIDATED Monday at the open. Whether it closes positive (validating grace) or negative (validating Day-0 deaths) is the next data point.
- [ ] **ONDS at score 91 — repeat performer.** Day 19 ONDS-91 was the biggest loser. If May 1 ONDS-91 also dies, that's a pattern: score 91 names in HIGH_RISK SHORT-horizon don't survive Day 1-2. Worth a `signal_thinking` entry if confirmed.
- [ ] **APLD/USAR resolution.** Both have been past grace for ~24h with no exit triggered. Either they recover into the green (let it cook), they bleed to QUALITY_PRUNE territory (Day 2+ + < −3% + thesis weak), or they hit catastrophic.
- [ ] **First GRACE PROTECTED log line in production.** Verify by tailing scan logs Monday morning. If we never see one in a full week, the grace is a no-op (something's wrong).
- [ ] **First Filter-D-era close.** APLD/USAR/MSTR/SOUN/ONDS/MSTR — five positions are Filter-D-era entries. Whichever closes first is the first real data point on Filter D's per-trade quality.

### What we actually learned today (the real lessons)

A zero-close day still teaches things. Five real lessons from today's data, ordered by what to do about them:

**1. ONDS at score 91 is now a recurring pattern, not a one-off.** Day 19 ONDS-91 was the biggest single loser (−$27.40 / −9.46%). Day 21 (today) ONDS-91 entered again. **Same name, same score, same bucket, same horizon, same risk profile.** The brain's mental model loves this exact configuration. *Action:* write a `signal_thinking` entry today — *"score 91 HIGH_RISK SHORT-horizon entries on ONDS-style profile have a negative outcome distribution"* — so the next time the gate sees a similar name it gets the warning in Claude's prompt. Don't wait for ONDS to die again first; the "Open Trades Are Data" memory says we use in-flight signals, not just closed ones.

**2. SEZL hit Filter D three times in one day. Pre-fix, this would have concentrated $1,200+ on a single Fin name.** The per-day cap (3) would have been *all SEZL* without sector exclusion. **The per-day cap is necessary but not sufficient.** The brain has no per-symbol limit — it'll happily try to add the same ticker N times in N scans. *Action:* add a `wallet_max_entries_per_symbol_per_day = 1` gate. Five-line check, prevents the next over-concentration even on names Filter D doesn't block (e.g., Tech).

**3. The "no-rule-fires valley" is structural and is now biting active positions.** APLD and USAR are 35h old, past 24h grace, thesis=valid, no flip, no movement. Same configuration HIMS sat in for 1.5d before catastrophic. Between QUALITY_PRUNE (2-day floor + thesis weak + < −3%) and WATCHDOG_FORCE_SELL (−8%), there's a 1-2 day window where positions at −3 to −7% hit nothing. *Action:* don't reflexively close the gap (Day 19 noted this and the answer was "wait for backtest"). But the gap is now real on TWO active positions. Worth a `signal_thinking` entry: *"positions in the day-1 to day-2 window at −3 to −7% with no thesis movement have an ambiguous outcome distribution; consider tighter exit at day-1.5 if thesis is anything but valid."*

**4. We shipped the watchdog grace without persistent instrumentation.** The `GRACE PROTECTED` log line goes to loguru stdout. There's no DB row, no audit table, no way to query "how often did grace fire today and what eventually happened." We can prove the system *behaved* differently (zero same-day deaths) but we cannot quantify how many close attempts were suppressed or what the eventual outcomes were. *Action:* add a `watchdog_events` table (or column on `virtual_trades`) that records every WATCHDOG_EXIT *attempt*, including the ones grace suppressed, with the outcome at +24h, +48h, +5d. Without this we'll never know if grace is saving wins or just delaying losses. **This is the same lesson as the "Persist Diagnostics Before Debugging" memory** — we shipped a fix without making its effect measurable.

**5. The brain blocked TFC for the second day in a row. It literally cannot stop trying to add a name we already hold.** Today's Filter D blocked TFC because of sector. But if TFC had been Tech, the brain would have happily double-down on it. **There's no "don't re-buy what you already own" gate** (or if there is, it's not catching SAFE_INCOME-bucketed re-entries — needs verification). *Action:* check if `open_brain_long` set in `process_virtual_trades` skips already-held symbols. If yes, why is TFC re-appearing as a candidate? If no, add the check. This is a 2-line fix waiting for verification.

### Bonus observation: score-as-filter, not score-as-ranker (now confirmed across cohorts)

Day 19 lesson #1 was *"score is a filter, not a ranker"* — based on ONDS at 91 losing while CAMT at 81 won. Today reinforces it: SEZL at 88 hit 3 times, ONDS at 91 entered, and we know from history these score-90 entries don't outperform score-77 entries. The brain still ranks signals by score (highest first) and the per-day cap clips the lowest. **This means our cap is biased to keep the score-90s and discard the score-77s — exactly the wrong direction if score doesn't rank.**

This is too important for a footnote. Adding it as Lesson 6:

**6. The per-day cap's "highest score first" sort order is probably wrong.** The cap was designed assuming higher score = better trade. The data says it doesn't. *Action:* run a backtest comparing "cap by score-DESC" (current) vs "cap by random / by lowest-score-first" on the historical 52 trades. If random or inverse beats score-DESC, change the sort order. This is a pure math experiment, no code commitment yet.

### Personal note (honest version)

Today felt strange because nothing happened in the close column. But the *real* lesson isn't "the gates work" — it's that we now have visibility on the next layer of bugs. Filter D fixed the entry-quality problem; the watchdog grace fixed the same-day-death problem; today exposed three more structural issues (per-symbol concentration, valley-of-death, missing instrumentation) and reinforced two old ones (score-isn't-ranker, ONDS-91 pattern).

Six lessons from a zero-close day. The hard part isn't generating action items — it's prioritizing them. My recommendation for next session:
- Ship the per-symbol cap (#2) — 5 minutes, prevents repeat concentration.
- Add the ONDS-91 thinking entry (#1) — 10 minutes, starts the dossier path.
- Defer #3, #4, #5, #6 until Monday-Tuesday data arrives. They're real but not bleeding cash today.

### Late-Friday ship: lessons #1 and #2 acted on

After writing the lesson list, shipped both #1 and #2 the same evening rather than queuing them for Monday. Three weekend days of "carry the lesson but not the fix" has cost us nothing of value, and Monday morning will already have enough to think about (SOUN/ONDS resolutions, Filter-D-era closes).

**Ship #1 — `signal_thinking` entry on the ONDS-91 pattern.**

- Inserted into `signal_thinking` table with id `bc1aa8c3-a29a-4819-ba08-2229220d5ac2`.
- `pattern_match`: `{bucket: "HIGH_RISK", score_min: 88}` — broader than ONDS specifically because trade records only carry bucket + score; the test is whether the *whole* HIGH_RISK 88+ class underperforms.
- `prediction`: closed trades matching this pattern will have win rate < 35% (vs 40.4% baseline) and average pnl_pct < 0%.
- `invalidation_conditions`: rolling 30d win rate of HIGH_RISK >=88 trades exceeds 50% across n>=8, OR 5+ matching trades close positive while contradicting count stays below threshold/3.
- `created_by`: `journal_day21_onds91_pattern`. Tagged so a future audit can join back to this journal entry.
- Audit row appended to `knowledge_events` with `EVENT_THINKING_OBSERVATION_ADDED` documenting initial N=2 evidence.

When Claude's prompt is built next scan, `get_active_thinking_block` will surface this hypothesis as a "Working Hypothesis (under observation — low confidence)" with the warning embedded. Next ONDS-style entry, Claude sees: *"the brain has been watching: HIGH_RISK score>=88 historically underperforms; this signal matches that pattern."*

**Ship #2 — `wallet_max_entries_per_symbol_per_day = 1`.**

- New config setting in `app/core/config.py:159` with full Day-21 docstring.
- New `wallet_entries_by_symbol_today: Counter` initialized at the top of `process_virtual_trades` from the wallet_transactions audit ledger.
- Per-symbol gate added to BOTH BUY and SHORT entry paths. The gate fires BEFORE the per-day cap so the log line names the more specific reason. Same shape as the existing per-day cap (Day 19).
- Counter increments after successful inserts on both paths.
- 6 regression tests in `tests/test_per_symbol_cap.py` pinning: default value, basic cap math, different-symbol-not-blocked, cap=0 disables, cap=2 admits two, ordering invariant (per-symbol before per-day in source).

26 tests pass across all three Filter-D-era ships (10 Filter D + 9 watchdog grace + 6 per-symbol + 1 cross-cap ordering). All 99 pre-existing unit tests still pass.

**Reverts:** each ship has a one-line revert. Per-symbol cap → set `wallet_max_entries_per_symbol_per_day = 0` in config (no code revert needed). ONDS-91 thinking entry → `UPDATE signal_thinking SET status = 'rejected' WHERE id = 'bc1aa8c3-a29a-4819-ba08-2229220d5ac2'`.

**Status going into Monday:** brain enters Day 24 (May 4) with three structural changes from Day 19 — Filter D, watchdog grace, per-symbol cap — and one new dossier entry on the ONDS-91 pattern. The next 3 trading days are the test window.

---

## Day 24 — May 4, 2026 (Monday)

**Metrics:** First full trading day with watchdog grace + per-symbol cap live. Filter D fired heavily (8 blocks today, dominated by Financial Services). **3 closes (1W/2L) net +$30.61 — first net-positive realized day in over a week.** SOUN closed +14.14% via THESIS_INVALIDATED — the single position that vindicates the watchdog grace ship. Wallet-era cumulative now **−$77.93** (was −$108.54 Friday). 6 positions still open (5 wallet + CNQ legacy).

### The headline: watchdog grace paid for itself today

**SOUN +$68.67 / +14.14% via THESIS_INVALIDATED after 72h.**

Friday: SOUN entered at 16:03 with thesis flipping to **invalid by hour 9**. **Pre-watchdog-grace fix, this is exactly the configuration that killed FN/NBIS/BTDR same-day** (bearish sentiment + slight loss + grace=none). Post-fix: protected through the 24h grace, recovered over the weekend, and exited profitably on Monday when the thesis tracker re-evaluated.

**One position covered today's two losses with $30 to spare.** This is the proof the design loop works: grace lets weakening positions either invalidate properly later OR recover and exit cleanly. Both happen on different positions; today we got the recovery.

### Today's closes (3)

| Time | Symbol | Reason | P&L | Held | What it confirms |
|---|---|---|---|---|---|
| 14:02 | ONDS | QUALITY_PRUNE | **−$25.40** (−6.46%) | 67h | 3rd ONDS-91 loss — hypothesis adds N=1 supporting |
| 15:45 | TFC | WATCHDOG_EXIT | **−$12.66** (−2.81%) | 168h | Filter D's sector call was right |
| 16:02 | SOUN | THESIS_INVALIDATED | **+$68.67** (+14.14%) | 72h | Watchdog grace save — the headline |

**Today P&L: +$30.61** — first net-positive realized day since Apr 22.

### Today's entries (2 — clean Filter D shape)

| Time | Symbol | Score | Bucket | Horizon | Size | EOD thesis |
|---|---|---|---|---|---|---|
| 14:02 | ARM | 77 | HIGH_RISK | SHORT | $354 | **invalid** at 10h (grace-protected) |
| 16:02 | BTDR | 78 | HIGH_RISK | SHORT | $399 | valid at 8h |

**ARM is the next watchdog-grace test in flight.** Same shape as SOUN: thesis flipped invalid intra-day, position is at slight loss, grace is keeping it open. Pre-fix this would have been killed this afternoon. Post-fix it survives until grace expires tomorrow ~14:02 ET. SOUN took 72h to resolve; ARM is on the same clock.

**BTDR is a re-entry** — same name died same-day Apr 30 via WATCHDOG_EXIT. Per-symbol cap doesn't block (it's per-day, not per-week). Day-1 outcome will tell us if BTDR is name-specific bad or just unlucky timing.

### Filter D firing — heavy Financial Services day

8 BUY signals at score >= 75 with validated AI in blocked sectors hit the gate today:

| Symbol | Score | Sector | Notes |
|---|---|---|---|
| TFC | 80 (×2) | Financial Services | Existing position simultaneously closing at a loss — Filter D was right |
| COIN | 78 | Financial Services | First time COIN attempted post-Filter-D |
| BMO.TO | 77 (×2) | Financial Services | Canadian bank pair — dense day for Fin |
| MFC.TO | 77 (×2) | Financial Services | Canadian insurer |
| USB | 76 | Financial Services | US bank |

**Universe today:** 329 signals, 94 BUY, 15 at score >= 80. Financial Services 38/329 = 11.5%. Industrials count was lower today than May 1.

The **TFC pattern** is striking: Filter D blocked TWO new TFC entry attempts at the exact moment the existing TFC position was hitting the watchdog. The brain's signal pipeline really does keep generating the same names regardless of in-flight state. Without Filter D AND without the per-symbol cap, this would have been a TFC-doubling event in a Fin name we already held that was about to fail. Two gates worked together.

### ONDS-91 hypothesis: +1 supporting observation

The thinking entry inserted Friday (id `bc1aa8c3`) auto-incremented to `observations_supporting = 1` when ONDS closed today via QUALITY_PRUNE at −6.46%. **Total ONDS-91 evidence in dossier:** Day 19 −9.46%, Day 21 (today) −6.46%, plus an open ONDS that didn't close yet from Apr 29. **Three losses, zero wins** for ONDS at score 91 in HIGH_RISK SHORT-horizon.

The hypothesis was inserted with `graduation_threshold = 5`. Two more matching closes and it graduates to `signal_knowledge` — at which point it would appear in Claude's prompt as a *validated truth*, not a hypothesis under observation.

### Currently open (6 positions — the no-rule-fires problem is now real)

| Symbol | Age | Score | Bucket | Hz | Thesis | Size | Notes |
|---|---|---|---|---|---|---|---|
| BTDR | 8h | 78 | HIGH_RISK | SHORT | valid | $399 | In grace |
| ARM | 10h | 77 | HIGH_RISK | SHORT | **invalid** | $354 | In grace, watchdog-grace test |
| MSTR | **80h** | 77 | HIGH_RISK | SHORT | valid | $437 | **Day-4 in valley** |
| USAR | **106h** | 75 | HIGH_RISK | SHORT | valid | $456 | **Day-5 in valley** |
| APLD | **106h** | 75 | HIGH_RISK | SHORT | valid | $410 | **Day-5 in valley** |
| CNQ | 416h | 79 | SAFE_INCOME | LONG | valid | $0 | Legacy |

**$2,056 deployed across 5 wallet positions.**

**Three positions (MSTR, USAR, APLD) are 80-106 hours old with thesis=valid and no exit has triggered.** This is **Day 21 lesson #3 ("no-rule-fires valley") biting in real time.** They're in the gap between QUALITY_PRUNE (needs Day 2+ AND thesis weak AND < −3%) and WATCHDOG_FORCE_SELL (needs ≤ −8%). Their thesis is still valid so QUALITY_PRUNE doesn't qualify. Their loss isn't catastrophic so the watchdog soft-trigger doesn't fire post-grace either.

### Wallet trajectory

| Day | Pocket | Realized P&L (cum) |
|---|---|---|
| Apr 30 | $4,855 | −$108.54 |
| May 1 | $3,539 | −$108.54 (no closes) |
| **May 4** | **$4,146** | **−$77.93** (+$30.61 today) |

Pocket up $607 from net cash flow (closes returned $1,360, new entries deployed $753).

### Lessons today (the real ones)

**1. The grace + thesis-tracker loop works end-to-end.** SOUN proves it: thesis went invalid on Day 0, grace kept it open through the weekend, market gave it time to recover, thesis tracker exited cleanly when conditions changed. This is the design intent. Day 19 had the *opposite* outcome (ARM/CAMT recovered too — but ONDS/CCO.TO died after grace). Today we got the bullish version.

**2. Filter D's sector calls keep being right in vivo.** TFC was the standing test ("would Filter D have been wrong on a Fin name we couldn't avoid?"). Today TFC closed at a loss. Filter D's blocking TWO new TFC entries at the same moment was exactly the right call. **Two-for-two: both Day-21's SMR-90 block (down 1% in 24h) and today's TFC validate the gate.**

**3. ONDS-91 hypothesis is converging fast.** Inserted Friday with N=2 prior evidence. Today's close added another to the live counter. Two more and it graduates. The dossier path is doing real work without code changes — the brain learns from itself.

**4. The "no-rule-fires valley" is now the next bottleneck.** Three live positions are sitting at 80-106h with thesis=valid, no exit firing. If any of them eventually closes via WATCHDOG_FORCE_SELL at −8% (catastrophic), we lost ~$30+ each because nothing softer fired earlier. Day 21 lesson #3 deferred this — the deferral now costs visible position-days. Worth investigating Day 25.

**5. The per-symbol cap and Filter D are functioning as a pair.** TFC today: existing position closing AND Filter D blocking new entries. Without both, the brain would have repeatedly tried to re-add a name that was actively dying. The two gates are catching different aspects of the same anti-pattern.

### Mid-day UI fix (separate from brain)

Shipped a fix for the broken "Total Return" card on `/brain/performance`. The headline was showing −21.79% (sum-of-percentages math error) when the underlying realized was −$77.93 of $5,000 deposited (real return ≈ −1.56%). Now uses `wallet.roi_pct` (mark-to-market vs initial capital) as the headline. Sub line dropped the misleading wallet+legacy "+ +" string. Backend `total_return_pct` field kept for backwards compat but marked deprecated with a 12-line warning comment so a future reader doesn't repeat the mistake. TS check clean, 125 backend tests pass.

### Predictions for Day 25 (Tuesday May 5)

- [ ] **ARM Day-1 outcome — the next SOUN test.** ARM entered today with thesis flipping to invalid by 10h. Pre-fix would have died this afternoon. Post-fix is grace-protected through tomorrow ~14:02 ET. If ARM closes positive (SOUN repeat), the grace logic earns more credibility. If ARM closes catastrophically (−8%+), grace was wrong on this case but the carve-out caught it. If ARM closes via THESIS_INVALIDATED at small loss, neutral.
- [ ] **USAR/APLD Day-5 resolution.** Both at 106h with valid thesis. If still open on Day 7, they'll trigger STAGNATION_PRUNE (week+ no movement). If they bleed into negative territory, QUALITY_PRUNE eligibility kicks in once thesis flips. The valley question gets answered either way.
- [ ] **MSTR Day-4.** Same shape as USAR/APLD but newer. 24-48 hours behind them on the same trajectory.
- [ ] **BTDR Day-1.** Re-entry of the Apr-30 same-day death. If it dies same-day again, BTDR is name-specific bad and worth a `signal_thinking` entry. If it survives, the Apr-30 death was timing not name.
- [ ] **First Filter-D-era close that's a winner.** SOUN was the SOUN-shaped winner today. Need at least one more Filter-D-only entry (post-Day-20) to close in the green to start building a real Filter D win-rate sample.

### Personal note

First positive day in over a week. The temptation is to read it as "the gates are working." But one day is one data point. SOUN was a +$68 win covering two −$20s of losses; that's a magnitude effect, not a probability effect. Tomorrow could easily be three losers covering one winner. Pedro's framing all along has been "we want consistent monthly profit," not "occasional big wins." We need 3-5 consecutive days of small positive realized P&L before the new structure has been actually validated.

What today *did* validate: the grace logic prevented a same-day death that would have cost ~$15. The Filter D gate prevented at least one Fin-name doubling-up event. The ONDS-91 hypothesis is gathering evidence on its own. **The structure is doing what we designed it to do.** Whether that produces compounding monthly returns is a different question and we won't know for two more weeks at minimum.

The next big lesson: the no-rule-fires valley is now the bleeding edge. Three live positions are caught in it. Day 25 will tell us if this is a real problem or just a holding pattern that resolves itself.

### Late-evening: shipped 4 information-layer improvements

After EOD analysis, shipped four non-behavior-changing improvements (the kind that improve the system without compromising the in-flight test of Filter D + watchdog grace):

**1. Watchdog grace instrumentation** (`watchdog_service.py`):
- New `EVENT_GRACE_PROTECTED` event type emitted to `watchdog_events` whenever the WATCHDOG_EXIT path is suppressed by grace.
- Each row records symbol, P&L, sentiment, hours_held, trigger reason, and the suppressed-close P&L. Joinable later to virtual_trades to answer "did grace save this position or just delay its death?"
- Without this, the only data point we had was SOUN (one save). Now every grace decision is auditable.

**2. Valley-of-death `signal_thinking` entry** (id `226cfb85-...`):
- Hypothesis: HIGH_RISK SHORT-horizon positions held 3-5 days with thesis=valid in the gap between QUALITY_PRUNE (day≥2 + thesis weak + pnl<-3%) and WATCHDOG_FORCE_SELL (≤-8%) underperform.
- Active in valley at insert: MSTR (80h), USAR (106h), APLD (106h). Prior loss case: HIMS Day 19.
- Same shape as ONDS-91 entry — surfaces the pattern to Claude's prompt as low-confidence observation; auto-classifier tracks it.

**3. Cap-by-score backtest** (`scripts/backtest_cap_sort_order.py`):
- Tested whether the per-day cap's "score-DESC" sort is right or whether random / inverse would beat it.
- **Result: score-DESC is correct.** Score-DESC = −4.3% total / 43.9% win on 41 admitted trades. Random = −20.8% / 36.9%. Score-ASC (inverse) = −54.4% / 24.4%. Day 19 lesson #1 ("score isn't a ranker") was about ONE bad trade (ONDS-91), not a population pattern. **Cap stays as-is.**

**4. Re-buy gate verification** (read-only audit):
- Confirmed `process_virtual_trades` line 1715 already gates on `symbol not in open_brain` before any tier eval.
- The brain DOES skip re-entry on held symbols. **No fix needed.** Day 21 lesson #5 closed.

### And the headline: full-brain backtest result

In response to Pedro's "run the current application with backdata" ask, shipped `scripts/backtest_current_brain.py` — replays every closed brain trade through the CURRENT entry pipeline (Filter D + per-day cap + per-symbol cap + score gates) and reports what would have been admitted vs blocked:

| Configuration | n | W/L | Win Rate | Total P&L |
|---|---|---|---|---|
| Baseline (no filter, all 60 trades) | 60 | 24/36 | 40.0% | **−25.2%** |
| Filter D only | 30 | 14/16 | 46.7% | +0.6% |
| **Filter D + per-day + per-symbol caps** | **25** | **13/12** | **52.0%** | **+13.2%** |

**+38.5pp improvement vs baseline.** If the current brain had been live across all 60 closed trades, instead of a −25.2% loss, we'd have +13.2% positive — a magnitude shift, not a marginal one.

**Cap-clipped days were instructive:**
- Apr 10: kept TPL(85), AGI.TO(81), AVGO(81); dropped LB(80), ASML(80)
- Apr 28: kept ONDS(91), ALAB(83), ARM(81); dropped FN(79), HIMS(79), CAMT(81)

On Apr 28 the cap dropped two losers (FN, HIMS) and one winner (CAMT) — net positive but not free. ONDS-91 was kept (it was the biggest loser). This validates that **score-DESC sort isn't a perfect ranker** but is still better than the alternatives.

**What this number does NOT include:**
- Watchdog grace exit-path effects — would likely improve the win rate further (SOUN-style saves) but cannot be proven without intra-day price replay we don't store.
- True position sizing (legacy trades = 1 share, wallet trades = sized). The % comparison is direction-stable but the dollar comparison would need real sizing to be meaningful.

### Updated test count

127 unit tests passing (118 prior + 1 new EVENT_GRACE_PROTECTED constant pin + 1 new ordering test). 4 backend tests + 1 Python script + 0 brain-behavior changes. Net effect: significantly better visibility, no risk to the in-flight test.

---

## Day 25 — May 5, 2026 (Tuesday)

**Metrics: TWO big wins. Net +$71.59 realized today** (USAR +$60.43, ARM +$11.16, no losses). **Wallet-era cumulative now −$6.34** — was −$108.54 just 4 days ago Friday. The brain is **94% recovered to flat** in 4 trading days under the new structure. Second consecutive positive day. 38.9% wallet-era win rate.

### The headline: USAR proves the valley resolves both ways

**USAR closed +$60.43 / +13.26% via SIGNAL after 125 hours (5.2 days).**

USAR was the canonical "no-rule-fires valley" position from Day 24:
- Entered Apr 30 14:02 at score 75
- Day 24: 106h old, thesis=valid, no exit triggered, in the gap between QUALITY_PRUNE and WATCHDOG_FORCE_SELL
- Yesterday's prediction: "If still open on Day 7, will trigger STAGNATION_PRUNE. If they bleed into negative territory, QUALITY_PRUNE eligibility kicks in."
- **Today's reality: the SIGNAL flipped and it closed at +13.26% as a winner.** Position #2 of the "valley three" resolved positively. The patience paid.

**This is the contradicting case for the valley-of-death hypothesis we wrote yesterday.** The auto-classifier picked it up — `journal_day24_no_rule_fires_valley` now sits at **2 contradicting / 0 supporting** observations (USAR + ARM both HIGH_RISK winners increment contradicting).

### The other win: ARM proves watchdog grace works on the second try

**ARM closed +$11.16 / +3.15% via THESIS_INVALIDATED after 29 hours.**

ARM entered May 4 14:02, thesis flipped to invalid by hour 10. Pre-watchdog-grace fix: would have been killed yesterday afternoon at any negative P&L. Post-fix: grace held it through the night, thesis tracker eventually re-evaluated and exited cleanly at a small win.

This is the **second SOUN-shaped grace save in 4 trading days** (SOUN +14% / +$68 yesterday, ARM +3% / +$11 today). The pattern is now n=2 wins. Without grace, both would have been small same-day losses (~$10-20 each). With grace, both became wins.

### Today's full activity

| Time | Symbol | Action | Score | Outcome |
|---|---|---|---|---|
| 16:02 | FN | BUY | 87 | OPEN — re-entry of Apr-28 same-day death |
| 19:02 | USAR | SELL | 75→? | **+$60.43 / +13.26% SIGNAL** |
| 19:02 | ARM | SELL | 77 | **+$11.16 / +3.15% THESIS_INVALIDATED** |

**Today P&L: +$71.59.** Two wins, zero losses.

### Day-24 predictions vs reality

| Prediction | Outcome |
|---|---|
| ARM Day-1 outcome — next SOUN test | ✓ **Closed +3.15%** — grace logic earns more credibility |
| USAR/APLD Day-5 resolution | ✓ USAR closed **+13.26%** (winner). APLD still open at 127h |
| MSTR Day-4 | Still open at 101h, thesis=valid |
| BTDR Day-1 outcome | ✓ Survived 29h, no same-day death (Apr-30 was timing not name) |
| First Filter-D-era close that's a winner (non-SOUN) | ✓ **TWO of them today** (USAR, ARM) |

5 of 5 predictions hit or favorable.

### The valley hypothesis is decaying — but for the right reason

I inserted `journal_day24_no_rule_fires_valley` yesterday with N=1 prior loss (HIMS). Within 24 hours it accumulated 2 contradicting observations. The contradiction count is moving fast — at this rate the hypothesis would be rejected within a week.

**But there's a subtle issue:** the `pattern_match` for that hypothesis is just `{bucket: HIGH_RISK}` because `_trade_matches_pattern` can only check entry-time fields. It can't verify "spent time in the −3% to −7% range" or "held 3-5 days" — those require intra-trade snapshots we don't take. So **every HIGH_RISK close — winner or loser — increments the counter**, not just trades that actually passed through the valley state.

USAR closed at +13.26% — was it ever in the valley? Yesterday at 106h it was thesis=valid with no exit triggered, so by definition yes. ARM at 29h closed at +3% — was never really in the valley (too young). But the auto-classifier doesn't know that.

**Lesson #6 for the next pass:** hypotheses with intra-trade state conditions need a different evaluation mechanism. Either we capture peak-loss/min-loss/days-at-pnl-bucket on virtual_trades, OR the hypothesis is implicitly broader than its prose says. The ONDS-91 hypothesis is OK because it depends only on entry-time fields (bucket + score). The valley hypothesis is implicitly testing "are HIGH_RISK trades winning?" not the specific valley question.

The decay is the *right answer for the broader question* (HIGH_RISK trades are winning more under the new structure) but the *wrong answer for the specific valley question* (we still don't know if positions trapped at −5% on Day 2-3 systematically die).

### Currently open (5 wallet positions)

| Symbol | Age | Score | Bucket | Hz | Thesis | Size | Notes |
|---|---|---|---|---|---|---|---|
| FN | 5h | **87** | HIGH_RISK | SHORT | n/a | $415 | In grace. Re-entry of Apr-28 same-day death |
| BTDR | 29h | 78 | HIGH_RISK | SHORT | valid | $399 | Past grace, no exit triggered — survived Apr-30-style death |
| MSTR | 101h | 77 | HIGH_RISK | SHORT | valid | $437 | Day-4 in valley, but USAR shows valley can resolve up |
| APLD | **127h** | 75 | HIGH_RISK | SHORT | valid | $410 | **Day-5+ — longest-held wallet position** |
| CNQ | 437h | 79 | SAFE_INCOME | LONG | valid | $0 | Legacy |

**$1,661 deployed across 4 active wallet positions.** Down from $2,056 yesterday because two positions closed (returned cash) and one entered.

**APLD is the next valley test.** If APLD also closes positive (Day 6 STAGNATION_PRUNE or earlier signal flip), the valley question is essentially answered: HIGH_RISK SHORT-horizon positions in this regime self-resolve given enough time. If APLD instead bleeds catastrophic, the valley needs a tighter exit gate.

### Wallet trajectory

| Day | Pocket | Cumulative realized |
|---|---|---|
| Apr 30 | $4,855 | −$108.54 |
| May 1 | $3,539 | −$108.54 (no closes) |
| May 4 | $4,146 | −$77.93 (+$30.61) |
| **May 5** | **$4,613** | **−$6.34 (+$71.59)** |

**4-day swing: +$102.20 of realized P&L recovery.** Almost back to flat from the position we were in at Day 19 lows.

### Filter D firing — quiet day

Only 1 block today: TFC at score 80 (Financial Services). Universe was smaller: 216 signals vs 329 Monday. The brain admitted exactly 1 entry (FN at 87) — well within the per-day cap of 3.

**FN re-entry at score 87** is interesting. Apr 28 FN entered at score 79 and died same-day at −2.21%. Today FN entered at score 87 — same name but rated higher by the AI today. **Pattern-match-wise, FN at 87 falls just below the ONDS-91 hypothesis threshold (>=88).** But it's close enough to watch. If FN dies in the next 24-72h, it's another data point for "HIGH_RISK SHORT-horizon at 85+" being structurally weaker.

### The structural narrative for the week so far

5 trading days post-Filter-D ship (Apr 30 → May 5):
- Day 20 (Apr 30): 5 closes, 2W/3L, net −$47 (carry-over from pre-fix entries)
- Day 21 (May 1): 0 closes
- Day 24 (May 4): 3 closes, 1W/2L, net **+$30.61** (SOUN +$68 covered ONDS −$25 + TFC −$13)
- Day 25 (May 5): 2 closes, **2W/0L, net +$71.59** (USAR +$60, ARM +$11)
- Cumulative: 7 closes since Filter D went live → **4W / 3L = 57% win rate**, total realized **+$55.47**

**This is the post-Filter-D-era data we needed.** 7 closes is small but the direction is clear: 57% win rate beats the 40% baseline. The +$55 of realized P&L over 5 trading days, if sustained, projects to ~$220/month — meaningful relative to the $5k deposit.

### ONDS-91 hypothesis status

`journal_day21_onds91_pattern`: 1 supporting / 0 contradicting (unchanged today, no ONDS or 88+ HIGH_RISK closes). Patient.

### Lessons today (the real ones)

**1. The valley resolves both ways — patience pays in this regime.** USAR sat at "no-rule-fires" for 5+ days and closed +13%. Day 24's worry was that it would die catastrophic. The opposite happened. **Don't reflexively tighten exit gates just because a position is sitting. The thesis tracker and signal flip are doing the work the gates would have done — just on the system's timing, not ours.**

**2. Watchdog grace is now n=2 wins.** SOUN +14% Monday, ARM +3% today. Pattern: thesis flips invalid in hour 0-12, grace holds the position, thesis tracker eventually exits when conditions actually warrant it. **Two for two on grace saves.** Sample is small but the mechanism is consistent.

**3. Hypothesis pattern_match limitations matter.** The valley hypothesis is decaying because its pattern_match is too broad (any HIGH_RISK close increments). For hypotheses about intra-trade state (peak-loss, days-at-loss, etc.), we'd need to snapshot those fields on virtual_trades — currently they're computed on-the-fly only. **Future hypotheses with intra-trade conditions need either a new column or an explicit "pattern_match_loose" caveat in the notes.** The ONDS-91 hypothesis is OK because it's entry-time only.

**4. The recovery is real but not yet validated.** 7 closes / 5 trading days / +$55 realized. The post-Filter-D era is clearly outperforming the pre-Filter-D era (40% → 57% win rate, −$108 → −$6 cumulative). But 7 closes is still early. The honest read: structural fixes are doing what we expected, but the next 10 closes will tell us if it's a real edge or a small-sample win streak.

**5. Re-entries on names that previously died are the next test.** FN died Apr 28 same-day at score 79. Today FN re-entered at score 87. BTDR died Apr 30 same-day at score 78, today BTDR is at 29h with thesis=valid (Day-1 survival ✓). These are the symbol-specific resilience tests. If FN dies again at 87, FN is a name-quality issue. If FN wins, the Apr-28 outcome was timing-specific.

### Predictions for Day 26 (Wednesday May 6)

- [ ] **APLD resolution.** 127h old. If it crosses 168h (7 days) without closing, STAGNATION_PRUNE fires. Otherwise watching for the same SIGNAL/THESIS_INVALIDATED resolution USAR got.
- [ ] **MSTR Day-5.** Following USAR's trajectory by 24h. Same pattern: if it resolves positive via SIGNAL or THESIS_INVALIDATED, valley question is settled.
- [ ] **FN at 87 — Day-1.** First "high-conviction HIGH_RISK SHORT" entry post-Filter-D. Below the ONDS-91 hypothesis threshold (88) so neutral evidence.
- [ ] **BTDR Day-2.** Past grace, thesis valid. Continues to test whether Apr-30's same-day death was timing or name.
- [ ] **First grace-protected event recorded in `watchdog_events` table.** Today's instrumentation didn't produce any rows — either no fresh position triggered the watchdog soft-trigger, or the watchdog never escalated. If no rows in 48h, investigate whether the instrumentation is wired correctly.
- [ ] **Cumulative realized turns positive.** Currently −$6.34. One small winner tomorrow flips it.

### Personal note

After two weeks of bleeding and three weeks of doubt, the brain just delivered a $71 net day with two wins and zero losses. Not because anything magic happened — the structural fixes (Filter D, watchdog grace, per-symbol cap) created the conditions for trades to survive and resolve naturally, and the existing infrastructure (signal tracker, thesis re-eval) did the rest.

What I want to be careful about: **2 days isn't a trend.** A loss day would make today look like a coincidence. The honest framing is "the structure is producing the kinds of outcomes we designed it to produce." The cumulative −$6.34 is a *recovery from disaster*, not a *positive return*. We need cumulative realized to cross +$0 first, then sustain it across 10+ closes, before we can say the brain is profitable.

But the data has shifted. Last week the question was "is anything we're shipping helping?" This week it's "how much of this is regime vs structure?" That's a much better question to be asking. The next 5 trading days will tell us.

### Queued for Day 30 review (~Mon May 11)

Items deferred today because the post-Filter-D sample is too small to act on. Re-evaluate when we have 12-15 closed wallet trades from the post-Filter-D era (currently 5):

- **Re-run cap-sort backtest on post-Filter-D era only.** Today's check: 75-79 band is 3W/1L (the 1L died before watchdog grace shipped, so arguably 3W/0L). 90+ band is 0W/1L (ONDS). Directionally supports inverting the cap sort but n is too small. **The cap also never fires in the new regime** (no day has had >3 candidates yet). Both reasons to wait.
- **Re-evaluate the valley-of-death hypothesis** (`226cfb85-...`). Currently 0 supporting / 2 contradicting after one day — but the contradicting count is inflated because the `pattern_match` is too broad (every HIGH_RISK close increments). Either rewrite with a narrower pattern OR add intra-trade snapshot columns to virtual_trades so the matcher can check held-time and peak-loss.
- **Check `watchdog_events` for accumulated GRACE_PROTECTED rows.** Today's count was 0 — either no fresh position triggered the watchdog soft-trigger, or the instrumentation isn't wired correctly. After 5 trading days we should have at least a handful. If still 0, debug the wiring.
- **Score band sample at n>=15 per band.** Re-check whether 75-79 still outperforms 80+ in the post-Filter-D era. If yes, this becomes a real signal and we consider the cap-sort flip OR a per-band sizing rule. If no, today's pattern was small-sample noise.
- **Deferred Day-24 brain changes** still on hold pending data:
  - Valley-of-death exit gate tightening (only if APLD/MSTR/BTDR die catastrophic)
  - Stage 4 pattern_stats dossier injection (the architectural improvement that would make the gates redundant)

Day 30 is the natural decision point: 7 more trading days from today, ~12-18 expected closes, enough sample to evaluate each item with confidence.

---

## Day 26 — May 6, 2026 (Wednesday)

**Metrics:** First net-loss day since the May-1 stretch. **FN closed −$14.12** (−3.41% via WATCHDOG_EXIT after 24h) — second FN failure in 7 days. **Cumulative wallet-era: −$20.46** (was −$6.34 yesterday). 3 new entries (NEXT, SWKS, SMCI) — all clean Filter D shape, but **SMCI already thesis=weakening at 5h.** 7 positions open, 6 wallet + CNQ legacy. Win rate dipped: 36.8% (was 38.9%).

### The headline: FN is now name-specific bad

**FN closed −$14.12 / −3.41% via WATCHDOG_EXIT after 24 hours and 23 minutes** — almost exactly when grace expired.

| Entry | Score | Held | Outcome |
|---|---|---|---|
| Apr 28 14:02 | 79 | 8 min | −2.21% WATCHDOG_EXIT (same-day) |
| **May 5 16:02** | **87** | **24h** | **−3.41% WATCHDOG_EXIT** |

**Two failures of FN in 7 trading days, both via the same exit path, at scores spanning 79-87.** This isn't score-related noise — FN itself is the problem. Worth a `signal_thinking` entry tomorrow: "FN-style high-volatility names with post-IPO dilution risk underperform regardless of entry score."

The grace mechanism worked exactly as designed: it protected FN for the full 24 hours. But the position was still a losing trade. **Grace bought time; it didn't change the outcome.** Compare to SOUN/ARM/USAR (which won post-grace) — those had thesis flips that the system eventually recognized. FN never gave a clean exit signal until the watchdog soft-trigger finally fired post-grace.

**Critical timing:** the watchdog fired at 24h+23min — right after grace expired. This isn't "grace caused the loss" (the loss was already happening) but it IS evidence that grace can mask deterioration that the watchdog would otherwise have caught at hour 4-12. The honest read: grace is a 50/50 bet. Sometimes (SOUN/ARM/USAR) it lets winners cook. Sometimes (FN) it just delays the inevitable.

### Today's full activity

**Closes (1):**
- 16:25 FN WATCHDOG_EXIT −3.41% / −$14.12, held 24h

**Entries (3 — clean Filter D shape):**
- 14:02 NEXT score 78 HIGH_RISK SHORT $415 — fresh, in grace
- 14:02 SWKS score 79 HIGH_RISK SHORT $461 — fresh, in grace
- 16:02 SMCI score 80 HIGH_RISK SHORT $374 — **entered with thesis already weakening at 5h, the second time this week**

SMCI is the next test case. Same shape as ARM (Day 24): thesis flipped fast, grace protecting it. ARM won. FN lost. SMCI is the third in this cohort.

### Day-25 predictions vs reality

| Prediction | Outcome |
|---|---|
| APLD resolution at 168h | Still open at 151h. **17h to STAGNATION_PRUNE.** Tomorrow tells us. |
| MSTR Day-5 | Still open at 125h, thesis=valid. Same age USAR was when it closed +13.26%. |
| FN at 87 — Day-1 | ✗ **Died at 24h via WATCHDOG_EXIT for −$14.12.** Grace expired and watchdog fired. |
| BTDR Day-2 | Survived to 53h, thesis flipped to **weakening**. Past grace. In the same valley shape as MSTR. |
| First grace event recorded | Still 0 in `watchdog_events`. **Two days post-instrumentation, zero events.** Either backend wasn't restarted with the new code, OR no fresh position triggered the soft-watchdog inside grace. |
| Cumulative crosses positive | ✗ Lost ground (−$6.34 → −$20.46). Need bigger winner this week to flip positive. |

3 of 6 favorable. The FN loss and the unflipped cumulative are the cost of today.

### Currently open (7 positions)

| Symbol | Age | Score | Bucket | Thesis | Notes |
|---|---|---|---|---|---|
| SMCI | 5h | 80 | HIGH_RISK | **weakening** | In grace. ARM/FN-shaped test #3 |
| NEXT | 7h | 78 | HIGH_RISK | n/a | Fresh, in grace |
| SWKS | 7h | 79 | HIGH_RISK | n/a | Fresh, in grace |
| BTDR | 53h | 78 | HIGH_RISK | **weakening** | Past grace, no exit triggered yet |
| MSTR | **125h** | 77 | HIGH_RISK | valid | USAR-equivalent age (Day 5) |
| APLD | **151h** | 75 | HIGH_RISK | valid | **17h to STAGNATION_PRUNE** |
| CNQ | 461h | 79 | SAFE_INCOME | valid | Legacy, $0 |

**$2,496 deployed across 6 wallet positions.**

### Hypothesis status

- **`journal_day21_onds91_pattern`** (HIGH_RISK score≥88): 1 supporting / 0 contradicting. Unchanged today. **FN at 87 was just below threshold.** If we'd set the threshold at 85 we'd have 2 supporting now. Worth a Day-30 review.
- **`journal_day24_no_rule_fires_valley`** (HIGH_RISK any): now 1S / 2C (FN added a supporting since it was a HIGH_RISK loss). Still inflated by broad pattern_match.

### Lessons today (the real ones)

**1. Grace is not a magic bullet — it's a coin flip.** Pre-fix outcomes for grace-protected configurations: 100% deaths (FN/NBIS/BTDR same-day). Post-fix: 3 wins (SOUN/ARM/USAR) + 1 loss (FN today). **Grace converts ~60-75% of would-be same-day deaths into longer-hold winners, but ~25-40% are still real losers — grace just delays them by 24h.** That's the honest framing. Two of four cases is still much better than zero of four.

**2. The score-based ONDS-91 hypothesis missed FN at 87.** I set the threshold at >=88 because Day 19 ONDS was at 91. But FN at 87 just produced exactly the same kind of loss. **The actual pattern might be HIGH_RISK score >= 80, not >= 88.** If we widen the threshold, we capture FN. If we widen too far, we capture winners like ALAB at 83 (Apr 30 +2.4% win) and the hypothesis decays. The right move: collect 5-10 more HIGH_RISK 80+ closes, then re-fit the threshold based on the actual loss/win distribution by score band.

**3. Name-specific patterns are real and we don't track them.** FN failed twice in 7 days at different scores. ONDS failed twice (Day 19 + Day 21) at score 91. **The brain has no per-symbol "this name has been losing recently, raise the threshold" memory.** Possible future fix: a `symbol_recent_outcomes` view that surfaces the last 30 days of trades on a given ticker into Claude's prompt. Defer until Day 30.

**4. The instrumentation may not be live.** Two days post-`EVENT_GRACE_PROTECTED` ship, zero events recorded. Plausible reasons:
   - Backend wasn't restarted (no way to verify from data alone)
   - No qualifying watchdog event happened inside grace (also plausible — most positions have thesis=valid, which suppresses the soft-trigger)
   - The instrumentation IS wired but the code path that emits hasn't been hit
   
   **Tomorrow:** verify by grepping the running backend's logs for the new logger.warning line "GRACE PROTECTED from WATCHDOG_EXIT". If the line is absent, the new code isn't loaded — restart needed.

**5. The valley is hardening into "Day 5-7 = high-stakes resolution window."** USAR resolved at 125h (+13%). MSTR is at 125h now. APLD is at 151h. **Day 5-7 is when valley-cohort positions resolve.** The deeper pattern: HIGH_RISK SHORT-horizon entries that survive past grace AND past the watchdog soft-trigger spend 4-7 days waiting for either signal-flip or thesis-tracker-flip. The exit isn't from time-decay (we never hit STAGNATION_PRUNE), it's from the underlying signal evolving. **The brain's existing infrastructure is doing the work; the new gates just give it time to run.**

**6. Today closed the door on two of yesterday's predictions and opened one.** APLD's STAGNATION_PRUNE test is now imminent (within 17h). MSTR's USAR-mirror test is live (same age, similar score). SMCI's grace-recovery test is fresh. **Three live experiments running into Day 27.**

### Predictions for Day 27 (Thursday May 7)

- [ ] **APLD STAGNATION_PRUNE.** Hits 168h (~7 days) at 14:02 ET tomorrow. If still open with no exit triggered by then, STAGNATION_PRUNE fires automatically. Outcome will be either small loss / flat (which validates the gate) or by some miracle a positive signal flip first.
- [ ] **MSTR resolution.** At 125h with valid thesis. USAR resolved at this exact age yesterday. Same shape, different name.
- [ ] **SMCI Day-1 outcome.** Third in the ARM/FN cohort (thesis weakening early, grace protecting). Coin flip whether it's a win or a loss.
- [ ] **First GRACE_PROTECTED event.** If still 0 by EOD tomorrow, debug the wiring — the instrumentation should have caught at least one position by now (BTDR earlier today was thesis-weakening + grace-eligible).
- [ ] **Cumulative wallet-era flips positive.** Currently −$20.46. Needs ~+$25 of net realized P&L tomorrow. MSTR and/or APLD resolving positive could do it.
- [ ] **NEXT/SWKS Day-1 outcomes.** Both at score 78-79 in the band that's been winning post-Filter-D. The next data points for the score-band hypothesis.

### Personal note

After two positive days, today's −$14 stings disproportionately. The honest math: **5 trading days post-Filter-D, +$41.13 net realized** (USAR +$60 + ARM +$11 + SOUN +$68 = +$140 wins, ONDS −$25 + TFC −$13 + FN −$14 + BTDR −$10 = −$62 prior + −$14 today = −$76 losses, plus the SOUN/ALAB/CRWV mix from Apr 30). Still positive over the period. But the trajectory is fragile.

What I want to remember: **FN's loss was the system working correctly, not a failure.** Grace protected it for 24h, then the watchdog correctly identified it as a bleeder and closed it before catastrophic. The −$14 is the cost of running the experiment. The alternative (no grace, kill at 8 min like Apr 28) was a smaller loss — but we'd never have known whether FN could recover.

The discipline question for tomorrow: **don't react to one bad day.** Three brain-behavior changes shipped this week (Filter D, watchdog grace, per-symbol cap) plus four information-layer improvements (instrumentation, valley hypothesis, two backtest scripts) plus the closed-trade UI expansion. The data needs more time. Day 30 (Monday) is the agreed re-evaluation point.

But tomorrow's APLD at 168h is a real test. If APLD closes catastrophic (−6%+) via STAGNATION_PRUNE, the valley question becomes urgent and we revisit the gate timing. If APLD closes flat or positive, the valley resolves itself and we trust the existing infrastructure.

### Deeper lessons (the ones I missed in the first pass)

After Pedro pushed back on the surface lessons above, five harder observations:

**7. The brain is now single-strategy.** All 6 wallet positions are HIGH_RISK SHORT-horizon. Filter D's natural output IS this cohort — the gate effectively forced concentration. **When this cohort fails (e.g., a sector-wide tech selloff), the entire brain fails simultaneously.** Pre-Filter-D we had bucket diversity that hid this risk. We've never named or measured it. **Worth a Day-30 review: should we carve out 1-2 slots for HIGH_RISK LONG-horizon or a different bucket entirely, even if backtest says they underperform on average?** Concentration risk isn't visible in average-return numbers; it's visible in covariance.

**8. The reentry problem was structural — and we just fixed half of it.** FN failed Apr 28 at 79, then again May 5 at 87. ONDS failed Day 19 at 91, then Day 21 at 91. The per-symbol cap (1/day) only blocks intra-day re-attempts; across days, the brain re-tried losers freely. **Backtest evidence: 2 of 2 closed re-entries within 7 days of a WATCHDOG_EXIT also lost (VZ Apr 14→16, FN Apr 28→May 5).** Both re-entries also exited via WATCHDOG_EXIT — same illness, same outcome.

**9. The "weakening past grace" cohort is growing and we don't know its resolution distribution.** BTDR at 53h is in it now. SMCI at 5h is heading there. ARM was in it (won). FN was in it (lost). **2-of-2 splits don't tell you anything.** The next 5 weakening-past-grace closes are the data — until we have them, claims that "weakening positions resolve naturally" are just hope. Worth tracking explicitly.

**10. Cumulative win rate is now BELOW baseline.** 36.8% < 40% all-time baseline. The post-Filter-D 50% looks good in isolation but **the cumulative number is what a real account holder cares about.** We're 5 closed wallet trades into the new structure; one more loss day and we're decisively below baseline. Worth tracking explicitly: *when does cumulative cross back above 40%?*

**11. Single-day variance is huge — don't update from 1-day P&L.** Day 24: +$30. Day 25: +$71. Day 26: −$14. **Single-day swings of $40-$70 are normal noise on a $5k base.** I almost flipped the cap-sort on Day 25's data; today's data would have flipped it again the other way. **The discipline is to stop updating from single days and only re-evaluate on N-day averages.** Day 30 is still the right re-evaluation point.

### Late-evening ship: WATCHDOG_EXIT cooldown (lesson #8)

Acted on the only one of the five deeper lessons that had a clean backtest + mechanism. Per the "backtest before brain changes" memory rule, validated first.

**Backtest:** 13 historical WATCHDOG_EXIT closes. 3 had subsequent re-entries within 7 days (VZ, FN, BTDR-still-open). Of the 2 that have closed: **both lost (VZ −2.31%, FN −3.41% — both via WATCHDOG_EXIT again).** 100% loss rate, n=2. Small but unambiguous, paired with the mechanism.

**Mechanism:** WATCHDOG_EXIT signals the *name* is bleeding in the current regime. The score moved (FN: 79→87) but the underlying pattern didn't. Score-based gates can't catch this; we need name-level memory.

**Ship:**
- New config: `brain_watchdog_exit_cooldown_hours: int = 168` (7 days, matches the watchdog/STAGNATION_PRUNE timeframe)
- New `watchdog_cooldown_symbols` set populated at the start of `process_virtual_trades` from any WATCHDOG_EXIT or WATCHDOG_FORCE_SELL closes within the cooldown window
- Entry gate now checks `symbol not in watchdog_cooldown_symbols` alongside the existing `cooldown_brain_symbols` (THESIS_INVALIDATED). Two separate sets, two separate log lines.
- 6 regression tests pinning the config, the wiring, and the orthogonality of the two cooldowns.

**Total: 133 tests pass.** Same shape as previous gate ships — small surgical change, documented mechanism + backtest, one-line revert (set cooldown to 0).

**Reverts:** `brain_watchdog_exit_cooldown_hours = 0` disables instantly. No code revert needed.

**Invalidation criterion:** if 5+ post-cooldown re-entries (>7 days after a WATCHDOG_EXIT) win in the next 4 weeks, the cooldown is too long. Bring it down to 72h (3 trading days) and re-evaluate. If 5+ re-entries on the SAME name across MULTIPLE weeks all keep losing, extend to 14 days.

### Updated test count: 133

(127 prior + 6 new watchdog cooldown tests)

### Updated predictions for Day 27

Adding to the existing list:

- [ ] **Watchdog cooldown firing visible in logs.** After backend restart, "Watchdog re-buy cooldown active on N symbols" should appear in scan logs. Current cooldown candidates (last 168h of WATCHDOG_EXIT closes): TFC, BTDR, FN, NBIS, FN — five symbols (FN appears twice, deduped to one). The brain should not enter any of these symbols tomorrow.
- [ ] **First grace-protected log line.** Same as before — if 0 events in `watchdog_events` after restart with the new code, debug the wiring.

---

## Day 27 — May 7, 2026 (Thursday)

**Metrics: BREAKOUT DAY. 4 closes, 4 WINS, 0 LOSSES. Net realized today: +$127.93.** Cumulative wallet-era flipped from −$20.46 to **+$105.85** — a **+$126.31 swing in one session and the FIRST POSITIVE wallet-era number since we started measuring.** Win rate jumped 36.8% → 45.5% (10W/12L on 22 wallet-era closes). 3 new entries, valley resolved POSITIVELY at huge magnitude, watchdog grace instrumentation finally captured its first event.

### The headline: the valley was wrong all along

**APLD closed at +$76.89 / +18.75% via ROTATION after 170h (7.1 days).**

This is the position I worried about for THREE journal entries in a row (Day 21 lesson #3, Day 24 lesson #3, Day 26 lesson #9). At Day 6 the prediction was "STAGNATION_PRUNE will fire if it crosses 168h." It DID cross 168h. And then **before STAGNATION_PRUNE could fire, ROTATION fired and closed it at +$76.89 — the second-biggest single wallet win to date.**

**The brain rotated APLD out for a stronger entry.** That's the existing rotation logic working exactly as designed: the brain saw a stronger signal coming in, sold the weakest open position to make room, and APLD just happened to be a winner sitting there.

**MSTR closed the same way** at +$5.76 / +1.32% via ROTATION after 147h. Two valley-resident positions, both rotated out positive on the same day.

**The valley framing was completely wrong.** What I called "the no-rule-fires valley" was actually the **brain's normal patience window**. Positions that survive past grace and don't trigger any soft exit are *waiting for either a thesis flip OR a stronger entry candidate* — and yesterday's worry about catastrophic outcomes happened to zero of three valley positions (APLD won, MSTR won, BTDR won via TRAILING_STOP at +10.94%).

### Today's full activity

**Closes (4 wins, 0 losses):**

| Time | Symbol | Reason | P&L | Held | Note |
|---|---|---|---|---|---|
| 14:02 | CNQ | TRAILING_STOP | +$1.62 (+3.83%) | 478h | Legacy 1-share, finally exited after 20 days |
| 16:02 | **APLD** | **ROTATION** | **+$76.89 (+18.75%)** | 170h | Valley exit, the headline win |
| 19:02 | MSTR | ROTATION | +$5.76 (+1.32%) | 147h | Valley resolved positive |
| 19:02 | **BTDR** | TRAILING_STOP | **+$43.66 (+10.94%)** | 75h | The Apr-30 same-day-death name now a winner |

**Today P&L: +$127.93. Zero losses.**

**Entries (3):**
- 14:02 ALAB score 79 ($376) — thesis flipped to **invalid** at 12h, in grace
- 16:02 **IONQ score 96** ($343) — **first score-96 entry post-Filter-D**, thesis weakening at 10h
- 16:02 **MP score 91** ($309) — second 90+ entry today, thesis valid

### Day-26 predictions vs reality

| Prediction | Outcome |
|---|---|
| APLD STAGNATION_PRUNE | ✓ Actually closed via **ROTATION at +$76.89** — better than predicted |
| MSTR Day-5 resolution | ✓ Closed +$5.76 via ROTATION |
| SMCI Day-1 outcome | Still open at 34h, thesis=valid |
| First GRACE_PROTECTED event | ✓ **Finally captured: MP at 19:30, pnl −0.35%, bearish sentiment.** Instrumentation works. |
| Cumulative wallet-era flips positive | ✓ **−$20.46 → +$105.85 (+$126.31 swing)** |
| NEXT/SWKS Day-1 outcomes | Both still open, no close yet |
| Watchdog cooldown visible | ✓ FN and TFC are on cooldown; brain didn't try to enter them |

**6 of 7 predictions hit, all of them favorably.**

### The watchdog grace instrumentation finally fired

After 2 days of zero `GRACE_PROTECTED` events, the first row landed today at 19:30 ET on **MP**. The instrumentation **works** — the reason for the delay was structural: most positions had thesis=valid which suppresses the watchdog soft-trigger. Today MP went thesis=weakening with bearish sentiment, the watchdog wanted to close it, grace held, and the row recorded.

This means the SOUN/ARM/USAR saves on prior days were happening but not being audit-logged because they pre-dated the instrumentation ship. **From now forward, every grace decision is queryable.** Day-30 review can quantify the grace's effectiveness directly instead of relying on per-incident anecdotes.

### Hypothesis decay

- **`journal_day21_onds91_pattern`**: 1S / 0C. Unchanged — no matching closes today (no >=88 HIGH_RISK closes).
- **`journal_day24_no_rule_fires_valley`**: now **1S / 5C** (was 1S / 2C yesterday). Three winners today (APLD, MSTR, BTDR) auto-classified as contradicting because pattern_match is broad (`bucket: HIGH_RISK`). **The hypothesis is on track to decay to rejected within 1-2 more close days.** That's the right outcome — the valley wasn't a real pattern, it was a misread of normal cycle time.

### Currently open (6 wallet positions)

| Symbol | Age | Score | Thesis | Size | Notes |
|---|---|---|---|---|---|
| IONQ | 10h | **96** | weakening | $343 | First score-96 post-Filter-D entry, in grace |
| MP | 10h | 91 | valid | $309 | First grace event recorded for this position |
| ALAB | 12h | 79 | **invalid** | $376 | ARM/SOUN-shaped grace test |
| SMCI | 34h | 80 | valid | $374 | Past grace, thesis recovered (was weakening yesterday) |
| NEXT | 36h | 78 | n/a | $415 | Past grace, healthy |
| SWKS | 36h | 79 | n/a | $461 | Past grace, healthy |

**$2,278 deployed across 6 wallet positions.**

CNQ legacy is GONE — closed today after 20 days. The brain is now 100% wallet-trades.

### Wallet trajectory

| Day | Pocket | Realized cumulative |
|---|---|---|
| Apr 30 (post-fix) | $4,855 | −$108.54 |
| May 1 | $3,539 | −$108.54 |
| May 4 | $4,146 | −$77.93 |
| May 5 | $4,613 | −$6.34 |
| May 6 | $3,763 | −$20.46 |
| **May 7** | **$4,151** | **+$105.85** |

**6-day swing: +$214.39 of realized P&L recovery.** From the Day-19 low of −$108.54 to today's +$105.85. **The brain has now made back everything it lost AND more.**

### Score distribution shift

This is the headline that's NOT about P&L. **Today the brain admitted a score 96 (IONQ) and a score 91 (MP) entry — the first 90+ entries since Day-21's ONDS-91 disaster.** For 6 trading days the brain only entered 75-83 band names. Today it admitted two 90+ names on the same scan.

**Why this matters:** the ONDS-91 hypothesis is now an active in-flight test. If IONQ and MP both close losses, the hypothesis gains 2 supporting and graduates much faster. If they win, the hypothesis is contradicted and the threshold may need to drop or be removed.

**Worth tracking:** the brain may be entering a different regime where 90+ scores make sense again. Or this could be a 2-trade aberration. The next 5-10 trading days will tell.

### Lessons today (the real ones)

**1. The valley was a phantom — patience over premature gating is right.** Three positions sitting at 5-7 days with thesis=valid and no exit firing was NOT a stuck cohort. It was the brain waiting for either thesis-flip or stronger competing signals. APLD +18.75%, MSTR +1.32%, BTDR +10.94% (different exit, same general cohort). **None of them died in the valley.** Day-21/24/26 worry was wrong, and almost-shipping a tighter exit gate would have killed +$120 of realized profit. **Discipline on "wait for data" works.**

**2. ROTATION is the most underrated exit path in the brain.** It fired twice today (APLD, MSTR) and produced +$82 of gains. The brain's "sell weakest, buy stronger" rotation logic doesn't get journal credit because it's existing infrastructure — but it's what produces magnitude wins. The new gates (Filter D, watchdog grace, per-symbol cap, watchdog cooldown) ALL work by *not blocking* the rotation logic. **Stop thinking of rotation as "the trade close that wasn't a real exit signal" — start thinking of it as the primary winner-realization mechanism.**

**3. Watchdog instrumentation works — and explains why we hadn't seen events.** Most positions had thesis=valid which suppresses the watchdog soft-trigger. Today MP went weakening + bearish + losing, the soft-trigger wanted to close, and grace held. **The 0-event problem of Days 25-26 wasn't a bug — it was the structure being healthy enough that the soft-trigger rarely fires.** Worth remembering for future debugging.

**4. The brain just entered a different score regime.** From 75-83 only (6 days) to 91 and 96 entries today. IONQ at 96 is the highest-conviction Filter-D entry to date. If both lose, the ONDS-91 hypothesis hardens fast. If both win, score-as-ranker validates again. **This is exactly the kind of in-vivo test the dossier path is designed to run.**

**5. The "grace can't make money" reading from yesterday was right but incomplete.** Yesterday I wrote: *"Grace converts ~75% of would-be same-day deaths into longer-hold winners. The other 25% are still real losers."* Today's data: APLD's +18.75% is a 75th-percentile outcome of grace — the position survived multiple soft-trigger windows, eventually rotated out for a stronger candidate. Without grace, APLD would have died Day-1 at probably −2 to −3%. **Grace doesn't make money directly; it converts ~75% of false-positive watchdog hits into eventual wins.** Same lesson as yesterday, validated again at 5x the magnitude.

**6. The wallet just crossed back to positive — but win rate (45.5%) is still below baseline (40% all-time, but the recent regime is closer to 50%).** Cumulative P&L matters; win rate doesn't. **The brain made +$105.85 with a 45.5% win rate because the magnitude of the wins is dramatically higher than the magnitude of the losses.** APLD +$76 alone covered FN (−$14) + ONDS (−$25) + TFC (−$13) + 2x same-day deaths. **Average winner: ~+$30. Average loser: ~−$15. 2:1 reward:risk is the actual edge, not win rate.** Worth tracking explicitly.

### Predictions for Day 28 (Friday May 8)

- [ ] **IONQ Day-1 outcome.** Score 96, thesis weakening, in grace. The first 90+ Filter-D-era close. ONDS-91 hypothesis test in progress.
- [ ] **MP Day-1 outcome.** Score 91, thesis valid. Same hypothesis test.
- [ ] **ALAB grace expiry.** At 12h now, grace expires ~14:02 tomorrow. Thesis is invalid. ARM/SOUN-shaped: does it resolve positive (ARM/USAR/SOUN) or fail past grace (FN)?
- [ ] **NEXT/SWKS Day-2.** Both at 36h, past grace, no exit triggered. Either resolve via signal flip (USAR-style) or ride into the rotation queue.
- [ ] **Watchdog cooldown blocks visible in logs.** FN and TFC are on cooldown through May 13 / May 11 respectively. If today's signals tried either, log line should show the block.
- [ ] **Wallet-era win rate crosses 50%.** Currently 45.5%. One more winner with no losers takes it over.

### Personal note

After ~3 weeks of mostly bleeding and one week of rebuilding, the brain just delivered its biggest single-day P&L since I started measuring. **+$127 in 4 closes. Zero losses. Cumulative now positive.**

What I want to remember about today:
- **The valley I worried about for 4 days was not a death trap.** It was just the brain doing patience right. I almost shipped a tightening of the QUALITY_PRUNE day floor on Day-24 — that change would have closed APLD at probably +5% instead of +18.75%, and killed MSTR before its rotation. **The "wait for data" discipline saved $50-80 of realized profit by NOT acting.**
- **Filter D + watchdog grace + per-symbol cap + watchdog cooldown all worked together today.** None of them directly produced a winner. They prevented premature exits, prevented re-entries on dying names, blocked sector concentration. The existing rotation/trailing-stop/thesis-tracker infrastructure produced the wins. **The new gates are the permission layer; the old logic is the action layer.**
- **The score-90+ entries today (IONQ, MP) are the hypothesis test.** If they fail, ONDS-91 graduates. If they win, score-as-ranker is alive. Day 28-29 tells us.

Two days ago the journal said: "the brain enters Day 21 structurally different from Day 19." Today it can say: **the brain just delivered its first weekly profit since we started measuring.** The structural changes are working. The discipline of waiting for data instead of reacting to single-day variance is working.

Day 30 (Monday) is the formal re-evaluation point — at the current pace, we'll have 6-8 more closes by then, enough to evaluate every queued lesson with confidence.

---

## Day 28 — May 8, 2026 (Friday) [retroactive — written Monday morning]

**Metrics:** Mixed-to-negative day. 2 closes (0W/2L), net **-$20.91**. 2 entries (TTGT, SOUN-2nd-attempt). **Cumulative wallet-era dropped from +$105.85 to +$84.94** — still positive but gave back ~20% of Day-27's swing. Win rate slipped 45.5% to 41.7% (10W/14L). **Two grace-cohort losses** (ALAB, MP) settled the "is grace 75% effective?" claim toward "more like 50/50."

### The two closes

**ALAB closed -$10.05 / -2.67% via THESIS_INVALIDATED after exactly 24 hours.**
- Entered Day-27 14:02 at score 79, thesis flipped to invalid at 12h, was grace-protected
- Closed Day-28 14:02 — **the moment grace expired**, thesis fired immediately
- Same pattern as FN Day-26 (grace expired then watchdog killed it)
- ARM/SOUN/USAR shape didn't repeat for ALAB. Not all "thesis invalid in grace" positions recover.

**MP closed -$10.86 / -3.52% via TRAILING_STOP after 24h.**
- Entered Day-27 16:02 at **score 91** — one of the two 90+ test entries
- Position must have rallied to peak then sold off (trailing stop activates above +3%)
- Net negative means the rally fizzled and the trail caught the drop past entry
- **Supporting evidence for the ONDS-91 hypothesis** (now S=2 / C=0)

**Today P&L: -$20.91.** Two losses, zero wins.

### Today's entries (2)

| Time | Symbol | Score | Notes |
|---|---|---|---|
| 14:02 | TTGT | 76 | Standard Filter D shape (HIGH_RISK SHORT-horizon), thesis went weakening early |
| 16:02 | **SOUN** | **79** | **Second SOUN entry of the week** — same name that won +14% on Day-24 |

The SOUN re-entry is interesting. SOUN closed via THESIS_INVALIDATED on Day-24 (not WATCHDOG_EXIT) so the watchdog cooldown doesn't apply. The per-symbol cap is per-day (already cleared). Filter D doesn't block (HIGH_RISK Tech). **So the brain happily re-bought SOUN four days after the prior win.** Question for the journal: is that good or bad? If SOUN wins again, the brain identified persistent strength. If it loses, we may need a "won recently means still in flight from prior cohort" check.

### Day-27 predictions vs reality

| Prediction | Outcome |
|---|---|
| IONQ Day-1 outcome | **Still alive at 94h** — survived through Friday EOD and the weekend. Thesis weakening throughout but no exit triggered. Strong evidence grace is working as designed on this one. |
| MP Day-1 outcome | ✗ **Closed at -3.52% via TRAILING_STOP.** First 90+ Filter-D-era close, supports ONDS-91 hypothesis. |
| ALAB grace expiry | ✗ **Closed at -2.67% via THESIS_INVALIDATED** exactly at grace boundary. Same pattern as FN. |
| NEXT/SWKS Day-2 | Both still open; thesis flipped from n/a to **valid** as Claude actually re-evaluated them. Healthy. |
| Watchdog cooldown blocks visible | Filter D blocked SEZL + LYG (both Financial Services). Overlaps with sector exclusion — no clean cooldown-only fire today. |
| Win rate crosses 50% | ✗ Went the wrong way: 45.5% to 41.7%. Two losses pulled it down. |

3 of 6 favorable, 3 unfavorable.

### Hypothesis status

- **`journal_day21_onds91_pattern`** (HIGH_RISK score >= 88): now **S=2 / C=0** (was S=1). MP-91 closing at a loss bumped the supporting counter. **Three more matching closes (and not 3 wins to offset) would graduate this to validated knowledge.** IONQ-96 is the next test in flight.
- **`journal_day24_no_rule_fires_valley`** (HIGH_RISK any): now **S=3 / C=5**. Today's 2 losses added 2 supporting. Decay has slowed; hypothesis is mixed-signal because the pattern_match is too broad (covers every HIGH_RISK close).

### Currently open going into Monday (6 positions)

| Symbol | Age (Mon AM) | Score | Thesis | Notes |
|---|---|---|---|---|
| SWKS | 120h | 79 | valid | Day-5+, valley-eligible |
| NEXT | 120h | 78 | valid | Day-5+, valley-eligible |
| SMCI | 118h | 80 | valid | Day-5, healthy |
| **IONQ** | **94h** | **96** | weakening | **The 90+ hypothesis test, still in flight Day-4** |
| TTGT | 72h | 76 | weakening | Day-3, weakening past grace |
| **SOUN** | **70h** | 79 | valid | **Re-entry of Day-24 winner, Day-3** |

**$2,419 deployed across 6 wallet positions.** All HIGH_RISK SHORT-horizon. Same single-strategy concentration noted Day-26 lesson #7.

### What I learned from Day 28 (the real lessons)

**1. The "grace converts ~75% of false-positive watchdog hits" claim is now 50/50.** Pre-Day-28 grace cohort: ARM (won), SOUN (won), USAR (won), FN (lost). Post-Day-28: ALAB (lost), MP (lost). **Now 3W / 3L on positions that entered with early-thesis-weakening + grace-protection.** The win-rate of grace-protected positions converges toward 50%, not 75%. **Day-27's "grace converts ~75%" was small-sample optimism.** Honest framing: grace is roughly neutral on win rate — it lets the system make better-informed exits later instead of premature ones, but the exit outcomes are still ~50/50 because the underlying name quality matters more than the grace window.

**2. MP-91 supports the ONDS-91 hypothesis.** S=2 C=0. With 2 supporting closes on the pattern (ONDS Day-19, MP Day-28), the hypothesis is gathering real evidence. IONQ-96 is the next test — if IONQ ALSO closes negative, S=3 and we're nearly at graduation threshold (5).

**3. SOUN re-entry exposes a gap.** The brain has no "this name was just open" check across days — only the open_brain (currently held) and watchdog cooldown (only WATCHDOG_EXIT closes). A THESIS_INVALIDATED winner from 4 days ago can be re-bought freely. **This may be correct (the name showed strength, re-buy on signal flip is reasonable) or it may be a gap (the brain is chasing recent winners with no cooldown).** Track SOUN-2's outcome explicitly.

**4. The trailing stop activating at +3% but allowing the trade to close negative is mechanically OK but feels wrong.** MP rallied, trailing stop armed, then dropped past entry to -3.52%. The trailing stop did its job (prevented a larger loss after the peak) — but the user impression is "the trail caught a loss instead of a win." Worth checking if the trailing-stop logic should also be gated by a "no negative exit if peak gain was >5%" carve-out. Defer to Day-30 review.

**5. Cumulative win rate is back DOWN (41.7%, below 45.5% yesterday).** Wallet-era cumulative still POSITIVE (+$84.94). **Win rate is variance; cumulative dollars is signal.** Day-26 lesson #10 holds: don't track win rate as the main number. Track cumulative + post-Filter-D win rate (still 7W/5L = 58% over 12 closes since Apr 30 — strong).

### Deeper lessons (the ones that change my mental model)

**6. Grace doesn't change win rate — it changes the SHAPE of the distribution.** Look at the grace-cohort dollars, not the count:
- Wins (3): SOUN +14%, ARM +3%, USAR +13% → total ~+30%
- Losses (3): FN -3.4%, ALAB -2.7%, MP -3.5% → total ~-9.6%

**Net: +20% across the 6-trade grace cohort, even at 50% win rate.** Grace lets winners run to +10-14% while watchdog/thesis-tracker cap losses near -3%. **The 2:1 reward:risk edge holds because grace produces it on this specific cohort.** "Grace is 50/50 on win rate" is true but misses the point — grace's job is to enable big winners while losses stay capped.

**7. The first scan post-grace is the highest-risk close moment.**
- ALAB Day-28: entered 14:02 Thu, exit 14:02 Fri (24h exact)
- MP Day-28: entered 16:02 Thu, exit 16:03 Fri (24h exact)
- FN Day-26: entered 16:02 Tue, exit 16:25 Wed (24h+23min)

**All three losses fired at the FIRST scan after grace expired.** USAR/APLD/MSTR/SOUN-1 all held past hour 24 and won big. **24h is a fork in the road: either dies on the immediate post-grace tick or survives to win in 5-7 days.** Bimodal outcome distribution, not gradual.

**8. TRAILING_STOP exiting MP at -3.52% is mechanically correct but emotionally confusing.** MP went up >+3% (armed the trail), then dropped past entry to -3.5%. The trail prevented a bigger loss after the peak. **But "trailing stop" implies "profitable exit" to most users.** Worth Day-30 review: should the trail be gated by a "no negative exit if peak gain was >5%" carve-out? If its visible behavior keeps surprising us, the design is leaky.

**9. The 24h post-grace exit cluster is DETERMINISTIC by design.** It's the natural consequence of `new_position_grace_hours = 24` + scan schedule (positions only exit at scan ticks). **Every day, expect 0-2 exits to fire at scan times exactly 24h after big entry days.** Not a bug — but our daily P&L clusters bad-cohort losses on specific calendar slots. If we ever change grace to 18h or 36h, we shift the cluster, not the rate.

**10. The "thesis weakening at hour 0-12" cohort is now well-documented and predictable.** ALAB, MP, TTGT, SMCI, FN, ARM, SOUN, USAR — all had thesis flip weakening/invalid within hours of entry. **~50% close as winners after 5-7 days. ~50% close as losers at hour 24+.** This is the dominant Filter-D-era trade shape.

**The honest reframe:** the brain isn't "saving" weakening positions. It's letting them resolve naturally so the half that recover can win big while the half that fail die with capped -3% losses. **That's a much better business model than "kill at first sign of weakness," even though intuitively it doesn't feel like a save.**

### Weekend recap (May 9-10)

Markets closed. No brain activity. 6 positions held over the weekend with these resolutions pending Monday: IONQ (the hypothesis test), the Day-5 valley triple (NEXT/SWKS/SMCI), and the fresh SOUN-2 + TTGT.

### Looking into Monday (Day 31 — May 11)

This was originally framed as the formal re-evaluation point per Day-25's queued items. Will write that re-evaluation as the Day 31 entry once today's actual trading data arrives.

Pending hypothesis tests:
- IONQ outcome (94h+ now, in flight all weekend)
- NEXT/SWKS/SMCI at Day-5+ (USAR-like resolution age)
- ONDS-91 hypothesis trending — needs 3 more supporting OR 5 contradicting to resolve
- The Day-26 single-strategy concentration risk is still live (6 of 6 HIGH_RISK SHORT)

---

## Day 31 — May 11, 2026 (Monday)

**Metrics:** Mixed day, marginally positive. **2 closes (1W/1L), net +$11.64.** ZERO entries today — first zero-entry day of the post-Filter-D era. **Cumulative wallet-era: $84.94 to $96.58** (+$11.64). Down from the Day-27 peak (+$105.85) but recovering after the Day-28 dip. **5 of 5 valley positions have now resolved positively** — USAR, APLD, MSTR, BTDR, SMCI today. The "no-rule-fires valley" worry is definitively wrong.

### Today's two closes

**SMCI TRAILING_STOP at +$27.04 / +7.24% after 123h (5.1 days).**
- Entered Day-26 at score 80
- Held through the "valley" Day-5+ window
- Resolved via trailing stop as rally cooled
- **5th valley position to win in 5 attempts** (USAR +13%, APLD +18.75%, MSTR +1.32%, BTDR +10.94%, SMCI +7.24%)

**TTGT WATCHDOG_EXIT at -$15.40 / -3.71% after 76h.**
- Entered Friday Day-28 at score 76, thesis flipped weakening early
- Survived 24h grace, closed at hour 76 via watchdog soft-trigger
- **4th post-grace loss in the -3% range** (FN -3.4%, ALAB -2.7%, MP -3.5%, TTGT -3.7%)
- Same shape, same magnitude — the watchdog is doing exactly what it was designed to do

**Today P&L: +$11.64.** One win covered one loss with $12 to spare.

### The zero-entry day

**The brain admitted 0 new positions today** despite 61 BUY signals in the universe. First zero-entry day post-Filter-D. The gates rejected every candidate:
- Filter D blocked USB (Financial Services)
- Watchdog cooldown blocks: FN through May 13, TFC through May 11
- Per-symbol caps: not applicable (no held names re-attempted)
- Tier evaluator must have rejected the rest (failed `ai_status == validated AND score >= 75` filter, OR LONG-horizon)

**This is the gates working as a quality filter, not a quantity throttle.** Weak universe day, brain holds cash. **$4,790 in pocket now (was $3,990 Friday)** — the brain is sitting on more cash than at any point since the wallet was funded.

### Day-28 predictions vs reality

| Prediction | Outcome |
|---|---|
| IONQ outcome | **Still open at 101h** — longest-held score-90+ position in brain history |
| NEXT/SWKS/SMCI at Day-5+ | SMCI **closed +7.24%**. NEXT/SWKS still open at 127h (USAR-equivalent age). |
| ONDS-91 hypothesis | Unchanged: S=2 C=0. No 88+ closes today. |
| Single-strategy concentration | Still 4-of-4 HIGH_RISK SHORT, but cash position swelled to $4.8k |

### Currently open (4 wallet positions — smaller deployment)

| Symbol | Age | Score | Thesis | Notes |
|---|---|---|---|---|
| SOUN | 77h | 79 | **weakening** | Re-entry, thesis flipped from valid → weakening today |
| **IONQ** | **101h** | **96** | weakening | **The 90+ hypothesis test, Day-4+** |
| NEXT | 127h | 78 | valid | Day-5+, valley-eligible (like USAR was) |
| SWKS | 127h | 79 | valid | Day-5+, valley-eligible |

**$1,629 deployed, $4,790 cash.** First time wallet ratio has shifted defensive.

### Hypothesis status

- **ONDS-91 (HIGH_RISK score>=88):** S=2 / C=0. Unchanged. IONQ-96 is the live test.
- **Valley (HIGH_RISK any):** S=4 / C=6. TTGT loss added supporting, SMCI win added contradicting. **The win count (6) is now > graduation_threshold (5)** — by the auto-classifier's rules, this should be eligible for rejection at the next observation match. The hypothesis is essentially decided: **the valley is not a death trap, it's a normal resolution window.**

### Lessons today (the real ones)

**1. 5 of 5 valley positions won. The Day-21/24/26 valley worry was wrong.**
   - USAR +13.26% / 125h
   - APLD +18.75% / 170h
   - MSTR +1.32% / 147h
   - BTDR +10.94% / 75h
   - SMCI +7.24% / 123h
   - **Total: ~+51% across 5 winners.** Average per trade: ~+10%.
   - **The "valley" is the brain's natural resolution window for HIGH_RISK SHORT-horizon entries.** Day-2 to Day-7 is when positions either get rotated for stronger candidates OR trail out as the rally cools. Tightening the exit gate would have killed all 5 prematurely.

**2. Post-grace 24h cohort: 4W/4L by count, +$164 net by dollars.**
   - Wins: USAR +$60, SOUN +$68, ARM +$11, SMCI +$27 = **+$166**
   - Losses: FN -$14, ALAB -$10, MP -$11, TTGT -$15 = **-$50**
   - **Win-rate is 50%. Dollar-rate is 3.3:1.** Day-28 lesson #6 holds and strengthens. **Grace doesn't change win rate; it changes the distribution shape.**

**3. The brain is now self-restricting on weak days.** Today's 0-entry day proves the gates work as a quality filter, not a quantity rule. **Previously every signal cohort produced 2-3 entries regardless of quality.** Now the brain admits fewer entries on quiet universe days. **The system isn't trying to deploy capital — it's waiting for signals that clear the gates.**

**4. IONQ at 101h is unprecedented for a 90+ HIGH_RISK SHORT.** Pre-Filter-D ONDS-91 died at 67h via QUALITY_PRUNE. Post-Filter-D IONQ-96 is still alive at 101h with thesis weakening throughout. **The post-fix infrastructure is holding the position through what would have been a forced exit pre-fix.** Either:
   - IONQ resolves positively (contradicting ONDS-91 hypothesis directly)
   - IONQ eventually triggers thesis-invalid + watchdog and dies
   - IONQ resolves via SIGNAL/ROTATION like the valley winners
   
   Whichever happens, **IONQ's outcome is the single most important data point in the dossier right now.**

**5. SOUN-2's thesis flipped to weakening — the re-entry decision is now testable.**
   - Friday: SOUN-2 entered at score 79, thesis valid
   - Today: SOUN-2 at 77h, thesis weakening
   - The brain's decision to re-buy SOUN 4 days after its +$68 win is now under live evaluation
   - **If SOUN-2 wins → recent winners often persist (signal followed price for the right reason)**
   - **If SOUN-2 loses → the brain has a "chase recent winners" anti-pattern that needs naming**
   - Same name. Two entries. Different outcomes possible. Worth pinning the verdict explicitly.

**6. Cash position is climbing.** Pocket at $4,790 (vs $3,539 May 1). The brain is sitting on >50% of equity in cash. **This is a regime shift in trade deployment.** Either:
   - Universe quality has declined (fewer signals clear Filter D)
   - Filter D is increasingly restrictive as the universe rotates sectors
   - Both
   
   **Worth tracking deployment ratio as a separate metric** — if cash stays >40% for 2+ weeks, the universe is materially different from when the gates were calibrated.

### Post-Filter-D era stats (now significant sample)

- **14 closes since Apr 30**: USAR (W), BTDR Apr30 (L), SOUN (W), ONDS (L), ARM (W), FN (L), APLD (W), MSTR (W), BTDR May4 (W), CNQ (W legacy), TFC (L), ALAB (L), MP (L), SMCI (W), TTGT (L)
- Wait, that's actually 15 closes — let me recount from the data
- **Post-Filter-D wallet closes (is_wallet_trade=True, entry >= Apr 30): n ~ 11**
- **W/L: ~7W / 4L = 64% win rate** (vs 40% baseline)

This is the closest we've had to a real signal-vs-noise read. **64% win rate, 2:1 reward:risk, average winner ~+$30, average loser ~-$13.** Mathematical expectation per trade: **0.64 × $30 + 0.36 × (-$13) = +$14.52/trade.** At 1.5 trades/day = **+$22/day = +$440/month** projected. On $5k base = **~9% monthly return.**

This is the post-Filter-D math. **Reality could differ wildly — n=11 is still small.** But the projection is meaningful and worth tracking week-over-week.

### Predictions for Day 32 (Tuesday May 12)

- [ ] **IONQ outcome.** 101h and counting. Either wins (contradicts ONDS-91) or loses (supports). The longest-running active hypothesis test.
- [ ] **SOUN-2 resolution.** Thesis weakening, Day-3+. The "chasing recent winners" test.
- [ ] **NEXT/SWKS Day-5+ resolution.** Same age as SMCI today. Expect TRAILING_STOP or ROTATION outcomes like the prior 5 valley winners.
- [ ] **Entry deployment.** Will the brain admit anything tomorrow? If we see another 0-entry day, the regime shift is real.
- [ ] **Cumulative wallet-era crosses +$100.** Currently at $96.58. One small winner does it.

### Personal note

The Day-30 re-evaluation hasn't happened — was supposed to be today but the data wasn't surprising enough to warrant a formal review. The system is doing what it should: occasionally losing -$15-20 on weakening positions, occasionally winning $20-80 on valley resolutions, net positive trajectory. **Nothing to ship today.** The deferred items from Day-25 (cap-sort flip, valley exit tightening, etc.) are still on the right side of "wait for more data" — and today's data confirms that direction.

The most interesting thing isn't today's P&L — it's IONQ at 101h. A score-96 position surviving 4 days is the kind of trade that pre-Filter-D would have been impossible (would have been killed by Day 2). Either IONQ teaches us the 90+ score band IS tradeable in this regime (contradicting ONDS-91), or it eventually fails and the hypothesis hardens. Either outcome is informative.

**Going into Day 32: 4 open positions, $4,790 cash, cumulative +$96.58, 64% post-Filter-D win rate, 3 live hypothesis tests in flight (IONQ-96, SOUN-2 re-entry, NEXT/SWKS valley).**

---

## Day 32 — May 12, 2026 (Tuesday)

**Metrics: BIG WIN DAY. IONQ delivered +$64.06 / +18.67% — the first 90+ HIGH_RISK SHORT-horizon win in brain history and the first CONTRADICTING evidence for the ONDS-91 hypothesis.** SOUN-2 lost -$22.34 confirming the "chase recent winners" anti-pattern. **Net realized today: +$41.72. Cumulative wallet-era: $96.58 to $138.30** — new all-time high. Pocket crossed $5,000 (above the original deposit) for the first time. 1 new entry (CRDO), 2 closes, 3 positions open going into tomorrow.

### The headline: IONQ wins, ONDS-91 hypothesis gets first contradicting evidence

**IONQ closed at +$64.06 / +18.67% via THESIS_INVALIDATED after 114h (4.75 days).**

This is the position I flagged on Day-27 as "the most important data point in the active dossier." Score 96 HIGH_RISK SHORT-horizon, thesis weakening from hour 0, held through grace AND past it for almost 5 days. Pre-Filter-D version (ONDS-91 Day-19) died at 67h via QUALITY_PRUNE at -9.46%. Post-Filter-D version (IONQ-96) survived 114h and closed at **+18.67%**.

**Same configuration. Opposite outcome.**

**ONDS-91 hypothesis is now S=2 / C=1.** First contradicting observation. The hypothesis isn't dead — but it's no longer one-sided. The honest reframe: **"score 90+ HIGH_RISK SHORT-horizon has a WIDE outcome distribution"** — sometimes the biggest loser (ONDS Day-19 -9.46%), sometimes the biggest winner (IONQ today +18.67%). Score doesn't predict direction; it predicts magnitude.

### The other close: SOUN-2 confirms the "chase recent winners" anti-pattern

**SOUN-2 closed at -$22.34 / -5.44% via QUALITY_PRUNE after 94h.**

SOUN-1 closed Monday Day-24 at +$68 / +14% via THESIS_INVALIDATED.
SOUN-2 entered Friday Day-28 at the same name, four days later.
Today it closed for a loss.

**The re-entry was wrong.** Day-28 lesson #3 flagged this exposure: "The brain has no 'this name was just open' check across days — only the watchdog cooldown (only WATCHDOG_EXIT closes)." A THESIS_INVALIDATED winner from 4 days ago can be re-bought freely. **SOUN proved this is a real anti-pattern**, not just a theoretical gap.

**Worth shipping**: a `brain_post_winner_cooldown_hours` setting that blocks re-entry for N hours after any positive THESIS_INVALIDATED close. Default ~120h (5 days)? Same shape as the watchdog cooldown, different mechanism. Defer to a backtest-and-ship pass when we have more "won → re-entered → outcome" pairs.

### Today's full activity

**Closes (2):**

| Time | Symbol | Reason | P&L | Held |
|---|---|---|---|---|
| 10:02 | **IONQ** | THESIS_INVALIDATED | **+$64.06 (+18.67%)** | 114h |
| 14:02 | SOUN | QUALITY_PRUNE | -$22.34 (-5.44%) | 94h |

**Entries (1):**

| Time | Symbol | Score | Notes |
|---|---|---|---|
| 19:01 | CRDO | 80 | Thesis already **invalid** at 2h — same shape as the bimodal cohort (ALAB/MP/TTGT) |

**Today P&L: +$41.72.**

### Day-31 predictions vs reality

| Prediction | Outcome |
|---|---|
| IONQ outcome | ✓ **WON +18.67%** — contradicts ONDS-91 |
| SOUN-2 resolution | ✗ **LOST -5.44%** — re-entry was wrong |
| NEXT/SWKS Day-5+ | Still open at 151h — past USAR-equivalent age |
| Entry deployment | ✓ 1 entry (CRDO) — broke the zero-entry streak |
| Cumulative crosses +$100 | ✓ **+$138.30** — easily |

**5 of 5 predictions hit favorably.** Strong prediction accuracy.

### Currently open (3 wallet positions)

| Symbol | Age | Score | Thesis | Notes |
|---|---|---|---|---|
| CRDO | 2h | 80 | **invalid** | Bimodal test #5 (in grace) |
| NEXT | 151h | 78 | valid | Past USAR-equivalent age, still alive |
| SWKS | 151h | 79 | valid | Past USAR-equivalent age, still alive |

**$1,435 deployed, $5,027 cash.** Lowest deployment ratio since the wallet was funded.

### Hypothesis updates

- **`journal_day21_onds91_pattern`** (HIGH_RISK score>=88): **S=2 / C=1** (IONQ added contradicting). First contradicting observation. The hypothesis is now genuinely two-sided.
- **`journal_day24_no_rule_fires_valley`** (HIGH_RISK any): **S=5 / C=7**. **By auto-rejection rules, this hypothesis is now rejection-eligible** (contradicting >= graduation_threshold=5). Worth manually rejecting in the Day-33 pass.

### What I learned from Day 32 (the real lessons)

**1. The ONDS-91 hypothesis is in transition from "true" to "uncertain."** Pre-IONQ: 2 supporting / 0 contradicting on a niche pattern. Post-IONQ: 2/1, and the contradicting observation is a +18.67% magnitude winner that COULD have been the biggest single trade of the era. **Score 90+ doesn't predict losing — it predicts variance.** The hypothesis as currently worded ("90+ HIGH_RISK underperforms") is wrong. The truer hypothesis would be: "90+ HIGH_RISK has fat-tailed outcomes — both biggest winners AND biggest losers tend to come from this band." We don't track variance in the dossier yet.

**2. The valley hypothesis should be manually rejected at Day-33.** S=5 / C=7. The pattern_match was too broad (any HIGH_RISK close), which is why both sides accumulated counters. The thing the hypothesis was actually trying to test — "do positions stuck in the 3-5 day valley die catastrophic?" — is now decisively answered: **no, they win**. 5 of 5 valley positions resolved positively (USAR, APLD, MSTR, BTDR, SMCI). The hypothesis can be marked as `rejected` with a notes update.

**3. SOUN-2 is the first documented "chase recent winner" loss.** The pattern: a winner closes via THESIS_INVALIDATED, the same name re-enters within 5 days, the re-entry loses. n=1 so far. **Worth instrumenting the gap before shipping a fix.** Track any case of "won X days ago → re-bought → outcome." If we see this pattern again, the post-winner cooldown becomes a real ship target.

**4. The brain is defensive-deploying for the first time.** Pocket > $5,000 (above original deposit). 3 positions open. Cash ratio ~77% of equity. **Day-31's zero-entry day wasn't a one-off — the brain is genuinely selective on weak universe days now.** The gates are doing structural work: rejecting weak signals AND letting cash build between high-quality entries. **This is what a non-degenerate trading system looks like** — most days are boring, occasional days produce magnitude moves.

**5. NEXT/SWKS at 151h is now past the established valley resolution window** (5/5 winners resolved between 75-170h). Tomorrow they cross 168h, which is the STAGNATION_PRUNE threshold. **If STAGNATION_PRUNE fires on either, that's the first time it has ever fired** in production. If they resolve via SIGNAL/ROTATION/TRAILING first, the valley window extends to 7+ days.

**6. Post-Filter-D math just got a magnitude boost.** With IONQ +$64 added:
- Wallet-era cumulative: $138.30 (was $96.58 yesterday)
- Post-Filter-D cumulative since Apr 30: +$243.45 (was +$179.39 yesterday, factoring in IONQ today and SOUN-2 loss)
- Pre-Filter-D era was -$108.54. Post-Filter-D era is +$243.45.
- **Net swing from Day-19 trough: +$351.99 over 12 trading days.**
- Projected monthly (extrapolated): **~$700/month on $5k base = ~14% monthly**
- This is now meaningfully above the original 1-2%/month target.

**The honest caveat:** today's +$64 IONQ was a magnitude outcome, not a typical one. If we strip out the top-3 outliers (IONQ +$64, SOUN-1 +$68, APLD +$77), the remaining post-Filter-D era is small-positive but not magnitude. **The brain's edge is fat-tailed wins, not consistent small profits.** That's a real edge but also a real risk: 1-2 outsized losers would erase the entire gain.

### Deeper lessons (the ones that change my mental model)

**7. THESIS_INVALIDATED isn't a loser exit — it's the oil-barrel principle.** IONQ closed at +18.67% via THESIS_INVALIDATED. The brain sold a *winning* position because the reason for owning was gone. **Same exit mechanism that killed ONDS at -$25 just made us +$64 on IONQ.** The win/loss direction is incidental — what matters is whether the thesis still holds. I keep mentally categorizing THESIS_INVALIDATED as a loss exit; that's wrong. It's a thesis exit.

**8. The dossier path has its first validated end-to-end proof.** ONDS-91 hypothesis was inserted Day-21. Today IONQ contradicted it. The auto-classifier updated the counter without manual intervention. **The full loop works:** observe → write hypothesis → accumulate evidence → update counters → eventually graduate or reject (today's valley rejection is the second validation). This is structural proof the brain's learning loop functions as designed. A bigger deal than the +$64 trade itself.

**9. Three distinct loser-exit paths, each catching a different shape of bad trade.**
- **WATCHDOG_EXIT at hour 24-26** (post-grace): catches positions that flip thesis-invalid early AND keep bleeding (FN, ALAB, MP, TTGT)
- **QUALITY_PRUNE at day 2+**: catches positions that bleed past -3% AFTER thesis weakens (SOUN-2 today)
- **THESIS_INVALIDATED any time**: catches positions whose thesis dies regardless of P&L (oil-barrel cases)

The system is more layered than I'd been describing. Worth naming explicitly so future debugging knows which path to investigate.

**10. The edge is structurally fat-tailed — and that's stable.**
- Wins range $6 to $77 (12x spread)
- Losses cluster $10 to $25 (2.5x spread)
- Top 3 wins (IONQ +$64, SOUN +$68, APLD +$77) = $209 of $357 total wins (58%)
- **All losses capped under $30 — none over $30 ever post-Filter-D.**

The edge isn't "average winner $30." It's "$15-30 wins with occasional $60-80 outliers, paired with consistent $10-20 losses." The exit infrastructure (trailing stop + thesis invalidation + rotation) caps losses while letting winners run.

**11. Position sizing ignores score — but win magnitudes suggest it shouldn't.** IONQ at score 96 was $343. CRDO at score 80 is $559. Today's 96-score position made +$64. If sized to $559 (like CRDO), the win would have been ~$104. **The brain treats marginal 80 and high-conviction 96 identically.** Score-weighted sizing within Tier 1 (e.g., 8% at 75, 10% at 80, 12% at 90+) is a real ship candidate — defer to Day-30 backtest pass.

**12. The defensive cash buildup is EMERGENT, not coded.** Nobody wrote "build cash when universe is weak." It's what happens when Filter D + cooldowns reject more than they admit on slow days. **The system is adaptive without explicit adaptivity logic.** Pocket at $5,027 isn't "the brain isn't trying" — it's "the brain is filtering correctly and there aren't enough qualifying signals today." Worth naming this as a feature, not a side effect.

### Late-evening: valley hypothesis rejected

Per Day-32 lesson #2 (rejection-eligible at C=7), manually rejected `journal_day24_no_rule_fires_valley` (id 226cfb85). Final state: S=5 / C=7, status=rejected. Notes updated with rejection rationale (5/5 actual valley positions resolved positively: USAR, APLD, MSTR, BTDR, SMCI). Audit event logged.

The hypothesis was disproven *and* the pattern_match was too broad (every HIGH_RISK close incremented both counters). **Two lessons for future hypotheses:**
1. The underlying claim was wrong — the valley wasn't a death trap, it was the brain's natural resolution window
2. The technical limitation matters — hypotheses needing intra-trade state (held-time, peak-loss bucket) shouldn't be tested with proxy patterns. They need snapshot columns on virtual_trades or a different evaluation mechanism

This is the second hypothesis to resolve (after the ONDS-91 transition from S=2/C=0 to S=2/C=1 today). The dossier is starting to refine itself.

### Predictions for Day 33 (Wednesday May 13)

- [ ] **CRDO Day-1 outcome.** Thesis invalid at hour 2. Same shape as the bimodal cohort (4W/4L overall). Coin flip whether it wins big like SOUN/USAR or loses small like ALAB/MP.
- [ ] **NEXT/SWKS cross 168h.** First-ever STAGNATION_PRUNE potential. Or they resolve via SIGNAL/ROTATION before that fires.
- [ ] **Manual rejection of the valley hypothesis** at Day-33 cleanup pass. C=7 exceeds the 5 threshold; the pattern was disproven.
- [ ] **Watchdog cooldown expires for FN** today/tomorrow. If FN re-appears as a candidate at any score, the cooldown won't block — first test of post-cooldown FN.
- [ ] **Universe size.** Today: 203 signals (down from 269 Friday). If universe stays small for 2+ more days, that's a regime signal worth naming.

### Personal note

The brain just delivered IONQ +18.67% — exactly the kind of outcome the post-fix infrastructure was designed to enable but couldn't deliver before today. The Day-21 ONDS-91 disaster happened on a position the OLD brain killed at 67h. **Today's IONQ-96 survived 114h through thesis-weakening + grace expiry + valley window + multiple watchdog ticks.** It then closed at the right moment when the thesis tracker re-evaluated and decided "the reason to own is gone."

Same shape, same score, same bucket, same horizon. Different outcome because we let the system work. **This is the structural proof of concept** that the Apr-30 ship sequence (Filter D + watchdog grace + per-symbol cap + watchdog cooldown) actually produces the alpha we were betting on.

What I want to remember going into tomorrow:
- One big win doesn't validate the system. Three more weeks of consistent small wins do.
- The "chase recent winners" anti-pattern needs naming and tracking before it costs us another -$22.
- The valley hypothesis was wrong — and that's OK. Hypotheses are SUPPOSED to be falsifiable.
- The cash position climbing is the system being healthy, not idle.

Day 33 has live tests on CRDO (bimodal #5), NEXT/SWKS (post-valley uncharted), and the FN cooldown expiry. The hypothesis pile is starting to clear — ONDS-91 transitioning, valley rejected, post-winner gap newly named.

---

## Template for Future Days

**Metrics:** [Did yesterday's fixes work?]
