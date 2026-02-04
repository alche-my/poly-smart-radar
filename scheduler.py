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
        self._running = False

    async def start(self) -> None:
        run_migrations(self.db_path)

        # Build watchlist if empty
        traders = get_traders(self.db_path)
        if not traders:
            logger.info("Watchlist empty, building...")
            await self.watchlist_builder.build_watchlist()

        self._running = True
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
        sent = await self.alert_sender.send_pending_alerts()

        traders_count = len(get_traders(self.db_path))
        result = {
            "traders_scanned": traders_count,
            "changes_detected": len(changes),
            "signals_created": len(signals),
            "alerts_sent": sent,
        }
        logger.info(
            "--- Scan cycle done: %d traders, %d changes, %d signals, %d alerts ---",
            result["traders_scanned"],
            result["changes_detected"],
            result["signals_created"],
            result["alerts_sent"],
        )
        return result

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
        await self.alert_sender.close()
        logger.info("All API clients closed")
