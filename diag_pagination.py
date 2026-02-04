"""Diagnostic: test closed-positions API pagination behavior."""
import asyncio
import aiohttp

DATA_API = "https://data-api.polymarket.com"

# Pick a known top-leaderboard trader to test
TEST_WALLET = None  # will be fetched from leaderboard


async def main():
    async with aiohttp.ClientSession() as session:
        # 1. Get a wallet from leaderboard
        url = f"{DATA_API}/v1/leaderboard"
        async with session.get(url, params={"category": "OVERALL", "timePeriod": "ALL", "orderBy": "PNL", "limit": 5}) as resp:
            leaders = await resp.json()

        wallet = leaders[0].get("proxyWallet") or leaders[0].get("userAddress")
        name = leaders[0].get("userName", wallet[:10])
        print(f"Testing with trader: {name} ({wallet[:16]}...)")
        print()

        # 2. Test: what does limit param actually do?
        for limit in [10, 25, 50, 100]:
            url = f"{DATA_API}/closed-positions"
            async with session.get(url, params={"user": wallet, "limit": limit}) as resp:
                data = await resp.json()
            count = len(data) if isinstance(data, list) else 0
            print(f"  limit={limit:>3}  → got {count} results")

        print()

        # 3. Test: does offset work?
        print("Pagination test (limit=50):")
        total = 0
        for offset in [0, 50, 100, 150]:
            url = f"{DATA_API}/closed-positions"
            async with session.get(url, params={"user": wallet, "limit": 50, "offset": offset}) as resp:
                data = await resp.json()
            count = len(data) if isinstance(data, list) else 0
            total += count
            print(f"  offset={offset:>3}, limit=50  → got {count} results")
            if count == 0:
                break

        print(f"\nTotal with pagination: {total}")

        # 4. Check current code's page_size
        print("\n--- Code check ---")
        with open("api/data_api.py") as f:
            for i, line in enumerate(f, 1):
                if "page_size" in line:
                    print(f"  Line {i}: {line.rstrip()}")


if __name__ == "__main__":
    asyncio.run(main())
