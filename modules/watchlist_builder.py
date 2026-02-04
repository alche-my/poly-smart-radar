import asyncio
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


def classify_category(title: str) -> str | None:
    if not title:
        return None
    lower = title.lower()
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if len(kw) <= 4:
                if re.search(r'\b' + re.escape(kw) + r'\b', lower):
                    return cat
            else:
                if kw in lower:
                    return cat
    return None


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
    """Detect dominant trading strategy/domain from closed positions.

    Returns one of: SPORTS, POLITICS, CRYPTO, ESPORTS, CULTURE, TECH, FINANCE,
    MARKET_MAKER, LONGSHOT, MIXED, UNKNOWN.
    """
    if not closed:
        return "UNKNOWN"

    total = len(closed)

    # 1. Check for market making (both-sides trading)
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
        both_sides_pct = both_sides / len(by_market)
        if both_sides_pct > 0.20:
            return "MARKET_MAKER"

    # 2. Check for longshot strategy (majority at extreme low prices)
    low_price_count = sum(
        1 for p in closed if float(p.get("avgPrice", 0)) < 0.15
    )
    if total > 0 and low_price_count / total > 0.40:
        return "LONGSHOT"

    # 3. Domain detection from titles
    domain_counts: dict[str, int] = defaultdict(int)
    for p in closed:
        title = p.get("title", "") or p.get("eventTitle", "") or ""
        cat = classify_category(title)
        if cat:
            domain_counts[cat] += 1

    if domain_counts:
        dominant = max(domain_counts, key=domain_counts.get)
        dominant_pct = domain_counts[dominant] / total
        if dominant_pct > 0.40:
            return dominant

    return "MIXED"


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

        closed = await self.data_api.get_closed_positions_all(wallet)
        if len(closed) < config.MIN_CLOSED_POSITIONS:
            return None

        win_rate = calc_win_rate(closed)
        roi = calc_roi(closed)
        timing = calc_timing_quality(closed)
        consistency = calc_consistency(win_rate, len(closed))
        cat_scores = calc_category_scores(closed)

        volume = lb_data.get("volume", 0)
        trader_type, algo_signals = classify_trader_type(closed, pnl, volume)
        strategy_type = detect_strategy_type(closed)

        # Username from leaderboard; wallet prefix as fallback
        username = lb_data.get("username") or wallet[:10]

        logger.info(
            "  %s: %s/%s, WR %.0f%%, %d closed, signals=%s",
            username, trader_type, strategy_type,
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
