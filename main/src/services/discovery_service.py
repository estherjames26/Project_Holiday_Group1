# Discovers tropical destinations dynamically via Google Places Text Search.
# Results are cached long-term in the database so repeated searches are fast.
# Falls back to the hardcoded DESTINATIONS list if the API is unavailable.

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from src.config import GOOGLE_MAPS_API_KEY, usable_api_key
from src.data.destinations import Destination
from src.database.models import cache_places, get_cached_places, get_session

# How long discovered destination lists are cached (7 days)
DISCOVERY_CACHE_TTL = 604800

# Regions the user can optionally filter by
REGIONS: list[str] = [
    "Global",
    "Southeast Asia",
    "Caribbean",
    "Mediterranean",
    "Central America",
    "South America",
    "Pacific Islands",
    "Indian Ocean",
    "Africa",
    "Middle East",
]

# Explicit geography-first queries per region so Google doesn't bias toward the user's IP location.
# Each query names a specific country or island group — generic terms like "tropical beach"
# alone cause Google to return nearby results (e.g. London bars) instead of actual destinations.
_REGION_QUERIES: dict[str, list[str]] = {
    "Global": [
        "Phuket Thailand beach city",
        "Bali Indonesia beach city",
        "Cancun Mexico beach city",
        "Punta Cana Dominican Republic beach",
        "Barbados beach city",
        "Jamaica beach city nightlife",
        "Maldives island resort",
        "Mauritius beach city",
        "Seychelles beach island",
        "Sri Lanka beach city",
        "Zanzibar Tanzania beach",
        "Nairobi coast Kenya beach",
        "Mykonos Greece island",
        "Ibiza Spain island nightlife",
        "Dubrovnik Croatia beach",
        "Dubai UAE beach city",
        "Fiji island beach",
        "Bora Bora French Polynesia",
        "Cartagena Colombia beach city",
        "Rio de Janeiro Brazil beach",
        "Puerto Rico San Juan beach",
        "Costa Rica beach city",
        "Philippines Boracay island beach",
        "Vietnam Da Nang beach city",
        "Malaysia Langkawi island beach",
    ],
    "Southeast Asia": [
        "Phuket Thailand beach city",
        "Koh Samui Thailand island",
        "Bali Indonesia beach city",
        "Lombok Indonesia island beach",
        "Boracay Philippines island",
        "Palawan Philippines beach",
        "Da Nang Vietnam beach city",
        "Hoi An Vietnam beach",
        "Langkawi Malaysia island beach",
        "Penang Malaysia beach city",
        "Siem Reap Cambodia",
        "Yangon Myanmar beach",
    ],
    "Caribbean": [
        "Jamaica Montego Bay beach city",
        "Jamaica Kingston nightlife",
        "Punta Cana Dominican Republic beach",
        "Santo Domingo Dominican Republic city",
        "San Juan Puerto Rico beach city",
        "Nassau Bahamas beach city",
        "Bridgetown Barbados beach city",
        "Castries St Lucia beach",
        "Antigua island beach",
        "Aruba island beach nightlife",
        "Trinidad Port of Spain nightlife",
        "Turks and Caicos island beach",
        "Curacao island beach",
        "St Maarten island beach",
    ],
    "Mediterranean": [
        "Mykonos Greece island nightlife",
        "Santorini Greece island",
        "Rhodes Greece island beach",
        "Ibiza Spain island nightlife",
        "Mallorca Spain island beach",
        "Dubrovnik Croatia beach city",
        "Split Croatia beach city",
        "Antalya Turkey beach city",
        "Bodrum Turkey beach nightlife",
        "Malta island beach city",
        "Valletta Malta city",
        "Limassol Cyprus beach city",
        "Amalfi Coast Italy beach",
        "Sicily Italy beach city",
        "Tunis Tunisia beach city",
    ],
    "Central America": [
        "San Jose Costa Rica city beach",
        "Liberia Costa Rica beach",
        "Panama City Panama beach nightlife",
        "Bocas del Toro Panama island",
        "Belize City Belize beach",
        "Ambergris Caye Belize island",
        "Managua Nicaragua beach",
        "Roatan Honduras island beach",
        "Antigua Guatemala city",
        "El Salvador beach city",
    ],
    "South America": [
        "Rio de Janeiro Brazil beach city nightlife",
        "Florianopolis Brazil beach city",
        "Cartagena Colombia beach city",
        "Santa Marta Colombia beach",
        "Lima Peru beach city",
        "Mancora Peru beach",
        "Guayaquil Ecuador beach",
        "Montanita Ecuador beach",
        "Caracas Venezuela beach",
        "Buenos Aires Argentina city beach",
        "Montevideo Uruguay beach city",
    ],
    "Pacific Islands": [
        "Nadi Fiji island beach",
        "Suva Fiji city beach",
        "Honolulu Hawaii beach city nightlife",
        "Maui Hawaii island beach",
        "Papeete Tahiti French Polynesia",
        "Bora Bora French Polynesia island",
        "Apia Samoa island beach",
        "Port Vila Vanuatu island beach",
        "Rarotonga Cook Islands beach",
        "Nuku alofa Tonga island beach",
    ],
    "Indian Ocean": [
        "Male Maldives island resort",
        "Port Louis Mauritius beach city",
        "Victoria Seychelles island beach",
        "Colombo Sri Lanka beach city",
        "Galle Sri Lanka beach",
        "Saint Denis Reunion island beach",
        "Zanzibar Tanzania beach city",
        "Maputo Mozambique beach city",
        "Diego Suarez Madagascar beach",
    ],
    "Africa": [
        "Mombasa Kenya beach city",
        "Zanzibar Tanzania beach city nightlife",
        "Cape Town South Africa beach city",
        "Durban South Africa beach city",
        "Marrakech Morocco city",
        "Agadir Morocco beach city",
        "Dakar Senegal beach city",
        "Accra Ghana beach city nightlife",
        "Lagos Nigeria beach city",
        "Dar es Salaam Tanzania beach city",
    ],
    "Middle East": [
        "Dubai UAE beach city nightlife",
        "Abu Dhabi UAE beach city",
        "Muscat Oman beach city",
        "Salalah Oman beach",
        "Manama Bahrain beach city nightlife",
        "Aqaba Jordan beach city",
        "Hurghada Egypt beach city",
        "Sharm el Sheikh Egypt beach",
    ],
}

# Google Places types that indicate a city/island — not a bar, hotel or restaurant
_VALID_LOCATION_TYPES = {
    "locality",
    "administrative_area_level_1",
    "administrative_area_level_2",
    "sublocality",
    "natural_feature",
    "island",
    "tourist_attraction",
    "point_of_interest",
    "establishment",
    "neighborhood",
    "colloquial_area",
    "archipelago",
}


class DestinationDiscoveryService:
    """Finds and returns Destination objects from Google Places Text Search."""

    TEXTSEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = usable_api_key(api_key or GOOGLE_MAPS_API_KEY)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def get_destinations(self, region: str = "Global") -> list[Destination]:
        cache_key = f"discovery_{region.lower().replace(' ', '_')}"
        session = get_session()
        try:
            cached = get_cached_places(session, cache_key)
            if cached and self._is_fresh(cached.get("fetched_at"), DISCOVERY_CACHE_TTL):
                return self._dests_from_cache(cached["data"])

            if not self.api_key:
                return []

            dests = self._discover(region)
            if not dests:
                return []

            serialised = [self._dest_to_dict(d) for d in dests]
            cache_places(
                session,
                cache_key,
                {
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "data": {"destinations": serialised},
                },
            )
            return dests
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover(self, region: str) -> list[Destination]:
        queries = _REGION_QUERIES.get(region, _REGION_QUERIES["Global"])
        seen_place_ids: set[str] = set()
        raw_results: list[dict[str, Any]] = []

        for query in queries:
            results = self._text_search(query)
            for r in results:
                pid = r.get("place_id", "")
                if pid and pid not in seen_place_ids:
                    seen_place_ids.add(pid)
                    raw_results.append(r)

        dests: list[Destination] = []
        seen_ids: set[str] = set()
        for raw in raw_results:
            d = self._to_destination(raw)
            if d and d.id not in seen_ids:
                seen_ids.add(d.id)
                dests.append(d)


        return dests

    def _text_search(self, query: str) -> list[dict[str, Any]]:
        try:
            resp = requests.get(
                self.TEXTSEARCH_URL,
                params={
                    "query": query,
                    "key": self.api_key,
                    "type": "locality",
                },
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("status") not in ("OK", "ZERO_RESULTS"):
                return []
            return payload.get("results", [])
        except requests.RequestException:
            return []

    def _to_destination(self, raw: dict[str, Any]) -> Destination | None:
        try:
            loc = raw["geometry"]["location"]
            lat, lon = loc["lat"], loc["lng"]
            name = raw.get("name", "").strip()
            if not name:
                return None

            # Skip individual venues — we want cities/islands only
            place_types = set(raw.get("types", []))
            venue_types = {"bar", "restaurant", "food", "night_club", "lodging", "cafe", "store"}
            if place_types & venue_types and not (place_types & _VALID_LOCATION_TYPES):
                return None

            # Skip anything with very few ratings — likely a small venue
            if raw.get("user_ratings_total", 0) < 500:
                return None

            country = self._extract_country(raw)
            dest_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            tags = self._infer_tags(raw.get("types", []), name)

            return Destination(
                id=dest_id,
                name=name,
                country=country,
                latitude=lat,
                longitude=lon,
                airport_code="",
                description=raw.get("formatted_address", name),
                adventure_tags=tuple(tags),
                nightlife_score=self._infer_nightlife_score(raw),
            )
        except (KeyError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_country(raw: dict[str, Any]) -> str:
        for comp in raw.get("address_components", []):
            if "country" in comp.get("types", []):
                return comp.get("long_name", "")
        addr = raw.get("formatted_address", "")
        parts = [p.strip() for p in addr.split(",")]
        return parts[-1] if parts else ""

    @staticmethod
    def _infer_tags(types: list[str], name: str) -> list[str]:
        tag_map = {
            "beach": "beach",
            "island": "island-hopping",
            "park": "hiking",
            "natural_feature": "hiking",
        }
        tags = [tag_map[t] for t in types if t in tag_map]
        name_lower = name.lower()
        if "surf" in name_lower:
            tags.append("surfing")
        if "div" in name_lower:
            tags.append("diving")
        if "snorkel" in name_lower:
            tags.append("snorkeling")
        return list(dict.fromkeys(tags)) or ["beach"]

    @staticmethod
    def _infer_nightlife_score(raw: dict[str, Any]) -> int:
        total = raw.get("user_ratings_total", 0)
        if total > 50000:
            return 9
        if total > 20000:
            return 8
        if total > 5000:
            return 7
        return 6

    # ------------------------------------------------------------------
    # Cache serialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _dest_to_dict(d: Destination) -> dict[str, Any]:
        return {
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

    @staticmethod
    def _dests_from_cache(data: dict[str, Any]) -> list[Destination]:
        return [
            Destination(
                id=d["id"],
                name=d["name"],
                country=d["country"],
                latitude=d["latitude"],
                longitude=d["longitude"],
                airport_code=d.get("airport_code", ""),
                description=d.get("description", ""),
                adventure_tags=tuple(d.get("adventure_tags", [])),
                nightlife_score=d.get("nightlife_score", 6),
            )
            for d in data.get("destinations", [])
        ]

    @staticmethod
    def _is_fresh(fetched_at: str | None, ttl: int) -> bool:
        if not fetched_at:
            return False
        ts = datetime.fromisoformat(fetched_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age < ttl