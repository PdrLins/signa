"""Profile: who the user is and how the tracker shows his money (migration 013).

Stored in user_settings (display_name, country, home_currency, language,
dividend_tax_view, compare_index, holdings_native_currency). Rules:

  * country          ISO 3166-1 alpha-2 or null. Signa is global; CA and US
                     unlock country-specific extras (account tax types,
                     after-tax dividends) for premium users.
  * home_currency    the currency totals are shown in (default CAD). Only
                     USD/CAD are converted today; other currencies are
                     accepted and marked unconverted where it matters.
  * dividend_tax_view  "before" | "after". "after" can only be SET by a user
                     with feature.tax_view (premium) whose country is CA/US
                     (403 upgrade_required / 422 tax_view_unavailable). Reads
                     return the EFFECTIVE value: "before" for anyone not
                     eligible, whatever is stored (a downgrade or a country
                     change can't leave a premium view on).
  * compare_index    opt-in benchmark, null by default; one of COMPARE_INDEXES.

No AI here.
"""

from __future__ import annotations

from typing import Any

from app.core.access import can, upgrade_required
from app.core.api_errors import api_error
from app.db import queries

# ISO 3166-1 alpha-2 (officially assigned codes).
COUNTRIES: frozenset[str] = frozenset("""
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT
BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH
ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT
HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS
LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI
NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG
SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG
UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW
""".split())

# Home currencies a user can pick (ISO 4217). All convert (Yahoo FX, cached:
# price_cache.usd_rates).
CURRENCIES: frozenset[str] = frozenset(
    "CAD USD EUR GBP BRL AUD NZD JPY CHF SEK NOK DKK MXN INR HKD SGD CNY KRW ZAR PLN ILS ARS CLP COP".split()
)
CONVERTIBLE_CURRENCIES: frozenset[str] = CURRENCIES

# Default home currency for a country (sign-up from the phone's region).
COUNTRY_CURRENCY: dict[str, str] = {
    "CA": "CAD", "US": "USD", "BR": "BRL", "MX": "MXN", "AR": "ARS", "CL": "CLP", "CO": "COP",
    "GB": "GBP", "IE": "EUR", "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR", "PT": "EUR", "NL": "EUR",
    "BE": "EUR", "AT": "EUR", "FI": "EUR", "GR": "EUR", "LU": "EUR", "CH": "CHF", "SE": "SEK", "NO": "NOK",
    "DK": "DKK", "PL": "PLN", "JP": "JPY", "CN": "CNY", "HK": "HKD", "SG": "SGD", "KR": "KRW", "IN": "INR",
    "AU": "AUD", "NZ": "NZD", "ZA": "ZAR", "IL": "ILS",
}

LANGUAGES: tuple[str, ...] = ("en", "pt")
TAX_VIEWS: tuple[str, ...] = ("before", "after")
TAX_VIEW_COUNTRIES: frozenset[str] = frozenset({"CA", "US"})

# Opt-in benchmarks (Yahoo symbols).
COMPARE_INDEXES: dict[str, str] = {
    "XEQT.TO": "iShares Core Equity ETF Portfolio",
    "VEQT.TO": "Vanguard All-Equity ETF Portfolio",
    "VFV.TO": "Vanguard S&P 500 Index ETF (CAD)",
    "XIU.TO": "iShares S&P/TSX 60 Index ETF",
    "^GSPTSE": "S&P/TSX Composite",
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq Composite",
    "SPY": "SPDR S&P 500 ETF",
    "VT": "Vanguard Total World Stock ETF",
    "^BVSP": "Ibovespa",
    "BOVA11.SA": "iShares Ibovespa (BOVA11)",
    "IVVB11.SA": "iShares S&P 500 em reais (IVVB11)",
    "^FTSE": "FTSE 100",
    "^STOXX50E": "Euro Stoxx 50",
    "^N225": "Nikkei 225",
}

DEFAULTS: dict[str, Any] = {
    "display_name": None,
    "country": None,
    "home_currency": "CAD",
    "language": "en",
    "dividend_tax_view": "before",
    "compare_index": None,
    "holdings_native_currency": False,
}


def tax_view_allowed(level: str, country: str | None) -> bool:
    return (country or "").upper() in TAX_VIEW_COUNTRIES and can(level, "feature.tax_view")


def effective_tax_view(stored: str | None, level: str, country: str | None) -> str:
    return "after" if stored == "after" and tax_view_allowed(level, country) else "before"


def merged_settings(row: dict | None) -> dict:
    row = row or {}
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        if row.get(k) is not None:
            out[k] = row[k]
    return out


def build_profile(user: dict, row: dict | None, email: str | None, slots: dict | None) -> dict:
    """The API shape of GET/PUT /profile."""
    s = merged_settings(row)
    level = user.get("access_level") or "free"
    stored = s["dividend_tax_view"] if s["dividend_tax_view"] in TAX_VIEWS else "before"
    return {
        "user_id": user["user_id"],
        "username": user.get("username"),
        "display_name": s["display_name"],
        "email": email,
        "country": s["country"],
        "home_currency": s["home_currency"],
        "language": s["language"],
        "dividend_tax_view": effective_tax_view(stored, level, s["country"]),
        "dividend_tax_view_stored": stored,
        "tax_view_available": tax_view_allowed(level, s["country"]),
        "compare_index": s["compare_index"],
        "holdings_native_currency": bool(s["holdings_native_currency"]),
        "access_level": level,
        "slots": slots,
    }


def _422(code: str, message: str, field: str) -> Exception:
    return api_error(code, message, 422, field=field)


def validate_update(user: dict, current: dict | None, patch: dict) -> dict:
    """Clean `patch` (only the keys the client sent) or raise a structured error."""
    level = user.get("access_level") or "free"
    cur = merged_settings(current)
    clean: dict[str, Any] = {}

    if "display_name" in patch:
        v = patch["display_name"]
        if v is not None:
            if not isinstance(v, str):
                raise _422("invalid_display_name", "Display name must be text.", "display_name")
            v = " ".join(v.split())
            if len(v) > 60 or any(ord(c) < 32 for c in v):
                raise _422("invalid_display_name", "Display name: up to 60 characters.", "display_name")
            v = v or None
        clean["display_name"] = v

    if "country" in patch:
        v = patch["country"]
        if v is not None:
            v = str(v).strip().upper()
            if v not in COUNTRIES:
                raise _422("invalid_country", "Country must be an ISO 3166-1 alpha-2 code (e.g. CA, US, BR).",
                           "country")
        clean["country"] = v

    if "home_currency" in patch:
        v = str(patch["home_currency"] or "").strip().upper()
        if v not in CURRENCIES:
            raise _422("invalid_currency", f"Home currency must be one of {', '.join(sorted(CURRENCIES))}.",
                       "home_currency")
        clean["home_currency"] = v

    if "language" in patch:
        v = patch["language"]
        if v not in LANGUAGES:
            raise _422("invalid_language", "Language must be en or pt.", "language")
        clean["language"] = v

    if "compare_index" in patch:
        v = patch["compare_index"]
        if v is not None:
            v = str(v).strip().upper()
            if v not in COMPARE_INDEXES:
                raise _422("invalid_compare_index",
                           f"Benchmark must be one of {', '.join(COMPARE_INDEXES)} (or null).", "compare_index")
        clean["compare_index"] = v

    if "holdings_native_currency" in patch:
        v = patch["holdings_native_currency"]
        if not isinstance(v, bool):
            raise _422("invalid_value", "holdings_native_currency must be true or false.",
                       "holdings_native_currency")
        clean["holdings_native_currency"] = v

    if "dividend_tax_view" in patch:
        v = patch["dividend_tax_view"]
        if v not in TAX_VIEWS:
            raise _422("invalid_tax_view", "dividend_tax_view must be before or after.", "dividend_tax_view")
        if v == "after":
            if not can(level, "feature.tax_view"):
                raise upgrade_required("feature.tax_view")
            country = clean.get("country", cur["country"])
            if (country or "").upper() not in TAX_VIEW_COUNTRIES:
                raise _422("tax_view_unavailable",
                           "The after-tax view is available for Canada and the United States only.",
                           "dividend_tax_view")
        clean["dividend_tax_view"] = v
    return clean


# ---------------------------------------------------------------- DB (sync)

def get_profile(user: dict) -> dict:
    from app.services import referrals, slots
    row = queries.get_profile_settings(user["user_id"])
    profile = build_profile(user, row, queries.get_user_email(user["user_id"]), slots.slot_summary(user))
    return {**profile, "account_id": referrals.account_id_for(user["user_id"])}  # migration 019; null before


def update_profile(user: dict, patch: dict) -> dict:
    from app.services import referrals, slots
    current = queries.get_profile_settings(user["user_id"])
    clean = validate_update(user, current, patch)
    saved = queries.upsert_profile_settings(user["user_id"], clean) if clean else {}
    profile = build_profile(user, {**(current or {}), **clean, **(saved or {})},
                            queries.get_user_email(user["user_id"]), slots.slot_summary(user))
    return {**profile, "account_id": referrals.account_id_for(user["user_id"])}


def get_country_and_currency(user_id: str) -> tuple[str | None, str]:
    """(country, home_currency) for rules elsewhere (accounts, imports)."""
    s = merged_settings(queries.get_profile_settings(user_id))
    return s["country"], s["home_currency"]


def signup_settings(country: str | None, home_currency: str | None, language: str | None,
                    locale: str | None) -> dict:
    """First settings of a new account from what the app sends (or the phone's
    locale, e.g. "pt-BR"): country, home currency (the country's when not
    given), language (pt for Portuguese locales). Invalid values are dropped. Pure."""
    loc = str(locale or "").replace("_", "-")
    parts = loc.split("-")
    lang_guess = "pt" if parts[0].lower() == "pt" else "en" if parts[0] else None
    region = parts[-1].upper() if len(parts) > 1 and len(parts[-1]) == 2 else None
    c = str(country or region or "").strip().upper() or None
    c = c if c in COUNTRIES else None
    ccy = str(home_currency or "").strip().upper() or COUNTRY_CURRENCY.get(c or "", "")
    out: dict[str, Any] = {}
    if c:
        out["country"] = c
    if ccy in CURRENCIES:
        out["home_currency"] = ccy
    lang = language if language in LANGUAGES else lang_guess
    if lang in LANGUAGES:
        out["language"] = lang
    return out
