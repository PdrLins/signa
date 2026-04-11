"""Plain-English warning text for technical danger signs in the AI prompt.

============================================================
WHY THIS MODULE EXISTS
============================================================

`signal_breakdown.py` is a frontend-facing rules engine: it produces i18n
KEYS like `"macd_strongly_negative"` with interpolation params, and the
React store turns those into EN/PT strings for the signal detail page.

The AI synthesis prompt also needs to surface these warnings, but in a
different way:
  • English-only (Claude prompts are English)
  • Prose instead of i18n keys (Claude doesn't speak i18n)
  • Salience-formatted (each warning prefixed with ⚠ and explained
    in one sentence about WHY it matters, not just what fired)

This module is the bridge: same rule engine, different output format.

When a new TONE_NEGATIVE rule is added to `signal_breakdown.RULES`, add
a matching entry to `KEY_TO_PROMPT_TEXT` here so the AI prompt picks it up.

============================================================
DESIGN PRINCIPLE
============================================================

The `format_warning_signs()` output gets injected into the Claude
synthesis prompt JUST BEFORE the "Your Task" section. The placement is
deliberate: LLMs exhibit recency bias, so positioning warnings near the
decision question gives them more weight than burying them between
Technical Indicators and Investment Knowledge.

The intent is NOT to override Claude. It's to make sure Claude can't
plausibly miss a danger sign because it was buried as one number in a
JSON-style technicals dump. AI is still the decider — we just hand it
a complete dossier.
"""

from __future__ import annotations

from app.services.signal_breakdown import compute_signal_breakdown


# When a new TONE_NEGATIVE rule is added to signal_breakdown.RULES, add
# a matching entry here. Templates use {kwarg} interpolation populated
# from each rule's `label_value` dict. The format string is plain text;
# we prefix it with "- ⚠ " when we render the section.
KEY_TO_PROMPT_TEXT: dict[str, str] = {
    "macd_strongly_negative": (
        "MACD histogram is {hist} (strongly negative, scaled to price) — "
        "momentum has reversed and the price is decelerating into a downtrend"
    ),
    "vs_sma200_extended": (
        "Price is {pct}% from the 200-day SMA (extreme distance) — "
        "mean reversion risk is high in either direction"
    ),
    "momentum_collapse": (
        "Multi-timeframe weakness confirmed: price below the 200-day SMA, "
        "MACD histogram negative, AND 5-day momentum negative — the downtrend "
        "is no longer noise, it's structural"
    ),
    "macd_bearish_divergence": (
        "MACD bearish divergence (price up, MACD down) — common precursor "
        "to a top, often precedes a 5-10% pullback"
    ),
    "death_cross": (
        "Death cross (50-day SMA crossed below 200-day SMA) — bearish "
        "trend confirmation, historically a multi-week negative drift"
    ),
    "volume_dry": (
        "Volume drying up (z-score {z}) — low participation; rallies on "
        "thin volume rarely sustain"
    ),
    "rsi_overbought": (
        "RSI {rsi} (overbought) — short-term mean reversion likely"
    ),
    "bb_upper": (
        "Price at {pct}% of the upper Bollinger Band — statistically "
        "stretched, prone to revert toward the mean"
    ),
    "pe_rich": (
        "Stretched valuation (P/E {pe}) — limited margin of safety on "
        "any earnings or guidance miss"
    ),
    "eps_growth_negative": (
        "EPS growth is negative — earnings deteriorating, fundamental "
        "support is weakening"
    ),
    "high_debt": (
        "High leverage (debt/equity {de}) — sensitive to rate or earnings "
        "shocks"
    ),
    "rr_weak": (
        "Weak risk/reward ({rr}:1) — even if the trade works, the upside "
        "doesn't justify the risk taken"
    ),
    "regime_crisis": (
        "Market is in CRISIS regime — only the highest-conviction "
        "defensive plays should be considered"
    ),
    "iv_complacency": (
        "Options IV at {pct}th percentile (extreme complacency) — "
        "historically precedes vol expansion and downside"
    ),
    "vix_backwardation_stress": (
        "VIX term structure in backwardation (ratio {ratio}) — acute market stress, "
        "spot fear exceeds expected future fear, historically precedes 5-15% drawdowns"
    ),
    "yield_curve_inverted": (
        "Yield curve inverted (10Y-2Y spread: {spread}bp) — recession warning, "
        "historically preceded every US recession since 1970"
    ),
    "credit_spread_stress": (
        "Credit spreads elevated (BBB OAS: {spread}bp) — corporate bond market "
        "pricing elevated default risk, often leads equity declines by weeks"
    ),
}


def format_warning_signs(signal: dict) -> str:
    """Build the '## Warning Signs' section content for the synthesis prompt.

    Filters `signal_breakdown.compute_signal_breakdown()` output to
    TONE_NEGATIVE rules only, looks up each key's English template, and
    interpolates the label_value dict. Returns the joined warning lines
    (with bullet markers and the ⚠ prefix), or the literal string
    "None detected." if nothing fires — the caller embeds the result
    into a fixed prompt section, so a stable placeholder string is
    preferable to an empty section header.

    Args:
        signal: dict with at least `technical_data`, `fundamental_data`,
            and `grok_data` keys (matches what `compute_signal_breakdown`
            expects). Missing fields are tolerated.

    Returns:
        Multi-line string with one bullet per fired warning, or
        "None detected." when no rules fire.
    """
    rows = compute_signal_breakdown(signal)
    lines: list[str] = []
    for row in rows:
        if row.get("tone") != "negative":
            continue
        template = KEY_TO_PROMPT_TEXT.get(row["key"])
        if not template:
            continue  # rule fired but we have no English template — skip silently
        try:
            text = template.format(**(row.get("label_value") or {}))
        except (KeyError, IndexError):
            # Template expects a kwarg the rule didn't provide — fall back
            # to the raw template so we still surface the warning.
            text = template
        lines.append(f"- ⚠ {text}")
    if not lines:
        return "None detected."
    return "\n".join(lines)
