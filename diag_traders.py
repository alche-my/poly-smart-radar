"""Deep analysis of top leaderboard traders: ALGO vs HUMAN classification."""
import asyncio
import statistics
from collections import Counter
from datetime import datetime
import aiohttp

DATA_API = "https://data-api.polymarket.com"
TIMEOUT = aiohttp.ClientTimeout(total=20)

# How many leaderboard traders to analyze
NUM_TRADERS = 30
# Max closed positions to fetch per trader (paginated)
MAX_POSITIONS = 500


async def fetch_closed_paginated(session, wallet, max_results=MAX_POSITIONS):
    """Fetch closed positions with pagination, page_size=50."""
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
    """Analyze one trader and print detailed report."""
    print(f"\n{'='*70}")
    print(f"  TRADER: {name}")
    print(f"  Wallet: {wallet[:20]}...")
    eff = f"{pnl/vol*100:.2f}%" if vol > 0 else "n/a"
    print(f"  PnL: ${pnl:,.0f}  |  Volume: ${vol:,.0f}  |  Efficiency: {eff}")
    print(f"{'='*70}")

    if not closed:
        print("  No closed positions\n")
        return None

    # --- Core metrics ---
    wins = [p for p in closed if float(p.get("realizedPnl", 0)) > 0]
    losses = [p for p in closed if float(p.get("realizedPnl", 0)) < 0]
    zeros = [p for p in closed if float(p.get("realizedPnl", 0)) == 0]
    total = len(closed)
    wr = len(wins) / total if total > 0 else 0

    print(f"\n  POSITIONS: {total} total ({len(wins)}W / {len(losses)}L / {len(zeros)}Z)  WR={wr:.0%}")

    # --- Entry prices ---
    win_prices = [float(p.get("avgPrice", 0)) for p in wins if float(p.get("avgPrice", 0)) > 0]
    all_prices = [float(p.get("avgPrice", 0)) for p in closed if float(p.get("avgPrice", 0)) > 0]
    if win_prices:
        print(f"  Entry prices (wins): mean={statistics.mean(win_prices):.3f}, "
              f"median={statistics.median(win_prices):.3f}, "
              f"stdev={statistics.stdev(win_prices):.3f}" if len(win_prices) > 1 else
              f"  Entry prices (wins): {win_prices[0]:.3f}")

    # --- Position sizes ---
    bought = [float(p.get("totalBought", 0)) for p in closed]
    pnls = [float(p.get("realizedPnl", 0)) for p in closed]
    if bought:
        avg_bought = statistics.mean(bought)
        med_bought = statistics.median(bought)
        std_bought = statistics.stdev(bought) if len(bought) > 1 else 0
        cv_bought = std_bought / avg_bought if avg_bought > 0 else 0
        print(f"  Position sizes: mean=${avg_bought:,.0f}, median=${med_bought:,.0f}, "
              f"stdev=${std_bought:,.0f}, CV={cv_bought:.2f}")
        print(f"  PnL/position: mean=${statistics.mean(pnls):,.0f}, "
              f"min=${min(pnls):,.0f}, max=${max(pnls):,.0f}")

    # --- Outcomes ---
    outcomes = Counter(p.get("outcome", "?").upper() for p in closed)
    print(f"  Outcomes: {dict(outcomes)}")

    # --- Time analysis ---
    timestamps = []
    for p in closed:
        ts = p.get("timestamp")
        if ts:
            try:
                timestamps.append(datetime.utcfromtimestamp(int(ts)))
            except (ValueError, TypeError):
                pass

    freq = 0
    if timestamps:
        hours = Counter(dt.hour for dt in timestamps)
        blocks = {"00-06": 0, "06-12": 0, "12-18": 0, "18-24": 0}
        for h, c in hours.items():
            if h < 6: blocks["00-06"] += c
            elif h < 12: blocks["06-12"] += c
            elif h < 18: blocks["12-18"] += c
            else: blocks["18-24"] += c
        print(f"  Trading hours (UTC): {blocks}")

        # Check 24/7 trading (all blocks active)
        active_blocks = sum(1 for v in blocks.values() if v > 0)

        ts_sorted = sorted(timestamps)
        span_days = max((ts_sorted[-1] - ts_sorted[0]).days, 1)
        freq = total / span_days
        print(f"  Active: {span_days} days, {freq:.2f} positions/day")

        # Gaps between trades
        if len(ts_sorted) > 1:
            gaps_hours = [(ts_sorted[i+1] - ts_sorted[i]).total_seconds() / 3600
                          for i in range(len(ts_sorted)-1)]
            min_gap = min(gaps_hours)
            print(f"  Min gap between trades: {min_gap:.1f}h, "
                  f"median gap: {statistics.median(gaps_hours):.1f}h")

    # --- Market diversity ---
    markets = set(p.get("conditionId", "") for p in closed)
    titles = list(set((p.get("title", "") or "")[:60] for p in closed))
    print(f"  Unique markets: {len(markets)} across {total} positions")
    for t in sorted(titles)[:5]:
        print(f"    - {t}")
    if len(titles) > 5:
        print(f"    ... and {len(titles)-5} more")

    # --- VERDICT ---
    algo_signals = []
    human_signals = []

    if total >= 200:
        algo_signals.append(f"High volume: {total} positions")
    elif total < 50:
        human_signals.append(f"Low volume: {total} positions")

    if wr > 0.95 and total > 30:
        algo_signals.append(f"Suspiciously high WR: {wr:.0%}")
    elif wr < 0.7:
        human_signals.append(f"Moderate WR: {wr:.0%}")

    if bought and cv_bought < 0.5:
        algo_signals.append(f"Uniform position sizes (CV={cv_bought:.2f})")
    elif bought and cv_bought > 2.0:
        human_signals.append(f"Variable position sizes (CV={cv_bought:.2f})")

    if freq > 2.0:
        algo_signals.append(f"High frequency: {freq:.1f}/day")

    if timestamps and active_blocks == 4:
        algo_signals.append("Trades across all time blocks (24/7)")

    if vol > 0 and pnl > 0 and vol / pnl > 10:
        algo_signals.append(f"High turnover: {vol/pnl:.0f}x")

    if len(markets) > 30:
        algo_signals.append(f"High market diversity: {len(markets)}")

    print(f"\n  --- CLASSIFICATION ---")
    verdict = "ALGO" if len(algo_signals) >= 2 else "HUMAN"
    print(f"  Type: {verdict}")
    if algo_signals:
        print(f"  ALGO signals: {'; '.join(algo_signals)}")
    if human_signals:
        print(f"  HUMAN signals: {'; '.join(human_signals)}")

    return {
        "name": name, "wallet": wallet, "pnl": pnl, "vol": vol,
        "total": total, "wr": wr, "freq": freq,
        "verdict": verdict, "algo_signals": len(algo_signals),
    }


async def main():
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        # Fetch top traders from leaderboard
        print(f"Fetching top {NUM_TRADERS} traders from leaderboard...\n")
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
        print(f"Got {len(entries)} traders. Fetching closed positions...\n")

        results = []
        for i, entry in enumerate(entries, 1):
            name = entry.get("userName") or "?"
            wallet = entry.get("proxyWallet") or entry.get("userAddress", "")
            pnl = float(entry.get("pnl", 0))
            vol = float(entry.get("vol", 0))

            print(f"[{i}/{len(entries)}] Fetching {name}...", end=" ", flush=True)
            closed = await fetch_closed_paginated(session, wallet)
            print(f"{len(closed)} positions")

            result = analyze_trader(name, wallet, pnl, vol, closed)
            if result:
                results.append(result)
            await asyncio.sleep(0.3)

        # --- SUMMARY ---
        print(f"\n{'='*70}")
        print(f"  SUMMARY: {len(results)} traders analyzed")
        print(f"{'='*70}")
        algos = [r for r in results if r["verdict"] == "ALGO"]
        humans = [r for r in results if r["verdict"] == "HUMAN"]
        print(f"\n  ALGO:  {len(algos)}")
        for r in sorted(algos, key=lambda x: -x["pnl"]):
            print(f"    {r['name']:<20} PnL=${r['pnl']:>12,.0f}  "
                  f"WR={r['wr']:.0%}  positions={r['total']}  freq={r['freq']:.1f}/day")
        print(f"\n  HUMAN: {len(humans)}")
        for r in sorted(humans, key=lambda x: -x["pnl"]):
            print(f"    {r['name']:<20} PnL=${r['pnl']:>12,.0f}  "
                  f"WR={r['wr']:.0%}  positions={r['total']}  freq={r['freq']:.1f}/day")


if __name__ == "__main__":
    asyncio.run(main())
