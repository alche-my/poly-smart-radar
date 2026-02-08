import json
from typing import Optional

from fastapi import APIRouter, Query

import config
from db.models import _get_connection

router = APIRouter(tags=["traders"])

_db_path = config.DB_PATH


@router.get("/traders")
def list_traders(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("trader_score", pattern="^(trader_score|win_rate|roi|total_closed)$"),
):
    conn = _get_connection(_db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM traders ORDER BY {sort_by} DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        traders = []
        for r in rows:
            t = dict(r)
            raw = t.get("category_scores")
            if isinstance(raw, str) and raw:
                try:
                    t["category_scores"] = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    t["category_scores"] = {}
            elif not raw:
                t["category_scores"] = {}
            traders.append(t)

        total = conn.execute("SELECT COUNT(*) FROM traders").fetchone()[0]
        return {"traders": traders, "total": total}
    finally:
        conn.close()


@router.get("/traders/{wallet_address}")
def get_trader(wallet_address: str):
    conn = _get_connection(_db_path)
    try:
        row = conn.execute(
            "SELECT * FROM traders WHERE wallet_address = ?", (wallet_address,)
        ).fetchone()
        if not row:
            return {"error": "Trader not found"}, 404
        t = dict(row)
        raw = t.get("category_scores")
        if isinstance(raw, str) and raw:
            try:
                t["category_scores"] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                t["category_scores"] = {}
        elif not raw:
            t["category_scores"] = {}
        return t
    finally:
        conn.close()


@router.get("/traders/{wallet_address}/changes")
def get_trader_changes(
    wallet_address: str,
    limit: int = Query(50, ge=1, le=200),
):
    conn = _get_connection(_db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM position_changes WHERE wallet_address = ? ORDER BY detected_at DESC LIMIT ?",
            (wallet_address, limit),
        ).fetchall()
        return {"changes": [dict(r) for r in rows]}
    finally:
        conn.close()
