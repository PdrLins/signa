# Phase 1 — Stabilization (Jun 15 → Jun 30, 2026)

**Status:** ACTIVE
**Started:** 2026-06-15 (Day 55)
**Decision point:** 2026-06-30 (review for $100 real-money deployment Jul 1)

## What Phase 1 is

A 2-week passive observation period. **No new rules ship.** The
caps and cooldowns from Days 47-55 need market data to validate.
The autonomous Daily Learning Loop reports every 17:30 ET; Pedro
reads, doesn't trade real money yet.

## Pass-bars (all must hold by Jun 30 for $100 deployment Jul 1)

| Metric | Current | Pass-bar | Source |
|---|---|---|---|
| Daily rate (rolling 7d) | -16.51/day | **≥0.20%/day (≈$10/day on $5K wallet)** | Daily report |
| MOMENTUM ≥85 force-sells | 0 since cap shipped Day 47 | **0 new** | Auto loop |
| NEUTRAL ≥85 force-sells | 0 since cap shipped Day 55 | **0 new** | Auto loop |
| WATCHDOG_CLUSTER (≥3 in 14d) | Currently active | **Resolves to 0-2** | Auto loop |
| 5-day cumulative drawdown | -$115 last 7d | **No new −5% week** | Daily report |
| Brain ships zero new rules | n/a | **0 rule changes** | Manual discipline |

## What invalidates Phase 1 (ping me immediately)

These trigger a check-in mid-window, not wait for Jun 30:

- A new WATCHDOG_FORCE_SELL fires on a **MOMENTUM** entry at tier-2 sizing.
  Day-47 cap predicted: 0 force-sells on capped MOMENTUM. A force-sell
  here means the cap didn't address the mechanism — re-examine.
- A new WATCHDOG_FORCE_SELL fires on a **NEUTRAL ≥85** entry at tier-2 sizing.
  Same logic for Day-55 cap.
- Wallet cumulative drops below **$200** ($297 → $200 = another -$97).
  Means the bleed continues despite the caps. Strategy is in question.
- The autonomous loop fails to fire for 2+ consecutive market days.
  Means the scheduler or the loop itself is broken.

## What Pedro does during Phase 1

1. **Read the daily Telegram digest** at 17:30 ET each market day.
2. **Skim the MD reports** at `docs/daily-reports/YYYY-MM-DD.md` for any CRITICAL findings.
3. **DO NOT trade based on brain signals with real money.** Paper only.
4. **DO NOT ship new rules to me asking to "fix" recent losses.** Variance is normal — let the data accumulate.
5. **Ping Claude only on:**
   - One of the invalidation triggers above
   - Jun 30 for the formal go/no-go decision
   - Genuine questions about a finding the loop surfaced

## What Claude does during Phase 1

1. **No new rule proposals.** The discipline `feedback_backtest_before_brain_changes`
   already requires backtest evidence; Phase 1 explicitly extends that
   to: even backtest-positive rules don't ship during the validation window.
2. **No "let me check the day" volunteering.** The autonomous loop is
   the day-checker now.
3. **Respond on invalidation triggers** with diagnosis + suggested action.
4. **Honor the Jun 30 review request.** Pull all 11 daily reports +
   the autonomous loop's hypothesis lifecycle and give an honest go/no-go.

## Decision matrix for Jun 30

| Pass-bars hit | Action Jul 1 |
|---|---|
| All 5 metric bars hit + 0 invalidations | **Deploy $100 real, start Phase 2** |
| 4 of 5 metric bars hit + 0 invalidations | **Deploy $50 real, extend Phase 2 to Aug 1** |
| Any invalidation trigger fired | **Hold paper, extend Phase 1 to Jul 15** |
| Strategy stays negative or rate <0.10%/day | **Hold paper, revisit strategy in Aug** |

## Next phases (preview)

- **Phase 2 (Jul 1-15):** $100 manual-mirror on Wealthsimple. Track real fills vs paper.
- **Phase 3 (Jul 15 - Aug 1):** Scale to $500 or $1K based on Phase 2 execution match.
- **Aug 1+:** If Phase 3 holds, sustained real-money operation. Revisit the 1%/day target with real data — or accept the realistic 0.3%/day reset.
