# API keys and app settings — loaded from .env in this folder.
# Other files import from here so keys aren't scattered everywhere.
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")

# Also load a shared env file one level up (team often keeps keys outside main/).
_parent_env = ROOT_DIR.parent / "env"
if _parent_env.is_file():
    load_dotenv(_parent_env, override=False)

_PLACEHOLDER_HINTS = ("your_", "example", "replace", "changeme", "paste", "insert")


def usable_api_key(raw: str | None) -> str:
    """Treat placeholder text like 'your_api_key' as missing."""
    key = (raw or "").strip()
    if not key:
        return ""
    lowered = key.lower()
    if any(hint in lowered for hint in _PLACEHOLDER_HINTS):
        return ""
    return key


OPENWEATHER_API_KEY = usable_api_key(os.getenv("OPENWEATHER_API_KEY"))
GOOGLE_MAPS_API_KEY = usable_api_key(os.getenv("GOOGLE_MAPS_API_KEY"))
OPENAI_API_KEY = usable_api_key(os.getenv("OPENAI_API_KEY"))
ORIGIN_AIRPORT = os.getenv("ORIGIN_AIRPORT", "LHR")
GBP_TO_USD = float(os.getenv("GBP_TO_USD", "1.27"))

_db_url = os.getenv("DATABASE_URL", "sqlite:///data/holiday_planner.db")
if _db_url.startswith("sqlite:///"):
    _rel = _db_url.replace("sqlite:///", "")
    DATABASE_PATH = ROOT_DIR / _rel if not os.path.isabs(_rel) else Path(_rel)
else:
    DATABASE_PATH = ROOT_DIR / "data" / "holiday_planner.db"

DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# How long we cache API responses (seconds)
WEATHER_CACHE_TTL = 3600        # 1 hour
PLACES_CACHE_TTL = 86400        # 24 hours
COST_CACHE_TTL = 604800         # 7 days
DESTINATIONS_CACHE_TTL = 86400  # 24 hours