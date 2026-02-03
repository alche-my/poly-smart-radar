import logging

import config
from api.base import BaseApiClient

logger = logging.getLogger(__name__)


class ClobApiClient(BaseApiClient):
    def __init__(self, base_url: str = config.CLOB_API_BASE_URL):
        super().__init__(base_url)

    async def get_price(self, token_id: str, side: str) -> dict:
        params = {"token_id": token_id, "side": side}
        result = await self._get("/price", params)
        return result if isinstance(result, dict) else {}

    async def get_midpoint(self, token_id: str) -> dict:
        params = {"token_id": token_id}
        result = await self._get("/midpoint", params)
        return result if isinstance(result, dict) else {}
