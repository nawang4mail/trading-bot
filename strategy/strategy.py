import logging
from dataclasses import dataclass
from enum import Enum

import pandas as pd
import ta

import config

logger = logging.getLogger(__name__)


class Signal(Enum):
    BUY  = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class StrategyResult:
    signal:       Signal
    symbol:       str
    short_ema:    float
    long_ema:     float
    rsi:          float
    volume_ratio: float
    trend_ema:    float
    macd:         float
    macd_signal_val: float


class EMACrossoverStrategy:
    """
    EMA crossover with four confirmation filters:
      1. RSI — avoid overbought/oversold entries
      2. Volume — only trade on above-average volume
      3. Trend EMA (200) — only trade with the long-term trend
      4. MACD — require MACD/signal agreement

    BUY  when short EMA crosses above long EMA AND all four filters pass.
    SELL when short EMA crosses below long EMA AND all four filters pass.
    """

    def __init__(self):
        self._prev: dict[str, tuple[float, float]] = {}

    def evaluate(self, symbol: str, df: pd.DataFrame) -> StrategyResult:
        _empty = StrategyResult(Signal.HOLD, symbol, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        min_bars = max(
            config.LONG_WINDOW,
            config.RSI_WINDOW + 1,
            config.MACD_SLOW + config.MACD_SIGN + 1,
            config.VOLUME_WINDOW,
        )
        if len(df) < min_bars:
            return _empty

        closes  = df["close"]
        volumes = df["volume"] if "volume" in df.columns else pd.Series([1.0] * len(df))

        # ── EMA crossover ────────────────────────────────────────────────────
        short_ema = float(closes.ewm(span=config.SHORT_WINDOW, adjust=False).mean().iloc[-1])
        long_ema  = float(closes.ewm(span=config.LONG_WINDOW,  adjust=False).mean().iloc[-1])
        price     = float(closes.iloc[-1])

        # ── RSI ──────────────────────────────────────────────────────────────
        rsi = float(ta.momentum.RSIIndicator(closes, window=config.RSI_WINDOW).rsi().iloc[-1])

        # ── Volume confirmation ───────────────────────────────────────────────
        vol_sma   = float(volumes.rolling(config.VOLUME_WINDOW).mean().iloc[-1])
        vol_ratio = float(volumes.iloc[-1]) / vol_sma if vol_sma > 0 else 1.0

        # ── Trend EMA ─────────────────────────────────────────────────────────
        trend_ema = float(closes.ewm(span=config.TREND_EMA, adjust=False).mean().iloc[-1])

        # ── MACD ──────────────────────────────────────────────────────────────
        macd_obj    = ta.trend.MACD(closes, window_fast=config.MACD_FAST,
                                    window_slow=config.MACD_SLOW, window_sign=config.MACD_SIGN)
        macd_val    = float(macd_obj.macd().iloc[-1])
        macd_sig    = float(macd_obj.macd_signal().iloc[-1])

        # ── Signal logic ──────────────────────────────────────────────────────
        signal = Signal.HOLD
        if symbol in self._prev:
            prev_short, prev_long = self._prev[symbol]
            crossed_above = prev_short <= prev_long and short_ema > long_ema
            crossed_below = prev_short >= prev_long and short_ema < long_ema

            if (crossed_above
                    and rsi < config.RSI_OVERBOUGHT
                    and vol_ratio > 1.0
                    and price > trend_ema
                    and macd_val > macd_sig):
                signal = Signal.BUY

            elif (crossed_below
                    and rsi > config.RSI_OVERSOLD
                    and vol_ratio > 1.0
                    and price < trend_ema
                    and macd_val < macd_sig):
                signal = Signal.SELL

        self._prev[symbol] = (short_ema, long_ema)

        if signal != Signal.HOLD:
            logger.info(
                "%s signal=%s  ema=%.2f/%.2f  rsi=%.1f  vol_ratio=%.2f  "
                "trend_ema=%.2f  macd=%.4f/%.4f",
                symbol, signal.value, short_ema, long_ema, rsi,
                vol_ratio, trend_ema, macd_val, macd_sig,
            )

        return StrategyResult(signal, symbol, short_ema, long_ema, rsi,
                              vol_ratio, trend_ema, macd_val, macd_sig)
