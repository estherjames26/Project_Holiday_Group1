# OpenWeatherMap — current weather and 5-day forecast.
# Docs: https://openweathermap.org/api
# No API key? We return fake but stable demo data so the UI still works.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from src.config import OPENWEATHER_API_KEY, WEATHER_CACHE_TTL
from src.database.models import cache_weather, get_cached_weather, get_session


@dataclass
class WeatherSnapshot:
    latitude: float
    longitude: float
    country: str
    temp_max_c: float
    temp_min_c: float
    humidity: int
    cloudiness: int
    wind_speed_ms: float
    wind_speed_forecast_ms: float
    description: str
    forecast_days: list[dict[str, Any]]


class WeatherService:
    BASE = "https://api.openweathermap.org/data/2.5"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or OPENWEATHER_API_KEY

    def get_weather(
        self,
        destination_id: str,
        lat: float,
        lon: float,
        country_hint: str = "",
    ) -> WeatherSnapshot:
        session = get_session()
        try:
            cached = get_cached_weather(session, destination_id)
            if cached and self._is_fresh(cached.get("fetched_at"), WEATHER_CACHE_TTL):
                return self._from_payload(cached["data"])

            data = self._fetch(lat, lon)
            cache_weather(
                session,
                destination_id,
                {"fetched_at": datetime.now(timezone.utc).isoformat(), "data": data},
            )
            return self._from_payload(data)
        finally:
            session.close()

    def _fetch(self, lat: float, lon: float) -> dict[str, Any]:
        if not self.api_key:
            return self._mock_weather(lat, lon)

        try:
            current = requests.get(
                f"{self.BASE}/weather",
                params={"lat": lat, "lon": lon, "appid": self.api_key, "units": "metric"},
                timeout=15,
            )
            current.raise_for_status()
            forecast = requests.get(
                f"{self.BASE}/forecast",
                params={"lat": lat, "lon": lon, "appid": self.api_key, "units": "metric"},
                timeout=15,
            )
            forecast.raise_for_status()
            cur = current.json()
            fc = forecast.json()
            return {
                "lat": lat,
                "lon": lon,
                "country": cur.get("sys", {}).get("country", ""),
                "current": cur,
                "forecast": fc,
            }
        except requests.RequestException:
            return self._mock_weather(lat, lon)

    @staticmethod
    def _mock_weather(lat: float, lon: float) -> dict[str, Any]:
        # Seed from coords so each destination gets different but repeatable numbers
        seed = int(abs(lat * 100 + lon * 10)) % 8
        temps = [28, 30, 32, 27, 29, 31, 26, 33]
        return {
            "lat": lat,
            "lon": lon,
            "country": "XX",
            "current": {
                "main": {"temp_max": temps[seed], "temp_min": temps[seed] - 4, "humidity": 65 + seed},
                "clouds": {"all": 20 + seed * 5},
                "wind": {"speed": 3.5 + seed * 0.4},
                "weather": [{"description": "partly cloudy"}],
            },
            "forecast": {
                "list": [
                    {
                        "dt_txt": f"2026-06-{22 + i} 12:00:00",
                        "main": {"temp_max": temps[seed] + i, "temp_min": temps[seed] - 3},
                        "wind": {"speed": 4.0 + i * 0.3},
                        "clouds": {"all": 30 + i * 5},
                    }
                    for i in range(5)
                ]
            },
        }

    @staticmethod
    def _from_payload(data: dict[str, Any]) -> WeatherSnapshot:
        cur = data["current"]
        fc_list = data.get("forecast", {}).get("list", [])
        forecast_days = []
        seen_dates: set[str] = set()

        # Forecast API returns every 3 hours — we only keep one entry per day
        for item in fc_list:
            date = item["dt_txt"].split(" ")[0]
            if date in seen_dates:
                continue
            seen_dates.add(date)
            forecast_days.append({
                "date": date,
                "temp_max": item["main"]["temp_max"],
                "temp_min": item["main"]["temp_min"],
                "wind_speed": item["wind"]["speed"],
                "cloudiness": item["clouds"]["all"],
            })
            if len(forecast_days) >= 5:
                break

        avg_fc_wind = (
            sum(d["wind_speed"] for d in forecast_days) / len(forecast_days)
            if forecast_days
            else cur["wind"]["speed"]
        )
        return WeatherSnapshot(
            latitude=data["lat"],
            longitude=data["lon"],
            country=data.get("country", ""),
            temp_max_c=cur["main"]["temp_max"],
            temp_min_c=cur["main"]["temp_min"],
            humidity=cur["main"]["humidity"],
            cloudiness=cur["clouds"]["all"],
            wind_speed_ms=cur["wind"]["speed"],
            wind_speed_forecast_ms=avg_fc_wind,
            description=cur["weather"][0]["description"],
            forecast_days=forecast_days,
        )

    @staticmethod
    def _is_fresh(fetched_at: str | None, ttl: int) -> bool:
        if not fetched_at:
            return False
        ts = datetime.fromisoformat(fetched_at)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age < ttl
