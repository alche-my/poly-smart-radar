import logging

import config
from api.base import BaseApiClient

logger = logging.getLogger(__name__)


class GammaApiClient(BaseApiClient):
    def __init__(self, base_url: str = config.GAMMA_API_BASE_URL):
        super().__init__(base_url)

    async def get_events(self, limit: int = 100, offset: int = 0) -> list[dict]:
        params = {"limit": limit, "offset": offset}
        result = await self._get("/events", params)
        return result if isinstance(result, list) else []

    async def get_markets(self, limit: int = 100, offset: int = 0) -> list[dict]:
        params = {"limit": limit, "offset": offset}
        result = await self._get("/markets", params)
        return result if isinstance(result, list) else []

    async def get_public_profile(self, address: str) -> dict:
        result = await self._get("/public-profile", {"address": address})
        return result if isinstance(result, dict) else {}

    async def get_market_by_condition(self, condition_id: str) -> dict:
        """Fetch market info by condition_id. Returns dict with resolution status."""
        result = await self._get("/markets", {"condition_id": condition_id})
        if isinstance(result, list) and result:
            return result[0]
        if isinstance(result, dict):
            return result
        return {}

    async def get_event_by_slug(self, slug: str) -> dict:
        """Fetch event info by slug."""
        result = await self._get("/events", {"slug": slug})
        if isinstance(result, list) and result:
            return result[0]
        return result if isinstance(result, dict) else {}
