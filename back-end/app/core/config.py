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
    otp_expire_seconds: int = 120  # 2 minutes (accounts for Telegram delivery latency)
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
    claude_model: str = "claude-sonnet-4-20250514"
    claude_max_tokens: int = 1024

    # --- Grok ---
    grok_base_url: str = "https://api.x.ai/v1"
    grok_model: str = "grok-4.1-fast"

    # --- Scoring Thresholds ---
    score_buy: int = 75
    score_hold: int = 50
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

    # --- Pre-filter ---
    min_volume: int = 200_000
    min_abs_change: float = 0.01
    max_candidates: int = 50

    # --- Scheduler ---
    timezone: str = "America/New_York"

    # --- Concurrency ---
    max_concurrent_api_calls: int = 10

    # --- Position Monitoring ---
    position_monitor_enabled: bool = True
    position_alert_profit_pct: float = 5.0
    position_alert_loss_pct: float = -5.0

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
        if not self.auth_enabled and not self.debug:
            raise ValueError(
                "AUTH_ENABLED=false is only allowed when DEBUG=true"
            )
        return self


settings = Settings()
