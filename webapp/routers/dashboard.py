import json

from fastapi import APIRouter

import config
from db.models import _get_connection

router = APIRouter(tags=["dashboard"])

_db_path = config.DB_PATH


@router.get("/dashboard")
def dashboard_summary():
    conn = _get_connection(_db_path)
    try:
        traders_count = conn.execute("SELECT COUNT(*) FROM traders").fetchone()[0]

        active_signals = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE status = 'ACTIVE'"
        ).fetchone()[0]

        total_signals = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]

        recent_changes = conn.execute(
            "SELECT COUNT(*) FROM position_changes WHERE detected_at >= datetime('now', '-24 hours')"
        ).fetchone()[0]

        top_signals = conn.execute(
            "SELECT * FROM signals WHERE status = 'ACTIVE' ORDER BY signal_score DESC LIMIT 5"
        ).fetchall()
        top_list = []
        for r in top_signals:
            s = dict(r)
            if isinstance(s.get("traders_involved"), str):
                s["traders_involved"] = json.loads(s["traders_involved"])
            top_list.append(s)

        return {
            "traders_count": traders_count,
            "active_signals": active_signals,
            "total_signals": total_signals,
            "recent_changes_24h": recent_changes,
            "top_signals": top_list,
        }
    finally:
        conn.close()
