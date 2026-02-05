import asyncio
import json
import logging
from datetime import datetime

import aiohttp

import config
from db.models import get_unsent_signals, mark_signal_sent

logger = logging.getLogger(__name__)

_TIER_EMOJI = {1: "\U0001f534", 2: "\U0001f7e1", 3: "\U0001f535"}
_TG_TIMEOUT = aiohttp.ClientTimeout(total=15)
_SEND_DELAY = 0.5  # seconds between sends (Telegram limit ~30/sec)
_MAX_ALERTS_PER_CYCLE = 30  # limit alerts per cycle to avoid rate limits
_MAX_RETRIES = 3


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


def _format_pnl(pnl: float) -> str:
    if abs(pnl) >= 1_000_000:
        return f"${pnl / 1_000_000:.1f}M"
    if abs(pnl) >= 1_000:
        return f"${pnl / 1_000:.0f}K"
    return f"${pnl:.0f}"


def _format_bet_pnl(pnl: float) -> str:
    if pnl > 0:
        return f"+{_format_pnl(pnl)}"
    if pnl < 0:
        return f"-{_format_pnl(abs(pnl))}"
    return "$0"


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

    # Split by trader type
    algo = [t for t in involved if t.get("trader_type") == "ALGO"]
    human = [t for t in involved if t.get("trader_type") != "ALGO"]

    # Status prefix for lifecycle updates
    status_prefix = ""
    if status == "WEAKENING":
        status_prefix = "\u26a0\ufe0f WEAKENING | "
    elif status == "CLOSED":
        status_prefix = "\u274c CLOSED | "

    # Signal type indicator
    if algo and not human:
        type_label = "\U0001f916 ALGO | "
    elif human and not algo:
        type_label = "\U0001f464 | "
    else:
        type_label = ""

    lines = [
        f"{emoji} {status_prefix}{type_label}TIER {tier} | Score: {score:.1f}",
        "",
        title,
        f"Direction: {direction} @ ${price:.2f}",
    ]
    if slug:
        lines.append(f"https://polymarket.com/event/{slug}")

    # ALGO traders section
    if algo:
        lines.append("")
        if human:
            lines.append(f"\U0001f916 Algo ({len(algo)}):")
        for t in algo:
            username = t.get("username", "?")
            ts = t.get("trader_score", 0)
            tags = t.get("domain_tags", [])
            tags_str = ", ".join(tags[:3]) if tags else "Mixed"
            ct = t.get("change_type", "?")
            size = t.get("size", 0)
            conv = t.get("conviction", 0)
            ago = format_time_ago(t.get("detected_at", ""))
            lines.append(
                f"  {username} (score {ts:.1f}, {tags_str})"
                f" \u2014 {ct} ${size:.0f} ({conv:.1f}x) {ago}"
            )

    # HUMAN traders section
    if human:
        lines.append("")
        if algo:
            lines.append(f"\U0001f464 Traders ({len(human)}):")
        for t in human:
            username = t.get("username", "?")
            wr = t.get("win_rate", 0)
            pnl = t.get("pnl", 0)
            ct = t.get("change_type", "?")
            size = t.get("size", 0)
            conv = t.get("conviction", 0)
            ago = format_time_ago(t.get("detected_at", ""))
            lines.append(
                f"  {username} (WR {wr:.0%}, PnL {_format_pnl(pnl)})"
                f" \u2014 {ct} ${size:.0f} ({conv:.1f}x) {ago}"
            )
            # Recent bets for HUMAN traders
            recent = t.get("recent_bets", [])
            for bet in recent[:5]:
                bet_title = bet.get("title", "?")
                if len(bet_title) > 40:
                    bet_title = bet_title[:37] + "..."
                cats = bet.get("category", [])
                cat_str = f" ({', '.join(cats)})" if cats else ""
                bet_pnl = bet.get("pnl", 0)
                icon = "\u2705" if bet_pnl > 0 else ("\u274c" if bet_pnl < 0 else "\u2796")
                lines.append(f"    {icon} {bet_title}{cat_str} \u2192 {_format_bet_pnl(bet_pnl)}")

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
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_TG_TIMEOUT)
        return self._session

    async def send_pending_alerts(self) -> int:
        signals = get_unsent_signals(self.db_path)
        if not signals:
            return 0

        # Limit alerts per cycle to avoid Telegram rate limits
        batch = signals[:_MAX_ALERTS_PER_CYCLE]
        if len(signals) > _MAX_ALERTS_PER_CYCLE:
            logger.info(
                "Limiting to %d/%d alerts this cycle",
                _MAX_ALERTS_PER_CYCLE, len(signals),
            )

        sent_count = 0
        for signal in batch:
            message = format_signal_message(signal)
            ok = await self._send(message)
            if ok:
                mark_signal_sent(self.db_path, signal["id"])
                sent_count += 1
            # Delay between sends to respect rate limits
            await asyncio.sleep(_SEND_DELAY)

        logger.info("Sent %d/%d alerts", sent_count, len(batch))
        return sent_count

    async def _send(self, text: str) -> bool:
        if not self.bot_token or not self.chat_id:
            logger.info("Telegram not configured, logging alert:\n%s", text)
            return True

        session = await self._ensure_session()
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        return True

                    body = await resp.text()

                    # Handle rate limiting (429)
                    if resp.status == 429:
                        try:
                            data = json.loads(body)
                            retry_after = data.get("parameters", {}).get("retry_after", 10)
                        except (json.JSONDecodeError, KeyError):
                            retry_after = 10

                        if attempt < _MAX_RETRIES:
                            logger.warning(
                                "Telegram rate limit, retry %d/%d in %ds",
                                attempt, _MAX_RETRIES, retry_after,
                            )
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            logger.error("Telegram rate limit exceeded after %d retries", _MAX_RETRIES)
                            return False

                    logger.error("Telegram API error %s: %.200s", resp.status, body)
                    return False

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < _MAX_RETRIES:
                    wait = 2 ** attempt
                    logger.warning(
                        "Telegram send error: %s, retry %d/%d in %ds",
                        e, attempt, _MAX_RETRIES, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.error("Failed to send Telegram alert after %d retries: %s", _MAX_RETRIES, e)
                return False

        return False

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
