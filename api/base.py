import asyncio
import logging
import re

import aiohttp

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=20)
_MAX_RETRIES = 3
_BACKOFF_BASE = 1  # seconds: 1, 2, 4
_REQUEST_DELAY = 0.15  # seconds between sequential requests
_MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10 MB safety cap

_WALLET_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def is_valid_wallet(address: str) -> bool:
    """Validate Ethereum/Polygon wallet address format."""
    return bool(_WALLET_RE.match(address))


class BaseApiClient:
    def __init__(self, base_url: str):
        if not base_url.startswith("https://"):
            raise ValueError(f"base_url must use HTTPS: {base_url}")
        self.base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=_DEFAULT_TIMEOUT,
                raise_for_status=False,
            )
        return self._session

    async def _get(self, path: str, params: dict | None = None) -> dict | list:
        session = await self._ensure_session()
        url = f"{self.base_url}{path}"

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        # Check content-length before reading
                        cl = resp.content_length
                        if cl is not None and cl > _MAX_RESPONSE_SIZE:
                            logger.error(
                                "%s response too large (%d bytes), skipping", url, cl,
                            )
                            return {}
                        await asyncio.sleep(_REQUEST_DELAY)
                        return await resp.json(content_type=None)

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
                    logger.error(
                        "%s returned %s: %.200s", url, resp.status, text,
                    )
                    return {} if not text.startswith("[") else []

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt == _MAX_RETRIES:
                    logger.error("%s failed after %d retries: %s", url, _MAX_RETRIES, e)
                    return {}
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
            # Allow underlying SSL transports to close cleanly
            await asyncio.sleep(0.25)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
