"""
Traders API router.
"""

import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db.models import _get_connection
from webapp.deps import get_db_path
from webapp.schemas import TraderResponse, TraderListResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# Wallet address validation pattern
_WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _validate_wallet(wallet_address: str) -> None:
    """Validate wallet address format to prevent injection attacks."""
    if not _WALLET_RE.match(wallet_address):
        raise HTTPException(status_code=400, detail="Invalid wallet address format")


def _parse_json_field(raw: str | list | dict, default=None):
    """Parse JSON field from database."""
    if default is None:
        default = []
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return default
    return raw if raw is not None else default


def _row_to_trader(row: dict) -> TraderResponse:
    """Convert database row to TraderResponse."""
    return TraderResponse(
        wallet_address=row["wallet_address"],
        username=row.get("username"),
        trader_type=row.get("trader_type", "UNKNOWN"),
        trader_score=row.get("trader_score", 0),
        win_rate=row.get("win_rate", 0),
        pnl=row.get("pnl", 0),
        total_closed=row.get("total_closed", 0),
        timing_quality=row.get("timing_quality"),
        domain_tags=_parse_json_field(row.get("domain_tags", "[]")),
        algo_signals=_parse_json_field(row.get("algo_signals", "[]")),
        category_scores=_parse_json_field(row.get("category_scores", "{}"), {}),
        recent_bets=_parse_json_field(row.get("recent_bets", "[]")),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


@router.get("", response_model=TraderListResponse)
async def list_traders(
    trader_type: Optional[str] = Query(None, description="Filter by type (HUMAN, ALGO, MM)"),
    min_score: Optional[float] = Query(None, description="Minimum trader score"),
    sort_by: str = Query("trader_score", description="Sort by field"),
    sort_order: str = Query("desc", description="Sort order (asc, desc)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """
    Get list of traders from watchlist.

    - **trader_type**: Filter by trader type (HUMAN, ALGO, MM)
    - **min_score**: Minimum trader score filter
    - **sort_by**: Field to sort by (trader_score, win_rate, pnl)
    - **sort_order**: Sort direction (asc, desc)
    """
    db_path = get_db_path()
    conn = _get_connection(db_path)

    try:
        # Build query
        conditions = []
        params = []

        if trader_type:
            conditions.append("trader_type = ?")
            params.append(trader_type.upper())

        if min_score is not None:
            conditions.append("trader_score >= ?")
            params.append(min_score)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Validate sort field
        allowed_sort = {"trader_score", "win_rate", "pnl", "total_closed", "timing_quality"}
        if sort_by not in allowed_sort:
            sort_by = "trader_score"

        order = "DESC" if sort_order.lower() == "desc" else "ASC"

        # Get total count
        count_query = f"SELECT COUNT(*) FROM traders WHERE {where_clause}"
        total = conn.execute(count_query, params).fetchone()[0]

        # Get paginated results
        offset = (page - 1) * page_size
        query = f"""
            SELECT * FROM traders
            WHERE {where_clause}
            ORDER BY {sort_by} {order}
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [page_size, offset]).fetchall()

        traders = [_row_to_trader(dict(row)) for row in rows]

        return TraderListResponse(
            traders=traders,
            total=total,
            page=page,
            page_size=page_size,
        )

    finally:
        conn.close()


@router.get("/{wallet_address}", response_model=TraderResponse)
async def get_trader(wallet_address: str):
    """
    Get a specific trader by wallet address.
    """
    _validate_wallet(wallet_address)
    db_path = get_db_path()
    conn = _get_connection(db_path)

    try:
        row = conn.execute(
            "SELECT * FROM traders WHERE wallet_address = ?", (wallet_address,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Trader not found")

        return _row_to_trader(dict(row))

    finally:
        conn.close()


@router.get("/{wallet_address}/signals")
async def get_trader_signals(
    wallet_address: str,
    limit: int = Query(10, ge=1, le=50, description="Number of signals"),
):
    """
    Get signals where this trader is involved.
    """
    _validate_wallet(wallet_address)
    db_path = get_db_path()
    conn = _get_connection(db_path)

    try:
        # Check trader exists
        trader = conn.execute(
            "SELECT wallet_address FROM traders WHERE wallet_address = ?",
            (wallet_address,)
        ).fetchone()

        if not trader:
            raise HTTPException(status_code=404, detail="Trader not found")

        # Find signals with this trader
        # We need to search in JSON field traders_involved
        rows = conn.execute(
            """
            SELECT * FROM signals
            WHERE traders_involved LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (f"%{wallet_address}%", limit)
        ).fetchall()

        from webapp.routers.signals import _row_to_signal
        signals = [_row_to_signal(dict(row)) for row in rows]

        return {"signals": signals, "total": len(signals)}

    finally:
        conn.close()
