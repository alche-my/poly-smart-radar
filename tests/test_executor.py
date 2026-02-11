"""Tests for bot/executor.py — core trading logic with mocked CLOB client."""

import json
import sqlite3
from datetime import datetime, date
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

import config
from db.models import init_db, _get_connection, insert_signal, mark_signal_sent, update_signal
from bot.executor import BotExecutor
from bot.clob_trading import MarketInfo, OrderResult


def _seed_signal(db_path, sent=True, **overrides):
    """Insert a test signal and return its ID."""
    base = {
        "condition_id": "c_test",
        "market_title": "Test Market",
        "market_slug": "test",
        "direction": "YES",
        "signal_score": 20.0,
        "peak_score": 20.0,
        "tier": 1,
        "status": "ACTIVE",
        "traders_involved": [],
        "current_price": 0.50,
        "market_category": "POLITICS",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "sent": False,
    }
    base.update(overrides)
    sid = insert_signal(db_path, base)
    if sent:
        mark_signal_sent(db_path, sid)
    return sid


def _get_bot_trades(db_path):
    """Get all bot_trades rows."""
    conn = _get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM bot_trades ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _make_market_info(**overrides):
    base = {
        "condition_id": "c_test",
        "token_id": "tok_123",
        "outcome": "YES",
        "accepting_orders": True,
        "minimum_order_size": 0.01,
        "minimum_tick_size": 0.01,
        "neg_risk": False,
    }
    base.update(overrides)
    return MarketInfo(**base)


class TestGetTradeableSignals:
    def test_returns_sent_active_untraded(self, db_path):
        _seed_signal(db_path, sent=True)
        executor = BotExecutor(db_path)
        signals = executor._get_tradeable_signals()
        assert len(signals) == 1

    def test_excludes_unsent(self, db_path):
        _seed_signal(db_path, sent=False)
        executor = BotExecutor(db_path)
        signals = executor._get_tradeable_signals()
        assert len(signals) == 0

    def test_excludes_already_traded(self, db_path):
        sid = _seed_signal(db_path, sent=True)
        # Insert a bot_trade for this signal
        conn = _get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO bot_trades (signal_id, condition_id, direction, "
                "status, created_at, updated_at) "
                "VALUES (?, 'c_test', 'YES', 'OPEN', ?, ?)",
                (sid, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

        executor = BotExecutor(db_path)
        signals = executor._get_tradeable_signals()
        assert len(signals) == 0

    def test_excludes_resolved(self, db_path):
        _seed_signal(db_path, sent=True)
        # Mark signal as resolved
        conn = _get_connection(db_path)
        try:
            conn.execute(
                "UPDATE signals SET resolved_at = ? WHERE condition_id = 'c_test'",
                (datetime.utcnow().isoformat(),),
            )
            conn.commit()
        finally:
            conn.close()

        executor = BotExecutor(db_path)
        signals = executor._get_tradeable_signals()
        assert len(signals) == 0

    def test_excludes_bad_categories(self, db_path):
        _seed_signal(db_path, sent=True, market_category="CRYPTO")
        executor = BotExecutor(db_path)
        signals = executor._get_tradeable_signals()
        assert len(signals) == 0


@pytest.mark.asyncio
class TestExecuteTrade:
    async def test_success(self, db_path):
        sid = _seed_signal(db_path, sent=True)
        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        executor._clob.resolve_token_id.return_value = _make_market_info()
        executor._clob.get_current_price.return_value = 0.50
        executor._clob.get_balance.return_value = 8.0
        executor._clob.place_market_order.return_value = OrderResult(
            success=True, order_id="ord_abc", cost_usd=0.50, shares_filled=1.0,
        )

        signal = executor._get_tradeable_signals()[0]
        result = await executor._execute_trade(signal)
        assert result == "traded"

        trades = _get_bot_trades(db_path)
        assert len(trades) == 1
        assert trades[0]["status"] == "OPEN"
        assert trades[0]["order_id"] == "ord_abc"

    async def test_market_not_accepting_orders(self, db_path):
        _seed_signal(db_path, sent=True)
        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        executor._clob.resolve_token_id.return_value = _make_market_info(
            accepting_orders=False
        )

        signal = executor._get_tradeable_signals()[0]
        result = await executor._execute_trade(signal)
        assert result == "skipped"
        assert len(_get_bot_trades(db_path)) == 0

    async def test_below_minimum_order_size(self, db_path):
        _seed_signal(db_path, sent=True)
        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        executor._clob.resolve_token_id.return_value = _make_market_info(
            minimum_order_size=5.0
        )

        signal = executor._get_tradeable_signals()[0]
        result = await executor._execute_trade(signal)
        assert result == "skipped"

    async def test_risk_blocked(self, db_path):
        _seed_signal(db_path, sent=True)
        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        executor._clob.resolve_token_id.return_value = _make_market_info()
        executor._clob.get_current_price.return_value = 0.50
        executor._clob.get_balance.return_value = 1.0  # Below min balance

        signal = executor._get_tradeable_signals()[0]
        result = await executor._execute_trade(signal)
        assert result == "skipped"
        assert len(_get_bot_trades(db_path)) == 0

    async def test_order_failure(self, db_path):
        _seed_signal(db_path, sent=True)
        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        executor._clob.resolve_token_id.return_value = _make_market_info()
        executor._clob.get_current_price.return_value = 0.50
        executor._clob.get_balance.return_value = 8.0
        executor._clob.place_market_order.return_value = OrderResult(
            success=False, error_message="Insufficient liquidity"
        )

        signal = executor._get_tradeable_signals()[0]
        result = await executor._execute_trade(signal)
        assert result == "error"

        trades = _get_bot_trades(db_path)
        assert len(trades) == 1
        assert trades[0]["status"] == "FAILED"
        assert trades[0]["error_message"] == "Insufficient liquidity"

    async def test_token_resolution_failure(self, db_path):
        _seed_signal(db_path, sent=True)
        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        executor._clob.resolve_token_id.return_value = None

        signal = executor._get_tradeable_signals()[0]
        result = await executor._execute_trade(signal)
        assert result == "error"


@pytest.mark.asyncio
class TestProcessResolutions:
    async def test_win(self, db_path):
        sid = _seed_signal(db_path, sent=True)
        # Insert open trade
        conn = _get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO bot_trades (signal_id, condition_id, market_title, "
                "direction, status, entry_price, cost_usd, shares, "
                "created_at, updated_at) "
                "VALUES (?, 'c_test', 'Test', 'YES', 'OPEN', 0.40, 0.50, 1.25, ?, ?)",
                (sid, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
            )
            # Mark signal as resolved YES
            conn.execute(
                "UPDATE signals SET resolved_at = ?, resolution_outcome = 'YES' "
                "WHERE id = ?",
                (datetime.utcnow().isoformat(), sid),
            )
            conn.commit()
        finally:
            conn.close()

        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        count = await executor.process_resolutions()
        assert count == 1

        trades = _get_bot_trades(db_path)
        assert trades[0]["status"] == "WON"
        assert trades[0]["pnl_usd"] > 0  # Won: payout > cost
        assert trades[0]["resolution_outcome"] == "YES"

    async def test_loss(self, db_path):
        sid = _seed_signal(db_path, sent=True)
        conn = _get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO bot_trades (signal_id, condition_id, market_title, "
                "direction, status, entry_price, cost_usd, shares, "
                "created_at, updated_at) "
                "VALUES (?, 'c_test', 'Test', 'YES', 'OPEN', 0.40, 0.50, 1.25, ?, ?)",
                (sid, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
            )
            conn.execute(
                "UPDATE signals SET resolved_at = ?, resolution_outcome = 'NO' "
                "WHERE id = ?",
                (datetime.utcnow().isoformat(), sid),
            )
            conn.commit()
        finally:
            conn.close()

        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        count = await executor.process_resolutions()
        assert count == 1

        trades = _get_bot_trades(db_path)
        assert trades[0]["status"] == "LOST"
        assert trades[0]["pnl_usd"] == -0.50


@pytest.mark.asyncio
class TestRecoverUnconfirmed:
    async def test_recover_with_order_id(self, db_path):
        sid = _seed_signal(db_path, sent=True)
        conn = _get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO bot_trades (signal_id, condition_id, direction, "
                "order_id, status, created_at, updated_at) "
                "VALUES (?, 'c_test', 'YES', 'ord_123', 'PLACED', ?, ?)",
                (sid, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        await executor._recover_unconfirmed()

        trades = _get_bot_trades(db_path)
        assert trades[0]["status"] == "OPEN"

    async def test_recover_without_order_id(self, db_path):
        sid = _seed_signal(db_path, sent=True)
        conn = _get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO bot_trades (signal_id, condition_id, direction, "
                "status, created_at, updated_at) "
                "VALUES (?, 'c_test', 'YES', 'PLACED', ?, ?)",
                (sid, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        await executor._recover_unconfirmed()

        trades = _get_bot_trades(db_path)
        assert trades[0]["status"] == "FAILED"


@pytest.mark.asyncio
class TestExecuteOnNewSignals:
    async def test_not_initialized(self, db_path):
        executor = BotExecutor(db_path)
        result = await executor.execute_on_new_signals()
        assert result == {"traded": 0, "skipped": 0, "errors": 0}

    async def test_no_signals(self, db_path):
        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        result = await executor.execute_on_new_signals()
        assert result["traded"] == 0

    async def test_counts_errors_from_exception(self, db_path):
        sid = _seed_signal(db_path, sent=True)
        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        executor._clob.resolve_token_id.side_effect = RuntimeError("boom")

        result = await executor.execute_on_new_signals()
        assert result["errors"] == 1
        assert result["traded"] == 0


@pytest.mark.asyncio
class TestSendDailySummary:
    async def test_not_initialized(self, db_path):
        executor = BotExecutor(db_path)
        result = await executor.send_daily_summary()
        assert result is False

    async def test_empty_db(self, db_path):
        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        executor._clob.get_balance.return_value = 10.0

        result = await executor.send_daily_summary()
        assert result is True

    async def test_with_trades(self, db_path):
        sid = _seed_signal(db_path, sent=True)
        now = datetime.utcnow().isoformat()
        conn = _get_connection(db_path)
        try:
            # Open trade
            conn.execute(
                "INSERT INTO bot_trades (signal_id, condition_id, market_title, "
                "direction, status, entry_price, cost_usd, shares, "
                "created_at, updated_at) "
                "VALUES (?, 'c_test', 'Test', 'YES', 'OPEN', 0.50, 0.50, 1.0, ?, ?)",
                (sid, now, now),
            )
            conn.commit()
        finally:
            conn.close()

        sid2 = _seed_signal(db_path, sent=True, condition_id="c_test2")
        conn = _get_connection(db_path)
        try:
            # Won trade
            conn.execute(
                "INSERT INTO bot_trades (signal_id, condition_id, market_title, "
                "direction, status, entry_price, cost_usd, shares, pnl_usd, "
                "created_at, updated_at, resolved_at) "
                "VALUES (?, 'c_test2', 'Test2', 'YES', 'WON', 0.40, 0.50, 1.25, 0.75, ?, ?, ?)",
                (sid2, now, now, now),
            )
            conn.commit()
        finally:
            conn.close()

        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        executor._clob.get_balance.return_value = 9.50

        result = await executor.send_daily_summary()
        assert result is True

    async def test_with_peak_balance(self, db_path):
        conn = _get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO bot_state (key, value, updated_at) VALUES (?, ?, ?)",
                ("peak_balance", "15.0", datetime.utcnow().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

        executor = BotExecutor(db_path)
        executor._initialized = True
        executor._clob = AsyncMock()
        executor._clob.get_balance.return_value = 12.0

        result = await executor.send_daily_summary()
        assert result is True


@pytest.mark.asyncio
class TestInsertTrade:
    async def test_insert_and_retrieve(self, db_path):
        sid = _seed_signal(db_path, sent=True)
        executor = BotExecutor(db_path)
        now = datetime.utcnow().isoformat()
        trade_data = {
            "signal_id": sid,
            "condition_id": "c_test",
            "market_title": "Test",
            "direction": "YES",
            "token_id": "tok_1",
            "order_id": "ord_1",
            "status": "OPEN",
            "entry_price": 0.45,
            "cost_usd": 0.50,
            "shares": 1.11,
            "created_at": now,
            "updated_at": now,
            "error_message": None,
        }
        trade_id = executor._insert_trade(trade_data)
        assert trade_id > 0

        trades = _get_bot_trades(db_path)
        assert len(trades) == 1
        assert trades[0]["token_id"] == "tok_1"
        assert trades[0]["entry_price"] == 0.45

    async def test_insert_failed_trade(self, db_path):
        sid = _seed_signal(db_path, sent=True)
        executor = BotExecutor(db_path)
        now = datetime.utcnow().isoformat()
        trade_data = {
            "signal_id": sid,
            "condition_id": "c_test",
            "market_title": "Test",
            "direction": "YES",
            "token_id": None,
            "order_id": None,
            "status": "FAILED",
            "entry_price": 0,
            "cost_usd": 0,
            "shares": 0,
            "created_at": now,
            "updated_at": now,
            "error_message": "Network error",
        }
        trade_id = executor._insert_trade(trade_data)
        trades = _get_bot_trades(db_path)
        assert trades[0]["status"] == "FAILED"
        assert trades[0]["error_message"] == "Network error"


@pytest.mark.asyncio
class TestUpdateTrade:
    async def test_update_status(self, db_path):
        sid = _seed_signal(db_path, sent=True)
        executor = BotExecutor(db_path)
        now = datetime.utcnow().isoformat()
        trade_id = executor._insert_trade({
            "signal_id": sid, "condition_id": "c_test",
            "direction": "YES", "status": "PLACED",
            "created_at": now, "updated_at": now,
        })

        executor._update_trade(trade_id, {"status": "OPEN"})
        trades = _get_bot_trades(db_path)
        assert trades[0]["status"] == "OPEN"

    async def test_update_multiple_fields(self, db_path):
        sid = _seed_signal(db_path, sent=True)
        executor = BotExecutor(db_path)
        now = datetime.utcnow().isoformat()
        trade_id = executor._insert_trade({
            "signal_id": sid, "condition_id": "c_test",
            "direction": "YES", "status": "OPEN",
            "entry_price": 0.5, "cost_usd": 0.5,
            "created_at": now, "updated_at": now,
        })

        executor._update_trade(trade_id, {
            "status": "WON",
            "pnl_usd": 0.50,
            "pnl_pct": 1.0,
            "resolution_outcome": "YES",
        })
        trades = _get_bot_trades(db_path)
        assert trades[0]["status"] == "WON"
        assert trades[0]["pnl_usd"] == 0.50
        assert trades[0]["resolution_outcome"] == "YES"
