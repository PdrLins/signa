"""Plain-English breakdown of why a signal looks the way it does.

Pure rules engine — takes a signal row (with `technical_data`,
`fundamental_data`, `grok_data`, `risk_reward`, `market_regime`) and returns
a list of "rows" describing each notable feature of the signal in
language a non-quant can understand.

The frontend renders the rows into a table:

    | Signal              | What it means                          | Why it matters                          |
    |---------------------|----------------------------------------|-----------------------------------------|
    | Bollinger upper 96% | Price at the top of its 2σ envelope    | Statistically stretched — prone to mean revert |
    | P/E 49.7            | ~50× earnings                          | Rich valuation, little margin for a miss        |
    | R/R 1.8             | Below the 2.0 floor the brain wants    | Even if it works, payoff doesn't justify risk   |

Design notes:
  - Pure function, no DB calls, no side effects. Sub-millisecond per signal.
  - Locale-agnostic: returns i18n KEYS (not English strings) so the frontend
    can render them in EN or PT via the existing useI18nStore. Each row is:

        {
            "key": "bb_upper",                   # i18n lookup key root
            "label_value": {"pct": 96},          # interpolation vars for label
            "tone": "negative",                  # positive | negative | neutral
        }

    The frontend looks up `t.signal.breakdown.bb_upper.label`,
    `.what`, and `.why`, and interpolates `{pct}` into the label.

  - Each rule is self-contained — to add a new one, append to the
    `RULES` list below. To remove one, delete it. No order dependency
    except: rules are evaluated in list order, and the output preserves
    that order so the most-important rules can be listed first.

  - Coverage is best-effort: a signal that's missing fields will simply
    skip those rules. Don't crash on missing data.
"""

from __future__ import annotations

from typing import Any, Callable, Optional


# Tone tags. The frontend uses these to color the row icon.
TONE_POSITIVE = "positive"
TONE_NEGATIVE = "negative"
TONE_NEUTRAL = "neutral"


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        # NaN check
        if f != f:
            return None
        return f
    except (TypeError, ValueError):
        return None


def _norm_pct(raw: Optional[float], decimal_threshold: float) -> Optional[float]:
    """Normalize a value to PERCENT form, auto-detecting decimal vs percent.

    yfinance stores some fields inconsistently across tickers — for example
    one stock's `dividend_yield` arrives as `0.0385` (decimal, meaning 3.85%)
    and another's as `0.46` (percent already, meaning 0.46%). We use a
    field-appropriate threshold to decide which form a given value is in:

      - **Yields** (`dividend_yield`): use `decimal_threshold=0.1`. Real
        dividend yields are virtually never below 10% in percent form,
        and decimal-form yields are virtually always below 0.1 (10%).
        A value of `0.46` correctly resolves to 0.46% (percent form);
        `0.0385` correctly resolves to 3.85% (decimal form ×100).

      - **Growth rates** (`eps_growth`, `revenue_growth`): use
        `decimal_threshold=3.0`. Growth values can plausibly reach
        100%+ in decimal form (1.0 = 100%), so the threshold has to be
        higher. A value of `0.37` resolves to 37%; `9.48` resolves to
        9.48%.

    Returns the normalized value in percent units, or None if input is None.
    Edge cases at the boundary (yield ≈ 0.1, growth ≈ 3.0) may misclassify;
    we accept that since both rules deliberately omit the number from the
    rendered label and stay qualitative.
    """
    if raw is None:
        return None
    return raw * 100 if abs(raw) < decimal_threshold else raw


# Rule definition: each entry is a dict with:
#   key:          i18n lookup root (e.g., "bb_upper")
#   tone:         positive | negative | neutral
#   fires:        (sig, tech, fund, opts) -> bool
#   label_value:  (sig, tech, fund, opts) -> dict | None
#                 — interpolation vars for the label template; None for static labels
RuleFn = Callable[[dict, dict, dict, dict], Any]


def _rule(key: str, tone: str, fires: RuleFn, label_value: Optional[RuleFn] = None) -> dict:
    return {"key": key, "tone": tone, "fires": fires, "label_value": label_value}


RULES: list[dict] = [
    # ── Technical: price location ──
    _rule(
        "bb_upper", TONE_NEGATIVE,
        fires=lambda s, t, f, o: (_safe_float(t.get("bb_position")) or 0) > 0.85,
        label_value=lambda s, t, f, o: {"pct": round((_safe_float(t.get("bb_position")) or 0) * 100)},
    ),
    _rule(
        "bb_lower", TONE_POSITIVE,
        fires=lambda s, t, f, o: 0 < (_safe_float(t.get("bb_position")) or 1) < 0.15,
        label_value=lambda s, t, f, o: {"pct": round((_safe_float(t.get("bb_position")) or 0) * 100)},
    ),

    # ── Technical: RSI bands ──
    _rule(
        "rsi_overbought", TONE_NEGATIVE,
        fires=lambda s, t, f, o: (_safe_float(t.get("rsi")) or 0) > 70,
        label_value=lambda s, t, f, o: {"rsi": round(_safe_float(t.get("rsi")) or 0)},
    ),
    _rule(
        "rsi_oversold", TONE_NEUTRAL,  # neutral because oversold can stay oversold (falling knife)
        fires=lambda s, t, f, o: 0 < (_safe_float(t.get("rsi")) or 0) < 30,
        label_value=lambda s, t, f, o: {"rsi": round(_safe_float(t.get("rsi")) or 0)},
    ),
    _rule(
        "rsi_sweet_spot", TONE_POSITIVE,
        fires=lambda s, t, f, o: 50 <= (_safe_float(t.get("rsi")) or 0) <= 65,
        label_value=lambda s, t, f, o: {"rsi": round(_safe_float(t.get("rsi")) or 0)},
    ),

    # ── Technical: MACD ──
    _rule(
        "macd_bullish", TONE_POSITIVE,
        fires=lambda s, t, f, o: (
            _safe_float(t.get("macd")) is not None
            and _safe_float(t.get("macd_signal")) is not None
            and (_safe_float(t.get("macd")) or 0) > (_safe_float(t.get("macd_signal")) or 0)
            and (_safe_float(t.get("macd_histogram")) or 0) > 0
        ),
    ),
    _rule(
        "macd_bearish_divergence", TONE_NEGATIVE,
        fires=lambda s, t, f, o: (
            (_safe_float(t.get("macd_histogram")) or 0) < -0.3
            and (_safe_float(t.get("momentum_5d")) or 0) > 2
        ),
    ),

    # ── Technical: volume ──
    _rule(
        "volume_surge", TONE_POSITIVE,
        fires=lambda s, t, f, o: (_safe_float(t.get("volume_zscore")) or 0) > 2,
        label_value=lambda s, t, f, o: {"z": round(_safe_float(t.get("volume_zscore")) or 0, 1)},
    ),
    _rule(
        "volume_dry", TONE_NEGATIVE,
        fires=lambda s, t, f, o: (_safe_float(t.get("volume_zscore")) or 0) < -1.5,
        label_value=lambda s, t, f, o: {"z": round(_safe_float(t.get("volume_zscore")) or 0, 1)},
    ),

    # ── Technical: trend ──
    _rule(
        "strong_trend", TONE_POSITIVE,
        fires=lambda s, t, f, o: (_safe_float(t.get("adx")) or 0) > 25,
        label_value=lambda s, t, f, o: {"adx": round(_safe_float(t.get("adx")) or 0)},
    ),
    _rule(
        "golden_cross", TONE_POSITIVE,
        fires=lambda s, t, f, o: t.get("sma_cross") == "golden",
    ),
    _rule(
        "death_cross", TONE_NEGATIVE,
        fires=lambda s, t, f, o: t.get("sma_cross") == "death",
    ),

    # ── Fundamental: valuation ──
    _rule(
        "pe_rich", TONE_NEGATIVE,
        fires=lambda s, t, f, o: (_safe_float(f.get("pe_ratio")) or 0) > 35,
        label_value=lambda s, t, f, o: {"pe": round(_safe_float(f.get("pe_ratio")) or 0, 1)},
    ),
    _rule(
        "pe_cheap", TONE_POSITIVE,
        fires=lambda s, t, f, o: 0 < (_safe_float(f.get("pe_ratio")) or 0) < 12,
        label_value=lambda s, t, f, o: {"pe": round(_safe_float(f.get("pe_ratio")) or 0, 1)},
    ),

    # ── Fundamental: growth ──
    # Note: eps_growth and revenue_growth are stored inconsistently across
    # tickers (some decimal, some percent — yfinance quirk). We normalize
    # for the THRESHOLD check but DO NOT pass a number into label_value,
    # so the rendered label stays qualitative ("Strong EPS growth") and
    # never shows a wrong figure.
    _rule(
        "eps_growth_strong", TONE_POSITIVE,
        fires=lambda s, t, f, o: (_norm_pct(_safe_float(f.get("eps_growth")), 3.0) or 0) > 15,
    ),
    _rule(
        "eps_growth_negative", TONE_NEGATIVE,
        fires=lambda s, t, f, o: (_norm_pct(_safe_float(f.get("eps_growth")), 3.0) or 0) < 0,
    ),
    _rule(
        "revenue_growth_strong", TONE_POSITIVE,
        fires=lambda s, t, f, o: (_norm_pct(_safe_float(f.get("revenue_growth")), 3.0) or 0) > 15,
    ),

    # ── Fundamental: balance sheet ──
    _rule(
        "high_debt", TONE_NEGATIVE,
        fires=lambda s, t, f, o: (_safe_float(f.get("debt_to_equity")) or 0) > 100,
        label_value=lambda s, t, f, o: {"de": round(_safe_float(f.get("debt_to_equity")) or 0)},
    ),

    # ── Fundamental: yield (especially relevant for SAFE_INCOME) ──
    # dividend_yield has the same decimal/percent inconsistency as growth
    # rates above. We normalize for the threshold and skip the number in
    # the label.
    _rule(
        "dividend_attractive", TONE_POSITIVE,
        fires=lambda s, t, f, o: (_norm_pct(_safe_float(f.get("dividend_yield")), 0.1) or 0) > 3,
    ),

    # ── Signal-level ──
    _rule(
        "rr_strong", TONE_POSITIVE,
        fires=lambda s, t, f, o: (_safe_float(s.get("risk_reward")) or 0) >= 3,
        label_value=lambda s, t, f, o: {"rr": round(_safe_float(s.get("risk_reward")) or 0, 1)},
    ),
    _rule(
        "rr_weak", TONE_NEGATIVE,
        fires=lambda s, t, f, o: 0 < (_safe_float(s.get("risk_reward")) or 0) < 2,
        label_value=lambda s, t, f, o: {"rr": round(_safe_float(s.get("risk_reward")) or 0, 1)},
    ),

    # ── Regime ──
    _rule(
        "regime_volatile", TONE_NEUTRAL,
        fires=lambda s, t, f, o: s.get("market_regime") == "VOLATILE",
    ),
    _rule(
        "regime_crisis", TONE_NEGATIVE,
        fires=lambda s, t, f, o: s.get("market_regime") == "CRISIS",
    ),

    # ── Options flow (from grok_data._options_flow) ──
    _rule(
        "iv_complacency", TONE_NEGATIVE,
        fires=lambda s, t, f, o: 0 < (_safe_float(o.get("iv_percentile")) or 100) < 5,
        label_value=lambda s, t, f, o: {"pct": round(_safe_float(o.get("iv_percentile")) or 0, 1)},
    ),
    _rule(
        "iv_panic", TONE_NEUTRAL,
        fires=lambda s, t, f, o: (_safe_float(o.get("iv_percentile")) or 0) > 95,
        label_value=lambda s, t, f, o: {"pct": round(_safe_float(o.get("iv_percentile")) or 0)},
    ),

    # ── 52-week range proximity ──
    _rule(
        "near_52w_high", TONE_NEUTRAL,
        fires=lambda s, t, f, o: (
            _safe_float(f.get("regular_market_price")) is not None
            and _safe_float(f.get("52w_high")) is not None
            and (_safe_float(f.get("regular_market_price")) or 0) >= 0.95 * (_safe_float(f.get("52w_high")) or 1)
        ),
    ),
    _rule(
        "near_52w_low", TONE_POSITIVE,
        fires=lambda s, t, f, o: (
            _safe_float(f.get("regular_market_price")) is not None
            and _safe_float(f.get("52w_low")) is not None
            and (_safe_float(f.get("regular_market_price")) or 0) <= 1.05 * (_safe_float(f.get("52w_low")) or 0)
        ),
    ),
]


def compute_signal_breakdown(signal: dict) -> list[dict]:
    """Return the plain-English breakdown rows for a signal.

    Pure function — no DB calls, no AI calls, no side effects. Each row:

        {
            "key": "bb_upper",                   # i18n root key
            "tone": "positive"|"negative"|"neutral",
            "label_value": {"pct": 96} | None,   # interpolation params
        }

    Empty list if no rules fire (e.g., a signal with no technical data,
    or a perfectly average signal that doesn't trip any threshold).
    """
    if not signal:
        return []

    technical = signal.get("technical_data") or {}
    fundamental = signal.get("fundamental_data") or {}
    grok = signal.get("grok_data") or {}
    options = (grok.get("_options_flow") or {}) if isinstance(grok, dict) else {}

    if not isinstance(technical, dict):
        technical = {}
    if not isinstance(fundamental, dict):
        fundamental = {}
    if not isinstance(options, dict):
        options = {}

    rows: list[dict] = []
    for rule in RULES:
        try:
            if rule["fires"](signal, technical, fundamental, options):
                row = {
                    "key": rule["key"],
                    "tone": rule["tone"],
                }
                if rule["label_value"] is not None:
                    row["label_value"] = rule["label_value"](signal, technical, fundamental, options)
                rows.append(row)
        except Exception:
            # Defensive: a single broken rule should never blow up the whole
            # detail page. Skip and continue.
            continue

    return rows
