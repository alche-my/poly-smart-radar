from datetime import datetime, timedelta

from modules.alert_sender import format_time_ago, format_signal_message


class TestFormatTimeAgo:
    def test_just_now(self):
        now = datetime.utcnow().isoformat()
        assert format_time_ago(now) == "just now"

    def test_minutes(self):
        ts = (datetime.utcnow() - timedelta(minutes=30)).isoformat()
        assert format_time_ago(ts) == "30min ago"

    def test_hours(self):
        ts = (datetime.utcnow() - timedelta(hours=5)).isoformat()
        assert format_time_ago(ts) == "5h ago"

    def test_days(self):
        ts = (datetime.utcnow() - timedelta(days=3)).isoformat()
        assert format_time_ago(ts) == "3d ago"

    def test_one_minute(self):
        ts = (datetime.utcnow() - timedelta(minutes=1)).isoformat()
        assert format_time_ago(ts) == "1min ago"

    def test_invalid(self):
        assert format_time_ago("bad") == "?"

    def test_none(self):
        assert format_time_ago(None) == "?"


class TestFormatSignalMessage:
    def _make_signal(self, **overrides):
        now = datetime.utcnow().isoformat()
        base = {
            "tier": 1,
            "status": "ACTIVE",
            "signal_score": 34.5,
            "market_title": "Will Trump win?",
            "direction": "YES",
            "current_price": 0.62,
            "market_slug": "trump-win",
            "traders_involved": [
                {
                    "username": "whale1",
                    "trader_score": 8.0,
                    "win_rate": 0.72,
                    "pnl": 450_000,
                    "trader_type": "HUMAN",
                    "domain_tags": ["Politics"],
                    "recent_bets": [
                        {"title": "Biden approval", "category": ["Politics"],
                         "outcome": "YES", "avgPrice": 0.45, "pnl": 2100},
                        {"title": "BTC above 80k", "category": ["Crypto"],
                         "outcome": "YES", "avgPrice": 0.30, "pnl": -800},
                    ],
                    "change_type": "OPEN",
                    "size": 5000,
                    "conviction": 2.5,
                    "detected_at": now,
                },
            ],
        }
        base.update(overrides)
        return base

    def test_contains_tier(self):
        msg = format_signal_message(self._make_signal())
        assert "TIER 1" in msg

    def test_contains_market_title(self):
        msg = format_signal_message(self._make_signal())
        assert "Will Trump win?" in msg

    def test_contains_direction_and_price(self):
        msg = format_signal_message(self._make_signal())
        assert "YES @ $0.62" in msg

    def test_contains_url(self):
        msg = format_signal_message(self._make_signal())
        assert "https://polymarket.com/event/trump-win" in msg

    def test_human_shows_wr_and_pnl(self):
        msg = format_signal_message(self._make_signal())
        assert "whale1" in msg
        assert "WR 72%" in msg
        assert "PnL $450K" in msg
        assert "OPEN" in msg

    def test_human_shows_recent_bets(self):
        msg = format_signal_message(self._make_signal())
        assert "Biden approval" in msg
        assert "Politics" in msg
        assert "+$2K" in msg or "+$2100" in msg
        assert "BTC above 80k" in msg

    def test_algo_shows_score_and_tags(self):
        now = datetime.utcnow().isoformat()
        signal = self._make_signal(traders_involved=[
            {
                "username": "bot1",
                "trader_score": 9.5,
                "win_rate": 1.0,
                "pnl": 5_000_000,
                "trader_type": "ALGO",
                "domain_tags": ["Sports", "NBA"],
                "recent_bets": [],
                "change_type": "OPEN",
                "size": 10000,
                "conviction": 3.0,
                "detected_at": now,
            },
        ])
        msg = format_signal_message(signal)
        assert "bot1" in msg
        assert "score 9.5" in msg
        assert "Sports, NBA" in msg
        assert "ALGO" in msg
        # ALGO signals should NOT show WR/PnL
        assert "WR 100%" not in msg

    def test_human_type_label(self):
        msg = format_signal_message(self._make_signal())
        assert "\U0001f464" in msg  # person emoji
        assert "\U0001f916" not in msg  # no robot emoji

    def test_algo_type_label(self):
        now = datetime.utcnow().isoformat()
        signal = self._make_signal(traders_involved=[{
            "username": "algobot", "trader_score": 7.0, "win_rate": 1.0,
            "pnl": 1_000_000, "trader_type": "ALGO",
            "domain_tags": ["Crypto"], "recent_bets": [],
            "change_type": "INCREASE", "size": 5000,
            "conviction": 2.0, "detected_at": now,
        }])
        msg = format_signal_message(signal)
        assert "\U0001f916" in msg  # robot emoji

    def test_mixed_signal_both_sections(self):
        now = datetime.utcnow().isoformat()
        signal = self._make_signal(traders_involved=[
            {"username": "algobot", "trader_score": 7.0, "win_rate": 1.0,
             "pnl": 2_000_000, "trader_type": "ALGO",
             "domain_tags": ["Sports"], "recent_bets": [],
             "change_type": "OPEN", "size": 5000,
             "conviction": 2.0, "detected_at": now},
            {"username": "human1", "trader_score": 5.0, "win_rate": 0.65,
             "pnl": 100_000, "trader_type": "HUMAN",
             "domain_tags": ["Politics"], "recent_bets": [],
             "change_type": "OPEN", "size": 3000,
             "conviction": 1.5, "detected_at": now},
        ])
        msg = format_signal_message(signal)
        assert "Algo (1):" in msg
        assert "Traders (1):" in msg
        assert "algobot" in msg
        assert "human1" in msg

    def test_weakening_prefix(self):
        msg = format_signal_message(self._make_signal(status="WEAKENING"))
        assert "WEAKENING" in msg

    def test_closed_prefix(self):
        msg = format_signal_message(self._make_signal(status="CLOSED"))
        assert "CLOSED" in msg

    def test_active_no_prefix(self):
        msg = format_signal_message(self._make_signal(status="ACTIVE"))
        assert "WEAKENING" not in msg
        assert "CLOSED" not in msg

    def test_tier_emojis(self):
        msg1 = format_signal_message(self._make_signal(tier=1))
        msg2 = format_signal_message(self._make_signal(tier=2))
        msg3 = format_signal_message(self._make_signal(tier=3))
        assert "\U0001f534" in msg1  # red
        assert "\U0001f7e1" in msg2  # yellow
        assert "\U0001f535" in msg3  # blue

    def test_no_slug(self):
        msg = format_signal_message(self._make_signal(market_slug=""))
        assert "polymarket.com" not in msg

    def test_json_string_traders(self):
        import json
        now = datetime.utcnow().isoformat()
        traders = [{"username": "x", "trader_score": 1.0, "win_rate": 0.5,
                     "pnl": 1000, "trader_type": "HUMAN",
                     "domain_tags": [], "recent_bets": [],
                     "change_type": "OPEN", "size": 50, "conviction": 1.0,
                     "detected_at": now}]
        msg = format_signal_message(self._make_signal(traders_involved=json.dumps(traders)))
        assert "x" in msg
