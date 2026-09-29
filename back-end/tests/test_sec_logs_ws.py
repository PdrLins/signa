"""Log stream WebSocket takes its tokens from subprotocols, never the URL."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.v1 import logs


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(logs, "decode_token", lambda t: {"sub": "u1", "jti": "j1"} if t == "good-jwt" else None)
    monkeypatch.setattr(logs, "is_token_blacklisted", lambda jti: False)
    monkeypatch.setattr(logs, "_decode_brain_token", lambda t: {"sub": "u1", "jti": "b1"} if t == "good-brain" else None)
    monkeypatch.setattr(logs, "brain_session_exists", lambda jti: True)
    app = FastAPI()
    app.include_router(logs.router)
    return TestClient(app)


def test_accepts_tokens_via_subprotocols(client):
    protocols = ["signa.logs", "jwt.good-jwt", "brain-token.good-brain"]
    with client.websocket_connect("/logs/stream", subprotocols=protocols) as ws:
        assert ws.accepted_subprotocol == "signa.logs"


def test_rejects_tokens_in_query_string(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/logs/stream?jwt=good-jwt&token=good-brain", subprotocols=["signa.logs"]):
            pass
    assert exc.value.code == 4001


def test_rejects_bad_brain_token(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/logs/stream", subprotocols=["signa.logs", "jwt.good-jwt", "brain-token.bad"]
        ):
            pass
    assert exc.value.code == 4003
