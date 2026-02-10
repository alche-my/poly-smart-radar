import asyncio
import logging
from datetime import datetime

from api.gamma_api import GammaApiClient
from db.models import get_unresolved_signals, update_signal

logger = logging.getLogger(__name__)


class ResolutionChecker:
    """Checks whether markets for existing signals have resolved and records outcomes."""

    def __init__(self, gamma_api: GammaApiClient, db_path: str):
        self.gamma_api = gamma_api
        self.db_path = db_path

    async def check_all(self) -> dict:
        signals = get_unresolved_signals(self.db_path)
        if not signals:
            logger.info("Resolution check: no unresolved signals")
            return {"checked": 0, "resolved": 0}

        resolved_count = 0

        for signal in signals:
            condition_id = signal.get("condition_id")
            if not condition_id:
                continue

            market = await self.gamma_api.get_market_by_condition(condition_id)
            if not market:
                continue

            # Check if market has resolved
            # Gamma API fields: "resolved", "resolution", "end_date_iso"
            is_resolved = (
                market.get("resolved") is True
                or market.get("closed") is True
                or str(market.get("active", "")).lower() == "false"
                or str(market.get("resolved", "")).lower() == "true"
            )

            if not is_resolved:
                continue

            # Determine resolution outcome
            resolution = self._extract_resolution(market)
            if not resolution:
                continue

            # Calculate P&L
            entry_price = signal.get("current_price", 0)
            direction = signal.get("direction", "YES").upper()
            pnl = self._calc_pnl(direction, entry_price, resolution)

            now = datetime.utcnow().isoformat()
            update_signal(self.db_path, signal["id"], {
                "resolved_at": now,
                "resolution_outcome": resolution,
                "pnl_percent": pnl,
                "status": "RESOLVED",
                "updated_at": now,
            })

            resolved_count += 1
            logger.info(
                "Signal %d resolved: %s -> %s (direction=%s, entry=%.2f, pnl=%.1f%%)",
                signal["id"],
                signal.get("market_title", "")[:40],
                resolution,
                direction,
                entry_price,
                pnl * 100,
            )

            await asyncio.sleep(0.15)

        logger.info("Resolution check: %d checked, %d resolved", len(signals), resolved_count)
        return {"checked": len(signals), "resolved": resolved_count}

    @staticmethod
    def _extract_resolution(market: dict) -> str | None:
        """Extract YES/NO resolution from Gamma market data."""
        # Different possible field names in the API response
        for field in ("resolution", "outcome", "winner"):
            val = market.get(field)
            if val:
                return str(val).upper()

        # Some markets use numeric outcome: 1 = YES, 0 = NO
        outcome_val = market.get("outcome")
        if outcome_val is not None:
            try:
                return "YES" if float(outcome_val) > 0.5 else "NO"
            except (ValueError, TypeError):
                pass

        # Check tokens/outcomes array
        tokens = market.get("tokens") or market.get("outcomes") or []
        if isinstance(tokens, list):
            for token in tokens:
                if isinstance(token, dict):
                    price = float(token.get("price", 0) or 0)
                    if price >= 0.95:
                        return str(token.get("outcome", "YES")).upper()

        return None

    @staticmethod
    def _calc_pnl(direction: str, entry_price: float, resolution: str) -> float:
        """Calculate P&L as a fraction. E.g. 0.5 = +50%, -1.0 = -100%."""
        if entry_price <= 0 or entry_price >= 1:
            return 0.0

        signal_correct = (direction == resolution)

        if signal_correct:
            # Bought at entry_price, paid out $1
            return (1.0 - entry_price) / entry_price
        else:
            # Bought at entry_price, paid out $0
            return -1.0
