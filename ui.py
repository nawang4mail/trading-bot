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

import altair as alt
import pandas as pd
import streamlit as st

PID_FILE   = Path("bot.pid")
SIGNAL_LOG = Path("logs/signals.jsonl")

MARKET_INDICES = {
    "S&P 500":      "SPY",
    "Nasdaq 100":   "QQQ",
    "Dow Jones":    "DIA",
    "Russell 2000": "IWM",
}

# (timeframe_str, bar_limit, x_axis_format)
_PERIOD_CFG = {
    "1D": ("minute",  390, "%H:%M"),
    "1W": ("5minute", 390, "%b %d"),
    "1M": ("day",      23, "%b %d"),
    "3M": ("day",      66, "%b %d"),
}

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


def get_data_client():
    from alpaca.data.historical import StockHistoricalDataClient
    if CONFIG_OK:
        config.maybe_reload()
    return StockHistoricalDataClient(config.API_KEY, config.API_SECRET)


# ── Market data helpers ───────────────────────────────────────────────────────

def _fetch_bars(symbol: str, tf_str: str, limit: int) -> pd.DataFrame:
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.data.enums import DataFeed

    tf_map = {
        "minute":  TimeFrame.Minute,
        "5minute": TimeFrame(5, TimeFrameUnit.Minute),
        "day":     TimeFrame.Day,
    }
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=tf_map[tf_str],
        limit=limit,
        feed=DataFeed.IEX,
    )
    bars = get_data_client().get_stock_bars(req).df
    if bars.empty:
        return pd.DataFrame()
    if isinstance(bars.index, pd.MultiIndex):
        return bars.loc[symbol].reset_index()
    return bars.reset_index()


def _fetch_quote(symbol: str) -> tuple[float, float]:
    """Return (current_close, day_pct_change) from last 2 daily bars."""
    df = _fetch_bars(symbol, "day", 2)
    if df.empty or len(df) < 2:
        return 0.0, 0.0
    cur  = float(df.iloc[-1]["close"])
    prev = float(df.iloc[-2]["close"])
    pct  = (cur - prev) / prev * 100 if prev else 0.0
    return cur, pct


def _make_chart(df: pd.DataFrame, period: str) -> alt.Chart:
    tf_str, _, x_fmt = _PERIOD_CFG[period]
    x_enc = alt.X("timestamp:T", axis=alt.Axis(title=None, format=x_fmt, labelAngle=-30))

    if tf_str == "minute":
        # Area + line chart for intraday
        base = alt.Chart(df)
        area = base.mark_area(
            line={"color": "#26a69a", "strokeWidth": 1.5},
            color=alt.Gradient(
                gradient="linear",
                stops=[
                    alt.GradientStop(color="rgba(38,166,154,0.25)", offset=0),
                    alt.GradientStop(color="rgba(38,166,154,0.0)", offset=1),
                ],
                x1=1, x2=1, y1=1, y2=0,
            ),
        ).encode(
            x=x_enc,
            y=alt.Y("close:Q", scale=alt.Scale(zero=False), title="Price ($)"),
            tooltip=[
                alt.Tooltip("timestamp:T", title="Time", format="%H:%M"),
                alt.Tooltip("close:Q",     title="Price", format="$.2f"),
                alt.Tooltip("volume:Q",    title="Volume", format=","),
            ],
        )
        vol = alt.Chart(df).mark_bar(opacity=0.35, color="#26a69a").encode(
            x=x_enc,
            y=alt.Y("volume:Q", title="Volume", axis=alt.Axis(format="~s")),
            tooltip=[alt.Tooltip("volume:Q", title="Volume", format=",")],
        ).properties(height=80)
        return alt.vconcat(area.properties(height=350), vol).resolve_scale(x="shared")

    # Candlestick for multi-day periods
    color_cond = alt.condition(
        "datum.close >= datum.open",
        alt.value("#26a69a"),
        alt.value("#ef5350"),
    )
    base = alt.Chart(df).encode(x=x_enc, color=color_cond)
    wicks   = base.mark_rule().encode(
        y=alt.Y("low:Q",  scale=alt.Scale(zero=False), title="Price ($)"),
        y2="high:Q",
        tooltip=[
            alt.Tooltip("timestamp:T", title="Date",  format="%Y-%m-%d"),
            alt.Tooltip("open:Q",      title="Open",  format="$.2f"),
            alt.Tooltip("high:Q",      title="High",  format="$.2f"),
            alt.Tooltip("low:Q",       title="Low",   format="$.2f"),
            alt.Tooltip("close:Q",     title="Close", format="$.2f"),
            alt.Tooltip("volume:Q",    title="Volume", format=","),
        ],
    )
    candles = base.mark_bar(size=6).encode(
        y=alt.Y("open:Q",  scale=alt.Scale(zero=False)),
        y2="close:Q",
    )
    vol = alt.Chart(df).mark_bar(opacity=0.35).encode(
        x=x_enc,
        y=alt.Y("volume:Q", title="Volume", axis=alt.Axis(format="~s")),
        color=color_cond,
    ).properties(height=80)
    return alt.vconcat(
        (wicks + candles).properties(height=350),
        vol,
    ).resolve_scale(x="shared")


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

tab_portfolio, tab_market, tab_dash, tab_settings = st.tabs(
    ["💼 Portfolio", "📈 Market", "📊 Dashboard", "⚙️ Settings"]
)


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
# MARKET TAB
# ══════════════════════════════════════════════════════════════════════════════

with tab_market:
    if not CONFIG_OK:
        st.error(f"Cannot connect: `{CONFIG_ERROR}`")
        st.info("Set `ALPACA_API_KEY` and `ALPACA_API_SECRET` in your `.env` file, then restart Streamlit.")
    else:
        # ── Market Summary ────────────────────────────────────────────────────
        @st.fragment(run_every=refresh_sec)
        def market_summary():
            st.subheader("Market Summary")
            cols = st.columns(len(MARKET_INDICES))
            for (label, sym), col in zip(MARKET_INDICES.items(), cols):
                try:
                    price, pct = _fetch_quote(sym)
                    col.metric(
                        label,
                        f"${price:,.2f}",
                        f"{pct:+.2f}%",
                        delta_color="normal",
                    )
                except Exception:
                    col.metric(label, "—", "unavailable")

        market_summary()

        st.divider()

        # ── Symbol Chart ──────────────────────────────────────────────────────
        st.subheader("Symbol Chart")

        index_syms  = list(MARKET_INDICES.values())
        config.maybe_reload()
        watch_syms  = config.SYMBOLS
        all_syms    = list(dict.fromkeys(watch_syms + index_syms))

        ctrl_l, ctrl_r = st.columns([3, 1])
        selected_sym = ctrl_l.selectbox("Symbol", all_syms, label_visibility="collapsed")
        period       = ctrl_r.radio("Period", list(_PERIOD_CFG.keys()), horizontal=True, label_visibility="collapsed")

        @st.fragment(run_every=refresh_sec)
        def symbol_chart(sym: str, per: str):
            tf_str, limit, _ = _PERIOD_CFG[per]
            try:
                df = _fetch_bars(sym, tf_str, limit)
            except Exception as e:
                st.error(f"Could not load data for {sym}: {e}")
                return

            if df.empty:
                st.warning(f"No data returned for **{sym}**. Market may be closed or symbol is invalid.")
                return

            # Header metrics
            cur   = float(df.iloc[-1]["close"])
            first = float(df.iloc[0]["open"])
            chg   = cur - first
            pct   = chg / first * 100 if first else 0.0
            hi    = float(df["high"].max())
            lo    = float(df["low"].min())
            vol   = int(df["volume"].sum())

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric(sym, f"${cur:,.2f}", f"{chg:+.2f} ({pct:+.2f}%)")
            m2.metric("Period High", f"${hi:,.2f}")
            m3.metric("Period Low",  f"${lo:,.2f}")
            m4.metric("Period Vol",  f"{vol:,}")
            m5.metric("Bars",        f"{len(df):,}")

            chart = _make_chart(df, per)
            st.altair_chart(chart, use_container_width=True)

        symbol_chart(selected_sym, period)

        st.divider()

        # ── Watchlist Manager ─────────────────────────────────────────────────
        st.subheader("Watchlist")
        config.maybe_reload()

        # Display current symbols as removable chips
        sym_cols = st.columns(min(len(config.SYMBOLS), 8) or 1)
        for i, sym in enumerate(config.SYMBOLS):
            with sym_cols[i % len(sym_cols)]:
                if st.button(f"✕ {sym}", key=f"rm_{sym}", use_container_width=True,
                             help=f"Remove {sym} from watchlist"):
                    new_syms = [s for s in config.SYMBOLS if s != sym]
                    config.save({**config.as_dict(), "symbols": new_syms})
                    if bot_is_running():
                        restart_bot()
                        st.success(f"Removed {sym} — bot restarted.")
                    else:
                        st.success(f"Removed {sym}.")
                    st.rerun()

        # Add symbol form
        with st.form("add_symbol_form", clear_on_submit=True):
            add_col, btn_col = st.columns([4, 1])
            new_sym = add_col.text_input(
                "Add symbol",
                placeholder="e.g. TSLA",
                label_visibility="collapsed",
            )
            add_clicked = btn_col.form_submit_button("＋ Add", type="primary", use_container_width=True)

        if add_clicked:
            sym = new_sym.strip().upper()
            if not sym:
                st.error("Enter a ticker symbol.")
            elif sym in config.SYMBOLS:
                st.warning(f"**{sym}** is already in your watchlist.")
            else:
                # Validate by fetching one bar
                with st.spinner(f"Validating {sym}…"):
                    try:
                        df_test = _fetch_bars(sym, "day", 1)
                        if df_test.empty:
                            st.error(f"No data found for **{sym}**. Check the ticker and try again.")
                        else:
                            config.save({**config.as_dict(), "symbols": config.SYMBOLS + [sym]})
                            if bot_is_running():
                                restart_bot()
                                st.success(f"Added **{sym}** to watchlist — bot restarted.")
                            else:
                                st.success(f"Added **{sym}** to watchlist.")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Could not validate {sym}: {e}")


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

        _SIGNAL_STYLES = {
            "buy":       "background:#1a3a1a;color:#4caf50",
            "sell":      "background:#3a1a1a;color:#f44336",
            "stop_loss": "background:#3a2a00;color:#ff9800",
        }

        def _explain(row):
            sig = row["Signal"]
            s = row["Short EMA"]; l = row["Long EMA"]
            rsi = row["RSI"]; vr = row["Vol Ratio"]
            te = row["Trend EMA"]; m = row["MACD"]; ms = row["MACD Sig"]
            if sig == "buy":
                return (
                    f"BUY triggered: Short EMA ({s:.2f}) crossed above Long EMA ({l:.2f}), "
                    f"signaling a bullish reversal. RSI at {rsi:.1f} is below overbought (70), "
                    f"leaving upside room. Volume ratio {vr:.2f}x confirms above-average activity. "
                    f"Price is above the 200 EMA ({te:.2f}), aligning with the long-term uptrend. "
                    f"MACD ({m:.4f}) is above its signal line ({ms:.4f}), confirming bullish momentum."
                )
            if sig == "sell":
                return (
                    f"SELL triggered: Short EMA ({s:.2f}) crossed below Long EMA ({l:.2f}), "
                    f"signaling a bearish reversal. RSI at {rsi:.1f} is above oversold (30), "
                    f"suggesting further downside is possible. Volume ratio {vr:.2f}x confirms above-average activity. "
                    f"Price is below the 200 EMA ({te:.2f}), aligning with the long-term downtrend. "
                    f"MACD ({m:.4f}) is below its signal line ({ms:.4f}), confirming bearish momentum."
                )
            if sig == "stop_loss":
                return (
                    f"STOP LOSS triggered: Price fell below the stop loss threshold, "
                    f"automatically closing the position to cap losses. "
                    f"At trigger — RSI: {rsi:.1f}, Short EMA: {s:.2f}, Long EMA: {l:.2f}, "
                    f"Trend EMA: {te:.2f}."
                )
            return ""

        def _fmt(v):
            try:    return f"{float(v):.4f}"
            except: return str(v)

        thead_cols = ["Time", "Symbol", "Signal", "Short EMA", "Long EMA",
                      "RSI", "Vol Ratio", "Trend EMA", "MACD", "MACD Sig"]
        th_cells = "".join(f"<th>{c}</th>" for c in thead_cols)

        rows_html = ""
        for _, row in df.iterrows():
            sig       = row["Signal"]
            badge_css = _SIGNAL_STYLES.get(sig, "")
            sig_cell  = (
                f'<td><div class="tip-wrap">'
                f'<span class="sig-badge" style="{badge_css}">{sig}</span>'
                f'<div class="tip-box">{_explain(row)}</div>'
                f'</div></td>'
            )
            cells = ""
            for col in thead_cols:
                if col == "Signal":
                    cells += sig_cell
                elif col in ("Time", "Symbol"):
                    cells += f"<td>{row[col]}</td>"
                else:
                    cells += f"<td>{_fmt(row[col])}</td>"
            rows_html += f"<tr>{cells}</tr>"

        html = f"""
<style>
  .sig-tbl {{width:100%;border-collapse:collapse;font-size:13px;}}
  .sig-tbl th {{padding:6px 10px;text-align:left;border-bottom:1px solid #333;color:#888;font-weight:500;white-space:nowrap;}}
  .sig-tbl td {{padding:6px 10px;border-bottom:1px solid #1e1e1e;white-space:nowrap;}}
  .tip-wrap {{position:relative;display:inline-block;}}
  .sig-badge {{padding:2px 10px;border-radius:4px;cursor:help;font-weight:600;font-size:12px;}}
  .tip-box {{
    visibility:hidden;opacity:0;
    background:#1e1e2e;color:#cdd6f4;
    border:1px solid #45475a;border-radius:6px;
    padding:10px 13px;font-size:12px;line-height:1.6;
    max-width:340px;white-space:normal;
    position:absolute;z-index:9999;
    bottom:130%;left:50%;transform:translateX(-50%);
    transition:opacity .15s ease;
    pointer-events:none;
  }}
  .tip-wrap:hover .tip-box {{visibility:visible;opacity:1;}}
</style>
<table class="sig-tbl">
  <thead><tr>{th_cells}</tr></thead>
  <tbody>{rows_html}</tbody>
</table>
"""
        st.markdown(html, unsafe_allow_html=True)

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
