"""Diagnostic: inspect leaderboard fields and closed-positions API."""
import asyncio
import json
import aiohttp

DATA_API = "https://data-api.polymarket.com"
TIMEOUT = aiohttp.ClientTimeout(total=15)


async def main():
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        # 1. Get top-5 from leaderboard and show ALL fields
        url = f"{DATA_API}/v1/leaderboard"
        async with session.get(url, params={
            "category": "OVERALL", "timePeriod": "ALL", "orderBy": "PNL", "limit": 5
        }) as resp:
            leaders = await resp.json()

        print("=== LEADERBOARD ENTRY FIELDS (top-1) ===")
        if leaders:
            print(json.dumps(leaders[0], indent=2, default=str))

        print("\n=== TOP-5 SUMMARY ===")
        for i, entry in enumerate(leaders[:5], 1):
            name = entry.get("userName") or entry.get("username") or "?"
            pnl_keys = [k for k in entry if "pnl" in k.lower() or "profit" in k.lower()]
            vol_keys = [k for k in entry if "vol" in k.lower() or "bought" in k.lower()]
            print(f"  {i}. {name}")
            for k in pnl_keys:
                print(f"     {k} = {entry[k]}")
            for k in vol_keys:
                print(f"     {k} = {entry[k]}")

        # 2. Test closed positions for top trader
        wallet = leaders[0].get("proxyWallet") or leaders[0].get("userAddress")
        name = leaders[0].get("userName", wallet[:10])
        print(f"\n=== CLOSED POSITIONS for {name} ===")
        for limit in [10, 25, 50]:
            try:
                url = f"{DATA_API}/closed-positions"
                async with session.get(url, params={"user": wallet, "limit": limit}) as resp:
                    data = await resp.json()
                count = len(data) if isinstance(data, list) else 0
                print(f"  limit={limit:>3}  → got {count}")
            except Exception as e:
                print(f"  limit={limit:>3}  → ERROR: {e}")

        # 3. Show first closed position fields
        url = f"{DATA_API}/closed-positions"
        async with session.get(url, params={"user": wallet, "limit": 1}) as resp:
            data = await resp.json()
        if data and isinstance(data, list):
            print(f"\n=== CLOSED POSITION FIELDS (sample) ===")
            print(json.dumps(data[0], indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
