"""Folium map builders used by the Streamlit app.

These helpers create overview destination maps, amenity heatmaps, and venue
marker maps from the dictionaries produced by the recommendation engine.
"""

from __future__ import annotations

from typing import Any

import folium
from folium.plugins import HeatMap


def build_destination_map(
    destinations: list[dict[str, Any]],
    selected_id: str | None = None,
) -> folium.Map:
    """Build an overview map with one marker per ranked destination."""
    if not destinations:
        return folium.Map(location=[0, 0], zoom_start=2)

    avg_lat = sum(d["latitude"] for d in destinations) / len(destinations)
    avg_lon = sum(d["longitude"] for d in destinations) / len(destinations)
    fmap = folium.Map(location=[avg_lat, avg_lon], zoom_start=3, tiles="CartoDB positron")

    for dest in destinations:
        # Highlight the selected destination without changing the map data.
        is_selected = dest["id"] == selected_id
        color = "red" if is_selected else "blue"
        radius = 12 if is_selected else 8
        popup_html = (
            f"<b>{dest['name']}</b><br>"
            f"Score: {dest.get('score', 'N/A')}<br>"
            f"Temp: {dest.get('temp_max_c', '?')}°C<br>"
            f"Nightlife: {dest.get('nightlife_total', '?')} venues"
        )
        folium.CircleMarker(
            location=[dest["latitude"], dest["longitude"]],
            radius=radius,
            popup=folium.Popup(popup_html, max_width=250),
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.7,
            tooltip=dest["name"],
        ).add_to(fmap)

    return fmap


def build_amenity_heatmap(places: list[dict[str, Any]], lat: float, lon: float) -> folium.Map:
    """Build a heatmap around one destination from venue/listing coordinates."""
    fmap = folium.Map(location=[lat, lon], zoom_start=13, tiles="CartoDB dark_matter")
    if places:
        heat_data = [[p["latitude"], p["longitude"], p.get("weight", 1.0)] for p in places]
        HeatMap(heat_data, radius=18, blur=22, max_zoom=15).add_to(fmap)

    folium.Marker(
        [lat, lon],
        popup="Destination center",
        icon=folium.Icon(color="green", icon="star"),
    ).add_to(fmap)
    return fmap


def build_amenity_markers_map(
    amenities: dict[str, list[dict[str, Any]]],
    lat: float,
    lon: float,
) -> folium.Map:
    """Build a marker map for grouped amenities around a destination."""
    fmap = folium.Map(location=[lat, lon], zoom_start=13, tiles="OpenStreetMap")
    colors = {"bar": "blue", "restaurant": "green", "night_club": "purple"}

    for category, items in amenities.items():
        for place in items:
            folium.Marker(
                [place["latitude"], place["longitude"]],
                popup=f"<b>{place['name']}</b><br>{place.get('address', '')}",
                tooltip=place["name"],
                icon=folium.Icon(color=colors.get(category, "gray"), icon="info-sign"),
            ).add_to(fmap)

    folium.CircleMarker(
        location=[lat, lon],
        radius=10,
        color="red",
        fill=True,
        popup="Destination",
    ).add_to(fmap)
    return fmap
