import json
from datetime import datetime, timedelta

import pytest

from db.models import upsert_trader, insert_changes, get_unsent_signals
from modules.signal_detector import (
    calc_freshness,
    calc_category_match,
    calc_signal_score,
    SignalDetector,
)


class TestCalcFreshness:
    def test_very_fresh(self):
        now = datetime.utcnow().isoformat()
        assert calc_freshness(now) == 2.0

    def test_one_hour(self):
        ts = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        assert calc_freshness(ts) == 2.0

    def test_three_hours(self):
        ts = (datetime.utcnow() - timedelta(hours=3)).isoformat()
        assert calc_freshness(ts) == 1.5

    def test_twelve_hours(self):
        ts = (datetime.utcnow() - timedelta(hours=12)).isoformat()
        assert calc_freshness(ts) == 1.0

    def test_thirty_hours(self):
        ts = (datetime.utcnow() - timedelta(hours=30)).isoformat()
        assert calc_freshness(ts) == 0.5

    def test_very_old(self):
        ts = (datetime.utcnow() - timedelta(hours=100)).isoformat()
        assert calc_freshness(ts) == 0.0

    def test_invalid_timestamp(self):
        assert calc_freshness("not-a-date") == 0.5

    def test_none(self):
        assert calc_freshness(None) == 0.5


class TestCalcCategoryMatch:
    def test_matching_category(self):
        trader = {"category_scores": '{"POLITICS": 5.0, "CRYPTO": 3.0}'}
        assert calc_category_match(trader, "POLITICS") == 1.5

    def test_no_matching_category(self):
        trader = {"category_scores": '{"POLITICS": 5.0}'}
        assert calc_category_match(trader, "SPORTS") == 1.0

    def test_no_category(self):
        trader = {"category_scores": '{"POLITICS": 5.0}'}
        assert calc_category_match(trader, None) == 1.0

    def test_empty_scores(self):
        trader = {"category_scores": "{}"}
        assert calc_category_match(trader, "POLITICS") == 1.0

    def test_dict_scores(self):
        trader = {"category_scores": {"CRYPTO": 4.0}}
        assert calc_category_match(trader, "CRYPTO") == 1.5

    def test_zero_score_not_matched(self):
        trader = {"category_scores": '{"POLITICS": 0}'}
        assert calc_category_match(trader, "POLITICS") == 1.0


class TestCalcSignalScore:
    def test_basic(self):
        traders_data = [
            {"trader_score": 5.0, "conviction": 2.0, "category_match": 1.5, "freshness": 2.0},
            {"trader_score": 3.0, "conviction": 1.0, "category_match": 1.0, "freshness": 1.5},
        ]
        # 5*2*1.5*2 + 3*1*1*1.5 = 30 + 4.5 = 34.5
        assert calc_signal_score(traders_data) == 34.5

    def test_single_trader(self):
        traders_data = [
            {"trader_score": 8.0, "conviction": 1.5, "category_match": 1.0, "freshness": 2.0},
        ]
        assert calc_signal_score(traders_data) == 24.0

    def test_empty(self):
        assert calc_signal_score([]) == 0.0


def _insert_test_traders(db_path):
    for wallet, score in [("0xAAA", 8.0), ("0xBBB", 5.0), ("0xCCC", 3.0)]:
        upsert_trader(db_path, {
            "wallet_address": wallet,
            "username": f"trader_{wallet}",
            "trader_score": score,
            "category_scores": {"POLITICS": 4.0},
            "avg_position_size": 100,
            "total_closed": 50,
            "win_rate": 0.65,
            "roi": 0.15,
        })


def _insert_convergence(db_path, wallets, condition_id="c1", change_type="OPEN"):
    now = datetime.utcnow().isoformat()
    changes = []
    for w in wallets:
        changes.append({
            "wallet_address": w,
            "condition_id": condition_id,
            "title": "Will Trump win?",
            "slug": "trump-win",
            "event_slug": "trump-election",
            "outcome": "YES",
            "change_type": change_type,
            "old_size": 0,
            "new_size": 200,
            "price_at_change": 0.6,
            "conviction_score": 1.2,
            "detected_at": now,
        })
    insert_changes(db_path, changes)


class TestSignalDetector:
    def test_tier1_three_traders(self, db_path):
        _insert_test_traders(db_path)
        _insert_convergence(db_path, ["0xAAA", "0xBBB", "0xCCC"])
        detector = SignalDetector(db_path)
        signals = detector.detect_signals()
        assert len(signals) == 1

        unsent = get_unsent_signals(db_path)
        assert len(unsent) == 1
        assert unsent[0]["tier"] == 1
        assert unsent[0]["status"] == "ACTIVE"
        assert unsent[0]["signal_score"] > 15.0

    def test_tier2_two_traders(self, db_path):
        _insert_test_traders(db_path)
        _insert_convergence(db_path, ["0xAAA", "0xBBB"])
        detector = SignalDetector(db_path)
        signals = detector.detect_signals()
        assert len(signals) == 1

        unsent = get_unsent_signals(db_path)
        assert unsent[0]["tier"] == 2

    def test_no_signal_single_regular_trader(self, db_path):
        _insert_test_traders(db_path)
        _insert_convergence(db_path, ["0xCCC"])  # low score, normal conviction
        detector = SignalDetector(db_path)
        signals = detector.detect_signals()
        assert len(signals) == 0

    def test_mixed_directions_no_signal(self, db_path):
        _insert_test_traders(db_path)
        now = datetime.utcnow().isoformat()
        insert_changes(db_path, [
            {"wallet_address": "0xAAA", "condition_id": "c1", "title": "Market",
             "slug": "", "event_slug": "", "outcome": "YES",
             "change_type": "OPEN", "old_size": 0, "new_size": 100,
             "price_at_change": 0.6, "conviction_score": 1.0, "detected_at": now},
            {"wallet_address": "0xBBB", "condition_id": "c1", "title": "Market",
             "slug": "", "event_slug": "", "outcome": "YES",
             "change_type": "CLOSE", "old_size": 100, "new_size": 0,
             "price_at_change": 0.6, "conviction_score": 1.0, "detected_at": now},
        ])
        detector = SignalDetector(db_path)
        signals = detector.detect_signals()
        assert len(signals) == 0

    def test_dedup_updates_existing(self, db_path):
        _insert_test_traders(db_path)
        _insert_convergence(db_path, ["0xAAA", "0xBBB"])
        detector = SignalDetector(db_path)

        # First detection
        detector.detect_signals()
        unsent1 = get_unsent_signals(db_path)
        assert len(unsent1) == 1
        score1 = unsent1[0]["signal_score"]

        # Add another trader to the same market
        _insert_convergence(db_path, ["0xCCC"])

        # Second detection — should update, not create new
        detector.detect_signals()
        unsent2 = get_unsent_signals(db_path)
        assert len(unsent2) == 1
        assert unsent2[0]["signal_score"] >= score1

    def test_direction_field(self, db_path):
        _insert_test_traders(db_path)
        _insert_convergence(db_path, ["0xAAA", "0xBBB"])
        detector = SignalDetector(db_path)
        detector.detect_signals()
        unsent = get_unsent_signals(db_path)
        assert unsent[0]["direction"] == "YES"

    def test_traders_involved_stored(self, db_path):
        _insert_test_traders(db_path)
        _insert_convergence(db_path, ["0xAAA", "0xBBB"])
        detector = SignalDetector(db_path)
        detector.detect_signals()
        unsent = get_unsent_signals(db_path)
        involved = json.loads(unsent[0]["traders_involved"])
        wallets = {t["wallet_address"] for t in involved}
        assert wallets == {"0xAAA", "0xBBB"}

    def test_no_changes_no_signals(self, db_path):
        _insert_test_traders(db_path)
        detector = SignalDetector(db_path)
        signals = detector.detect_signals()
        assert len(signals) == 0
