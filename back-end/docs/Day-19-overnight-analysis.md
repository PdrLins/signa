# Day-19 Overnight Backtest Analysis

**Run:** Apr 29, 2026 evening → Apr 30 morning
**Data:** 52 closed brain virtual_trades (full lifetime to date)
**Baseline P&L:** −17.6% total, 40.4% win rate (21W / 31L), avg −0.34%/trade
**Constraint:** Information-only. No code, config, or DB writes shipped overnight. Everything in this doc is a recommendation awaiting your morning approval.

---

## TL;DR — the three things that matter

1. **The Day-19 raise of `BRAIN_MIN_SCORE` from 75 → 80 may be wrong.** Full-history numbers show score 75-79 has a **42.1% win rate** (8W / 11L, n=19). It's not a death zone — it's slightly below par. Raising to 80 cuts trade count by 53% (36 → 17) for a marginal win-rate gain. Score 80 alone is +1.7% historically, but n=17 is small-sample territory.

2. **The single most reliable filter we can derive from history is:**
   > **Score ≥ 75 + SHORT horizon + exclude Financial Services / Industrials sectors**

   Historical: **+5.4% total** (vs baseline −17.6% → **+23.1pp improvement**), 47.8% win rate, n=23. Two structurally distinct filter recipes (D and G in the backtest) collapse to this same trade subset.

3. **The LONG horizon has been a structural drag.** All 15 LONG-horizon trades in history are SAFE_INCOME bucket (zero HIGH_RISK × LONG ever existed) and the cohort is 33.3% win rate, **−14.9% total**. Every LONG trade in the brain's lifetime has been a SAFE_INCOME pick. **Killing the LONG horizon entirely produces nearly identical results to "drop SAFE_INCOME × LONG"** because they're the same set of trades.

---

## Section 1 — Single-rule filters ranked

| Filter | n | W/L | Win rate | Total P&L | Δ vs baseline |
|---|---|---|---|---|---|
| Drop Financial Services + Industrials | 43 | 20/23 | 46.5% | **+0.2%** | +17.8pp |
| Score ≥ 80 (current rule) | 17 | 7/10 | 41.2% | **+1.7%** | +19.3pp |
| Drop SAFE_INCOME × LONG | 37 | 16/21 | 43.2% | −2.7% | +14.9pp |
| SHORT horizon only | 37 | 16/21 | 43.2% | −2.7% | +14.9pp |
| Score ≥ 85 | 2 | 1/1 | 50.0% | −5.3% | +12.3pp ⚠ n=2 |
| Sentiment ≥ 70 | 4 | 3/1 | 75.0% | −4.8% | +12.8pp ⚠ n=4 |
| Sentiment ≥ 60 | 7 | 4/3 | 57.1% | −6.8% | +10.8pp |
| R/R ≥ 2.0 | 6 | 2/4 | 33.3% | −3.9% | ⚠ n=6 |
| Score ≥ 75 (current Tier 1) | 36 | 15/21 | 41.7% | −8.0% | +9.6pp |
| LONG horizon only | 15 | 5/10 | 33.3% | **−14.9%** | the drag |
| R/R ≥ 1.5 | 23 | 9/14 | 39.1% | −13.9% | weak |
| ai_status = validated | 47 | 19/28 | 40.4% | −17.9% | ≈ baseline |

**Reading the table:**
- **"Drop SAFE_INCOME × LONG" and "SHORT horizon only" produce the identical 37-trade set.** This means every LONG-horizon trade in history is in the SAFE_INCOME bucket — there has never been a HIGH_RISK × LONG entry. The two filters are operationally equivalent.
- **"ai_status = validated"** is meaningless as a filter — 47 of 52 trades already had it, so it changes almost nothing.
- **"Drop Fin + Industrials"** alone is shockingly strong: it removes 9 trades and the net P&L moves +17.8pp. Those two sectors carry an outsized share of the loss.
- **Sentiment ≥ 60 and R/R ≥ 1.5** look weak when used alone, but only because they correlate with our worst-bucket trades — they re-strengthen in combination (see Section 2).

---

## Section 2 — Combined filters (candidate strategies)

Sorted by historical total P&L:

| Rank | Filter | n | Win rate | Total P&L | Δ vs baseline |
|---|---|---|---|---|---|
| 🥇 | **D. Score ≥ 75 + SHORT + drop Fin/Industrials** | 23 | **47.8%** | **+5.4%** | **+23.1pp** |
| 🥇 | G. Score ≥ 75 + drop SAFE_INCOME×LONG + drop Fin/Industrials | 23 | 47.8% | +5.4% | +23.1pp (same set) |
| 🥈 | J. Kitchen sink: 75+ AND SHORT AND not Fin/Industrials AND validated | 18 | 50.0% | +5.2% | +22.8pp |
| 🥉 | E. Score ≥ 80 + SHORT only | 13 | 46.2% | +4.3% | +21.9pp |
| 🥉 | I. Score ≥ 80 + drop SAFE_INCOME×LONG | 13 | 46.2% | +4.3% | +21.9pp (same set) |
| 5 | A. Score ≥ 75 + drop SAFE_INCOME×LONG | 25 | 44.0% | +3.1% | +20.7pp |
| 5 | B. Score ≥ 75 + SHORT horizon only | 25 | 44.0% | +3.1% | +20.7pp (same set) |
| 7 | C. Score ≥ 75 + drop Fin/Industrials | 32 | 43.8% | −3.1% | +14.5pp |
| 8 | H. Score ≥ 75 + R/R ≥ 1.5 | 19 | 47.4% | −5.6% | +12.0pp |
| 9 | F. Score ≥ 75 + sentiment ≥ 60 | 6 | 50.0% | −9.0% | +8.6pp ⚠ n=6 |

**Key observations:**

- **D and G are tied at the top with identical 23-trade subsets.** Once "SHORT horizon" is applied, "drop SAFE_INCOME × LONG" is redundant (same 37-trade base, score≥75 reduces both to 23). The simpler rule wins: **Score ≥ 75 + SHORT + drop Fin/Industrials**.
- **J adds `ai_status = validated` on top of D and gains +0.6pp average per trade but loses 5 trades.** Marginal benefit; stricter is mostly noise here.
- **E (Score ≥ 80 + SHORT) is what the Day-19 raise effectively produces today** when combined with the existing horizon mix. n=13 historical — too small to declare victory, but the avg/trade (+0.33%) is the best of any group.
- **The current Day-19 rule is essentially filter E.** Backtest says it's #4. The free upgrade is to either (a) drop the score floor back to 75 and add the sector exclusion, or (b) keep 80 and add the sector exclusion. (b) likely halves trade count further but we can't measure (would have n=8 or so).

---

## Section 3 — Why the Day-19 raise to 80 deserves a second look

Yesterday's diagnosis was **based on 4 wallet-era trades** at score 75-79, which all closed losses in 2 days, suggesting "raise the floor."

Full history says different:

- **Score 75-79 over all 52 trades:** 19 trades, 42.1% win rate (8W / 11L), total ≈ −9.7%, avg −0.51%/trade.
- **Score 80+ over all 52 trades:** 17 trades, 41.2% win rate (7W / 10L), total +1.7%, avg +0.10%/trade.

The raise from 75 to 80 isolates a *slightly* better cohort (+0.6pp avg per trade) at the cost of cutting trade volume in half. Across 19 entries, that's the difference between −$2.50 and +$0.50 per typical $500 position — real but modest.

**Compare against the sector filter:**
- "Drop Fin + Industrials" alone: 43 trades survive (vs 36 at score ≥ 75), 46.5% win rate, +0.2% total — better win rate AND more trades than the score raise.
- "Score ≥ 75 + Drop Fin + Industrials" (filter C): 32 trades, 43.8%, −3.1%. Decent.
- "Score ≥ 75 + SHORT + Drop Fin + Industrials" (filter D): 23 trades, 47.8%, +5.4%. **The winner.**

**Hypothesis:** the Day-19 raise was the right *direction* (filter quality) but the wrong *axis* (score). The data points to **horizon + sector**, not score, as the primary discriminators.

---

## Section 4 — The LONG-horizon problem in detail

15 closed LONG trades. All 15 are SAFE_INCOME bucket. Win rate 33.3%. Total **−14.9%**.

There has never been a HIGH_RISK × LONG trade — the brain has never picked a high-volatility name with a multi-week horizon. Either by design or by selection bias, LONG-horizon = SAFE_INCOME = drag.

**Decision options for the LONG horizon (in order of conservatism):**

1. **Suspend it entirely.** Treat as a kill-switch on `trade_horizon == "LONG"`. Loses optionality if SAFE_INCOME ever recovers. Easy revert.
2. **Raise the LONG entry score to 85.** The 2 trades at score ≥ 85 came in at 50% win rate (n=2 noise). Filters but doesn't remove the bucket.
3. **Restrict LONG to specific buckets.** If we ever pick a HIGH_RISK × LONG (none yet), let it through; SAFE_INCOME × LONG always blocked.
4. **Do nothing** and rely on the sector filter (Fin + Industrials are common SAFE_INCOME members) to indirectly drain the SAFE_INCOME × LONG pipe.

Recommended: **option 1**. The data is unambiguous and the cost of being wrong is very low (we re-enable if we ever see SAFE_INCOME positions winning).

---

## Section 5 — Sector breakdown context

From the underlying data, "Drop Financial Services + Industrials" removes 9 trades that as a group were heavily loss-skewed. The exact distribution wasn't stamped on every trade in the dataset, but the aggregate effect is:

- Removing the 9 = +17.8pp improvement to total P&L.
- That's ~+2pp per trade removed → these 9 averaged roughly −2% per trade.
- For comparison, the surviving 43 trades averaged near 0% per trade (+0.2% total / 43).

In other words: Fin + Industrials trades were structurally negative-EV in our sample. Excluding them is the highest-leverage single-axis filter we have.

---

## Section 6 — Sentiment and R/R: weak as standalone, but worth re-testing in combos

Both sentiment and R/R look weak as single filters, but the small samples are masking. Sentiment ≥ 70 had **75% win rate (3W / 1L, n=4)** — promising signal but unreliable below n=10. The same applies to R/R ≥ 2.0 at n=6.

**These are filters to revisit with more data, not filters to apply now.** Treat as "watch the next 10-20 trades and re-run the backtest."

---

## Section 7 — GEM gate audit — separate confirmation

`scripts/audit_gem_gates.py` re-run summary (last 7 days, 80+ score signals):

| Gate | Failure rate |
|---|---|
| **sentiment ≥ 80** | **100%** — top observed sentiment is 60–70 |
| R/R ≥ 3.0 | 98.8% — actual R/R distribution is 1.4–2.2 |
| score ≥ 85 | 89.4% |
| ai_status = validated | varies, most pass |
| target + stop filled | most pass |

**Conclusion: the GEM badge is structurally unreachable with the current Grok output range.** This is the same finding from Day 19 EOD; nothing changed overnight. **Action is unchanged: don't relax sentiment to 70 just to manufacture GEMs** — Filter F (Score ≥ 75 + sentiment ≥ 60) was 50% win rate on n=6 but still −9.0% total. The volatile names with high sentiment have been our worst trades.

If you want GEM to do something meaningful, give the badge functional consequence (e.g., 1.5x position size when triggered) AND recalibrate the threshold based on the realized distribution. Otherwise leave the badge cosmetic.

---

## Section 8 — Top 5 recommended changes (ranked, ready for morning approval)

Each is presented with: the change, the historical evidence, the risk, and the easy revert.

### #1 — Add sector exclusion: drop Financial Services + Industrials from brain entries

- **What:** In `process_virtual_trades` and the SHORT entry path, reject any signal whose `fundamental_data.sector` is in `{"Financial Services", "Industrials"}`.
- **Why (data):** "Drop Fin + Industrials" alone was the highest-leverage single filter — +17.8pp vs baseline, 46.5% win rate, n=43 (large sample). Combined with horizon + score it produces our best historical result (+5.4%).
- **Risk:** sector classification depends on Yahoo's `fundamental_data.sector` which can be missing or stale; need a fallback (skip vs admit). Recommend "admit if missing" so we don't accidentally block Tech entries.
- **Revert:** delete two lines from `_filter_eq` / equivalent gate.

### #2 — Revisit BRAIN_MIN_SCORE = 80; consider rolling back to 75 + adding sector + horizon filters

- **What:** Set `BRAIN_MIN_SCORE = 75` again, but add the sector exclusion (#1) AND a "no LONG horizon" gate (#3).
- **Why (data):** Filter D (Score ≥ 75 + SHORT + drop Fin/Industrials) produces +5.4% historically with 23 trades — better than the current 80-only rule's projected +1.7% with 17 trades. More trades, better outcome.
- **Risk:** the Day-19 small-sample observation (4 wallet-era 75-79 trades all losing) could be real and full-history could be lying. Mitigate by **keeping 80 for 2 more trading days** to gather wallet-era 80-only data, THEN flip to 75+filters.
- **Revert:** flip `BRAIN_MIN_SCORE` back to 80 in one line.

### #3 — Suspend the LONG-horizon entry path

- **What:** In `process_virtual_trades`, reject `signal.trade_horizon == "LONG"` for new entries. Existing LONG positions ride out their close paths normally.
- **Why (data):** All 15 closed LONG trades were SAFE_INCOME bucket. 33% win rate. −14.9% total. The single worst slice of the data.
- **Risk:** we exclude an entire category that *could* recover if we ever picked a HIGH_RISK × LONG (none yet exist). Optionality cost is real but small.
- **Revert:** one-line gate removal. Re-enable when we see 5+ winning SAFE_INCOME positions in a 30-day window.

### #4 — Promote Filter D as the explicit, named rule

- **What:** Wrap #1 + #2 + #3 into a single named guard, e.g. `BRAIN_FILTER_D = score >= 75 AND horizon == SHORT AND sector NOT IN {Fin, Industrials}`. Centralize so future analysis can A/B with one toggle.
- **Why:** code clarity. Today's gates are scattered across `process_virtual_trades`, helper functions, and tier_evaluator — re-rolling them later requires hunting them down.
- **Risk:** mild refactor risk, easy to introduce a regression. Mitigate with the 14-day backtest re-run after every gate change.
- **Revert:** keep individual gates from #1-3; #4 is purely organizational.

### #5 — Add a recurring backtest job + a "would-have-applied" badge in the UI

- **What:** Cron the backtest scripts (`backtest_filters.py`, `backtest_patterns.py`, `audit_gem_gates.py`) to run nightly and save a snapshot to `docs/backtest-snapshots/YYYY-MM-DD.md`. Optionally surface in the brain performance page.
- **Why:** today these scripts are run on-demand. Once-nightly auto-runs let us catch when our best filter degrades or a new cohort emerges. Pure information layer; no behavior change.
- **Risk:** zero behavioral, but adds a recurring job to maintain. Can stub as a manual script for the first 2 weeks.
- **Revert:** delete the cron entry.

---

## Section 9 — What I did NOT recommend (and why)

- **Drop sentiment threshold to 70 to unlock GEMs.** Filter F (Score ≥ 75 + sentiment ≥ 60) was −9.0% historical. Lowering sentiment manufactures more entries on volatile names that have lost us money.
- **Lower WATCHDOG_FORCE_SELL from −8% to −6%.** Day-19 lesson: ARM and CAMT recovered post-grace from negative territory. A tighter watchdog would have killed them. The "valley of death" between QUALITY_PRUNE and watchdog deserves attention but not via threshold tightening — the right fix is probably to lower QUALITY_PRUNE's day floor from 2 to 1 *only when* thesis = invalid and Claude ≠ BUY.
- **Raise BRAIN_MIN_SCORE further (85+).** n=2. Pure noise. We'd be making policy from coin flips.
- **Re-enable any filter combination at n < 10.** Sentiment ≥ 70 looked great (75%) but n=4. Until we have 10+ samples, treat as a hypothesis, not a rule.

---

## Section 10 — Sequencing recommendation for the morning

1. **Read this doc.**
2. **Decide on Filter D.** (Yes / no / "let me think.") The single highest-impact decision.
3. **If yes,** ship #1 (sector exclusion) and #3 (suspend LONG) first. They're low-risk and the evidence is the cleanest.
4. **Defer #2 (BRAIN_MIN_SCORE rollback) for 2 more trading days** of wallet-era 80-only data. That's the noisier call and the wait costs little.
5. **Defer #4 and #5** to a later cleanup pass. They don't move P&L; they make future iteration faster.

---

## Appendix — How to re-run

```bash
cd back-end && source venv/bin/activate
python -m scripts.backtest_patterns       # cohort slicing
python -m scripts.backtest_filters        # filter recipes
python -m scripts.audit_gem_gates --days 14  # GEM gate audit
```

All three are read-only against Supabase — no DB writes, no config changes, no scan triggers.
