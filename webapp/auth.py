"""
Telegram MiniApp Authentication.

Validates initData from Telegram WebApp to ensure requests are authentic.
See: https://core.telegram.org/bots/webapps#validating-data-received-via-the-web-app
"""

import hashlib
import hmac
import logging
import time
from typing import Optional
from urllib.parse import parse_qs, unquote

from fastapi import HTTPException, Request
from pydantic import BaseModel

import config

logger = logging.getLogger(__name__)

# How long initData is valid (in seconds)
INIT_DATA_EXPIRY = 86400  # 24 hours


class TelegramUser(BaseModel):
    """Telegram user from initData."""

    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    language_code: Optional[str] = None
    is_premium: Optional[bool] = None


class InitData(BaseModel):
    """Parsed and validated initData."""

    user: Optional[TelegramUser] = None
    auth_date: int
    hash: str
    query_id: Optional[str] = None
    chat_type: Optional[str] = None
    chat_instance: Optional[str] = None


def validate_init_data(init_data_raw: str, bot_token: str) -> InitData:
    """
    Validate Telegram initData string.

    Args:
        init_data_raw: URL-encoded initData from Telegram.WebApp.initData
        bot_token: Bot token for HMAC validation

    Returns:
        Parsed InitData object

    Raises:
        ValueError: If validation fails
    """
    if not init_data_raw:
        raise ValueError("Empty initData")

    # Parse URL-encoded data
    parsed = parse_qs(init_data_raw, keep_blank_values=True)

    # Extract hash
    received_hash = parsed.get("hash", [""])[0]
    if not received_hash:
        raise ValueError("Missing hash in initData")

    # Build data-check-string (sorted key=value pairs, excluding hash)
    data_pairs = []
    for key, values in sorted(parsed.items()):
        if key != "hash":
            # URL decode the value
            value = unquote(values[0]) if values else ""
            data_pairs.append(f"{key}={value}")

    data_check_string = "\n".join(data_pairs)

    # Create secret key: HMAC-SHA256(bot_token, "WebAppData")
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode(),
        hashlib.sha256,
    ).digest()

    # Calculate hash: HMAC-SHA256(data_check_string, secret_key)
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    # Compare hashes
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError("Invalid initData hash")

    # Check expiration
    auth_date_str = parsed.get("auth_date", ["0"])[0]
    try:
        auth_date = int(auth_date_str)
    except ValueError:
        raise ValueError("Invalid auth_date")

    if time.time() - auth_date > INIT_DATA_EXPIRY:
        raise ValueError("initData expired")

    # Parse user JSON
    user = None
    user_raw = parsed.get("user", [""])[0]
    if user_raw:
        import json
        try:
            user_data = json.loads(unquote(user_raw))
            user = TelegramUser(**user_data)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Failed to parse user data: %s", e)

    return InitData(
        user=user,
        auth_date=auth_date,
        hash=received_hash,
        query_id=parsed.get("query_id", [None])[0],
        chat_type=parsed.get("chat_type", [None])[0],
        chat_instance=parsed.get("chat_instance", [None])[0],
    )


async def get_telegram_user(request: Request) -> Optional[TelegramUser]:
    """
    FastAPI dependency to extract and validate Telegram user.

    Usage:
        @router.get("/protected")
        async def protected_endpoint(user: TelegramUser = Depends(get_telegram_user)):
            return {"user_id": user.id}

    The initData should be passed in the Authorization header:
        Authorization: tma <initData>
    """
    # Get bot token
    bot_token = getattr(config, "TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        # No bot token = skip validation (development mode)
        logger.warning("No TELEGRAM_BOT_TOKEN, skipping initData validation")
        return None

    # Get Authorization header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("tma "):
        # No auth header = public endpoint or dev mode
        return None

    init_data_raw = auth_header[4:]  # Remove "tma " prefix

    try:
        init_data = validate_init_data(init_data_raw, bot_token)
        return init_data.user
    except ValueError as e:
        logger.warning("initData validation failed: %s", e)
        raise HTTPException(status_code=401, detail=str(e))


def require_telegram_auth(user: Optional[TelegramUser]) -> TelegramUser:
    """
    Require valid Telegram authentication.

    Usage:
        @router.get("/protected")
        async def protected_endpoint(
            user: Optional[TelegramUser] = Depends(get_telegram_user)
        ):
            user = require_telegram_auth(user)
            return {"user_id": user.id}
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Telegram authentication required")
    return user
