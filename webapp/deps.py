"""
Dependencies for FastAPI endpoints.
"""

import config


def get_db_path() -> str:
    """Get the database path from config."""
    return config.DB_PATH
