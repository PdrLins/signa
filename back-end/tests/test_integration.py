"""Integration tests for API endpoints.

Uses FastAPI TestClient with AUTH_ENABLED=false (dev mode)
so that all protected routes are accessible without a real JWT.
Mocks Supabase queries to avoid needing a live database.
"""

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Set env vars BEFORE importing app
os.environ["AUTH_ENABLED"] = "false"
os.environ["DEBUG"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-integration-tests-only"
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_KEY"] = "eyJtest"

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

# ── Sample data ────────────────────────────────────────────

_NOW = datetime.now(timezone.utc).isoformat()

SAMPLE_SIGNAL = {
    "id": "sig-001",
    "symbol": "AAPL",
    "action": "BUY",
    "status": "CONFIRMED",
    "score": 88,
    "confidence": 82,
    "is_gem": True,
    "bucket": "HIGH_RISK",
    "price_at_signal": 185.50,
    "target_price": 210.0,
    "stop_loss": 175.0,
    "risk_reward": 3.5,
    "catalyst": "Earnings beat",
    "sentiment_score": 78,
    "reasoning": "Strong momentum",
    "technical_data": {},
    "fundamental_data": {},
    "macro_data": {},
    "grok_data": {},
    "scan_id": "scan-001",
    "created_at": _NOW,
    "updated_at": _NOW,
}

SAMPLE_SCAN = {
    "id": "scan-001",
    "scan_type": "MORNING",
    "started_at": _NOW,
    "completed_at": _NOW,
    "tickers_scanned": 150,
    "signals_found": 12,
    "gems_found": 3,
    "status": "COMPLETE",
    "error_message": None,
    "created_at": _NOW,
}

SAMPLE_WATCHLIST_ITEM = {
    "id": "wl-001",
    "symbol": "AAPL",
    "added_at": _NOW,
    "notes": None,
}


# ── Mock helpers ───────────────────────────────────────────

def _mock_supabase():
    """Return a mock Supabase client whose query chains return empty data."""
    mock = MagicMock()
    # Default: all queries return empty
    result = MagicMock()
    result.data = []
    result.execute.return_value = result
    mock.table.return_value = result
    result.select.return_value = result
    result.insert.return_value = result
    result.update.return_value = result
    result.delete.return_value = result
    result.upsert.return_value = result
    result.eq.return_value = result
    result.neq.return_value = result
    result.gte.return_value = result
    result.order.return_value = result
    result.limit.return_value = result
    result.is_.return_value = result
    return mock


# ── Tests ──────────────────────────────────────────────────

def test_health():
    """GET /api/v1/health → 200."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "uptime_seconds" in data


def test_cors_header():
    """GET /api/v1/health with Origin header includes CORS response header."""
    resp = client.get(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


@patch("app.services.auth_service.login")
def test_login_returns_session_token(mock_login):
    """POST /api/v1/auth/login → 200 + session_token."""
    mock_login.return_value = {
        "message": "OTP sent to Telegram",
        "session_token": "abc123session",
    }
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "testuser", "password": "testpass"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_token" in data
    assert data["session_token"] == "abc123session"


def test_protected_route_without_token():
    """GET /api/v1/signals with AUTH_ENABLED=false gives dev-mode access (200).

    In production (AUTH_ENABLED=true), this would be 401.
    We verify the auth middleware dev-mode bypass works.
    """
    with patch("app.db.queries.get_signals", return_value=[]):
        resp = client.get("/api/v1/signals")
    assert resp.status_code == 200


@patch("app.db.queries.get_signals")
@patch("app.services.price_cache.enrich_signals", side_effect=lambda s: s)
def test_signals_returns_list(mock_enrich, mock_get):
    """GET /api/v1/signals → 200 + list (can be empty)."""
    mock_get.return_value = [SAMPLE_SIGNAL]
    resp = client.get("/api/v1/signals")
    assert resp.status_code == 200
    data = resp.json()
    assert "signals" in data
    assert isinstance(data["signals"], list)
    assert data["count"] >= 0


@patch("app.db.queries.get_signals")
@patch("app.services.price_cache.enrich_signals", side_effect=lambda s: s)
def test_signals_gems_never_404(mock_enrich, mock_get):
    """GET /api/v1/signals/gems → 200 + list (never 404)."""
    mock_get.return_value = []
    resp = client.get("/api/v1/signals/gems")
    assert resp.status_code == 200
    data = resp.json()
    assert "signals" in data
    assert isinstance(data["signals"], list)


@patch("app.db.queries.get_signals")
@patch("app.db.queries.get_scans")
def test_stats_daily_shape(mock_scans, mock_signals):
    """GET /api/v1/stats/daily → 200 + all required fields."""
    mock_signals.return_value = [SAMPLE_SIGNAL]
    mock_scans.return_value = [SAMPLE_SCAN]

    resp = client.get("/api/v1/stats/daily")
    assert resp.status_code == 200
    data = resp.json()

    required_fields = [
        "gems_today", "gems_yesterday", "win_rate_30d",
        "tickers_scanned", "next_scan_time",
        "ai_cost_today", "claude_cost", "grok_cost",
    ]
    for field in required_fields:
        assert field in data, f"Missing field: {field}"


@patch("app.db.queries.get_scans")
def test_scans_today_returns_4(mock_get):
    """GET /api/v1/scans/today → 200 + list of exactly 4 items."""
    mock_get.return_value = [SAMPLE_SCAN]
    resp = client.get("/api/v1/scans/today")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 4
    for item in data:
        assert "scan_type" in item
        assert "label" in item
        assert "scheduled_time" in item
        assert "status" in item


@patch("app.db.queries.remove_from_watchlist")
@patch("app.db.queries.get_watchlist")
@patch("app.db.queries.add_to_watchlist")
def test_watchlist_add_remove(mock_add, mock_get, mock_remove):
    """POST/GET/DELETE /watchlist — full lifecycle."""
    mock_add.return_value = SAMPLE_WATCHLIST_ITEM

    # Add
    resp = client.post("/api/v1/watchlist/AAPL")
    assert resp.status_code == 201

    # Get (with AAPL in list)
    mock_get.return_value = [SAMPLE_WATCHLIST_ITEM]
    resp = client.get("/api/v1/watchlist")
    assert resp.status_code == 200
    symbols = [item["symbol"] for item in resp.json()["items"]]
    assert "AAPL" in symbols

    # Remove
    mock_remove.return_value = True
    resp = client.delete("/api/v1/watchlist/AAPL")
    assert resp.status_code == 200

    # Get again (empty)
    mock_get.return_value = []
    resp = client.get("/api/v1/watchlist")
    assert resp.status_code == 200
    symbols = [item["symbol"] for item in resp.json()["items"]]
    assert "AAPL" not in symbols
