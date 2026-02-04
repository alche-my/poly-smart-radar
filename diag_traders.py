"""Export top leaderboard traders as CSV for analysis."""
import asyncio
import csv
import statistics
from collections import Counter
from datetime import datetime
import aiohttp

DATA_API = "https://data-api.polymarket.com"
TIMEOUT = aiohttp.ClientTimeout(total=20)

NUM_TRADERS = 30
MAX_POSITIONS = 500
OUTPUT_FILE = "data/traders_analysis.csv"


async def fetch_closed_paginated(session, wallet, max_results=MAX_POSITIONS):
    all_results = []
    offset = 0
    while offset < max_results:
        try:
            url = f"{DATA_API}/closed-positions"
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


def analyze_trader(name, wallet, pnl, vol, closed):
    if not closed:
        return None

    wins = [p for p in closed if float(p.get("realizedPnl", 0)) > 0]
    losses = [p for p in closed if float(p.get("realizedPnl", 0)) < 0]
    zeros = [p for p in closed if float(p.get("realizedPnl", 0)) == 0]
    total = len(closed)
    wr = len(wins) / total if total > 0 else 0

    # Entry prices
    win_prices = [float(p.get("avgPrice", 0)) for p in wins if float(p.get("avgPrice", 0)) > 0]
    loss_prices = [float(p.get("avgPrice", 0)) for p in losses if float(p.get("avgPrice", 0)) > 0]
    all_prices = [float(p.get("avgPrice", 0)) for p in closed if float(p.get("avgPrice", 0)) > 0]

    # Position sizes
    bought = [float(p.get("totalBought", 0)) for p in closed]
    pnls_list = [float(p.get("realizedPnl", 0)) for p in closed]
    avg_bought = statistics.mean(bought) if bought else 0
    med_bought = statistics.median(bought) if bought else 0
    std_bought = statistics.stdev(bought) if len(bought) > 1 else 0
    cv_bought = std_bought / avg_bought if avg_bought > 0 else 0

    # Outcomes
    outcomes = Counter(p.get("outcome", "?").upper() for p in closed)

    # Timing quality
    timing_scores = []
    for p in closed:
        rpnl = float(p.get("realizedPnl", 0))
        if rpnl <= 0:
            continue
        avg_price = float(p.get("avgPrice", 0))
        outcome = p.get("outcome", "").upper()
        if outcome == "YES":
            timing_scores.append(1.0 - avg_price)
        elif outcome == "NO":
            timing_scores.append(avg_price)
    timing_quality = statistics.mean(timing_scores) if timing_scores else 0

    # Time analysis
    timestamps = []
    for p in closed:
        ts = p.get("timestamp")
        if ts:
            try:
                timestamps.append(datetime.utcfromtimestamp(int(ts)))
            except (ValueError, TypeError):
                pass

    freq = 0
    span_days = 0
    min_gap_hours = 0
    median_gap_hours = 0
    blocks = {"00-06": 0, "06-12": 0, "12-18": 0, "18-24": 0}
    active_blocks = 0
    if timestamps:
        hours = Counter(dt.hour for dt in timestamps)
        for h, c in hours.items():
            if h < 6: blocks["00-06"] += c
            elif h < 12: blocks["06-12"] += c
            elif h < 18: blocks["12-18"] += c
            else: blocks["18-24"] += c
        active_blocks = sum(1 for v in blocks.values() if v > 0)
        ts_sorted = sorted(timestamps)
        span_days = max((ts_sorted[-1] - ts_sorted[0]).days, 1)
        freq = total / span_days
        if len(ts_sorted) > 1:
            gaps = [(ts_sorted[i+1] - ts_sorted[i]).total_seconds() / 3600
                    for i in range(len(ts_sorted)-1)]
            min_gap_hours = min(gaps)
            median_gap_hours = statistics.median(gaps)

    # Markets
    markets = set(p.get("conditionId", "") for p in closed)

    # ROI
    total_pnl = sum(pnls_list)
    total_bought = sum(bought)
    roi = total_pnl / total_bought if total_bought > 0 else 0

    # Classification
    algo_signals = []
    if total >= 200:
        algo_signals.append("high_volume")
    if wr > 0.95 and total > 30:
        algo_signals.append("high_wr")
    if cv_bought < 0.5 and total > 10:
        algo_signals.append("uniform_sizes")
    if freq > 2.0:
        algo_signals.append("high_freq")
    if active_blocks == 4:
        algo_signals.append("24/7")
    if vol > 0 and pnl > 0 and vol / pnl > 10:
        algo_signals.append("high_turnover")
    if len(markets) > 30:
        algo_signals.append("high_diversity")
    verdict = "ALGO" if len(algo_signals) >= 2 else "HUMAN"

    return {
        "name": name,
        "wallet": wallet,
        "verdict": verdict,
        "algo_signals": "|".join(algo_signals),
        "algo_signal_count": len(algo_signals),
        "pnl": round(pnl, 2),
        "volume": round(vol, 2),
        "efficiency_pct": round(pnl / vol * 100, 4) if vol > 0 else 0,
        "roi_pct": round(roi * 100, 4),
        "total_positions": total,
        "wins": len(wins),
        "losses": len(losses),
        "zeros": len(zeros),
        "win_rate": round(wr, 4),
        "timing_quality": round(timing_quality, 4),
        "avg_entry_price_wins": round(statistics.mean(win_prices), 4) if win_prices else 0,
        "median_entry_price_wins": round(statistics.median(win_prices), 4) if win_prices else 0,
        "stdev_entry_price_wins": round(statistics.stdev(win_prices), 4) if len(win_prices) > 1 else 0,
        "avg_entry_price_losses": round(statistics.mean(loss_prices), 4) if loss_prices else 0,
        "avg_position_size": round(avg_bought, 2),
        "median_position_size": round(med_bought, 2),
        "stdev_position_size": round(std_bought, 2),
        "cv_position_size": round(cv_bought, 4),
        "max_position_size": round(max(bought), 2) if bought else 0,
        "min_position_size": round(min(bought), 2) if bought else 0,
        "avg_pnl_per_position": round(statistics.mean(pnls_list), 2) if pnls_list else 0,
        "max_pnl_position": round(max(pnls_list), 2) if pnls_list else 0,
        "min_pnl_position": round(min(pnls_list), 2) if pnls_list else 0,
        "outcomes_yes": outcomes.get("YES", 0),
        "outcomes_no": outcomes.get("NO", 0),
        "unique_markets": len(markets),
        "span_days": span_days,
        "freq_per_day": round(freq, 4),
        "min_gap_hours": round(min_gap_hours, 2),
        "median_gap_hours": round(median_gap_hours, 2),
        "active_time_blocks": active_blocks,
        "trades_00_06": blocks["00-06"],
        "trades_06_12": blocks["06-12"],
        "trades_12_18": blocks["12-18"],
        "trades_18_24": blocks["18-24"],
    }


async def main():
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
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

        results = []
        for i, entry in enumerate(entries, 1):
            name = entry.get("userName") or "?"
            wallet = entry.get("proxyWallet") or entry.get("userAddress", "")
            pnl = float(entry.get("pnl", 0))
            vol = float(entry.get("vol", 0))
            print(f"[{i}/{len(entries)}] {name}...", end=" ", flush=True)
            closed = await fetch_closed_paginated(session, wallet)
            print(f"{len(closed)} positions")
            result = analyze_trader(name, wallet, pnl, vol, closed)
            if result:
                results.append(result)
            await asyncio.sleep(0.3)

        # Write CSV
        if results:
            fields = list(results[0].keys())
            with open(OUTPUT_FILE, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(results)
            print(f"\nSaved {len(results)} traders to {OUTPUT_FILE}")
            print(f"Columns: {len(fields)}")

            # Quick summary
            algos = [r for r in results if r["verdict"] == "ALGO"]
            humans = [r for r in results if r["verdict"] == "HUMAN"]
            print(f"\nALGO: {len(algos)}, HUMAN: {len(humans)}")


if __name__ == "__main__":
    asyncio.run(main())
