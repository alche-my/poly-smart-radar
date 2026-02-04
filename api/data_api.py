import logging

import config
from api.base import BaseApiClient

logger = logging.getLogger(__name__)


class DataApiClient(BaseApiClient):
    def __init__(self, base_url: str = config.DATA_API_BASE_URL):
        super().__init__(base_url)

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
        all_results = []
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

    async def get_positions(self, user: str) -> list[dict]:
        result = await self._get("/positions", {"user": user})
        return result if isinstance(result, list) else []

    async def get_closed_positions(
        self, user: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        params = {"user": user, "limit": limit, "offset": offset}
        result = await self._get("/closed-positions", params)
        return result if isinstance(result, list) else []

    async def get_closed_positions_all(
        self, user: str, max_results: int = 2000
    ) -> list[dict]:
        all_results = []
        offset = 0
        page_size = 50  # API returns max 50 per request
        while offset < max_results:
            batch = await self.get_closed_positions(user, limit=page_size, offset=offset)
            if not batch:
                break
            all_results.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        return all_results[:max_results]

    async def get_trades(
        self, user: str, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        params = {"user": user, "limit": limit, "offset": offset}
        result = await self._get("/trades", params)
        return result if isinstance(result, list) else []

    async def get_activity(self, user: str, limit: int = 100) -> list[dict]:
        params = {"user": user, "limit": limit}
        result = await self._get("/activity", params)
        return result if isinstance(result, list) else []

    async def get_holders(self, market: str, limit: int = 20) -> list[dict]:
        params = {"market": market, "limit": limit}
        result = await self._get("/holders", params)
        return result if isinstance(result, list) else []

    async def get_value(self, user: str) -> dict:
        result = await self._get("/value", {"user": user})
        return result if isinstance(result, dict) else {}
