# Google Places — finds bars, restaurants and nightclubs within 5 km.
# Needs GOOGLE_MAPS_API_KEY with Places API enabled.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import googlemaps
import requests

from src.config import GOOGLE_MAPS_API_KEY, PLACES_CACHE_TTL, usable_api_key
from src.database.models import cache_places, get_cached_places, get_session


@dataclass
class PlaceResult:
    name: str
    place_type: str
    rating: float | None
    latitude: float
    longitude: float
    address: str
    user_ratings_total: int = 0


@dataclass
class AmenitySummary:
    bars: list[PlaceResult] = field(default_factory=list)
    restaurants: list[PlaceResult] = field(default_factory=list)
    night_clubs: list[PlaceResult] = field(default_factory=list)

    @property
    def bar_count(self) -> int:
        return len(self.bars)

    @property
    def restaurant_count(self) -> int:
        return len(self.restaurants)

    @property
    def nightclub_count(self) -> int:
        return len(self.night_clubs)

    @property
    def total_nightlife(self) -> int:
        return self.bar_count + self.nightclub_count


class GooglePlacesService:
    PLACE_TYPES = {
        "bar": "bar",
        "restaurant": "restaurant",
        "night_club": "night_club",
    }

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = usable_api_key(api_key or GOOGLE_MAPS_API_KEY)
        self._client = None
        if self.api_key:
            try:
                self._client = googlemaps.Client(key=self.api_key)
            except ValueError:
                self.api_key = ""

    def get_amenities(
        self,
        destination_id: str,
        lat: float,
        lon: float,
        radius_m: int = 5000,
    ) -> AmenitySummary:
        cache_key = f"{destination_id}_{radius_m}"
        session = get_session()
        try:
            cached = get_cached_places(session, cache_key)
            if cached and self._is_fresh(cached):
                return self._from_dict(cached["data"])

            data = self._fetch(lat, lon, radius_m)
            cache_places(session, cache_key, {"fetched_at": cached_fetched_iso(), "data": data})
            return self._from_dict(data)
        finally:
            session.close()

    def _fetch(self, lat: float, lon: float, radius_m: int) -> dict[str, list[dict]]:
        if self._client:
            return self._fetch_via_sdk(lat, lon, radius_m)
        return self._fetch_via_rest(lat, lon, radius_m)
    

    def _fetch_via_sdk(self, lat: float, lon: float, radius_m: int) -> dict[str, list[dict]]:
        location = (lat, lon)
        result = {}
        try:
            for key, place_type in self.PLACE_TYPES.items():
                resp = self._client.places_nearby(location=location, radius=radius_m, type=place_type)
                results = resp.get("results", [])[:10]
                print(f"[Places SDK] {place_type} at {lat},{lon}: {len(results)} results, first={results[0]['name'] if results else 'none'}")
                result[key] = results
            return result
        except Exception:
            return self._fetch_via_rest(lat, lon, radius_m)

    def _fetch_via_rest(self, lat: float, lon: float, radius_m: int) -> dict[str, list[dict]]:
        if not self.api_key:
            return self._mock_places(lat, lon)

        result: dict[str, list[dict]] = {}
        try:
            for key, place_type in self.PLACE_TYPES.items():
                resp = requests.get(
                    "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
                    params={
                        "location": f"{lat},{lon}",
                        "radius": radius_m,
                        "type": place_type,
                        "key": self.api_key,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                payload = resp.json()
                print(f"[Places API] status={payload.get('status')} error={payload.get('error_message', '')}")
                if payload.get("status") not in (None, "OK", "ZERO_RESULTS"):
                    return self._mock_places(lat, lon)
                result[key] = payload.get("results", [])[:10]
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            return self._mock_places(lat, lon)
        return result

    @staticmethod
    def _mock_places(lat: float, lon: float) -> dict[str, list[dict]]:
        offsets = [(0.01, 0.008), (-0.008, 0.012), (0.015, -0.005), (-0.012, -0.01)]
        bar_names = ["The Beach Bar", "Harbour Tavern", "Sunset Lounge", "Corner Pub"]
        food_names = ["Harbour Kitchen", "Local Grill", "Sea View Cafe", "Backstreet Bistro"]
        club_names = ["Club 21", "The Loft", "Ocean Room"]
        areas = ["Beachfront", "Old Town", "Centre", "Marina"]
        bars = [
            {
                "name": bar_names[i],
                "geometry": {"location": {"lat": lat + o[0], "lng": lon + o[1]}},
                "rating": 4.2 + i * 0.1,
                "vicinity": areas[i],
                "user_ratings_total": 120 + i * 30,
            }
            for i, o in enumerate(offsets)
        ]
        restaurants = [
            {
                "name": food_names[i],
                "geometry": {"location": {"lat": lat - o[0], "lng": lon + o[1]}},
                "rating": 4.0 + i * 0.15,
                "vicinity": areas[i],
                "user_ratings_total": 200 + i * 40,
            }
            for i, o in enumerate(offsets)
        ]
        clubs = [
            {
                "name": club_names[i],
                "geometry": {"location": {"lat": lat + o[1], "lng": lon - o[0]}},
                "rating": 4.3 + i * 0.08,
                "vicinity": areas[i],
                "user_ratings_total": 350 + i * 50,
            }
            for i, o in enumerate(offsets[:3])
        ]
        return {"bar": bars, "restaurant": restaurants, "night_club": clubs}

    @staticmethod
    def _parse_place(raw: dict, place_type: str) -> PlaceResult:
        loc = raw["geometry"]["location"]
        return PlaceResult(
            name=raw.get("name", "Unknown"),
            place_type=place_type,
            rating=raw.get("rating"),
            latitude=loc["lat"],
            longitude=loc["lng"],
            address=raw.get("vicinity", raw.get("formatted_address", "")),
            user_ratings_total=raw.get("user_ratings_total", 0),
        )

    def _from_dict(self, data: dict[str, list[dict]]) -> AmenitySummary:
        return AmenitySummary(
            bars=[self._parse_place(p, "bar") for p in data.get("bar", [])],
            restaurants=[self._parse_place(p, "restaurant") for p in data.get("restaurant", [])],
            night_clubs=[self._parse_place(p, "night_club") for p in data.get("night_club", [])],
        )

    @staticmethod
    def _is_fresh(cached: dict[str, Any]) -> bool:
        from datetime import datetime, timezone

        fetched_at = cached.get("fetched_at")
        if not fetched_at:
            return False
        ts = datetime.fromisoformat(fetched_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age < PLACES_CACHE_TTL


def cached_fetched_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def build_google_maps_embed_url(lat: float, lon: float, api_key: str, zoom: int = 12) -> str:
    if not api_key:
        return ""
    return (
        f"https://www.google.com/maps/embed/v1/view"
        f"?key={api_key}&center={lat},{lon}&zoom={zoom}&maptype=roadmap"
    )
