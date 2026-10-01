"""Application settings loaded from environment variables."""

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


MIN_SECRET_LENGTH = 32

# Placeholder / example values that must never be accepted as real secrets.
_PLACEHOLDER_SECRETS = {
    "",
    "change-me-in-production",
    "generate-with-openssl-rand-hex-32",
    "changeme",
    "change-me",
    "secret",
    "your-secret-key",
}


def _check_secret(name: str, value: str) -> None:
    """Reject empty, placeholder, or short signing secrets."""
    v = (value or "").strip()
    lowered = v.lower()
    if (
        lowered in _PLACEHOLDER_SECRETS
        or "generate-with" in lowered
        or "change-me" in lowered
        or len(set(v)) < 8  # e.g. "aaaa...": trivially guessable
    ):
        raise ValueError(
            f"{name} is unset or a placeholder. "
            "Generate one with: openssl rand -hex 32"
        )
    if len(v) < MIN_SECRET_LENGTH:
        raise ValueError(
            f"{name} must be at least {MIN_SECRET_LENGTH} characters. "
            "Generate one with: openssl rand -hex 32"
        )


class Settings(BaseSettings):
    """All configuration for Signa backend."""

    # --- API Keys ---
    anthropic_api_key: str = ""
    xai_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    supabase_url: str = ""
    supabase_key: str = ""
    fred_api_key: str = ""

    # --- Auth ---
    # Auth is always enforced (AuthMiddleware). There is no AUTH_ENABLED switch.
    jwt_secret_key: str  # No default — forces env var
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60  # 1 hour (refresh for longer sessions)
    jwt_refresh_grace_hours: int = 4   # an expired token can be refreshed for this long
    jwt_max_session_hours: int = 24    # absolute cap since OTP login, across refreshes
    # Sessions (migration 017): one per signed-in device. iOS gets a short
    # access token plus a rotating refresh token; the web keeps the access-
    # token refresh above (its session ends with jwt_max_session_hours).
    ios_access_token_minutes: int = 15
    session_refresh_days: int = 90         # sliding: extended on each refresh
    session_absolute_days: int = 180       # hard cap since sign-in
    session_owner_days: int = 30           # owner sessions: sliding AND absolute cap
    session_check_cache_seconds: int = 60  # how long "session still active" is cached
    # macOS: block idle sleep while the back-end runs (app/core/keep_awake.py),
    # so scheduled scans and the watchdog run on time.
    keep_awake: bool = True
    # Email sign-in (migration 018). Accounts without Telegram confirm each
    # password sign-in with a code sent by email. Public sign-up stays OFF
    # until the app is hosted (SIGNUP_ENABLED=true).
    signup_enabled: bool = False
    email_code_expire_seconds: int = 600
    email_provider: str = "console"   # console (logs, dev) | resend | smtp
    email_from: str = "Signa <no-reply@localhost>"
    resend_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    otp_expire_seconds: int = 30  # 30 seconds
    session_token_expire_seconds: int = 180

    # --- Telegram Webhook ---
    telegram_webhook_secret: str = ""  # Set via setWebhook secret_token param
    # Bot @username without the @ (for t.me/<bot>?start=<code> links when a
    # user connects Telegram). Optional: when empty it's read once via getMe.
    telegram_bot_username: str = ""

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:3000"]

    # --- Referrals (migration 019) ---
    # Public URL of the web app; GET /referrals then returns
    # share_url = f"{WEB_APP_URL}/signup?code=<account id>". Optional (null when empty).
    web_app_url: str = ""

    # --- Login second factor ---
    # True = password + Telegram code. False = password only; acceptable only
    # while the app listens on 127.0.0.1 (the default in start.sh / F5).
    login_otp_enabled: bool = True
    # Brain Editor unlock code via Telegram. When False — or when Telegram is
    # not configured (empty/placeholder bot token) — no message is sent and
    # brain_otp_fallback_code unlocks instead. Local, trusted use only.
    brain_otp_enabled: bool = True
    brain_otp_fallback_code: str = "123456"

    # --- Rate Limiting ---
    max_login_attempts_per_ip: int = 5
    max_otp_attempts_per_session: int = 3
    rate_limit_window_minutes: int = 15

    # --- Trusted Proxies ---
    trusted_proxies: list[str] = ["127.0.0.1", "::1"]

    # --- Claude ---
    # True  = local machine: Claude only via the `claude` CLI (subscription);
    #         the Anthropic API is never called, even with ANTHROPIC_API_KEY set.
    # False = Claude only via the paid Anthropic API (budget-capped).
    claude_local: bool = True
    # Two tiers (API and local CLI alike):
    #   routine  — every candidate synthesis + daily thesis re-evaluation
    #   decision — confirms a routine BUY before it can become "validated"
    claude_model: str = "claude-sonnet-5-5"
    claude_effort: str = "medium"  # low | medium | high | xhigh | max
    claude_decision_model: str = "claude-opus-5-5"
    claude_decision_effort: str = "high"
    ai_decision_escalation: bool = True  # False = routine model's BUY is final
    # Both models always think; thinking tokens count against max_tokens.
    claude_max_tokens: int = 16000
    claude_local_timeout_s: int = 180

    # --- Grok (xAI Responses API with live x_search + web_search) ---
    grok_base_url: str = "https://api.x.ai/v1"
    grok_model: str = "grok-4.7"
    grok_search_window_hours: int = 48
    # Latency: each server-side search turn costs ~10-20s (observed ~57s
    # per call at 4 turns). 3 turns (one X + one web search + a follow-up)
    # is enough for a 48h window; a timed-out request is not retried
    # (sentiment is then marked unavailable). Results are cached 24h per ticker.
    # Cost: xAI bills ~$5 per 1K X posts fetched plus the search results as
    # prompt tokens; on 2026-09-29 that was ~$0.25 per call at 3 turns. 2 turns
    # (one X + one web search) caps the fetch.
    grok_max_turns: int = 2  # cap on server-side search tool turns per request
    grok_timeout_s: int = 75

    # --- Codex (OpenAI) — independent second opinion on decision-model BUYs ---
    # Runs only after the decision model (Opus) confirmed a BUY. CODEX_LOCAL:
    # True = the local `codex` CLI (ChatGPT login, `codex login`), read-only
    # sandbox in an empty temp dir; False = the OpenAI API (OPENAI_API_KEY,
    # budget-capped). The API path REQUIRES CODEX_MODEL; empty on the CLI
    # path = the CLI's own default model.
    codex_enabled: bool = True
    codex_local: bool = True
    openai_api_key: str = ""
    codex_model: str = ""
    # record = store the verdict only (default); veto = a confident Codex
    # AVOID/SELL (>= codex_veto_min_confidence) downgrades the BUY to HOLD;
    # off = never run. Codex unavailable / erroring never blocks a BUY.
    codex_decision_mode: str = "record"
    codex_veto_min_confidence: int = 60
    codex_timeout_s: int = 120

    # --- AI Provider Preferences ---
    # Ordered list of providers to try for each task. First available wins.
    # Gemini was removed (2026-09); a leftover "gemini" in an old .env is
    # dropped by the validator below.
    synthesis_providers: list[str] = ["claude"]
    sentiment_providers: list[str] = ["grok"]

    # --- Scoring Thresholds ---
    score_buy: int = 65           # Default BUY threshold (configurable in Settings)
    score_buy_safe: int = 62      # Safe Income BUY threshold
    score_buy_risk: int = 65      # High Risk BUY threshold
    score_hold: int = 55          # HOLD threshold (below = AVOID)
    gem_min_score: int = 85
    gem_catalyst_days: int = 30
    gem_min_rr_ratio: float = 3.0

    # --- Scoring Weights ---
    safe_income_weights: dict = {
        "dividend_reliability": 0.35,
        "fundamental_health": 0.30,
        "macro": 0.25,
        "sentiment": 0.10,
    }
    high_risk_weights: dict = {
        "sentiment": 0.35,
        "catalyst": 0.30,
        "technical_momentum": 0.25,
        "fundamentals": 0.10,
    }

    # ETF scoring uses lower dividend weight since many great ETFs don't pay dividends
    etf_weights: dict = {
        "fundamental_health": 0.40,
        "macro": 0.30,
        "dividend_reliability": 0.15,
        "sentiment": 0.15,
    }

    # --- Pre-filter ---
    min_volume: int = 200_000
    min_abs_change: float = 0.01
    max_candidates: int = 50
    discovery_min_market_cap: int = 5_000_000_000  # $5B minimum for discovered tickers
    # Yahoo "most_actives" screener adds whatever traded heavily today —
    # a move-chasing source. Off by default; day_gainers was removed.
    discovery_include_most_actives: bool = False

    # --- Two-Pass Scanning ---
    ai_candidate_limit: int = 15  # Top N candidates get AI analysis
    ai_enabled: bool = True       # False = tech-only mode (zero AI cost)

    # --- Decision quality gates (scan pipeline) ---
    # ai_status="validated" requires Claude's synthesis signal == BUY AND
    # confidence >= this value.
    ai_validated_min_confidence: int = 60
    # MACD histogram is scored in ATR units (hist / ATR14) so the
    # threshold is price-invariant. "Strong" bullish above this.
    macd_hist_strong_atr: float = 0.25
    # No new BUY when the next earnings report is within N trading days.
    earnings_blackout_trading_days: int = 3
    # Richer equity data (scanners/enrichment.py): estimate revisions,
    # relative strength vs sector ETF / SPY, short-interest trend, insider
    # buying. fetch=False skips the extra yfinance requests entirely;
    # scoring=False keeps the data (prompt context) but zeroes the
    # UNVALIDATED score contributions so backtests can A/B them.
    enrichment_fetch_enabled: bool = True
    enrichment_scoring_enabled: bool = True
    enrichment_cache_hours: int = 12

    # --- Scheduler ---
    timezone: str = "America/New_York"

    # --- Concurrency ---
    max_concurrent_api_calls: int = 10

    # --- Position Monitoring ---
    position_monitor_enabled: bool = True
    position_alert_profit_pct: float = 5.0
    position_alert_loss_pct: float = -5.0

    # --- Virtual Portfolio ---
    virtual_trade_max_days: int = 30  # Auto-close virtual trades after N days
    # p_win = P(price higher N trading days after entry). Matches the 5-20 day
    # holding period; also the horizon p_win calibration is graded at.
    ai_pwin_horizon_days: int = 20
    brain_max_open: int = 20          # Max simultaneous brain positions

    # --- Wallet ---
    # Brain virtual portfolio is wallet-based (base currency USD). Every
    # brain trade debits cash on entry and credits proceeds on exit.
    wallet_enabled: bool = True
    wallet_starting_balance: float = 10000.0     # starting capital (reset_brain.py re-seeds with this)
    wallet_min_balance_for_trade: float = 100.0  # smallest allocation worth opening (USD)

    # --- Brain decision policy (2026-09 decision-quality reset) ---
    # Entry: only an AI BUY (ai_status == "validated" AND ai_signal == "BUY")
    # may auto-buy. Tech-only / low_confidence / failed signals never do.
    brain_require_ai_buy: bool = True
    brain_min_rr: float = 2.0                   # reward:risk computed in code from final levels
    # Technical gate for an AI BUY. "filter" (default): the pass/fail
    # `signal_engine.technical_filter` (trend, not overextended, liquid, no
    # blocker); entries are ordered by AI p_win, then AI confidence.
    # "score" (legacy): score >= BRAIN_MIN_SCORE, ordered by score. The
    # 2021-2026 signal study (8,996 trades) found a higher compute_score did
    # NOT predict better returns, so score no longer gates or ranks entries.
    brain_entry_mode: str = "filter"
    tech_filter_max_rsi: float = 75.0                  # RSI(14) must be <= this
    tech_filter_max_ext_sma50_pct: float = 15.0        # price at most this % above SMA50
    tech_filter_min_dollar_volume: float = 10_000_000  # 20d avg $ volume, stocks/ETFs (native ccy)
    tech_filter_min_dollar_volume_crypto: float = 50_000_000  # 20d avg $ volume, crypto (USD)
    # Risk-based sizing: size so (entry - stop) * shares = risk_pct of equity,
    # then cap the position at max_position_pct of equity.
    brain_risk_per_trade_pct: float = 1.0
    brain_max_position_pct: float = 10.0
    brain_max_open_positions: int = 8           # all brain positions (long + short)
    brain_max_per_sector: int = 2
    brain_max_crypto_pct: float = 25.0          # max % of equity (cost basis) in crypto
    # Correlation gate (services/portfolio_risk.py), LONG entries only, after
    # the limits above. Block when the candidate's daily-return correlation to
    # ANY open position >= corr_max_pairwise, OR when >= corr_cluster_max open
    # positions correlate >= corr_cluster_threshold. Missing data -> no block.
    brain_correlation_check_enabled: bool = True
    brain_corr_lookback_days: int = 120         # trading days of daily returns
    brain_corr_min_obs: int = 40                # min overlapping returns per pair
    brain_corr_max_pairwise: float = 0.80
    brain_corr_cluster_threshold: float = 0.70
    brain_corr_cluster_max: int = 2
    brain_max_portfolio_beta: float = 0.0       # post-trade beta-to-SPY cap; 0 = off
    # Default levels when Claude's are absent: stop = entry - k*ATR,
    # target = entry + R_mult * (entry - stop).
    brain_stop_atr_mult: float = 2.0
    brain_target_r_mult: float = 2.0
    brain_min_stop_atr_mult: float = 1.0        # Claude stop tighter than this*ATR -> use ATR stop
    # Trailing stop: once price has moved +activate_r R in our favor, the
    # stop ratchets to (peak - trail_atr_mult * ATR). Never loosens.
    brain_trail_atr_mult: float = 2.5
    brain_trail_activate_r: float = 1.0
    brain_catastrophic_stop_pct: float = 15.0   # safety net only when a row has no stop_loss
    # Shorts add risk without measured evidence -> disabled by default.
    brain_short_entries_enabled: bool = False
    # Execution costs (applied on BOTH sides of every brain fill).
    brain_slippage_bps_stock: float = 10.0
    brain_slippage_bps_crypto: float = 20.0
    brain_commission_usd: float = 0.0           # per fill
    # Drawdown breaker: halt NEW entries when equity is this % below its peak.
    brain_max_drawdown_pct: float = 10.0
    # After the breaker trips, pause new entries for this many US trading
    # days, then reset the peak to current equity and resume. Without the
    # reset a flat-in-cash book can never climb back to the old peak and
    # the breaker latches forever (backtest: 1,734 blocked days after one trip).
    brain_drawdown_pause_trading_days: int = 10
    # Same-symbol re-entry cooldown after ANY exit, in trading days.
    brain_reentry_cooldown_days: int = 3
    # Time stop for brain positions (calendar days).
    brain_max_hold_days: int = 30
    # Legacy admission gates fit on tiny samples (n=1..17). All OFF after
    # the reset; flip on only with a documented n>=30 backtest.
    brain_filter_d_sectors_enabled: bool = False      # Fin/Industrials sector block (Day 20)
    brain_long_horizon_suspended: bool = False        # LONG-horizon entry suspension (Day 20)
    brain_portfolio_heat_enabled: bool = False        # heat score incl. VIX<16 floor (Day 8)
    brain_trend_downsize_enabled: bool = False        # below-SMA50 / BB>95% half-size (Week 1)
    brain_quality_prune_enabled: bool = False         # QUALITY_PRUNE exit (Day 17)
    brain_stagnation_prune_enabled: bool = False      # STAGNATION_PRUNE exit (Day 14)

    # Legacy sizing knobs — no longer read by the brain (risk-based sizing
    # above replaced them). Kept so old .env files still parse.
    wallet_position_pct_tier1: float = 10.0
    wallet_position_pct_tier2_3: float = 5.0
    wallet_max_position_pct: float = 10.0
    wallet_auto_revert_pnl_floor: float | None = None  # replaced by brain_max_drawdown_pct

    # --- Day-0 grace period ---
    # Hours after entry during which THESIS_INVALIDATED exits are ignored.
    # 0 after the reset: thesis_tracker now needs two consecutive
    # high-confidence "invalid" calls, which already filters noise.
    new_position_grace_hours: float = 0.0

    # --- Entry-rate caps (Day 19 / Day 21). 0 = disabled. ---
    # Superseded by max open positions + risk sizing + re-entry cooldown.
    wallet_max_entries_per_day: int = 0
    wallet_max_entries_per_symbol_per_day: int = 0

    # --- Brain Thesis Tracking (Stage 6) ---
    # When enabled, every scan re-evaluates the thesis on every open brain
    # position via Claude. Positions whose thesis is invalidated are closed
    # with exit_reason='THESIS_INVALIDATED', regardless of P&L direction.
    # Existing exit paths (STOP_HIT, TARGET_HIT, etc.) are GATED by the
    # thesis check — if the thesis is still 'valid', the exit is suppressed
    # as noise. EXCEPTION: catastrophic stops (pnl_pct <= -8%) ALWAYS fire,
    # bypassing the thesis gate, so a wrong thesis call can never blow us up.
    # Set to False to revert to pre-Stage-6 behavior (no thesis checks).
    brain_thesis_gate_enabled: bool = True   # runs thesis re-eval (thesis_tracker reads this)
    # 2026-09 reset: a 'valid' thesis may NOT suppress exits by default. Even
    # when enabled it can only hold a WINNING position past TARGET/TIME/SIGNAL;
    # STOP_HIT / TRAILING_STOP are always hard and losers are never held.
    brain_thesis_suppresses_exits: bool = False
    brain_thesis_hard_stop_pct: float = -8.0  # catastrophic stop carve-out
    # Re-buy cooldown after a THESIS_INVALIDATED exit. The brain otherwise
    # would re-open the same symbol on the next scan if Claude flips back
    # to BUY (Claude is non-deterministic on borderline trades). Real case
    # 2026-04-09: WING #1 invalidated in 17s, WING #2 opened 54min later
    # at +$2.95 from the close, currently bleeding. The Day 4 journal
    # explicitly named this fix. Set to 0 to disable.
    brain_thesis_rebuy_cooldown_minutes: int = 0  # 2026-09 reset: superseded by brain_reentry_cooldown_days

    # Day 26: post-WATCHDOG_EXIT cooldown. When the watchdog closes a
    # position via the bearish-sentiment + slight-loss path (WATCHDOG_EXIT),
    # the brain is blocked from re-entering that symbol for N hours.
    # Backtest evidence: 2 of 2 closed re-entries within 7 days of a
    # prior WATCHDOG_EXIT also lost (VZ Apr 14→16, FN Apr 28→May 5).
    # Both re-entries also exited via WATCHDOG_EXIT — same illness, same
    # outcome. The mechanism: WATCHDOG_EXIT signals the *name* is bleeding
    # in the current regime, not just that one entry was poorly timed.
    # Default 168h = 7 days = one full trading week, matching the watchdog
    # / STAGNATION_PRUNE timeframe. Set to 0 to disable.
    brain_watchdog_exit_cooldown_hours: int = 0  # 2026-09 reset: OFF (n=2); see brain_reentry_cooldown_days

    # Day 37: post-WINNER cooldown. After a wallet trade closes positive
    # via THESIS_INVALIDATED / TARGET_HIT / TRAILING_STOP / SIGNAL /
    # ROTATION, the brain is blocked from re-entering that symbol for N
    # hours.
    # Backtest evidence: 3 of 3 chase-winner re-entries lost -$67 total:
    #   - SOUN won +$68 Day 24 → SOUN-2 entered 4d later → lost -$22 Day 32
    #   - IONQ won +$64 Day 32 → IONQ-2 entered 1d later → lost -$41 Day 36
    #   - ARM  won +$11 Day 25 → ARM-2  entered 10d later → lost -$4 Day 36
    # Same name, recent winner, fresh entry weakens early, dies within
    # 3-5 days. Gap-from-winner ranged 1-10 days, so the cooldown needs
    # to be at least 14 days to catch all observed cases.
    # Default 336h = 14 days. Set to 0 to disable.
    brain_post_winner_cooldown_hours: int = 0  # 2026-09 reset: OFF (n=3)

    # Day 47 (Jun 4): post-LOSING-close cooldown. After a wallet trade closes
    # negative (any exit_reason), block re-entry of the same symbol for N
    # hours. Backtest motivation: OSCR closed -$5.79 TIME_EXPIRED with
    # weakening thesis (May 28 12:05) → brain re-entered the SAME symbol
    # 3 hours later → lost another -$11.82 (Jun 2 TRAILING_STOP). Across
    # all losing closes (n=26), only ONE re-entry has ever happened within
    # 48h (the OSCR case), and it lost. The next-fastest re-entry was 53+
    # hours later. So a 24h cooldown blocks the observed bad case without
    # touching any historical winner.
    # Mechanism: a losing close means the recent thesis didn't play out.
    # Within 24h the brain has not received enough fresh information to
    # justify reversing that judgment. Forcing a wait ensures any re-entry
    # is preceded by at least one full scan cycle of new data.
    # Invalidation: if a same-symbol re-entry < 24h after a losing close
    # WOULD have been profitable in the next 30 days, revisit.
    # Default 24h. Set to 0 to disable.
    brain_post_loss_cooldown_hours: int = 0  # 2026-09 reset: OFF (n=1)

    # Day 47 (Jun 4): MOMENTUM tier-1 size cap. Backtest n=17 closed wallet
    # trades that entered as tier-1 MOMENTUM:
    #   - 5 wins +$237.14, 12 losses -$297.67 → 29% win rate, net -$60.53
    #   - 5 of those losses were WATCHDOG_FORCE_SELL totaling -$230.93
    #     (SATS -$76 Day 40, FN -$23 Day 44, ONDS -$71 Day 47, IONQ -$41,
    #     LUN.TO -$20). All five at amplified tier-1 sizing.
    # Simulating these at tier-2 sizing (observed ratio ~0.43) gives:
    #   - Wins clipped to +$103, losses clipped to -$129 → net -$26.28
    #   - Delta: +$34.25 improvement
    # Sensitivity: every sizing ratio between 0.4-0.7 produces a positive
    # delta because the cohort itself is net-negative. Mechanism: MOMENTUM
    # style is structurally negative-EV at amplified sizing — Claude's
    # MOMENTUM flag fires on extension setups, which produce big winners
    # AND big losers, but the losers are more frequent.
    # Cost of being wrong: would have clipped IONQ +$80 to +$35, SOUN
    # +$30 to +$13, etc. Net still negative for cohort even after the
    # foregone upside. Invalidation: if the next 10 MOMENTUM entries at
    # tier-2 produce >=6 wins AND positive net P&L, revisit.
    # Default True. Set False to revert.
    brain_momentum_force_tier2: bool = False  # 2026-09 reset: OFF (n=17); sizing is risk-based now

    # Day 55 (Jun 15): NEUTRAL ≥85 tier cap. Mirrors the Day-47 MOMENTUM cap
    # but for the NEUTRAL cohort, discovered during the Pedro-away week:
    #   - n=8 closed wallet trades with signal_style=NEUTRAL, entry_tier=1,
    #     entry_score>=85.
    #   - 2W/6L = 25% win rate; net P&L -$97.68.
    #   - 4 of 6 losses were WATCHDOG-family closes (FSLR -$65, TEAM -$64,
    #     ONDS -$27 twice as ONDS NEUTRAL ≥85 before the Day-47 MOMENTUM cap).
    # Backtest (sizing ratio 0.447, matching the actual observed tier-2/tier-1
    # ratio):
    #   - actual cohort net: -$97.68
    #   - simulated at tier-2: -$43.65
    #   - DELTA: +$54.03 improvement
    #   - 2 winners cut (IONQ +$64→+$29, SOUN +$30→+$14): -$52 upside lost
    #   - 6 losers cut: +$106 downside saved
    # Sensitivity: dropping threshold to ≥80 yields nearly identical delta
    # (+$56) but cuts 9 more trades that net out — too mixed to justify.
    # The ≥85 cohort is the structural negative-EV cell.
    # Cross-cutting context: the combined Day-47 (MOMENTUM ≥83) + Day-55
    # (NEUTRAL ≥85) finding suggests "high score + amplified tier-1 sizing"
    # is the deeper mechanism. Per-style caps are cleaner to operate and
    # easier to revert independently if one cohort regime-shifts.
    # Invalidation: if the next 5 NEUTRAL ≥85 entries at tier-2 produce
    # >=3 wins AND positive net P&L, revisit. Same shape as the MOMENTUM
    # invalidation criterion.
    # Default True. Set False to revert.
    brain_neutral_high_score_force_tier2: bool = False  # 2026-09 reset: OFF (n=8)
    brain_neutral_high_score_threshold: int = 85

    # --- Trade Horizon (SHORT vs LONG) ---
    # SHORT: momentum trades, 1-7d hold, tight trail, every-scan thesis re-eval.
    # LONG: trend trades, up to 60d, wide trail, daily thesis re-eval (AFTER_CLOSE only).
    # Winners were consistently cut early because the thesis tracker ran 5x/day
    # and Claude's conservative bias flagged every extended winner as "weakening".
    # LONG positions now breathe — only 1 re-eval/day, wider trail, no quality prune.
    horizon_short_trail_pct: float = 5.0       # trailing stop % below peak (SHORT horizon)
    horizon_long_trail_pct: float = 8.0        # trailing stop % below peak (LONG horizon)
    horizon_short_expiry_days: int = 7         # max hold for SHORT horizon
    horizon_long_expiry_days: int = 60         # max hold for LONG horizon
    horizon_long_min_score: int = 72           # minimum entry score for LONG horizon
    # LONG positions require N consecutive AVOID/SELL signals before closing
    # (prevents single-signal shake-outs like CCO.TO Day 14: opened 19h prior,
    # closed on one MORNING AVOID at +1.49% while the trend was intact).
    # Set to 1 to revert to immediate-exit (pre-Day 14 behavior).
    brain_long_signal_exit_threshold: int = 1  # 2026-09 reset: OFF (n=1 CCO.TO); 1 = exit on first AI SELL

    # QUALITY_PRUNE magnitude floor (Day 17 learning): the prune rule
    # used to fire on any pnl < 0, but with the wallet active a 1-2%
    # drawdown locks in real $ losses ($10-20 per Tier-1 trade) on
    # positions that would likely recover. Floor at 3%: positions need
    # to be down at least this much before the prune fires. Symmetric
    # with the 3% trailing-stop activation threshold.
    brain_quality_prune_min_loss_pct: float = 3.0

    # STAGNATION_PRUNE (Day 14 learning): LONG/LONG positions that produce
    # nothing meaningful for a week+ are dead capital. REGN held 12 days for
    # +0.77% at +$5.73 — a "win" on paper but 0.06%/day is worse than sitting
    # in cash. This rule cuts them: held >= N days, |pnl| < X%, thesis
    # weakening/invalid → PRUNE. Frees the slot for something that actually
    # moves. Set days to 999 to disable.
    brain_stagnation_min_days: int = 7
    brain_stagnation_pnl_range_pct: float = 2.0

    # --- Short Selling (direction=SHORT) ---
    # Two-wallet system: LONG wallet buys winners, SHORT wallet bets against losers.
    # Separate slot limits concentrate capital on fewer, higher-quality positions.
    brain_max_open_long: int = 8               # max simultaneous LONG brain positions
    brain_max_open_short: int = 6              # max simultaneous SHORT brain positions
    brain_short_max_score: int = 40            # score must be <= this to qualify for short entry
    brain_short_trail_pct: float = 5.0         # trailing stop % ABOVE trough for shorts
    brain_short_hard_stop_pct: float = -8.0    # catastrophic stop for shorts (price up 8%)
    brain_short_expiry_days: int = 14          # max hold for short-direction trades

    # --- Brain Watchdog ---
    watchdog_enabled: bool = True
    watchdog_pnl_alert_pct: float = 2.0       # Alert if P&L drops this % in one interval
    watchdog_stop_proximity_pct: float = 2.0  # Alert if price within this % of stop
    watchdog_min_notify_pct: float = 0.5      # Don't send Telegram for moves smaller than this %

    # --- Notification Quiet Hours ---
    # Quiet window is [start_hour:start_minute, end_hour:end_minute) in ET.
    # If end is earlier than start the window spans midnight.
    notify_quiet_start: int = 18         # 6 PM ET -- quiet begins
    notify_quiet_start_minute: int = 0
    notify_quiet_end: int = 6            # 6:30 AM ET -- quiet ends (notifications resume)
    notify_quiet_end_minute: int = 30
    notify_quiet_enabled: bool = True

    # --- Per-scan Telegram toggle ---
    # Comma-separated scan_type values whose notifications should be silenced
    # (PRE_MARKET | MORNING | MIDDAY | PRE_CLOSE | AFTER_CLOSE | MANUAL).
    # Messages emitted inside a `run_scan` matching any of these types are
    # dropped before hitting the Telegram API. `urgent=True` sends (e.g. OTP)
    # still bypass this filter.
    notify_scans_disabled: str = "PRE_MARKET"
    watchdog_weekend_crypto: bool = True      # Run watchdog on weekends for crypto positions (crypto trades 24/7)
    allow_weekend_scans: bool = True          # Allow manual scan triggers on weekends

    # --- Brain Editor ---
    brain_token_secret: str = ""  # Separate secret for brain tokens
    brain_otp_expire_seconds: int = 60
    brain_token_expire_minutes: int = 15
    brain_max_challenges_per_window: int = 3
    brain_max_otp_attempts: int = 3

    # --- AI Budget Limits ---
    # ~$50/month total. Daily caps ≈ monthly / 21 trading days so one bad
    # day can't burn the month. Claude normally runs free via the local CLI
    # (CLAUDE_LOCAL=true); its budget only matters on the API path. When
    # Grok is capped, sentiment is marked unavailable (a data gap).
    budget_daily_limit_usd: float = 1.20     # Default daily cap per provider
    budget_monthly_limit_usd: float = 5.00   # Default monthly cap per provider
    budget_claude_monthly_usd: float = 5.00
    budget_claude_daily_usd: float = 0.25
    budget_grok_monthly_usd: float = 45.00
    budget_grok_daily_usd: float = 2.15
    # OpenAI (Codex API path only; the CLI path is $0). 0 = unset -> the
    # API path is capped at $5/month anyway (see codex_client).
    budget_openai_monthly_usd: float = 0.0
    budget_openai_daily_usd: float = 0.25

    # --- AI call caching (cuts repeat calls across the day's scans) ---
    sentiment_cache_hours: int = 24     # X/news sentiment reused per ticker
    # Market-wide Grok "macro pulse": one live-search call, reused across
    # scans for this long so the Grok budget goes to per-stock news.
    macro_pulse_cache_hours: int = 6
    # When Grok can't give the market mood (no credit, paused, failed), ask
    # Claude with web search instead — local CLI only ($0 on the owner's
    # subscription); the API path is not used for this.
    macro_pulse_claude_fallback: bool = True
    macro_pulse_claude_timeout_s: int = 180
    # Back-end log files (relative to back-end/); "" disables file logging.
    log_file_dir: str = "logs"
    # Scans are Grok-first (live X + web, cached 24h per ticker). PASS 2
    # reserves the daily Grok budget in candidate-rank order, so the best
    # candidates get sentiment first; the rest proceed with sentiment marked
    # unavailable. scan_grok_on_buy: before the decision model rules on a
    # routine BUY whose sentiment is missing, try Grok once more (a no-op
    # when grok_data already came from Grok). scan_sentiment_free_first is
    # kept only so old .env files parse; there is no free path any more.
    scan_sentiment_free_first: bool = False
    scan_grok_on_buy: bool = True
    synthesis_cache_hours: int = 3      # routine synthesis reused per ticker...
    synthesis_cache_max_move_pct: float = 2.0  # ...unless price moved more than this

    # --- Learning → prompt ---
    # Hypotheses are shown to Claude only once they have this many observed
    # trades; below it they're noise that can still sway a live decision.
    hypothesis_prompt_min_observations: int = 30

    # --- Counterfactual candidate outcomes (migration 008) ---
    # Daily 17:15 ET job: seed one candidate_outcomes row per signal and
    # fill 5/10/20 trading-day forward returns vs SPY. Read by the daily
    # learning report (skip-reason effectiveness, p_win calibration,
    # routine-vs-decision model, AI-status cohorts).
    outcomes_enabled: bool = True
    outcomes_seed_lookback_days: int = 7        # seed signals created in this window
    outcomes_fill_max_age_days: int = 60        # stop retrying fills older than this
    outcomes_report_lookback_days: int = 180    # window analysed by daily learning
    outcomes_benchmark: str = "SPY"             # benchmark for excess returns (all assets)

    # --- On-demand "Check a stock" (services/stock_check.py) ---
    # A repeat check of the same resolved symbol within this window returns
    # the cached result (force=true bypasses). Non-cached runs are capped
    # per US-Eastern day and at most N run at once.
    stock_check_cache_minutes: int = 30
    stock_check_daily_limit: int = 20
    stock_check_max_concurrent: int = 2
    stock_check_job_ttl_minutes: int = 60
    # Long-term mode (services/long_term_check.py): results and the
    # long-run yfinance data (max history, fund/financial data) are cached
    # this long per resolved symbol. Shares the daily limit above.
    stock_check_long_cache_hours: int = 24

    # --- My holdings (the owner's REAL long-term positions; migration 010) ---
    # Daily 17:45 ET monitor (services/holdings_monitor.py): trend, drawdown,
    # earnings, cited red flags (stocks only), concentration. Telegram alerts
    # fire only on state changes and are de-duplicated per holding.
    holdings_monitor_enabled: bool = True
    holdings_alerts_enabled: bool = True
    holdings_max_weight_pct: float = 15.0        # "overweight" above this share of the book
    holdings_earnings_alert_trading_days: int = 3
    # Red-flag search for held STOCKS (never ETFs / crypto): reuse a cached
    # Grok result from a scan / check when there is one; otherwise call Grok
    # at most once per stock per holdings_grok_refresh_days (budget-checked).
    holdings_ai_red_flags: bool = True
    holdings_grok_refresh_days: int = 7
    # Long-term reviews (POST /holdings/review): "review all" at most once
    # per N days; a single request may review at most N selected holdings.
    holdings_review_all_days: int = 7
    holdings_review_max_ids: int = 10

    # --- Portfolio tracker (migration 013; no AI) ---
    # Shared quotes: every 60s during the 09:30-16:00 ET session (plus one
    # refresh after the close) for the distinct symbols in all holdings and
    # watchlists. Daily snapshots per user/account at 16:30 ET.
    quotes_refresh_enabled: bool = True
    portfolio_snapshots_enabled: bool = True
    # Cost control (migration 014): the quotes job runs every minute but a
    # symbol is refreshed only when its best follower's level is due —
    # followed by any premium/owner user -> every quotes_refresh_seconds_premium,
    # free-only -> every quotes_refresh_seconds_free. Only symbols followed by
    # users seen in the last quotes_active_user_days days are refreshed.
    quotes_refresh_seconds_free: int = 900
    quotes_refresh_seconds_premium: int = 60
    quotes_active_user_days: int = 7
    # Insights history jobs (migration 014): income forecast (18:00 ET) and
    # Signa check statuses per followed symbol (18:15 ET).
    portfolio_insights_jobs_enabled: bool = True
    # Per-user Telegram notifications (migration 016, feature.telegram_alerts =
    # premium): event digests at 08:30 ET daily + 18:30 ET weekdays, price
    # alerts and big moves every 5 min during the session.
    telegram_notifications_enabled: bool = True

    # --- Language ---
    language: str = "en"  # "en" or "pt"

    # --- App ---
    app_name: str = "Signa"
    debug: bool = False
    # Dev tools: lets an OWNER preview the app as free / premium via the
    # X-View-As request header (web "View as" switch). Never enable in
    # production. Nothing is written to the database.
    dev_tools_enabled: bool = False

    # extra="ignore": tolerate retired keys (e.g. AUTH_ENABLED) left in old .env files
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @field_validator("synthesis_providers", "sentiment_providers", mode="after")
    @classmethod
    def _drop_retired_providers(cls, v: list[str]) -> list[str]:
        # Gemini was removed; an old .env may still list it.
        return [p for p in (v or []) if str(p).strip().lower() != "gemini"]

    @field_validator("codex_decision_mode", mode="after")
    @classmethod
    def _codex_mode(cls, v: str) -> str:
        v = (v or "").strip().lower()
        return v if v in ("record", "veto", "off") else "record"

    @model_validator(mode="after")
    def validate_security(self):
        _check_secret("JWT_SECRET_KEY", self.jwt_secret_key)
        _check_secret("BRAIN_TOKEN_SECRET", self.brain_token_secret)
        if self.jwt_secret_key == self.brain_token_secret:
            raise ValueError(
                "JWT_SECRET_KEY and BRAIN_TOKEN_SECRET must be different values. "
                "Generate each with: openssl rand -hex 32"
            )
        if not self.debug and "*" in self.cors_origins:
            raise ValueError(
                "CORS_ORIGINS cannot contain '*' in production (DEBUG=false). "
                "Set specific origins like ['https://yourdomain.com']"
            )
        return self


settings = Settings()
