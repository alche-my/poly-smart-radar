import json
import os
from typing import Optional

from fastapi import APIRouter, Query

import config
from db.models import _get_connection

router = APIRouter(tags=["signals"])

_db_path = config.DB_PATH


@router.get("/signals")
def list_signals(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tier: Optional[int] = Query(None, ge=1, le=3),
    status: Optional[str] = Query(None),
):
    conn = _get_connection(_db_path)
    try:
        query = "SELECT * FROM signals WHERE 1=1"
        params: list = []

        if tier is not None:
            query += " AND tier = ?"
            params.append(tier)
        if status is not None:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        signals = []
        for r in rows:
            s = dict(r)
            if isinstance(s.get("traders_involved"), str):
                s["traders_involved"] = json.loads(s["traders_involved"])
            signals.append(s)

        count_query = "SELECT COUNT(*) FROM signals WHERE 1=1"
        count_params: list = []
        if tier is not None:
            count_query += " AND tier = ?"
            count_params.append(tier)
        if status is not None:
            count_query += " AND status = ?"
            count_params.append(status)

        total = conn.execute(count_query, count_params).fetchone()[0]

        return {"signals": signals, "total": total}
    finally:
        conn.close()


@router.get("/signals/{signal_id}")
def get_signal(signal_id: int):
    conn = _get_connection(_db_path)
    try:
        row = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
        if not row:
            return {"error": "Signal not found"}, 404
        s = dict(row)
        if isinstance(s.get("traders_involved"), str):
            s["traders_involved"] = json.loads(s["traders_involved"])
        return s
    finally:
        conn.close()
