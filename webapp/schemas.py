"""
Pydantic schemas for API responses.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TraderBrief(BaseModel):
    """Brief trader info for signal cards."""

    wallet_address: str
    username: Optional[str] = None
    trader_type: str  # HUMAN, ALGO, MM
    trader_score: float
    win_rate: float
    pnl: float
    conviction: float
    change_type: str  # OPEN, INCREASE, DECREASE, CLOSE
    size: float
    detected_at: Optional[str] = None


class SignalResponse(BaseModel):
    """Signal response schema."""

    id: int
    condition_id: str
    market_title: str
    market_slug: Optional[str] = None
    direction: str  # YES, NO
    signal_score: float
    peak_score: float
    tier: int  # 1, 2, 3
    status: str  # ACTIVE, WEAKENING, CLOSED
    current_price: float
    traders_involved: list[TraderBrief]
    created_at: str
    updated_at: str


class SignalListResponse(BaseModel):
    """Response for signal list."""

    signals: list[SignalResponse]
    total: int
    page: int
    page_size: int


class TraderResponse(BaseModel):
    """Full trader profile response."""

    wallet_address: str
    username: Optional[str] = None
    trader_type: str
    trader_score: float
    win_rate: float
    pnl: float
    total_closed: int
    timing_quality: Optional[float] = None
    domain_tags: list[str]
    algo_signals: list[str]
    category_scores: dict[str, float]
    recent_bets: list[dict]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TraderListResponse(BaseModel):
    """Response for trader list."""

    traders: list[TraderResponse]
    total: int
    page: int
    page_size: int
