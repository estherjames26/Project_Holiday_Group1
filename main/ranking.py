# Main ranking logic — filters places by your prefs and scores what's left.
# If rankings look wrong, start debugging here.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from places import get_destinations, Destination
from database import get_session, log_recommendation
from trip_notes import generate_destination_insights, generate_portfolio_insights
from api_geocoding import GoogleGeocodingService
from api_google_places import GooglePlacesService
from api_openai import LLMService
from scrape_costs import CostScraperService
from api_weather import WeatherService


@dataclass
class UserPreferences:
    min_temp_c: float = 26.0
    max_temp_c: float = 34.0
    max_wind_ms: float = 12.0
    max_budget_usd: float = 3500.0
    min_nightlife_venues: int = 3
    weather_weight: float = 0.25
    cost_weight: float = 0.25
    nightlife_weight: float = 0.30
    adventure_weight: float = 0.20
    preferred_tags: list[str] = field(default_factory=list)


@dataclass
class ScoredDestination:
    destination: Destination
    score: float
    weather: dict[str, Any]
    costs: dict[str, Any]
    amenities: dict[str, Any]
    breakdown: dict[str, float]


class RecommendationEngine:
    def __init__(self) -> None:
        self.weather = WeatherService()
        self.places = GooglePlacesService()
        self.geocoding = GoogleGeocodingService()
        self.costs = CostScraperService()
        self.llm = LLMService()

    def recommend(
        self,
        prefs: UserPreferences,
        origin_airport: str = "LHR",
        top_n: int = 5,
        persist: bool = True,
    ) -> tuple[list[dict[str, Any]], str, list[str]]:
        self.costs.origin = origin_airport
        scored: list[ScoredDestination] = []
        candidates = get_destinations()

        for dest in candidates:
            result = self._score_destination(dest, prefs)
            if result:
                scored.append(result)

        scored.sort(key=lambda x: x.score, reverse=True)
        top = scored[:top_n]
        output = [self._to_dict(s) for s in top]

        for item in output:
            item["insights"] = generate_destination_insights(item, output)

        portfolio = generate_portfolio_insights(output, prefs.__dict__, len(candidates))
        summary = self.llm.generate_recommendation_summary(
            output,
            {
                "max_budget": prefs.max_budget_usd,
                "min_temp": prefs.min_temp_c,
                "max_temp": prefs.max_temp_c,
                "nightlife_weight": prefs.nightlife_weight,
            },
        )

        if persist and output:
            session = get_session()
            try:
                log_recommendation(session, origin_airport, prefs.__dict__, output)
            finally:
                session.close()

        return output, summary, portfolio

    def _score_destination(
        self,
        dest: Destination,
        prefs: UserPreferences,
    ) -> ScoredDestination | None:
        wx = self.weather.get_weather(dest.id, dest.latitude, dest.longitude, dest.country)
        if wx.temp_max_c < prefs.min_temp_c or wx.temp_max_c > prefs.max_temp_c:
            return None
        if wx.wind_speed_ms > prefs.max_wind_ms:
            return None

        amenities = self.places.get_amenities(dest.id, dest.latitude, dest.longitude)
        if amenities.total_nightlife < prefs.min_nightlife_venues:
            return None

        costs = self.costs.get_costs(dest.id, dest.name, dest.country, dest.airport_code)
        if costs.total_7_night_usd > prefs.max_budget_usd:
            return None

        weather_score = self._weather_score(wx, prefs)
        cost_score = self._cost_score(costs.total_7_night_usd, prefs.max_budget_usd)
        nightlife_score = self._nightlife_score(amenities, dest.nightlife_score)
        adventure_score = self._adventure_score(dest, prefs.preferred_tags)

        total = (
            weather_score * prefs.weather_weight
            + cost_score * prefs.cost_weight
            + nightlife_score * prefs.nightlife_weight
            + adventure_score * prefs.adventure_weight
        ) * 100

        return ScoredDestination(
            destination=dest,
            score=round(total, 1),
            weather={
                "temp_max_c": wx.temp_max_c,
                "temp_min_c": wx.temp_min_c,
                "humidity": wx.humidity,
                "cloudiness": wx.cloudiness,
                "wind_speed_ms": wx.wind_speed_ms,
                "wind_forecast_ms": wx.wind_speed_forecast_ms,
                "country": wx.country or dest.country,
                "description": wx.description,
                "forecast_days": wx.forecast_days,
            },
            costs={
                "flight_usd": costs.flight_estimate_usd,
                "hotel_nightly_usd": costs.hotel_nightly_usd,
                "airbnb_nightly_usd": costs.airbnb_nightly_usd,
                "meal_index": costs.meal_index,
                "total_7_night_usd": costs.total_7_night_usd,
                "source": costs.source,
                "scrape_sources": costs.scrape_sources,
            },
            amenities={
                "bars": [self._place_dict(p) for p in amenities.bars],
                "restaurants": [self._place_dict(p) for p in amenities.restaurants],
                "night_clubs": [self._place_dict(p) for p in amenities.night_clubs],
                "total_nightlife": amenities.total_nightlife,
                "restaurant_count": amenities.restaurant_count,
            },
            breakdown={
                "weather": round(weather_score * 100, 1),
                "cost": round(cost_score * 100, 1),
                "nightlife": round(nightlife_score * 100, 1),
                "adventure": round(adventure_score * 100, 1),
            },
        )

    @staticmethod
    def _weather_score(wx: Any, prefs: UserPreferences) -> float:
        ideal = (prefs.min_temp_c + prefs.max_temp_c) / 2
        temp_diff = abs(wx.temp_max_c - ideal) / max(ideal, 1)
        temp_part = max(0, 1 - temp_diff)
        wind_part = max(0, 1 - wx.wind_speed_ms / prefs.max_wind_ms)
        cloud_part = max(0, 1 - wx.cloudiness / 100)
        humidity_part = max(0, 1 - abs(wx.humidity - 60) / 60)
        return temp_part * 0.4 + wind_part * 0.25 + cloud_part * 0.2 + humidity_part * 0.15

    @staticmethod
    def _cost_score(total: float, max_budget: float) -> float:
        if total >= max_budget:
            return 0.0
        return 1 - (total / max_budget)

    @staticmethod
    def _nightlife_score(amenities: Any, baseline: int) -> float:
        venue_part = min(amenities.total_nightlife / 10, 1.0)
        baseline_part = baseline / 10
        return venue_part * 0.6 + baseline_part * 0.4

    @staticmethod
    def _adventure_score(dest: Destination, preferred: list[str]) -> float:
        if not preferred:
            return len(dest.adventure_tags) / 6
        matches = sum(1 for t in dest.adventure_tags if any(p in t for p in preferred))
        return min(matches / max(len(preferred), 1), 1.0)

    @staticmethod
    def _place_dict(place: Any) -> dict[str, Any]:
        return {
            "name": place.name,
            "latitude": place.latitude,
            "longitude": place.longitude,
            "rating": place.rating,
            "address": place.address,
            "type": place.place_type,
            "weight": (place.rating or 3.5) / 5,
        }

    def _to_dict(self, scored: ScoredDestination) -> dict[str, Any]:
        d = scored.destination
        geo = self.geocoding.reverse_geocode(d.latitude, d.longitude)
        return {
            "id": d.id,
            "name": d.name,
            "country": d.country,
            "latitude": d.latitude,
            "longitude": d.longitude,
            "airport_code": d.airport_code,
            "description": d.description,
            "adventure_tags": list(d.adventure_tags),
            "score": scored.score,
            "breakdown": scored.breakdown,
            "temp_max_c": scored.weather["temp_max_c"],
            "humidity": scored.weather["humidity"],
            "cloudiness": scored.weather["cloudiness"],
            "wind_speed_ms": scored.weather["wind_speed_ms"],
            "weather": scored.weather,
            "costs": scored.costs,
            "total_cost_usd": scored.costs["total_7_night_usd"],
            "nightlife_total": scored.amenities["total_nightlife"],
            "amenities": scored.amenities,
            "geocoding": {
                "formatted_address": geo.formatted_address,
                "country_verified": geo.country,
                "region": geo.region,
                "place_id": geo.place_id,
            },
        }

    def get_all_for_map(self, prefs: UserPreferences, origin: str = "LHR") -> list[dict[str, Any]]:
        self.costs.origin = origin
        results = []
        candidates = get_destinations()
        for dest in candidates:
            s = self._score_destination(dest, prefs)
            if s:
                results.append(self._to_dict(s))
        return results
