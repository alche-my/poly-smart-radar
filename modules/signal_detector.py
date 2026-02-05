import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta

import config
from db.models import (
    get_recent_changes,
    get_traders,
    get_trader,
    get_active_signal,
    insert_signal,
    update_signal,
)
from modules.watchlist_builder import classify_category, classify_domains

logger = logging.getLogger(__name__)


def calc_freshness(detected_at: str) -> float:
    try:
        dt = datetime.fromisoformat(detected_at)
    except (ValueError, TypeError):
        return 0.5
    hours_ago = (datetime.utcnow() - dt).total_seconds() / 3600
    for max_hours, multiplier in sorted(config.FRESHNESS_TIERS.items()):
        if hours_ago < max_hours:
            return multiplier
    return 0.0


def calc_category_match(trader: dict, market_category: str | None) -> float:
    if not market_category:
        return 1.0
    cat_scores_raw = trader.get("category_scores", "{}")
    if isinstance(cat_scores_raw, str):
        try:
            cat_scores = json.loads(cat_scores_raw)
        except (json.JSONDecodeError, TypeError):
            cat_scores = {}
    else:
        cat_scores = cat_scores_raw
    if market_category in cat_scores and cat_scores[market_category] > 0:
        return 1.5
    return 1.0


def calc_signal_score(traders_data: list[dict]) -> float:
    total = 0.0
    for td in traders_data:
        score = (
            td["trader_score"]
            * td["conviction"]
            * td["category_match"]
            * td["freshness"]
        )
        total += score
    return round(total, 4)


class SignalDetector:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def detect_signals(self) -> list[dict]:
        since = (datetime.utcnow() - timedelta(hours=config.SIGNAL_WINDOW_HOURS)).isoformat()
        changes = get_recent_changes(self.db_path, since)
        if not changes:
            return []

        # Group by condition_id
        groups: dict[str, list[dict]] = defaultdict(list)
        for c in changes:
            groups[c["condition_id"]].append(c)

        # Load all traders for quick lookup
        all_traders = {t["wallet_address"]: t for t in get_traders(self.db_path)}
        top10_wallets = set(
            list(all_traders.keys())[:10]
        )

        new_signals = []

        for condition_id, group_changes in groups.items():
            signals = self._process_group(
                condition_id, group_changes, all_traders, top10_wallets, since,
            )
            new_signals.extend(signals)

        # Update lifecycle of existing active signals
        self._update_active_signals(changes, all_traders, since)

        logger.info("Signal detection: %d new/updated signals", len(new_signals))
        return new_signals

    def _process_group(
        self,
        condition_id: str,
        changes: list[dict],
        all_traders: dict,
        top10_wallets: set,
        since: str,
    ) -> list[dict]:
        # Group by wallet to get unique traders
        by_wallet: dict[str, list[dict]] = defaultdict(list)
        for c in changes:
            by_wallet[c["wallet_address"]].append(c)

        # Determine direction consensus
        direction_info = self._check_direction(changes)
        if not direction_info:
            return []

        direction, bullish_wallets = direction_info
        unique_wallets = list(bullish_wallets)

        # Build trader data for score calculation
        market_title = changes[0].get("title", "")
        market_category = classify_category(market_title)

        traders_data = []
        for wallet in unique_wallets:
            trader = all_traders.get(wallet)
            if not trader:
                continue
            wallet_changes = by_wallet[wallet]
            best_change = max(wallet_changes, key=lambda c: c.get("conviction_score", 0))

            # Parse domain_tags and recent_bets from DB (stored as JSON strings)
            raw_tags = trader.get("domain_tags", "[]")
            domain_tags = json.loads(raw_tags) if isinstance(raw_tags, str) else (raw_tags or [])
            raw_bets = trader.get("recent_bets", "[]")
            recent_bets = json.loads(raw_bets) if isinstance(raw_bets, str) else (raw_bets or [])

            traders_data.append({
                "wallet_address": wallet,
                "username": trader.get("username", wallet[:8]),
                "trader_score": trader.get("trader_score", 0),
                "win_rate": trader.get("win_rate", 0),
                "pnl": trader.get("pnl", 0),
                "trader_type": trader.get("trader_type", "UNKNOWN"),
                "domain_tags": domain_tags,
                "recent_bets": recent_bets,
                "conviction": best_change.get("conviction_score", 1.0),
                "change_type": best_change.get("change_type", "OPEN"),
                "size": best_change.get("new_size", 0),
                "category_match": calc_category_match(trader, market_category),
                "freshness": calc_freshness(best_change.get("detected_at", "")),
                "detected_at": best_change.get("detected_at", ""),
            })

        if not traders_data:
            return []

        signal_score = calc_signal_score(traders_data)
        num_traders = len(traders_data)

        # Determine tier
        tier = self._determine_tier(
            num_traders, signal_score, traders_data, top10_wallets,
        )
        if tier is None:
            return []

        # Dedup: check existing signal
        existing = get_active_signal(self.db_path, condition_id, direction, since)
        now = datetime.utcnow().isoformat()

        if existing:
            new_peak = max(existing.get("peak_score", 0), signal_score)
            update_signal(self.db_path, existing["id"], {
                "signal_score": signal_score,
                "peak_score": new_peak,
                "tier": tier,
                "traders_involved": traders_data,
                "updated_at": now,
                "sent": False,
            })
            logger.info("Updated signal %d for %s (score %.1f)", existing["id"], condition_id[:8], signal_score)
            return [{"id": existing["id"], "updated": True, "condition_id": condition_id}]
        else:
            signal = {
                "condition_id": condition_id,
                "market_title": market_title,
                "market_slug": changes[0].get("slug", ""),
                "direction": direction,
                "signal_score": signal_score,
                "peak_score": signal_score,
                "tier": tier,
                "status": "ACTIVE",
                "traders_involved": traders_data,
                "current_price": changes[0].get("price_at_change", 0),
                "created_at": now,
                "updated_at": now,
                "sent": False,
            }
            sid = insert_signal(self.db_path, signal)
            logger.info("New signal %d for %s: tier %d, score %.1f", sid, condition_id[:8], tier, signal_score)
            return [{"id": sid, "new": True, "condition_id": condition_id}]

    def _check_direction(self, changes: list[dict]) -> tuple[str, set[str]] | None:
        bullish = set()   # OPEN/INCREASE
        bearish = set()   # DECREASE/CLOSE

        for c in changes:
            wallet = c["wallet_address"]
            ct = c["change_type"]
            if ct in ("OPEN", "INCREASE"):
                bullish.add(wallet)
            elif ct in ("DECREASE", "CLOSE"):
                bearish.add(wallet)

        # Check for consensus on outcome
        outcomes = set(c.get("outcome", "") for c in changes if c["change_type"] in ("OPEN", "INCREASE"))
        if len(outcomes) > 1:
            return None  # Mixed directions

        if bullish and not bearish:
            outcome = outcomes.pop() if outcomes else "YES"
            return (outcome, bullish)

        # If there's disagreement, skip
        if bullish & bearish:
            return None

        return None

    def _determine_tier(
        self,
        num_traders: int,
        signal_score: float,
        traders_data: list[dict],
        top10_wallets: set[str],
    ) -> int | None:
        """Determine signal tier. Only HUMAN traders count for multi-trader requirement.

        Tier 1: 2+ HUMAN traders with high score (strong consensus)
        Tier 2: 1+ HUMAN trader(s) with medium score (notable signal)

        ALGO/MM-only signals are not created (return None).
        """
        # Count by trader type
        human_traders = [t for t in traders_data if t.get("trader_type") == "HUMAN"]
        num_humans = len(human_traders)

        # No HUMAN traders = no signal worth alerting
        if num_humans == 0:
            return None

        # Tier 1: 2+ HUMAN traders with strong consensus
        if num_humans >= 2 and signal_score > config.HIGH_THRESHOLD:
            return 1

        # Tier 2: At least 1 HUMAN with decent score
        if num_humans >= 1 and signal_score > config.MEDIUM_THRESHOLD:
            return 2

        return None

    def _update_active_signals(
        self,
        recent_changes: list[dict],
        all_traders: dict,
        since: str,
    ) -> None:
        from db.models import get_unsent_signals

        # Find exits (DECREASE/CLOSE) in recent changes
        exits_by_condition: dict[str, set[str]] = defaultdict(set)
        for c in recent_changes:
            if c["change_type"] in ("DECREASE", "CLOSE"):
                exits_by_condition[c["condition_id"]].add(c["wallet_address"])

        if not exits_by_condition:
            return

        # Check all active signals for weakening/closing
        # We need to query active signals — use a simple approach
        import sqlite3
        from db.models import _get_connection
        conn = _get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM signals WHERE status IN ('ACTIVE', 'WEAKENING')"
            ).fetchall()
        finally:
            conn.close()

        now = datetime.utcnow().isoformat()

        for row in rows:
            signal = dict(row)
            cid = signal["condition_id"]
            if cid not in exits_by_condition:
                continue

            exiting_wallets = exits_by_condition[cid]
            involved_raw = signal.get("traders_involved", "[]")
            if isinstance(involved_raw, str):
                try:
                    involved = json.loads(involved_raw)
                except (json.JSONDecodeError, TypeError):
                    involved = []
            else:
                involved = involved_raw

            involved_wallets = {t.get("wallet_address", "") for t in involved}
            remaining = involved_wallets - exiting_wallets

            if not remaining:
                new_status = "CLOSED"
            elif len(remaining) < len(involved_wallets):
                new_status = "WEAKENING"
            else:
                continue

            if new_status != signal.get("status"):
                update_signal(self.db_path, signal["id"], {
                    "status": new_status,
                    "updated_at": now,
                    "sent": False,
                })
                logger.info(
                    "Signal %d for %s: %s -> %s (%d/%d traders remaining)",
                    signal["id"], cid[:8], signal["status"], new_status,
                    len(remaining), len(involved_wallets),
                )
