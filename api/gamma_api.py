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
