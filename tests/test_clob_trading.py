"""Tests for bot/clob_trading.py — CLOB API wrapper with mocked py-clob-client."""

import sys
from unittest.mock import patch, MagicMock

import pytest

from bot.clob_trading import ClobTradingClient, MarketInfo, OrderResult


@pytest.fixture
def mock_clob_client():
    """Create a mock ClobClient."""
    with patch("bot.clob_trading.ClobTradingClient._ensure_client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.mark.asyncio
class TestResolveTokenId:
    async def test_yes_direction(self, mock_clob_client):
        mock_clob_client.get_market.return_value = {
            "tokens": [
                {"token_id": "tok_yes", "outcome": "Yes"},
                {"token_id": "tok_no", "outcome": "No"},
            ],
            "accepting_orders": True,
            "minimum_order_size": 1,
            "minimum_tick_size": 0.01,
            "neg_risk": False,
        }
        trading = ClobTradingClient("0xfake")
        result = await trading.resolve_token_id("cond_123", "YES")
        assert result is not None
        assert result.token_id == "tok_yes"
        assert result.outcome == "YES"
        assert result.accepting_orders is True

    async def test_no_direction(self, mock_clob_client):
        mock_clob_client.get_market.return_value = {
            "tokens": [
                {"token_id": "tok_yes", "outcome": "Yes"},
                {"token_id": "tok_no", "outcome": "No"},
            ],
            "accepting_orders": True,
            "minimum_order_size": 1,
            "minimum_tick_size": 0.01,
            "neg_risk": False,
        }
        trading = ClobTradingClient("0xfake")
        result = await trading.resolve_token_id("cond_123", "NO")
        assert result is not None
        assert result.token_id == "tok_no"
        assert result.outcome == "NO"

    async def test_market_not_found(self, mock_clob_client):
        mock_clob_client.get_market.return_value = None
        trading = ClobTradingClient("0xfake")
        result = await trading.resolve_token_id("cond_missing", "YES")
        assert result is None

    async def test_token_not_found(self, mock_clob_client):
        mock_clob_client.get_market.return_value = {
            "tokens": [],
            "accepting_orders": True,
            "minimum_order_size": 1,
            "minimum_tick_size": 0.01,
            "neg_risk": False,
        }
        trading = ClobTradingClient("0xfake")
        result = await trading.resolve_token_id("cond_123", "YES")
        assert result is None

    async def test_neg_risk_market(self, mock_clob_client):
        mock_clob_client.get_market.return_value = {
            "tokens": [
                {"token_id": "tok_yes", "outcome": "Yes"},
                {"token_id": "tok_no", "outcome": "No"},
            ],
            "accepting_orders": True,
            "minimum_order_size": 1,
            "minimum_tick_size": 0.01,
            "neg_risk": True,
        }
        trading = ClobTradingClient("0xfake")
        result = await trading.resolve_token_id("cond_123", "YES")
        assert result is not None
        assert result.neg_risk is True


@pytest.mark.asyncio
class TestGetCurrentPrice:
    async def test_returns_midpoint(self, mock_clob_client):
        mock_clob_client.get_midpoint.return_value = {"mid": "0.55"}
        trading = ClobTradingClient("0xfake")
        price = await trading.get_current_price("tok_123")
        assert price == 0.55

    async def test_no_midpoint(self, mock_clob_client):
        mock_clob_client.get_midpoint.return_value = {}
        trading = ClobTradingClient("0xfake")
        price = await trading.get_current_price("tok_123")
        assert price is None


@pytest.mark.asyncio
class TestGetBalance:
    async def test_returns_balance_in_dollars(self, mock_clob_client):
        mock_clob_client.get_balance_allowance.return_value = {
            "balance": "10000000"  # 10 USDC (6 decimals)
        }
        trading = ClobTradingClient("0xfake")
        balance = await trading.get_balance()
        assert balance == 10.0

    async def test_empty_balance(self, mock_clob_client):
        mock_clob_client.get_balance_allowance.return_value = {}
        trading = ClobTradingClient("0xfake")
        balance = await trading.get_balance()
        assert balance == 0.0


@pytest.mark.asyncio
class TestPlaceMarketOrder:
    async def test_success(self, mock_clob_client):
        # Mock the py_clob_client imports used inside _place()
        mock_order_type = MagicMock()
        mock_order_type.FOK = "FOK"
        mock_market_args = MagicMock()

        with patch.dict("sys.modules", {
            "py_clob_client": MagicMock(),
            "py_clob_client.clob_types": MagicMock(
                MarketOrderArgs=mock_market_args, OrderType=mock_order_type
            ),
            "py_clob_client.order_builder": MagicMock(),
            "py_clob_client.order_builder.constants": MagicMock(BUY="BUY"),
        }):
            mock_clob_client.create_market_order.return_value = MagicMock()
            mock_clob_client.post_order.return_value = {
                "orderID": "ord_abc",
                "averagePrice": 0.50,
                "size": 1.0,
                "success": True,
            }
            trading = ClobTradingClient("0xfake")
            result = await trading.place_market_order("tok_123", 0.50)
            assert result.success is True
            assert result.order_id == "ord_abc"
            assert result.cost_usd == 0.50

    async def test_failure(self, mock_clob_client):
        mock_order_type = MagicMock()
        mock_order_type.FOK = "FOK"
        mock_market_args = MagicMock()

        with patch.dict("sys.modules", {
            "py_clob_client": MagicMock(),
            "py_clob_client.clob_types": MagicMock(
                MarketOrderArgs=mock_market_args, OrderType=mock_order_type
            ),
            "py_clob_client.order_builder": MagicMock(),
            "py_clob_client.order_builder.constants": MagicMock(BUY="BUY"),
        }):
            mock_clob_client.create_market_order.return_value = MagicMock()
            mock_clob_client.post_order.return_value = {
                "errorMsg": "Insufficient funds",
            }
            trading = ClobTradingClient("0xfake")
            result = await trading.place_market_order("tok_123", 0.50)
            assert result.success is False
            assert "Insufficient funds" in result.error_message

    async def test_exception(self, mock_clob_client):
        mock_order_type = MagicMock()
        mock_order_type.FOK = "FOK"
        mock_market_args = MagicMock()

        with patch.dict("sys.modules", {
            "py_clob_client": MagicMock(),
            "py_clob_client.clob_types": MagicMock(
                MarketOrderArgs=mock_market_args, OrderType=mock_order_type
            ),
            "py_clob_client.order_builder": MagicMock(),
            "py_clob_client.order_builder.constants": MagicMock(BUY="BUY"),
        }):
            mock_clob_client.create_market_order.side_effect = Exception("Network error")
            trading = ClobTradingClient("0xfake")
            result = await trading.place_market_order("tok_123", 0.50)
            assert result.success is False
            assert "Network error" in result.error_message
