import asyncio
import logging

import aiohttp

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)
_MAX_RETRIES = 3
_BACKOFF_BASE = 1  # seconds: 1, 2, 4
_REQUEST_DELAY = 0.2  # seconds between sequential requests


class BaseApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_DEFAULT_TIMEOUT)
        return self._session

    async def _get(self, path: str, params: dict | None = None) -> dict | list:
        session = await self._ensure_session()
        url = f"{self.base_url}{path}"

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        await asyncio.sleep(_REQUEST_DELAY)
                        return await resp.json()

                    if resp.status == 404:
                        await asyncio.sleep(_REQUEST_DELAY)
                        logger.debug("%s returned 404", url)
                        return {}

                    if resp.status == 429 or resp.status >= 500:
                        wait = _BACKOFF_BASE * (2 ** (attempt - 1))
                        logger.warning(
                            "%s returned %s, retry %d/%d in %ds",
                            url, resp.status, attempt, _MAX_RETRIES, wait,
                        )
                        await asyncio.sleep(wait)
                        continue

                    text = await resp.text()
                    logger.error("%s returned %s: %s", url, resp.status, text[:200])
                    return {} if not text.startswith("[") else []

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                wait = _BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "%s error: %s, retry %d/%d in %ds",
                    url, e, attempt, _MAX_RETRIES, wait,
                )
                await asyncio.sleep(wait)

        logger.error("%s failed after %d retries", url, _MAX_RETRIES)
        return {}

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
