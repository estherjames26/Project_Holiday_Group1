# Main Streamlit page — run with: streamlit run app.py

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from src.config import GOOGLE_MAPS_API_KEY, OPENAI_API_KEY, OPENWEATHER_API_KEY, ORIGIN_AIRPORT
from src.database.models import init_db
from src.engine.insights import generate_destination_insights
from src.engine.recommender import RecommendationEngine, UserPreferences
from src.services.google_places_service import build_google_maps_embed_url
from src.services.maps_service import (
    build_amenity_heatmap,
    build_amenity_markers_map,
    build_destination_map,
)
from src.services.visualization_service import (
    build_amenity_breakdown_chart,
    build_bubble_chart,
    build_decision_matrix,
    build_radar_chart,
)
from src.ui.components import PRESETS, normalize_weights
from src.ui.display import (
    inject_styles,
    render_dest_card,
    render_hero,
    render_status_pills,
    render_summary_box,
    render_takeaway,
)

st.set_page_config(
    page_title="Holiday Planner",
    page_icon="🌴",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()
inject_styles()



@st.cache_resource
def get_engine() -> RecommendationEngine:
    return RecommendationEngine()


def render_sidebar() -> tuple[UserPreferences, str, int, str]:
    st.sidebar.header("Your trip preferences")
 
    preset = st.sidebar.selectbox("Quick preset", ["Custom"] + list(PRESETS.keys()))
    preset_prefs = PRESETS.get(preset) if preset != "Custom" else None
 
    # Region picker — new addition
    from src.services.discovery_service import REGIONS
    region = st.sidebar.selectbox("Region", REGIONS, index=0)
 
    origin = st.sidebar.text_input("Flying from (airport code)", value=ORIGIN_AIRPORT).upper()
    min_temp = st.sidebar.slider("Min temperature (°C)", 20, 35, int(preset_prefs.min_temp_c) if preset_prefs else 26)
    max_temp = st.sidebar.slider("Max temperature (°C)", 25, 40, int(preset_prefs.max_temp_c) if preset_prefs else 34)
    max_wind = st.sidebar.slider("Max wind (m/s)", 5.0, 20.0, preset_prefs.max_wind_ms if preset_prefs else 12.0, 0.5)
    max_budget = st.sidebar.slider(
        "Max budget (USD, 7 nights)", 1000, 8000,
        int(preset_prefs.max_budget_usd) if preset_prefs else 3500, 100,
    )
    min_nightlife = st.sidebar.slider("Min nightlife venues nearby", 1, 15, preset_prefs.min_nightlife_venues if preset_prefs else 3)
    top_n = st.sidebar.slider("How many results", 3, 10, 5)
 
    with st.sidebar.expander("Scoring weights", expanded=False):
        w_weather = st.slider("Weather", 0.0, 1.0, preset_prefs.weather_weight if preset_prefs else 0.25, 0.05)
        w_cost = st.slider("Cost", 0.0, 1.0, preset_prefs.cost_weight if preset_prefs else 0.25, 0.05)
        w_nightlife = st.slider("Nightlife", 0.0, 1.0, preset_prefs.nightlife_weight if preset_prefs else 0.30, 0.05)
        w_adventure = st.slider("Adventure", 0.0, 1.0, preset_prefs.adventure_weight if preset_prefs else 0.20, 0.05)
        w_weather, w_cost, w_nightlife, w_adventure = normalize_weights(w_weather, w_cost, w_nightlife, w_adventure)
        st.caption(f"Weights normalised to 100%: weather {w_weather:.0%}, cost {w_cost:.0%}, nightlife {w_nightlife:.0%}, adventure {w_adventure:.0%}")
 
    default_tags = list(preset_prefs.preferred_tags) if preset_prefs and preset_prefs.preferred_tags else ["diving", "culture"]
    tags = st.sidebar.multiselect(
        "What you are into",
        ["surfing", "diving", "hiking", "culture", "snorkeling", "kayaking", "food"],
        default=default_tags,
    )
 
    prefs = UserPreferences(
        min_temp_c=float(min_temp),
        max_temp_c=float(max_temp),
        max_wind_ms=float(max_wind),
        max_budget_usd=float(max_budget),
        min_nightlife_venues=int(min_nightlife),
        weather_weight=w_weather,
        cost_weight=w_cost,
        nightlife_weight=w_nightlife,
        adventure_weight=w_adventure,
        preferred_tags=tags,
    )
    return prefs, origin, top_n, region  # now returns region too


def export_results_csv(results: list[dict]) -> bytes:
    rows = []
    for i, d in enumerate(results):
        rows.append({
            "Rank": i + 1,
            "Destination": d["name"],
            "Country": d["country"],
            "Score": d["score"],
            "Max Temp C": d["temp_max_c"],
            "7-Night USD": d["total_cost_usd"],
            "Nightlife Venues": d["nightlife_total"],
            "Verdict": d.get("insights", {}).get("verdict", ""),
        })
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


def render_insight_cards(dest: dict) -> None:
    insights = dest.get("insights") or generate_destination_insights(dest, [dest])
    st.caption(insights["verdict"])
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Good points**")
        for pro in insights.get("pros", []):
            st.markdown(f'<div class="insight-card">{pro}</div>', unsafe_allow_html=True)
    with c2:
        st.markdown("**Watch out for**")
        for con in insights.get("cons", []):
            st.markdown(f'<div class="con-card">{con}</div>', unsafe_allow_html=True)


def render_forecast_chart(dest: dict) -> None:
    forecast = dest["weather"].get("forecast_days", [])
    if not forecast:
        return
    df = pd.DataFrame(forecast)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["date"], y=df["temp_max"], name="Max °C", mode="lines+markers"))
    fig.add_trace(go.Scatter(x=df["date"], y=df["temp_min"], name="Min °C", mode="lines+markers"))
    fig.update_layout(title=f"5-day forecast — {dest['name']}", height=320, margin=dict(t=40, b=20))
    st.plotly_chart(fig, width="stretch")


def render_destination_detail(dest: dict) -> None:
    st.markdown(f'<p class="section-title">{dest["name"]}</p>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Score", f"{dest['score']}/100")
    c2.metric("Temperature", f"{dest['temp_max_c']}°C")
    c3.metric("7-night cost", f"${dest['total_cost_usd']:,.0f}")
    c4.metric("Nightlife nearby", dest["nightlife_total"])

    render_insight_cards(dest)
    st.write(dest["description"])

    tab1, tab2, tab3, tab4 = st.tabs(["Map", "Weather", "Costs", "Venues"])

    with tab1:
        all_places = dest["amenities"]["bars"] + dest["amenities"]["restaurants"] + dest["amenities"]["night_clubs"]
        heat_places = [{"latitude": p["latitude"], "longitude": p["longitude"], "weight": p.get("weight", 1)} for p in all_places]
        c1, c2 = st.columns(2)
        with c1:
            st_folium(build_amenity_heatmap(heat_places, dest["latitude"], dest["longitude"]), width=480, height=380)
        with c2:
            st_folium(build_amenity_markers_map(
                {"bar": dest["amenities"]["bars"], "restaurant": dest["amenities"]["restaurants"],
                 "night_club": dest["amenities"]["night_clubs"]},
                dest["latitude"], dest["longitude"],
            ), width=480, height=380)
        embed_url = build_google_maps_embed_url(dest["latitude"], dest["longitude"], GOOGLE_MAPS_API_KEY)
        if embed_url:
            st.components.v1.iframe(embed_url, height=320)

    with tab2:
        render_forecast_chart(dest)
        w = dest["weather"]
        st.caption(f"Humidity {w['humidity']}% · Cloud cover {w['cloudiness']}% · Wind {w['wind_speed_ms']} m/s")

    with tab3:
        c = dest["costs"]
        st.dataframe(pd.DataFrame({
            "Item": ["Return flight", "Hotel per night", "Airbnb per night", "Meal cost index"],
            "USD": [c["flight_usd"], c["hotel_nightly_usd"], c["airbnb_nightly_usd"], c["meal_index"]],
        }), hide_index=True, width="stretch")
        st.caption(f"Estimated 7-night total: ${c['total_7_night_usd']:,.2f} (source: {c['source']})")

    with tab4:
        st.plotly_chart(build_amenity_breakdown_chart(dest), width="stretch")
        for label, key in [("Bars", "bars"), ("Restaurants", "restaurants"), ("Nightclubs", "night_clubs")]:
            items = dest["amenities"][key]
            if items:
                with st.expander(f"{label} ({len(items)})"):
                    st.dataframe(pd.DataFrame(items)[["name", "rating", "address"]], hide_index=True)


def main() -> None:
    render_hero()
    render_status_pills(bool(OPENWEATHER_API_KEY), bool(GOOGLE_MAPS_API_KEY), bool(OPENAI_API_KEY), ORIGIN_AIRPORT)
    prefs, origin, top_n, region = render_sidebar()

    if st.sidebar.button("Find destinations", type="primary", use_container_width=True):
        with st.spinner("Discovering and scoring destinations worldwide..."):
            engine = get_engine()
            results, summary, portfolio = engine.recommend(prefs, origin, top_n, region=region)
            st.session_state["results"] = results
            st.session_state["summary"] = summary
            st.session_state["portfolio"] = portfolio
            st.session_state["all_map"] = engine.get_all_for_map(prefs, origin, region=region)
    results: list[dict] = st.session_state.get("results", [])
    summary: str = st.session_state.get("summary", "")
    portfolio: list[str] = st.session_state.get("portfolio", [])

    if not results:
        st.info("Set your preferences in the sidebar, then click **Find destinations**.")
        st.markdown(
            "We rank **10 tropical spots** using weather (live or demo), "
            "nearby bars and clubs from Google, and rough trip costs."
        )
        return

    render_summary_box(summary)
    if portfolio:
        st.markdown('<p class="section-title">At a glance</p>', unsafe_allow_html=True)
        for insight in portfolio:
            render_takeaway(insight)

    st.download_button("Download CSV", data=export_results_csv(results), file_name="holiday_recommendations.csv")

    st.markdown('<p class="section-title">Your top picks</p>', unsafe_allow_html=True)
    for i, dest in enumerate(results):
        render_dest_card(i + 1, dest)

    with st.expander("Full results table", expanded=False):
        st.dataframe(pd.DataFrame([
            {
                "Rank": i + 1,
                "Destination": d["name"],
                "Country": d["country"],
                "Score": d["score"],
                "Max °C": d["temp_max_c"],
                "7-night USD": d["total_cost_usd"],
                "Nightlife": d["nightlife_total"],
            }
            for i, d in enumerate(results)
        ]), hide_index=True, width="stretch")

    st.markdown('<p class="section-title">Map</p>', unsafe_allow_html=True)
    st_folium(build_destination_map(st.session_state.get("all_map", results)), width=None, height=400)

    with st.expander("Charts and comparisons", expanded=False):
        v1, v2 = st.columns(2)
        with v1:
            st.plotly_chart(build_radar_chart(results), width="stretch")
        with v2:
            st.plotly_chart(build_bubble_chart(results), width="stretch")
        st.plotly_chart(build_decision_matrix(results), width="stretch")

        df = pd.DataFrame([
            {"Destination": d["name"], "Weather": d["breakdown"]["weather"], "Cost": d["breakdown"]["cost"],
             "Nightlife": d["breakdown"]["nightlife"], "Adventure": d["breakdown"]["adventure"]}
            for d in results
        ])
        melted = df.melt(id_vars="Destination", var_name="Criterion", value_name="Score")
        st.plotly_chart(px.bar(melted, x="Destination", y="Score", color="Criterion", barmode="group"), width="stretch")

    st.markdown('<p class="section-title">Explore one destination</p>', unsafe_allow_html=True)
    selected = st.selectbox(
        "Choose a place",
        options=[d["id"] for d in results],
        format_func=lambda x: next(d["name"] for d in results if d["id"] == x),
        label_visibility="collapsed",
    )
    render_destination_detail(next(d for d in results if d["id"] == selected))


if __name__ == "__main__":
    main()
