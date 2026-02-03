import json
import logging
from datetime import datetime

import config
from db.models import get_unsent_signals, mark_signal_sent

logger = logging.getLogger(__name__)

_TIER_EMOJI = {1: "\U0001f534", 2: "\U0001f7e1", 3: "\U0001f535"}


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


def format_signal_message(signal: dict) -> str:
    tier = signal.get("tier", 0)
    emoji = _TIER_EMOJI.get(tier, "")
    status = signal.get("status", "ACTIVE")
    score = signal.get("signal_score", 0)
    title = signal.get("market_title", "Unknown market")
    direction = signal.get("direction", "?")
    price = signal.get("current_price", 0)
    slug = signal.get("market_slug", "")

    involved_raw = signal.get("traders_involved", "[]")
    if isinstance(involved_raw, str):
        try:
            involved = json.loads(involved_raw)
        except (json.JSONDecodeError, TypeError):
            involved = []
    else:
        involved = involved_raw

    # Status prefix for lifecycle updates
    status_prefix = ""
    if status == "WEAKENING":
        status_prefix = "\u26a0\ufe0f WEAKENING | "
    elif status == "CLOSED":
        status_prefix = "\u274c CLOSED | "

    lines = [
        f"{emoji} {status_prefix}TIER {tier} | Score: {score:.1f}",
        "",
        title,
        f"Direction: {direction} @ ${price:.2f}",
    ]
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

    async def send_pending_alerts(self) -> int:
        signals = get_unsent_signals(self.db_path)
        if not signals:
            return 0

        sent_count = 0
        for signal in signals:
            message = format_signal_message(signal)
            ok = await self._send(message)
            if ok:
                mark_signal_sent(self.db_path, signal["id"])
                sent_count += 1

        logger.info("Sent %d/%d alerts", sent_count, len(signals))
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
