import json
import sqlite3
from datetime import datetime, timedelta

from api.base import is_valid_wallet
from db.models import (
    _SIGNAL_UPDATABLE_FIELDS,
    init_db,
    upsert_trader,
    get_traders,
    get_trader,
    insert_snapshots,
    get_latest_snapshots,
    delete_old_snapshots,
    insert_changes,
    get_recent_changes,
    insert_signal,
    update_signal,
    get_active_signal,
    get_unsent_signals,
    mark_signal_sent,
)


def _make_trader(wallet="0xAAA", score=5.0, **overrides):
    base = {
        "wallet_address": wallet,
        "username": "test_trader",
        "profile_image": None,
        "x_username": None,
        "trader_score": score,
        "category_scores": {"POLITICS": 4.0},
        "avg_position_size": 100,
        "total_closed": 50,
        "win_rate": 0.65,
        "roi": 0.15,
    }
    base.update(overrides)
    return base


class TestInitDb:
    def test_creates_all_tables(self, db_path):
        conn = sqlite3.connect(db_path)
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        conn.close()
        assert "traders" in tables
        assert "position_snapshots" in tables
        assert "position_changes" in tables
        assert "signals" in tables

    def test_creates_indexes(self, db_path):
        conn = sqlite3.connect(db_path)
        indexes = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            ).fetchall()
        ]
        conn.close()
        assert len(indexes) == 7

    def test_idempotent(self, db_path):
        init_db(db_path)
        init_db(db_path)
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        conn.close()
        assert len(tables) == 4


class TestTraders:
    def test_upsert_and_get(self, db_path):
        upsert_trader(db_path, _make_trader("0xAAA", score=5.0))
        traders = get_traders(db_path)
        assert len(traders) == 1
        assert traders[0]["wallet_address"] == "0xAAA"
        assert traders[0]["trader_score"] == 5.0

    def test_upsert_updates_existing(self, db_path):
        upsert_trader(db_path, _make_trader("0xAAA", score=5.0))
        upsert_trader(db_path, _make_trader("0xAAA", score=9.0, username="updated"))
        traders = get_traders(db_path)
        assert len(traders) == 1
        assert traders[0]["trader_score"] == 9.0
        assert traders[0]["username"] == "updated"

    def test_get_trader_by_address(self, db_path):
        upsert_trader(db_path, _make_trader("0xAAA"))
        upsert_trader(db_path, _make_trader("0xBBB", score=3.0))
        t = get_trader(db_path, "0xBBB")
        assert t is not None
        assert t["wallet_address"] == "0xBBB"

    def test_get_trader_not_found(self, db_path):
        assert get_trader(db_path, "0xNONE") is None

    def test_get_traders_ordered_by_score(self, db_path):
        upsert_trader(db_path, _make_trader("0xA", score=3.0))
        upsert_trader(db_path, _make_trader("0xB", score=9.0))
        upsert_trader(db_path, _make_trader("0xC", score=6.0))
        traders = get_traders(db_path)
        scores = [t["trader_score"] for t in traders]
        assert scores == [9.0, 6.0, 3.0]

    def test_category_scores_stored_as_json(self, db_path):
        cats = {"POLITICS": 4.0, "CRYPTO": 2.5}
        upsert_trader(db_path, _make_trader("0xA", category_scores=cats))
        t = get_trader(db_path, "0xA")
        parsed = json.loads(t["category_scores"])
        assert parsed == cats


class TestSnapshots:
    def test_insert_and_get_latest(self, db_path):
        upsert_trader(db_path, _make_trader("0xA"))
        now = datetime.utcnow().isoformat()
        insert_snapshots(db_path, [
            {"wallet_address": "0xA", "condition_id": "c1", "title": "M1",
             "slug": "m1", "outcome": "YES", "size": 100, "avg_price": 0.5,
             "current_value": 60, "cur_price": 0.6, "scanned_at": now},
            {"wallet_address": "0xA", "condition_id": "c2", "title": "M2",
             "slug": "m2", "outcome": "NO", "size": 50, "avg_price": 0.3,
             "current_value": 15, "cur_price": 0.3, "scanned_at": now},
        ])
        latest = get_latest_snapshots(db_path, "0xA")
        assert len(latest) == 2
        cids = {s["condition_id"] for s in latest}
        assert cids == {"c1", "c2"}

    def test_latest_returns_only_most_recent(self, db_path):
        upsert_trader(db_path, _make_trader("0xA"))
        old = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        new = datetime.utcnow().isoformat()
        insert_snapshots(db_path, [
            {"wallet_address": "0xA", "condition_id": "c1", "title": "M",
             "slug": "", "outcome": "YES", "size": 100, "avg_price": 0.5,
             "current_value": 50, "cur_price": 0.5, "scanned_at": old},
        ])
        insert_snapshots(db_path, [
            {"wallet_address": "0xA", "condition_id": "c1", "title": "M",
             "slug": "", "outcome": "YES", "size": 200, "avg_price": 0.5,
             "current_value": 100, "cur_price": 0.5, "scanned_at": new},
        ])
        latest = get_latest_snapshots(db_path, "0xA")
        assert len(latest) == 1
        assert latest[0]["size"] == 200

    def test_no_snapshots_returns_empty(self, db_path):
        assert get_latest_snapshots(db_path, "0xNONE") == []

    def test_delete_old(self, db_path):
        upsert_trader(db_path, _make_trader("0xA"))
        old = (datetime.utcnow() - timedelta(days=31)).isoformat()
        new = datetime.utcnow().isoformat()
        insert_snapshots(db_path, [
            {"wallet_address": "0xA", "condition_id": "c1", "title": "M",
             "slug": "", "outcome": "YES", "size": 100, "avg_price": 0.5,
             "current_value": 50, "cur_price": 0.5, "scanned_at": old},
        ])
        insert_snapshots(db_path, [
            {"wallet_address": "0xA", "condition_id": "c2", "title": "M2",
             "slug": "", "outcome": "YES", "size": 50, "avg_price": 0.5,
             "current_value": 25, "cur_price": 0.5, "scanned_at": new},
        ])
        cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
        deleted = delete_old_snapshots(db_path, cutoff)
        assert deleted == 1

    def test_insert_empty_list(self, db_path):
        insert_snapshots(db_path, [])


class TestChanges:
    def test_insert_and_get_recent(self, db_path):
        upsert_trader(db_path, _make_trader("0xA"))
        now = datetime.utcnow().isoformat()
        insert_changes(db_path, [
            {"wallet_address": "0xA", "condition_id": "c1", "title": "M",
             "slug": "", "event_slug": "", "outcome": "YES",
             "change_type": "OPEN", "old_size": 0, "new_size": 100,
             "price_at_change": 0.6, "conviction_score": 1.2,
             "detected_at": now},
        ])
        since = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        changes = get_recent_changes(db_path, since)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "OPEN"

    def test_old_changes_not_returned(self, db_path):
        upsert_trader(db_path, _make_trader("0xA"))
        old = (datetime.utcnow() - timedelta(hours=25)).isoformat()
        insert_changes(db_path, [
            {"wallet_address": "0xA", "condition_id": "c1", "title": "M",
             "slug": "", "event_slug": "", "outcome": "YES",
             "change_type": "OPEN", "old_size": 0, "new_size": 100,
             "price_at_change": 0.6, "conviction_score": 1.0,
             "detected_at": old},
        ])
        since = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        changes = get_recent_changes(db_path, since)
        assert len(changes) == 0

    def test_insert_empty_list(self, db_path):
        insert_changes(db_path, [])


class TestSignals:
    def _make_signal(self, **overrides):
        base = {
            "condition_id": "c1",
            "market_title": "Test Market",
            "market_slug": "test",
            "direction": "YES",
            "signal_score": 20.0,
            "peak_score": 20.0,
            "tier": 1,
            "status": "ACTIVE",
            "traders_involved": [{"wallet": "0xA"}],
            "current_price": 0.6,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "sent": False,
        }
        base.update(overrides)
        return base

    def test_insert_and_get_unsent(self, db_path):
        sid = insert_signal(db_path, self._make_signal())
        assert sid > 0
        unsent = get_unsent_signals(db_path)
        assert len(unsent) == 1
        assert unsent[0]["condition_id"] == "c1"

    def test_mark_sent(self, db_path):
        sid = insert_signal(db_path, self._make_signal())
        mark_signal_sent(db_path, sid)
        unsent = get_unsent_signals(db_path)
        assert len(unsent) == 0

    def test_update_signal(self, db_path):
        sid = insert_signal(db_path, self._make_signal(signal_score=10.0))
        update_signal(db_path, sid, {
            "signal_score": 25.0,
            "status": "WEAKENING",
        })
        unsent = get_unsent_signals(db_path)
        assert unsent[0]["signal_score"] == 25.0
        assert unsent[0]["status"] == "WEAKENING"

    def test_get_active_signal_found(self, db_path):
        since = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        insert_signal(db_path, self._make_signal())
        found = get_active_signal(db_path, "c1", "YES", since)
        assert found is not None
        assert found["condition_id"] == "c1"

    def test_get_active_signal_not_found_wrong_direction(self, db_path):
        since = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        insert_signal(db_path, self._make_signal(direction="YES"))
        found = get_active_signal(db_path, "c1", "NO", since)
        assert found is None

    def test_get_active_signal_ignores_closed(self, db_path):
        since = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        insert_signal(db_path, self._make_signal(status="CLOSED"))
        found = get_active_signal(db_path, "c1", "YES", since)
        assert found is None

    def test_traders_involved_json_roundtrip(self, db_path):
        traders = [{"wallet": "0xA", "score": 5.0}, {"wallet": "0xB", "score": 3.0}]
        sid = insert_signal(db_path, self._make_signal(traders_involved=traders))
        unsent = get_unsent_signals(db_path)
        parsed = json.loads(unsent[0]["traders_involved"])
        assert len(parsed) == 2
        assert parsed[0]["wallet"] == "0xA"

    def test_update_signal_rejects_unknown_fields(self, db_path):
        """update_signal silently ignores fields not in the whitelist."""
        sid = insert_signal(db_path, self._make_signal())
        # "drop_table" is not in _SIGNAL_UPDATABLE_FIELDS
        update_signal(db_path, sid, {"status": "WEAKENING", "drop_table": "evil"})
        unsent = get_unsent_signals(db_path)
        # The valid field should be updated
        assert unsent[0]["status"] == "WEAKENING"

    def test_signal_updatable_fields_whitelist(self):
        """All expected fields are in the whitelist."""
        expected = {"signal_score", "peak_score", "tier", "status",
                    "traders_involved", "current_price", "updated_at", "sent"}
        assert _SIGNAL_UPDATABLE_FIELDS == expected


class TestWalletValidation:
    def test_valid_wallet(self):
        assert is_valid_wallet("0x1234567890abcdef1234567890abcdef12345678")

    def test_valid_uppercase(self):
        assert is_valid_wallet("0xABCDEF1234567890ABCDEF1234567890ABCDEF12")

    def test_missing_prefix(self):
        assert not is_valid_wallet("1234567890abcdef1234567890abcdef12345678")

    def test_too_short(self):
        assert not is_valid_wallet("0x1234")

    def test_too_long(self):
        assert not is_valid_wallet("0x1234567890abcdef1234567890abcdef1234567890")

    def test_invalid_chars(self):
        assert not is_valid_wallet("0xGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG")

    def test_empty_string(self):
        assert not is_valid_wallet("")
