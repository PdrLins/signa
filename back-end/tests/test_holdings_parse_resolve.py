"""My holdings — import parsing, symbol resolution (TSX preference, ambiguity)."""

import asyncio

import pytest

from app.services import holdings_service as hs
from app.services import stock_check as sc


def _p(text):
    return [{k: r.get(k) for k in ("input", "shares", "avg_cost", "account", "error")} for r in hs.parse_holdings_text(text)]


# ── parsing ──

def test_parse_bare_ticker():
    assert _p("XEQT") == [{"input": "XEQT", "shares": None, "avg_cost": None, "account": None, "error": None}]


def test_parse_shares_only():
    assert _p("NVDA 17.99")[0] | {} == {"input": "NVDA", "shares": 17.99, "avg_cost": None, "account": None, "error": None}


def test_parse_shares_and_cost_with_at():
    r = _p("RY.TO 4.1 @ 145.20")[0]
    assert (r["input"], r["shares"], r["avg_cost"]) == ("RY.TO", 4.1, 145.2)


def test_parse_dollar_signs_words_and_at_word():
    r = _p("$PLTR 10 shares at $25.50")[0]
    assert (r["input"], r["shares"], r["avg_cost"]) == ("PLTR", 10.0, 25.5)


def test_parse_several_tickers_on_one_line_including_cost_ticker():
    assert [r["input"] for r in _p("XEQT, COST, NVDA")] == ["XEQT", "COST", "NVDA"]


def test_parse_tabs_and_account():
    r = _p("AAPL\t3\t150\tTFSA")[0]
    assert (r["input"], r["shares"], r["avg_cost"], r["account"]) == ("AAPL", 3.0, 150.0, "TFSA")


def test_parse_csv_with_header_any_order():
    rows = _p("Ticker,Avg Cost,Quantity,Account\nNVDA,120,17.99,RRSP\nXEQT,,,\nRY.TO,145.2,4.1,Non-registered")
    assert rows[0] == {"input": "NVDA", "shares": 17.99, "avg_cost": 120.0, "account": "RRSP", "error": None}
    assert rows[1]["input"] == "XEQT" and rows[1]["shares"] is None
    assert rows[2]["account"] == "NON_REGISTERED"


def test_parse_semicolon_csv():
    assert _p("symbol;shares\nMSFT;2")[0]["shares"] == 2.0


def test_parse_skips_blank_and_comments():
    assert [r["input"] for r in _p("# my list\n\nXEQT\n   \nVFV")] == ["XEQT", "VFV"]


def test_parse_merges_duplicates_weighting_cost():
    r = hs.parse_holdings_text("NVDA 2 @ 100\nNVDA 2 @ 200")
    assert len(r) == 1 and r[0]["shares"] == 4.0 and r[0]["avg_cost"] == 150.0 and r[0]["merged"] == 2


def test_parse_duplicate_without_cost_drops_cost():
    r = hs.parse_holdings_text("NVDA 2 @ 100\nNVDA 2")
    assert r[0]["shares"] == 4.0 and r[0]["avg_cost"] is None


def test_parse_invalid_ticker_flagged():
    assert _p("BAD!!")[0]["error"] == "invalid_ticker"


def test_parse_caps_lines():
    text = "\n".join(f"T{i}" for i in range(500))
    assert len(hs.parse_holdings_text(text)) == hs.MAX_IMPORT_LINES


def test_parse_ignores_negative_or_zero_numbers():
    r = _p("NVDA 0")[0]
    assert r["shares"] is None


# ── candidate order ──

def test_candidate_symbols_default_unchanged(monkeypatch):
    monkeypatch.setattr(sc, "get_all_tickers", lambda: [])
    assert sc.candidate_symbols("ENS") == ["ENS", "ENS.TO", "ENS-USD"]


def test_candidate_symbols_prefer_tsx(monkeypatch):
    monkeypatch.setattr(sc, "get_all_tickers", lambda: [])
    assert sc.candidate_symbols("ENS", prefer_tsx=True) == ["ENS.TO", "ENS", "ENS-USD"]


def test_candidate_symbols_universe_still_wins(monkeypatch):
    monkeypatch.setattr(sc, "get_all_tickers", lambda: ["BTC-USD"])
    assert sc.candidate_symbols("BTC", prefer_tsx=True)[0] == "BTC-USD"


def test_candidate_symbols_suffix_as_is():
    assert sc.candidate_symbols("RY.TO", prefer_tsx=True) == ["RY.TO"]


# ── resolution ──

LISTINGS = {
    "ENS.TO": {"symbol": "ENS.TO", "name": "E Split Corp.", "exchange": "TSX", "currency": "CAD",
               "asset_type": "STOCK", "price": 17.1},
    "ENS": {"symbol": "ENS", "name": "EnerSys", "exchange": "NYSE", "currency": "USD",
            "asset_type": "STOCK", "price": 110.0},
    "XEQT.TO": {"symbol": "XEQT.TO", "name": "iShares Core Equity ETF Portfolio", "exchange": "TSX",
                "currency": "CAD", "asset_type": "ETF", "price": 34.0},
    "NVDA": {"symbol": "NVDA", "name": "NVIDIA Corporation", "exchange": "NASDAQ", "currency": "USD",
             "asset_type": "STOCK", "price": 180.0},
    "BTC-USD": {"symbol": "BTC-USD", "name": "Bitcoin USD", "exchange": "CRYPTO", "currency": "USD",
                "asset_type": "CRYPTO", "price": 90000.0},
}


@pytest.fixture
def listings(monkeypatch):
    looked: list[str] = []

    def fake_lookup(sym):
        looked.append(sym)
        return LISTINGS.get(sym)

    monkeypatch.setattr(hs, "_lookup_listing", fake_lookup)
    monkeypatch.setattr(sc, "get_all_tickers", lambda: ["BTC-USD", "XEQT.TO", "NVDA"])
    return looked


def test_resolve_ambiguous_prefers_tsx_but_flags(listings):
    res = asyncio.run(hs.resolve_input("ENS"))
    assert res["status"] == "ambiguous"
    assert res["selected"]["symbol"] == "ENS.TO"
    assert res["selected"]["name"] == "E Split Corp."
    assert [a["symbol"] for a in res["alternatives"]] == ["ENS.TO", "ENS"]
    assert res["note"] == "prefer_tsx"
    assert "ENS-USD" not in listings        # crypto not tried when a stock listing exists


def test_resolve_tsx_only(listings):
    res = asyncio.run(hs.resolve_input("XEQT"))
    assert res["status"] == "ok" and res["selected"]["symbol"] == "XEQT.TO"


def test_resolve_us_only(listings):
    res = asyncio.run(hs.resolve_input("NVDA"))
    assert res["status"] == "ok" and res["selected"]["symbol"] == "NVDA"


def test_resolve_known_crypto(listings):
    res = asyncio.run(hs.resolve_input("BTC"))
    assert res["selected"]["symbol"] == "BTC-USD"


def test_resolve_not_found(listings):
    res = asyncio.run(hs.resolve_input("ZZZZ"))
    assert res["status"] == "not_found" and res["selected"] is None


def test_resolve_explicit_suffix(listings):
    res = asyncio.run(hs.resolve_input("ENS.TO"))
    assert res["status"] == "ok" and listings == ["ENS.TO"]


def test_resolve_rows_marks_existing_and_invalid(listings):
    rows = hs.parse_holdings_text("ENS 3\nNVDA\nBAD!!")
    out = asyncio.run(hs.resolve_rows(rows, existing_symbols={"NVDA"}))
    assert out[0]["status"] == "ambiguous" and out[0]["shares"] == 3.0
    assert out[1]["existing"] is True
    assert out[2]["status"] == "invalid"


def test_resolve_cdr_prefers_us_listing_but_flags(monkeypatch):
    table = {
        "RDDT.TO": {"symbol": "RDDT.TO", "name": "Reddit, Inc.", "exchange": "TSX", "currency": "CAD",
                    "asset_type": "ETF", "price": 13.7},
        "RDDT": {"symbol": "RDDT", "name": "Reddit, Inc.", "exchange": "NYSE", "currency": "USD",
                 "asset_type": "STOCK", "price": 143.0},
    }
    monkeypatch.setattr(hs, "_lookup_listing", lambda s: table.get(s))
    monkeypatch.setattr(sc, "get_all_tickers", lambda: [])
    res = asyncio.run(hs.resolve_input("RDDT"))
    assert res["status"] == "ambiguous" and res["note"] == "cdr"
    assert res["selected"]["symbol"] == "RDDT"
    assert [a["symbol"] for a in res["alternatives"]] == ["RDDT", "RDDT.TO"]


def test_is_cdr_of_names():
    assert hs.is_cdr_of({"name": "NVIDIA CDR (CAD Hedged)"}, {"name": "NVIDIA Corporation"})
    assert not hs.is_cdr_of({"name": "E Split Corp."}, {"name": "EnerSys"})
    assert not hs.is_cdr_of({"name": None}, {"name": None})
