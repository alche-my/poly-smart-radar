import pytest

from modules.watchlist_builder import (
    classify_category,
    classify_domains,
    classify_trader_type,
    detect_strategy_type,
    detect_domain_tags,
    calc_win_rate,
    calc_roi,
    calc_consistency,
    calc_timing_quality,
    calc_pnl_score,
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


class TestCalcPnlScore:
    def test_large_pnl(self):
        # log10(22_000_000) ≈ 7.34
        assert calc_pnl_score(22_000_000) == pytest.approx(7.34, abs=0.01)

    def test_small_pnl(self):
        # log10(100_000) = 5.0
        assert calc_pnl_score(100_000) == pytest.approx(5.0)

    def test_zero_pnl(self):
        assert calc_pnl_score(0) == 0.0

    def test_negative_pnl(self):
        assert calc_pnl_score(-500) == 0.0


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


def _make_closed(n, pnl="10", bought="100", title="Some market", outcome="YES",
                 price="0.5", condition_id="c1", timestamp=None):
    """Helper to generate closed position dicts."""
    return [
        {
            "realizedPnl": pnl,
            "totalBought": bought,
            "totalSold": "0",
            "title": title,
            "outcome": outcome,
            "avgPrice": price,
            "conditionId": f"{condition_id}_{i}" if n > 1 else condition_id,
            "timestamp": timestamp,
        }
        for i in range(n)
    ]


class TestClassifyTraderType:
    def test_algo_high_volume_high_wr(self):
        # 200+ positions, >95% WR → ALGO (high_volume + high_wr)
        closed = _make_closed(250, pnl="10")
        trader_type, signals = classify_trader_type(closed, pnl=1_000_000, volume=500_000)
        assert trader_type == "ALGO"
        assert "high_volume" in signals
        assert "high_wr" in signals

    def test_human_few_positions(self):
        # Few positions with varied sizes → no uniform_sizes, no high_volume
        closed = [
            {"realizedPnl": "10", "totalBought": str(50 + i * 30),
             "totalSold": "0", "title": "M", "outcome": "YES",
             "avgPrice": "0.5", "conditionId": f"c{i}",
             "timestamp": str(1700000000 + i * 86400)}
            for i in range(15)
        ]
        trader_type, signals = classify_trader_type(closed, pnl=50_000, volume=100_000)
        assert trader_type == "HUMAN"

    def test_algo_high_turnover_high_diversity(self):
        # vol/pnl > 10 and >30 unique markets → ALGO
        closed = _make_closed(40, pnl="10")
        trader_type, signals = classify_trader_type(closed, pnl=10_000, volume=500_000)
        assert trader_type == "ALGO"
        assert "high_turnover" in signals
        assert "high_diversity" in signals

    def test_unknown_too_few(self):
        closed = _make_closed(3, pnl="10")
        trader_type, _ = classify_trader_type(closed, pnl=1000, volume=5000)
        assert trader_type == "UNKNOWN"

    def test_human_low_signals(self):
        # 20 positions with mixed results and varied sizes → human-like
        closed = [
            {"realizedPnl": "10" if i % 2 == 0 else "-5",
             "totalBought": str(50 + i * 25),
             "totalSold": "0", "title": "M", "outcome": "YES",
             "avgPrice": "0.5", "conditionId": f"c{i}",
             "timestamp": str(1700000000 + i * 86400)}
            for i in range(20)
        ]
        trader_type, signals = classify_trader_type(closed, pnl=50_000, volume=100_000)
        assert trader_type == "HUMAN"
        assert len(signals) < 2


class TestDetectStrategyType:
    """detect_strategy_type returns first tag from detect_domain_tags."""

    def test_nba(self):
        closed = _make_closed(20, title="NBA Finals MVP 2025")
        result = detect_strategy_type(closed)
        assert result in ("NBA", "Sports")

    def test_politics(self):
        closed = _make_closed(20, title="Will Trump win the election?")
        assert detect_strategy_type(closed) == "Politics"

    def test_crypto(self):
        closed = _make_closed(20, title="Bitcoin above 100k?")
        assert detect_strategy_type(closed) == "Crypto"

    def test_esports(self):
        closed = _make_closed(20, title="LCK Spring Finals winner")
        assert detect_strategy_type(closed) == "Esports"

    def test_market_maker(self):
        positions = []
        for i in range(20):
            positions.append({
                "realizedPnl": "10", "totalBought": "100", "totalSold": "90",
                "title": "Some event", "outcome": "YES", "avgPrice": "0.5",
                "conditionId": f"c{i}",
            })
            positions.append({
                "realizedPnl": "5", "totalBought": "100", "totalSold": "90",
                "title": "Some event", "outcome": "NO", "avgPrice": "0.5",
                "conditionId": f"c{i}",
            })
        assert detect_strategy_type(positions) == "Market Maker"

    def test_longshot(self):
        closed = _make_closed(20, price="0.05", title="Will something happen?")
        assert detect_strategy_type(closed) == "Longshot"

    def test_mixed(self):
        # Titles that don't match any keywords → Mixed
        closed = _make_closed(20, title="Will something happen tomorrow?")
        assert detect_strategy_type(closed) == "Mixed"

    def test_empty(self):
        assert detect_strategy_type([]) == "UNKNOWN"


class TestDetectDomainTags:
    """Domain tags with 10% threshold."""

    def test_single_domain(self):
        closed = _make_closed(20, title="NBA Finals MVP 2025")
        tags = detect_domain_tags(closed)
        assert "NBA" in tags
        assert "Sports" in tags  # parent auto-added

    def test_multiple_domains(self):
        positions = (
            _make_closed(10, title="NBA game tonight") +
            _make_closed(10, title="Bitcoin above 100k?")
        )
        tags = detect_domain_tags(positions)
        assert "NBA" in tags
        assert "Crypto" in tags

    def test_10pct_threshold(self):
        # 2 NBA positions out of 20 = 10% → should be tagged
        positions = (
            _make_closed(2, title="NBA Finals") +
            _make_closed(18, title="Random thing here")
        )
        tags = detect_domain_tags(positions)
        assert "NBA" in tags

    def test_below_threshold(self):
        # 1 NBA out of 20 = 5% → below 10%, but threshold = max(20*0.1, 1) = 2
        # So 1 < 2 → not tagged
        positions = (
            _make_closed(1, title="NBA Finals") +
            _make_closed(19, title="Random thing here")
        )
        tags = detect_domain_tags(positions)
        assert "NBA" not in tags

    def test_sub_category_adds_parent(self):
        closed = _make_closed(20, title="NFL Super Bowl prediction")
        tags = detect_domain_tags(closed)
        assert "NFL" in tags
        assert "Sports" in tags

    def test_market_maker_tag(self):
        positions = []
        for i in range(20):
            positions.append({
                "realizedPnl": "10", "totalBought": "100", "totalSold": "90",
                "title": "Event X", "outcome": "YES", "avgPrice": "0.5",
                "conditionId": f"c{i}",
            })
            positions.append({
                "realizedPnl": "5", "totalBought": "100", "totalSold": "90",
                "title": "Event X", "outcome": "NO", "avgPrice": "0.5",
                "conditionId": f"c{i}",
            })
        tags = detect_domain_tags(positions)
        assert "Market Maker" in tags

    def test_longshot_tag(self):
        closed = _make_closed(20, price="0.05", title="Will X happen?")
        tags = detect_domain_tags(closed)
        assert "Longshot" in tags

    def test_empty(self):
        assert detect_domain_tags([]) == []

    def test_no_matches_returns_mixed(self):
        closed = _make_closed(20, title="Something completely unrelated")
        tags = detect_domain_tags(closed)
        assert tags == ["Mixed"]


class TestClassifyDomains:
    def test_nba_with_parent(self):
        tags = classify_domains("NBA Finals MVP")
        assert "NBA" in tags
        assert "Sports" in tags

    def test_politics(self):
        tags = classify_domains("Trump wins the election")
        assert "Politics" in tags

    def test_multiple_domains(self):
        tags = classify_domains("Bitcoin prediction for NBA fans")
        assert "Crypto" in tags
        assert "NBA" in tags

    def test_esports(self):
        tags = classify_domains("LCK Spring 2025 winner")
        assert "Esports" in tags

    def test_ai_with_parent(self):
        tags = classify_domains("OpenAI releases GPT-5")
        assert "AI" in tags
        assert "Science" in tags

    def test_empty(self):
        assert classify_domains("") == []
        assert classify_domains(None) == []


class TestClassifyCategoryEsports:
    """Legacy classify_category still works for backward compat."""

    def test_esports_keywords(self):
        assert classify_category("LCK Spring 2025 winner") == "ESPORTS"
        assert classify_category("Valorant Champions Tour") == "ESPORTS"
        assert classify_category("Dota 2 International winner") == "ESPORTS"
        assert classify_category("CS2 Major winner") == "ESPORTS"
