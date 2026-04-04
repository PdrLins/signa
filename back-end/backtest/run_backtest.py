"""Signa Backtest — entry point."""

import argparse
import copy
import time

from loguru import logger

from backtest.config import BACKTEST_CONFIG
from backtest.data.loader import DataLoader
from backtest.engine.simulator import BacktestSimulator
from backtest.evaluation.evaluator import BacktestEvaluator
from backtest.evaluation.metrics import compute_metrics
from backtest.reports.generator import save_results
from backtest.reports.summary import print_summary


def main():
    parser = argparse.ArgumentParser(description="Signa Backtest System")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip Claude API calls, use scorer only",
    )
    parser.add_argument(
        "--analyze", action="store_true",
        help="Run dry-run and generate Claude Code analysis file",
    )
    parser.add_argument(
        "--tickers", type=str,
        help="Comma-separated tickers e.g. AAPL,SHOP.TO",
    )
    parser.add_argument(
        "--start", type=str,
        help="Start date YYYY-MM-DD",
    )
    parser.add_argument(
        "--end", type=str,
        help="End date YYYY-MM-DD",
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Force fresh data pull from yfinance",
    )
    args = parser.parse_args()

    # Load config and apply CLI overrides
    config = copy.deepcopy(BACKTEST_CONFIG)

    if args.dry_run or args.analyze:
        config["dry_run"] = True

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
        us = [t for t in tickers if not t.endswith(".TO") and not t.endswith("-USD")]
        tsx = [t for t in tickers if t.endswith(".TO")]
        crypto = [t for t in tickers if t.endswith("-USD")]
        config["tickers"] = {"US": us, "TSX": tsx, "CRYPTO": crypto}

    if args.start:
        config["start_date"] = args.start
    if args.end:
        config["end_date"] = args.end

    if args.no_cache:
        config["use_cache"] = False

    # Count tickers
    all_tickers = (
        config["tickers"].get("US", [])
        + config["tickers"].get("TSX", [])
        + config["tickers"].get("CRYPTO", [])
    )
    us_count = len(config["tickers"].get("US", []))
    tsx_count = len(config["tickers"].get("TSX", []))
    crypto_count = len(config["tickers"].get("CRYPTO", []))

    logger.info("=" * 50)
    logger.info("💎 SIGNA BACKTEST")
    logger.info(f"Period: {config['start_date']} → {config['end_date']}")
    logger.info(f"Tickers: {len(all_tickers)} ({us_count} US + {tsx_count} TSX + {crypto_count} Crypto)")
    logger.info(f"Mode: {'DRY RUN (scorer only)' if config['dry_run'] else 'FULL (with Claude)'}")
    logger.info(f"Cache: {'ON' if config['use_cache'] else 'OFF'}")
    logger.info("=" * 50)

    start_time = time.time()

    # Step 1: Load data
    logger.info("Step 1/6: Loading market data...")
    loader = DataLoader(config)
    price_data = loader.load_all()

    if not price_data:
        logger.error("No price data loaded — aborting")
        return

    # Load fundamentals for each ticker
    fundamentals_data = {}
    for ticker in all_tickers:
        fundamentals_data[ticker] = loader.load_fundamentals(ticker)

    # Load macro (optional — continues without it)
    logger.info("Step 2/6: Loading macro data...")
    macro_data = loader.load_macro()

    # Step 2: Run simulation
    logger.info("Step 3/6: Running simulation...")
    simulator = BacktestSimulator(
        config=config,
        price_data=price_data,
        macro_data=macro_data,
        fundamentals_data=fundamentals_data,
    )
    results = simulator.run()

    if not results:
        logger.warning("No signals generated — check data and config")
        return

    # Step 3: Evaluate
    logger.info("Step 4/6: Evaluating signals against actual returns...")
    evaluator = BacktestEvaluator(
        results=results,
        price_data=price_data,
        eval_windows=config.get("eval_windows", [5, 10, 20]),
    )
    evaluated = evaluator.evaluate()

    # Step 4: Compute metrics
    logger.info("Step 5/6: Computing metrics...")
    metrics = compute_metrics(evaluated)

    # Step 5: Print summary
    print_summary(metrics, config)

    # Step 6: Save files
    logger.info("Step 6/6: Saving output files...")
    saved_files = save_results(evaluated, metrics, config)

    # Done
    elapsed = round(time.time() - start_time, 1)
    logger.info(f"Backtest complete in {elapsed}s")
    logger.info(f"Output files ({len(saved_files)}):")
    for f in saved_files:
        logger.info(f"  📄 {f}")


if __name__ == "__main__":
    main()
