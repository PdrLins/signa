"""Application settings loaded from environment variables."""

from pydantic import model_validator
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
    """All configuration for the Signa back-end."""

    # --- Services ---
    supabase_url: str = ""
    supabase_key: str = ""   # service_role key
    telegram_bot_token: str = ""

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
    # iOS: presenting the refresh token that was rotated less than this many
    # seconds ago (the response was lost) returns the same new pair once
    # instead of reuse_detected (app/services/sessions.py). 0 = off.
    session_refresh_grace_seconds: int = 30
    # Receive bot messages by polling Telegram (getUpdates) when there's no
    # public webhook (local machine). Stops by itself if a webhook is set.
    telegram_polling: bool = True
    # Email (migration 018) and public sign-up (SIGNUP_ENABLED=true).
    signup_enabled: bool = False
    # POST /auth/register: true = an invite code is required (invite-only);
    # false = open sign-up (the code is optional; a friend's code still counts).
    # Turn off before running ads: people from an ad have no code.
    signup_invite_required: bool = True
    email_code_expire_seconds: int = 600
    email_provider: str = "console"   # console (logs, dev) | resend | smtp
    email_from: str = "Signa <no-reply@localhost>"
    resend_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    otp_expire_seconds: int = 30  # 30 seconds

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
    # while the app listens on 127.0.0.1.
    login_otp_enabled: bool = True

    # --- Rate Limiting ---
    max_otp_attempts_per_session: int = 3

    # --- Trusted Proxies ---
    trusted_proxies: list[str] = ["127.0.0.1", "::1"]

    # --- Scheduler ---
    timezone: str = "America/New_York"

    # --- Signa checks (stock page, app/market/technicals.py) ---
    tech_filter_max_rsi: float = 75.0                  # RSI(14) must be <= this
    tech_filter_max_ext_sma50_pct: float = 15.0        # price at most this % above SMA50
    tech_filter_min_dollar_volume: float = 10_000_000  # 20d avg $ volume, stocks/ETFs (native ccy)
    tech_filter_min_dollar_volume_crypto: float = 50_000_000  # 20d avg $ volume, crypto (USD)
    # earnings_soon warns when the next report is within N trading days.
    earnings_blackout_trading_days: int = 3

    # --- Notification Quiet Hours ---
    # Quiet window is [start_hour:start_minute, end_hour:end_minute) in ET.
    # If end is earlier than start the window spans midnight.
    notify_quiet_start: int = 18         # 6 PM ET -- quiet begins
    notify_quiet_start_minute: int = 0
    notify_quiet_end: int = 6            # 6:30 AM ET -- quiet ends (notifications resume)
    notify_quiet_end_minute: int = 30
    notify_quiet_enabled: bool = True

    # --- Logs ---
    # Back-end log files (relative to back-end/); "" disables file logging
    # (containers: logs go to stdout only).
    log_file_dir: str = "logs"

    # --- My holdings (migration 010) ---
    # Daily 17:45 ET price snapshot on every holding (app/services/holding_status.py).
    holdings_monitor_enabled: bool = True
    holdings_max_weight_pct: float = 15.0        # "overweight" above this share of the book
    # Sent in GET /holdings "settings" for older clients (the AI review moved
    # to Signa Advisor).
    holdings_alerts_enabled: bool = True
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
    # Outside the regular session (migration 021): followed crypto refreshes
    # 24/7 at the same plan rates; US stocks followed by Premium users get
    # pre-market (4:00-9:30 ET) and after-hours (16:00-20:00 ET) prices.
    quotes_offhours_enabled: bool = True
    quotes_refresh_seconds_extended: int = 120
    quotes_active_user_days: int = 7
    # Insights history jobs (migration 014): income forecast (18:00 ET) and
    # Signa check statuses per followed symbol (18:15 ET).
    portfolio_insights_jobs_enabled: bool = True
    # Per-user Telegram notifications (migration 016, feature.telegram_alerts =
    # premium): event digests at 08:30 ET daily + 18:30 ET weekdays, price
    # alerts and big moves every 5 min during the session.
    telegram_notifications_enabled: bool = True

    # --- iOS push notifications (migration 025, app/services/push.py) ---
    # APNs token auth: Apple Developer -> Keys -> a key with "Apple Push
    # Notifications service" (.p8). Empty = pushes are only logged (dev).
    push_notifications_enabled: bool = True
    apns_team_id: str = ""
    apns_key_id: str = ""
    apns_private_key: str = ""       # the .p8 contents (PEM); "\n" escapes allowed
    apns_bundle_id: str = ""         # the iOS app's bundle id (APNs topic)

    # --- Language ---
    language: str = "en"  # "en" or "pt"

    # --- App ---
    app_name: str = "Signa"
    debug: bool = False
    # Dev tools: lets an OWNER preview the app as free / premium via the
    # X-View-As request header (web "View as" switch). Never enable in
    # production. Nothing is written to the database.
    dev_tools_enabled: bool = False

    # extra="ignore": tolerate retired keys (e.g. the brain's AI keys) left in old .env files
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @model_validator(mode="after")
    def validate_security(self):
        _check_secret("JWT_SECRET_KEY", self.jwt_secret_key)
        if not self.debug and "*" in self.cors_origins:
            raise ValueError(
                "CORS_ORIGINS cannot contain '*' in production (DEBUG=false). "
                "Set specific origins like ['https://yourdomain.com']"
            )
        return self


settings = Settings()
