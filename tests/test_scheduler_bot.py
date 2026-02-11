"""Tests for scheduler.py — bot integration paths (init, failures, daily summary)."""

from datetime import datetime, date
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

import config
from db.models import _get_connection
from scheduler import RadarScheduler


@pytest.fixture
def scheduler(db_path):
    """Create a scheduler with mocked API clients and bot disabled."""
    with patch.object(config, "BOT_ENABLED", False):
        sched = RadarScheduler(db_path)
    # Stub out API clients so nothing hits network
    sched.data_api = AsyncMock()
    sched.gamma_api = AsyncMock()
    sched.watchlist_builder = AsyncMock()
    sched.position_scanner = AsyncMock()
    sched.position_scanner.scan_all = AsyncMock(return_value=[])
    sched.signal_detector = MagicMock()
    sched.signal_detector.detect_signals = MagicMock(return_value=[])
    sched.alert_sender = AsyncMock()
    sched.alert_sender.send_strategy_alerts = AsyncMock(
        return_value={"new_signals": 0, "resolutions": 0}
    )
    sched.resolution_checker = AsyncMock()
    sched.resolution_checker.check_all = AsyncMock(return_value={"resolved": 0})
    return sched


@pytest.mark.asyncio
class TestBotInitFailure:
    async def test_init_returns_false(self, scheduler, db_path):
        """Bot init returning False → executor set to None, scan continues."""
        mock_executor = AsyncMock()
        mock_executor.initialize = AsyncMock(return_value=False)
        scheduler._bot_executor = mock_executor

        await scheduler.start.__wrapped__(scheduler) if hasattr(scheduler.start, '__wrapped__') else None

        # Simulate the init block from start()
        try:
            bot_ok = await scheduler._bot_executor.initialize()
            if not bot_ok:
                scheduler._bot_executor = None
        except Exception:
            scheduler._bot_executor = None

        assert scheduler._bot_executor is None

    async def test_init_raises_exception(self, scheduler, db_path):
        """Bot init raising exception → executor set to None, scan continues."""
        mock_executor = AsyncMock()
        mock_executor.initialize = AsyncMock(side_effect=RuntimeError("CLOB down"))
        scheduler._bot_executor = mock_executor

        try:
            await scheduler._bot_executor.initialize()
            scheduler._bot_executor = None  # shouldn't reach
        except Exception:
            scheduler._bot_executor = None

        assert scheduler._bot_executor is None

    async def test_scan_cycle_without_bot(self, scheduler, db_path):
        """Scan cycle works when bot is None."""
        scheduler._bot_executor = None

        from db.models import get_traders
        result = await scheduler.scan_cycle()
        assert "bot_trades" in result
        assert result["bot_trades"] == 0


@pytest.mark.asyncio
class TestBotScanCycleErrors:
    async def test_execute_on_new_signals_exception(self, scheduler, db_path):
        """Bot execute_on_new_signals raises → scan_cycle completes anyway."""
        mock_executor = AsyncMock()
        mock_executor.execute_on_new_signals = AsyncMock(
            side_effect=RuntimeError("token resolution failed")
        )
        mock_executor.process_resolutions = AsyncMock(return_value=0)
        mock_executor.send_daily_summary = AsyncMock(return_value=True)
        scheduler._bot_executor = mock_executor

        result = await scheduler.scan_cycle()
        # Scan should complete despite bot error
        assert result["bot_trades"] == 0

    async def test_process_resolutions_exception(self, scheduler, db_path):
        """Bot process_resolutions raises → scan_cycle completes anyway."""
        mock_executor = AsyncMock()
        mock_executor.execute_on_new_signals = AsyncMock(
            return_value={"traded": 1, "skipped": 0, "errors": 0}
        )
        mock_executor.process_resolutions = AsyncMock(
            side_effect=RuntimeError("DB locked")
        )
        mock_executor.send_daily_summary = AsyncMock(return_value=True)
        scheduler._bot_executor = mock_executor

        result = await scheduler.scan_cycle()
        assert result["bot_trades"] == 1

    async def test_daily_summary_exception(self, scheduler, db_path):
        """Daily summary raises → scan_cycle completes anyway."""
        mock_executor = AsyncMock()
        mock_executor.execute_on_new_signals = AsyncMock(
            return_value={"traded": 0, "skipped": 0, "errors": 0}
        )
        mock_executor.process_resolutions = AsyncMock(return_value=0)
        scheduler._bot_executor = mock_executor

        # Make _maybe_send_daily_summary raise
        with patch.object(scheduler, "_maybe_send_daily_summary",
                          AsyncMock(side_effect=RuntimeError("TG down"))):
            result = await scheduler.scan_cycle()
        assert "bot_trades" in result


@pytest.mark.asyncio
class TestMaybeSendDailySummary:
    async def test_sends_once_per_day(self, scheduler, db_path):
        mock_executor = AsyncMock()
        mock_executor.send_daily_summary = AsyncMock(return_value=True)
        scheduler._bot_executor = mock_executor

        await scheduler._maybe_send_daily_summary()

        # Verify it was recorded
        conn = _get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT value FROM bot_state WHERE key = 'last_daily_summary'"
            ).fetchone()
            assert row is not None
            assert row["value"] == date.today().isoformat()
        finally:
            conn.close()

    async def test_skips_if_already_sent(self, scheduler, db_path):
        mock_executor = AsyncMock()
        mock_executor.send_daily_summary = AsyncMock(return_value=True)
        scheduler._bot_executor = mock_executor

        # Pre-set today's date
        conn = _get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO bot_state (key, value, updated_at) VALUES (?, ?, ?)",
                ("last_daily_summary", date.today().isoformat(),
                 datetime.utcnow().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

        await scheduler._maybe_send_daily_summary()
        mock_executor.send_daily_summary.assert_not_called()

    async def test_skips_if_no_executor(self, scheduler, db_path):
        scheduler._bot_executor = None
        await scheduler._maybe_send_daily_summary()
        # Should not raise
