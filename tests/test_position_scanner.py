import pytest

from modules.position_scanner import diff_positions, calc_conviction


class TestDiffPositions:
    def test_open(self):
        prev = []
        curr = [{"conditionId": "c1", "outcome": "YES", "size": "100", "curPrice": "0.6"}]
        changes = diff_positions(prev, curr)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "OPEN"
        assert changes[0]["old_size"] == 0
        assert changes[0]["new_size"] == 100

    def test_increase(self):
        prev = [{"conditionId": "c1", "outcome": "YES", "size": "100", "curPrice": "0.6"}]
        curr = [{"conditionId": "c1", "outcome": "YES", "size": "200", "curPrice": "0.65"}]
        changes = diff_positions(prev, curr)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "INCREASE"
        assert changes[0]["old_size"] == 100
        assert changes[0]["new_size"] == 200

    def test_decrease(self):
        prev = [{"conditionId": "c1", "outcome": "YES", "size": "200", "curPrice": "0.7"}]
        curr = [{"conditionId": "c1", "outcome": "YES", "size": "50", "curPrice": "0.65"}]
        changes = diff_positions(prev, curr)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "DECREASE"
        assert changes[0]["old_size"] == 200
        assert changes[0]["new_size"] == 50

    def test_close(self):
        prev = [{"conditionId": "c1", "outcome": "YES", "size": "100", "curPrice": "0.7"}]
        curr = []
        changes = diff_positions(prev, curr)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "CLOSE"
        assert changes[0]["new_size"] == 0

    def test_no_change(self):
        prev = [{"conditionId": "c1", "outcome": "YES", "size": "100", "curPrice": "0.7"}]
        curr = [{"conditionId": "c1", "outcome": "YES", "size": "100", "curPrice": "0.72"}]
        changes = diff_positions(prev, curr)
        assert len(changes) == 0

    def test_multiple_positions_mixed(self):
        prev = [
            {"conditionId": "c1", "outcome": "YES", "size": "100", "curPrice": "0.5"},
            {"conditionId": "c2", "outcome": "NO", "size": "50", "curPrice": "0.3"},
            {"conditionId": "c3", "outcome": "YES", "size": "200", "curPrice": "0.8"},
        ]
        curr = [
            {"conditionId": "c1", "outcome": "YES", "size": "100", "curPrice": "0.5"},  # no change
            {"conditionId": "c2", "outcome": "NO", "size": "80", "curPrice": "0.35"},   # increase
            {"conditionId": "c4", "outcome": "YES", "size": "60", "curPrice": "0.4"},   # open
            # c3 missing → close
        ]
        changes = diff_positions(prev, curr)
        types = {c["change_type"] for c in changes}
        assert types == {"INCREASE", "OPEN", "CLOSE"}

    def test_different_outcomes_same_condition(self):
        prev = [{"conditionId": "c1", "outcome": "YES", "size": "100", "curPrice": "0.6"}]
        curr = [
            {"conditionId": "c1", "outcome": "YES", "size": "100", "curPrice": "0.6"},
            {"conditionId": "c1", "outcome": "NO", "size": "50", "curPrice": "0.4"},
        ]
        changes = diff_positions(prev, curr)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "OPEN"
        assert changes[0]["outcome"] == "NO"

    def test_empty_both(self):
        assert diff_positions([], []) == []

    def test_uses_normalized_keys(self):
        # Tests that condition_id (snake_case) also works as a key
        prev = [{"condition_id": "c1", "outcome": "YES", "size": "100", "cur_price": "0.5"}]
        curr = [{"condition_id": "c1", "outcome": "YES", "size": "150", "cur_price": "0.6"}]
        changes = diff_positions(prev, curr)
        assert len(changes) == 1
        assert changes[0]["change_type"] == "INCREASE"


class TestCalcConviction:
    def test_basic(self):
        change = {"new_size": 200, "old_size": 0, "price_at_change": 0.6}
        # delta=200, dollar=120, avg=50 → 2.4
        assert calc_conviction(change, 50) == 2.4

    def test_decrease(self):
        change = {"new_size": 50, "old_size": 200, "price_at_change": 0.5}
        # delta=150, dollar=75, avg=100 → 0.75
        assert calc_conviction(change, 100) == 0.75

    def test_zero_avg_size(self):
        change = {"new_size": 100, "old_size": 0, "price_at_change": 0.5}
        assert calc_conviction(change, 0) == 1.0

    def test_zero_price(self):
        change = {"new_size": 200, "old_size": 0, "price_at_change": 0}
        # delta=200, price=0 → dollar_delta=delta=200, avg=100 → 2.0
        assert calc_conviction(change, 100) == 2.0

    def test_no_change(self):
        change = {"new_size": 100, "old_size": 100, "price_at_change": 0.5}
        assert calc_conviction(change, 50) == 0.0
