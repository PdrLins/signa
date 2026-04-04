"""All prompt templates and shared AI utilities."""


def clean_json_response(content: str) -> str:
    """Strip markdown code fences from an AI response."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
    return content.strip()

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
    "sentiment_weight": <0-100, how much sentiment influenced your decision>
}}

## Rules
- BUY: Strong conviction, favorable risk/reward, multiple confirming signals
- HOLD: Mixed signals, wait for confirmation
- SELL: Deteriorating conditions, high risk
- AVOID: Red flags, hostile conditions, or signal blockers detected
- Be especially cautious about fraud allegations, earnings misses, and hostile macro
- Factor in X/Twitter sentiment but don't let it dominate for safe income stocks
- For high risk stocks, sentiment and catalysts should weigh more heavily
- If you detect any red flags (fraud, SEC investigation, insider selling), bias toward AVOID

Return JSON only, no markdown formatting."""


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
