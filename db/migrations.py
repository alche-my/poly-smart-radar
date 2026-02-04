import sqlite3

from db.models import init_db


def run_migrations(db_path: str) -> None:
    init_db(db_path)
    _add_trader_classification_columns(db_path)


def _add_trader_classification_columns(db_path: str) -> None:
    """Add classification columns to existing traders table."""
    conn = sqlite3.connect(db_path)
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(traders)").fetchall()]
        for col, default in [
            ("trader_type", "'UNKNOWN'"),
            ("strategy_type", "'UNKNOWN'"),
            ("domain_tags", "'[]'"),
            ("recent_bets", "'[]'"),
        ]:
            if col not in cols:
                conn.execute(f"ALTER TABLE traders ADD COLUMN {col} TEXT DEFAULT {default}")
        conn.commit()
    finally:
        conn.close()
