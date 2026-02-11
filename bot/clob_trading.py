"""Async wrapper for py-clob-client CLOB trading operations.

Wraps the synchronous py-clob-client library via asyncio.to_thread()
to avoid blocking the event loop in the radar's async architecture.
"""

import asyncio
import logging
from dataclasses import dataclass

import config

logger = logging.getLogger(__name__)


@dataclass
class MarketInfo:
    """Parsed market data from CLOB API."""

    condition_id: str
    token_id: str
    outcome: str  # "YES" or "NO"
    accepting_orders: bool
    minimum_order_size: float
    minimum_tick_size: float
    neg_risk: bool


@dataclass
class OrderResult:
    """Result of a placed order."""

    success: bool
    order_id: str | None = None
    error_message: str | None = None
    avg_price: float = 0.0
    shares_filled: float = 0.0
    cost_usd: float = 0.0


class ClobTradingClient:
    """Async interface to Polymarket CLOB for placing FOK market orders."""

    def __init__(self, private_key: str, chain_id: int = 137):
        self._private_key = private_key
        self._chain_id = chain_id
        self._client = None

    def _ensure_client(self):
        """Create or return the ClobClient instance (synchronous)."""
        if self._client is None:
            from py_clob_client.client import ClobClient

            self._client = ClobClient(
                config.CLOB_API_BASE_URL,
                key=self._private_key,
                chain_id=self._chain_id,
                signature_type=0,
            )
            creds = self._client.create_or_derive_api_creds()
            self._client.set_api_creds(creds)
        return self._client

    async def initialize(self) -> None:
        """Initialize client and derive API creds (one-time)."""
        await asyncio.to_thread(self._ensure_client)
        logger.info("CLOB trading client initialized")

    async def get_balance(self) -> float:
        """Get USDC.e collateral balance in dollars."""

        def _get():
            client = self._ensure_client()
            result = client.get_balance_allowance(asset_type="COLLATERAL")
            if not result:
                return 0.0
            balance_raw = result.get("balance", "0")
            return float(balance_raw) / 1e6

        return await asyncio.to_thread(_get)

    async def resolve_token_id(
        self, condition_id: str, direction: str
    ) -> MarketInfo | None:
        """Resolve condition_id + direction to a token_id and market metadata."""

        def _resolve():
            client = self._ensure_client()
            market = client.get_market(condition_id)
            if not market:
                return None

            tokens = market.get("tokens", [])
            token_id = None
            for t in tokens:
                if t.get("outcome", "").upper() == direction.upper():
                    token_id = t["token_id"]
                    break

            if not token_id:
                return None

            return MarketInfo(
                condition_id=condition_id,
                token_id=token_id,
                outcome=direction.upper(),
                accepting_orders=bool(market.get("accepting_orders", False)),
                minimum_order_size=float(market.get("minimum_order_size", 0)),
                minimum_tick_size=float(market.get("minimum_tick_size", 0.01)),
                neg_risk=bool(market.get("neg_risk", False)),
            )

        return await asyncio.to_thread(_resolve)

    async def get_current_price(self, token_id: str) -> float | None:
        """Get the current midpoint price for a token."""

        def _get_price():
            client = self._ensure_client()
            result = client.get_midpoint(token_id=token_id)
            if result and "mid" in result:
                return float(result["mid"])
            return None

        return await asyncio.to_thread(_get_price)

    async def place_market_order(
        self,
        token_id: str,
        amount_usd: float,
    ) -> OrderResult:
        """Place a FOK market BUY order for the given amount in USDC."""

        def _place():
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY

            client = self._ensure_client()
            try:
                order_args = MarketOrderArgs(
                    token_id=token_id,
                    amount=amount_usd,
                    side=BUY,
                    order_type=OrderType.FOK,
                )
                signed_order = client.create_market_order(order_args)
                resp = client.post_order(signed_order, OrderType.FOK)

                if isinstance(resp, dict):
                    if resp.get("success") or resp.get("orderID"):
                        return OrderResult(
                            success=True,
                            order_id=resp.get("orderID"),
                            avg_price=float(resp.get("averagePrice", 0)),
                            shares_filled=float(resp.get("size", 0)),
                            cost_usd=amount_usd,
                        )
                    else:
                        return OrderResult(
                            success=False,
                            error_message=resp.get("errorMsg")
                            or resp.get("error")
                            or str(resp),
                        )

                return OrderResult(
                    success=True, order_id=str(resp), cost_usd=amount_usd
                )

            except Exception as e:
                return OrderResult(success=False, error_message=str(e))

        return await asyncio.to_thread(_place)
