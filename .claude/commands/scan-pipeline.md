Show the Signa scan pipeline, scoring system, GEM detection, and signal blockers.

## Scan Schedule (Eastern Time, Mon-Fri)
| Time | Type | Purpose |
|------|------|---------|
| 6:00 AM | PRE_MARKET | Pre-market scan, overnight signal confirmation |
| 10:00 AM | MORNING | Morning confirmation (best entry window) |
| 3:00 PM | PRE_CLOSE | Pre-close check (second best entry) |
| 4:30 PM | AFTER_CLOSE | Full scan, next-day watchlist |
| 2:00 AM | CLEANUP | Purge expired tokens, OTPs, brain sessions, caches |

Trigger endpoint has a concurrency guard — rejects if a scan is already RUNNING/QUEUED (409 Conflict). Weekend triggers blocked (400).

## Two-Pass Pipeline (scan_service.run_scan)
1. Load ~141 tickers from universe.py
2. Bulk screen via yfinance (5d data, batches of 50)
3. Pre-filter to ~50 candidates: volume >= 200K, |change| > 1%, price > $1, 5 crypto slots reserved
4. Macro snapshot once: FRED (fed funds, 10Y, CPI, unemployment) + VIX
5. Market regime once: TRENDING/VOLATILE/CRISIS from VIX + SPY vs SMA200
6. Load brain knowledge block once (10 key concepts)

**Pass 1 — FREE (all ~50 candidates):**
- Fetch price history + fundamentals in parallel (semaphore=10)
- Compute technical indicators (CPU only)
- Quick score: technicals + fundamentals + macro only, no AI
- Sort by pre-score descending

**Pass 2 — PAID (top 15 by pre-score, budget-checked):**
- Balanced: at least 5 HIGH_RISK slots (sentiment matters most there)
- Safe Income tickers skip sentiment (only 10% weight — not worth the cost)
- For each: sentiment (Grok/Gemini) + synthesis (Claude/Gemini) in parallel
- Full scoring with all weights
- Contrarian detection, blocker checks, GEM detection, status tracking
- Kelly position sizing for BUY signals

**Bottom ~35 — stored with tech-only scores and generic reasoning**

7. Batch insert all signals
8. GEM alerts → Watchlist sell alerts → Scan digest (PRE_MARKET + AFTER_CLOSE only)
9. Position monitor: stop-loss, target, P&L milestones, signal weakening

## Phase 7 — Virtual Portfolio + Learning Loop (after signals are inserted)

Order matters in this phase. The new learning-loop logic (Stage 6) inserts a thesis re-evaluation step BETWEEN the new-entry/SIGNAL-exit pass and the price-based exit sweep.

```
process_pending_reviews(signals)        # pre-market reviews flagged earlier
   ↓
process_virtual_trades(signals, ...)    # SIGNAL/AVOID closes + new entries
                                         # (each entry captures entry_thesis +
                                         #  entry_thesis_keywords for Stage 6)
   ↓
thesis_tracker.reevaluate_open_theses()  # re-asks Claude per OPEN brain position
                                         # parallel via asyncio.gather, semaphore=3
                                         # writes thesis_last_status on each row
   ↓
thesis_tracker.execute_thesis_invalidation_exits()
                                         # closes positions where status=invalid
                                         # AND confidence>=60 (THESIS_INVALIDATED)
   ↓
check_virtual_exits()                    # STOP/TARGET/PROFIT/EXPIRED — each exit
                                         # gated by _exit_is_thesis_protected
                                         # (catastrophic stop -8% bypasses gate)
   ↓
flush_brain_notifications()              # drain Telegram queue
```

**Key invariant:** every brain trade close (regardless of path) flows through `_record_brain_outcome` which:
1. Writes a row to `trade_outcomes` for the existing weekly Claude analysis + Stage 4 pattern stats
2. Calls `_match_thinking_observations` to bump evidence counters on any active hypothesis whose `pattern_match` matches the closed trade
3. Logs `thinking_observation_added` events to `knowledge_events`

## Per-ticker prompt construction (Phase 4 — AI synthesis)

Every AI synthesis call now includes 4 evidence layers fed into the prompt:

```
## Investment Knowledge (from Signa Brain)
{validated patterns from signal_knowledge — proven, high confidence}

## Working Hypotheses (under observation — low confidence)
{active hypotheses from signal_thinking — explicit low-conf framing}

## Pattern Stats — Your Live Track Record on This Setup
{closed history + currently-open positions, combined per (bucket, regime)
 surfaces ⚠ warning if N>=5 + WR<40%, ✓ green light if WR>65%}

## Warning Signs (from technical/fundamental analysis)
{signal_breakdown rules filtered to TONE_NEGATIVE, formatted as plain English}
{placed JUST BEFORE "Your Task" — LLM recency bias}

## Your Task
{Claude's decision question}
```

The 3 AI clients (`claude_local_client`, `claude_client`, `gemini_client`) all build the same prompt via `format_warning_signs(signal_for_warnings)`. The knowledge block is loaded once per scan and per-ticker pattern stats are appended.

## Brain trust gate (unchanged from Stage 0)

`_eval_brain_trust_tier` is still in `app/services/virtual_portfolio.py` and still gates entries:

| Tier | AI status | Min score | Position size |
|------|-----------|-----------|---------------|
| Tier 1 | validated | 72 | 1.0× (full Kelly) |
| Tier 2 | low_confidence | 80 | 0.5× (half) |
| Tier 3 | skipped (tech-only) | 82 + tech confirm | 0.5× (half) |

This gate is NOT replaced by the learning loop — the learning loop layers ABOVE it. The brain still requires a tier match to BUY; the learning loop just makes Claude's decision better-informed and adds the THESIS_INVALIDATED exit type.

For deeper detail on the brain learning system: see `/brain-learning`.

## Scoring Weights (app/ai/signal_engine.py)

**Safe Income:**
| Component | Weight |
|-----------|--------|
| Dividend reliability | 35% |
| Fundamental health | 30% |
| Macro environment | 25% |
| Sentiment (Grok) | 10% |

**High Risk:**
| Component | Weight |
|-----------|--------|
| X/Twitter sentiment (Grok) | 35% |
| Catalyst detection (Claude) | 30% |
| Technical momentum | 25% |
| Fundamentals | 10% |

Dynamic sentiment weight: if mention_count < 100, sentiment weight drops to 5%, excess redistributed to macro (SAFE) or technical (RISK).

Contrarian adjustment: extreme sentiment (100+ mentions, score >85 or <15) gets +-10 contrarian dampening.

## Thresholds
| | SAFE_INCOME | HIGH_RISK |
|---|---|---|
| BUY | >= 62 | >= 65 |
| Contrarian BUY | >= 55 (+ contrarian_score >= 60) | >= 55 |
| Score Ceiling | 90 (forced HOLD) | 90 |
| HOLD | >= 55 | >= 55 |
| AVOID | < 55 | < 55 |

All configurable via `SCORE_BUY_SAFE`, `SCORE_BUY_RISK`, `SCORE_HOLD` env vars or Settings API.

## Market Regimes
| Regime | VIX | Effect |
|--------|-----|--------|
| TRENDING | < 20 | Normal operation |
| VOLATILE | 20-30 | HIGH_RISK scores reduced 15%, Kelly halved |
| CRISIS | > 30 | HIGH_RISK paused (score=0), SAFE_INCOME non-dividend reduced 40% |

## GEM Alert (all 5 must be true)
1. Score >= 85
2. Catalyst within 30 days (from Claude synthesis)
3. Grok sentiment = bullish AND confidence >= 80
4. No red flags from Claude
5. Risk/reward >= 3.0x

## Signal Blockers (auto-AVOID regardless of score)
1. Fraud/legal keywords in sentiment ("fraud", "sec investigation", "lawsuit", etc.)
2. Breaking news with fraud keywords
3. Hostile macro (VIX > 30, high fed funds, high unemployment)
4. Suspiciously low volume (Z-score < -2.0 or avg < 50K)
5. RSI > 75 overbought (backtest-validated: 60%+ fail rate)

## Contrarian Detection (app/signals/contrarian.py)
4 conditions, need 3/4:
1. Below SMA200 by >5% (out of favor)
2. RSI < 45 (oversold)
3. Volume ratio > 1.0 (accumulation)
4. MACD histogram positive (momentum shifting)

Contrarian signals use lower BUY threshold (55 vs 62/65).

## Signal Status (vs previous signal for same ticker)
- CONFIRMED — stable
- WEAKENING — score dropped 15+ points
- CANCELLED — was BUY, now SELL/AVOID
- UPGRADED — score up 10+ points, or HOLD → BUY

## Key Files
- `app/services/scan_service.py` — orchestrator + bucket classification
- `app/ai/signal_engine.py` — scoring + GEM + blockers + status
- `app/ai/provider.py` — AI provider fallback router (budget-checked)
- `app/signals/regime.py` — market regime from VIX
- `app/signals/kelly.py` — position sizing
- `app/signals/contrarian.py` — deep-value detection
- `app/scanners/` — data ingestion (yfinance, FRED, pandas-ta)
