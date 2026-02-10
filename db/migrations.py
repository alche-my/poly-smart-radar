import logging
import sqlite3

from db.models import init_db, _get_connection

logger = logging.getLogger(__name__)

_ALTER_MIGRATIONS = [
    ("signals", "resolved_at", "ALTER TABLE signals ADD COLUMN resolved_at TIMESTAMP"),
    ("signals", "resolution_outcome", "ALTER TABLE signals ADD COLUMN resolution_outcome TEXT"),
    ("signals", "pnl_percent", "ALTER TABLE signals ADD COLUMN pnl_percent REAL"),
]


def run_migrations(db_path: str) -> None:
    init_db(db_path)
    conn = _get_connection(db_path)
    try:
        for table, column, sql in _ALTER_MIGRATIONS:
            existing = {
                row[1]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column not in existing:
                conn.execute(sql)
                logger.info("Migration: added %s.%s", table, column)
        conn.commit()
    finally:
        conn.close()
