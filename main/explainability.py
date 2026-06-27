"""
explainability.py

Creates user-facing explanations for why each destination was recommended.

This module does not change the ranking algorithm. It explains the existing
score breakdown in plain English so users can understand how weather, cost,
nightlife and adventure affected the final ranking.
"""

from __future__ import annotations

from typing import Any


CRITERIA_LABELS = {
    "weather": "weather",
    "cost": "cost value",
    "nightlife": "nightlife",
    "adventure": "adventure match",
}


def _get_breakdown(dest: dict[str, Any]) -> dict[str, float]:
    """
    Safely return the score breakdown from a destination dictionary.

    Expected format:
        {
            "weather": 77.0,
            "cost": 19.0,
            "nightlife": 78.0,
            "adventure": 50.0
        }
    """
    breakdown = dest.get("breakdown", {}) or {}

    return {
        "weather": float(breakdown.get("weather", 0)),
        "cost": float(breakdown.get("cost", 0)),
        "nightlife": float(breakdown.get("nightlife", 0)),
        "adventure": float(breakdown.get("adventure", 0)),
    }


def _get_weights(prefs: Any) -> dict[str, float]:
    """
    Safely return the user's scoring weights.

    If preferences are missing, use a balanced fallback.
    """
    if prefs is None:
        return {
            "weather": 0.25,
            "cost": 0.25,
            "nightlife": 0.25,
            "adventure": 0.25,
        }

    weights = {
        "weather": float(getattr(prefs, "weather_weight", 0.25)),
        "cost": float(getattr(prefs, "cost_weight", 0.25)),
        "nightlife": float(getattr(prefs, "nightlife_weight", 0.25)),
        "adventure": float(getattr(prefs, "adventure_weight", 0.25)),
    }

    total = sum(weights.values())

    if total <= 0:
        return {
            "weather": 0.25,
            "cost": 0.25,
            "nightlife": 0.25,
            "adventure": 0.25,
        }

    return {key: value / total for key, value in weights.items()}


def _join_naturally(items: list[str]) -> str:
    """
    Join a list of words in a readable way.

    Examples:
        ["weather"] -> "weather"
        ["weather", "cost"] -> "weather and cost"
        ["weather", "cost", "nightlife"] -> "weather, cost and nightlife"
    """
    if not items:
        return "the selected criteria"

    if len(items) == 1:
        return items[0]

    if len(items) == 2:
        return f"{items[0]} and {items[1]}"

    return f"{', '.join(items[:-1])} and {items[-1]}"


def _top_categories(values: dict[str, float], tolerance: float = 0.0001) -> list[str]:
    """
    Return all categories tied for the highest value.

    The tolerance avoids tiny floating point differences causing false winners.
    """
    if not values:
        return []

    highest = max(values.values())

    return [
        key
        for key, value in values.items()
        if abs(value - highest) <= tolerance
    ]


def _describe_user_priority(weights: dict[str, float]) -> str:
    """
    Explain which criteria the user weighted most highly.
    """
    top_keys = _top_categories(weights)

    if len(top_keys) == 4:
        return "Your selected weights are balanced equally across weather, cost, nightlife and adventure."

    top_labels = [CRITERIA_LABELS.get(key, key) for key in top_keys]

    return (
        "Your selected weights place the most emphasis on "
        f"{_join_naturally(top_labels)}."
    )


def _describe_strongest_raw_score(breakdown: dict[str, float]) -> str:
    """
    Explain which criterion had the highest raw score before weighting.
    """
    top_keys = _top_categories(breakdown)
    top_labels = [CRITERIA_LABELS.get(key, key) for key in top_keys]

    if len(top_keys) == 4:
        return "This destination has an even score profile across all criteria."

    return f"This destination scored strongest for {_join_naturally(top_labels)}."


def _describe_largest_weighted_contribution(
    breakdown: dict[str, float],
    weights: dict[str, float],
) -> str:
    """
    Explain which criterion contributed most to the final weighted score.

    This is different from the raw highest score because the user's weights
    affect how much each category matters.
    """
    contributions = {
        key: breakdown[key] * weights[key]
        for key in breakdown
    }

    top_keys = _top_categories(contributions)
    top_labels = [CRITERIA_LABELS.get(key, key) for key in top_keys]

    if len(top_keys) == 4:
        return "Each criterion contributed equally to the final weighted score."

    return (
        "After applying your selected weights, the largest contribution to the "
        f"final score came from {_join_naturally(top_labels)}."
    )


def build_score_explanation(dest: dict[str, Any], prefs: Any) -> list[str]:
    """
    Build explanation bullets for one destination.

    Args:
        dest:
            A scored destination dictionary created by the recommendation engine.
        prefs:
            The user's selected preferences from the sidebar.

    Returns:
        A list of short strings that can be displayed in Streamlit.
    """
    breakdown = _get_breakdown(dest)
    weights = _get_weights(prefs)

    weighted_score = sum(
        breakdown[key] * weights[key]
        for key in breakdown
    )

    return [
        f"Weather score: {breakdown['weather']:.0f}/100 "
        f"(weight: {weights['weather']:.0%})",
        f"Cost score: {breakdown['cost']:.0f}/100 "
        f"(weight: {weights['cost']:.0%})",
        f"Nightlife score: {breakdown['nightlife']:.0f}/100 "
        f"(weight: {weights['nightlife']:.0%})",
        f"Adventure score: {breakdown['adventure']:.0f}/100 "
        f"(weight: {weights['adventure']:.0%})",
        _describe_strongest_raw_score(breakdown),
        _describe_user_priority(weights),
        _describe_largest_weighted_contribution(breakdown, weights),
        f"Estimated weighted score from the breakdown: {weighted_score:.1f}/100.",
        "This is a preference-based recommendation, not an objective universal ranking.",
    ]

def _format_source_label(source: str | None) -> str:
    """
    Clean up technical source labels so they are easier for users to read.
    """
    if not source:
        return "not recorded"

    cleaned = source.replace("_", " ").replace("-", " ")

    replacements = {
        "numbeo scrape": "Numbeo web scrape",
        "numbeo:": "Numbeo web scrape",
        "cheapflights scrape": "Cheapflights web scrape",
        "google flights": "Google Flights estimate",
        "fallback": "fallback estimate",
        "fallback estimate": "fallback estimate",
        "numbeo rent scrape": "Numbeo rent scrape",
        "numbeo rent estimate": "Numbeo rent estimate",
        "not recorded in cache": "not recorded in cache",
    }

    for old, new in replacements.items():
        if old in cleaned.lower():
            return new

    return source


def build_data_source_summary(
    dest: dict[str, Any],
    openweather_available: bool,
    google_maps_available: bool,
) -> list[str]:
    """
    Build a user-facing summary of where the data came from.

    Some parts of the app can identify exact sources, especially costs.
    Other parts, such as weather and venues, only tell this module whether
    an API key is configured. A configured key does not guarantee that the
    live request succeeded, so this explanation avoids claiming certainty.

    Args:
        dest:
            A scored destination dictionary.
        openweather_available:
            Whether an OpenWeather API key is available.
        google_maps_available:
            Whether a Google Maps API key is available.

    Returns:
        A list of short strings for display in Streamlit.
    """
    costs = dest.get("costs", {}) or {}
    scrape_sources = costs.get("scrape_sources", {}) or {}

    if openweather_available:
        weather_source = (
            "OpenWeather API key is configured; results may be live API data, "
            "cached API data, or fallback data if the request failed."
        )
    else:
        weather_source = (
            "Demo/fallback weather data because no OpenWeather API key is configured."
        )

    if google_maps_available:
        venue_source = (
            "Google Maps API key is configured; venues may be live Google Places data, "
            "cached Places data, or fallback data if the request failed."
        )
        geocoding_source = (
            "Google Maps API key is configured; geocoding may use Google Geocoding "
            "or fallback behaviour if unavailable."
        )
    else:
        venue_source = (
            "Demo/fallback venue data because no Google Maps API key is configured."
        )
        geocoding_source = (
            "Demo/fallback geocoding because no Google Maps API key is configured."
        )

    cost_source = costs.get("source", "fallback estimate")
    flight_source = scrape_sources.get("flight", "not recorded in cache")
    meal_source = scrape_sources.get("meal", "not recorded in cache")
    hotel_source = scrape_sources.get("hotel", "not recorded in cache")
    airbnb_estimate_source = scrape_sources.get("airbnb", "not recorded in cache")

    return [
        f"Weather: {weather_source}",
        f"Venues: {venue_source}",
        f"Location/geocoding: {geocoding_source}",
        f"Overall cost estimate: {_format_source_label(cost_source)}.",
        f"Flights: {_format_source_label(flight_source)}.",
        f"Meals: {_format_source_label(meal_source)}.",
        f"Hotels: {_format_source_label(hotel_source)}.",
        f"Airbnb estimate: {_format_source_label(airbnb_estimate_source)}.",
        "Airbnb listings tab: checks cached database listings first; if none are found, the Selenium scraper attempts to fetch live listings.",
        "Reliability note: API-key status only confirms that a key is configured, not that the latest request succeeded.",
        "Reliability note: scraped prices and live API results may change between runs, so figures should be treated as estimates rather than guaranteed booking prices.",
    ]
