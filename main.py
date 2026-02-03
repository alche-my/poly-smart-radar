import argparse
import asyncio
import logging
import signal
import sys

import config
from scheduler import RadarScheduler

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("radar")


async def run_once(scheduler: RadarScheduler) -> None:
    from db.migrations import run_migrations
    run_migrations(scheduler.db_path)
    try:
        result = await scheduler.scan_cycle()
        logger.info("Single cycle result: %s", result)
    finally:
        await scheduler.close()


async def rebuild_watchlist(scheduler: RadarScheduler) -> None:
    from db.migrations import run_migrations
    from db.models import get_traders
    run_migrations(scheduler.db_path)
    try:
        count = await scheduler.watchlist_builder.build_watchlist()
        logger.info("Watchlist rebuilt: %d traders", count)
        traders = get_traders(scheduler.db_path)
        logger.info("Top 10 traders:")
        for i, t in enumerate(traders[:10], 1):
            logger.info(
                "  %d. %s — score %.2f, WR %.0f%%, ROI %.1f%%, closed %d",
                i,
                t.get("username") or t["wallet_address"][:10],
                t.get("trader_score", 0),
                t.get("win_rate", 0) * 100,
                t.get("roi", 0) * 100,
                t.get("total_closed", 0),
            )
    finally:
        await scheduler.close()


async def run_daemon(scheduler: RadarScheduler) -> None:
    loop = asyncio.get_event_loop()

    def handle_shutdown(sig, frame):
        logger.info("Received %s, shutting down...", signal.Signals(sig).name)
        scheduler.stop()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    try:
        await scheduler.start()
    finally:
        await scheduler.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Polymarket Whale Radar")
    parser.add_argument("--once", action="store_true", help="Run one scan cycle and exit")
    parser.add_argument("--rebuild-watchlist", action="store_true", help="Rebuild watchlist and exit")
    args = parser.parse_args()

    scheduler = RadarScheduler(db_path=config.DB_PATH)

    if args.rebuild_watchlist:
        asyncio.run(rebuild_watchlist(scheduler))
    elif args.once:
        asyncio.run(run_once(scheduler))
    else:
        asyncio.run(run_daemon(scheduler))


if __name__ == "__main__":
    main()
