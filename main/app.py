# Home page for the Holiday Planner app.
# Run locally: streamlit run app.py

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
from scrape_airbnb import scrape_airbnb_listings
from database import get_airbnb_listings, get_session
from settings import GOOGLE_MAPS_API_KEY, OPENAI_API_KEY, OPENWEATHER_API_KEY, ORIGIN_AIRPORT
from database import init_db
from trip_notes import generate_destination_insights
from ranking import RecommendationEngine, UserPreferences
from explainability import build_data_source_summary, build_score_explanation
from api_google_places import build_google_maps_embed_url
from folium_maps import build_amenity_heatmap, build_amenity_markers_map, build_destination_map
from charts import build_amenity_breakdown_chart, build_bubble_chart, build_decision_matrix, build_radar_chart
from sidebar import PRESETS, apply_preset_sidebar_state, render_origin_airport, render_scoring_weights, search_fingerprint
from page_styling import (
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


def render_sidebar() -> tuple[UserPreferences, str, int, bool]:
    st.sidebar.header("Your trip preferences")

    preset = st.sidebar.selectbox("Quick preset", ["Custom"] + list(PRESETS.keys()))
    preset_prefs = PRESETS.get(preset) if preset != "Custom" else None
    apply_preset_sidebar_state(preset)

    origin, origin_valid = render_origin_airport(ORIGIN_AIRPORT)
    min_temp = st.sidebar.slider(
        "Min temperature (°C)", 20, 35,
        int(preset_prefs.min_temp_c) if preset_prefs else 26,
        key="sidebar_min_temp",
    )
    max_temp_default = int(preset_prefs.max_temp_c) if preset_prefs else 34
    max_temp = st.sidebar.slider(
        "Max temperature (°C)",
        min_temp,
        40,
        max(max_temp_default, min_temp),
        key="sidebar_max_temp",
    )
    max_wind = st.sidebar.slider(
        "Max wind (m/s)", 5.0, 20.0,
        preset_prefs.max_wind_ms if preset_prefs else 12.0, 0.5,
        key="sidebar_max_wind",
    )
    max_budget = st.sidebar.slider(
        "Max budget (USD, 7 nights)", 1000, 8000,
        int(preset_prefs.max_budget_usd) if preset_prefs else 3500, 100,
        key="sidebar_max_budget",
    )
    min_nightlife = st.sidebar.slider(
        "Min nightlife venues nearby", 1, 15,
        preset_prefs.min_nightlife_venues if preset_prefs else 3,
        key="sidebar_min_nightlife",
    )
    top_n = st.sidebar.slider("How many results", 3, 10, 5, key="sidebar_top_n")

    w_weather, w_cost, w_nightlife, w_adventure = render_scoring_weights(preset_prefs, preset)

    default_tags = list(preset_prefs.preferred_tags) if preset_prefs and preset_prefs.preferred_tags else ["diving", "culture"]
    tags = st.sidebar.multiselect(
        "What you are into",
        ["surfing", "diving", "hiking", "culture", "snorkeling", "kayaking", "food"],
        default=default_tags,
        key="sidebar_tags",
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
    return prefs, origin, top_n, origin_valid


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

    prefs_for_explanation = st.session_state.get("last_prefs", UserPreferences())

    with st.expander("Why this destination?"):
        for line in build_score_explanation(dest, prefs_for_explanation):
            st.markdown(f"- {line}")

    with st.expander("Data sources and reliability"):
        for line in build_data_source_summary(
            dest,
            bool(OPENWEATHER_API_KEY),
            bool(GOOGLE_MAPS_API_KEY),
        ):
            st.markdown(f"- {line}")

    render_insight_cards(dest)
    st.write(dest["description"])

    # Fetch Airbnb listings early so they can be placed on the main map
    dest_id = dest["id"]
    db = get_session()
    try:
        listings = get_airbnb_listings(db, dest_id)
    finally:
        db.close()

    if not listings:
        with st.spinner("Fetching Airbnb listings..."):
            _, listings = scrape_airbnb_listings(
                dest["name"],
                dest["country"],
                destination_id=dest_id,
                limit=6,
                dest_lat=dest["latitude"],
                dest_lng=dest["longitude"],
            )

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Map", "Weather", "Costs","Airbnb listings", "Venues"])

    with tab1:
        all_places = dest["amenities"]["bars"] + dest["amenities"]["restaurants"] + dest["amenities"]["night_clubs"]
        heat_places = [{"latitude": p["latitude"], "longitude": p["longitude"], "weight": p.get("weight", 1)} for p in all_places]
        c1, c2 = st.columns(2)
        with c1:
            st_folium(build_amenity_heatmap(heat_places, dest["latitude"], dest["longitude"]), width=480, height=380, key=f"heatmap_{dest['id']}")
        with c2:
            import folium
            m = folium.Map(location=[dest["latitude"], dest["longitude"]], zoom_start=13, tiles="CartoDB positron")
            
            # Destination center marker
            folium.Marker(
                location=[dest["latitude"], dest["longitude"]],
                popup=dest["name"],
                icon=folium.Icon(color="blue", icon="info-sign")
            ).add_to(m)
            
            # Add Venues to the map
            for b in dest["amenities"]["bars"]:
                folium.Marker(
                    location=[b["latitude"], b["longitude"]],
                    popup=f"🍸 {b['name']} ({b.get('rating', 'N/A')}⭐)",
                    icon=folium.Icon(color="orange", icon="glass", prefix="fa")
                ).add_to(m)
            for r in dest["amenities"]["restaurants"]:
                folium.Marker(
                    location=[r["latitude"], r["longitude"]],
                    popup=f"🍴 {r['name']} ({r.get('rating', 'N/A')}⭐)",
                    icon=folium.Icon(color="green", icon="cutlery", prefix="fa")
                ).add_to(m)
            for nc in dest["amenities"]["night_clubs"]:
                folium.Marker(
                    location=[nc["latitude"], nc["longitude"]],
                    popup=f"💃 {nc['name']} ({nc.get('rating', 'N/A')}⭐)",
                    icon=folium.Icon(color="purple", icon="music", prefix="fa")
                ).add_to(m)
                
            # Add Airbnb listings as red pins to the same venue map
            if listings:
                sym = listings[0].get("currency_symbol", "£")
                for l in listings:
                    if l.get("latitude") and l.get("longitude") and l["latitude"] != 0.0 and l["longitude"] != 0.0:
                        price_label = f"{sym}{l['price_nightly']:.0f}/night" if l.get("price_nightly") else ""
                        rating_label = f" · ⭐{l['rating']}" if l.get("rating") else ""
                        url = l.get("listing_url", "")
                        folium.Marker(
                            location=[l["latitude"], l["longitude"]],
                            popup=folium.Popup(
                                f'<b><a href="{url}" target="_blank">{l["name"]}</a></b>'
                                f"<br>{price_label}{rating_label}",
                                max_width=220,
                            ),
                            tooltip=f"{l['name']} — {price_label}",
                            icon=folium.Icon(color="red", icon="home", prefix="fa"),
                        ).add_to(m)
                        
            st_folium(m, width=480, height=380, key=f"venue_map_{dest['id']}")

        embed_url = build_google_maps_embed_url(dest["latitude"], dest["longitude"], GOOGLE_MAPS_API_KEY)
        if embed_url:
            st.iframe(embed_url, height=320)

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
        st.caption(
            f"Estimated 7-night total: ${c['total_7_night_usd']:,.2f} "
            f"(return flight from **{c.get('origin_airport', '—')}**: ${c['flight_usd']:,.0f})"
        )
        flight_detail = (c.get("scrape_sources") or {}).get("flight", c.get("source", ""))
        if flight_detail:
            st.caption(f"Flight estimate source: {flight_detail}")


    with tab4:
        if listings:
            sym = listings[0].get("currency_symbol", "£")
            valid_prices = [r["price_nightly"] for r in listings if r["price_nightly"]]
            avg = round(sum(valid_prices) / len(valid_prices), 2) if valid_prices else 0
            st.caption(f"{len(listings)} listings · avg {sym}{avg}/night")

            for listing in listings:
                img_col, info_col = st.columns([1, 3])
                with img_col:
                    if listing.get("image_url"):
                        st.image(listing["image_url"], width="stretch")
                    else:
                        st.markdown("🏠")
                with info_col:
                    name = listing.get("name", "Unknown listing")
                    url = listing.get("listing_url")
                    st.markdown(f"**[{name}]({url})**" if url else f"**{name}**")
                    if listing.get("description"):
                        st.caption(listing["description"])
                    meta_parts = []
                    if listing.get("bedrooms"):
                        meta_parts.append(f"🛏 {listing['bedrooms']}")
                    if listing.get("rating"):
                        meta_parts.append(f"⭐ {listing['rating']}")
                    if meta_parts:
                        st.markdown("  ·  ".join(meta_parts))
                    if listing.get("price_nightly"):
                        st.markdown(f"**{sym}{listing['price_nightly']:.0f} / night**")
                    if url:
                        st.link_button("View on Airbnb →", url)
                st.divider()
        else:
            st.info("No Airbnb listings found for this destination.")

    with tab5:
        st.markdown("### 📍 Nearby Venues")
        amenities = dest.get("amenities", {})
        categories = [
            ("bars", "🍸 Bars & Pubs"),
            ("restaurants", "🍴 Restaurants & Eateries"),
            ("night_clubs", "💃 Nightclubs & Lounges")
        ]
        for key, label in categories:
            st.markdown(f"#### {label}")
            places = amenities.get(key, [])
            if not places:
                st.info(f"No {key.replace('_', ' ')} found nearby.")
            else:
                df_places = pd.DataFrame([
                    {
                        "Name": p.get("name", "Unknown"),
                        "Rating": f"⭐ {p.get('rating')}" if p.get("rating") else "N/A",
                        "Address": p.get("address", "N/A")
                    }
                    for p in places
                ])
                st.dataframe(df_places, hide_index=True, use_container_width=True)

def main() -> None:
    render_hero()
    prefs, origin, top_n, origin_valid = render_sidebar()
    render_status_pills(bool(OPENWEATHER_API_KEY), bool(GOOGLE_MAPS_API_KEY), bool(OPENAI_API_KEY), origin)

    find_clicked = st.sidebar.button(
        "Find destinations",
        type="primary",
        width="stretch",
        disabled=not origin_valid,
    )
    if not origin_valid:
        st.sidebar.caption("Choose a valid departure airport to search.")

    if find_clicked:
        with st.spinner(f"Fetching weather and venue data (flights from {origin})..."):
            engine = get_engine()
            results, summary, portfolio = engine.recommend(prefs, origin, top_n)
            st.session_state["results"] = results
            st.session_state["summary"] = summary
            st.session_state["portfolio"] = portfolio
            st.session_state["last_prefs"] = prefs
            st.session_state["all_map"] = engine.get_all_for_map(prefs, origin)
            st.session_state["search_origin"] = origin
            st.session_state["search_fingerprint"] = search_fingerprint(prefs, origin, top_n)

    results: list[dict] = st.session_state.get("results", [])
    summary: str = st.session_state.get("summary", "")
    portfolio: list[str] = st.session_state.get("portfolio", [])

    if results:
        current_fp = search_fingerprint(prefs, origin, top_n)
        if st.session_state.get("search_fingerprint") != current_fp:
            st.warning(
                "Your sidebar settings have changed since the last search "
                "(airport, budget, weights, tags, etc.). "
                "Click **Find destinations** again to refresh rankings and prices."
            )
        elif st.session_state.get("search_origin") and st.session_state["search_origin"] != origin:
            st.info(f"Showing results for flights from **{st.session_state['search_origin']}**. Re-search to update for **{origin}**.")

    if not results:
        st.info("Set your preferences in the sidebar, then click **Find destinations**.")
        st.markdown(
            "We rank **tropical destinations** discovered via Google Places using live weather, "
            "nearby bars and clubs, and **web-scraped** trip costs (Numbeo + Cheapflights)."
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
