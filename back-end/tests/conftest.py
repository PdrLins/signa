"""Shared test fixtures."""

import os

import pytest

# Strong dummy secrets for tests. Forced (not setdefault) so a weak value in the
# shell (e.g. JWT_SECRET_KEY=x) or a placeholder in back-end/.env can't trip the
# Settings security validator. Must run before any `app.*` import.
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-0123456789abcdef0123456789abcdef"
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")


@pytest.fixture(autouse=True)
def _no_live_dividends(monkeypatch):
    """The stock page fetches a dividend profile: never let a test reach
    yfinance for it (empty data -> "no dividend"). Tests that need data
    patch dividends._fetch_raw themselves."""
    from app.services import dividends
    monkeypatch.setattr(dividends, "_fetch_raw", lambda symbol, info=None: {"info": info or {}, "dividends": None,
                                                                             "calendar": {}})
    dividends._cache.clear()


@pytest.fixture(autouse=True)
def _no_live_fx(monkeypatch):
    """Currencies other than USD/CAD convert through Yahoo "{CCY}=X" rates:
    never fetch them in tests. Tests that need a rate patch _download_fx."""
    from app.services import price_cache
    monkeypatch.setattr(price_cache, "_download_fx", lambda codes: {})
    for k in list(getattr(price_cache._fx_cache, "_store", {}) or {}):
        if k.startswith("USD") and k != "USDCAD":
            price_cache._fx_cache.delete(k) if hasattr(price_cache._fx_cache, "delete") else None
    yield


@pytest.fixture(autouse=True)
def _no_live_followed_symbols(monkeypatch):
    """The after-close quotes refresh reads every followed symbol: no DB in tests."""
    from app.db import queries
    monkeypatch.setattr(queries, "get_all_followed_symbols", lambda: set())


@pytest.fixture(autouse=True)
def _fresh_follow_cache():
    """The quotes job caches who follows what for 5 minutes: start each test empty."""
    from app.services import quotes
    quotes.clear_follow_cache()
    quotes.clear_quote_caches()
    from app.core import user_cache
    user_cache.clear()
    yield
    quotes.clear_follow_cache()
    quotes.clear_quote_caches()


@pytest.fixture(autouse=True)
def _no_live_last_seen(monkeypatch):
    """The auth middleware records users.last_seen_at in a thread: never let
    a test reach Supabase for it."""
    from app.middleware import auth as auth_mw
    monkeypatch.setattr(auth_mw, "touch_user_last_seen", lambda _uid: None)
    auth_mw._last_seen_written.clear()


@pytest.fixture(autouse=True)
def _no_usage_leak():
    """Usage counters are process memory: start every test empty."""
    from app.services import usage_metrics
    usage_metrics.reset()


@pytest.fixture(autouse=True)
def _owner_access_by_default(monkeypatch, request):
    """Test users aren't in a DB: treat them as owner (single-user behaviour)
    and use the code's feature catalog. Access-level tests opt out with the
    `real_access` marker and patch levels themselves."""
    if request.node.get_closest_marker("real_access"):
        return
    from app.core import access
    from app.middleware import auth as auth_mw
    owner = lambda _uid: {"level": "owner", "slot_bonus": 0}  # noqa: E731
    monkeypatch.setattr(access, "get_user_access", owner)
    monkeypatch.setattr(auth_mw, "get_user_access", owner)
    defaults = {k: v[0] for k, v in access.FEATURE_CATALOG.items()}
    monkeypatch.setattr(access, "get_feature_levels", lambda: dict(defaults))


@pytest.fixture(autouse=True)
def _no_price_alert_db(monkeypatch):
    """The quotes job reads price alerts (migration 015): never reach the real
    DB from a test. Alert tests replace these with fakes."""
    from app.db import queries
    monkeypatch.setattr(queries, "get_active_alert_follow_rows", lambda: [])
    monkeypatch.setattr(queries, "get_active_price_alerts", lambda symbols: [])


@pytest.fixture(autouse=True)
def _no_referrals_db(monkeypatch):
    """Referrals / account IDs (migration 019) read Supabase: by default
    behave like a database without 019 (account_id null, no slot bonus,
    rewards no-op). Referral tests install tests/referral_fakes.ReferralDB."""
    from app.services import referrals

    class _No019:
        def table(self, name):
            raise RuntimeError(f'relation "{name}" does not exist (42P01)')
    monkeypatch.setattr(referrals, "_db", lambda: _No019())
    referrals.clear_caches()


def pytest_configure(config):
    config.addinivalue_line("markers", "real_access: use real access-level resolution (no owner default)")
