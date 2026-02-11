import asyncio
import logging
from datetime import datetime, timedelta

import config
from api.data_api import DataApiClient
from api.gamma_api import GammaApiClient
from db.models import get_traders, delete_old_snapshots
from db.migrations import run_migrations
from modules.watchlist_builder import WatchlistBuilder
from modules.position_scanner import PositionScanner
from modules.signal_detector import SignalDetector
from modules.alert_sender import AlertSender
from modules.resolution_checker import ResolutionChecker

logger = logging.getLogger(__name__)


class RadarScheduler:
    def __init__(self, db_path: str = config.DB_PATH):
        self.db_path = db_path
        self.data_api = DataApiClient()
        self.gamma_api = GammaApiClient()
        self.watchlist_builder = WatchlistBuilder(self.data_api, self.gamma_api, db_path)
        self.position_scanner = PositionScanner(self.data_api, db_path)
        self.signal_detector = SignalDetector(db_path)
        self.alert_sender = AlertSender(db_path=db_path)
        self.resolution_checker = ResolutionChecker(self.gamma_api, db_path)
        self._running = False

        # Trading bot (optional — only active if BOT_ENABLED=true)
        self._bot_executor = None
        if config.BOT_ENABLED:
            from bot.executor import BotExecutor
            self._bot_executor = BotExecutor(db_path)

    async def start(self) -> None:
        run_migrations(self.db_path)

        # Build watchlist if empty
        traders = get_traders(self.db_path)
        if not traders:
            logger.info("Watchlist empty, building...")
            await self.watchlist_builder.build_watchlist()

        self._running = True

        # Initialize bot if enabled
        if self._bot_executor:
            try:
                bot_ok = await self._bot_executor.initialize()
                if bot_ok:
                    logger.info("Trading bot initialized and active")
                else:
                    logger.warning("Trading bot failed to initialize — running without bot")
                    self._bot_executor = None
            except Exception as e:
                logger.error("Trading bot crashed during init: %s", e, exc_info=True)
                self._bot_executor = None

        logger.info(
            "Scheduler started: scan every %dm, watchlist update every %dh",
            config.SCAN_INTERVAL_MINUTES,
            config.WATCHLIST_UPDATE_HOURS,
        )

        scan_interval = config.SCAN_INTERVAL_MINUTES * 60
        watchlist_interval = config.WATCHLIST_UPDATE_HOURS * 3600
        cleanup_interval = 86400  # daily

        last_watchlist = datetime.utcnow()
        last_cleanup = datetime.utcnow()

        while self._running:
            await self.scan_cycle()

            now = datetime.utcnow()
            if (now - last_watchlist).total_seconds() >= watchlist_interval:
                logger.info("Scheduled watchlist rebuild")
                await self.watchlist_builder.build_watchlist()
                last_watchlist = now

            if (now - last_cleanup).total_seconds() >= cleanup_interval:
                self._cleanup_old_data()
                last_cleanup = now

            await asyncio.sleep(scan_interval)

    async def scan_cycle(self) -> dict:
        logger.info("--- Scan cycle start ---")
        changes = await self.position_scanner.scan_all()
        signals = self.signal_detector.detect_signals()

        # Enrich new signals with current market price
        await self._enrich_market_prices(signals)

        # Check resolutions of existing signals
        res_result = await self.resolution_checker.check_all()

        # Strategy-filtered notifications: new signals + resolutions
        alert_result = await self.alert_sender.send_strategy_alerts()
        sent = alert_result.get("new_signals", 0) + alert_result.get("resolutions", 0)

        # Execute bot trades on new signals + process resolutions
        bot_traded = 0
        if self._bot_executor:
            try:
                bot_result = await self._bot_executor.execute_on_new_signals()
                bot_traded = bot_result.get("traded", 0)
            except Exception as e:
                logger.error("Bot execute_on_new_signals failed: %s", e, exc_info=True)

            try:
                await self._bot_executor.process_resolutions()
            except Exception as e:
                logger.error("Bot process_resolutions failed: %s", e, exc_info=True)

            try:
                await self._maybe_send_daily_summary()
            except Exception as e:
                logger.error("Bot daily summary failed: %s", e, exc_info=True)

        traders_count = len(get_traders(self.db_path))
        result = {
            "traders_scanned": traders_count,
            "changes_detected": len(changes),
            "signals_created": len(signals),
            "alerts_sent": sent,
            "resolutions_found": res_result.get("resolved", 0),
            "bot_trades": bot_traded,
        }
        logger.info(
            "--- Scan cycle done: %d traders, %d changes, %d signals, %d resolved ---",
            result["traders_scanned"],
            result["changes_detected"],
            result["signals_created"],
            result["resolutions_found"],
        )
        return result

    async def _enrich_market_prices(self, signals: list[dict]) -> None:
        """Fetch current market price for newly created signals via Gamma API."""
        from db.models import _get_connection, update_signal

        new_signals = [s for s in signals if s.get("new")]
        if not new_signals:
            return

        conn = _get_connection(self.db_path)
        try:
            for sig in new_signals:
                sid = sig.get("id")
                cid = sig.get("condition_id")
                if not sid or not cid:
                    continue
                try:
                    # Fetch signal to get direction
                    row = conn.execute(
                        "SELECT direction FROM signals WHERE id = ?", (sid,)
                    ).fetchone()
                    if not row:
                        continue
                    direction = row["direction"]

                    market = await self.gamma_api.get_market_by_condition(cid)
                    if not market:
                        continue

                    # Parse outcomePrices — JSON string like "[0.35, 0.65]"
                    outcome_prices = market.get("outcomePrices")
                    if isinstance(outcome_prices, str):
                        import json
                        outcome_prices = json.loads(outcome_prices)

                    if outcome_prices and len(outcome_prices) >= 2:
                        # outcomePrices[0] = YES price, outcomePrices[1] = NO price
                        if direction == "YES":
                            market_price = float(outcome_prices[0])
                        else:
                            market_price = float(outcome_prices[1])
                    else:
                        continue

                    update_signal(self.db_path, sid, {
                        "market_price_at_signal": market_price,
                    })
                    logger.info(
                        "Signal %d: market price at signal = %.4f",
                        sid, market_price,
                    )
                except Exception as e:
                    logger.warning("Failed to enrich signal %s: %s", sid, e)
        finally:
            conn.close()

    async def _maybe_send_daily_summary(self) -> None:
        """Send bot daily summary once per day."""
        if not self._bot_executor:
            return
        from db.models import _get_connection
        from datetime import date

        conn = _get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT value FROM bot_state WHERE key = 'last_daily_summary'"
            ).fetchone()
            last_date = row["value"] if row else ""
            today = date.today().isoformat()
            if last_date == today:
                return
        finally:
            conn.close()

        await self._bot_executor.send_daily_summary()

        conn = _get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO bot_state (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (
                    "last_daily_summary",
                    date.today().isoformat(),
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def _cleanup_old_data(self) -> None:
        cutoff = (
            datetime.utcnow() - timedelta(days=config.SNAPSHOT_RETENTION_DAYS)
        ).isoformat()
        deleted = delete_old_snapshots(self.db_path, cutoff)
        if deleted:
            logger.info("Cleaned up %d old snapshots (older than %d days)",
                        deleted, config.SNAPSHOT_RETENTION_DAYS)

    def stop(self) -> None:
        self._running = False
        logger.info("Scheduler stopping...")

    async def close(self) -> None:
        self.stop()
        await self.data_api.close()
        await self.gamma_api.close()
        logger.info("All API clients closed")
