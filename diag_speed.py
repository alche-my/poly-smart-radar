"""Diagnostic: measure time per API call in _score_trader pipeline."""
import asyncio
import time
import aiohttp

DATA_API = "https://data-api.polymarket.com"
TIMEOUT = aiohttp.ClientTimeout(total=15)


async def main():
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        # Get first 10 wallets from leaderboard
        url = f"{DATA_API}/v1/leaderboard"
        async with session.get(url, params={
            "category": "OVERALL", "timePeriod": "ALL", "orderBy": "PNL", "limit": 10
        }) as resp:
            leaders = await resp.json()

        print("=== CLOSED POSITIONS PAGINATION TIMING ===")
        print(f"{'#':<3} {'name':<20} {'pages':<6} {'total':<6} {'time':<8}")
        print("-" * 50)

        for i, entry in enumerate(leaders[:10], 1):
            wallet = entry.get("proxyWallet") or entry.get("userAddress")
            name = (entry.get("userName") or wallet[:10])[:20]

            t0 = time.monotonic()
            all_positions = []
            pages = 0
            offset = 0

            while offset < 2000:
                pages += 1
                try:
                    url = f"{DATA_API}/closed-positions"
                    async with session.get(url, params={
                        "user": wallet, "limit": 50, "offset": offset
                    }) as resp:
                        if resp.status == 429:
                            print(f"  [{name}] 429 at page {pages}, waiting 2s...")
                            await asyncio.sleep(2)
                            pages -= 1
                            continue
                        data = await resp.json()
                except Exception as e:
                    print(f"  [{name}] error: {e}")
                    break

                count = len(data) if isinstance(data, list) else 0
                all_positions.extend(data if isinstance(data, list) else [])
                if count < 50:
                    break
                offset += 50
                await asyncio.sleep(0.15)

            elapsed = time.monotonic() - t0
            print(f"{i:<3} {name:<20} {pages:<6} {len(all_positions):<6} {elapsed:.1f}s")

        print("\n=== CONCLUSION ===")
        print("If 'pages' is high (>5), pagination is the bottleneck.")
        print("If 'time' is high but 'pages' is low, it's rate limiting/latency.")


if __name__ == "__main__":
    asyncio.run(main())
