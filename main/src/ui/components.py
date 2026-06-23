# Sidebar presets and weight helpers.

from __future__ import annotations

from src.engine.recommender import UserPreferences

PRESETS: dict[str, UserPreferences] = {
    "Party focus": UserPreferences(
        nightlife_weight=0.45,
        weather_weight=0.15,
        cost_weight=0.15,
        adventure_weight=0.25,
        min_nightlife_venues=5,
    ),
    "Budget trip": UserPreferences(
        cost_weight=0.40,
        adventure_weight=0.30,
        weather_weight=0.15,
        nightlife_weight=0.15,
        max_budget_usd=2500.0,
    ),
    "Balanced": UserPreferences(
        weather_weight=0.25,
        cost_weight=0.25,
        nightlife_weight=0.25,
        adventure_weight=0.25,
    ),
    "Adventure first": UserPreferences(
        adventure_weight=0.40,
        weather_weight=0.25,
        cost_weight=0.15,
        nightlife_weight=0.20,
        preferred_tags=["surfing", "diving", "hiking", "snorkeling"],
    ),
}


def normalize_weights(w_w: float, w_c: float, w_n: float, w_a: float) -> tuple[float, float, float, float]:
    total = w_w + w_c + w_n + w_a
    if total <= 0:
        return 0.25, 0.25, 0.25, 0.25
    return w_w / total, w_c / total, w_n / total, w_a / total
