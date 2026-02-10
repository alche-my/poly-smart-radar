"""
Polymarket Backtest: test convergence signals on historical resolved markets.

Usage:
    python scripts/backtest.py --months 3
    python scripts/backtest.py --months 1 --output results.json
"""
import argparse
import asyncio
import json
import logging
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from api.data_api import DataApiClient
from api.gamma_api import GammaApiClient
from db.models import get_traders
from modules.watchlist_builder import (
    classify_category,
    calc_win_rate,
    calc_roi,
    calc_avg_position_size,
)
from modules.signal_detector import calc_category_match, calc_signal_score

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backtest")


# ── Phase 1: Data collection ──────────────────────────────────────────


async def collect_trader_positions(
    data_api: DataApiClient, traders: list[dict]
) -> dict[str, list[dict]]:
    """Fetch closed positions for every trader in the watchlist."""
    all_positions: dict[str, list[dict]] = {}
    total = len(traders)

    for i, trader in enumerate(traders):
        wallet = trader["wallet_address"]
        logger.info("Fetching positions %d/%d: %s", i + 1, total, wallet[:10])
        positions = await data_api.get_closed_positions_all(wallet, max_results=2000)
        if positions:
            all_positions[wallet] = positions
            logger.info("  → %d closed positions", len(positions))
        await asyncio.sleep(0.05)

    logger.info("Collected positions for %d/%d traders", len(all_positions), total)
    return all_positions


async def collect_resolved_markets(
    gamma_api: GammaApiClient, months: int
) -> list[dict]:
    """Fetch all resolved markets within the date range."""
    cutoff = (datetime.utcnow() - timedelta(days=months * 30)).strftime("%Y-%m-%d")
    logger.info("Fetching resolved markets since %s", cutoff)
    markets = await gamma_api.get_all_closed_markets(
        end_date_min=cutoff, max_results=10000,
    )
    logger.info("Fetched %d resolved markets", len(markets))
    return markets


# ── Phase 2: Signal reconstruction ────────────────────────────────────


def extract_resolution(market: dict) -> str | None:
    """Determine which outcome won from Gamma market data."""
    # outcomePrices is a JSON string like "[\"1\",\"0\"]" or "[\"0.95\",\"0.05\"]"
    prices_raw = market.get("outcomePrices")
    outcomes_raw = market.get("outcomes")

    if not prices_raw:
        return None

    if isinstance(prices_raw, str):
        try:
            prices = json.loads(prices_raw)
        except (json.JSONDecodeError, TypeError):
            return None
    else:
        prices = prices_raw

    if isinstance(outcomes_raw, str):
        try:
            outcomes = json.loads(outcomes_raw)
        except (json.JSONDecodeError, TypeError):
            outcomes = ["Yes", "No"]
    else:
        outcomes = outcomes_raw or ["Yes", "No"]

    # Find winning outcome (price >= 0.95)
    for idx, price in enumerate(prices):
        try:
            if float(price) >= 0.95:
                if idx < len(outcomes):
                    return str(outcomes[idx]).upper()
                return "YES" if idx == 0 else "NO"
        except (ValueError, TypeError):
            continue

    return None


def build_market_index(
    resolved_markets: list[dict],
) -> dict[str, dict]:
    """Index resolved markets by condition_id for fast lookup."""
    index: dict[str, dict] = {}
    for m in resolved_markets:
        cid = m.get("condition_id") or m.get("conditionId", "")
        if not cid:
            continue
        resolution = extract_resolution(m)
        if not resolution:
            continue
        index[cid] = {
            "condition_id": cid,
            "title": m.get("question") or m.get("title", ""),
            "slug": m.get("slug", ""),
            "category": classify_category(m.get("question") or m.get("title", "")),
            "resolution": resolution,
            "end_date": m.get("end_date_iso") or m.get("endDate", ""),
        }
    logger.info("Indexed %d markets with clear resolution", len(index))
    return index


def build_trader_market_map(
    all_positions: dict[str, list[dict]],
) -> dict[str, dict[str, dict]]:
    """
    Build mapping: condition_id → {wallet → position_data}.
    Groups traders by which markets they participated in.
    """
    market_traders: dict[str, dict[str, dict]] = defaultdict(dict)

    for wallet, positions in all_positions.items():
        for p in positions:
            cid = p.get("conditionId") or p.get("condition_id", "")
            if not cid:
                continue
            outcome = (p.get("outcome") or "").upper()
            if outcome not in ("YES", "NO"):
                continue

            avg_price = float(p.get("avgPrice", 0) or 0)
            total_bought = float(p.get("totalBought", 0) or 0)

            market_traders[cid][wallet] = {
                "wallet_address": wallet,
                "outcome": outcome,
                "avg_price": avg_price,
                "total_bought": total_bought,
                "realized_pnl": float(p.get("realizedPnl", 0) or 0),
            }

    return dict(market_traders)


def reconstruct_signals(
    market_index: dict[str, dict],
    market_traders: dict[str, dict[str, dict]],
    traders_db: dict[str, dict],
) -> list[dict]:
    """
    For each resolved market, check if 2+ watchlist traders entered same direction.
    If yes, build a virtual signal and calculate score/tier.
    """
    top10_wallets = set(
        sorted(traders_db.keys(), key=lambda w: traders_db[w].get("trader_score", 0), reverse=True)[:10]
    )

    signals = []

    for cid, market_info in market_index.items():
        if cid not in market_traders:
            continue

        participants = market_traders[cid]

        # Group by direction
        by_direction: dict[str, list[dict]] = defaultdict(list)
        for wallet, pos_data in participants.items():
            if wallet not in traders_db:
                continue
            by_direction[pos_data["outcome"]].append({**pos_data, **traders_db[wallet]})

        # Check each direction for convergence
        for direction, group in by_direction.items():
            if len(group) < 1:
                continue

            # Build trader data for scoring
            traders_data = []
            for td in group:
                wallet = td["wallet_address"]
                avg_pos_size = td.get("avg_position_size", 0) or 1
                conviction = td["total_bought"] / avg_pos_size if avg_pos_size > 0 else 1.0

                traders_data.append({
                    "wallet_address": wallet,
                    "username": td.get("username", wallet[:8]),
                    "trader_score": td.get("trader_score", 0),
                    "win_rate": td.get("win_rate", 0),
                    "roi": td.get("roi", 0),
                    "conviction": min(conviction, 10.0),  # cap at 10x
                    "category_match": calc_category_match(td, market_info.get("category")),
                    "freshness": 1.0,  # no timestamp data
                    "avg_price": td.get("avg_price", 0),
                    "total_bought": td.get("total_bought", 0),
                })

            signal_score = calc_signal_score(traders_data)
            num_traders = len(traders_data)

            # Determine tier
            tier = _determine_tier(num_traders, signal_score, traders_data, top10_wallets)
            if tier is None:
                continue

            # Entry price = weighted average by position size
            total_bought_sum = sum(t["total_bought"] for t in traders_data)
            if total_bought_sum > 0:
                entry_price = sum(
                    t["avg_price"] * t["total_bought"] for t in traders_data
                ) / total_bought_sum
            else:
                entry_price = sum(t["avg_price"] for t in traders_data) / len(traders_data)

            # Resolution check
            resolution = market_info["resolution"]
            signal_correct = (direction == resolution)

            # P&L calculation
            if entry_price > 0 and entry_price < 1:
                if signal_correct:
                    pnl = (1.0 - entry_price) / entry_price
                else:
                    pnl = -1.0
            else:
                pnl = 0.0

            # Category match ratio
            cat_match_count = sum(1 for t in traders_data if t["category_match"] > 1.0)
            avg_conviction = sum(t["conviction"] for t in traders_data) / len(traders_data)

            signals.append({
                "condition_id": cid,
                "market_title": market_info["title"],
                "category": market_info.get("category"),
                "direction": direction,
                "resolution": resolution,
                "correct": signal_correct,
                "tier": tier,
                "signal_score": round(signal_score, 2),
                "num_traders": num_traders,
                "entry_price": round(entry_price, 4),
                "pnl": round(pnl, 4),
                "avg_conviction": round(avg_conviction, 2),
                "cat_match_ratio": round(cat_match_count / num_traders, 2),
                "end_date": market_info.get("end_date", ""),
                "traders": [
                    {
                        "wallet": t["wallet_address"][:10],
                        "username": t["username"],
                        "score": t["trader_score"],
                        "conviction": round(t["conviction"], 2),
                    }
                    for t in traders_data
                ],
            })

    signals.sort(key=lambda s: s["end_date"], reverse=True)
    logger.info("Reconstructed %d virtual signals", len(signals))
    return signals


def _determine_tier(
    num_traders: int,
    signal_score: float,
    traders_data: list[dict],
    top10_wallets: set[str],
) -> int | None:
    if num_traders >= 3 and signal_score > config.HIGH_THRESHOLD:
        return 1
    if num_traders >= config.MIN_TRADERS_FOR_SIGNAL and signal_score > config.MEDIUM_THRESHOLD:
        return 2
    if num_traders == 1:
        td = traders_data[0]
        if td["wallet_address"] in top10_wallets and td["conviction"] > 2.0:
            return 3
    return None


# ── Phase 3: Analytics ────────────────────────────────────────────────


def compute_stats(signals: list[dict]) -> dict:
    """Compute win rates, P&L, Kelly criterion grouped by tier and category."""

    def _tier_stats(sigs: list[dict]) -> dict:
        if not sigs:
            return {"count": 0}
        wins = sum(1 for s in sigs if s["correct"])
        total = len(sigs)
        win_rate = wins / total
        avg_pnl = sum(s["pnl"] for s in sigs) / total

        # Separate win and loss P&L for Kelly
        win_pnls = [s["pnl"] for s in sigs if s["correct"]]
        avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0

        # Kelly fraction
        if avg_win > 0:
            kelly = (win_rate * avg_win - (1 - win_rate)) / avg_win
        else:
            kelly = 0

        # Average entry price
        avg_entry = sum(s["entry_price"] for s in sigs) / total

        return {
            "count": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(win_rate, 4),
            "avg_pnl": round(avg_pnl, 4),
            "avg_entry_price": round(avg_entry, 4),
            "avg_win_pnl": round(avg_win, 4),
            "kelly": round(kelly, 4),
            "half_kelly": round(kelly / 2, 4),
        }

    # By tier
    by_tier = defaultdict(list)
    for s in signals:
        by_tier[s["tier"]].append(s)

    tier_stats = {f"tier_{t}": _tier_stats(sigs) for t, sigs in sorted(by_tier.items())}

    # By category
    by_cat = defaultdict(list)
    for s in signals:
        cat = s.get("category") or "OTHER"
        by_cat[cat].append(s)

    cat_stats = {cat: _tier_stats(sigs) for cat, sigs in sorted(by_cat.items())}

    # High conviction vs low conviction
    high_conv = [s for s in signals if s["avg_conviction"] > 1.5]
    low_conv = [s for s in signals if s["avg_conviction"] <= 1.5]

    # With category match vs without
    with_cat = [s for s in signals if s["cat_match_ratio"] > 0.5]
    without_cat = [s for s in signals if s["cat_match_ratio"] <= 0.5]

    return {
        "overall": _tier_stats(signals),
        "by_tier": tier_stats,
        "by_category": cat_stats,
        "high_conviction": _tier_stats(high_conv),
        "low_conviction": _tier_stats(low_conv),
        "with_category_match": _tier_stats(with_cat),
        "without_category_match": _tier_stats(without_cat),
    }


def print_report(stats: dict, signals: list[dict]) -> None:
    """Print a human-readable report to stdout."""
    print("\n" + "=" * 70)
    print("  BACKTEST REPORT — Polymarket Convergence Signals")
    print("=" * 70)

    overall = stats["overall"]
    print(f"\n  Total signals: {overall['count']}")
    print(f"  Win rate:      {overall.get('win_rate', 0) * 100:.1f}%")
    print(f"  Avg P&L:       {overall.get('avg_pnl', 0) * 100:+.1f}%")
    print(f"  Kelly:         {overall.get('kelly', 0):.4f}")
    print(f"  Half-Kelly:    {overall.get('half_kelly', 0):.4f}")

    print("\n" + "-" * 70)
    print("  BY TIER")
    print("-" * 70)
    print(f"  {'Tier':<8} {'Count':>6} {'Wins':>6} {'WR':>8} {'Avg P&L':>10} {'Kelly':>8}")
    for tier_name, ts in sorted(stats["by_tier"].items()):
        if ts["count"] == 0:
            continue
        print(
            f"  {tier_name:<8} {ts['count']:>6} {ts.get('wins', 0):>6} "
            f"{ts.get('win_rate', 0) * 100:>7.1f}% {ts.get('avg_pnl', 0) * 100:>+9.1f}% "
            f"{ts.get('kelly', 0):>8.4f}"
        )

    print("\n" + "-" * 70)
    print("  BY CATEGORY")
    print("-" * 70)
    print(f"  {'Category':<12} {'Count':>6} {'WR':>8} {'Avg P&L':>10}")
    for cat, cs in sorted(stats["by_category"].items(), key=lambda x: x[1].get("count", 0), reverse=True):
        if cs["count"] == 0:
            continue
        print(
            f"  {cat:<12} {cs['count']:>6} {cs.get('win_rate', 0) * 100:>7.1f}% "
            f"{cs.get('avg_pnl', 0) * 100:>+9.1f}%"
        )

    print("\n" + "-" * 70)
    print("  CONVICTION & CATEGORY MATCH ANALYSIS")
    print("-" * 70)
    hc = stats["high_conviction"]
    lc = stats["low_conviction"]
    wc = stats["with_category_match"]
    nc = stats["without_category_match"]
    print(f"  High conviction (>1.5x):  {hc.get('count', 0):>4} signals, WR {hc.get('win_rate', 0) * 100:.1f}%, P&L {hc.get('avg_pnl', 0) * 100:+.1f}%")
    print(f"  Low conviction  (≤1.5x):  {lc.get('count', 0):>4} signals, WR {lc.get('win_rate', 0) * 100:.1f}%, P&L {lc.get('avg_pnl', 0) * 100:+.1f}%")
    print(f"  With cat match  (>50%):   {wc.get('count', 0):>4} signals, WR {wc.get('win_rate', 0) * 100:.1f}%, P&L {wc.get('avg_pnl', 0) * 100:+.1f}%")
    print(f"  Without cat match (≤50%): {nc.get('count', 0):>4} signals, WR {nc.get('win_rate', 0) * 100:.1f}%, P&L {nc.get('avg_pnl', 0) * 100:+.1f}%")

    # Top 5 best and worst signals
    sorted_by_pnl = sorted(signals, key=lambda s: s["pnl"], reverse=True)
    print("\n" + "-" * 70)
    print("  TOP 5 BEST SIGNALS")
    print("-" * 70)
    for s in sorted_by_pnl[:5]:
        print(f"  T{s['tier']} | {s['direction']} @ {s['entry_price']:.2f} → {s['resolution']} | P&L {s['pnl'] * 100:+.0f}% | {s['market_title'][:50]}")

    print("\n  TOP 5 WORST SIGNALS")
    print("-" * 70)
    for s in sorted_by_pnl[-5:]:
        print(f"  T{s['tier']} | {s['direction']} @ {s['entry_price']:.2f} → {s['resolution']} | P&L {s['pnl'] * 100:+.0f}% | {s['market_title'][:50]}")

    print("\n" + "=" * 70)


# ── Main ──────────────────────────────────────────────────────────────


async def run_backtest(months: int, output_path: str | None) -> dict:
    data_api = DataApiClient()
    gamma_api = GammaApiClient()

    try:
        # Phase 1: Collect data
        logger.info("=== Phase 1: Collecting data ===")
        traders = get_traders(config.DB_PATH)
        if not traders:
            logger.error("No traders in watchlist! Run: python main.py --rebuild-watchlist")
            return {}

        logger.info("Watchlist: %d traders", len(traders))
        traders_db = {t["wallet_address"]: t for t in traders}

        all_positions = await collect_trader_positions(data_api, traders)
        resolved_markets = await collect_resolved_markets(gamma_api, months)

        # Phase 2: Reconstruct signals
        logger.info("=== Phase 2: Reconstructing signals ===")
        market_index = build_market_index(resolved_markets)
        market_traders = build_trader_market_map(all_positions)
        signals = reconstruct_signals(market_index, market_traders, traders_db)

        if not signals:
            logger.warning("No signals reconstructed! Check if traders have overlapping markets.")
            return {"signals": [], "stats": {}}

        # Phase 3: Analytics
        logger.info("=== Phase 3: Computing analytics ===")
        stats = compute_stats(signals)

        # Print report
        print_report(stats, signals)

        # Save results
        results = {
            "meta": {
                "months": months,
                "run_at": datetime.utcnow().isoformat(),
                "traders_count": len(traders),
                "positions_count": sum(len(v) for v in all_positions.values()),
                "markets_count": len(market_index),
                "signals_count": len(signals),
            },
            "stats": stats,
            "signals": signals,
        }

        if output_path:
            with open(output_path, "w") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            logger.info("Results saved to %s", output_path)

        return results

    finally:
        await data_api.close()
        await gamma_api.close()


def main():
    parser = argparse.ArgumentParser(description="Polymarket Convergence Backtest")
    parser.add_argument("--months", type=int, default=3, help="How many months back (default: 3)")
    parser.add_argument("--output", "-o", type=str, default=None, help="Save results to JSON file")
    args = parser.parse_args()

    results = asyncio.run(run_backtest(args.months, args.output))

    if results and results.get("stats", {}).get("overall", {}).get("count", 0) > 0:
        overall = results["stats"]["overall"]
        kelly = overall.get("kelly", 0)
        if kelly > 0:
            print(f"\n  ✓ Strategy is PROFITABLE (Kelly = {kelly:.4f})")
        else:
            print(f"\n  ✗ Strategy is NOT profitable (Kelly = {kelly:.4f})")


if __name__ == "__main__":
    main()
