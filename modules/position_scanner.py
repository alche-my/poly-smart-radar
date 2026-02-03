import asyncio
import logging
from datetime import datetime

import config
from api.data_api import DataApiClient
from db.models import (
    get_traders,
    get_trader,
    get_latest_snapshots,
    insert_snapshots,
    insert_changes,
)

logger = logging.getLogger(__name__)


def _make_key(position: dict) -> tuple[str, str]:
    cid = position.get("condition_id") or position.get("conditionId", "")
    outcome = (position.get("outcome") or "").upper()
    return (cid, outcome)


def diff_positions(previous: list[dict], current: list[dict]) -> list[dict]:
    prev_map = {}
    for p in previous:
        key = _make_key(p)
        prev_map[key] = p

    curr_map = {}
    for c in current:
        key = _make_key(c)
        curr_map[key] = c

    changes = []

    # Check current positions against previous
    for key, cur in curr_map.items():
        cur_size = float(cur.get("size", 0))
        if key in prev_map:
            prev_size = float(prev_map[key].get("size", 0))
            if cur_size > prev_size:
                changes.append(_build_change(cur, "INCREASE", prev_size, cur_size))
            elif cur_size < prev_size:
                changes.append(_build_change(cur, "DECREASE", prev_size, cur_size))
        else:
            changes.append(_build_change(cur, "OPEN", 0, cur_size))

    # Check for closed positions (in prev but not in curr)
    for key, prev in prev_map.items():
        if key not in curr_map:
            changes.append(_build_change(prev, "CLOSE", float(prev.get("size", 0)), 0))

    return changes


def _build_change(position: dict, change_type: str, old_size: float, new_size: float) -> dict:
    return {
        "condition_id": position.get("condition_id") or position.get("conditionId", ""),
        "title": position.get("title", ""),
        "slug": position.get("slug", ""),
        "event_slug": position.get("event_slug") or position.get("eventSlug", ""),
        "outcome": (position.get("outcome") or "").upper(),
        "change_type": change_type,
        "old_size": old_size,
        "new_size": new_size,
        "price_at_change": float(position.get("cur_price") or position.get("curPrice") or 0),
    }


def calc_conviction(change: dict, avg_position_size: float) -> float:
    if avg_position_size <= 0:
        return 1.0
    delta = abs(change["new_size"] - change["old_size"])
    price = change.get("price_at_change", 0)
    dollar_delta = delta * price if price > 0 else delta
    return round(dollar_delta / avg_position_size, 4)


class PositionScanner:
    def __init__(self, data_api: DataApiClient, db_path: str):
        self.data_api = data_api
        self.db_path = db_path

    async def scan_all(self) -> list[dict]:
        traders = get_traders(self.db_path)
        if not traders:
            logger.warning("No traders in watchlist, skipping scan")
            return []

        all_changes = []
        now = datetime.utcnow().isoformat()

        for i, trader in enumerate(traders):
            wallet = trader["wallet_address"]
            avg_size = trader.get("avg_position_size", 0) or 0
            logger.info("Scanning %d/%d: %s", i + 1, len(traders), wallet[:10])

            # Get current positions from API
            current_raw = await self.data_api.get_positions(wallet)
            current = self._normalize_positions(current_raw)

            # Get previous snapshot from DB
            previous = get_latest_snapshots(self.db_path, wallet)

            if not previous:
                # First scan for this trader — bootstrap from trade history
                previous = await self._bootstrap_trader(wallet)

            # Diff
            changes = diff_positions(previous, current)

            # Add wallet + conviction + timestamp
            for c in changes:
                c["wallet_address"] = wallet
                c["conviction_score"] = calc_conviction(c, avg_size)
                c["detected_at"] = now

            if changes:
                insert_changes(self.db_path, changes)
                all_changes.extend(changes)
                logger.info("  %d changes detected for %s", len(changes), wallet[:10])

            # Save current snapshot
            snapshots = [
                {
                    "wallet_address": wallet,
                    "condition_id": p.get("condition_id", ""),
                    "title": p.get("title", ""),
                    "slug": p.get("slug", ""),
                    "outcome": p.get("outcome", ""),
                    "size": float(p.get("size", 0)),
                    "avg_price": float(p.get("avg_price", 0)),
                    "current_value": float(p.get("current_value", 0)),
                    "cur_price": float(p.get("cur_price", 0)),
                    "scanned_at": now,
                }
                for p in current
            ]
            insert_snapshots(self.db_path, snapshots)

            await asyncio.sleep(0.1)

        logger.info("Scan complete: %d traders, %d changes", len(traders), len(all_changes))
        return all_changes

    async def _bootstrap_trader(self, wallet: str) -> list[dict]:
        logger.info("  Bootstrapping %s from trade history...", wallet[:10])
        trades = await self.data_api.get_trades(wallet, limit=500)
        if not trades:
            return []

        # Aggregate trades into synthetic positions
        positions: dict[tuple, dict] = {}
        for t in trades:
            cid = t.get("conditionId") or t.get("condition_id", "")
            outcome = (t.get("outcome") or t.get("side") or "").upper()
            key = (cid, outcome)

            if key not in positions:
                positions[key] = {
                    "condition_id": cid,
                    "title": t.get("title") or t.get("eventTitle", ""),
                    "slug": t.get("slug", ""),
                    "event_slug": t.get("eventSlug", ""),
                    "outcome": outcome,
                    "size": 0,
                    "avg_price": 0,
                    "cur_price": float(t.get("price", 0)),
                    "current_value": 0,
                }
            positions[key]["size"] += float(t.get("size", 0))

        return list(positions.values())

    @staticmethod
    def _normalize_positions(raw: list[dict]) -> list[dict]:
        normalized = []
        for p in raw:
            normalized.append({
                "condition_id": p.get("conditionId") or p.get("condition_id", ""),
                "title": p.get("title", ""),
                "slug": p.get("slug", ""),
                "event_slug": p.get("eventSlug") or p.get("event_slug", ""),
                "outcome": (p.get("outcome") or "").upper(),
                "size": float(p.get("size", 0)),
                "avg_price": float(p.get("avgPrice") or p.get("avg_price", 0)),
                "current_value": float(p.get("currentValue") or p.get("current_value", 0)),
                "cur_price": float(p.get("curPrice") or p.get("cur_price", 0)),
            })
        return normalized
