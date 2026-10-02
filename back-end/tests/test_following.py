"""Following overview (GET /watchlist/overview): pure builder."""

import pandas as pd

from app.services import following


def _closes(vals):
    return pd.Series(vals, index=pd.date_range("2026-08-01", periods=len(vals), freq="D"))


def test_watched_held_split_and_dedupe():
    watch = [{"symbol": "shop.to", "added_at": "2026-09-28"}, {"symbol": "META", "added_at": "2026-09-01"},
             {"symbol": "SHOP.TO", "added_at": "2026-08-01"}]
    holdings = [{"symbol": "META", "name": "Meta Platforms"}, {"symbol": "XEQT.TO", "name": "iShares Core Equity"},
                {"symbol": "XEQT.TO", "name": None}, {"symbol": "ENB.TO", "name": "Enbridge"}]
    quotes = {"SHOP.TO": {"price": 214.3, "change_pct": 2.1, "currency": "CAD", "as_of": "2026-09-30T14:00:00+00:00"},
              "META": {"price": 742.0, "change_pct": 1.8, "currency": "USD", "as_of": "2026-09-30T13:45:00+00:00"}}
    out = following.build_following(watch, holdings, quotes, {"SHOP.TO": _closes([200.0, 205.0, 210.0])},
                                     {"SHOP.TO": "Shopify"}, "CA", {"used": 4, "limit": 10, "remaining": 6})
    assert [r["symbol"] for r in out["watched"]] == ["SHOP.TO", "META"]
    shop, meta = out["watched"]
    assert shop["name"] == "Shopify" and shop["in_holdings"] is False and shop["added_at"] == "2026-09-28"
    assert shop["spark"] == [200.0, 205.0, 210.0] and shop["change_1m_pct"] == 7.15
    assert meta["in_holdings"] is True and meta["name"] == "Meta Platforms" and meta["spark"] == []
    # held: not on the watchlist, one row per symbol, ordered by name
    assert [r["symbol"] for r in out["held"]] == ["ENB.TO", "XEQT.TO"]
    assert out["held"][1]["name"] == "iShares Core Equity" and out["held"][1]["price"] is None
    assert out["as_of"] == "2026-09-30T13:45:00+00:00" and out["delayed_minutes"] == 15
    assert out["slots"]["limit"] == 10


def test_suggestions_skip_followed_and_follow_country():
    out = following.build_suggestions("CA", ["XEQT.TO", "ENB.TO"])
    assert out[0]["key"] == "popular_ca"
    syms = [i["symbol"] for g in out for i in g["items"]]
    assert "XEQT.TO" not in syms and "ENB.TO" not in syms
    assert len(syms) == len(set(syms))   # a symbol shows in one group only
    assert all(len(g["items"]) <= following.SUGGESTION_LIMIT for g in out)
    assert following.build_suggestions("US", [])[0]["key"] == "popular_us"
    assert following.build_suggestions(None, [])[0]["key"] == "popular_us"


def test_spark_is_capped_and_tolerates_bad_values():
    vals = [float(i) for i in range(1, 40)] + [float("nan")]
    row = following._row("X", None, {"price": 40.0}, _closes(vals), {})
    assert len(row["spark"]) <= following.SPARK_POINTS
    assert row["spark"][-1] == 39.0
    assert following._row("X", None, None, None, {})["spark"] == []


def test_suggestion_quotes_prefer_fresh_rows_then_one_cached_batch(monkeypatch):
    from datetime import datetime, timezone

    from app.services import quotes as quotes_service
    following._suggestion_quotes.clear()
    now = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc).timestamp()
    fresh = datetime.fromtimestamp(now - 60, tz=timezone.utc).isoformat()
    old = datetime.fromtimestamp(now - 7200, tz=timezone.utc).isoformat()
    stored = {"VOO": {"symbol": "VOO", "price": 600.0, "change_pct": 0.5, "currency": "USD", "updated_at": fresh},
              "AAPL": {"symbol": "AAPL", "price": 1.0, "change_pct": 9.0, "currency": "USD", "updated_at": old}}
    fetches = []
    monkeypatch.setattr(quotes_service, "get_stored_quotes", lambda syms: {s: stored[s] for s in syms if s in stored})

    def fetch(syms):
        fetches.append(list(syms))
        return {"AAPL": {"symbol": "AAPL", "price": 250.0, "change_pct": 1.2, "currency": "USD"}}
    monkeypatch.setattr(quotes_service, "fetch_quotes", fetch)
    q = following.suggestion_quotes(["VOO", "AAPL", "ZZZ"], now_ts=now)
    assert q["VOO"]["price"] == 600.0 and q["AAPL"]["price"] == 250.0 and "ZZZ" not in q
    assert fetches == [["AAPL", "ZZZ"]]
    following.suggestion_quotes(["AAPL", "ZZZ"], now_ts=now + 60)        # cached, unpriceable too
    assert len(fetches) == 1
    following.suggestion_quotes(["AAPL"], now_ts=now + following.SUGGESTION_QUOTE_TTL + 1)
    assert len(fetches) == 2
    following._suggestion_quotes.clear()


def test_suggestion_quotes_fail_soft(monkeypatch):
    from app.services import quotes as quotes_service
    following._suggestion_quotes.clear()

    def boom(syms):
        raise RuntimeError("down")
    monkeypatch.setattr(quotes_service, "get_stored_quotes", boom)
    monkeypatch.setattr(quotes_service, "fetch_quotes", boom)
    assert following.suggestion_quotes(["VOO"]) == {}
    groups = following.price_suggestions(following.build_suggestions("US", []), {"VOO": {"price": 600.0,
                                                                                         "change_pct": 0.5,
                                                                                         "currency": "USD"}})
    voo = next(i for g in groups for i in g["items"] if i["symbol"] == "VOO")
    assert (voo["price"], voo["change_pct"], voo["currency"]) == (600.0, 0.5, "USD")
    other = next(i for g in groups for i in g["items"] if i["symbol"] != "VOO")
    assert other["price"] is None and other["change_pct"] is None and other["currency"] is None
    following._suggestion_quotes.clear()
