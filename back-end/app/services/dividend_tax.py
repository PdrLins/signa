"""Dividend withholding tax by account type (premium after-tax view). Pure, no AI.

Who gets it: users with feature.tax_view (premium) whose country is CA or
US and whose profile says dividend_tax_view="after" (profile_service
.effective_tax_view). Everyone else sees before-tax amounts only (the
summary's "tax" block is null with a reason code). Accounts without an
account_type get NO tax applied and are listed under `untyped_accounts`.

This models WITHHOLDING TAX only (what a foreign government keeps at the
source). Income tax at the user's marginal rate is not modelled.

Canada (country CA)
  US-listed payer (listing not .TO/.V/.NE/.CN, currency USD):
    TFSA, FHSA, RESP        15% withheld, LOST (not recoverable)
    RRSP                    0% (Canada-US treaty exempts retirement accounts)
    NON_REGISTERED, OTHER   15% withheld, RECOVERABLE as a foreign tax credit
                            (OTHER is treated as a taxable account — the
                            conservative choice for "cash lands in my hand")
  Canadian-listed payer: no withholding.
United States (country US)
  Foreign (Canadian-listed) payer: 15% withheld (Canada-US treaty rate)
    TAXABLE, OTHER          RECOVERABLE as a foreign tax credit
    ROTH_IRA, TRADITIONAL_IRA, 401K   LOST
  (Simplified: the treaty exemption some Canadian payers grant US
  retirement accounts is ignored; other countries' rates are not modelled.)
  US-listed payer: no withholding.

Inside the fund (both countries, every account, can't be avoided)
  A Canadian-listed ETF that holds US stocks pays 15% US withholding
  INSIDE the fund before it distributes. The distribution Yahoo reports is
  already net of it, so it is NOT subtracted again: it is reported as
  `inside_fund` = distribution x us_share x 0.15 / 0.85 (the estimated
  tax the fund paid on your behalf). us_share comes from:
    1. FUND_US_SHARE below (maintained by hand; approximate US equity
       weight of the fund's holdings, e.g. XEQT ~0.45), else
    2. name/category heuristics for Canadian-listed funds: "S&P 500",
       "U.S.", "US ", "USA", "Nasdaq", "American", "Dow Jones" -> 1.0.
  Anything else: 0 (not flagged).

after_tax = gross - lost withholding (recoverable withholding comes back as
a credit at tax time; cash_received = gross - all withholding).
"""

from __future__ import annotations

from app.services.holdings_service import base_symbol

WHT_RATE = 0.15
CA_SUFFIXES = (".TO", ".V", ".NE", ".CN")

# Approximate share of a Canadian-listed fund's distributions that come
# from US stocks (hand-maintained; update when fund mixes change).
FUND_US_SHARE: dict[str, float] = {
    # S&P 500 / US total market / Nasdaq-100 (unhedged and hedged)
    "VFV": 1.0, "VSP": 1.0, "XUS": 1.0, "XSP": 1.0, "ZSP": 1.0, "ZUE": 1.0, "HULC": 1.0,
    "XUU": 1.0, "VUN": 1.0, "VUS": 1.0, "ZQQ": 1.0, "XQQ": 1.0, "QQC": 1.0, "QQEQ": 1.0,
    "ZUQ": 1.0, "ZDY": 1.0, "XUH": 1.0, "ZUT": 1.0,
    # US covered-call funds listed in Canada (upper bound: the fund's option
    # premiums are not taxed, only its US dividends — see module docstring)
    "ZWT": 1.0, "QQCL": 1.0, "ZWH": 1.0, "ZWS": 1.0, "HYLD": 0.6,
    # all-in-one / global
    "XEQT": 0.45, "VEQT": 0.44, "ZEQT": 0.45, "XGRO": 0.36, "VGRO": 0.35, "ZGRO": 0.36,
    "XBAL": 0.27, "VBAL": 0.26, "ZBAL": 0.27, "XAW": 0.62, "VXC": 0.60, "XWD": 0.70, "VGG": 1.0,
}
_US_WORDS = ("s&p 500", "u.s.", "us ", "usa", "nasdaq", "american", "dow jones", "united states")

LOST_TYPES = {"CA": {"TFSA", "FHSA", "RESP"}, "US": {"ROTH_IRA", "TRADITIONAL_IRA", "401K"}}
EXEMPT_TYPES = {"CA": {"RRSP"}, "US": set()}


def is_ca_listed(symbol: str) -> bool:
    return str(symbol or "").upper().endswith(CA_SUFFIXES)


def fund_us_share(symbol: str, profile: dict | None = None) -> float:
    """US-stock share of a CANADIAN-listed fund's distributions (0 otherwise)."""
    if not is_ca_listed(symbol):
        return 0.0
    b = base_symbol(symbol)
    if b in FUND_US_SHARE:
        return FUND_US_SHARE[b]
    p = profile or {}
    if not p.get("is_fund"):
        return 0.0
    text = f" {p.get('name') or ''} {p.get('category') or ''} ".lower()
    return 1.0 if any(w in text for w in _US_WORDS) else 0.0


def rule_for(symbol: str, currency: str | None, account_type: str | None, country: str | None,
             profile: dict | None = None) -> dict:
    """{"applies", "rate", "recoverable", "code", "inside_fund_share"} for one holding.

    applies=False when the account has no type (no tax applied).
    code: none | treaty_exempt | lost | recoverable."""
    c = (country or "").upper()
    t = (account_type or "").upper() or None
    share = fund_us_share(symbol, profile)
    if t is None:
        return {"applies": False, "rate": 0.0, "recoverable": False, "code": "untyped", "inside_fund_share": share}
    foreign = False
    if c == "CA":
        foreign = not is_ca_listed(symbol) and (currency or "USD").upper() == "USD"
    elif c == "US":
        foreign = is_ca_listed(symbol)
    if not foreign:
        return {"applies": True, "rate": 0.0, "recoverable": False, "code": "none", "inside_fund_share": share}
    if t in EXEMPT_TYPES.get(c, set()):
        return {"applies": True, "rate": 0.0, "recoverable": False, "code": "treaty_exempt",
                "inside_fund_share": share}
    lost = t in LOST_TYPES.get(c, set())
    return {"applies": True, "rate": WHT_RATE, "recoverable": not lost, "code": "lost" if lost else "recoverable",
            "inside_fund_share": share}


def apply(gross: float, rule: dict) -> dict:
    """Split a gross dividend (home currency) by a rule_for() result."""
    withheld = gross * rule["rate"] if rule["applies"] else 0.0
    lost = 0.0 if rule["recoverable"] else withheld
    recoverable = withheld if rule["recoverable"] else 0.0
    inside = gross * rule["inside_fund_share"] * WHT_RATE / (1 - WHT_RATE) if rule["inside_fund_share"] else 0.0
    return {"gross": gross, "lost": lost, "recoverable": recoverable, "inside_fund": inside,
            "after_tax": gross - lost, "cash_received": gross - withheld}
