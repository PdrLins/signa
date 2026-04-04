"""Backtest simulator — runs signals across all tickers and trading days."""

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from loguru import logger

from backtest.engine.fundamentals import classify_bucket, extract_fundamentals
from backtest.engine.indicators import compute_indicators
from backtest.engine.scorer import (
    check_gem_conditions,
    determine_signal,
    score_high_risk,
    score_safe_income,
)


@dataclass
class SignalRecord:
    ticker: str
    date: str
    bucket: str
    signal: str
    score: float
    confidence: float
    price_at_signal: float
    components: dict
    reasoning: str
    stop_loss_pct: float
    target_pct: float
    risk_reward: float
    is_gem: bool
    gem_reason: Optional[str]
    indicators_snapshot: dict
    fundamentals_snapshot: dict


class BacktestSimulator:

    def __init__(
        self,
        config: dict,
        price_data: dict[str, pd.DataFrame],
        macro_data: dict[str, pd.DataFrame],
        fundamentals_data: dict[str, dict] | None = None,
    ):
        self.config = config
        self.price_data = price_data
        self.macro_data = macro_data
        self.fundamentals_data = fundamentals_data or {}
        self.results: list[SignalRecord] = []

    def run(self) -> list[SignalRecord]:
        """Run the full backtest simulation across all tickers and days."""
        all_tickers = (
            self.config["tickers"].get("US", [])
            + self.config["tickers"].get("TSX", [])
            + self.config["tickers"].get("CRYPTO", [])
        )

        trading_days = self._get_trading_days()
        if not trading_days:
            logger.error("No trading days found — cannot run simulation")
            return []

        total_days = len(trading_days)
        logger.info(
            f"Starting simulation: {len(all_tickers)} tickers x "
            f"{total_days} days ({trading_days[0]} → {trading_days[-1]})"
        )

        for day_num, date in enumerate(trading_days, 1):
            day_signals = 0

            for ticker in all_tickers:
                record = self._process_ticker(ticker, date)
                if record:
                    self.results.append(record)
                    day_signals += 1

            if day_num % 10 == 0:
                logger.info(
                    f"Progress: {day_num}/{total_days} days — "
                    f"{len(self.results)} signals so far"
                )

        logger.info(
            f"Simulation complete: {len(self.results)} total signals "
            f"across {total_days} days"
        )
        return self.results

    def _process_ticker(self, ticker: str, date: str) -> SignalRecord | None:
        """Process a single ticker on a single day.

        Returns a SignalRecord if the ticker produces a meaningful signal,
        or None if data is missing, indicators fail, or score is too low.
        """
        try:
            # 1. Get price data
            df = self.price_data.get(ticker)
            if df is None or df.empty:
                return None

            # 2. Compute indicators (sliced to date, no look-ahead)
            indicators = compute_indicators(df, date)
            if indicators is None:
                return None

            # 3. Get fundamentals
            raw_fundamentals = self.fundamentals_data.get(ticker, {})
            fundamentals = extract_fundamentals(raw_fundamentals)

            # 4. Classify bucket
            bucket = classify_bucket(fundamentals)

            # 5. Get macro snapshot for this date
            macro_snapshot = self._get_macro_snapshot(date)

            # 6. Score based on bucket
            if bucket == "SAFE_INCOME":
                score_result = score_safe_income(indicators, fundamentals, macro_snapshot)
            else:
                score_result = score_high_risk(indicators, fundamentals, macro_snapshot)

            score = score_result["total_score"]

            # 7. Pre-filter: skip low scores
            if score < 40:
                return None

            # 8. Determine signal (bucket-aware thresholds)
            signal = determine_signal(score, bucket, self.config.get("signal_thresholds"))

            # 9. Check GEM conditions
            is_gem, gem_reason = check_gem_conditions(score_result, indicators, fundamentals)

            # 10. Calculate stop loss, target, risk/reward
            atr = indicators.get("atr") or 0
            close = indicators.get("close") or 1
            stop_loss_pct = (atr / close) * 100 * 2
            risk_reward_proxy = 2.0
            if is_gem:
                risk_reward_proxy = 3.0
            elif signal == "BUY":
                risk_reward_proxy = 2.5
            target_pct = stop_loss_pct * risk_reward_proxy
            risk_reward = (target_pct / stop_loss_pct) if stop_loss_pct > 0 else 0

            # 11. Build reasoning string
            components = score_result["components"]
            top_component = max(components, key=components.get)
            reasoning = (
                f"{signal} signal (score {score:.0f}) driven by "
                f"{top_component} ({components[top_component]:.0f}). "
                f"RSI {indicators['rsi']:.0f}, "
                f"MACD {'bullish' if indicators['macd_line'] > indicators['macd_signal'] else 'bearish'}."
            )

            return SignalRecord(
                ticker=ticker,
                date=date,
                bucket=bucket,
                signal=signal,
                score=score,
                confidence=min(score, 95.0),
                price_at_signal=indicators["close"],
                components=components,
                reasoning=reasoning,
                stop_loss_pct=round(stop_loss_pct, 4),
                target_pct=round(target_pct, 4),
                risk_reward=round(risk_reward, 2),
                is_gem=is_gem,
                gem_reason=gem_reason,
                indicators_snapshot=indicators,
                fundamentals_snapshot=fundamentals,
            )

        except Exception as e:
            logger.debug(f"Skipped {ticker} on {date}: {e}")
            return None

    def _get_macro_snapshot(self, date: str) -> dict:
        """Get the most recent macro values available as of date (no look-ahead).

        Returns dict with fed_rate, cpi, vix, fed_funds_rate (DataFrame slice for scorer),
        and fed_trend ("rising", "falling", "stable").
        """
        ts = pd.Timestamp(date)
        snapshot: dict = {}

        # Extract latest value as of date for each series
        for key, series_name in [("fed_rate", "fed_funds_rate"), ("cpi", "cpi"), ("vix", "vix")]:
            df = self.macro_data.get(series_name)
            if df is not None and not df.empty:
                available = df[df.index <= ts]
                if not available.empty:
                    val = available.iloc[-1, 0]
                    snapshot[key] = float(val) if pd.notna(val) else None
                else:
                    snapshot[key] = None
            else:
                snapshot[key] = None

        # Fed trend: compare current vs 30 days ago
        ff_df = self.macro_data.get("fed_funds_rate")
        if ff_df is not None and not ff_df.empty:
            available = ff_df[ff_df.index <= ts]
            if len(available) >= 5:
                # Pass the sliced DataFrame for scorer's _score_macro
                snapshot["fed_funds_rate"] = available.iloc[:, 0]

                current = float(available.iloc[-1, 0])
                past_30 = available[available.index <= ts - pd.Timedelta(days=30)]
                if not past_30.empty:
                    earlier = float(past_30.iloc[-1, 0])
                    diff = current - earlier
                    if diff < -0.1:
                        snapshot["fed_trend"] = "falling"
                    elif diff > 0.1:
                        snapshot["fed_trend"] = "rising"
                    else:
                        snapshot["fed_trend"] = "stable"
                else:
                    snapshot["fed_trend"] = "stable"
            else:
                snapshot["fed_trend"] = "stable"
        else:
            snapshot["fed_trend"] = "stable"

        return snapshot

    def _get_trading_days(self) -> list[str]:
        """Get trading days from the price data (using first available ticker)."""
        # Use AAPL as reference, fall back to first available ticker
        ref_ticker = "AAPL"
        if ref_ticker not in self.price_data:
            if not self.price_data:
                return []
            ref_ticker = next(iter(self.price_data))

        df = self.price_data[ref_ticker]
        start = pd.Timestamp(self.config["start_date"])
        end = pd.Timestamp(self.config["end_date"])

        mask = (df.index >= start) & (df.index <= end)
        days = [d.strftime("%Y-%m-%d") for d in df.index[mask]]
        return days
