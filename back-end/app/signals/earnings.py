"""Earnings-based signals — PEAD (Post-Earnings Announcement Drift).

Stocks continue drifting in the direction of an earnings surprise for 20-60 days.
This is one of the most documented anomalies in finance (3-7% annual alpha).
"""

import asyncio
from datetime import date, timedelta

import yfinance as yf
from loguru import logger


async def get_earnings_context(ticker: str) -> dict:
    """Get earnings context for a ticker — surprise, drift potential, upcoming dates.

    Returns dict with:
    - days_since_earnings: days since last earnings report
    - earnings_surprise_pct: last EPS surprise as percentage
    - drift_signal: POSITIVE_DRIFT / NEGATIVE_DRIFT / NONE
    - drift_score: 0-20 bonus points for scoring
    - next_earnings_date: ISO date string or None
    - days_to_earnings: days until next earnings
    - pre_earnings_flag: True if earnings within 7 days (reduce position size)
    """
    def _fetch():
        try:
            t = yf.Ticker(ticker)

            result = {
                "days_since_earnings": None,
                "earnings_surprise_pct": None,
                "drift_signal": "NONE",
                "drift_score": 0,
                "next_earnings_date": None,
                "days_to_earnings": None,
                "pre_earnings_flag": False,
            }

            # Get earnings history
            try:
                earnings = t.earnings_dates
                if earnings is not None and not earnings.empty:
                    # Find most recent past earnings
                    today = date.today()
                    past_earnings = earnings[earnings.index.date <= today]

                    if not past_earnings.empty:
                        last_date = past_earnings.index[0].date()
                        result["days_since_earnings"] = (today - last_date).days

                        # EPS surprise
                        surprise_col = [c for c in past_earnings.columns if 'surprise' in c.lower() or 'diff' in c.lower()]
                        eps_col = [c for c in past_earnings.columns if 'eps' in c.lower() and 'estimate' not in c.lower()]
                        est_col = [c for c in past_earnings.columns if 'estimate' in c.lower()]

                        if surprise_col:
                            surprise = past_earnings[surprise_col[0]].iloc[0]
                            if surprise is not None and not (hasattr(surprise, '__float__') and str(surprise) == 'nan'):
                                result["earnings_surprise_pct"] = round(float(surprise), 2)
                        elif eps_col and est_col:
                            actual = past_earnings[eps_col[0]].iloc[0]
                            estimate = past_earnings[est_col[0]].iloc[0]
                            if actual is not None and estimate is not None and estimate != 0:
                                surprise_pct = ((float(actual) - float(estimate)) / abs(float(estimate))) * 100
                                result["earnings_surprise_pct"] = round(surprise_pct, 2)

                        # PEAD drift signal
                        days = result["days_since_earnings"]
                        surprise = result["earnings_surprise_pct"]
                        if days is not None and surprise is not None and days <= 40:
                            if surprise > 5:
                                result["drift_signal"] = "POSITIVE_DRIFT"
                                result["drift_score"] = min(15, int(surprise * 0.5))
                            elif surprise > 2:
                                result["drift_signal"] = "POSITIVE_DRIFT"
                                result["drift_score"] = 5
                            elif surprise < -5:
                                result["drift_signal"] = "NEGATIVE_DRIFT"
                                result["drift_score"] = 0  # No bonus for negative
                            elif surprise < -2:
                                result["drift_signal"] = "NEGATIVE_DRIFT"
                                result["drift_score"] = 0

                    # Next earnings date
                    future_earnings = earnings[earnings.index.date > today]
                    if not future_earnings.empty:
                        next_date = future_earnings.index[-1].date()
                        result["next_earnings_date"] = next_date.isoformat()
                        result["days_to_earnings"] = (next_date - today).days
                        result["pre_earnings_flag"] = result["days_to_earnings"] <= 7
            except Exception as e:
                logger.debug(f"Earnings data unavailable for {ticker}: {e}")

            return result

        except Exception as e:
            logger.debug(f"Earnings context failed for {ticker}: {e}")
            return {
                "days_since_earnings": None,
                "earnings_surprise_pct": None,
                "drift_signal": "NONE",
                "drift_score": 0,
                "next_earnings_date": None,
                "days_to_earnings": None,
                "pre_earnings_flag": False,
            }

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.debug(f"Earnings context thread failed for {ticker}: {e}")
        return {"drift_signal": "NONE", "drift_score": 0, "pre_earnings_flag": False}
