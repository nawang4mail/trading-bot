import logging

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

import config

logger = logging.getLogger(__name__)


class OrderManager:
    def __init__(self):
        self._client = TradingClient(config.API_KEY, config.API_SECRET, paper=config.PAPER)
        self._daily_start_equity: float | None = None

    # ------------------------------------------------------------------
    # Account helpers
    # ------------------------------------------------------------------

    def get_equity(self) -> float:
        return float(self._client.get_account().equity)

    def get_position(self, symbol: str):
        """Return the open position object, or None if no position."""
        try:
            return self._client.get_open_position(symbol)
        except Exception:
            return None

    def get_position_qty(self, symbol: str) -> float:
        pos = self.get_position(symbol)
        return float(pos.qty) if pos else 0.0

    def is_market_open(self) -> bool:
        return self._client.get_clock().is_open

    # ------------------------------------------------------------------
    # Daily loss guard
    # ------------------------------------------------------------------

    def check_daily_loss_limit(self) -> bool:
        """Return False (halt) when the portfolio is down more than MAX_DAILY_LOSS_PCT."""
        equity = self.get_equity()
        if self._daily_start_equity is None:
            self._daily_start_equity = equity
            return True
        loss_pct = (self._daily_start_equity - equity) / self._daily_start_equity
        if loss_pct >= config.MAX_DAILY_LOSS_PCT:
            logger.warning(
                "Daily loss limit reached (%.2f%%). Halting new orders.", loss_pct * 100
            )
            return False
        return True

    def reset_daily_equity(self):
        self._daily_start_equity = None

    # ------------------------------------------------------------------
    # Stop-loss
    # ------------------------------------------------------------------

    def check_stop_loss(self, symbol: str) -> bool:
        """
        Exit the position if it has fallen more than STOP_LOSS_PCT from entry.
        Returns True if a stop-loss sell was triggered.
        """
        pos = self.get_position(symbol)
        if pos is None:
            return False
        entry = float(pos.avg_entry_price)
        current = float(pos.current_price)
        loss_pct = (entry - current) / entry
        if loss_pct >= config.STOP_LOSS_PCT:
            logger.warning(
                "Stop-loss triggered for %s: entry=%.4f current=%.4f loss=%.2f%%",
                symbol, entry, current, loss_pct * 100,
            )
            self.sell(symbol)
            return True
        return False

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def _calc_notional(self) -> float:
        """Size position as a fixed % of current equity (notional USD)."""
        return round(self.get_equity() * config.MAX_POSITION_PCT, 2)

    def buy(self, symbol: str):
        if not self.check_daily_loss_limit():
            return
        if self.get_position_qty(symbol) > 0:
            logger.debug("Already long %s, skipping buy.", symbol)
            return
        notional = self._calc_notional()
        req = MarketOrderRequest(
            symbol=symbol,
            notional=notional,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = self._client.submit_order(req)
        logger.info("BUY  %s  notional=$%.2f  order_id=%s", symbol, notional, order.id)

    def buy_manual(self, symbol: str, qty: float):
        """
        Place a manual market buy from the UI with an explicit share quantity.
        Raises ValueError with a human-readable message on any failure.
        """
        symbol = symbol.upper().strip()
        if not symbol:
            raise ValueError("Symbol cannot be empty.")
        if qty <= 0:
            raise ValueError("Quantity must be greater than 0 shares.")
        if not self.check_daily_loss_limit():
            raise ValueError("Daily loss limit reached — no new orders allowed today.")
        if self.get_position_qty(symbol) > 0:
            raise ValueError(f"Already holding a position in {symbol}.")
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = self._client.submit_order(req)
        logger.info("MANUAL BUY  %s  qty=%.4f  order_id=%s", symbol, qty, order.id)
        return order

    def sell(self, symbol: str):
        qty = self.get_position_qty(symbol)
        if qty <= 0:
            logger.debug("No position in %s, skipping sell.", symbol)
            return
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = self._client.submit_order(req)
        logger.info("SELL %s  qty=%.4f  order_id=%s", symbol, qty, order.id)

    def close_all_positions(self):
        """Flatten all open positions — call this at end-of-day."""
        self._client.close_all_positions(cancel_orders=True)
        logger.info("All positions closed.")
