"""Integration tests for API endpoints.

Uses a real JWT issued by the test secret to authenticate.
Mocks Supabase queries to avoid needing a live database.
"""

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


# Set env vars BEFORE importing app
os.environ["AUTH_ENABLED"] = "true"
os.environ["DEBUG"] = "false"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-integration-tests-only"
os.environ["BRAIN_TOKEN_SECRET"] = "test-brain-secret-for-integration-tests-only"
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_KEY"] = "eyJtest"

from fastapi.testclient import TestClient

from main import app
from app.core.security import create_access_token

client = TestClient(app)

# Create a valid test JWT for authenticated requests
_TEST_TOKEN = create_access_token(user_id="test-user-uuid", username="testuser")
_AUTH_HEADERS = {"Authorization": f"Bearer {_TEST_TOKEN}"}

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
    """GET /api/v1/holdings without token → 401."""
    resp = client.get("/api/v1/holdings")
    assert resp.status_code == 401


@patch("app.db.queries.remove_from_watchlist")
@patch("app.db.queries.get_watchlist")
@patch("app.db.queries.add_to_watchlist")
def test_watchlist_add_remove(mock_add, mock_get, mock_remove):
    """POST/GET/DELETE /watchlist — full lifecycle."""
    mock_add.return_value = SAMPLE_WATCHLIST_ITEM

    # Add
    resp = client.post("/api/v1/watchlist/AAPL", headers=_AUTH_HEADERS)
    assert resp.status_code == 201

    # Get (with AAPL in list)
    mock_get.return_value = [SAMPLE_WATCHLIST_ITEM]
    resp = client.get("/api/v1/watchlist", headers=_AUTH_HEADERS)
    assert resp.status_code == 200
    symbols = [item["symbol"] for item in resp.json()["items"]]
    assert "AAPL" in symbols

    # Remove
    mock_remove.return_value = True
    resp = client.delete("/api/v1/watchlist/AAPL", headers=_AUTH_HEADERS)
    assert resp.status_code == 200

    # Get again (empty)
    mock_get.return_value = []
    resp = client.get("/api/v1/watchlist", headers=_AUTH_HEADERS)
    assert resp.status_code == 200
    symbols = [item["symbol"] for item in resp.json()["items"]]
    assert "AAPL" not in symbols
