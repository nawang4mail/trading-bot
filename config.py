import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

SETTINGS_FILE = Path("settings.json")

# API credentials — always from .env, never from settings.json
API_KEY: str = os.environ["ALPACA_API_KEY"]
API_SECRET: str = os.environ["ALPACA_API_SECRET"]
PAPER: bool = os.getenv("PAPER", "true").lower() == "true"

# Strategy / risk settings — overridable via settings.json
SYMBOLS: list[str]
SHORT_WINDOW: int
LONG_WINDOW: int
RSI_WINDOW: int
RSI_OVERBOUGHT: float
RSI_OVERSOLD: float
VOLUME_WINDOW: int
TREND_EMA: int
MACD_FAST: int
MACD_SLOW: int
MACD_SIGN: int
MAX_POSITION_PCT: float
MAX_DAILY_LOSS_PCT: float
STOP_LOSS_PCT: float

_last_mtime: float = 0.0


def reload():
    """Load settings from settings.json, falling back to .env defaults."""
    global SYMBOLS, SHORT_WINDOW, LONG_WINDOW
    global RSI_WINDOW, RSI_OVERBOUGHT, RSI_OVERSOLD
    global VOLUME_WINDOW, TREND_EMA, MACD_FAST, MACD_SLOW, MACD_SIGN
    global MAX_POSITION_PCT, MAX_DAILY_LOSS_PCT, STOP_LOSS_PCT, _last_mtime

    data: dict = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            _last_mtime = SETTINGS_FILE.stat().st_mtime
        except Exception:
            pass

    SYMBOLS       = data.get("symbols", os.getenv("SYMBOLS", "AAPL,MSFT,NVDA").split(","))
    SHORT_WINDOW  = int(data.get("short_window",  os.getenv("SHORT_WINDOW",  "9")))
    LONG_WINDOW   = int(data.get("long_window",   os.getenv("LONG_WINDOW",   "21")))
    RSI_WINDOW    = int(data.get("rsi_window",    os.getenv("RSI_WINDOW",    "14")))
    RSI_OVERBOUGHT = float(data.get("rsi_overbought", os.getenv("RSI_OVERBOUGHT", "70")))
    RSI_OVERSOLD   = float(data.get("rsi_oversold",   os.getenv("RSI_OVERSOLD",   "30")))
    VOLUME_WINDOW = int(data.get("volume_window", os.getenv("VOLUME_WINDOW", "20")))
    TREND_EMA     = int(data.get("trend_ema",     os.getenv("TREND_EMA",     "200")))
    MACD_FAST     = int(data.get("macd_fast",     os.getenv("MACD_FAST",     "12")))
    MACD_SLOW     = int(data.get("macd_slow",     os.getenv("MACD_SLOW",     "26")))
    MACD_SIGN     = int(data.get("macd_sign",     os.getenv("MACD_SIGN",     "9")))
    MAX_POSITION_PCT   = float(data.get("max_position_pct",   os.getenv("MAX_POSITION_PCT",   "0.05")))
    MAX_DAILY_LOSS_PCT = float(data.get("max_daily_loss_pct", os.getenv("MAX_DAILY_LOSS_PCT", "0.02")))
    STOP_LOSS_PCT      = float(data.get("stop_loss_pct",      os.getenv("STOP_LOSS_PCT",      "0.02")))


def maybe_reload():
    """Reload only if settings.json has been modified since last load."""
    if SETTINGS_FILE.exists() and SETTINGS_FILE.stat().st_mtime > _last_mtime:
        reload()


def save(data: dict):
    """Persist settings to settings.json and reload."""
    SETTINGS_FILE.write_text(json.dumps(data, indent=2))
    reload()


def as_dict() -> dict:
    return {
        "symbols":           SYMBOLS,
        "short_window":      SHORT_WINDOW,
        "long_window":       LONG_WINDOW,
        "rsi_window":        RSI_WINDOW,
        "rsi_overbought":    RSI_OVERBOUGHT,
        "rsi_oversold":      RSI_OVERSOLD,
        "volume_window":     VOLUME_WINDOW,
        "trend_ema":         TREND_EMA,
        "macd_fast":         MACD_FAST,
        "macd_slow":         MACD_SLOW,
        "macd_sign":         MACD_SIGN,
        "max_position_pct":  MAX_POSITION_PCT,
        "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
        "stop_loss_pct":     STOP_LOSS_PCT,
    }


# Load on import
reload()
