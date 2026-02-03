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

    def test_contains_trader_info(self):
        msg = format_signal_message(self._make_signal())
        assert "whale1" in msg
        assert "score 8.0" in msg
        assert "WR 72%" in msg
        assert "OPEN" in msg
        assert "2.5x avg" in msg

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

    def test_multiple_traders(self):
        now = datetime.utcnow().isoformat()
        signal = self._make_signal(traders_involved=[
            {"username": "t1", "trader_score": 5.0, "win_rate": 0.6,
             "change_type": "OPEN", "size": 100, "conviction": 1.0, "detected_at": now},
            {"username": "t2", "trader_score": 3.0, "win_rate": 0.5,
             "change_type": "INCREASE", "size": 200, "conviction": 1.5, "detected_at": now},
        ])
        msg = format_signal_message(signal)
        assert "Traders (2):" in msg
        assert "t1" in msg
        assert "t2" in msg

    def test_no_slug(self):
        msg = format_signal_message(self._make_signal(market_slug=""))
        assert "polymarket.com" not in msg

    def test_json_string_traders(self):
        import json
        now = datetime.utcnow().isoformat()
        traders = [{"username": "x", "trader_score": 1.0, "win_rate": 0.5,
                     "change_type": "OPEN", "size": 50, "conviction": 1.0,
                     "detected_at": now}]
        msg = format_signal_message(self._make_signal(traders_involved=json.dumps(traders)))
        assert "x" in msg
