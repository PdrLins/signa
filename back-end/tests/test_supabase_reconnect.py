"""A dropped Supabase keep-alive connection is retried on a fresh one
(app/db/supabase.py) instead of failing a whole scan or watchdog run."""

import httpx
import pytest

from app.db import supabase as supa

DROP = httpx.RemoteProtocolError("Server disconnected without sending a response.")


def test_should_retry_rules():
    assert supa.should_retry_disconnect("GET", DROP)
    assert supa.should_retry_disconnect("POST", DROP)              # nothing reached the server
    assert supa.should_retry_disconnect("PATCH", httpx.ConnectError("refused"))
    # a write that may have been processed is NOT retried
    assert not supa.should_retry_disconnect("POST", httpx.ReadError("peer closed mid-response"))
    assert supa.should_retry_disconnect("GET", httpx.ReadError("peer closed mid-response"))
    assert not supa.should_retry_disconnect("GET", ValueError("bad"))


def _transport(monkeypatch, failures, exc=DROP):
    calls = {"n": 0}

    def fake(self, request):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise exc
        return httpx.Response(200, json=[{"ok": True}], request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake)
    monkeypatch.setattr(supa.time, "sleep", lambda s: None)
    return supa._ReconnectTransport(), calls


def test_transport_retries_then_succeeds(monkeypatch):
    t, calls = _transport(monkeypatch, failures=2)
    client = httpx.Client(transport=t, base_url="https://example.supabase.co")
    r = client.post("/rest/v1/signals", json={"symbol": "MSFT"})
    assert r.status_code == 200 and calls["n"] == 3


def test_transport_gives_up_after_three(monkeypatch):
    t, calls = _transport(monkeypatch, failures=5)
    client = httpx.Client(transport=t, base_url="https://example.supabase.co")
    with pytest.raises(httpx.RemoteProtocolError):
        client.get("/rest/v1/signals")
    assert calls["n"] == 3


def test_unsafe_write_error_is_not_retried(monkeypatch):
    t, calls = _transport(monkeypatch, failures=1, exc=httpx.ReadError("peer closed mid-response"))
    client = httpx.Client(transport=t, base_url="https://example.supabase.co")
    with pytest.raises(httpx.ReadError):
        client.post("/rest/v1/positions", json={"symbol": "MSFT"})
    assert calls["n"] == 1
