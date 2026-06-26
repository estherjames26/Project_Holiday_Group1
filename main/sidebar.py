# Sidebar presets (Party focus, Budget trip, etc.) and weight allocation.

from __future__ import annotations

import streamlit as st

from ranking import UserPreferences
from settings import COMMON_ORIGIN_AIRPORTS, ORIGIN_AIRPORT

TOTAL_SCORE_POINTS = 100

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


def apply_preset_sidebar_state(preset_name: str) -> None:
    """Reset sidebar widget state when the user picks a different preset."""
    if preset_name == st.session_state.get("_sidebar_preset"):
        return
    st.session_state["_sidebar_preset"] = preset_name
    for key in (
        "sidebar_min_temp",
        "sidebar_max_temp",
        "sidebar_max_wind",
        "sidebar_max_budget",
        "sidebar_min_nightlife",
        "sidebar_top_n",
        "sidebar_tags",
        "score_weight_weather",
        "score_weight_cost",
        "score_weight_nightlife",
    ):
        st.session_state.pop(key, None)


def search_fingerprint(prefs: UserPreferences, origin: str, top_n: int) -> str:
    """Hash of all inputs that affect ranking — detect stale on-screen results."""
    import json

    return json.dumps(
        {
            "origin": origin.upper().strip()[:3],
            "top_n": top_n,
            "min_temp_c": prefs.min_temp_c,
            "max_temp_c": prefs.max_temp_c,
            "max_wind_ms": prefs.max_wind_ms,
            "max_budget_usd": prefs.max_budget_usd,
            "min_nightlife_venues": prefs.min_nightlife_venues,
            "weather_weight": round(prefs.weather_weight, 4),
            "cost_weight": round(prefs.cost_weight, 4),
            "nightlife_weight": round(prefs.nightlife_weight, 4),
            "adventure_weight": round(prefs.adventure_weight, 4),
            "preferred_tags": sorted(prefs.preferred_tags),
        },
        sort_keys=True,
    )


def normalize_weights(w_w: float, w_c: float, w_n: float, w_a: float) -> tuple[float, float, float, float]:
    """Re-export for backwards compatibility — logic lives in ranking.py."""
    from ranking import normalize_weights as _nw
    return _nw(w_w, w_c, w_n, w_a)


def _preset_point_defaults(preset_prefs: UserPreferences | None) -> tuple[int, int, int, int]:
    prefs = preset_prefs or UserPreferences()
    raw = [
        int(round(prefs.weather_weight * TOTAL_SCORE_POINTS)),
        int(round(prefs.cost_weight * TOTAL_SCORE_POINTS)),
        int(round(prefs.nightlife_weight * TOTAL_SCORE_POINTS)),
        int(round(prefs.adventure_weight * TOTAL_SCORE_POINTS)),
    ]
    diff = TOTAL_SCORE_POINTS - sum(raw)
    raw[0] = max(0, min(TOTAL_SCORE_POINTS, raw[0] + diff))
    return raw[0], raw[1], raw[2], raw[3]


def is_valid_iata(code: str) -> bool:
    """True for a 3-letter alphabetic IATA airport code."""
    cleaned = (code or "").upper().strip()
    return len(cleaned) == 3 and cleaned.isalpha()


def _point_slider(label: str, max_points: int, default: int, key: str) -> int:
    """Slider for 0..max_points; skips widget when no points remain (Streamlit needs min < max)."""
    default = max(0, min(default, max_points))
    if max_points <= 0:
        st.session_state[key] = 0
        st.caption(f"{label}: **0** pts (no points left)")
        return 0
    if key in st.session_state and st.session_state[key] > max_points:
        st.session_state[key] = max_points
    step = 5 if max_points >= 5 else 1
    return st.slider(label, 0, max_points, default, step, key=key)


def _reset_weight_sliders_if_preset_changed(preset_name: str) -> None:
    if preset_name != st.session_state.get("_weight_preset"):
        for key in ("score_weight_weather", "score_weight_cost", "score_weight_nightlife"):
            st.session_state.pop(key, None)
        st.session_state["_weight_preset"] = preset_name


def render_scoring_weights(
    preset_prefs: UserPreferences | None,
    preset_name: str = "Custom",
) -> tuple[float, float, float, float]:
    """
    Allocate exactly 100 points across weather, cost, nightlife, and adventure.
    Sliders are capped so the total can never exceed 100.
    """
    w_default, c_default, n_default, _a_default = _preset_point_defaults(preset_prefs)

    with st.sidebar.expander("Scoring weights (100 points total)", expanded=False):
        st.caption(
            "Split **100 points** across the four criteria. "
            "Adventure gets whatever is left — you cannot exceed 100 in total."
        )

        w_weather = _point_slider("Weather", TOTAL_SCORE_POINTS, w_default, "score_weight_weather")
        max_cost = TOTAL_SCORE_POINTS - w_weather
        w_cost = _point_slider("Cost", max_cost, c_default, "score_weight_cost")
        max_nightlife = TOTAL_SCORE_POINTS - w_weather - w_cost
        w_nightlife = _point_slider("Nightlife", max_nightlife, n_default, "score_weight_nightlife")
        w_adventure = TOTAL_SCORE_POINTS - w_weather - w_cost - w_nightlife

        st.metric("Adventure (auto)", f"{w_adventure} pts")
        total = w_weather + w_cost + w_nightlife + w_adventure
        st.caption(
            f"Total: **{total}/{TOTAL_SCORE_POINTS}** · "
            f"Weather {w_weather}% · Cost {w_cost}% · "
            f"Nightlife {w_nightlife}% · Adventure {w_adventure}%"
        )

    return (
        w_weather / TOTAL_SCORE_POINTS,
        w_cost / TOTAL_SCORE_POINTS,
        w_nightlife / TOTAL_SCORE_POINTS,
        w_adventure / TOTAL_SCORE_POINTS,
    )


def render_origin_airport(default_code: str | None = None) -> tuple[str, bool]:
    """Pick a common departure airport or enter a custom 3-letter IATA code."""
    default_code = (default_code or ORIGIN_AIRPORT).upper().strip()[:3]
    labels = list(COMMON_ORIGIN_AIRPORTS.keys())

    default_label = next(
        (label for label, code in COMMON_ORIGIN_AIRPORTS.items() if code == default_code),
        None,
    )
    if default_label is None:
        default_label = "Custom airport code…"

    choice = st.sidebar.selectbox(
        "Flying from",
        labels,
        index=labels.index(default_label),
        help="Used for flight cost estimates — passed to Google Flights and logged with each search.",
    )

    if COMMON_ORIGIN_AIRPORTS[choice] == "__custom__":
        origin = st.sidebar.text_input(
            "Airport code (IATA)",
            value=default_code if default_label == "Custom airport code…" else "",
            max_chars=3,
            placeholder="e.g. BRS",
        ).upper().strip()[:3]
    else:
        origin = COMMON_ORIGIN_AIRPORTS[choice]

    valid = is_valid_iata(origin)
    if valid:
        st.sidebar.caption(f"Flight costs will be estimated from **{origin}**.")
    else:
        st.sidebar.warning("Enter a valid 3-letter IATA code (e.g. LHR, JFK, MAN).")

    return origin, valid
