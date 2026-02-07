"""
Signals API router.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db.models import _get_connection
from webapp.deps import get_db_path
from webapp.schemas import SignalResponse, SignalListResponse, TraderBrief

logger = logging.getLogger(__name__)
router = APIRouter()

# Allowed values for enum-like fields
_ALLOWED_STATUS = {"ACTIVE", "WEAKENING", "CLOSED"}
_ALLOWED_TRADER_TYPE = {"HUMAN", "ALGO", "MM"}


def _parse_traders_involved(raw: str | list) -> list[TraderBrief]:
    """Parse traders_involved JSON into TraderBrief list."""
    if isinstance(raw, str):
        try:
            traders = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    else:
        traders = raw or []

    return [
        TraderBrief(
            wallet_address=t.get("wallet_address", ""),
            username=t.get("username"),
            trader_type=t.get("trader_type", "UNKNOWN"),
            trader_score=t.get("trader_score", 0),
            win_rate=t.get("win_rate", 0),
            pnl=t.get("pnl", 0),
            conviction=t.get("conviction", 1),
            change_type=t.get("change_type", "OPEN"),
            size=t.get("size", 0),
            detected_at=t.get("detected_at"),
        )
        for t in traders
    ]


def _row_to_signal(row: dict) -> SignalResponse:
    """Convert database row to SignalResponse."""
    return SignalResponse(
        id=row["id"],
        condition_id=row["condition_id"],
        market_title=row.get("market_title", ""),
        market_slug=row.get("market_slug"),
        direction=row.get("direction", "YES"),
        signal_score=row.get("signal_score", 0),
        peak_score=row.get("peak_score", 0),
        tier=row.get("tier", 3),
        status=row.get("status", "ACTIVE"),
        current_price=row.get("current_price", 0),
        traders_involved=_parse_traders_involved(row.get("traders_involved", "[]")),
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
    )


@router.get("", response_model=SignalListResponse)
async def list_signals(
    tier: Optional[int] = Query(None, ge=1, le=3, description="Filter by tier (1, 2, 3)"),
    status: Optional[str] = Query(None, description="Filter by status (ACTIVE, WEAKENING, CLOSED)"),
    trader_type: Optional[str] = Query(None, description="Filter by trader type (HUMAN, ALGO)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """
    Get list of signals with optional filters.

    - **tier**: Filter by signal tier (1 = highest priority)
    - **status**: Filter by signal status
    - **trader_type**: Filter signals that have this trader type involved
    - **page**: Page number (starts at 1)
    - **page_size**: Number of items per page (max 100)
    """
    # Validate enum-like parameters
    if status is not None and status.upper() not in _ALLOWED_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Allowed: {', '.join(_ALLOWED_STATUS)}",
        )
    if trader_type is not None and trader_type.upper() not in _ALLOWED_TRADER_TYPE:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid trader_type. Allowed: {', '.join(_ALLOWED_TRADER_TYPE)}",
        )

    db_path = get_db_path()
    conn = _get_connection(db_path)

    try:
        # Build query
        conditions = []
        params = []

        if tier is not None:
            conditions.append("tier = ?")
            params.append(tier)

        if status is not None:
            conditions.append("status = ?")
            params.append(status.upper())

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Get total count
        count_query = f"SELECT COUNT(*) FROM signals WHERE {where_clause}"
        total = conn.execute(count_query, params).fetchone()[0]

        # Get paginated results
        offset = (page - 1) * page_size
        query = f"""
            SELECT * FROM signals
            WHERE {where_clause}
            ORDER BY
                CASE status
                    WHEN 'ACTIVE' THEN 1
                    WHEN 'WEAKENING' THEN 2
                    ELSE 3
                END,
                tier ASC,
                signal_score DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params + [page_size, offset]).fetchall()

        # Convert to response
        signals = []
        for row in rows:
            signal = _row_to_signal(dict(row))

            # Apply trader_type filter (post-query since it's in JSON)
            if trader_type:
                has_type = any(
                    t.trader_type == trader_type.upper()
                    for t in signal.traders_involved
                )
                if not has_type:
                    continue

            signals.append(signal)

        return SignalListResponse(
            signals=signals,
            total=total,
            page=page,
            page_size=page_size,
        )

    finally:
        conn.close()


@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal(signal_id: int):
    """
    Get a specific signal by ID.
    """
    db_path = get_db_path()
    conn = _get_connection(db_path)

    try:
        row = conn.execute(
            "SELECT * FROM signals WHERE id = ?", (signal_id,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Signal not found")

        return _row_to_signal(dict(row))

    finally:
        conn.close()
