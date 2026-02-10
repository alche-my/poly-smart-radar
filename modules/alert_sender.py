"""
Telegram alert sender with strategy-based filtering.

Only sends notifications for signals that pass the validated strategy:
  - Tier 1 or Tier 2 (max_tier=2)
  - Entry price $0.10–$0.85
  - Exclude categories: CRYPTO, CULTURE, FINANCE

Two notification types:
  1. NEW SIGNAL — when a qualifying signal is first detected
  2. RESOLVED   — when a qualifying signal's market resolves (win/loss)
"""

import json
import logging
from datetime import datetime

import config
from db.models import (
    get_unsent_signals,
    mark_signal_sent,
    get_newly_resolved_signals,
    mark_resolution_alert_sent,
)

logger = logging.getLogger(__name__)

_TIER_EMOJI = {1: "\U0001f534", 2: "\U0001f7e1", 3: "\U0001f535"}


def passes_strategy_filter(signal: dict) -> bool:
    """Check if signal passes the validated strategy filters."""
    tier = signal.get("tier", 99)
    if tier > config.STRATEGY_MAX_TIER:
        return False

    price = signal.get("current_price", 0) or signal.get("market_price_at_signal", 0)
    if price < config.STRATEGY_MIN_PRICE or price > config.STRATEGY_MAX_PRICE:
        return False

    category = (signal.get("market_category") or "OTHER").upper()
    if category in config.STRATEGY_BAD_CATEGORIES:
        return False

    return True


def format_time_ago(timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(timestamp)
    except (ValueError, TypeError):
        return "?"
    delta = datetime.utcnow() - dt
    total_minutes = int(delta.total_seconds() / 60)
    if total_minutes < 1:
        return "just now"
    if total_minutes < 60:
        return f"{total_minutes}min ago"
    hours = total_minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def format_new_signal_message(signal: dict) -> str:
    """Format a new signal notification."""
    tier = signal.get("tier", 0)
    emoji = _TIER_EMOJI.get(tier, "")
    score = signal.get("signal_score", 0)
    title = signal.get("market_title", "Unknown market")
    direction = signal.get("direction", "?")
    price = signal.get("current_price", 0)
    category = signal.get("market_category", "")
    slug = signal.get("market_slug", "")

    involved_raw = signal.get("traders_involved", "[]")
    if isinstance(involved_raw, str):
        try:
            involved = json.loads(involved_raw)
        except (json.JSONDecodeError, TypeError):
            involved = []
    else:
        involved = involved_raw

    lines = [
        f"{emoji} NEW SIGNAL | TIER {tier} | Score: {score:.1f}",
        "",
        title,
        f"Direction: {direction} @ ${price:.2f}",
    ]
    if category:
        lines.append(f"Category: {category}")
    if slug:
        lines.append(f"https://polymarket.com/event/{slug}")

    lines.append("")
    lines.append(f"Traders ({len(involved)}):")

    for t in involved:
        username = t.get("username", "?")
        ts = t.get("trader_score", 0)
        wr = t.get("win_rate", 0)
        ct = t.get("change_type", "?")
        size = t.get("size", 0)
        conv = t.get("conviction", 0)
        detected = t.get("detected_at", "")
        ago = format_time_ago(detected)
        lines.append(
            f"  - {username} (score {ts:.1f}, WR {wr:.0%})"
            f" \u2014 {ct} ${size:.0f} ({conv:.1f}x avg) {ago}"
        )

    return "\n".join(lines)


def format_resolution_message(signal: dict) -> str:
    """Format a resolution notification."""
    tier = signal.get("tier", 0)
    emoji = _TIER_EMOJI.get(tier, "")
    title = signal.get("market_title", "Unknown market")
    direction = signal.get("direction", "?")
    entry_price = signal.get("current_price", 0)
    resolution = signal.get("resolution_outcome", "?")
    pnl = signal.get("pnl_percent", 0) or 0
    slug = signal.get("market_slug", "")

    correct = direction.upper() == resolution.upper()
    result_emoji = "\u2705" if correct else "\u274c"
    pnl_str = f"{pnl * 100:+.0f}%"

    lines = [
        f"{result_emoji} RESOLVED | TIER {tier} | {pnl_str}",
        "",
        title,
        f"Signal: {direction} @ ${entry_price:.2f}",
        f"Result: {resolution} \u2014 {'WIN' if correct else 'LOSS'}",
    ]
    if slug:
        lines.append(f"https://polymarket.com/event/{slug}")

    return "\n".join(lines)


class AlertSender:
    def __init__(
        self,
        bot_token: str = config.TELEGRAM_BOT_TOKEN,
        chat_id: str = config.TELEGRAM_CHAT_ID,
        db_path: str = config.DB_PATH,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.db_path = db_path

    async def send_strategy_alerts(self) -> dict:
        """Send alerts only for signals passing the strategy filter.

        Returns dict with counts of sent new-signal and resolution alerts.
        """
        new_sent = await self._send_new_signal_alerts()
        res_sent = await self._send_resolution_alerts()
        return {"new_signals": new_sent, "resolutions": res_sent}

    async def _send_new_signal_alerts(self) -> int:
        """Send alerts for new signals that pass strategy filters."""
        signals = get_unsent_signals(self.db_path)
        if not signals:
            return 0

        sent_count = 0
        for signal in signals:
            if not passes_strategy_filter(signal):
                # Mark as sent so we don't re-check, but don't actually send
                mark_signal_sent(self.db_path, signal["id"])
                continue

            message = format_new_signal_message(signal)
            ok = await self._send(message)
            if ok:
                mark_signal_sent(self.db_path, signal["id"])
                sent_count += 1

        if sent_count:
            logger.info("Sent %d new signal alerts (strategy-filtered)", sent_count)
        return sent_count

    async def _send_resolution_alerts(self) -> int:
        """Send alerts for resolved signals that pass strategy filters."""
        signals = get_newly_resolved_signals(self.db_path)
        if not signals:
            return 0

        sent_count = 0
        for signal in signals:
            if not passes_strategy_filter(signal):
                mark_resolution_alert_sent(self.db_path, signal["id"])
                continue

            message = format_resolution_message(signal)
            ok = await self._send(message)
            if ok:
                mark_resolution_alert_sent(self.db_path, signal["id"])
                sent_count += 1

        if sent_count:
            logger.info("Sent %d resolution alerts (strategy-filtered)", sent_count)
        return sent_count

    async def _send(self, text: str) -> bool:
        if not self.bot_token or not self.chat_id:
            logger.info("Telegram not configured, logging alert:\n%s", text)
            return True

        try:
            import aiohttp

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": True,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        return True
                    body = await resp.text()
                    logger.error("Telegram API error %s: %s", resp.status, body[:200])
                    return False
        except Exception as e:
            logger.error("Failed to send Telegram alert: %s", e)
            return False
