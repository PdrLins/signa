"""Evaluate backtest signals against actual future price movements."""

from dataclasses import asdict

import pandas as pd
from loguru import logger

from backtest.engine.simulator import SignalRecord


class BacktestEvaluator:

    def __init__(
        self,
        results: list[SignalRecord],
        price_data: dict[str, pd.DataFrame],
        eval_windows: list[int] | None = None,
    ):
        self.results = results
        self.price_data = price_data
        self.eval_windows = eval_windows or [5, 10, 20]

    def evaluate(self) -> list[dict]:
        """Evaluate each signal by measuring actual returns at 5/10/20 day windows.

        Returns list of dicts with all SignalRecord fields plus
        return_Xd and profitable_Xd for each window.
        """
        evaluated: list[dict] = []

        for i, record in enumerate(self.results):
            row = asdict(record)

            for window in self.eval_windows:
                future_price = self._get_future_price(
                    record.ticker, record.date, window,
                )

                if future_price is None:
                    row[f"return_{window}d"] = None
                    row[f"profitable_{window}d"] = None
                else:
                    return_pct = (
                        (future_price - record.price_at_signal)
                        / record.price_at_signal
                        * 100
                    )
                    row[f"return_{window}d"] = round(return_pct, 4)
                    row[f"profitable_{window}d"] = return_pct > 0

            evaluated.append(row)

            if (i + 1) % 500 == 0:
                logger.info(f"Evaluated {i + 1}/{len(self.results)} signals")

        logger.info(f"Evaluation complete: {len(evaluated)} signals evaluated")
        return evaluated

    def _get_future_price(
        self,
        ticker: str,
        signal_date: str,
        n_days: int,
    ) -> float | None:
        """Get the closing price n trading days after signal_date.

        Returns None if the ticker has fewer than n_days of data
        after the signal date.
        """
        df = self.price_data.get(ticker)
        if df is None or df.empty:
            return None

        ts = pd.Timestamp(signal_date)
        future = df[df.index > ts]

        if len(future) < n_days:
            return None

        return float(future.iloc[n_days - 1]["Close"])
