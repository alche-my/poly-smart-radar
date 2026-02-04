import pytest

from modules.watchlist_builder import (
    classify_category,
    calc_win_rate,
    calc_roi,
    calc_consistency,
    calc_timing_quality,
    calc_volume_weight,
    calc_avg_position_size,
    calc_category_scores,
    WatchlistBuilder,
)


class TestClassifyCategory:
    def test_politics(self):
        assert classify_category("Will Trump win the election?") == "POLITICS"
        assert classify_category("Biden approval rating above 50%?") == "POLITICS"

    def test_crypto(self):
        assert classify_category("Bitcoin above 100k by December?") == "CRYPTO"
        assert classify_category("ETH price above 5000") == "CRYPTO"
        assert classify_category("Ethereum merge successful?") == "CRYPTO"

    def test_sports(self):
        assert classify_category("NBA Finals MVP 2025") == "SPORTS"
        assert classify_category("Super Bowl winner") == "SPORTS"

    def test_culture(self):
        assert classify_category("Best Picture Oscar winner") == "CULTURE"

    def test_weather(self):
        assert classify_category("Hurricane hits Florida?") == "WEATHER"

    def test_tech(self):
        assert classify_category("OpenAI releases GPT-5?") == "TECH"

    def test_finance(self):
        assert classify_category("S&P 500 above 6000?") == "FINANCE"
        assert classify_category("Fed interest rate cut?") == "FINANCE"

    def test_no_match(self):
        assert classify_category("Something completely random") is None
        assert classify_category("Will it happen?") is None

    def test_empty_and_none(self):
        assert classify_category("") is None
        assert classify_category(None) is None

    def test_short_keywords_word_boundary(self):
        # "eth" should not match "something" (som-eth-ing)
        assert classify_category("Something random") is None
        # "sol" should not match "solution"
        assert classify_category("A solution to the problem") is None
        # "btc" should match standalone
        assert classify_category("BTC rally continues") == "CRYPTO"
        # "nba" should match standalone
        assert classify_category("NBA season opener") == "SPORTS"

    def test_case_insensitive(self):
        assert classify_category("BITCOIN price prediction") == "CRYPTO"
        assert classify_category("trump ELECTION") == "POLITICS"


class TestCalcWinRate:
    def test_basic(self):
        positions = [
            {"realizedPnl": "10"},
            {"realizedPnl": "-5"},
            {"realizedPnl": "3"},
            {"realizedPnl": "0"},
        ]
        assert calc_win_rate(positions) == 0.5

    def test_all_wins(self):
        positions = [{"realizedPnl": "10"}, {"realizedPnl": "1"}]
        assert calc_win_rate(positions) == 1.0

    def test_all_losses(self):
        positions = [{"realizedPnl": "-10"}, {"realizedPnl": "-1"}]
        assert calc_win_rate(positions) == 0.0

    def test_empty(self):
        assert calc_win_rate([]) == 0.0

    def test_zero_pnl_not_counted_as_win(self):
        positions = [{"realizedPnl": "0"}]
        assert calc_win_rate(positions) == 0.0


class TestCalcRoi:
    def test_basic(self):
        positions = [
            {"realizedPnl": "100", "totalBought": "500"},
            {"realizedPnl": "-50", "totalBought": "500"},
        ]
        assert calc_roi(positions) == pytest.approx(0.05)

    def test_negative_roi(self):
        positions = [{"realizedPnl": "-200", "totalBought": "500"}]
        assert calc_roi(positions) == pytest.approx(-0.4)

    def test_zero_bought(self):
        positions = [{"realizedPnl": "100", "totalBought": "0"}]
        assert calc_roi(positions) == 0.0

    def test_empty(self):
        assert calc_roi([]) == 0.0


class TestCalcConsistency:
    def test_basic(self):
        # log2(64) = 6, 0.6 * 6 = 3.6
        assert calc_consistency(0.6, 64) == pytest.approx(3.6)

    def test_one_position(self):
        assert calc_consistency(0.5, 1) == 0.0

    def test_zero_positions(self):
        assert calc_consistency(0.5, 0) == 0.0

    def test_high_count(self):
        # log2(1024) = 10
        assert calc_consistency(0.7, 1024) == pytest.approx(7.0)


class TestCalcTimingQuality:
    def test_yes_positions(self):
        # Bought at 0.3, resolved at 1.0 → timing = 0.7
        positions = [
            {"realizedPnl": "10", "avgPrice": "0.3", "outcome": "YES"},
        ]
        assert calc_timing_quality(positions) == pytest.approx(0.7)

    def test_no_positions(self):
        # Bought at 0.8, resolved at 0.0 → timing = 0.8
        positions = [
            {"realizedPnl": "5", "avgPrice": "0.8", "outcome": "NO"},
        ]
        assert calc_timing_quality(positions) == pytest.approx(0.8)

    def test_mixed(self):
        positions = [
            {"realizedPnl": "10", "avgPrice": "0.3", "outcome": "YES"},  # 0.7
            {"realizedPnl": "5", "avgPrice": "0.8", "outcome": "NO"},    # 0.8
        ]
        assert calc_timing_quality(positions) == pytest.approx(0.75)

    def test_losses_excluded(self):
        positions = [
            {"realizedPnl": "10", "avgPrice": "0.3", "outcome": "YES"},
            {"realizedPnl": "-5", "avgPrice": "0.9", "outcome": "YES"},  # skipped
        ]
        assert calc_timing_quality(positions) == pytest.approx(0.7)

    def test_no_wins(self):
        positions = [{"realizedPnl": "-5", "avgPrice": "0.9", "outcome": "YES"}]
        assert calc_timing_quality(positions) == 0.0

    def test_empty(self):
        assert calc_timing_quality([]) == 0.0


class TestCalcVolumeWeight:
    def test_large_volume(self):
        # log2(1_000_000) ≈ 19.93
        positions = [{"totalBought": "1000000"}]
        assert calc_volume_weight(positions) == pytest.approx(19.93, abs=0.1)

    def test_small_volume(self):
        # log2(100) ≈ 6.64
        positions = [{"totalBought": "100"}]
        assert calc_volume_weight(positions) == pytest.approx(6.64, abs=0.1)

    def test_zero_volume(self):
        positions = [{"totalBought": "0"}]
        assert calc_volume_weight(positions) == 0.0

    def test_empty(self):
        assert calc_volume_weight([]) == 0.0


class TestCalcAvgPositionSize:
    def test_median(self):
        trades = [
            {"usdcSize": "100"},
            {"usdcSize": "200"},
            {"usdcSize": "150"},
        ]
        assert calc_avg_position_size(trades) == 150.0

    def test_zero_size_excluded(self):
        trades = [{"usdcSize": "0"}, {"usdcSize": "100"}]
        assert calc_avg_position_size(trades) == 100.0

    def test_empty(self):
        assert calc_avg_position_size([]) == 0.0


class TestCalcCategoryScores:
    def test_enough_positions(self):
        positions = [
            {"realizedPnl": "10", "title": "Trump wins?", "totalBought": "100"}
            for _ in range(12)
        ]
        scores = calc_category_scores(positions)
        assert "POLITICS" in scores

    def test_not_enough_positions(self):
        positions = [
            {"realizedPnl": "10", "title": "Trump wins?", "totalBought": "100"}
            for _ in range(5)
        ]
        scores = calc_category_scores(positions)
        assert "POLITICS" not in scores

    def test_unclassifiable(self):
        positions = [
            {"realizedPnl": "10", "title": "Random thing", "totalBought": "100"}
            for _ in range(20)
        ]
        scores = calc_category_scores(positions)
        assert len(scores) == 0


class TestNormalizeRoi:
    def test_basic(self):
        traders = [
            {"roi": 0.1},
            {"roi": -0.05},
            {"roi": 0.3},
        ]
        WatchlistBuilder._normalize_roi(traders)
        assert traders[1]["roi_normalized"] == 0.0  # min
        assert traders[2]["roi_normalized"] == 1.0  # max
        assert 0 < traders[0]["roi_normalized"] < 1

    def test_all_same_roi(self):
        traders = [{"roi": 0.1}, {"roi": 0.1}]
        WatchlistBuilder._normalize_roi(traders)
        assert traders[0]["roi_normalized"] == 0.5
        assert traders[1]["roi_normalized"] == 0.5
