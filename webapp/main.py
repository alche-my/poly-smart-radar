"""
Telegram MiniApp Backend - FastAPI Application

This module provides the REST API for the Poly Smart Radar MiniApp.
It reads data from the existing radar.db SQLite database.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from webapp.routers import signals, traders

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("MiniApp API starting...")
    yield
    logger.info("MiniApp API shutting down...")


app = FastAPI(
    title="Poly Smart Radar API",
    description="API for Telegram MiniApp - Polymarket whale tracking signals",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for MiniApp (Telegram WebView)
# Note: allow_credentials=False because we use Authorization header, not cookies
# This avoids CORS misconfiguration (can't use "*" with credentials=True)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Include routers
app.include_router(signals.router, prefix="/api/signals", tags=["signals"])
app.include_router(traders.router, prefix="/api/traders", tags=["traders"])


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "poly-smart-radar"}


@app.get("/api/stats")
async def get_stats():
    """Get overall statistics."""
    from fastapi import HTTPException
    from webapp.deps import get_db_path
    from db.models import _get_connection

    db_path = get_db_path()
    try:
        conn = _get_connection(db_path)
    except Exception as e:
        logger.error("Database connection failed: %s", e)
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        # Count signals by tier
        signals_by_tier = {}
        for tier in [1, 2, 3]:
            count = conn.execute(
                "SELECT COUNT(*) FROM signals WHERE tier = ?", (tier,)
            ).fetchone()[0]
            signals_by_tier[f"tier_{tier}"] = count

        # Count active signals
        active_count = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE status = 'ACTIVE'"
        ).fetchone()[0]

        # Count traders
        traders_count = conn.execute("SELECT COUNT(*) FROM traders").fetchone()[0]

        # Count by trader type
        human_count = conn.execute(
            "SELECT COUNT(*) FROM traders WHERE trader_type = 'HUMAN'"
        ).fetchone()[0]
        algo_count = conn.execute(
            "SELECT COUNT(*) FROM traders WHERE trader_type = 'ALGO'"
        ).fetchone()[0]

        return {
            "signals": {
                "total": sum(signals_by_tier.values()),
                "active": active_count,
                **signals_by_tier,
            },
            "traders": {
                "total": traders_count,
                "human": human_count,
                "algo": algo_count,
            },
        }
    except Exception as e:
        logger.error("Stats query failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get stats")
    finally:
        conn.close()
