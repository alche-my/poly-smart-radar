"""Deep analysis of top-10 traders: verify ALGO hypothesis and trade patterns."""
import asyncio
import json
from collections import Counter
from datetime import datetime
import aiohttp

DATA_API = "https://data-api.polymarket.com"
TIMEOUT = aiohttp.ClientTimeout(total=15)

# Top-10 from last run
TOP_TRADERS = [
    ("Snoorrason", "0x56687bf4"),
    ("JohnnyTenNumbers", None),
    ("rwo", None),
    ("statwC00KS", None),
    ("sovereign2013", None),
    ("SHARKSEATDOGS", None),
    ("lmeow11", None),
    ("Pestle", None),
    ("qrpenc", None),
    ("bigmoneyloser00", None),
]


async def main():
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        # 1. Resolve wallets from leaderboard
        url = f"{DATA_API}/v1/leaderboard"
        all_entries = []
        for offset in [0, 50, 100, 150]:
            async with session.get(url, params={
                "category": "OVERALL", "timePeriod": "ALL",
                "orderBy": "PNL", "limit": 50, "offset": offset,
            }) as resp:
                batch = await resp.json()
                all_entries.extend(batch)
            await asyncio.sleep(0.2)

        # Map username -> wallet
        name_to_wallet = {}
        for e in all_entries:
            name = e.get("userName") or ""
            wallet = e.get("proxyWallet") or e.get("userAddress", "")
            pnl = float(e.get("pnl", 0))
            vol = float(e.get("vol", 0))
            if name:
                name_to_wallet[name] = {"wallet": wallet, "pnl": pnl, "vol": vol}

        # Find our top-10
        targets = []
        for name, _ in TOP_TRADERS:
            if name in name_to_wallet:
                targets.append((name, name_to_wallet[name]))

        if not targets:
            print("Could not find any top traders in leaderboard!")
            return

        print(f"Found {len(targets)} traders in leaderboard\n")

        for name, info in targets:
            wallet = info["wallet"]
            pnl = info["pnl"]
            vol = info["vol"]

            print(f"{'='*70}")
            print(f"TRADER: {name}")
            print(f"Wallet: {wallet}")
            print(f"PnL: ${pnl:,.0f}  |  Volume: ${vol:,.0f}  |  Efficiency: {pnl/vol*100:.2f}%" if vol > 0 else "")
            print(f"{'='*70}")

            # Fetch closed positions (first 50 for speed)
            try:
                url = f"{DATA_API}/closed-positions"
                async with session.get(url, params={"user": wallet, "limit": 50}) as resp:
                    closed = await resp.json()
                closed = closed if isinstance(closed, list) else []
            except Exception as e:
                print(f"  ERROR fetching closed: {e}\n")
                continue

            if not closed:
                print("  No closed positions found\n")
                continue

            # --- Analysis ---

            # A. Win/loss breakdown
            wins = [p for p in closed if float(p.get("realizedPnl", 0)) > 0]
            losses = [p for p in closed if float(p.get("realizedPnl", 0)) < 0]
            zeros = [p for p in closed if float(p.get("realizedPnl", 0)) == 0]
            print(f"\n  Positions (first {len(closed)}): {len(wins)} wins, {len(losses)} losses, {len(zeros)} zero")

            # B. Avg entry price distribution
            prices = [float(p.get("avgPrice", 0)) for p in wins]
            if prices:
                avg_p = sum(prices) / len(prices)
                min_p = min(prices)
                max_p = max(prices)
                print(f"  Avg entry price (wins): mean={avg_p:.3f}, min={min_p:.3f}, max={max_p:.3f}")

            # C. Position sizes
            bought = [float(p.get("totalBought", 0)) for p in closed]
            pnls = [float(p.get("realizedPnl", 0)) for p in closed]
            if bought:
                print(f"  Position sizes: mean=${sum(bought)/len(bought):,.0f}, "
                      f"min=${min(bought):,.0f}, max=${max(bought):,.0f}")
                print(f"  PnL per position: mean=${sum(pnls)/len(pnls):,.0f}, "
                      f"min=${min(pnls):,.0f}, max=${max(pnls):,.0f}")

            # D. Outcome distribution (YES vs NO)
            outcomes = Counter(p.get("outcome", "?").upper() for p in closed)
            print(f"  Outcomes: {dict(outcomes)}")

            # E. Time analysis - when do they trade?
            timestamps = []
            for p in closed:
                ts = p.get("timestamp")
                if ts:
                    try:
                        dt = datetime.fromtimestamp(int(ts))
                        timestamps.append(dt)
                    except (ValueError, TypeError):
                        pass

            if timestamps:
                hours = Counter(dt.hour for dt in timestamps)
                # Group into 6h blocks
                blocks = {"00-06": 0, "06-12": 0, "12-18": 0, "18-24": 0}
                for h, c in hours.items():
                    if h < 6: blocks["00-06"] += c
                    elif h < 12: blocks["06-12"] += c
                    elif h < 18: blocks["12-18"] += c
                    else: blocks["18-24"] += c
                print(f"  Trading hours (UTC): {blocks}")

                days = Counter(dt.strftime("%A") for dt in timestamps)
                print(f"  Trading days: {dict(days)}")

                # Time span
                ts_sorted = sorted(timestamps)
                span = (ts_sorted[-1] - ts_sorted[0]).days
                freq = len(closed) / max(span, 1)
                print(f"  Active period: {span} days, {freq:.1f} positions/day")

            # F. Market diversity - how many unique markets?
            markets = set(p.get("conditionId", "") for p in closed)
            titles = set((p.get("title", "") or "")[:50] for p in closed)
            print(f"  Unique markets: {len(markets)}")
            # Show first 5 market titles
            for t in list(titles)[:5]:
                print(f"    - {t}")

            # G. ALGO/HUMAN verdict
            print(f"\n  --- VERDICT ---")
            signals = []
            if len(closed) >= 50 and len(wins) / max(len(closed), 1) > 0.95:
                signals.append("WR>95% with 50+ positions")
            if bought and sum(bought) / len(bought) < 100:
                signals.append("Small avg position (<$100)")
            if timestamps and freq > 1.0:
                signals.append(f"High frequency ({freq:.1f}/day)")
            if len(markets) > 20:
                signals.append(f"High market diversity ({len(markets)} markets)")
            if vol > 0 and vol / max(pnl, 1) > 10:
                signals.append(f"High turnover ratio ({vol/pnl:.0f}x)")

            if signals:
                print(f"  LIKELY ALGO: {', '.join(signals)}")
            else:
                print(f"  LIKELY HUMAN")

            print()
            await asyncio.sleep(0.3)


if __name__ == "__main__":
    asyncio.run(main())
