# Turns lat/lon into a city name and country via Google Geocoding.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import googlemaps
import requests

from settings import GOOGLE_MAPS_API_KEY, usable_api_key


@dataclass
class GeoInfo:
    formatted_address: str
    country: str
    region: str
    locality: str
    place_id: str


class GoogleGeocodingService:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = usable_api_key(api_key or GOOGLE_MAPS_API_KEY)
        self._client = None
        if self.api_key:
            try:
                self._client = googlemaps.Client(key=self.api_key)
            except ValueError:
                self.api_key = ""

    def reverse_geocode(self, lat: float, lon: float) -> GeoInfo:
        if self._client:
            return self._via_sdk(lat, lon)
        if self.api_key:
            return self._via_rest(lat, lon)
        return self._mock(lat, lon)

    def _via_sdk(self, lat: float, lon: float) -> GeoInfo:
        results = self._client.reverse_geocode((lat, lon))
        return self._parse(results)

    def _via_rest(self, lat: float, lon: float) -> GeoInfo:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"latlng": f"{lat},{lon}", "key": self.api_key},
            timeout=15,
        )
        resp.raise_for_status()
        return self._parse(resp.json().get("results", []))

    @staticmethod
    def _parse(results: list[dict[str, Any]]) -> GeoInfo:
        if not results:
            return GeoInfo("Unknown", "Unknown", "Unknown", "Unknown", "")

        top = results[0]
        country = region = locality = ""
        for comp in top.get("address_components", []):
            types = comp.get("types", [])
            if "country" in types:
                country = comp.get("long_name", "")
            if "administrative_area_level_1" in types:
                region = comp.get("long_name", "")
            if "locality" in types:
                locality = comp.get("long_name", "")
            elif not locality and "administrative_area_level_2" in types:
                locality = comp.get("long_name", "")

        return GeoInfo(
            formatted_address=top.get("formatted_address", ""),
            country=country,
            region=region,
            locality=locality or region or top.get("formatted_address", "").split(",")[0],
            place_id=top.get("place_id", ""),
        )

    @staticmethod
    def _mock(lat: float, lon: float) -> GeoInfo:
        return GeoInfo(
            formatted_address=f"Demo location ({lat:.2f}, {lon:.2f})",
            country="Demo",
            region="Tropical",
            locality="Demo",
            place_id="demo_place_id",
        )
