"""Risk management — all safety checks before placing a trade.

Every check returns (allowed: bool, reason: str) for full debuggability.
The first failing check short-circuits — trade is blocked with reason logged.
"""

import logging
from datetime import datetime, date

import config
from db.models import _get_connection

logger = logging.getLogger(__name__)


class RiskManager:
    """Enforces all risk limits before allowing a trade."""

    def __init__(self, db_path: str = config.DB_PATH):
        self.db_path = db_path

    def check_all(
        self,
        signal: dict,
        current_balance: float,
        current_price: float | None = None,
    ) -> tuple[bool, str]:
        """Run all risk checks. Returns (allowed, reason).

        If allowed is False, reason explains which check failed.
        If allowed is True, reason is "OK".
        """
        checks = [
            self._check_bot_enabled(),
            self._check_min_balance(current_balance),
            self._check_circuit_breaker(current_balance),
            self._check_max_open_positions(),
            self._check_daily_spend(),
            self._check_duplicate_market(signal["condition_id"]),
            self._check_price_slippage(signal, current_price),
        ]
        for allowed, reason in checks:
            if not allowed:
                logger.warning("Risk check BLOCKED: %s", reason)
                return False, reason

        return True, "OK"

    def _check_bot_enabled(self) -> tuple[bool, str]:
        """Check if circuit breaker is not active."""
        conn = _get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT value FROM bot_state WHERE key = 'circuit_breaker_active'"
            ).fetchone()
            if row and row["value"] == "1":
                return False, "Circuit breaker is active — trading halted"
            return True, "OK"
        finally:
            conn.close()

    def _check_min_balance(self, balance: float) -> tuple[bool, str]:
        """Check balance is above minimum reserve."""
        if balance < config.BOT_MIN_BALANCE:
            return False, (
                f"Balance ${balance:.2f} below minimum ${config.BOT_MIN_BALANCE:.2f}"
            )
        return True, "OK"

    def _check_circuit_breaker(self, current_balance: float) -> tuple[bool, str]:
        """30% drawdown from peak balance triggers circuit breaker."""
        conn = _get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT value FROM bot_state WHERE key = 'peak_balance'"
            ).fetchone()
            peak = float(row["value"]) if row else config.BOT_INITIAL_BUDGET
            threshold = peak * (1 - config.BOT_CIRCUIT_BREAKER_PCT)
            if current_balance < threshold:
                self._set_state("circuit_breaker_active", "1")
                return False, (
                    f"Circuit breaker: balance ${current_balance:.2f} < "
                    f"threshold ${threshold:.2f} (peak ${peak:.2f}, "
                    f"{config.BOT_CIRCUIT_BREAKER_PCT * 100:.0f}% drawdown)"
                )
            # Update peak if current is higher
            if current_balance > peak:
                self._set_state("peak_balance", str(current_balance))
            return True, "OK"
        finally:
            conn.close()

    def _check_max_open_positions(self) -> tuple[bool, str]:
        """Check we haven't reached the position limit."""
        conn = _get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM bot_trades WHERE status = 'OPEN'"
            ).fetchone()
            count = row["cnt"] if row else 0
            if count >= config.BOT_MAX_OPEN_POSITIONS:
                return False, (
                    f"Max open positions reached: {count}/{config.BOT_MAX_OPEN_POSITIONS}"
                )
            return True, "OK"
        finally:
            conn.close()

    def _check_daily_spend(self) -> tuple[bool, str]:
        """Check we haven't exceeded the daily spending limit."""
        today = date.today().isoformat()
        conn = _get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) as spent FROM bot_trades "
                "WHERE DATE(created_at) = ? AND status != 'FAILED'",
                (today,),
            ).fetchone()
            spent = row["spent"] if row else 0
            if spent + config.BOT_BET_SIZE > config.BOT_MAX_DAILY_SPEND:
                return False, (
                    f"Daily spend limit: ${spent:.2f} spent today, "
                    f"limit ${config.BOT_MAX_DAILY_SPEND:.2f}"
                )
            return True, "OK"
        finally:
            conn.close()

    def _check_duplicate_market(self, condition_id: str) -> tuple[bool, str]:
        """Check we don't already have an open position on this market."""
        conn = _get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM bot_trades "
                "WHERE condition_id = ? AND status = 'OPEN'",
                (condition_id,),
            ).fetchone()
            if row and row["cnt"] > 0:
                return False, (
                    f"Duplicate: already have open position on {condition_id[:16]}..."
                )
            return True, "OK"
        finally:
            conn.close()

    def _check_price_slippage(
        self,
        signal: dict,
        current_price: float | None,
    ) -> tuple[bool, str]:
        """Check that the current price hasn't drifted too far from the signal price."""
        if current_price is None:
            return True, "OK"

        signal_price = signal.get("current_price", 0) or signal.get(
            "market_price_at_signal", 0
        )
        if signal_price <= 0:
            return True, "OK"

        slippage = abs(current_price - signal_price) / signal_price
        if slippage > config.BOT_MAX_SLIPPAGE:
            return False, (
                f"Price slippage {slippage * 100:.1f}% > "
                f"max {config.BOT_MAX_SLIPPAGE * 100:.0f}%: "
                f"signal=${signal_price:.3f}, current=${current_price:.3f}"
            )
        return True, "OK"

    def _set_state(self, key: str, value: str) -> None:
        """Upsert a value into bot_state."""
        conn = _get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO bot_state (key, value, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (key, value, datetime.utcnow().isoformat()),
            )
            conn.commit()
            logger.debug("bot_state: %s = %s", key, value)
        except Exception as e:
            logger.error(
                "Failed to set bot_state %s=%s: %s", key, value, e,
                exc_info=True,
            )
            raise
        finally:
            conn.close()

    def reset_circuit_breaker(self) -> None:
        """Manually reset the circuit breaker. Use with caution."""
        self._set_state("circuit_breaker_active", "0")
        logger.info("Circuit breaker reset manually")
