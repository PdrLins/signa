"""Grok live-search client: citations gate, mention_count, request shape."""

import asyncio
import json

import httpx

from app.ai import grok_client


def _responses_payload(model_json: dict, citations: list[str] | None) -> dict:
    payload = {
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": json.dumps(model_json), "annotations": []}
                ],
            },
        ],
        "status": "completed",
    }
    if citations is not None:
        payload["citations"] = citations
    return payload


GOOD_JSON = {
    "score": 72,
    "label": "bullish",
    "confidence": 65,
    "mention_count": 240,
    "top_themes": ["earnings beat", "guidance raise"],
    "breaking_news": "Company raises FY guidance",
    "breaking_news_url": "https://www.reuters.com/markets/abc",
    "red_flags": [
        {"text": "SEC investigation rumor", "url": "https://random-blog.example/uncited"},
        {"text": "Class action lawsuit filed", "url": "https://www.reuters.com/legal/xyz"},
    ],
    "notable_accounts": ["@analyst"],
    "summary": "Bullish on earnings.",
    "sources": [],
}


def _run_with_transport(handler, monkeypatch) -> tuple[dict, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def _wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_wrapped))
    monkeypatch.setattr(grok_client, "_client", client)
    monkeypatch.setattr(grok_client.settings, "xai_api_key", "test-key")

    async def _go():
        try:
            return await grok_client.analyze_sentiment("ACME", max_retries=2)
        finally:
            await client.aclose()

    return asyncio.run(_go()), seen


def test_no_citations_means_zero_confidence_and_error(monkeypatch):
    result, _ = _run_with_transport(
        lambda req: httpx.Response(200, json=_responses_payload(GOOD_JSON, citations=[])),
        monkeypatch,
    )
    assert result["confidence"] == 0
    assert result["error"]
    assert result["mention_count"] == 0
    assert result["breaking_news"] is None
    assert result["citations"] == []


def test_cited_result_keeps_only_cited_items(monkeypatch):
    citations = [
        "https://x.com/someone/status/1",
        "https://www.reuters.com/markets/abc",
        "https://www.reuters.com/legal/xyz",
    ]
    result, seen = _run_with_transport(
        lambda req: httpx.Response(200, json=_responses_payload(GOOD_JSON, citations)),
        monkeypatch,
    )
    assert result["error"] is None
    assert result["confidence"] == 65
    assert result["mention_count"] == 240
    assert result["breaking_news"] == "Company raises FY guidance"
    assert [f["text"] for f in result["red_flags"]] == ["Class action lawsuit filed"]
    assert result["citations"] == citations

    body = json.loads(seen[0].content)
    assert seen[0].url.path.endswith("/responses")
    types = {t["type"] for t in body["tools"]}
    assert types == {"x_search", "web_search"}
    xs = next(t for t in body["tools"] if t["type"] == "x_search")
    assert xs["from_date"] and xs["to_date"]
    assert "no_inline_citations" in body["include"]


def test_mention_count_zeroed_without_x_sources(monkeypatch):
    result, _ = _run_with_transport(
        lambda req: httpx.Response(
            200, json=_responses_payload(GOOD_JSON, ["https://www.reuters.com/markets/abc"])
        ),
        monkeypatch,
    )
    assert result["error"] is None
    assert result["mention_count"] == 0


def test_annotation_citations_are_collected():
    payload = _responses_payload(GOOD_JSON, citations=None)
    payload["output"][1]["content"][0]["annotations"] = [
        {"type": "url_citation", "url": "https://x.com/a/status/2", "start_index": 0, "end_index": 1}
    ]
    assert grok_client.extract_citations(payload) == ["https://x.com/a/status/2"]


def test_api_error_returns_zero_confidence(monkeypatch):
    result, _ = _run_with_transport(lambda req: httpx.Response(400, json={"error": "bad"}), monkeypatch)
    assert result["confidence"] == 0
    assert result["error"].startswith("API error 400")
