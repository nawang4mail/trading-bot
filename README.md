# Trading Bot

An automated stock trading bot that runs an EMA crossover strategy with multi-indicator confirmation filters, connected to Alpaca Markets. Includes a Streamlit dashboard for live monitoring and configuration.

---

## Prerequisites

- Python 3.9+
- An [Alpaca Markets](https://alpaca.markets) account (free paper trading account is sufficient)

---

## Installation

**1. Clone the repository**

```bash
git clone <repo-url>
cd trading-bot
```

**2. Create and activate a virtual environment**

```bash
python3 -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```

**4. Configure your API keys**

Copy the example env file and fill in your Alpaca credentials:

```bash
cp .env.example .env
```

Open `.env` and set your keys:

```
ALPACA_API_KEY=your_api_key_here
ALPACA_API_SECRET=your_api_secret_here
PAPER=true
```

Get your keys from [alpaca.markets](https://alpaca.markets) → Paper Trading → API Keys. Paper trading keys start with `PK`.

> **Note:** Keep `PAPER=true` until you are confident in the strategy. Set it to `false` only to trade with real money.

---

## Running the Application

### Option A — Dashboard (recommended)

Start the Streamlit UI, which lets you start/stop the bot, monitor live positions, and adjust settings from the browser:

```bash
.venv/bin/streamlit run ui.py
```

Then open **http://localhost:8501** in your browser. Use the sidebar to start the bot.

### Option B — Bot only (headless)

Run the trading bot directly from the terminal:

```bash
python main.py
```

Logs are written to the terminal and signal history is saved to `logs/signals.jsonl`.

---

## How It Works

### Strategy — EMA Crossover with 4 confirmation filters

The bot watches live 1-minute bars for each configured symbol via the Alpaca WebSocket. On every new bar it runs the following logic:

| Step | Check | Purpose |
|------|-------|---------|
| 1 | **EMA crossover** | Fast EMA (default 9) crosses above/below slow EMA (default 21) |
| 2 | **RSI filter** | RSI must be below overbought (70) to buy; above oversold (30) to sell |
| 3 | **Volume filter** | Current bar volume must be above the rolling average — no low-volume signals |
| 4 | **Trend EMA (200)** | Price must be above the 200 EMA to buy; below it to sell |
| 5 | **MACD confirmation** | MACD line must agree with the crossover direction |

All five conditions must pass for a BUY or SELL order to be placed. Otherwise the bar is ignored (HOLD).

### Risk Management

- **Position sizing** — each trade uses a fixed percentage of portfolio equity (default 5%).
- **Stop-loss** — if a position drops more than the configured threshold (default 2%) from entry, it is automatically sold.
- **Daily loss limit** — if the portfolio is down more than the daily loss limit (default 2%) from the opening equity, no new orders are placed for the rest of the day.
- **Market hours** — no orders are placed outside regular market hours.

### Signal log

Every non-HOLD signal is appended to `logs/signals.jsonl` with a timestamp, symbol, signal type, and all indicator values for later review.

---

## Configuration

All strategy parameters can be changed live from the **Settings tab** in the dashboard — most changes take effect on the next bar without restarting the bot. Symbol changes require a bot restart (the UI handles this automatically).

You can also set defaults in `.env` before first launch:

| Variable | Default | Description |
|----------|---------|-------------|
| `SYMBOLS` | `AAPL,MSFT,NVDA` | Comma-separated list of tickers to trade |
| `SHORT_WINDOW` | `9` | Fast EMA period |
| `LONG_WINDOW` | `21` | Slow EMA period |
| `RSI_WINDOW` | `14` | RSI period |
| `RSI_OVERBOUGHT` | `70` | RSI level that blocks a BUY signal |
| `RSI_OVERSOLD` | `30` | RSI level that blocks a SELL signal |
| `VOLUME_WINDOW` | `20` | Rolling bars used for volume average |
| `TREND_EMA` | `200` | Long-term trend EMA period |
| `MACD_FAST` | `12` | MACD fast period |
| `MACD_SLOW` | `26` | MACD slow period |
| `MACD_SIGN` | `9` | MACD signal period |
| `MAX_POSITION_PCT` | `0.05` | Fraction of equity per trade (5%) |
| `MAX_DAILY_LOSS_PCT` | `0.02` | Daily drawdown limit before halting (2%) |
| `STOP_LOSS_PCT` | `0.02` | Per-trade stop-loss threshold (2%) |

---

## Project Structure

```
trading-bot/
├── main.py              # Bot entry point — event loop and signal dispatch
├── ui.py                # Streamlit dashboard
├── config.py            # Settings loader (env + settings.json)
├── strategy/
│   └── strategy.py      # EMA crossover strategy and indicator logic
├── data/
│   └── market_data.py   # Alpaca WebSocket feed and historical bar loader
├── execution/
│   └── orders.py        # Order manager — buy, sell, stop-loss, risk checks
├── logs/
│   └── signals.jsonl    # Appended signal history (auto-created)
├── .env.example         # Environment variable template
└── requirements.txt     # Python dependencies
```

---

## Disclaimer

This bot is for educational purposes. Automated trading carries significant financial risk. Always test thoroughly in paper trading mode before using real money.
