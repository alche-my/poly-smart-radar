import asyncio
import json
import logging
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime

import config
from api.data_api import DataApiClient
from api.gamma_api import GammaApiClient
from db.models import upsert_trader

logger = logging.getLogger(__name__)

_CATEGORIES = ["OVERALL", "POLITICS", "CRYPTO", "SPORTS", "CULTURE"]

# Legacy flat keywords for classify_category (used in category scoring)
_CATEGORY_KEYWORDS = {
    "POLITICS": [
        "president", "election", "trump", "biden", "congress", "senate",
        "governor", "democrat", "republican", "vote", "political", "minister",
        "parliament", "gop", "dnc", "rnc", "primary", "inaugur",
    ],
    "CRYPTO": [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "token", "defi",
        "blockchain", "solana", "sol", "nft", "coin", "binance", "mining",
    ],
    "ESPORTS": [
        "league of legends", "dota", "csgo", "cs2", "counter-strike",
        "valorant", "overwatch", "esports", "e-sports", "starcraft",
        "lck", "lpl", "lec", "lcs", "worlds 20",
    ],
    "SPORTS": [
        "nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball",
        "baseball", "tennis", "ufc", "boxing", "championship", "super bowl",
        "world cup", "olympics", "playoff", "mvp",
    ],
    "CULTURE": [
        "oscar", "grammy", "emmy", "movie", "film", "album", "spotify",
        "tiktok", "youtube", "celebrity", "twitter", "music", "award",
    ],
    "WEATHER": [
        "hurricane", "temperature", "weather", "storm", "rain", "snow",
        "tornado", "flood", "climate",
    ],
    "TECH": [
        "apple", "google", "microsoft", "openai", "ai ", "artificial intelligence",
        "spacex", "tesla", "launch", "iphone", "chip",
    ],
    "FINANCE": [
        "stock", "s&p", "nasdaq", "fed", "interest rate", "inflation",
        "gdp", "recession", "earnings", "ipo",
    ],
}

# Domain tags system — matches Polymarket web categories + sub-categories
_DOMAIN_KEYWORDS = {
    # === Broad categories (Polymarket top-level) ===
    "Politics": [
        "president", "election", "trump", "biden", "congress", "senate",
        "governor", "democrat", "republican", "vote", "political", "minister",
        "parliament", "gop", "dnc", "rnc", "primary", "inaugur",
        "legislation", "supreme court", "executive order", "white house",
        "vance", "desantis", "newsom", "rfk", "kamala", "harris",
    ],
    "Crypto": [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "token", "defi",
        "blockchain", "solana", "sol", "nft", "coin", "binance", "mining",
        "airdrop", "staking", "altcoin", "memecoin", "doge", "xrp",
        "cardano", "ada", "polygon", "matic", "avax", "bnb",
    ],
    "Sports": [
        "sports", "athlete", "championship", "playoff", "tournament",
        "world cup", "olympics", "mvp", "medal", "coach", "draft",
        "season", "standings", "division", "conference",
    ],
    "Pop Culture": [
        "oscar", "grammy", "emmy", "movie", "film", "album", "spotify",
        "tiktok", "youtube", "celebrity", "twitter", "music", "award",
        "netflix", "streaming", "box office", "tv show", "reality",
        "kardashian", "taylor swift", "drake", "kanye", "beyonce",
        "instagram", "viral", "podcast",
    ],
    "Business": [
        "stock", "s&p", "nasdaq", "fed", "interest rate", "inflation",
        "gdp", "recession", "earnings", "ipo", "company", "ceo",
        "economy", "market cap", "revenue", "dow jones", "treasury",
        "unemployment", "tariff", "trade war", "debt ceiling",
    ],
    "Science": [
        "climate", "nasa", "space", "satellite", "vaccine",
        "disease", "health", "research", "study", "fda",
        "hurricane", "temperature", "weather", "storm", "tornado",
        "earthquake", "wildfire", "pandemic", "virus",
    ],
    # === Sub-categories within Sports ===
    "NBA": [
        "nba", "basketball", "lakers", "celtics", "warriors", "nets",
        "bucks", "nuggets", "knicks", "sixers", "mavericks", "heat",
        "suns", "clippers", "rockets", "spurs", "raptors", "76ers",
    ],
    "NFL": [
        "nfl", "super bowl", "football", "touchdown", "quarterback",
        "chiefs", "eagles", "cowboys", "patriots", "packers", "49ers",
        "ravens", "bills", "dolphins", "steelers", "bears",
    ],
    "NHL": [
        "nhl", "hockey", "stanley cup", "bruins", "rangers", "penguins",
        "maple leafs", "canadiens", "oilers", "avalanche", "panthers",
    ],
    "MLB": [
        "mlb", "baseball", "world series", "home run", "yankees",
        "dodgers", "red sox", "cubs", "astros", "mets", "braves",
    ],
    "Soccer": [
        "soccer", "premier league", "la liga", "bundesliga", "serie a",
        "champions league", "mls", "euro 20", "copa america", "copa libertadores",
        "arsenal", "barcelona", "real madrid", "manchester", "liverpool",
        "chelsea", "bayern", "psg", "juventus", "inter milan",
    ],
    "MMA": [
        "ufc", "mma", "boxing", "fight night", "bellator",
        "knockout", "wrestling", "submission",
    ],
    "Tennis": [
        "tennis", "wimbledon", "australian open", "french open",
        "roland garros", "atp", "wta",
    ],
    # === Sub-category within Science ===
    "AI": [
        "openai", "ai", "artificial intelligence", "gpt", "chatgpt",
        "machine learning", "deepmind", "gemini", "llm", "neural",
        "anthropic", "claude", "midjourney", "stable diffusion",
    ],
    # === Standalone ===
    "Esports": [
        "league of legends", "dota", "csgo", "cs2", "counter-strike",
        "valorant", "overwatch", "esports", "e-sports", "starcraft",
        "lck", "lpl", "lec", "lcs", "worlds 20", "major qualifier",
    ],
}

# Sub-category → parent mapping (child tag auto-adds parent)
_DOMAIN_PARENTS = {
    "NBA": "Sports", "NFL": "Sports", "NHL": "Sports", "MLB": "Sports",
    "Soccer": "Sports", "MMA": "Sports", "Tennis": "Sports",
    "AI": "Science",
}


def _kw_match(keyword: str, text_lower: str) -> bool:
    """Match keyword in text. Short keywords (<=4 chars) use word boundaries."""
    if len(keyword) <= 4:
        return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text_lower))
    return keyword in text_lower


def classify_category(title: str) -> str | None:
    """Legacy: return first matching broad category (uppercase). Used for scoring."""
    if not title:
        return None
    lower = title.lower()
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if _kw_match(kw, lower):
                return cat
    return None


def classify_domains(title: str) -> list[str]:
    """Return all matching domain tags for a title (including parent tags)."""
    if not title:
        return []
    lower = title.lower()
    matched = set()
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if _kw_match(kw, lower):
                matched.add(domain)
                parent = _DOMAIN_PARENTS.get(domain)
                if parent:
                    matched.add(parent)
                break
    return sorted(matched)


def calc_win_rate(closed_positions: list[dict]) -> float:
    if not closed_positions:
        return 0.0
    wins = sum(1 for p in closed_positions if float(p.get("realizedPnl", 0)) > 0)
    return wins / len(closed_positions)


def calc_roi(closed_positions: list[dict]) -> float:
    total_pnl = sum(float(p.get("realizedPnl", 0)) for p in closed_positions)
    total_bought = sum(float(p.get("totalBought", 0)) for p in closed_positions)
    if total_bought == 0:
        return 0.0
    return total_pnl / total_bought


def calc_consistency(win_rate: float, total_closed: int) -> float:
    if total_closed <= 1:
        return 0.0
    return win_rate * math.log2(total_closed)


def calc_timing_quality(closed_positions: list[dict]) -> float:
    scores = []
    for p in closed_positions:
        pnl = float(p.get("realizedPnl", 0))
        if pnl <= 0:
            continue
        avg_price = float(p.get("avgPrice", 0))
        outcome = p.get("outcome", "").upper()
        if outcome == "YES":
            scores.append(1.0 - avg_price)
        elif outcome == "NO":
            scores.append(avg_price)
    if not scores:
        return 0.0
    return statistics.mean(scores)


def calc_pnl_score(pnl: float) -> float:
    """Log10-scaled PnL. $22M → ~7.3, $100K → ~5.0, $1K → ~3.0."""
    if pnl <= 0:
        return 0.0
    return math.log10(pnl)


def calc_avg_position_size(trades: list[dict]) -> float:
    sizes = [float(t.get("usdcSize", 0)) for t in trades if float(t.get("usdcSize", 0)) > 0]
    if not sizes:
        return 0.0
    return statistics.median(sizes)


def calc_category_scores(closed_positions: list[dict]) -> dict[str, float]:
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for p in closed_positions:
        title = p.get("title", "") or p.get("eventTitle", "") or ""
        cat = classify_category(title)
        if cat:
            by_cat[cat].append(p)

    scores = {}
    for cat, positions in by_cat.items():
        if len(positions) < 10:
            continue
        wr = calc_win_rate(positions)
        roi = calc_roi(positions)
        consistency = calc_consistency(wr, len(positions))
        scores[cat] = round(consistency * (1 + roi), 2)
    return scores


def classify_trader_type(
    closed: list[dict], pnl: float, volume: float,
) -> tuple[str, list[str]]:
    """Classify trader as HUMAN or ALGO based on behavioral signals.

    Returns (type, list_of_signals) where signals explain why ALGO was detected.
    """
    total = len(closed)
    if total < 5:
        return "UNKNOWN", []

    wins = sum(1 for p in closed if float(p.get("realizedPnl", 0)) > 0)
    wr = wins / total

    # CV of position sizes
    bought = [float(p.get("totalBought", 0)) for p in closed if float(p.get("totalBought", 0)) > 0]
    if len(bought) > 1:
        avg_b = statistics.mean(bought)
        std_b = statistics.stdev(bought)
        cv_b = std_b / avg_b if avg_b > 0 else 999
    else:
        cv_b = 999

    # Frequency and 24/7 activity from timestamps
    timestamps = []
    blocks = {"00-06": 0, "06-12": 0, "12-18": 0, "18-24": 0}
    for p in closed:
        ts = p.get("timestamp")
        if ts:
            try:
                dt = datetime.utcfromtimestamp(int(ts))
                timestamps.append(dt)
                h = dt.hour
                if h < 6:
                    blocks["00-06"] += 1
                elif h < 12:
                    blocks["06-12"] += 1
                elif h < 18:
                    blocks["12-18"] += 1
                else:
                    blocks["18-24"] += 1
            except (ValueError, TypeError):
                pass

    active_blocks = sum(1 for v in blocks.values() if v > 0)
    ts_sorted = sorted(timestamps)
    span_days = max((ts_sorted[-1] - ts_sorted[0]).days, 1) if len(ts_sorted) > 1 else 1
    freq = total / span_days

    # Unique markets
    n_markets = len(set(p.get("conditionId", "") for p in closed))

    # Accumulate signals
    signals = []
    if total >= 200:
        signals.append("high_volume")
    if wr > 0.95 and total > 30:
        signals.append("high_wr")
    if cv_b < 0.5 and total > 10:
        signals.append("uniform_sizes")
    if freq > 2.0:
        signals.append("high_freq")
    if active_blocks == 4:
        signals.append("24/7")
    if volume > 0 and pnl > 0 and volume / pnl > 10:
        signals.append("high_turnover")
    if n_markets > 30:
        signals.append("high_diversity")

    trader_type = "ALGO" if len(signals) >= 2 else "HUMAN"
    return trader_type, signals


def detect_strategy_type(closed: list[dict]) -> str:
    """Detect single dominant strategy. Kept for backward compat."""
    tags = detect_domain_tags(closed)
    return tags[0] if tags else "UNKNOWN"


def detect_domain_tags(closed: list[dict]) -> list[str]:
    """Detect all domain tags where 10%+ of positions match.

    Returns list of tags like ["Sports", "NBA", "Crypto"] or ["Mixed"].
    Also detects behavioral tags: "Market Maker", "Longshot".
    """
    if not closed:
        return []

    total = len(closed)
    threshold = max(total * 0.10, 1)

    # 1. Count domain matches per position
    domain_counts: dict[str, int] = defaultdict(int)
    for p in closed:
        title = p.get("title", "") or p.get("eventTitle", "") or ""
        domains = classify_domains(title)
        for d in domains:
            domain_counts[d] += 1

    # 2. Collect tags above 10% threshold
    tags = []
    for domain, count in sorted(domain_counts.items(), key=lambda x: -x[1]):
        if count >= threshold:
            tags.append(domain)

    # 3. Behavioral tags
    by_market: dict[str, list[dict]] = defaultdict(list)
    for p in closed:
        cid = p.get("conditionId", "")
        if cid:
            by_market[cid].append(p)

    if by_market:
        both_sides = sum(
            1 for ps in by_market.values()
            if len(set(p.get("outcome", "").upper() for p in ps)) > 1
        )
        if both_sides / len(by_market) > 0.20:
            tags.append("Market Maker")

    low_price = sum(1 for p in closed if float(p.get("avgPrice", 0)) < 0.15)
    if total > 0 and low_price / total > 0.40:
        tags.append("Longshot")

    return tags if tags else ["Mixed"]


def _extract_recent_bets(closed: list[dict], n: int = 10) -> list[dict]:
    """Extract last N closed positions as compact bet records (most recent first).

    The API returns positions sorted by realizedPnl desc, so we re-sort
    by timestamp to show the trader's actual recent activity.
    """
    sorted_closed = sorted(
        closed,
        key=lambda p: int(p.get("timestamp", 0) or 0),
        reverse=True,
    )
    bets = []
    for p in sorted_closed[:n]:
        title = p.get("title", "") or p.get("eventTitle", "") or ""
        pnl_val = float(p.get("realizedPnl", 0))
        bets.append({
            "title": title[:60],
            "category": classify_domains(title)[:2],  # top 2 domain tags
            "outcome": p.get("outcome", ""),
            "avgPrice": round(float(p.get("avgPrice", 0)), 2),
            "pnl": round(pnl_val, 2),
        })
    return bets


class WatchlistBuilder:
    def __init__(self, data_api: DataApiClient, gamma_api: GammaApiClient, db_path: str):
        self.data_api = data_api
        self.gamma_api = gamma_api
        self.db_path = db_path

    async def build_watchlist(self, limit: int = 0) -> int:
        logger.info("Building watchlist...")

        # 1. Collect unique wallets from leaderboards
        wallet_info = await self._collect_wallets()
        logger.info("Collected %d unique wallets from leaderboards", len(wallet_info))

        # Optional: limit for fast debugging
        if limit > 0:
            wallet_info = dict(list(wallet_info.items())[:limit])
            logger.info("Limited to %d wallets for testing", limit)

        # 2. Score each trader (3 concurrent workers)
        sem = asyncio.Semaphore(3)
        total = len(wallet_info)
        processed = 0

        async def _process(wallet: str, lb_data: dict) -> dict | None:
            nonlocal processed
            async with sem:
                processed += 1
                logger.info("Processing trader %d/%d: %s...", processed, total, wallet[:10])
                return await self._score_trader(wallet, lb_data)

        results = await asyncio.gather(
            *[_process(w, d) for w, d in wallet_info.items()]
        )
        traders = [t for t in results if t is not None]

        if not traders:
            logger.warning("No traders passed filtering")
            return 0

        # 3. Normalize ROI across pool
        self._normalize_roi(traders)

        # 4. Calculate final TraderScore
        # timing_quality is primary: rewards traders who enter early (real edge)
        # consistency (WR × log2(N)): validates accuracy over sample size
        # roi_normalized: bonus for good returns
        # Safe-bet traders (buy YES@0.95) get timing ≈ 0.05 → naturally rank low
        for t in traders:
            t["trader_score"] = round(
                t["timing_quality"] * t["consistency"] * (1 + t["roi_normalized"]),
                4,
            )
            upsert_trader(self.db_path, t)

        traders.sort(key=lambda t: t["trader_score"], reverse=True)
        logger.info(
            "Watchlist built: %d traders. Top 5: %s",
            len(traders),
            [(t.get("username", t["wallet_address"][:8]), round(t["trader_score"], 2)) for t in traders[:5]],
        )
        return len(traders)

    async def _collect_wallets(self) -> dict[str, dict]:
        wallet_info: dict[str, dict] = {}
        for cat in _CATEGORIES:
            entries = await self.data_api.get_leaderboard_all(
                category=cat, time_period="ALL", order_by="PNL", max_results=200,
            )
            for entry in entries:
                addr = entry.get("proxyWallet") or entry.get("userAddress") or entry.get("address", "")
                if not addr:
                    continue
                pnl = float(entry.get("pnl", 0) or 0)
                vol = float(entry.get("vol", 0) or entry.get("volume", 0) or 0)
                if addr not in wallet_info:
                    wallet_info[addr] = {
                        "username": entry.get("userName") or entry.get("username") or entry.get("name"),
                        "profile_image": entry.get("profileImage") or entry.get("profilePicture"),
                        "pnl": pnl,
                        "volume": vol,
                    }
                else:
                    # Keep the highest PnL seen across categories
                    if pnl > wallet_info[addr].get("pnl", 0):
                        wallet_info[addr]["pnl"] = pnl
        return wallet_info

    async def _score_trader(self, wallet: str, lb_data: dict) -> dict | None:
        pnl = lb_data.get("pnl", 0)
        if pnl <= 0:
            return None

        closed = await self.data_api.get_closed_positions_all(wallet)  # fetch ALL positions
        if len(closed) < config.MIN_CLOSED_POSITIONS:
            return None

        win_rate = calc_win_rate(closed)
        roi = calc_roi(closed)
        timing = calc_timing_quality(closed)
        consistency = calc_consistency(win_rate, len(closed))
        cat_scores = calc_category_scores(closed)

        volume = lb_data.get("volume", 0)
        trader_type, algo_signals = classify_trader_type(closed, pnl, volume)
        domain_tags = detect_domain_tags(closed)
        strategy_type = domain_tags[0] if domain_tags else "Mixed"
        recent_bets = _extract_recent_bets(closed)

        # Username from leaderboard; wallet prefix as fallback
        username = lb_data.get("username") or wallet[:10]

        logger.info(
            "  %s: %s [%s], WR %.0f%%, %d closed, signals=%s",
            username, trader_type, ", ".join(domain_tags),
            win_rate * 100, len(closed), algo_signals or "-",
        )

        return {
            "wallet_address": wallet,
            "username": username,
            "profile_image": lb_data.get("profile_image"),
            "x_username": None,
            "pnl": pnl,
            "volume": volume,
            "win_rate": round(win_rate, 4),
            "roi": round(roi, 4),
            "consistency": round(consistency, 4),
            "timing_quality": round(timing, 4),
            "roi_normalized": 0.0,  # filled in _normalize_roi
            "avg_position_size": 0,
            "total_closed": len(closed),
            "category_scores": cat_scores,
            "trader_type": trader_type,
            "strategy_type": strategy_type,
            "domain_tags": domain_tags,
            "recent_bets": recent_bets,
            "trader_score": 0.0,  # filled after normalization
        }

    @staticmethod
    def _normalize_roi(traders: list[dict]) -> None:
        rois = [t["roi"] for t in traders]
        min_roi = min(rois)
        max_roi = max(rois)
        spread = max_roi - min_roi
        for t in traders:
            if spread == 0:
                t["roi_normalized"] = 0.5
            else:
                t["roi_normalized"] = round((t["roi"] - min_roi) / spread, 4)
