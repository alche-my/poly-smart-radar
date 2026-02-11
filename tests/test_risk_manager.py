"""Tests for bot/risk_manager.py — all safety checks."""

import sqlite3
from datetime import datetime, date

import config
from db.models import init_db, _get_connection, insert_signal
from bot.risk_manager import RiskManager


def _seed_signal(db_path, **overrides):
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
        "sent": True,
    }
    base.update(overrides)
    return insert_signal(db_path, base)


def _seed_bot_trade(db_path, signal_id, **overrides):
    """Insert a test bot_trade record."""
    base = {
        "signal_id": signal_id,
        "condition_id": "c_test",
        "market_title": "Test Market",
        "direction": "YES",
        "token_id": "tok_123",
        "order_id": "ord_123",
        "status": "OPEN",
        "entry_price": 0.50,
        "cost_usd": 0.50,
        "shares": 1.0,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    base.update(overrides)
    conn = _get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO bot_trades (
                signal_id, condition_id, market_title, direction,
                token_id, order_id, status, entry_price,
                cost_usd, shares, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                base["signal_id"], base["condition_id"], base["market_title"],
                base["direction"], base["token_id"], base["order_id"],
                base["status"], base["entry_price"], base["cost_usd"],
                base["shares"], base["created_at"], base["updated_at"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _set_bot_state(db_path, key, value):
    """Set a bot_state value."""
    conn = _get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO bot_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value, datetime.utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


class TestCheckMinBalance:
    def test_pass(self, db_path):
        rm = RiskManager(db_path)
        ok, reason = rm._check_min_balance(5.0)
        assert ok
        assert reason == "OK"

    def test_fail(self, db_path):
        rm = RiskManager(db_path)
        ok, reason = rm._check_min_balance(1.50)
        assert not ok
        assert "below minimum" in reason


class TestCheckCircuitBreaker:
    def test_pass_no_drawdown(self, db_path):
        _set_bot_state(db_path, "peak_balance", "10.0")
        rm = RiskManager(db_path)
        ok, reason = rm._check_circuit_breaker(8.0)
        assert ok

    def test_fail_drawdown_exceeded(self, db_path):
        _set_bot_state(db_path, "peak_balance", "10.0")
        rm = RiskManager(db_path)
        ok, reason = rm._check_circuit_breaker(6.0)
        assert not ok
        assert "circuit breaker" in reason.lower()

        # Verify it was persisted
        conn = _get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT value FROM bot_state WHERE key = 'circuit_breaker_active'"
            ).fetchone()
            assert row["value"] == "1"
        finally:
            conn.close()

    def test_updates_peak(self, db_path):
        _set_bot_state(db_path, "peak_balance", "10.0")
        rm = RiskManager(db_path)
        ok, _ = rm._check_circuit_breaker(12.0)
        assert ok

        conn = _get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT value FROM bot_state WHERE key = 'peak_balance'"
            ).fetchone()
            assert float(row["value"]) == 12.0
        finally:
            conn.close()

    def test_default_peak_from_config(self, db_path):
        rm = RiskManager(db_path)
        # No peak_balance in DB — uses config.BOT_INITIAL_BUDGET (10.0)
        ok, _ = rm._check_circuit_breaker(8.0)
        assert ok  # 8.0 > 10.0 * 0.7 = 7.0


class TestCheckMaxOpenPositions:
    def test_pass_no_positions(self, db_path):
        rm = RiskManager(db_path)
        ok, reason = rm._check_max_open_positions()
        assert ok

    def test_fail_at_limit(self, db_path):
        # Create signals and bot_trades up to the limit
        for i in range(config.BOT_MAX_OPEN_POSITIONS):
            sid = _seed_signal(db_path, condition_id=f"c_{i}")
            _seed_bot_trade(db_path, sid, condition_id=f"c_{i}", status="OPEN")

        rm = RiskManager(db_path)
        ok, reason = rm._check_max_open_positions()
        assert not ok
        assert "Max open positions" in reason


class TestCheckDailySpend:
    def test_pass_no_trades_today(self, db_path):
        rm = RiskManager(db_path)
        ok, reason = rm._check_daily_spend()
        assert ok

    def test_fail_at_limit(self, db_path):
        # Spend up to the daily limit
        for i in range(5):  # 5 * $0.50 = $2.50
            sid = _seed_signal(db_path, condition_id=f"c_{i}")
            _seed_bot_trade(db_path, sid, condition_id=f"c_{i}")

        rm = RiskManager(db_path)
        ok, reason = rm._check_daily_spend()
        assert not ok
        assert "Daily spend limit" in reason


class TestCheckDuplicateMarket:
    def test_pass_no_existing(self, db_path):
        rm = RiskManager(db_path)
        ok, reason = rm._check_duplicate_market("c_new")
        assert ok

    def test_fail_existing(self, db_path):
        sid = _seed_signal(db_path, condition_id="c_dup")
        _seed_bot_trade(db_path, sid, condition_id="c_dup", status="OPEN")

        rm = RiskManager(db_path)
        ok, reason = rm._check_duplicate_market("c_dup")
        assert not ok
        assert "Duplicate" in reason

    def test_pass_resolved_trade(self, db_path):
        sid = _seed_signal(db_path, condition_id="c_done")
        _seed_bot_trade(db_path, sid, condition_id="c_done", status="WON")

        rm = RiskManager(db_path)
        ok, reason = rm._check_duplicate_market("c_done")
        assert ok


class TestCheckPriceSlippage:
    def test_pass_within_tolerance(self, db_path):
        rm = RiskManager(db_path)
        signal = {"current_price": 0.50}
        ok, reason = rm._check_price_slippage(signal, 0.55)
        assert ok

    def test_fail_exceeded(self, db_path):
        rm = RiskManager(db_path)
        signal = {"current_price": 0.50}
        ok, reason = rm._check_price_slippage(signal, 0.70)
        assert not ok
        assert "slippage" in reason.lower()

    def test_pass_no_current_price(self, db_path):
        rm = RiskManager(db_path)
        signal = {"current_price": 0.50}
        ok, reason = rm._check_price_slippage(signal, None)
        assert ok

    def test_pass_no_signal_price(self, db_path):
        rm = RiskManager(db_path)
        signal = {"current_price": 0}
        ok, reason = rm._check_price_slippage(signal, 0.50)
        assert ok


class TestCheckBotEnabled:
    def test_pass_no_circuit_breaker(self, db_path):
        rm = RiskManager(db_path)
        ok, reason = rm._check_bot_enabled()
        assert ok

    def test_fail_circuit_breaker_active(self, db_path):
        _set_bot_state(db_path, "circuit_breaker_active", "1")
        rm = RiskManager(db_path)
        ok, reason = rm._check_bot_enabled()
        assert not ok
        assert "Circuit breaker" in reason


class TestCheckAll:
    def test_all_pass(self, db_path):
        _set_bot_state(db_path, "peak_balance", "10.0")
        rm = RiskManager(db_path)
        signal = {"condition_id": "c_new", "current_price": 0.50}
        ok, reason = rm.check_all(signal, current_balance=8.0, current_price=0.52)
        assert ok
        assert reason == "OK"

    def test_fails_on_first_check(self, db_path):
        _set_bot_state(db_path, "circuit_breaker_active", "1")
        rm = RiskManager(db_path)
        signal = {"condition_id": "c_new", "current_price": 0.50}
        ok, reason = rm.check_all(signal, current_balance=8.0, current_price=0.52)
        assert not ok
        assert "Circuit breaker" in reason


class TestResetCircuitBreaker:
    def test_reset(self, db_path):
        _set_bot_state(db_path, "circuit_breaker_active", "1")
        rm = RiskManager(db_path)

        ok, _ = rm._check_bot_enabled()
        assert not ok

        rm.reset_circuit_breaker()

        ok, _ = rm._check_bot_enabled()
        assert ok
