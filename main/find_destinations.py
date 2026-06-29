# Finds tropical cities via Google Places text search.
# Filters out UK/Europe and groups results by city (not individual bars).

"""Discover tropical destination candidates with Google Places.

The service searches broad tropical regions, groups nearby place hits into
city-level destinations, caches the result, and falls back to seed destinations
when Google is unavailable.
"""

from __future__ import annotations

import re
from typing import Any

import googlemaps
import requests

from settings import DESTINATIONS_CACHE_TTL, GOOGLE_MAPS_API_KEY, usable_api_key
from places import Destination, SEED_DESTINATIONS
from database import cache_destinations, get_cached_destinations, get_session
from api_geocoding import GoogleGeocodingService


# Search from tropical regions so results are not biased toward the UK origin airport.
TROPICAL_SEARCH_REGIONS: list[tuple[float, float, int, str]] = [
    (18.0, -66.0, 2_000_000, "tropical beach city nightlife"),
    (10.0, -75.0, 1_500_000, "coastal resort town bars restaurants"),
    (7.0, 98.0, 1_500_000, "island beach destination thailand"),
    (18.0, -87.0, 1_500_000, "tropical beach town mexico"),
    (-8.0, 115.0, 1_500_000, "bali beach resort nightlife"),
    (-22.0, -43.0, 1_500_000, "rio beach city nightlife"),
    (21.0, -157.0, 1_500_000, "hawaii beach island nightlife"),
    (-6.0, 39.0, 1_500_000, "zanzibar tropical beach island"),
    (6.0, 100.0, 1_500_000, "langkawi island beach resort"),
    (-18.0, 178.0, 2_000_000, "fiji tropical island beach"),
    (25.0, -77.0, 1_500_000, "caribbean beach island nightlife"),
    (-28.0, 153.4, 1_500_000, "gold coast beach nightlife australia"),
]

EXCLUDED_COUNTRIES = {
    "United Kingdom",
    "England",
    "Scotland",
    "Wales",
    "Northern Ireland",
    "Ireland",
    "United States of America",  # keep Miami/Honolulu via lat filter + city types
}
# US cities we want are handled by latitude; exclude only if clearly non-tropical US.
NON_TROPICAL_US_REGIONS = {"Alaska", "Montana", "North Dakota", "Maine", "Vermont"}

MIN_TROPICAL_LAT = -35.0
MAX_TROPICAL_LAT = 35.0

ADVENTURE_BY_TYPES: dict[str, tuple[str, ...]] = {
    "natural_feature": ("hiking", "nature", "beach"),
    "tourist_attraction": ("culture", "sightseeing"),
    "locality": ("culture", "food", "nightlife"),
    "sublocality": ("food", "nightlife", "culture"),
}


def _slug(name: str) -> str:
    """Create a stable lowercase id from a destination name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "destination"


def _is_tropical_location(lat: float, country: str, region: str = "") -> bool:
    """Filter out clearly non-tropical or intentionally excluded locations."""
    if country in EXCLUDED_COUNTRIES:
        return False
    if region in NON_TROPICAL_US_REGIONS:
        return False
    if not (MIN_TROPICAL_LAT <= lat <= MAX_TROPICAL_LAT):
        return False
    return True


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Estimate distance between two coordinates in kilometres."""
    from math import asin, cos, radians, sin, sqrt

    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(a))


def _dedupe_nearby(destinations: list[Destination], max_km: float = 40.0) -> list[Destination]:
    """Merge duplicate hits for the same city (e.g. Badung / Kabupaten Badung)."""
    kept: list[Destination] = []
    for dest in destinations:
        merged = False
        for i, existing in enumerate(kept):
            if dest.country != existing.country:
                continue
            if _haversine_km(dest.latitude, dest.longitude, existing.latitude, existing.longitude) > max_km:
                continue
            winner = dest if dest.nightlife_score >= existing.nightlife_score else existing
            loser = existing if winner is dest else dest
            kept[i] = Destination(
                id=winner.id,
                name=winner.name if len(winner.name) <= len(loser.name) + 5 else existing.name,
                country=winner.country,
                latitude=(winner.latitude + loser.latitude) / 2,
                longitude=(winner.longitude + loser.longitude) / 2,
                airport_code=winner.airport_code or loser.airport_code,
                description=winner.description,
                adventure_tags=winner.adventure_tags,
                nightlife_score=max(winner.nightlife_score, loser.nightlife_score),
            )
            merged = True
            break
        if not merged:
            kept.append(dest)
    return kept


class DestinationDiscoveryService:
    """Find and cache candidate destinations for the ranking engine."""

    def __init__(self, api_key: str | None = None) -> None:
        """Create Google Places and Geocoding clients when a usable key exists."""
        self.api_key = usable_api_key(api_key or GOOGLE_MAPS_API_KEY)
        self._client: googlemaps.Client | None = None
        self._geocoder = GoogleGeocodingService(self.api_key or None)
        if self.api_key:
            try:
                self._client = googlemaps.Client(key=self.api_key)
            except ValueError:
                self.api_key = ""
                self._client = None

    def discover(self, limit: int = 12) -> list[Destination]:
        """Return discovered destinations, using cache and seed fallbacks as needed."""
        session = get_session()
        try:
            cached = get_cached_destinations(session)
            if cached and self._is_fresh(cached.get("fetched_at")):
                destinations = self._deserialize(cached["destinations"])
                if destinations:
                    return destinations[:limit]

            if not self.api_key:
                # Demo mode keeps the app usable without Google credentials.
                return list(SEED_DESTINATIONS)[:limit]

            raw_places = self._search_tropical_destinations()
            destinations = self._build_destinations(raw_places)
            destinations = self._ensure_minimum_pool(destinations)
            if not destinations:
                destinations = list(SEED_DESTINATIONS)

            # Cache the city-level pool rather than raw Google place responses.
            cache_destinations(session, {
                "fetched_at": cached_fetched_iso(),
                "destinations": self._serialize(destinations),
            })
            return destinations[:limit]
        finally:
            session.close()

    def _search_tropical_destinations(self) -> list[dict[str, Any]]:
        """Run text searches across predefined tropical regions and dedupe place ids."""
        seen_ids: set[str] = set()
        results: list[dict[str, Any]] = []

        for lat, lon, radius, query in TROPICAL_SEARCH_REGIONS:
            batch = self._text_search(query, lat, lon, radius)
            for place in batch:
                place_id = place.get("place_id", "")
                if not place_id or place_id in seen_ids:
                    continue
                seen_ids.add(place_id)
                results.append(place)

        return results

    def _text_search(self, query: str, lat: float, lon: float, radius: int) -> list[dict[str, Any]]:
        """Search Google Places by SDK first, then REST as a fallback."""
        if self._client:
            try:
                resp = self._client.places(query=query, location=(lat, lon), radius=radius)
                return resp.get("results", [])[:8]
            except Exception:
                pass

        if not self.api_key:
            return []

        try:
            resp = requests.get(
                "https://maps.googleapis.com/maps/api/place/textsearch/json",
                params={
                    "query": query,
                    "location": f"{lat},{lon}",
                    "radius": radius,
                    "key": self.api_key,
                },
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("status") not in (None, "OK", "ZERO_RESULTS"):
                return []
            return payload.get("results", [])[:8]
        except requests.RequestException:
            return []

    def _build_destinations(self, places: list[dict[str, Any]]) -> list[Destination]:
        """Group venue/city hits by geocoded locality so we recommend cities, not single bars."""
        city_buckets: dict[str, dict[str, Any]] = {}

        for place in places:
            loc = place.get("geometry", {}).get("location", {})
            lat = loc.get("lat")
            lon = loc.get("lng")
            if lat is None or lon is None:
                continue

            geo = self._geocoder.reverse_geocode(lat, lon)
            if geo.country in ("Demo", "Unknown") and not self.api_key:
                continue
            if not _is_tropical_location(lat, geo.country, geo.region):
                continue

            city_name = geo.locality or place.get("name", "Unknown")
            bucket_key = f"{city_name}|{geo.country}".lower()
            bucket = city_buckets.setdefault(
                bucket_key,
                {
                    "name": city_name,
                    "country": geo.country,
                    "region": geo.region,
                    "lat_total": 0.0,
                    "lon_total": 0.0,
                    "count": 0,
                    "types": set(),
                },
            )
            bucket["lat_total"] += lat
            bucket["lon_total"] += lon
            bucket["count"] += 1
            bucket["types"].update(place.get("types", []))

        destinations: list[Destination] = []
        seen_slugs: set[str] = set()

        for bucket in city_buckets.values():
            count = bucket["count"]
            lat = bucket["lat_total"] / count
            lon = bucket["lon_total"] / count
            name = bucket["name"]
            country = bucket["country"]
            types = list(bucket["types"])

            slug = _slug(name)
            if slug in seen_slugs:
                slug = f"{slug}-{len(seen_slugs)}"
            seen_slugs.add(slug)

            adventure = self._infer_adventure_tags(types)
            airport = self._guess_airport_code(name, lat, lon)

            destinations.append(
                Destination(
                    id=slug,
                    name=name,
                    country=country,
                    latitude=lat,
                    longitude=lon,
                    airport_code=airport,
                    description=self._build_description(name, country, types),
                    adventure_tags=adventure,
                    nightlife_score=min(6 + count, 10),
                )
            )

        destinations.sort(key=lambda d: d.nightlife_score, reverse=True)
        return _dedupe_nearby(destinations)

    @staticmethod
    def _ensure_minimum_pool(destinations: list[Destination], minimum: int = 8) -> list[Destination]:
        """Top up with seed destinations if Google returns too few distinct cities."""
        if len(destinations) >= minimum:
            return destinations
        seen = {d.name.lower() for d in destinations}
        merged = list(destinations)
        for seed in SEED_DESTINATIONS:
            if seed.name.lower() not in seen:
                merged.append(seed)
                seen.add(seed.name.lower())
            if len(merged) >= minimum:
                break
        return merged

    @staticmethod
    def _infer_adventure_tags(types: list[str]) -> tuple[str, ...]:
        """Turn Google place types into a small set of activity tags."""
        tags: list[str] = []
        for t in types:
            tags.extend(ADVENTURE_BY_TYPES.get(t, ()))
        if not tags:
            tags = ["beach", "nightlife", "culture", "food"]
        # dedupe preserving order
        seen: set[str] = set()
        unique = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique.append(tag)
        return tuple(unique[:4])

    @staticmethod
    def _build_description(name: str, country: str, types: list[str]) -> str:
        """Build a short plain-English description for a discovered destination."""
        kind = "coastal destination"
        if "natural_feature" in types:
            kind = "natural getaway"
        elif "locality" in types or "sublocality" in types:
            kind = "city break"
        return f"{name} — {kind} in {country}, with beaches, restaurants, and nightlife nearby."

    def _guess_airport_code(self, city_name: str, lat: float, lon: float) -> str:
        """Guess a nearby airport code, using Google text search when available."""
        if not self.api_key:
            return city_name[:3].upper()

        query = f"{city_name} international airport"
        results = self._text_search(query, lat, lon, 150_000)
        for place in results:
            name = place.get("name", "")
            match = re.search(r"\(([A-Z]{3})\)", name)
            if match:
                return match.group(1)
        return city_name.replace(" ", "")[:3].upper()

    @staticmethod
    def _serialize(destinations: list[Destination]) -> list[dict[str, Any]]:
        """Convert destination objects into JSON-friendly cache rows."""
        return [
            {
                "id": d.id,
                "name": d.name,
                "country": d.country,
                "latitude": d.latitude,
                "longitude": d.longitude,
                "airport_code": d.airport_code,
                "description": d.description,
                "adventure_tags": list(d.adventure_tags),
                "nightlife_score": d.nightlife_score,
            }
            for d in destinations
        ]

    @staticmethod
    def _deserialize(rows: list[dict[str, Any]]) -> list[Destination]:
        """Convert cached destination dictionaries back into Destination objects."""
        return [
            Destination(
                id=row["id"],
                name=row["name"],
                country=row["country"],
                latitude=row["latitude"],
                longitude=row["longitude"],
                airport_code=row["airport_code"],
                description=row["description"],
                adventure_tags=tuple(row.get("adventure_tags", ())),
                nightlife_score=int(row.get("nightlife_score", 7)),
            )
            for row in rows
        ]

    @staticmethod
    def _is_fresh(fetched_at: str | None) -> bool:
        """Check whether the cached destination pool is still inside its TTL."""
        from datetime import datetime, timezone

        if not fetched_at:
            return False
        ts = datetime.fromisoformat(fetched_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age < DESTINATIONS_CACHE_TTL


def cached_fetched_iso() -> str:
    """Return a timezone-aware timestamp for destination cache writes."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
