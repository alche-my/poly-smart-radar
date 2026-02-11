"""Tests for db/migrations.py — migration edge cases."""

import os
import tempfile

import pytest

from db.models import init_db, _get_connection, _TABLES
from db.migrations import run_migrations


@pytest.fixture
def fresh_db():
    """Create a fresh DB (no migrations)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


class TestColumnMigrations:
    def test_idempotent(self, fresh_db):
        """Running migrations twice doesn't fail."""
        run_migrations(fresh_db)
        run_migrations(fresh_db)

        conn = _get_connection(fresh_db)
        try:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(signals)").fetchall()
            }
            assert "resolved_at" in cols
            assert "market_category" in cols
        finally:
            conn.close()

    def test_adds_all_signal_columns(self, fresh_db):
        """All migration columns are present after run."""
        run_migrations(fresh_db)
        expected = {
            "resolved_at", "resolution_outcome", "pnl_percent",
            "market_price_at_signal", "resolution_alert_sent", "market_category",
        }
        conn = _get_connection(fresh_db)
        try:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(signals)").fetchall()
            }
            assert expected.issubset(cols)
        finally:
            conn.close()


class TestTableMigrations:
    def test_creates_bot_tables(self, fresh_db):
        """Bot tables are created during migration."""
        run_migrations(fresh_db)
        conn = _get_connection(fresh_db)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "bot_trades" in tables
            assert "bot_state" in tables
        finally:
            conn.close()

    def test_bot_tables_idempotent(self, fresh_db):
        """Creating bot tables twice doesn't fail."""
        run_migrations(fresh_db)
        run_migrations(fresh_db)

        conn = _get_connection(fresh_db)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "bot_trades" in tables
            assert "bot_state" in tables
        finally:
            conn.close()

    def test_bot_tables_on_existing_db_without_them(self, fresh_db):
        """If DB has base tables but not bot tables, migration adds them.

        Simulates an older DB by creating all tables then dropping bot tables.
        """
        init_db(fresh_db)

        # Simulate pre-bot DB by dropping bot tables
        conn = _get_connection(fresh_db)
        try:
            conn.execute("DROP TABLE IF EXISTS bot_trades")
            conn.execute("DROP TABLE IF EXISTS bot_state")
            conn.commit()
        finally:
            conn.close()

        conn = _get_connection(fresh_db)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "bot_trades" not in tables
        finally:
            conn.close()

        # Now run full migrations
        run_migrations(fresh_db)

        conn = _get_connection(fresh_db)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "bot_trades" in tables
            assert "bot_state" in tables
        finally:
            conn.close()

    def test_bot_trades_schema(self, fresh_db):
        """Verify bot_trades has all expected columns."""
        run_migrations(fresh_db)
        conn = _get_connection(fresh_db)
        try:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(bot_trades)").fetchall()
            }
            expected = {
                "id", "signal_id", "condition_id", "market_title",
                "direction", "token_id", "order_id", "status",
                "entry_price", "cost_usd", "shares", "pnl_usd",
                "pnl_pct", "resolution_outcome", "error_message",
                "created_at", "updated_at", "resolved_at",
            }
            assert expected.issubset(cols)
        finally:
            conn.close()

    def test_bot_state_schema(self, fresh_db):
        """Verify bot_state has all expected columns."""
        run_migrations(fresh_db)
        conn = _get_connection(fresh_db)
        try:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(bot_state)").fetchall()
            }
            assert {"key", "value", "updated_at"}.issubset(cols)
        finally:
            conn.close()

    def test_bot_trades_indexes(self, fresh_db):
        """Verify bot_trades indexes exist."""
        run_migrations(fresh_db)
        conn = _get_connection(fresh_db)
        try:
            indexes = {
                row[1]
                for row in conn.execute(
                    "PRAGMA index_list(bot_trades)"
                ).fetchall()
                if row[1]  # skip unnamed indexes
            }
            assert "idx_bot_trades_status" in indexes
            assert "idx_bot_trades_signal" in indexes
            assert "idx_bot_trades_condition" in indexes
            assert "idx_bot_trades_created" in indexes
        finally:
            conn.close()
