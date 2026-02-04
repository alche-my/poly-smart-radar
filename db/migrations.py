import sqlite3

from db.models import init_db


def run_migrations(db_path: str) -> None:
    init_db(db_path)
    _add_trader_classification_columns(db_path)


def _add_trader_classification_columns(db_path: str) -> None:
    """Add trader_type and strategy_type to existing traders table."""
    conn = sqlite3.connect(db_path)
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(traders)").fetchall()]
        if "trader_type" not in cols:
            conn.execute("ALTER TABLE traders ADD COLUMN trader_type TEXT DEFAULT 'UNKNOWN'")
        if "strategy_type" not in cols:
            conn.execute("ALTER TABLE traders ADD COLUMN strategy_type TEXT DEFAULT 'UNKNOWN'")
        conn.commit()
    finally:
        conn.close()
