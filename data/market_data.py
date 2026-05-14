import asyncio
import logging
from collections import defaultdict, deque
from typing import Callable

import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

import config

logger = logging.getLogger(__name__)


class MarketDataFeed:
    """Manages historical data loading and real-time bar streaming via WebSocket."""

    def __init__(self, on_bar: Callable):
        self._on_bar = on_bar
        self._hist_client = StockHistoricalDataClient(config.API_KEY, config.API_SECRET)
        self._stream = StockDataStream(config.API_KEY, config.API_SECRET)
        self._bars: dict[str, deque] = defaultdict(self._make_deque)
        self._subscribed: set[str] = set()

    def _make_deque(self):
        # Large enough for 200 EMA + buffer
        return deque(maxlen=max(config.LONG_WINDOW * 3, config.TREND_EMA + 50))

    def load_history(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        """Fetch recent 1-minute bars to seed all indicators before live trading starts."""
        limit = max(config.LONG_WINDOW * 3, config.TREND_EMA + 50)
        try:
            req = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame.Minute,
                limit=limit,
                feed=DataFeed.IEX,
            )
            bars = self._hist_client.get_stock_bars(req).df
        except Exception as e:
            logger.warning("Could not load historical bars (indicators will seed from live data): %s", e)
            return {}

        if bars.empty:
            return {}

        result = {}
        for sym in symbols:
            try:
                sym_bars = bars.loc[sym].reset_index()
            except KeyError:
                continue
            for _, row in sym_bars.iterrows():
                self._bars[sym].append({
                    "close":  float(row["close"]),
                    "volume": float(row["volume"]),
                    "time":   row["timestamp"],
                })
            result[sym] = self.get_dataframe(sym)
        logger.info("Historical bars loaded for %s (%d bars each)", symbols, limit)
        return result

    async def subscribe_new(self, symbols: list[str]):
        """Load history and subscribe to bars for symbols not yet in the stream."""
        new = [s for s in symbols if s not in self._subscribed]
        if not new:
            return
        try:
            await asyncio.to_thread(self.load_history, new)
        except Exception as e:
            logger.warning("History load failed for %s — will seed from live bars: %s", new, e)
        self._stream.subscribe_bars(self._handle_bar, *new)
        self._subscribed.update(new)
        logger.info("Dynamically subscribed to new symbols: %s", new)

    def get_dataframe(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame(list(self._bars[symbol]))

    async def _handle_bar(self, bar):
        symbol = bar.symbol
        self._bars[symbol].append({
            "close":  float(bar.close),
            "volume": float(bar.volume),
            "time":   bar.timestamp,
        })
        await self._on_bar(symbol, self.get_dataframe(symbol))

    async def run(self, symbols: list[str]):
        self._subscribed.update(symbols)
        self._stream.subscribe_bars(self._handle_bar, *symbols)
        logger.info("WebSocket subscribed to bars: %s", symbols)
        await self._stream._run_forever()
