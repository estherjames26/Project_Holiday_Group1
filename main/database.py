# SQLite database — caches API results and logs past searches.
# File lives at data/holiday_planner.db and is created on first run.

"""SQLite models, cache helpers, and search history logging.

The app stores API responses, scraped prices, Airbnb listings, discovered
destinations, and recommendation history in one local SQLite database.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    case,
    create_engine,
    inspect,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from settings import DATABASE_PATH


MOCK_VENUE_NAMES = {
    "The Beach Bar",
    "Harbour Tavern",
    "Sunset Lounge",
    "Corner Pub",
    "Harbour Kitchen",
    "Local Grill",
    "Sea View Cafe",
    "Backstreet Bistro",
    "Club 21",
    "The Loft",
    "Ocean Room",
}


def is_mock_places_payload(data: dict[str, Any]) -> bool:
    """Detect old demo Google Places payloads so live API data can replace them."""
    for key in ("bar", "restaurant", "night_club"):
        for place in data.get(key, []):
            name = place.get("name", "")
            if name in MOCK_VENUE_NAMES or name.startswith("Tropical Bar"):
                return True
    return False


def is_mock_weather_payload(data: dict[str, Any]) -> bool:
    """Detect old demo weather payloads so real OpenWeather data can replace them."""
    if data.get("country") == "XX":
        return True
    current = data.get("current", {})
    return "sys" not in current and "weather" in current

class Base(DeclarativeBase):
    """Base class for SQLAlchemy ORM models."""

    pass


class WeatherCache(Base):
    """Cached OpenWeatherMap JSON, one row per destination."""

    __tablename__ = "weather_cache"

    destination_id = Column(String(64), primary_key=True)
    payload = Column(Text, nullable=False)
    fetched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PlacesCache(Base):
    """Cached Google Places results. Key looks like 'phuket_5000'."""

    __tablename__ = "places_cache"

    cache_key = Column(String(128), primary_key=True)
    payload = Column(Text, nullable=False)
    fetched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CostCache(Base):
    """Scraped/estimated costs per destination."""

    __tablename__ = "cost_cache"

    destination_id = Column(String(64), primary_key=True)
    flight_estimate_usd = Column(Float)
    hotel_nightly_usd = Column(Float)
    airbnb_nightly_usd = Column(Float)
    meal_index = Column(Float)
    source = Column(String(256))
    source_details = Column(Text)
    fetched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class AirbnbListing(Base):
    """Cached Airbnb listing cards for one destination."""

    __tablename__ = "airbnb_listings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    destination_id = Column(String(64), nullable=False, index=True)
    name = Column(String(256))
    description = Column(String(512))
    bedrooms = Column(String(128))
    price_nightly = Column(Float)
    currency_symbol = Column(String(4), default="£")
    rating = Column(Float)
    image_url = Column(String(512))
    listing_url = Column(String(512))
    latitude = Column(Float)       # ← new
    longitude = Column(Float)      # ← new
    scraped_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
# ── new helpers ────────────────────────────────────────────────────────────────
def save_airbnb_listings(
    session: Session,
    destination_id: str,
    listings: list[dict],
    currency_symbol: str = "£",
) -> None:
    """Delete stale rows for this destination then insert fresh ones."""
    session.query(AirbnbListing).filter(
        AirbnbListing.destination_id == destination_id
    ).delete()
    for item in listings:
        session.add(
            AirbnbListing(
                destination_id=destination_id,
                name=item.get("name", "Unknown"),
                description=item.get("description"),
                bedrooms=item.get("bedrooms"),
                price_nightly=item.get("price_nightly"),
                currency_symbol=item.get("currency_symbol", currency_symbol),
                rating=item.get("rating"),
                image_url=item.get("image_url"),
                listing_url=item.get("listing_url"),
                latitude=item.get("latitude"),
                longitude=item.get("longitude"),
            )
        )
    session.commit()


def get_airbnb_listings(
    session: Session, destination_id: str, max_age_hours: int = 24
) -> list[dict]:
    """Return cached listings if they exist and are younger than max_age_hours."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    rows = (
        session.query(AirbnbListing)
        .filter(
            AirbnbListing.destination_id == destination_id,
            AirbnbListing.scraped_at >= cutoff,
        )
        .order_by(
            case((AirbnbListing.price_nightly.is_(None), 1), else_=0),
            AirbnbListing.price_nightly,
            AirbnbListing.id,
        )
        .all()
    )
    return [
        {
            "name": r.name,
            "description": r.description,
            "bedrooms": r.bedrooms,
            "price_nightly": r.price_nightly,
            "currency_symbol": r.currency_symbol,
            "rating": r.rating,
            "image_url": r.image_url,
            "listing_url": r.listing_url,
            "latitude": r.latitude,
            "longitude": r.longitude,
        }
        for r in rows
    ]

class DestinationsCache(Base):
    """Cached list of dynamically discovered destinations."""

    __tablename__ = "destinations_cache"

    cache_key = Column(String(32), primary_key=True, default="latest")
    payload = Column(Text, nullable=False)
    fetched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RecommendationLog(Base):
    """One row each time someone runs a search on the home page."""

    __tablename__ = "recommendation_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    origin_airport = Column(String(8))
    preferences_json = Column(Text)
    results_json = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


_engine = create_engine(f"sqlite:///{DATABASE_PATH}", echo=False)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create database tables, apply small migrations, and clear stale mock cache."""
    Base.metadata.create_all(_engine)
    _ensure_schema_migrations()
    purge_mock_api_cache()


def _ensure_schema_migrations() -> None:
    """Apply small backwards-compatible SQLite schema updates."""
    inspector = inspect(_engine)
    if inspector.has_table("cost_cache"):
        columns = {col["name"] for col in inspector.get_columns("cost_cache")}
        if "source_details" not in columns:
            # Older databases did not track per-source scrape details.
            with _engine.begin() as conn:
                conn.exec_driver_sql("ALTER TABLE cost_cache ADD COLUMN source_details TEXT")

    if inspector.has_table("airbnb_listings"):
        columns = {col["name"] for col in inspector.get_columns("airbnb_listings")}
        with _engine.begin() as conn:
            if "latitude" not in columns:
                # Coordinates were added later so Airbnb pins can appear on maps.
                conn.exec_driver_sql("ALTER TABLE airbnb_listings ADD COLUMN latitude FLOAT")
            if "longitude" not in columns:
                conn.exec_driver_sql("ALTER TABLE airbnb_listings ADD COLUMN longitude FLOAT")


def get_session() -> Session:
    """Open a SQLAlchemy session for callers to close when finished."""
    return SessionLocal()


def cache_weather(session: Session, destination_id: str, data: dict[str, Any]) -> None:
    """Insert or update cached weather JSON for one destination."""
    row = session.get(WeatherCache, destination_id)
    payload = json.dumps(data)
    if row:
        row.payload = payload
        row.fetched_at = datetime.now(timezone.utc)
    else:
        session.add(WeatherCache(destination_id=destination_id, payload=payload))
    session.commit()


def get_cached_weather(session: Session, destination_id: str) -> dict[str, Any] | None:
    """Return cached weather JSON for one destination, if present."""
    row = session.get(WeatherCache, destination_id)
    if row:
        return json.loads(row.payload)
    return None


def cache_places(session: Session, cache_key: str, data: dict[str, Any]) -> None:
    """Insert or update cached Google Places JSON for a destination/radius key."""
    row = session.get(PlacesCache, cache_key)
    payload = json.dumps(data)
    if row:
        row.payload = payload
        row.fetched_at = datetime.now(timezone.utc)
    else:
        session.add(PlacesCache(cache_key=cache_key, payload=payload))
    session.commit()


def get_cached_places(session: Session, cache_key: str) -> dict[str, Any] | None:
    """Return cached Google Places JSON for a destination/radius key."""
    row = session.get(PlacesCache, cache_key)
    if row:
        return json.loads(row.payload)
    return None


def cache_costs(
    session: Session,
    destination_id: str,
    flight: float,
    hotel: float,
    airbnb: float,
    meal_index: float,
    source: str,
    source_details: dict[str, str] | None = None,
) -> None:
    """Insert or update cached cost estimates and their source details."""
    row = session.get(CostCache, destination_id)
    source_details_json = json.dumps(source_details or {})
    if row:
        row.flight_estimate_usd = flight
        row.hotel_nightly_usd = hotel
        row.airbnb_nightly_usd = airbnb
        row.meal_index = meal_index
        row.source = source
        row.source_details = source_details_json
        row.fetched_at = datetime.now(timezone.utc)
    else:
        session.add(
            CostCache(
                destination_id=destination_id,
                flight_estimate_usd=flight,
                hotel_nightly_usd=hotel,
                airbnb_nightly_usd=airbnb,
                meal_index=meal_index,
                source=source,
                source_details=source_details_json,
            )
        )
    session.commit()


def get_cached_costs(session: Session, destination_id: str) -> CostCache | None:
    """Return the raw cached cost row so callers can inspect age/source metadata."""
    return session.get(CostCache, destination_id)


def cache_destinations(session: Session, data: dict[str, Any]) -> None:
    """Store the latest dynamically discovered destination list."""
    row = session.get(DestinationsCache, "latest")
    payload = json.dumps(data)
    if row:
        row.payload = payload
        row.fetched_at = datetime.now(timezone.utc)
    else:
        session.add(DestinationsCache(cache_key="latest", payload=payload))
    session.commit()


def get_cached_destinations(session: Session) -> dict[str, Any] | None:
    """Return the cached discovered destination list, if present."""
    row = session.get(DestinationsCache, "latest")
    if row:
        return json.loads(row.payload)
    return None


def purge_mock_api_cache() -> None:
    """Drop cached fake data from before API keys were added."""
    from settings import GOOGLE_MAPS_API_KEY, OPENWEATHER_API_KEY

    if not OPENWEATHER_API_KEY and not GOOGLE_MAPS_API_KEY:
        return

    session = get_session()
    try:
        if OPENWEATHER_API_KEY:
            # Once a real key exists, demo weather should not shadow live requests.
            for row in session.query(WeatherCache).all():
                try:
                    payload = json.loads(row.payload)
                    data = payload.get("data", payload)
                    if is_mock_weather_payload(data):
                        session.delete(row)
                except (json.JSONDecodeError, TypeError):
                    session.delete(row)

        if GOOGLE_MAPS_API_KEY:
            # Clear old demo venues so Google Places can repopulate the cache.
            for row in session.query(PlacesCache).all():
                try:
                    payload = json.loads(row.payload)
                    data = payload.get("data", payload)
                    if is_mock_places_payload(data):
                        session.delete(row)
                except (json.JSONDecodeError, TypeError):
                    session.delete(row)

        session.commit()
    finally:
        session.close()


def log_recommendation(
    session: Session,
    origin: str,
    preferences: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    """Save a completed recommendation run for the History page."""
    session.add(
        RecommendationLog(
            origin_airport=origin,
            preferences_json=json.dumps(preferences),
            results_json=json.dumps(results),
        )
    )
    session.commit()


def get_recommendation_history(session: Session, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent recommendation runs in a compact display format."""
    rows = (
        session.query(RecommendationLog)
        .order_by(RecommendationLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "origin_airport": r.origin_airport,
            "top_destination": json.loads(r.results_json)[0]["name"] if r.results_json else "—",
            "top_score": json.loads(r.results_json)[0]["score"] if r.results_json else 0,
            "result_count": len(json.loads(r.results_json)) if r.results_json else 0,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]


def get_cache_stats(session: Session) -> dict[str, int]:
    """Count cache and history rows for diagnostics/admin views."""
    return {
        "weather_entries": session.query(WeatherCache).count(),
        "places_entries": session.query(PlacesCache).count(),
        "cost_entries": session.query(CostCache).count(),
        "recommendation_runs": session.query(RecommendationLog).count(),
    }
