# Plotly charts for comparing destinations.

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def build_radar_chart(destinations: list[dict[str, Any]], selected_ids: list[str] | None = None) -> go.Figure:
    criteria = ["Weather", "Cost", "Nightlife", "Adventure"]
    fig = go.Figure()

    for dest in destinations:
        if selected_ids and dest["id"] not in selected_ids:
            continue
        values = [
            dest["breakdown"]["weather"],
            dest["breakdown"]["cost"],
            dest["breakdown"]["nightlife"],
            dest["breakdown"]["adventure"],
        ]
        values_closed = values + [values[0]]
        labels_closed = criteria + [criteria[0]]
        fig.add_trace(
            go.Scatterpolar(
                r=values_closed,
                theta=labels_closed,
                fill="toself",
                name=dest["name"],
                opacity=0.65,
            )
        )

    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        title="Score breakdown (radar)",
        showlegend=True,
        height=450,
    )
    return fig


def build_decision_matrix(destinations: list[dict[str, Any]]) -> go.Figure:
    if not destinations:
        return go.Figure()

    rows = []
    for dest in destinations:
        rows.append({
            "Destination": dest["name"],
            "Weather": dest["breakdown"]["weather"],
            "Cost Value": dest["breakdown"]["cost"],
            "Nightlife": dest["breakdown"]["nightlife"],
            "Adventure": dest["breakdown"]["adventure"],
            "Overall": dest["score"],
        })

    df = pd.DataFrame(rows).set_index("Destination").T
    fig = px.imshow(
        df,
        labels=dict(x="Destination", y="Criterion", color="Score"),
        title="Scores heatmap (0–100)",
        color_continuous_scale="Tealgrn",
        aspect="auto",
        text_auto=".0f",
    )
    fig.update_layout(height=380)
    return fig


def build_bubble_chart(destinations: list[dict[str, Any]]) -> go.Figure:
    df = pd.DataFrame([
        {
            "Destination": d["name"],
            "Score": d["score"],
            "7-Night Cost (USD)": d["total_cost_usd"],
            "Nightlife Venues": d["nightlife_total"],
            "Max Temp (°C)": d["temp_max_c"],
        }
        for d in destinations
    ])
    fig = px.scatter(
        df,
        x="7-Night Cost (USD)",
        y="Score",
        size="Nightlife Venues",
        color="Max Temp (°C)",
        hover_name="Destination",
        title="Cost vs score (bubble size = nightlife venues)",
        color_continuous_scale="Sunset",
        size_max=40,
    )
    fig.update_layout(height=420)
    return fig


def build_amenity_breakdown_chart(dest: dict[str, Any]) -> go.Figure:
    a = dest["amenities"]
    labels = ["Bars", "Restaurants", "Nightclubs"]
    values = [len(a["bars"]), len(a["restaurants"]), len(a["night_clubs"])]
    fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.45)])
    fig.update_layout(title=f"Bars, restaurants & clubs — {dest['name']}", height=320)
    return fig
