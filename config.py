import os
from dotenv import load_dotenv

load_dotenv()

# --- API Base URLs ---
DATA_API_BASE_URL = "https://data-api.polymarket.com"
GAMMA_API_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_API_BASE_URL = "https://clob.polymarket.com"

# --- Intervals ---
SCAN_INTERVAL_MINUTES = 5
WATCHLIST_UPDATE_HOURS = 168  # 7 days — keep current traders stable for a week
SNAPSHOT_RETENTION_DAYS = 30

# --- Scoring Thresholds ---
HIGH_THRESHOLD = 15.0
MEDIUM_THRESHOLD = 8.0
MIN_CLOSED_POSITIONS = 20
MIN_TRADERS_FOR_SIGNAL = 2

# --- Signal Window ---
SIGNAL_WINDOW_HOURS = 24

# --- Strategy Filters (validated via train/test split) ---
STRATEGY_MIN_PRICE = 0.10
STRATEGY_MAX_PRICE = 0.85
STRATEGY_BAD_CATEGORIES = {"CRYPTO", "CULTURE", "FINANCE"}
STRATEGY_MAX_TIER = 2  # Tier 1 + Tier 2 only

# --- Freshness Tiers (hours -> multiplier) ---
FRESHNESS_TIERS = {
    2: 2.0,
    6: 1.5,
    24: 1.0,
    48: 0.5,
}

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Trading Bot ---
BOT_ENABLED = os.getenv("BOT_ENABLED", "false").lower() == "true"
BOT_PRIVATE_KEY = os.getenv("BOT_PRIVATE_KEY", "")
BOT_WALLET_ADDRESS = os.getenv("BOT_WALLET_ADDRESS", "")
BOT_TELEGRAM_CHAT_ID = os.getenv("BOT_TELEGRAM_CHAT_ID", "")
BOT_INITIAL_BUDGET = float(os.getenv("BOT_INITIAL_BUDGET", "10.0"))
BOT_BET_SIZE = float(os.getenv("BOT_BET_SIZE", "0.50"))
BOT_MAX_OPEN_POSITIONS = int(os.getenv("BOT_MAX_OPEN_POSITIONS", "10"))
BOT_MAX_DAILY_SPEND = float(os.getenv("BOT_MAX_DAILY_SPEND", "2.50"))
BOT_MIN_BALANCE = float(os.getenv("BOT_MIN_BALANCE", "2.00"))
BOT_CIRCUIT_BREAKER_PCT = float(os.getenv("BOT_CIRCUIT_BREAKER_PCT", "0.30"))
BOT_MAX_SLIPPAGE = float(os.getenv("BOT_MAX_SLIPPAGE", "0.15"))

# --- Database ---
DB_PATH = os.path.join(os.path.dirname(__file__), "radar.db")
