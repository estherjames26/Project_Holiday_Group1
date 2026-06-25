# Compare page — run a search on the home page first.

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from src.database.models import init_db
from src.services.visualization_service import build_radar_chart
from src.ui.display import inject_styles, render_hero

init_db()
inject_styles()
render_hero()

st.header("Compare destinations")
st.caption("Pick up to three places from your last search.")

results: list[dict] = st.session_state.get("results", [])

if not results:
    st.warning("Run a search on the home page first.")
    st.stop()

selected = st.multiselect(
    "Destinations",
    options=[d["id"] for d in results],
    default=[d["id"] for d in results[:2]],
    max_selections=3,
    format_func=lambda x: next(d["name"] for d in results if d["id"] == x),
)

if len(selected) < 2:
    st.info("Select at least two destinations.")
    st.stop()

compared = [d for d in results if d["id"] in selected]

st.plotly_chart(build_radar_chart(compared, selected_ids=selected), width="stretch")

cols = st.columns(len(compared))
for col, dest in zip(cols, compared):
    with col:
        st.subheader(dest["name"])
        st.metric("Score", f"{dest['score']}/100")
        st.metric("7-night cost", f"${dest['total_cost_usd']:,.0f}")
        st.metric("Nightlife", dest["nightlife_total"])
        st.metric("Temperature", f"{dest['temp_max_c']}°C")
        insights = dest.get("insights", {})
        st.caption(insights.get("verdict", ""))

st.subheader("Side by side")
rows = []
for dest in compared:
    rows.append({
        "Destination": dest["name"],
        "Score": dest["score"],
        "Weather": dest["breakdown"]["weather"],
        "Cost": dest["breakdown"]["cost"],
        "Nightlife": dest["breakdown"]["nightlife"],
        "Adventure": dest["breakdown"]["adventure"],
        "7-night USD": dest["total_cost_usd"],
        "Venues": dest["nightlife_total"],
    })
st.dataframe(pd.DataFrame(rows).set_index("Destination"), width="stretch")
