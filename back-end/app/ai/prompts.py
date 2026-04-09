"""All prompt templates and shared AI utilities."""


def clean_json_response(content: str) -> str:
    """Strip markdown code fences from an AI response."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    return content.strip()


def _safe_int(value: object, default: int = 0) -> int:
    """Safely cast to int, returning default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def synthesis_error_response(reason: str) -> dict:
    """Return the canonical "synthesis failed" dict.

    Used by all 3 AI clients (claude_client, claude_local_client,
    gemini_client) when their provider exhausts retries. Contains a safe
    HOLD signal so downstream code never crashes on missing fields, plus
    `error` set to the reason string so `_process_candidate` can classify
    the candidate as `ai_status="failed"` and route it through the tech-only
    Tier 3 entry path.

    Includes a `_present=False` self_check so the scan_service guard
    doesn't try to apply the structured contradiction check on a fallback
    response that has no real reasoning to check.
    """
    return {
        "signal": "HOLD",
        "confidence": 0,
        "reasoning": "Analysis temporarily unavailable",
        "risk_factors": [],
        "catalyst": None,
        "catalyst_date": None,
        "red_flags": [],
        "risk_reward_ratio": None,
        "target_price": None,
        "stop_loss": None,
        "sentiment_weight": 0,
        "self_check": normalize_self_check(None),
        "error": reason,
    }


def normalize_synthesis_result(data: dict) -> dict:
    """Normalize a raw parsed AI synthesis JSON into the canonical result dict.

    All 3 AI clients (claude_client, claude_local_client, gemini_client) used
    to build this dict inline with copy-pasted code. This helper is the single
    source of truth — adding a new field means editing here once.

    Side effects: validates `signal` against the allowed whitelist, coerces
    int fields, normalizes `self_check` via `normalize_self_check()`, and
    stamps `error: None` to indicate success.
    """
    raw_signal = (data.get("signal") or "HOLD").upper()
    if raw_signal not in ("BUY", "HOLD", "SELL", "AVOID"):
        raw_signal = "HOLD"

    return {
        "signal": raw_signal,
        "confidence": _safe_int(data.get("confidence"), 50),
        "reasoning": data.get("reasoning", ""),
        "risk_factors": data.get("risk_factors", []),
        "catalyst": data.get("catalyst"),
        "catalyst_date": data.get("catalyst_date"),
        "red_flags": data.get("red_flags", []),
        "risk_reward_ratio": data.get("risk_reward_ratio"),
        "target_price": data.get("target_price"),
        "stop_loss": data.get("stop_loss"),
        "sentiment_weight": _safe_int(data.get("sentiment_weight"), 0),
        "self_check": normalize_self_check(data.get("self_check")),
        "error": None,
    }


def normalize_self_check(raw: object) -> dict:
    """Coerce a raw `self_check` field from the AI response into a normalized dict.

    The AI is asked to return:
        {
          "reasoning_supports_signal": bool,
          "contains_wait_instruction": bool,
          "contains_bearish_descriptors": bool,
          "self_check_notes": str,
        }

    But providers can be sloppy: missing fields, string "true"/"false", null,
    or omit the block entirely. This helper returns a dict with all four keys
    always present so downstream code (scan_service guard) can read them
    without defensive checks at every call site.

    Conservative defaults when the AI omits the block:
        reasoning_supports_signal=True (don't auto-downgrade legacy / older
            providers that haven't been updated yet — they fall through to
            the regex backstop in scan_service)
        contains_wait_instruction=False
        contains_bearish_descriptors=False
        self_check_notes=""

    The `_present` flag tells the guard whether the AI actually returned
    a self_check block — when False, the regex backstop runs as a fallback.
    When True, the structured check is authoritative.
    """
    def _to_bool(v: object, default: bool) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "yes", "1", "t", "y")
        return default

    if not isinstance(raw, dict):
        return {
            "_present": False,
            "reasoning_supports_signal": True,
            "contains_wait_instruction": False,
            "contains_bearish_descriptors": False,
            "self_check_notes": "",
        }

    return {
        "_present": True,
        "reasoning_supports_signal": _to_bool(raw.get("reasoning_supports_signal"), True),
        "contains_wait_instruction": _to_bool(raw.get("contains_wait_instruction"), False),
        "contains_bearish_descriptors": _to_bool(raw.get("contains_bearish_descriptors"), False),
        "self_check_notes": str(raw.get("self_check_notes") or "")[:300],
    }

GROK_SENTIMENT_SYSTEM = """
You are a financial sentiment analyst specializing in X/Twitter data.
You MUST respond with valid JSON only.
No markdown, no code fences, no explanation — just the raw JSON object.
"""

GROK_SENTIMENT_PROMPT = """
Analyze recent X/Twitter posts about {ticker} from the last 48 hours.

Return this exact JSON structure:
{{
  "score": <0-100, where 0=very bearish, 50=neutral, 100=very bullish>,
  "label": <"bullish" | "neutral" | "bearish">,
  "confidence": <0-100>,
  "top_themes": ["theme1", "theme2", "theme3"],
  "breaking_news": "<string or null>",
  "notable_accounts": ["handle1", "handle2"],
  "summary": "<2 sentence max>"
}}
"""

CLAUDE_SYNTHESIS_PROMPT = """You are an AI investment analyst. Analyze the following data for {ticker} and produce a clear investment signal.

## Technical Indicators
{technicals}

## Fundamental Data
{fundamentals}

## Macro Environment
{macro}

## X/Twitter Sentiment (from Grok)
{sentiment}

## Options Flow (from Barchart)
{options_flow}

## Market Context
Current regime: {market_regime}
{regime_note}

## Catalyst Context
{catalyst_context}

## Investment Knowledge (from Signa Brain)
{knowledge_block}

## Warning Signs (from technical/fundamental analysis)
The brain has flagged the following danger signs in the data above. These are
not vetoes — you (Claude) are the decider. But they are surfaced here so you
cannot plausibly miss them when synthesizing your recommendation.
{warning_signs}

## Your Task
Based on ALL the data above, produce a JSON response with this exact structure:
{{
    "signal": "<BUY, HOLD, SELL, or AVOID>",
    "confidence": <0-100>,
    "reasoning": "<2-3 sentence explanation of your signal>",
    "risk_factors": ["<risk 1>", "<risk 2>"],
    "catalyst": "<upcoming catalyst event, or null>",
    "catalyst_date": "<YYYY-MM-DD if known, or null>",
    "red_flags": ["<any red flags detected>"],
    "risk_reward_ratio": <estimated risk/reward ratio as float, e.g. 2.5>,
    "target_price": <estimated target price, or null>,
    "stop_loss": <suggested stop loss price, or null>,
    "sentiment_weight": <0-100, how much sentiment influenced your decision>,
    "account_recommendation": "<RRSP or TFSA or TAXABLE>",
    "catalyst_type": "<PEAD or PRE_EARNINGS or DIVIDEND or OTHER or null>",
    "self_check": {{
        "reasoning_supports_signal": <true | false>,
        "contains_wait_instruction": <true | false>,
        "contains_bearish_descriptors": <true | false>,
        "self_check_notes": "<one sentence: if BUY, explicitly confirm reasoning is unambiguously bullish; otherwise explain the mismatch>"
    }}
}}

## Rules
- BUY: Strong conviction, favorable risk/reward, multiple confirming signals
- HOLD: Mixed signals, wait for confirmation
- SELL: Deteriorating conditions, high risk
- AVOID: Red flags, hostile conditions, or signal blockers detected

## Mandatory Self-Check Protocol (the LAST thing you do before returning JSON)

After drafting `reasoning` and `signal`, you MUST fill `self_check` honestly.
The downstream system uses these three booleans as the canonical contradiction
detector — they have hard, deterministic effects:

- If `reasoning_supports_signal` is **false** on a BUY → the BUY is
  automatically downgraded to HOLD by the system.
- If `contains_wait_instruction` is **true** on a BUY → automatic downgrade.
- If `contains_bearish_descriptors` is **true** on a BUY → automatic downgrade.

You are NOT being asked to lie. Answer honestly. Then, BEFORE finalizing the
`signal` field, change `signal` to HOLD if any of the above conditions hold,
so your output is internally consistent in the first place.

### Definitions

- **contains_wait_instruction** = true if your reasoning anywhere tells the
  reader to wait. Triggers: "wait for", "before considering entry", "before
  committing", "premature", "for a better entry", "wait for confirmation",
  "monitor before entering", "let it stabilize first", any synonym. False
  otherwise.

- **contains_bearish_descriptors** = true if your reasoning describes the
  SETUP itself using bearish words like: "falling knife", "downtrend",
  "deeply negative MACD", "technically stretched", "overextended", "rolled
  over", "no margin of safety", "decisively bearish", "momentum collapse",
  "bearish divergence", "structural weakness", any synonym. NOTE: bearish
  words appearing only in `risk_factors` (not in `reasoning`) do NOT count.
  This flag is about how you describe the *core setup*, not the disclaimers.

- **reasoning_supports_signal** = true only if a reader of your `reasoning`
  text alone (without ever seeing the `signal` field) would arrive at the
  SAME signal you chose. If a reader of the reasoning would conclude HOLD
  but you wrote BUY, this is FALSE.

### Failure examples (all of these MUST be HOLD, not BUY)

- "MACD is deeply negative... wait for momentum to flatten before entry" →
  wait_instruction=true, bearish_descriptors=true → HOLD
- "Stock is in a structural downtrend, but valuation is compelling" →
  bearish_descriptors=true → HOLD (put valuation in risk_factors as upside)
- "Technically stretched at 100% Bollinger Band, momentum has rolled over" →
  bearish_descriptors=true → HOLD
- "Forward P/E is attractive but the stock is a falling knife" →
  bearish_descriptors=true → HOLD

### Correct BUY example

```
{{
  "signal": "BUY",
  "reasoning": "MACD histogram just turned positive after 3 weeks of compression, RSI at 55 in the sweet spot, broke above SMA50 on 2.3x volume, and the earnings catalyst is 6 days away.",
  "self_check": {{
    "reasoning_supports_signal": true,
    "contains_wait_instruction": false,
    "contains_bearish_descriptors": false,
    "self_check_notes": "Reasoning is unambiguously bullish — momentum turn, healthy RSI, volume confirmation, near-term catalyst. No hedging language."
  }}
}}
```

A correctly-filled BUY must have all three booleans matching the example
above. If any of them are wrong, the system will downgrade and the trade
won't happen. Just write HOLD honestly when the setup isn't there.

- Be especially cautious about fraud allegations, earnings misses, and hostile macro
- Factor in X/Twitter sentiment but don't let it dominate for safe income stocks
- For high risk stocks, sentiment and catalysts should weigh more heavily
- When options flow data is available, use it to confirm or question the sentiment signal
- If sentiment and options flow agree (both bullish or both bearish), increase confidence
- If sentiment and options flow conflict, flag as uncertain and explain the divergence
- If you detect any red flags (fraud, SEC investigation, insider selling), bias toward AVOID
- In VOLATILE regime: be more conservative, raise conviction bar for BUY
- In CRISIS regime: only recommend BUY for dividend/income plays
- PEAD (post-earnings drift) and PRE_EARNINGS are mutually exclusive — never both
- For Canadian accounts: recommend RRSP for active trading, TFSA for dividend holds

Return JSON only, no markdown formatting."""


# ============================================================
# THESIS RE-EVALUATION PROMPT (Stage 6)
# ============================================================
#
# Used by `app/services/thesis_tracker.py` to ask Claude whether the
# original reason for a brain entry still holds. The output gates the
# THESIS_INVALIDATED exit and suppresses noise on the existing 6 exit
# paths.
#
# Design notes:
#   - Inputs are the FULL original thesis (Claude's verbatim reasoning at
#     entry) plus the structured snapshot of conditions at entry vs now.
#   - Output is JSON with status ('valid'|'weakening'|'invalid'),
#     confidence, reason, should_exit, and an updated thesis when the
#     reason has evolved but is still intact.
#   - The "Rules" section makes the principle explicit: a winning position
#     with a dead thesis must be exited; a losing position with an intact
#     thesis must be held. P&L direction does not determine the answer.

THESIS_REEVAL_PROMPT = """You are an AI investment analyst re-evaluating an OPEN brain position.

The brain bought {symbol} on {entry_date} ({days_held} days ago) at ${entry_price}.
Current price: ${current_price} (P&L: {pnl_pct:+.2f}%).

## Original Entry Thesis (verbatim from when we bought)
{entry_thesis}

## Conditions at Entry
{entry_conditions}

## Current Conditions
{current_conditions}

## Your Task
Determine whether the original thesis is still valid TODAY. Return JSON:

{{
  "status": "valid" | "weakening" | "invalid",
  "confidence": <0-100>,
  "reason": "<one paragraph: what changed (or didn't), and why this conclusion>",
  "should_exit": <true if status == "invalid", else false>,
  "current_thesis": "<if still valid: the updated thesis given today's data; if invalid: null>"
}}

## Rules
- "valid": the conditions and reasoning that justified entry are still in place
- "weakening": some conditions have degraded but the core reason still holds (HOLD, monitor closely)
- "invalid": the reason for owning is gone — even if the position is currently winning, the EDGE is gone
- A winning position with a dead thesis should be EXITED. We sold not because we're losing but because we no longer have a reason to be long.
- A losing position with an intact thesis should be HELD. The drawdown is noise.
- Be especially alert to:
  • Catalysts that have already played out (earnings beat, FDA approval, deal closed)
  • Macro shifts that change the regime (war ends, Fed pivots, recession averted)
  • Sentiment flips (bullish → bearish without our position recovering)
  • The thesis itself becoming the consensus (everyone's already long, no incremental buyers)
- P&L direction does NOT determine the answer. The thesis does.

Return JSON only, no markdown."""


def format_technicals(tech_data: dict) -> str:
    """Format technical data dict into readable prompt text."""
    lines = []
    if tech_data.get("current_price") is not None:
        lines.append(f"- Current Price: ${tech_data['current_price']:.2f}")
    if tech_data.get("rsi") is not None:
        lines.append(f"- RSI(14): {tech_data['rsi']:.1f}")
    if tech_data.get("macd") is not None:
        lines.append(f"- MACD: {tech_data['macd']:.4f} (Signal: {tech_data.get('macd_signal', 0):.4f}, Histogram: {tech_data.get('macd_histogram', 0):.4f})")
    if tech_data.get("bb_position") is not None:
        lines.append(f"- Bollinger Band Position: {tech_data['bb_position']:.2%} (Lower: ${tech_data.get('bb_lower', 0):.2f}, Upper: ${tech_data.get('bb_upper', 0):.2f})")
    if tech_data.get("sma_50") is not None:
        lines.append(f"- SMA 50: ${tech_data['sma_50']:.2f}")
    if tech_data.get("sma_200") is not None:
        lines.append(f"- SMA 200: ${tech_data['sma_200']:.2f}")
    sma_cross = tech_data.get("sma_cross", "none")
    if sma_cross != "none":
        lines.append(f"- SMA Cross: {sma_cross.replace('_', ' ').title()}")
    if tech_data.get("volume_zscore") is not None:
        lines.append(f"- Volume Z-Score: {tech_data['volume_zscore']:.2f} (Avg: {tech_data.get('volume_avg', 0):,.0f})")
    if tech_data.get("atr") is not None:
        lines.append(f"- ATR(14): {tech_data['atr']:.4f}")
    return "\n".join(lines) if lines else "No technical data available"


def format_fundamentals(fund_data: dict) -> str:
    """Format fundamental data dict into readable prompt text."""
    lines = []
    if fund_data.get("pe_ratio") is not None:
        lines.append(f"- P/E Ratio: {fund_data['pe_ratio']:.2f}")
    if fund_data.get("forward_pe") is not None:
        lines.append(f"- Forward P/E: {fund_data['forward_pe']:.2f}")
    if fund_data.get("eps") is not None:
        lines.append(f"- EPS: ${fund_data['eps']:.2f}")
    if fund_data.get("eps_growth") is not None:
        lines.append(f"- EPS Growth: {fund_data['eps_growth']:.1%}")
    if fund_data.get("dividend_yield") is not None:
        lines.append(f"- Dividend Yield: {fund_data['dividend_yield']:.2%}")
    if fund_data.get("payout_ratio") is not None:
        lines.append(f"- Payout Ratio: {fund_data['payout_ratio']:.1%}")
    if fund_data.get("debt_to_equity") is not None:
        lines.append(f"- Debt/Equity: {fund_data['debt_to_equity']:.2f}")
    if fund_data.get("market_cap") is not None:
        cap_b = fund_data["market_cap"] / 1e9
        lines.append(f"- Market Cap: ${cap_b:.1f}B")
    if fund_data.get("sector"):
        lines.append(f"- Sector: {fund_data['sector']}")
    if fund_data.get("earnings_date"):
        lines.append(f"- Next Earnings: {fund_data['earnings_date']}")
    return "\n".join(lines) if lines else "No fundamental data available"


def format_macro(macro_data: dict) -> str:
    """Format macro data dict into readable prompt text."""
    env = macro_data.get("environment", "unknown").upper()
    lines = [f"- Environment: {env}"]
    if macro_data.get("fed_funds_rate") is not None:
        lines.append(f"- Fed Funds Rate: {macro_data['fed_funds_rate']:.2f}%")
    if macro_data.get("treasury_10y") is not None:
        lines.append(f"- 10Y Treasury: {macro_data['treasury_10y']:.2f}%")
    if macro_data.get("cpi_yoy") is not None:
        lines.append(f"- CPI (YoY): {macro_data['cpi_yoy']:.1f}")
    if macro_data.get("unemployment_rate") is not None:
        lines.append(f"- Unemployment: {macro_data['unemployment_rate']:.1f}%")
    if macro_data.get("vix") is not None:
        lines.append(f"- VIX: {macro_data['vix']:.1f}")
    fg = macro_data.get("fear_greed")
    if fg and isinstance(fg, dict) and fg.get("score") is not None:
        lines.append(f"- Fear & Greed Index: {fg['score']:.0f}/100 ({fg.get('label', 'Unknown')})")
    pulse = macro_data.get("macro_pulse")
    if pulse and isinstance(pulse, dict) and pulse.get("trends"):
        lines.append(f"- Market Pulse: {pulse.get('summary', 'N/A')}")
        for trend in pulse["trends"][:3]:
            topic = trend.get("topic", "")
            impact = trend.get("impact", "NEUTRAL")
            lines.append(f"  * {topic} [{impact}]")
    return "\n".join(lines)


def format_sentiment(grok_data: dict) -> str:
    """Format Grok sentiment data into readable prompt text."""
    label = grok_data.get("label", "unknown").replace("_", " ").title()
    lines = [
        f"- Sentiment: {label} (score: {grok_data.get('score', 0):.2f})",
        f"- Confidence: {grok_data.get('confidence', 0):.0f}/100",
        f"- Summary: {grok_data.get('summary', 'N/A')}",
    ]
    themes = grok_data.get("top_themes", [])
    if themes:
        lines.append(f"- Top Themes: {', '.join(themes)}")
    news = grok_data.get("breaking_news")
    if news:
        lines.append(f"- Breaking News: {news}")
    accounts = grok_data.get("notable_accounts", [])
    if accounts:
        lines.append(f"- Notable Accounts: {', '.join(accounts)}")
    return "\n".join(lines)


def format_options_flow(grok_data: dict) -> str:
    """Format Barchart options flow data into readable prompt text."""
    flow = grok_data.get("_options_flow") if isinstance(grok_data, dict) else None
    if not flow or not isinstance(flow, dict):
        return "No options flow data available (ticker may be TSX, crypto, or data unavailable)"

    lines = []
    if flow.get("put_call_ratio") is not None:
        lines.append(f"- Put/Call Volume Ratio: {flow['put_call_ratio']}")
    if flow.get("iv_percentile") is not None:
        lines.append(f"- IV Percentile: {flow['iv_percentile']}%")
    if flow.get("options_volume") is not None:
        lines.append(f"- Today's Options Volume: {flow['options_volume']:,.0f}")
    if flow.get("options_volume_avg_30d") is not None:
        lines.append(f"- 30-Day Avg Options Volume: {flow['options_volume_avg_30d']:,.0f}")
    if flow.get("volume_vs_avg") is not None:
        lines.append(f"- Volume vs 30d Avg: {flow['volume_vs_avg']}x")
    if flow.get("signal"):
        lines.append(f"- Options Signal: {flow['signal'].upper()} (strength: {flow.get('signal_strength', 0)})")
    if flow.get("agreement_note"):
        lines.append(f"- Note: {flow['agreement_note']}")
    return "\n".join(lines) if lines else "No options flow data available"


def build_synthesis_prompt(
    ticker: str,
    technical_data: dict,
    fundamental_data: dict,
    macro_data: dict,
    grok_data: dict,
) -> str:
    """Build the full Claude synthesis prompt from the raw data dicts.

    Centralizes the prompt-prep boilerplate that was previously duplicated
    across all 3 AI clients (claude_client, claude_local_client, gemini_client).
    Each client now calls this ONE function instead of re-implementing:

        market_regime = grok_data.get(...) if isinstance(...) else ...
        signal_for_warnings = {"technical_data": ..., ...}
        CLAUDE_SYNTHESIS_PROMPT.format(ticker=..., technicals=..., ...)

    Adding a new prompt field (e.g., another evidence layer) now means
    editing THIS function, not hunting through 3 clients.

    Args:
        ticker: The symbol being analyzed.
        technical_data: Indicator output from `compute_indicators`.
        fundamental_data: Output from `market_scanner.get_fundamentals`.
        macro_data: Snapshot from `macro_scanner`.
        grok_data: Sentiment result + injected metadata (_market_regime,
            _regime_note, _catalyst_context, _knowledge_block, _options_flow).

    Returns:
        The fully-formatted `CLAUDE_SYNTHESIS_PROMPT` string, ready to
        pass to any AI client's API/subprocess call.
    """
    from app.ai.danger_signals import format_warning_signs

    is_dict = isinstance(grok_data, dict)
    market_regime = grok_data.get("_market_regime", "TRENDING") if is_dict else "TRENDING"
    regime_note = grok_data.get("_regime_note", "") if is_dict else ""
    catalyst_context = (
        grok_data.get("_catalyst_context", "No specific catalyst detected")
        if is_dict else "No specific catalyst detected"
    )
    knowledge_block = grok_data.get("_knowledge_block", "") if is_dict else ""

    # Build the signal-shaped dict that signal_breakdown expects so the
    # warning rules can fire on the same data Claude is about to see.
    # NOTE: `risk_reward` is None at this stage because Claude hasn't
    # produced target/stop yet. rr_weak/rr_strong rules are intentionally
    # inert via the warning_signs path — they still fire on the signal
    # detail page via compute_signal_breakdown directly.
    signal_for_warnings = {
        "technical_data": technical_data,
        "fundamental_data": fundamental_data,
        "grok_data": grok_data,
        "market_regime": market_regime,
        "risk_reward": None,
    }

    return CLAUDE_SYNTHESIS_PROMPT.format(
        ticker=ticker,
        technicals=format_technicals(technical_data),
        fundamentals=format_fundamentals(fundamental_data),
        macro=format_macro(macro_data),
        sentiment=format_sentiment(grok_data),
        options_flow=format_options_flow(grok_data),
        market_regime=market_regime,
        regime_note=regime_note,
        catalyst_context=catalyst_context,
        knowledge_block=knowledge_block,
        warning_signs=format_warning_signs(signal_for_warnings),
    )
