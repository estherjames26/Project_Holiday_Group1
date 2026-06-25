# SQLite setup — stores API cache and a log of past searches.
#
# The database file lives at data/holiday_planner.db (created on first run).
# We don't import data from an external DB; tables fill up as people use the app.

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
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import DATABASE_PATH


class Base(DeclarativeBase):
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
    Base.metadata.create_all(_engine)


def get_session() -> Session:
    return SessionLocal()


def cache_weather(session: Session, destination_id: str, data: dict[str, Any]) -> None:
    row = session.get(WeatherCache, destination_id)
    payload = json.dumps(data)
    if row:
        row.payload = payload
        row.fetched_at = datetime.now(timezone.utc)
    else:
        session.add(WeatherCache(destination_id=destination_id, payload=payload))
    session.commit()


def get_cached_weather(session: Session, destination_id: str) -> dict[str, Any] | None:
    row = session.get(WeatherCache, destination_id)
    if row:
        return json.loads(row.payload)
    return None


def cache_places(session: Session, cache_key: str, data: dict[str, Any]) -> None:
    row = session.get(PlacesCache, cache_key)
    payload = json.dumps(data)
    if row:
        row.payload = payload
        row.fetched_at = datetime.now(timezone.utc)
    else:
        session.add(PlacesCache(cache_key=cache_key, payload=payload))
    session.commit()


def get_cached_places(session: Session, cache_key: str) -> dict[str, Any] | None:
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
) -> None:
    row = session.get(CostCache, destination_id)
    if row:
        row.flight_estimate_usd = flight
        row.hotel_nightly_usd = hotel
        row.airbnb_nightly_usd = airbnb
        row.meal_index = meal_index
        row.source = source
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
            )
        )
    session.commit()


def get_cached_costs(session: Session, destination_id: str) -> CostCache | None:
    return session.get(CostCache, destination_id)


def log_recommendation(
    session: Session,
    origin: str,
    preferences: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    session.add(
        RecommendationLog(
            origin_airport=origin,
            preferences_json=json.dumps(preferences),
            results_json=json.dumps(results),
        )
    )
    session.commit()


def get_recommendation_history(session: Session, limit: int = 20) -> list[dict[str, Any]]:
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
    return {
        "weather_entries": session.query(WeatherCache).count(),
        "places_entries": session.query(PlacesCache).count(),
        "cost_entries": session.query(CostCache).count(),
        "recommendation_runs": session.query(RecommendationLog).count(),
    }
