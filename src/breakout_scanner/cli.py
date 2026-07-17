from __future__ import annotations

import argparse
import asyncio
import json
import logging

import pandas as pd

from .backtest import run_backtest
from .config import Settings
from .models import SymbolRules
from .scanner import Scanner


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper-only breakout/retest scanner")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("once")
    sub.add_parser("run")
    backtest = sub.add_parser("backtest")
    backtest.add_argument("csv")
    backtest.add_argument("--symbol", default="BTCUSDT")
    backtest.add_argument("--tick-size", type=float, default=0.1)
    backtest.add_argument("--step-size", type=float, default=0.001)
    backtest.add_argument("--min-notional", type=float, default=5.0)
    args = parser.parse_args()
    cfg = Settings()
    logging.basicConfig(level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.command in {"once", "run"}:
        scanner = Scanner(cfg)
        asyncio.run(scanner.once() if args.command == "once" else scanner.run())
    else:
        raw = pd.read_csv(args.csv, parse_dates=["open_time", "close_time"])
        trades, metrics = run_backtest(raw, args.symbol, SymbolRules(args.tick_size, args.step_size, args.min_notional), cfg)
        trades.to_csv("backtest_trades.csv", index=False)
        print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()

