"""Application settings loaded from environment variables."""

from pydantic import model_validator
from pydantic_settings import BaseSettings


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
    auth_enabled: bool = True
    jwt_secret_key: str  # No default — forces env var
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60  # 1 hour (refresh for longer sessions)
    otp_expire_seconds: int = 30  # 30 seconds
    session_token_expire_seconds: int = 180

    # --- Telegram Webhook ---
    telegram_webhook_secret: str = ""  # Set via setWebhook secret_token param

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:3000"]

    # --- Rate Limiting ---
    max_login_attempts_per_ip: int = 5
    max_otp_attempts_per_session: int = 3
    rate_limit_window_minutes: int = 15

    # --- Trusted Proxies ---
    trusted_proxies: list[str] = ["127.0.0.1", "::1"]

    # --- Claude ---
    claude_local: bool = True  # True = use local Claude CLI (no API tokens)
    claude_model: str = "claude-sonnet-4-20250514"
    claude_max_tokens: int = 1024

    # --- Grok ---
    grok_base_url: str = "https://api.x.ai/v1"
    grok_model: str = "grok-3-mini"

    # --- Gemini ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # --- AI Provider Preferences ---
    # Ordered list of providers to try for each task. First available wins.
    synthesis_providers: list[str] = ["claude", "gemini"]
    sentiment_providers: list[str] = ["grok", "gemini"]

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

    # --- Two-Pass Scanning ---
    ai_candidate_limit: int = 15  # Top N candidates get AI analysis
    ai_enabled: bool = True       # False = tech-only mode (zero AI cost)

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
    brain_max_open: int = 20          # Max simultaneous brain positions

    # --- Brain Thesis Tracking (Stage 6) ---
    # When enabled, every scan re-evaluates the thesis on every open brain
    # position via Claude. Positions whose thesis is invalidated are closed
    # with exit_reason='THESIS_INVALIDATED', regardless of P&L direction.
    # Existing exit paths (STOP_HIT, TARGET_HIT, etc.) are GATED by the
    # thesis check — if the thesis is still 'valid', the exit is suppressed
    # as noise. EXCEPTION: catastrophic stops (pnl_pct <= -8%) ALWAYS fire,
    # bypassing the thesis gate, so a wrong thesis call can never blow us up.
    # Set to False to revert to pre-Stage-6 behavior (no thesis checks).
    brain_thesis_gate_enabled: bool = True
    brain_thesis_hard_stop_pct: float = -8.0  # catastrophic stop carve-out
    # Re-buy cooldown after a THESIS_INVALIDATED exit. The brain otherwise
    # would re-open the same symbol on the next scan if Claude flips back
    # to BUY (Claude is non-deterministic on borderline trades). Real case
    # 2026-04-09: WING #1 invalidated in 17s, WING #2 opened 54min later
    # at +$2.95 from the close, currently bleeding. The Day 4 journal
    # explicitly named this fix. Set to 0 to disable.
    brain_thesis_rebuy_cooldown_minutes: int = 60

    # --- Trade Horizon (SHORT vs LONG) ---
    # SHORT: momentum trades, 1-7d hold, tight trail, every-scan thesis re-eval.
    # LONG: trend trades, up to 60d, wide trail, daily thesis re-eval (AFTER_CLOSE only).
    # Winners were consistently cut early because the thesis tracker ran 5x/day
    # and Claude's conservative bias flagged every extended winner as "weakening".
    # LONG positions now breathe — only 1 re-eval/day, wider trail, no quality prune.
    horizon_short_trail_pct: float = 5.0       # trailing stop % below peak (SHORT)
    horizon_long_trail_pct: float = 8.0        # trailing stop % below peak (LONG)
    horizon_short_expiry_days: int = 7         # max hold for SHORT
    horizon_long_expiry_days: int = 60         # max hold for LONG
    horizon_long_min_score: int = 72           # minimum entry score for LONG

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
    watchdog_weekend_crypto: bool = False     # Run watchdog on weekends for crypto positions
    allow_weekend_scans: bool = True          # Allow manual scan triggers on weekends

    # --- Brain Editor ---
    brain_token_secret: str = ""  # Separate secret for brain tokens
    brain_otp_expire_seconds: int = 60
    brain_token_expire_minutes: int = 15
    brain_max_challenges_per_window: int = 3
    brain_max_otp_attempts: int = 3

    # --- AI Budget Limits ---
    budget_daily_limit_usd: float = 1.00     # Max spend per provider per day
    budget_monthly_limit_usd: float = 5.00   # Default monthly cap per provider
    budget_claude_monthly_usd: float = 5.00  # Claude monthly cap
    budget_grok_monthly_usd: float = 5.00    # Grok monthly cap
    budget_gemini_monthly_usd: float = 0.00  # Gemini = free tier (0 = unlimited)

    # --- Language ---
    language: str = "en"  # "en" or "pt"

    # --- App ---
    app_name: str = "Signa"
    debug: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def validate_security(self):
        if self.jwt_secret_key in ("change-me-in-production", ""):
            raise ValueError(
                "JWT_SECRET_KEY must be set to a secure random value. "
                "Generate one with: openssl rand -hex 32"
            )
        if self.auth_enabled and self.brain_token_secret in ("", "generate-with-openssl-rand-hex-32"):
            raise ValueError(
                "BRAIN_TOKEN_SECRET must be set to a secure random value. "
                "Generate one with: openssl rand -hex 32"
            )
        if not self.debug and "*" in self.cors_origins:
            raise ValueError(
                "CORS_ORIGINS cannot contain '*' in production (DEBUG=false). "
                "Set specific origins like ['https://yourdomain.com']"
            )
        return self


settings = Settings()
