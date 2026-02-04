import logging

import config
from api.base import BaseApiClient

logger = logging.getLogger(__name__)


class DataApiClient(BaseApiClient):
    def __init__(self, base_url: str = config.DATA_API_BASE_URL):
        super().__init__(base_url)

    # ---- Leaderboard ----

    async def get_leaderboard(
        self,
        category: str = "OVERALL",
        time_period: str = "ALL",
        order_by: str = "PNL",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        params = {
            "category": category,
            "timePeriod": time_period,
            "orderBy": order_by,
            "limit": limit,
            "offset": offset,
        }
        result = await self._get("/v1/leaderboard", params)
        return result if isinstance(result, list) else []

    async def get_leaderboard_all(
        self,
        category: str = "OVERALL",
        time_period: str = "ALL",
        order_by: str = "PNL",
        max_results: int = 200,
    ) -> list[dict]:
        all_results: list[dict] = []
        offset = 0
        page_size = 50
        while offset < max_results:
            batch = await self.get_leaderboard(
                category=category,
                time_period=time_period,
                order_by=order_by,
                limit=page_size,
                offset=offset,
            )
            if not batch:
                break
            all_results.extend(batch)
            offset += page_size
        return all_results[:max_results]

    # ---- Positions (open) ----

    async def get_positions(self, user: str, limit: int = 500, offset: int = 0) -> list[dict]:
        params = {"user": user, "limit": limit, "offset": offset}
        result = await self._get("/positions", params)
        return result if isinstance(result, list) else []

    async def get_positions_all(self, user: str) -> list[dict]:
        """Fetch ALL open positions (paginate with limit=500)."""
        all_results: list[dict] = []
        offset = 0
        page_size = 500
        while True:
            batch = await self.get_positions(user, limit=page_size, offset=offset)
            if not batch:
                break
            all_results.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
            if offset > 10_000:  # safety cap
                break
        return all_results

    # ---- Closed positions ----

    async def get_closed_positions(
        self,
        user: str,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "REALIZEDPNL",
        sort_direction: str = "DESC",
    ) -> list[dict]:
        params = {
            "user": user,
            "limit": limit,
            "offset": offset,
            "sortBy": sort_by,
            "sortDirection": sort_direction,
        }
        result = await self._get("/closed-positions", params)
        return result if isinstance(result, list) else []

    async def get_closed_positions_chronological(
        self, user: str, since_ts: int = 0, max_results: int = 500,
    ) -> list[dict]:
        """Fetch closed positions sorted by TIMESTAMP DESC (most recent first).

        Paginates until we've either collected `max_results` positions or gone
        past the `since_ts` cutoff.  Much more efficient than the old
        PnL-sorted approach because we can stop early.
        """
        all_results: list[dict] = []
        offset = 0
        page_size = 50  # API returns max 50 per page for /closed-positions
        while len(all_results) < max_results:
            batch = await self.get_closed_positions(
                user, limit=page_size, offset=offset,
                sort_by="TIMESTAMP", sort_direction="DESC",
            )
            if not batch:
                break

            hit_cutoff = False
            for pos in batch:
                ts = int(pos.get("timestamp", 0) or 0)
                if since_ts and ts < since_ts:
                    hit_cutoff = True
                    break
                all_results.append(pos)

            if hit_cutoff or len(batch) < page_size:
                break
            offset += page_size
            if offset > 10_000:  # safety: API supports offset up to 100000
                break
        return all_results

    # ---- Trades ----

    async def get_trades(
        self, user: str, limit: int = 100, offset: int = 0,
    ) -> list[dict]:
        params = {"user": user, "limit": limit, "offset": offset}
        result = await self._get("/trades", params)
        return result if isinstance(result, list) else []

    # ---- Activity ----

    async def get_activity(
        self, user: str, *, types: str | None = None,
        start: int | None = None, end: int | None = None,
        limit: int = 500, offset: int = 0,
    ) -> list[dict]:
        """Fetch user on-chain activity, ordered by timestamp desc."""
        params: dict = {
            "user": user, "limit": limit, "offset": offset,
            "sortBy": "TIMESTAMP", "sortDirection": "DESC",
        }
        if types:
            params["type"] = types
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        result = await self._get("/activity", params)
        return result if isinstance(result, list) else []

    async def get_activity_all(
        self, user: str, *, types: str | None = None,
        start: int | None = None, end: int | None = None,
    ) -> list[dict]:
        """Paginate /activity (API limit: offset <= 1000, limit <= 500)."""
        all_results: list[dict] = []
        offset = 0
        page_size = 500
        while offset <= 1000:
            batch = await self.get_activity(
                user, types=types, start=start, end=end,
                limit=page_size, offset=offset,
            )
            if not batch:
                break
            all_results.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        return all_results

    # ---- Misc ----

    async def get_holders(self, market: str, limit: int = 20) -> list[dict]:
        params = {"market": market, "limit": limit}
        result = await self._get("/holders", params)
        return result if isinstance(result, list) else []

    async def get_value(self, user: str) -> dict:
        result = await self._get("/value", {"user": user})
        return result if isinstance(result, dict) else {}
