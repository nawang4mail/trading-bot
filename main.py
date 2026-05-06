"""
Trading bot entry point.

Usage:
    python main.py

Configure via .env (copy .env.example → .env and fill in your Alpaca keys).
Tune strategy/risk settings live via the UI — changes apply on the next bar.
"""

import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

import pandas as pd

import config
from data.market_data import MarketDataFeed
from execution.orders import OrderManager
from strategy.strategy import EMACrossoverStrategy, Signal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SIGNAL_LOG = Path("logs/signals.jsonl")
SIGNAL_LOG.parent.mkdir(exist_ok=True)

order_mgr = OrderManager()
strategy = EMACrossoverStrategy()


def _log_signal(symbol: str, signal_value: str, short_ema: float, long_ema: float,
                rsi: float, volume_ratio: float = 0.0, trend_ema: float = 0.0,
                macd: float = 0.0, macd_signal: float = 0.0):
    entry = {
        "time":         pd.Timestamp.now().isoformat(),
        "symbol":       symbol,
        "signal":       signal_value,
        "short_ema":    round(short_ema, 4),
        "long_ema":     round(long_ema, 4),
        "rsi":          round(rsi, 1),
        "volume_ratio": round(volume_ratio, 2),
        "trend_ema":    round(trend_ema, 4),
        "macd":         round(macd, 4),
        "macd_signal":  round(macd_signal, 4),
    }
    with SIGNAL_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


async def on_bar(symbol: str, df: pd.DataFrame):
    # Pick up any settings changes saved from the UI
    config.maybe_reload()

    if not order_mgr.is_market_open():
        return

    # Check stop-loss before evaluating new signals
    if order_mgr.check_stop_loss(symbol):
        _log_signal(symbol, "stop_loss", 0.0, 0.0, 0.0)
        return

    result = strategy.evaluate(symbol, df)

    if result.signal != Signal.HOLD:
        _log_signal(symbol, result.signal.value, result.short_ema, result.long_ema,
                    result.rsi, result.volume_ratio, result.trend_ema,
                    result.macd, result.macd_signal_val)

    if result.signal == Signal.BUY:
        order_mgr.buy(symbol)
    elif result.signal == Signal.SELL:
        order_mgr.sell(symbol)


async def main():
    mode = "PAPER" if config.PAPER else "LIVE"
    logger.info("Starting trading bot | mode=%s | symbols=%s", mode, config.SYMBOLS)

    feed = MarketDataFeed(on_bar=on_bar)
    feed.load_history(config.SYMBOLS)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(_shutdown()))

    await feed.run(config.SYMBOLS)


async def _shutdown():
    logger.info("Shutdown signal received. Closing all positions...")
    order_mgr.close_all_positions()
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
