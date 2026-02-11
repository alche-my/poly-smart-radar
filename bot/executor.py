"""Bot executor — orchestrates the full trade lifecycle.

Wires together signal consumption, risk checks, order placement,
DB logging, and Telegram notifications.
"""

import json
import logging
from datetime import datetime, date

import aiohttp

import config
from db.models import _get_connection
from modules.alert_sender import passes_strategy_filter
from bot.clob_trading import ClobTradingClient
from bot.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class BotExecutor:
    """Executes trades based on radar signals, manages lifecycle."""

    def __init__(self, db_path: str = config.DB_PATH):
        self.db_path = db_path
        self.risk_manager = RiskManager(db_path)
        self._clob: ClobTradingClient | None = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize CLOB client. Returns False if wallet not configured."""
        if not config.BOT_PRIVATE_KEY:
            logger.warning("BOT_PRIVATE_KEY not set — bot disabled")
            return False
        self._clob = ClobTradingClient(config.BOT_PRIVATE_KEY)
        try:
            await self._clob.initialize()
            self._initialized = True
            await self._recover_unconfirmed()
            logger.info("Bot executor initialized")
            return True
        except Exception as e:
            logger.error("Failed to initialize bot: %s", e)
            return False

    async def execute_on_new_signals(self) -> dict:
        """Called each scan cycle. Find tradeable signals and execute.

        Returns dict with counts: traded, skipped, errors.
        """
        if not self._initialized:
            return {"traded": 0, "skipped": 0, "errors": 0}

        tradeable = self._get_tradeable_signals()
        traded = 0
        skipped = 0
        errors = 0

        for signal in tradeable:
            try:
                result = await self._execute_trade(signal)
                if result == "traded":
                    traded += 1
                elif result == "skipped":
                    skipped += 1
                else:
                    errors += 1
            except Exception as e:
                logger.error(
                    "Unexpected error trading signal %s: %s",
                    signal.get("id"),
                    e,
                )
                errors += 1

        if traded or errors:
            logger.info(
                "Bot cycle: %d traded, %d skipped, %d errors",
                traded, skipped, errors,
            )

        return {"traded": traded, "skipped": skipped, "errors": errors}

    async def process_resolutions(self) -> int:
        """Check open bot_trades whose signals have resolved. Update P&L."""
        if not self._initialized:
            return 0

        conn = _get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT bt.*,
                       s.resolution_outcome as signal_resolution,
                       s.resolved_at as signal_resolved_at
                FROM bot_trades bt
                JOIN signals s ON bt.signal_id = s.id
                WHERE bt.status = 'OPEN' AND s.resolved_at IS NOT NULL
                """
            ).fetchall()
        finally:
            conn.close()

        resolved_count = 0
        for row in [dict(r) for r in rows]:
            await self._resolve_trade(row)
            resolved_count += 1

        return resolved_count

    async def send_daily_summary(self) -> bool:
        """Send daily summary to bot Telegram chat."""
        if not self._initialized:
            return False

        conn = _get_connection(self.db_path)
        try:
            today = date.today().isoformat()

            today_trades = conn.execute(
                "SELECT * FROM bot_trades WHERE DATE(created_at) = ?",
                (today,),
            ).fetchall()

            open_trades = conn.execute(
                "SELECT * FROM bot_trades WHERE status = 'OPEN'"
            ).fetchall()

            resolved = conn.execute(
                "SELECT * FROM bot_trades WHERE status IN ('WON', 'LOST')"
            ).fetchall()

            today_count = len(today_trades)
            today_cost = sum(
                dict(t)["cost_usd"]
                for t in today_trades
                if dict(t)["status"] != "FAILED"
            )
            open_count = len(open_trades)
            open_exposure = sum(dict(t)["cost_usd"] for t in open_trades)
            total_pnl = sum(dict(t).get("pnl_usd", 0) or 0 for t in resolved)
            wins = sum(1 for t in resolved if dict(t)["status"] == "WON")
            losses = sum(1 for t in resolved if dict(t)["status"] == "LOST")
            total_resolved = wins + losses
            win_rate = wins / total_resolved if total_resolved > 0 else 0
        finally:
            conn.close()

        balance = await self._clob.get_balance()

        conn2 = _get_connection(self.db_path)
        try:
            peak_row = conn2.execute(
                "SELECT value FROM bot_state WHERE key = 'peak_balance'"
            ).fetchone()
            peak = float(peak_row["value"]) if peak_row else config.BOT_INITIAL_BUDGET
        finally:
            conn2.close()

        message = (
            f"{'=' * 30}\n"
            f"DAILY BOT SUMMARY\n"
            f"{'=' * 30}\n\n"
            f"Balance: ${balance:.2f} (peak: ${peak:.2f})\n"
            f"Open positions: {open_count} (${open_exposure:.2f} exposed)\n\n"
            f"Today: {today_count} trades, ${today_cost:.2f} spent\n"
            f"All-time: {total_resolved} resolved, "
            f"{wins}W/{losses}L ({win_rate:.0%} WR)\n"
            f"Total P&L: ${total_pnl:+.2f}\n"
        )

        return await self._send_bot_telegram(message)

    # ---- Internal methods ----

    def _get_tradeable_signals(self) -> list[dict]:
        """Get signals that pass strategy filter and haven't been traded yet."""
        conn = _get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT s.* FROM signals s
                WHERE s.sent = 1
                  AND s.status IN ('ACTIVE', 'WEAKENING')
                  AND s.resolved_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM bot_trades bt WHERE bt.signal_id = s.id
                  )
                ORDER BY s.signal_score DESC
                """
            ).fetchall()
        finally:
            conn.close()

        return [dict(r) for r in rows if passes_strategy_filter(dict(r))]

    async def _execute_trade(self, signal: dict) -> str:
        """Execute a single trade. Returns 'traded', 'skipped', or 'error'."""
        signal_id = signal["id"]
        condition_id = signal["condition_id"]
        direction = signal["direction"]

        # Step 1: Resolve token_id
        market_info = await self._clob.resolve_token_id(condition_id, direction)
        if not market_info:
            logger.warning(
                "Could not resolve token for signal %d (%s)",
                signal_id,
                condition_id[:16],
            )
            return "error"

        # Step 2: Pre-trade validation
        if not market_info.accepting_orders:
            logger.info("Market not accepting orders for signal %d", signal_id)
            return "skipped"

        if config.BOT_BET_SIZE < market_info.minimum_order_size:
            logger.info(
                "Bet size $%.2f below minimum $%.2f for signal %d",
                config.BOT_BET_SIZE,
                market_info.minimum_order_size,
                signal_id,
            )
            return "skipped"

        # Step 3: Get current price for slippage check
        current_price = await self._clob.get_current_price(market_info.token_id)

        # Step 4: Get balance
        balance = await self._clob.get_balance()

        # Step 5: Risk checks
        allowed, reason = self.risk_manager.check_all(signal, balance, current_price)
        if not allowed:
            logger.info("Trade blocked for signal %d: %s", signal_id, reason)
            if "circuit breaker" in reason.lower():
                await self._send_bot_telegram(
                    f"CIRCUIT BREAKER ACTIVATED\n\n{reason}"
                )
            return "skipped"

        # Step 6: Place order
        logger.info(
            "Placing order: signal %d, %s %s @ ~$%.3f, $%.2f",
            signal_id,
            direction,
            condition_id[:12],
            current_price or 0,
            config.BOT_BET_SIZE,
        )

        order_result = await self._clob.place_market_order(
            token_id=market_info.token_id,
            amount_usd=config.BOT_BET_SIZE,
        )

        # Step 7: Record trade
        now = datetime.utcnow().isoformat()
        trade_data = {
            "signal_id": signal_id,
            "condition_id": condition_id,
            "market_title": signal.get("market_title", ""),
            "direction": direction,
            "token_id": market_info.token_id,
            "order_id": order_result.order_id,
            "status": "OPEN" if order_result.success else "FAILED",
            "entry_price": current_price or signal.get("current_price", 0),
            "cost_usd": config.BOT_BET_SIZE if order_result.success else 0,
            "shares": order_result.shares_filled,
            "created_at": now,
            "updated_at": now,
            "error_message": order_result.error_message,
        }
        trade_id = self._insert_trade(trade_data)

        # Step 8: Send notification
        if order_result.success:
            entry = current_price or signal.get("current_price", 0)
            potential_payout = config.BOT_BET_SIZE / entry if entry > 0 else 0
            msg = (
                f"TRADE EXECUTED | #{trade_id}\n\n"
                f"{signal.get('market_title', 'Unknown')}\n"
                f"Direction: {direction} @ ${entry:.3f}\n"
                f"Cost: ${config.BOT_BET_SIZE:.2f}\n"
                f"Potential payout: ${potential_payout:.2f}\n"
                f"Signal: score {signal.get('signal_score', 0):.1f}, "
                f"Tier {signal.get('tier', '?')}\n"
                f"Balance: ${balance - config.BOT_BET_SIZE:.2f}"
            )
            await self._send_bot_telegram(msg)
            logger.info("Trade %d executed for signal %d", trade_id, signal_id)
            return "traded"
        else:
            msg = (
                f"TRADE FAILED | Signal #{signal_id}\n\n"
                f"{signal.get('market_title', 'Unknown')}\n"
                f"Reason: {order_result.error_message or 'Unknown error'}"
            )
            await self._send_bot_telegram(msg)
            logger.error(
                "Trade failed for signal %d: %s",
                signal_id,
                order_result.error_message,
            )
            return "error"

    async def _resolve_trade(self, trade: dict) -> None:
        """Resolve a trade whose market has been settled."""
        trade_id = trade["id"]
        direction = trade["direction"].upper()
        resolution = (trade.get("signal_resolution") or "").upper()
        entry_price = trade.get("entry_price", 0)
        cost_usd = trade.get("cost_usd", 0)

        won = direction == resolution
        if won and entry_price > 0:
            shares = cost_usd / entry_price
            payout = shares  # each share pays $1
            pnl_usd = payout - cost_usd
        else:
            pnl_usd = -cost_usd

        pnl_pct = (pnl_usd / cost_usd) if cost_usd > 0 else 0
        status = "WON" if won else "LOST"

        now = datetime.utcnow().isoformat()
        conn = _get_connection(self.db_path)
        try:
            conn.execute(
                """
                UPDATE bot_trades SET
                    status = ?, resolution_outcome = ?,
                    pnl_usd = ?, pnl_pct = ?,
                    resolved_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, resolution, pnl_usd, pnl_pct, now, now, trade_id),
            )
            conn.commit()
        finally:
            conn.close()

        result_emoji = "WIN" if won else "LOSS"
        msg = (
            f"POSITION RESOLVED | #{trade_id}\n\n"
            f"{trade.get('market_title', 'Unknown')}\n"
            f"Signal: {direction} @ ${entry_price:.3f}\n"
            f"Result: {resolution} -- {result_emoji}\n"
            f"P&L: ${pnl_usd:+.2f} ({pnl_pct:+.0%})\n"
            f"Cost: ${cost_usd:.2f}"
        )
        await self._send_bot_telegram(msg)
        logger.info(
            "Trade %d resolved: %s, P&L $%.2f (%.0f%%)",
            trade_id,
            status,
            pnl_usd,
            pnl_pct * 100,
        )

    async def _recover_unconfirmed(self) -> None:
        """On startup, check for PLACED trades that never confirmed.

        FOK orders either fill instantly or fail, so:
        - Has order_id -> mark OPEN (it filled)
        - No order_id -> mark FAILED
        """
        conn = _get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM bot_trades WHERE status = 'PLACED'"
            ).fetchall()
        finally:
            conn.close()

        for row in [dict(r) for r in rows]:
            trade_id = row["id"]
            if row.get("order_id"):
                self._update_trade(trade_id, {"status": "OPEN"})
                logger.info("Recovered trade %d as OPEN (has order_id)", trade_id)
            else:
                self._update_trade(
                    trade_id,
                    {
                        "status": "FAILED",
                        "error_message": "Unconfirmed after restart",
                    },
                )
                logger.warning("Marked trade %d as FAILED (no order_id)", trade_id)

    def _insert_trade(self, trade: dict) -> int:
        """Insert a new bot_trade record. Returns the trade ID."""
        conn = _get_connection(self.db_path)
        try:
            cur = conn.execute(
                """
                INSERT INTO bot_trades (
                    signal_id, condition_id, market_title, direction,
                    token_id, order_id, status, entry_price,
                    cost_usd, shares, created_at, updated_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade["signal_id"],
                    trade["condition_id"],
                    trade.get("market_title", ""),
                    trade["direction"],
                    trade.get("token_id"),
                    trade.get("order_id"),
                    trade["status"],
                    trade.get("entry_price", 0),
                    trade.get("cost_usd", 0),
                    trade.get("shares", 0),
                    trade["created_at"],
                    trade["updated_at"],
                    trade.get("error_message"),
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def _update_trade(self, trade_id: int, updates: dict) -> None:
        """Update a bot_trade record with arbitrary fields."""
        conn = _get_connection(self.db_path)
        try:
            fields = []
            values = []
            for key, val in updates.items():
                fields.append(f"{key} = ?")
                values.append(val)
            values.append(datetime.utcnow().isoformat())
            values.append(trade_id)
            conn.execute(
                f"UPDATE bot_trades SET {', '.join(fields)}, updated_at = ? "
                f"WHERE id = ?",
                values,
            )
            conn.commit()
        finally:
            conn.close()

    async def _send_bot_telegram(self, text: str) -> bool:
        """Send message to the bot-specific Telegram chat."""
        if not config.TELEGRAM_BOT_TOKEN or not config.BOT_TELEGRAM_CHAT_ID:
            logger.info("Bot Telegram not configured, logging:\n%s", text)
            return True

        try:
            url = (
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
            )
            payload = {
                "chat_id": config.BOT_TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        return True
                    body = await resp.text()
                    logger.error(
                        "Bot Telegram error %s: %s", resp.status, body[:200]
                    )
                    return False
        except Exception as e:
            logger.error("Failed to send bot Telegram: %s", e)
            return False
