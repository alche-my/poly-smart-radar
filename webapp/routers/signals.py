import json
import os
from typing import Optional

from fastapi import APIRouter, Query

import config
from db.models import _get_connection

router = APIRouter(tags=["signals"])

_db_path = config.DB_PATH


def _enrich_signal(s: dict, conn) -> dict:
    """Parse traders_involved JSON; if empty, rebuild from position_changes + traders."""
    raw = s.get("traders_involved", "[]")
    if isinstance(raw, str):
        try:
            traders = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            traders = []
    else:
        traders = raw

    # Enrich existing traders with fresh data from traders table
    if traders:
        wallets = [t.get("wallet_address") for t in traders if t.get("wallet_address")]
        if wallets:
            placeholders = ",".join("?" for _ in wallets)
            rows = conn.execute(
                f"SELECT * FROM traders WHERE wallet_address IN ({placeholders})",
                wallets,
            ).fetchall()
            trader_map = {r["wallet_address"]: dict(r) for r in rows}

            for t in traders:
                w = t.get("wallet_address")
                if w and w in trader_map:
                    db_t = trader_map[w]
                    t.setdefault("roi", db_t.get("roi", 0))
                    t.setdefault("total_closed", db_t.get("total_closed", 0))
                    cat_raw = db_t.get("category_scores", "{}")
                    if isinstance(cat_raw, str):
                        try:
                            cat = json.loads(cat_raw)
                        except (json.JSONDecodeError, TypeError):
                            cat = {}
                    else:
                        cat = cat_raw
                    t.setdefault("category_scores", cat)
                    if not t.get("username") or t["username"] == w[:8]:
                        t["username"] = db_t.get("username") or w[:10]
    else:
        # Rebuild traders_involved from position_changes + traders tables
        cid = s.get("condition_id")
        if cid:
            rows = conn.execute(
                """
                SELECT pc.*, t.username, t.trader_score, t.win_rate, t.roi,
                       t.total_closed, t.category_scores, t.avg_position_size
                FROM position_changes pc
                JOIN traders t ON pc.wallet_address = t.wallet_address
                WHERE pc.condition_id = ?
                  AND pc.change_type IN ('OPEN', 'INCREASE')
                ORDER BY pc.detected_at DESC
                """,
                (cid,),
            ).fetchall()

            seen = set()
            for r in rows:
                r = dict(r)
                w = r["wallet_address"]
                if w in seen:
                    continue
                seen.add(w)

                cat_raw = r.get("category_scores", "{}")
                if isinstance(cat_raw, str):
                    try:
                        cat = json.loads(cat_raw)
                    except (json.JSONDecodeError, TypeError):
                        cat = {}
                else:
                    cat = cat_raw

                traders.append({
                    "wallet_address": w,
                    "username": r.get("username") or w[:10],
                    "trader_score": r.get("trader_score", 0),
                    "win_rate": r.get("win_rate", 0),
                    "roi": r.get("roi", 0),
                    "total_closed": r.get("total_closed", 0),
                    "category_scores": cat,
                    "conviction": r.get("conviction_score", 1.0),
                    "change_type": r.get("change_type", "OPEN"),
                    "size": r.get("new_size", 0),
                    "detected_at": r.get("detected_at", ""),
                })

    s["traders_involved"] = traders

    # Look up event_slug from position_changes so Polymarket links work
    if not s.get("event_slug"):
        cid = s.get("condition_id")
        if cid:
            evt_row = conn.execute(
                "SELECT event_slug FROM position_changes WHERE condition_id = ? AND event_slug != '' LIMIT 1",
                (cid,),
            ).fetchone()
            if evt_row and evt_row["event_slug"]:
                s["event_slug"] = evt_row["event_slug"]

    return s


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
        signals = [_enrich_signal(dict(r), conn) for r in rows]

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
        return _enrich_signal(dict(row), conn)
    finally:
        conn.close()
