"""Prompt formatters for the richer data, red-flag normalization, and the
Grok sentiment request (severity schema, market-cap context, timeout)."""

import asyncio
import json

import httpx

from app.ai import grok_client
from app.ai.prompts import (
    GROK_SENTIMENT_PROMPT,
    format_fundamentals,
    format_price_context,
    format_sentiment,
    normalize_red_flag,
    sentiment_size_context,
)

RICH = {
    "last_eps_surprise_pct": 7.5, "days_since_last_earnings": 12,
    "eps_est_change_0q_30d_pct": 3.2, "eps_est_change_fy1_90d_pct": -1.5,
    "eps_revisions_up_30d": 6, "eps_revisions_down_30d": 2,
    "short_percent_of_float": 0.043, "short_interest_change_pct": 12.0, "short_ratio_days": 1.8,
    "insider_net_shares_6m": 25_000, "insider_buy_count_6m": 3, "insider_sell_count_6m": 1,
}


class TestFormatters:
    def test_fundamentals_include_new_fields_when_present(self):
        text = format_fundamentals({"pe_ratio": 20.0, **RICH})
        assert "Last EPS surprise vs consensus: +7.5% (12 days ago)" in text
        assert "current-quarter EPS estimate 30d +3.2%" in text
        assert "fiscal-year 90d -1.5%" in text
        assert "Analyst EPS revisions last 30d: 6 up, 2 down" in text
        assert "Short interest: 4.3% of float, +12.0% vs prior month, 1.8 days to cover" in text
        assert "Insider net shares, last 6 months: +25,000 (3 purchase / 1 sale transactions)" in text

    def test_fundamentals_omit_absent_fields(self):
        text = format_fundamentals({"pe_ratio": 20.0})
        for word in ("surprise", "revisions", "estimate", "Short interest", "Insider"):
            assert word not in text
        assert format_fundamentals({}) == "No fundamental data available"

    def test_partial_fields(self):
        text = format_fundamentals({"last_eps_surprise_pct": -3.0, "short_interest_change_pct": -20.0})
        assert "Last EPS surprise vs consensus: -3.0%" in text and "days ago" not in text
        assert "Short interest: -20.0% vs prior month" in text

    def test_price_context_relative_strength(self):
        tech = {"current_price": 100.0, "momentum_3m": 10.0, "momentum_6m": 15.0}
        fund = {"rs_benchmark": "XLK", "rs_benchmark_return_3m": 4.0, "rs_benchmark_return_6m": 20.0,
                "spy_return_3m": 2.0}
        text = format_price_context(tech, fund)
        assert "Return relative to XLK: 3m +6.0 pts, 6m -5.0 pts" in text
        assert "Return relative to SPY: 3m +8.0 pts" in text

    def test_price_context_without_benchmarks(self):
        text = format_price_context({"current_price": 100.0, "momentum_3m": 10.0}, {})
        assert "relative to" not in text

    def test_sentiment_shows_severity(self):
        grok = {"confidence": 60, "score": 55, "label": "neutral", "red_flags": [
            {"text": "Patent verdict", "url": "https://r.com/a", "category": "litigation",
             "severity": "low", "estimated_impact_usd": 5.7e9},
            {"text": "Old flag", "url": "https://r.com/b"},
        ]}
        text = format_sentiment(grok)
        assert "Cited red flag [litigation, low, stated impact ~$5.70B]: Patent verdict" in text
        assert "Cited red flag: Old flag" in text


class TestRedFlagNormalization:
    def test_valid_fields(self):
        out = normalize_red_flag({"text": "x", "url": "u", "severity": "HIGH",
                                  "category": "Going Concern", "estimated_impact_usd": "1e9"})
        assert out == {"text": "x", "url": "u", "severity": "high",
                       "category": "going_concern", "estimated_impact_usd": 1e9}

    def test_invalid_fields_dropped(self):
        out = normalize_red_flag({"text": "x", "url": "u", "severity": "extreme",
                                  "category": "weird", "estimated_impact_usd": None})
        assert out == {"text": "x", "url": "u"}
        out = normalize_red_flag({"text": "x", "url": "u", "severity": "low", "category": "weird"})
        assert out["category"] == "other"
        assert normalize_red_flag({"url": "u"}) is None
        assert normalize_red_flag("text") is None

    def test_size_context(self):
        assert sentiment_size_context(None) == ""
        assert sentiment_size_context(0) == ""
        assert "5.00 trillion" in sentiment_size_context(5e12)
        assert "2.5 billion" in sentiment_size_context(2.5e9)
        prompt = GROK_SENTIMENT_PROMPT.format(ticker="X", from_date="a", to_date="b", size_context="")
        assert '"severity"' in prompt and '"category"' in prompt and "estimated_impact_usd" in prompt


def _payload(model_json, citations):
    return {
        "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(model_json), "annotations": []}]}],
        "citations": citations,
    }


def _run(handler, monkeypatch, **kw):
    seen = []

    def _wrapped(req):
        seen.append(req)
        return handler(req)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_wrapped))
    monkeypatch.setattr(grok_client, "_client", client)
    monkeypatch.setattr(grok_client.settings, "xai_api_key", "test-key")

    async def _go():
        try:
            return await grok_client.analyze_sentiment("AAPL", max_retries=3, **kw)
        finally:
            await client.aclose()

    return asyncio.run(_go()), seen


class TestGrokSeverity:
    def test_severity_passes_validation_and_market_cap_in_prompt(self, monkeypatch):
        model = {"score": 50, "label": "neutral", "confidence": 60, "mention_count": 0, "red_flags": [
            {"text": "Patent verdict $5.7B", "url": "https://www.reuters.com/legal/x",
             "category": "litigation", "severity": "low", "estimated_impact_usd": 5.7e9},
            {"text": "Uncited fraud", "url": "https://nowhere.example/x",
             "category": "fraud", "severity": "critical"},
        ]}
        result, seen = _run(
            lambda req: httpx.Response(200, json=_payload(model, ["https://www.reuters.com/legal/x"])),
            monkeypatch, market_cap=5e12,
        )
        assert result["red_flags"] == [{
            "text": "Patent verdict $5.7B", "url": "https://www.reuters.com/legal/x",
            "severity": "low", "category": "litigation", "estimated_impact_usd": 5.7e9,
        }]
        body = json.loads(seen[0].content)
        user_msg = body["input"][-1]["content"]
        assert "5.00 trillion" in user_msg
        assert body["max_turns"] == grok_client.settings.grok_max_turns

    def test_timeout_is_not_retried(self, monkeypatch):
        def _timeout(req):
            raise httpx.ReadTimeout("slow", request=req)

        result, seen = _run(_timeout, monkeypatch)
        assert len(seen) == 1
        assert result["confidence"] == 0 and "Timeout" in result["error"]
