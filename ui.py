"""
Trading bot dashboard.

Usage:
    streamlit run ui.py
"""

import json
import os
import signal as _signal
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PID_FILE  = Path("bot.pid")
SIGNAL_LOG = Path("logs/signals.jsonl")

st.set_page_config(page_title="Trading Bot", page_icon="📈", layout="wide")

# ── Config ────────────────────────────────────────────────────────────────────

try:
    import config
    CONFIG_OK    = True
    CONFIG_ERROR = None
except Exception as e:
    CONFIG_OK    = False
    CONFIG_ERROR = str(e)


def get_client():
    from alpaca.trading.client import TradingClient
    if CONFIG_OK:
        config.maybe_reload()
    return TradingClient(config.API_KEY, config.API_SECRET, paper=config.PAPER)


# ── Bot helpers ───────────────────────────────────────────────────────────────

def bot_is_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError, OSError):
        PID_FILE.unlink(missing_ok=True)
        return False


def start_bot():
    proc = subprocess.Popen([sys.executable, "main.py"])
    PID_FILE.write_text(str(proc.pid))


def stop_bot():
    if not PID_FILE.exists():
        return
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, _signal.SIGTERM)
    except Exception:
        pass
    PID_FILE.unlink(missing_ok=True)


def restart_bot():
    stop_bot()
    start_bot()


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📈 Trading Bot")
    st.divider()

    @st.fragment(run_every="3s")
    def sidebar_status():
        running = bot_is_running()
        st.markdown(f"**Status:** {'🟢 Running' if running else '🔴 Stopped'}")
        if CONFIG_OK:
            config.maybe_reload()
            st.markdown(f"**Mode:** {'🧪 Paper' if config.PAPER else '⚡ Live'}")
            st.markdown(f"**Symbols:** {', '.join(config.SYMBOLS)}")
            st.markdown(f"**EMA:** {config.SHORT_WINDOW} / {config.LONG_WINDOW}")
            st.markdown(f"**RSI:** {config.RSI_WINDOW} ({config.RSI_OVERSOLD}–{config.RSI_OVERBOUGHT})")
            st.markdown(f"**Stop-loss:** {config.STOP_LOSS_PCT * 100:.0f}%")
        else:
            st.error(f"Config error: {CONFIG_ERROR}")

    sidebar_status()

    st.divider()

    running = bot_is_running()
    col_a, col_b = st.columns(2)
    if running:
        if col_a.button("⏹ Stop", use_container_width=True):
            stop_bot()
            st.rerun()
        if col_b.button("🔄 Restart", type="primary", use_container_width=True):
            restart_bot()
            st.rerun()
    else:
        if col_a.button("▶ Start", type="primary", use_container_width=True, disabled=not CONFIG_OK):
            start_bot()
            st.rerun()

    st.divider()
    refresh_sec = st.select_slider(
        "Live update interval",
        options=[3, 5, 10, 15, 30, 60],
        value=10,
        format_func=lambda x: f"{x}s",
    )


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_portfolio, tab_dash, tab_settings = st.tabs(["💼 Portfolio", "📊 Dashboard", "⚙️ Settings"])


# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO TAB
# ══════════════════════════════════════════════════════════════════════════════

with tab_portfolio:
    if not CONFIG_OK:
        st.error(f"Cannot connect: `{CONFIG_ERROR}`")
        st.info("Set `ALPACA_API_KEY` and `ALPACA_API_SECRET` in your `.env` file, then restart Streamlit.")
        st.stop()

    # ── Live account + positions (auto-refreshes) ─────────────────────────────
    @st.fragment(run_every=refresh_sec)
    def portfolio_live():
        try:
            client    = get_client()
            acct      = client.get_account()
            equity    = float(acct.equity)
            last_eq   = float(acct.last_equity)
            cash      = float(acct.cash)
            bp        = float(acct.buying_power)
            day_pnl   = equity - last_eq
            day_pct   = (day_pnl / last_eq * 100) if last_eq else 0.0
        except Exception as e:
            st.error(f"Connection failed: {e}")
            st.markdown(
                "**Check:**\n"
                "- Keys copied from the **Paper Trading** section of alpaca.markets\n"
                "- Paper keys start with `PK`\n"
                "- Both Key ID and Secret saved in `.env`"
            )
            if st.button("🔄 Retry"):
                st.rerun(scope="fragment")
            return

        # Account metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Portfolio Value", f"${equity:,.2f}")
        m2.metric("Day P&L", f"${day_pnl:+,.2f}", f"{day_pct:+.2f}%")
        m3.metric("Cash", f"${cash:,.2f}")
        m4.metric("Buying Power", f"${bp:,.2f}")

        st.divider()

        # Positions
        st.subheader("My Stocks")
        try:
            positions = client.get_all_positions()
        except Exception as e:
            st.error(f"Could not load positions: {e}")
            return

        if not positions:
            st.info("No open positions. Use the **Buy** form below to purchase stocks.")
            return

        hdrs = ["Symbol", "Shares", "Entry Price", "Current Price", "Market Value", "P&L ($)", "P&L (%)", ""]
        cols = st.columns([1.5, 1.2, 1.5, 1.5, 1.5, 1.5, 1.8, 1.2])
        for h, c in zip(hdrs, cols):
            c.markdown(f"**{h}**")
        st.markdown("---")

        for pos in positions:
            sym    = pos.symbol
            qty    = float(pos.qty)
            entry  = float(pos.avg_entry_price)
            price  = float(pos.current_price)
            value  = float(pos.market_value)
            pl     = float(pos.unrealized_pl)
            pl_pct = float(pos.unrealized_plpc) * 100
            color  = "green" if pl >= 0 else "red"

            c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([1.5, 1.2, 1.5, 1.5, 1.5, 1.5, 1.8, 1.2])
            c1.markdown(f"**{sym}**")
            c2.markdown(f"{qty:g}")
            c3.markdown(f"${entry:.2f}")
            c4.markdown(f"${price:.2f}")
            c5.markdown(f"${value:,.2f}")
            c6.markdown(f":{color}[${pl:+,.2f}]")
            c7.markdown(f":{color}[{pl_pct:+.2f}%]")
            if c8.button("Close", key=f"close_{sym}", use_container_width=True):
                try:
                    from execution.orders import OrderManager
                    OrderManager().sell(sym)
                    st.success(f"Closed {sym}")
                    st.rerun(scope="fragment")
                except Exception as e:
                    st.error(str(e))

    portfolio_live()

    st.divider()

    # ── Buy form (static — only reruns on submit) ─────────────────────────────
    st.subheader("Buy Stock")

    hc1, hc2, hc3, hc4 = st.columns([2, 2, 2, 1])
    hc1.markdown("**Symbol**")
    hc2.markdown("**Shares**")
    hc3.markdown("**Add to watchlist**")
    hc4.markdown("")

    with st.form("buy_form", clear_on_submit=True):
        fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 1])
        sym_input = fc1.text_input("Symbol", placeholder="e.g. AAPL", label_visibility="collapsed")
        qty_input = fc2.number_input("Shares", min_value=0.001, value=1.0, step=1.0,
                                     format="%.3f", label_visibility="collapsed")
        watchlist = fc3.checkbox("Add to watchlist", value=True, label_visibility="collapsed")
        submitted = fc4.form_submit_button("Buy", type="primary", use_container_width=True)

    if submitted:
        sym = sym_input.strip().upper()
        if not sym:
            st.error("Enter a symbol.")
        else:
            try:
                from execution.orders import OrderManager
                order = OrderManager().buy_manual(sym, qty_input)
                st.success(f"✅ Bought {qty_input:g} shares of **{sym}** — order id: `{order.id}`")
                if watchlist and sym not in config.SYMBOLS:
                    config.maybe_reload()
                    new_settings = config.as_dict()
                    new_settings["symbols"] = config.SYMBOLS + [sym]
                    config.save(new_settings)
                    running = bot_is_running()
                    if running:
                        restart_bot()
                        st.info(f"{sym} added to watchlist — bot restarted to subscribe.")
                    else:
                        st.info(f"{sym} added to watchlist.")
            except Exception as e:
                st.error(str(e))


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD TAB
# ══════════════════════════════════════════════════════════════════════════════

with tab_dash:
    @st.fragment(run_every=refresh_sec)
    def dashboard_live():
        if not CONFIG_OK:
            st.warning("API not configured.")
            return

        # Account metrics
        try:
            client    = get_client()
            acct      = client.get_account()
            equity    = float(acct.equity)
            last_eq   = float(acct.last_equity)
            day_pnl   = equity - last_eq
            day_pct   = (day_pnl / last_eq * 100) if last_eq else 0.0

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Equity", f"${equity:,.2f}")
            c2.metric("Day P&L", f"${day_pnl:+,.2f}", f"{day_pct:+.2f}%")
            c3.metric("Buying Power", f"${float(acct.buying_power):,.2f}")
            c4.metric("Bot", f"{'Running 🟢' if bot_is_running() else 'Stopped 🔴'}")
        except Exception as e:
            st.error(f"Could not load account: {e}")

        st.divider()

        # Signals
        st.subheader("Recent Signals")
        if not SIGNAL_LOG.exists() or not SIGNAL_LOG.read_text().strip():
            st.info("Start the bot to see signals here.")
            return

        records = [json.loads(l) for l in SIGNAL_LOG.read_text().strip().splitlines()[-100:]][::-1]
        df = pd.DataFrame(records)
        df["time"] = pd.to_datetime(df["time"]).dt.strftime("%H:%M:%S")
        df = df.reindex(columns=["time", "symbol", "signal", "short_ema", "long_ema",
                                  "rsi", "volume_ratio", "trend_ema", "macd", "macd_signal"])
        df.columns = ["Time", "Symbol", "Signal", "Short EMA", "Long EMA",
                      "RSI", "Vol Ratio", "Trend EMA", "MACD", "MACD Sig"]

        def _color(val):
            if val == "buy":       return "background-color:#1a3a1a;color:#4caf50"
            if val == "sell":      return "background-color:#3a1a1a;color:#f44336"
            if val == "stop_loss": return "background-color:#3a2a00;color:#ff9800"
            return ""

        st.dataframe(df.style.applymap(_color, subset=["Signal"]),
                     use_container_width=True, hide_index=True)

    dashboard_live()


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS TAB
# ══════════════════════════════════════════════════════════════════════════════

with tab_settings:
    st.header("Strategy Settings")
    st.caption(
        "Risk and indicator changes apply on the **next bar** without restarting. "
        "Symbol changes require a **bot restart**."
    )

    if not CONFIG_OK:
        st.error(f"Cannot load settings: {CONFIG_ERROR}")
    else:
        config.maybe_reload()
        current = config.as_dict()

        with st.form("settings_form"):
            st.subheader("Symbols")
            symbols_input = st.text_input(
                "Symbols (comma-separated)", value=", ".join(current["symbols"]),
                help="US stock tickers, e.g. AAPL, MSFT, NVDA, TSLA",
            )
            st.divider()

            st.subheader("EMA Crossover")
            col1, col2 = st.columns(2)
            short_window = col1.slider("Fast EMA period", 3, 50, current["short_window"])
            long_window  = col2.slider("Slow EMA period", 10, 200, current["long_window"])
            st.divider()

            st.subheader("RSI Filter")
            col3, col4, col5 = st.columns(3)
            rsi_window     = col3.slider("RSI period", 5, 30, current["rsi_window"])
            rsi_overbought = col4.slider("Overbought — blocks BUY", 50, 95, int(current["rsi_overbought"]))
            rsi_oversold   = col5.slider("Oversold — blocks SELL",  5, 50, int(current["rsi_oversold"]))
            st.divider()

            st.subheader("Additional Filters")
            col_a, col_b = st.columns(2)
            volume_window = col_a.slider("Volume window (bars)", 5, 50,
                                         current.get("volume_window", 20),
                                         help="Signal requires volume > this many bars' average")
            trend_ema_val = col_b.slider("Trend EMA period", 50, 500,
                                         current.get("trend_ema", 200),
                                         help="BUY only above this EMA; SELL only below it")
            col_c, col_d, col_e = st.columns(3)
            macd_fast = col_c.slider("MACD fast",   5,  20, current.get("macd_fast", 12))
            macd_slow = col_d.slider("MACD slow",  15,  50, current.get("macd_slow", 26))
            macd_sign = col_e.slider("MACD signal",  3,  15, current.get("macd_sign",  9))
            st.divider()

            st.subheader("Risk Management")
            col6, col7, col8 = st.columns(3)
            max_pos_pct   = col6.slider("Position size (%)", 1, 25, int(current["max_position_pct"] * 100))
            max_loss_pct  = col7.slider("Daily loss limit (%)", 1, 10, int(current["max_daily_loss_pct"] * 100))
            stop_loss_pct = col8.slider("Stop-loss per trade (%)", 1, 15, int(current["stop_loss_pct"] * 100))
            st.divider()

            save_clicked = st.form_submit_button("💾 Save Settings", type="primary", use_container_width=True)

        if save_clicked:
            if short_window >= long_window:
                st.error("Fast EMA must be less than Slow EMA.")
            elif rsi_oversold >= rsi_overbought:
                st.error("Oversold must be less than Overbought.")
            elif macd_fast >= macd_slow:
                st.error("MACD fast period must be less than slow period.")
            else:
                new_symbols     = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]
                symbols_changed = sorted(new_symbols) != sorted(current["symbols"])
                config.save({
                    "symbols": new_symbols,
                    "short_window": short_window,
                    "long_window": long_window,
                    "rsi_window": rsi_window,
                    "rsi_overbought": float(rsi_overbought),
                    "rsi_oversold":   float(rsi_oversold),
                    "volume_window":  volume_window,
                    "trend_ema":      trend_ema_val,
                    "macd_fast":      macd_fast,
                    "macd_slow":      macd_slow,
                    "macd_sign":      macd_sign,
                    "max_position_pct":   max_pos_pct / 100,
                    "max_daily_loss_pct": max_loss_pct / 100,
                    "stop_loss_pct":      stop_loss_pct / 100,
                })
                if symbols_changed and bot_is_running():
                    restart_bot()
                    st.success("Saved — bot restarted for symbol change.")
                elif symbols_changed:
                    st.success("Saved — start the bot to trade new symbols.")
                else:
                    st.success("Saved — changes apply on the next bar.")
                st.rerun()
