import os
import sqlite3
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_TABLES = {
    "traders": """
        CREATE TABLE IF NOT EXISTS traders (
            wallet_address TEXT PRIMARY KEY,
            username TEXT,
            profile_image TEXT,
            x_username TEXT,
            trader_score REAL DEFAULT 0,
            category_scores TEXT DEFAULT '{}',
            avg_position_size REAL DEFAULT 0,
            total_closed INTEGER DEFAULT 0,
            win_rate REAL DEFAULT 0,
            roi REAL DEFAULT 0,
            timing_quality REAL DEFAULT 0,
            pnl REAL DEFAULT 0,
            volume REAL DEFAULT 0,
            last_updated TIMESTAMP
        )
    """,
    "position_snapshots": """
        CREATE TABLE IF NOT EXISTS position_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            condition_id TEXT NOT NULL,
            title TEXT,
            slug TEXT,
            outcome TEXT,
            size REAL DEFAULT 0,
            avg_price REAL DEFAULT 0,
            current_value REAL DEFAULT 0,
            cur_price REAL DEFAULT 0,
            scanned_at TIMESTAMP NOT NULL,
            FOREIGN KEY (wallet_address) REFERENCES traders(wallet_address)
        )
    """,
    "position_changes": """
        CREATE TABLE IF NOT EXISTS position_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet_address TEXT NOT NULL,
            condition_id TEXT NOT NULL,
            title TEXT,
            slug TEXT,
            event_slug TEXT,
            outcome TEXT,
            change_type TEXT NOT NULL,
            old_size REAL DEFAULT 0,
            new_size REAL DEFAULT 0,
            price_at_change REAL DEFAULT 0,
            conviction_score REAL DEFAULT 0,
            detected_at TIMESTAMP NOT NULL,
            FOREIGN KEY (wallet_address) REFERENCES traders(wallet_address)
        )
    """,
    "signals": """
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            condition_id TEXT NOT NULL,
            market_title TEXT,
            market_slug TEXT,
            direction TEXT,
            signal_score REAL DEFAULT 0,
            peak_score REAL DEFAULT 0,
            tier INTEGER,
            status TEXT DEFAULT 'ACTIVE',
            traders_involved TEXT DEFAULT '[]',
            current_price REAL DEFAULT 0,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP,
            sent BOOLEAN DEFAULT 0
        )
    """,
}

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_snapshots_wallet_scanned ON position_snapshots(wallet_address, scanned_at)",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_scanned ON position_snapshots(scanned_at)",
    "CREATE INDEX IF NOT EXISTS idx_changes_detected ON position_changes(detected_at)",
    "CREATE INDEX IF NOT EXISTS idx_changes_condition ON position_changes(condition_id)",
    "CREATE INDEX IF NOT EXISTS idx_signals_condition_dir ON signals(condition_id, direction)",
    "CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status)",
    "CREATE INDEX IF NOT EXISTS idx_signals_sent ON signals(sent)",
]


def _get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str) -> None:
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = _get_connection(db_path)
    try:
        for name, ddl in _TABLES.items():
            conn.execute(ddl)
            logger.info("Table '%s' ready", name)
        for idx in _INDEXES:
            conn.execute(idx)
        conn.commit()
        logger.info("Database initialized at %s", db_path)
    finally:
        conn.close()


# --------------- traders ---------------

def upsert_trader(db_path: str, trader: dict) -> None:
    conn = _get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO traders (
                wallet_address, username, profile_image, x_username,
                trader_score, category_scores, avg_position_size,
                total_closed, win_rate, roi, timing_quality,
                pnl, volume, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(wallet_address) DO UPDATE SET
                username=excluded.username,
                profile_image=excluded.profile_image,
                x_username=excluded.x_username,
                trader_score=excluded.trader_score,
                category_scores=excluded.category_scores,
                avg_position_size=excluded.avg_position_size,
                total_closed=excluded.total_closed,
                win_rate=excluded.win_rate,
                roi=excluded.roi,
                timing_quality=excluded.timing_quality,
                pnl=excluded.pnl,
                volume=excluded.volume,
                last_updated=excluded.last_updated
            """,
            (
                trader["wallet_address"],
                trader.get("username"),
                trader.get("profile_image"),
                trader.get("x_username"),
                trader.get("trader_score", 0),
                json.dumps(trader.get("category_scores", {})),
                trader.get("avg_position_size", 0),
                trader.get("total_closed", 0),
                trader.get("win_rate", 0),
                trader.get("roi", 0),
                trader.get("timing_quality", 0),
                trader.get("pnl", 0),
                trader.get("volume", 0),
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_traders(db_path: str) -> list[dict]:
    conn = _get_connection(db_path)
    try:
        rows = conn.execute("SELECT * FROM traders ORDER BY trader_score DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_trader(db_path: str, wallet_address: str) -> dict | None:
    conn = _get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM traders WHERE wallet_address = ?", (wallet_address,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# --------------- position_snapshots ---------------

def insert_snapshots(db_path: str, snapshots: list[dict]) -> None:
    if not snapshots:
        return
    conn = _get_connection(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO position_snapshots (
                wallet_address, condition_id, title, slug,
                outcome, size, avg_price, current_value, cur_price, scanned_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    s["wallet_address"], s["condition_id"], s.get("title"),
                    s.get("slug"), s.get("outcome"), s.get("size", 0),
                    s.get("avg_price", 0), s.get("current_value", 0),
                    s.get("cur_price", 0), s["scanned_at"],
                )
                for s in snapshots
            ],
        )
        conn.commit()
    finally:
        conn.close()


def get_latest_snapshots(db_path: str, wallet_address: str) -> list[dict]:
    conn = _get_connection(db_path)
    try:
        latest = conn.execute(
            "SELECT MAX(scanned_at) FROM position_snapshots WHERE wallet_address = ?",
            (wallet_address,),
        ).fetchone()[0]
        if not latest:
            return []
        rows = conn.execute(
            "SELECT * FROM position_snapshots WHERE wallet_address = ? AND scanned_at = ?",
            (wallet_address, latest),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_old_snapshots(db_path: str, before_iso: str) -> int:
    conn = _get_connection(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM position_snapshots WHERE scanned_at < ?", (before_iso,)
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# --------------- position_changes ---------------

def insert_changes(db_path: str, changes: list[dict]) -> None:
    if not changes:
        return
    conn = _get_connection(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO position_changes (
                wallet_address, condition_id, title, slug, event_slug,
                outcome, change_type, old_size, new_size,
                price_at_change, conviction_score, detected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    c["wallet_address"], c["condition_id"], c.get("title"),
                    c.get("slug"), c.get("event_slug"), c.get("outcome"),
                    c["change_type"], c.get("old_size", 0), c.get("new_size", 0),
                    c.get("price_at_change", 0), c.get("conviction_score", 0),
                    c["detected_at"],
                )
                for c in changes
            ],
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_changes(db_path: str, since_iso: str) -> list[dict]:
    conn = _get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM position_changes WHERE detected_at >= ? ORDER BY detected_at DESC",
            (since_iso,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --------------- signals ---------------

def insert_signal(db_path: str, signal: dict) -> int:
    conn = _get_connection(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO signals (
                condition_id, market_title, market_slug, direction,
                signal_score, peak_score, tier, status,
                traders_involved, current_price, created_at, updated_at, sent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal["condition_id"], signal.get("market_title"),
                signal.get("market_slug"), signal.get("direction"),
                signal.get("signal_score", 0), signal.get("peak_score", 0),
                signal.get("tier"), signal.get("status", "ACTIVE"),
                json.dumps(signal.get("traders_involved", [])),
                signal.get("current_price", 0),
                signal.get("created_at", datetime.utcnow().isoformat()),
                signal.get("updated_at"),
                signal.get("sent", False),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_signal(db_path: str, signal_id: int, updates: dict) -> None:
    conn = _get_connection(db_path)
    try:
        fields = []
        values = []
        for key, val in updates.items():
            if key == "traders_involved":
                val = json.dumps(val)
            fields.append(f"{key} = ?")
            values.append(val)
        values.append(signal_id)
        conn.execute(
            f"UPDATE signals SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        conn.commit()
    finally:
        conn.close()


def get_active_signal(db_path: str, condition_id: str, direction: str, since_iso: str) -> dict | None:
    conn = _get_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT * FROM signals
            WHERE condition_id = ? AND direction = ? AND created_at >= ? AND status != 'CLOSED'
            ORDER BY created_at DESC LIMIT 1
            """,
            (condition_id, direction, since_iso),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_unsent_signals(db_path: str) -> list[dict]:
    conn = _get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM signals WHERE sent = 0 ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_signal_sent(db_path: str, signal_id: int) -> None:
    conn = _get_connection(db_path)
    try:
        conn.execute("UPDATE signals SET sent = 1 WHERE id = ?", (signal_id,))
        conn.commit()
    finally:
        conn.close()
