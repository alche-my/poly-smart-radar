"""Reverse-engineer ALGO trader strategies from Polymarket data.

Analyzes bot traders to understand:
- HOW they make money (resolution exploit, market making, predictive)
- WHAT markets they trade (categories, price ranges)
- WHEN they enter (timing relative to resolution)

Outputs:
  data/algo_summary.csv    — per-trader strategy classification
  data/algo_positions.csv  — per-position detail for all ALGOs
"""
import asyncio
import csv
import statistics
from collections import Counter, defaultdict
from datetime import datetime
import aiohttp

DATA_API = "https://data-api.polymarket.com"
TIMEOUT = aiohttp.ClientTimeout(total=20)

NUM_TRADERS = 30
MAX_POSITIONS = 500
SUMMARY_FILE = "data/algo_summary.csv"
POSITIONS_FILE = "data/algo_positions.csv"


# ---------- classification (same as diag_traders.py) ----------

def classify_algo(total, wr, cv_bought, freq, active_blocks, vol, pnl, n_markets):
    signals = []
    if total >= 200:
        signals.append("high_volume")
    if wr > 0.95 and total > 30:
        signals.append("high_wr")
    if cv_bought < 0.5 and total > 10:
        signals.append("uniform_sizes")
    if freq > 2.0:
        signals.append("high_freq")
    if active_blocks == 4:
        signals.append("24/7")
    if vol > 0 and pnl > 0 and vol / pnl > 10:
        signals.append("high_turnover")
    if n_markets > 30:
        signals.append("high_diversity")
    return signals


# ---------- API helpers ----------

async def fetch_paginated(session, endpoint, wallet, max_results=MAX_POSITIONS):
    all_results = []
    offset = 0
    while offset < max_results:
        try:
            url = f"{DATA_API}/{endpoint}"
            async with session.get(url, params={
                "user": wallet, "limit": 50, "offset": offset
            }) as resp:
                if resp.status == 429:
                    await asyncio.sleep(2)
                    continue
                data = await resp.json()
            batch = data if isinstance(data, list) else []
            if not batch:
                break
            all_results.extend(batch)
            if len(batch) < 50:
                break
            offset += 50
            await asyncio.sleep(0.15)
        except Exception:
            break
    return all_results[:max_results]


# ---------- per-position analysis ----------

def analyze_position(p):
    """Extract features from a single closed position."""
    rpnl = float(p.get("realizedPnl", 0))
    avg_price = float(p.get("avgPrice", 0))
    total_bought = float(p.get("totalBought", 0))
    total_sold = float(p.get("totalSold", 0))
    outcome = p.get("outcome", "").upper()
    title = p.get("title", "") or p.get("eventTitle", "") or ""
    condition_id = p.get("conditionId", "")

    # Strategy classification per position
    strategy = "unknown"
    if outcome == "YES" and avg_price > 0.90:
        strategy = "resolution_exploit_yes"  # bought YES near 1.0
    elif outcome == "NO" and avg_price < 0.10:
        strategy = "resolution_exploit_no"  # bought YES cheap on NO outcome (=sold NO cheap)
    elif outcome == "YES" and avg_price < 0.30:
        strategy = "early_entry_yes"  # entered early on correct YES
    elif outcome == "NO" and avg_price > 0.70:
        strategy = "early_entry_no"  # entered early on correct NO side
    elif abs(total_bought - total_sold) < total_bought * 0.1 and total_bought > 0:
        strategy = "market_making"  # bought and sold similar amounts
    elif rpnl > 0 and avg_price > 0 and avg_price < 0.90:
        strategy = "predictive"  # profitable entry at non-extreme price
    elif rpnl <= 0:
        strategy = "loss"

    # Price bucket
    if avg_price <= 0.10:
        price_bucket = "0.00-0.10"
    elif avg_price <= 0.20:
        price_bucket = "0.10-0.20"
    elif avg_price <= 0.30:
        price_bucket = "0.20-0.30"
    elif avg_price <= 0.50:
        price_bucket = "0.30-0.50"
    elif avg_price <= 0.70:
        price_bucket = "0.50-0.70"
    elif avg_price <= 0.80:
        price_bucket = "0.70-0.80"
    elif avg_price <= 0.90:
        price_bucket = "0.80-0.90"
    elif avg_price <= 0.95:
        price_bucket = "0.90-0.95"
    else:
        price_bucket = "0.95-1.00"

    return {
        "condition_id": condition_id,
        "title": title[:100],
        "outcome": outcome,
        "avg_price": avg_price,
        "price_bucket": price_bucket,
        "realized_pnl": rpnl,
        "total_bought": total_bought,
        "total_sold": total_sold,
        "strategy": strategy,
    }


def classify_strategy_type(positions_analysis):
    """Classify overall trader strategy from position-level analysis."""
    if not positions_analysis:
        return "unknown", {}

    strategies = Counter(p["strategy"] for p in positions_analysis)
    total = len(positions_analysis)

    resolution_pct = (strategies.get("resolution_exploit_yes", 0) +
                      strategies.get("resolution_exploit_no", 0)) / total
    predictive_pct = (strategies.get("predictive", 0) +
                      strategies.get("early_entry_yes", 0) +
                      strategies.get("early_entry_no", 0)) / total
    mm_pct = strategies.get("market_making", 0) / total
    loss_pct = strategies.get("loss", 0) / total

    # Price distribution
    price_buckets = Counter(p["price_bucket"] for p in positions_analysis)
    extreme_high = (price_buckets.get("0.90-0.95", 0) +
                    price_buckets.get("0.95-1.00", 0)) / total
    extreme_low = (price_buckets.get("0.00-0.10", 0) +
                   price_buckets.get("0.10-0.20", 0)) / total

    # Both-sides analysis: same conditionId with different outcomes
    by_market = defaultdict(list)
    for p in positions_analysis:
        by_market[p["condition_id"]].append(p)
    both_sides_markets = sum(
        1 for cid, ps in by_market.items()
        if len(set(p["outcome"] for p in ps)) > 1
    )
    both_sides_pct = both_sides_markets / max(len(by_market), 1)

    # PnL by strategy
    pnl_by_strategy = defaultdict(float)
    for p in positions_analysis:
        pnl_by_strategy[p["strategy"]] += p["realized_pnl"]

    # Determine primary strategy
    if resolution_pct > 0.50:
        primary = "RESOLUTION_EXPLOIT"
    elif both_sides_pct > 0.20:
        primary = "MARKET_MAKER"
    elif mm_pct > 0.30:
        primary = "MARKET_MAKER"
    elif predictive_pct > 0.40:
        primary = "PREDICTIVE"
    elif extreme_high > 0.50:
        primary = "LATE_ENTRY"  # enters after outcome mostly decided
    elif extreme_low > 0.50:
        primary = "CONTRARIAN"  # buys cheap longshots
    else:
        primary = "MIXED"

    details = {
        "resolution_pct": round(resolution_pct, 4),
        "predictive_pct": round(predictive_pct, 4),
        "mm_pct": round(mm_pct, 4),
        "loss_pct": round(loss_pct, 4),
        "extreme_high_pct": round(extreme_high, 4),
        "extreme_low_pct": round(extreme_low, 4),
        "both_sides_pct": round(both_sides_pct, 4),
        "both_sides_markets": both_sides_markets,
        "unique_markets": len(by_market),
        "strategies": dict(strategies),
        "pnl_by_strategy": {k: round(v, 2) for k, v in pnl_by_strategy.items()},
        "price_buckets": dict(price_buckets),
    }
    return primary, details


# ---------- main ----------

async def main():
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        # 1. Fetch leaderboard
        print(f"Fetching top {NUM_TRADERS} traders...")
        entries = []
        for offset in range(0, NUM_TRADERS, 50):
            url = f"{DATA_API}/v1/leaderboard"
            async with session.get(url, params={
                "category": "OVERALL", "timePeriod": "ALL",
                "orderBy": "PNL", "limit": 50, "offset": offset,
            }) as resp:
                batch = await resp.json()
                entries.extend(batch)
            await asyncio.sleep(0.2)
        entries = entries[:NUM_TRADERS]

        # 2. Process each trader: classify, then deep-dive ALGOs
        all_summaries = []
        all_positions = []

        for i, entry in enumerate(entries, 1):
            name = entry.get("userName") or "?"
            wallet = entry.get("proxyWallet") or entry.get("userAddress", "")
            pnl = float(entry.get("pnl", 0))
            vol = float(entry.get("vol", 0))

            print(f"[{i}/{len(entries)}] {name}...", end=" ", flush=True)

            # Fetch closed positions
            closed = await fetch_paginated(session, "closed-positions", wallet)
            total = len(closed)
            print(f"{total} positions", end="", flush=True)

            if not closed:
                print(" — skipped (no data)")
                continue

            # Quick stats for classification
            wins = sum(1 for p in closed if float(p.get("realizedPnl", 0)) > 0)
            wr = wins / total if total > 0 else 0
            bought = [float(p.get("totalBought", 0)) for p in closed]
            avg_b = statistics.mean(bought) if bought else 0
            std_b = statistics.stdev(bought) if len(bought) > 1 else 0
            cv_b = std_b / avg_b if avg_b > 0 else 0
            markets = set(p.get("conditionId", "") for p in closed)

            # Timestamps for freq
            timestamps = []
            blocks = {"00-06": 0, "06-12": 0, "12-18": 0, "18-24": 0}
            for p in closed:
                ts = p.get("timestamp")
                if ts:
                    try:
                        dt = datetime.utcfromtimestamp(int(ts))
                        timestamps.append(dt)
                        h = dt.hour
                        if h < 6: blocks["00-06"] += 1
                        elif h < 12: blocks["06-12"] += 1
                        elif h < 18: blocks["12-18"] += 1
                        else: blocks["18-24"] += 1
                    except (ValueError, TypeError):
                        pass
            active_blocks = sum(1 for v in blocks.values() if v > 0)
            ts_sorted = sorted(timestamps) if timestamps else []
            span_days = max((ts_sorted[-1] - ts_sorted[0]).days, 1) if len(ts_sorted) > 1 else 1
            freq = total / span_days

            algo_signals = classify_algo(total, wr, cv_b, freq, active_blocks, vol, pnl, len(markets))
            is_algo = len(algo_signals) >= 2

            if not is_algo:
                print(f" — HUMAN (skipped)")
                continue

            print(f" — ALGO [{','.join(algo_signals)}]", flush=True)

            # Deep analysis of positions
            pos_analysis = [analyze_position(p) for p in closed]
            strategy_type, details = classify_strategy_type(pos_analysis)

            print(f"    Strategy: {strategy_type}")
            print(f"    Resolution exploit: {details['resolution_pct']*100:.0f}%")
            print(f"    Predictive: {details['predictive_pct']*100:.0f}%")
            print(f"    Both-sides: {details['both_sides_pct']*100:.0f}% ({details['both_sides_markets']} markets)")
            print(f"    PnL by strategy: {details['pnl_by_strategy']}")
            print(f"    Price buckets: {details['price_buckets']}")

            summary = {
                "name": name,
                "wallet": wallet,
                "pnl": round(pnl, 2),
                "volume": round(vol, 2),
                "total_positions": total,
                "win_rate": round(wr, 4),
                "strategy_type": strategy_type,
                "algo_signals": "|".join(algo_signals),
                "resolution_exploit_pct": details["resolution_pct"],
                "predictive_pct": details["predictive_pct"],
                "market_making_pct": details["mm_pct"],
                "loss_pct": details["loss_pct"],
                "extreme_high_price_pct": details["extreme_high_pct"],
                "extreme_low_price_pct": details["extreme_low_pct"],
                "both_sides_pct": details["both_sides_pct"],
                "both_sides_markets": details["both_sides_markets"],
                "unique_markets": details["unique_markets"],
                "pnl_resolution": details["pnl_by_strategy"].get("resolution_exploit_yes", 0) +
                                  details["pnl_by_strategy"].get("resolution_exploit_no", 0),
                "pnl_predictive": details["pnl_by_strategy"].get("predictive", 0) +
                                  details["pnl_by_strategy"].get("early_entry_yes", 0) +
                                  details["pnl_by_strategy"].get("early_entry_no", 0),
                "pnl_mm": details["pnl_by_strategy"].get("market_making", 0),
                "pnl_loss": details["pnl_by_strategy"].get("loss", 0),
                "prices_0_10": details["price_buckets"].get("0.00-0.10", 0),
                "prices_10_20": details["price_buckets"].get("0.10-0.20", 0),
                "prices_20_30": details["price_buckets"].get("0.20-0.30", 0),
                "prices_30_50": details["price_buckets"].get("0.30-0.50", 0),
                "prices_50_70": details["price_buckets"].get("0.50-0.70", 0),
                "prices_70_80": details["price_buckets"].get("0.70-0.80", 0),
                "prices_80_90": details["price_buckets"].get("0.80-0.90", 0),
                "prices_90_95": details["price_buckets"].get("0.90-0.95", 0),
                "prices_95_100": details["price_buckets"].get("0.95-1.00", 0),
            }
            all_summaries.append(summary)

            # Per-position detail
            for pa in pos_analysis:
                pa["trader_name"] = name
                pa["trader_wallet"] = wallet
                pa["trader_strategy"] = strategy_type
            all_positions.extend(pos_analysis)

            await asyncio.sleep(0.3)

        # 3. Write CSVs
        if all_summaries:
            fields = list(all_summaries[0].keys())
            with open(SUMMARY_FILE, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(all_summaries)
            print(f"\nSaved {len(all_summaries)} ALGO traders to {SUMMARY_FILE}")

        if all_positions:
            pos_fields = ["trader_name", "trader_wallet", "trader_strategy",
                         "condition_id", "title", "outcome", "avg_price",
                         "price_bucket", "realized_pnl", "total_bought",
                         "total_sold", "strategy"]
            with open(POSITIONS_FILE, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=pos_fields)
                writer.writeheader()
                writer.writerows(all_positions)
            print(f"Saved {len(all_positions)} positions to {POSITIONS_FILE}")

        # 4. Summary
        if all_summaries:
            print(f"\n{'='*60}")
            print("ALGO STRATEGY BREAKDOWN")
            print(f"{'='*60}")
            types = Counter(s["strategy_type"] for s in all_summaries)
            for st, count in types.most_common():
                traders = [s for s in all_summaries if s["strategy_type"] == st]
                total_pnl = sum(s["pnl"] for s in traders)
                print(f"\n{st}: {count} traders, total PnL ${total_pnl:,.0f}")
                for s in traders:
                    print(f"  - {s['name']}: ${s['pnl']:,.0f}, "
                          f"WR {s['win_rate']*100:.0f}%, "
                          f"{s['total_positions']} pos, "
                          f"resolution {s['resolution_exploit_pct']*100:.0f}%, "
                          f"predictive {s['predictive_pct']*100:.0f}%")


if __name__ == "__main__":
    asyncio.run(main())
