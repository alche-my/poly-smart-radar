import asyncio
import logging
import math
import re
import statistics
from collections import defaultdict

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


class WatchlistBuilder:
    def __init__(self, data_api: DataApiClient, gamma_api: GammaApiClient, db_path: str):
        self.data_api = data_api
        self.gamma_api = gamma_api
        self.db_path = db_path

    async def build_watchlist(self) -> int:
        logger.info("Building watchlist...")

        # 1. Collect unique wallets from leaderboards
        wallet_info = await self._collect_wallets()
        logger.info("Collected %d unique wallets from leaderboards", len(wallet_info))

        # 2. Score each trader (5 concurrent workers)
        sem = asyncio.Semaphore(5)
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

        # 4. Calculate final TraderScore and save
        for t in traders:
            t["trader_score"] = round(
                t["consistency"] * t["roi_normalized"] * (1 + t["timing_quality"]),
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
                if addr and addr not in wallet_info:
                    wallet_info[addr] = {
                        "username": entry.get("username") or entry.get("name"),
                        "profile_image": entry.get("profileImage") or entry.get("profilePicture"),
                    }
        return wallet_info

    async def _score_trader(self, wallet: str, lb_data: dict) -> dict | None:
        closed = await self.data_api.get_closed_positions_all(wallet)
        if len(closed) < config.MIN_CLOSED_POSITIONS:
            return None

        profile = await self.gamma_api.get_public_profile(wallet)
        trades = await self.data_api.get_trades(wallet, limit=500)

        win_rate = calc_win_rate(closed)
        roi = calc_roi(closed)
        consistency = calc_consistency(win_rate, len(closed))
        timing = calc_timing_quality(closed)
        avg_size = calc_avg_position_size(trades)
        cat_scores = calc_category_scores(closed)

        # Username: prefer profile, fallback to leaderboard data
        username = profile.get("username") or lb_data.get("username") or wallet[:10]

        return {
            "wallet_address": wallet,
            "username": username,
            "profile_image": profile.get("profileImage") or lb_data.get("profile_image"),
            "x_username": profile.get("xUsername"),
            "win_rate": round(win_rate, 4),
            "roi": round(roi, 4),
            "consistency": round(consistency, 4),
            "timing_quality": round(timing, 4),
            "roi_normalized": 0.0,  # filled in _normalize_roi
            "avg_position_size": round(avg_size, 2),
            "total_closed": len(closed),
            "category_scores": cat_scores,
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
