import os
from dotenv import load_dotenv

load_dotenv()

# --- API Base URLs ---
DATA_API_BASE_URL = "https://data-api.polymarket.com"
GAMMA_API_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_API_BASE_URL = "https://clob.polymarket.com"

# --- Intervals ---
SCAN_INTERVAL_MINUTES = 5
WATCHLIST_UPDATE_HOURS = 24
SNAPSHOT_RETENTION_DAYS = 30

# --- Scoring Thresholds ---
HIGH_THRESHOLD = 15.0
MEDIUM_THRESHOLD = 8.0
MIN_CLOSED_POSITIONS = 30
MIN_TRADERS_FOR_SIGNAL = 2

# --- Signal Window ---
SIGNAL_WINDOW_HOURS = 24

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

# --- Database ---
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "radar.db")
