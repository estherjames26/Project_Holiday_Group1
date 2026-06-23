# Shows what's in the SQLite database — cache counts and past searches.

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import streamlit as st

from src.database.models import get_cache_stats, get_recommendation_history, get_session, init_db
from src.ui.display import inject_styles, render_hero

init_db()
inject_styles()
render_hero()

st.header("Analytics & history")
st.markdown("What's stored locally in `data/holiday_planner.db`.")

session = get_session()
try:
    stats = get_cache_stats(session)
    history = get_recommendation_history(session, limit=25)
finally:
    session.close()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Weather cache", stats["weather_entries"])
c2.metric("Places cache", stats["places_entries"])
c3.metric("Cost cache", stats["cost_entries"])
c4.metric("Past searches", stats["recommendation_runs"])

if history:
    df = pd.DataFrame(history)
    st.subheader("Recent searches")
    st.dataframe(
        df[["id", "created_at", "origin_airport", "top_destination", "top_score", "result_count"]],
        hide_index=True,
        use_container_width=True,
    )

    if len(df) >= 2:
        df["created_at"] = pd.to_datetime(df["created_at"])
        fig = px.line(
            df.sort_values("created_at"), x="created_at", y="top_score",
            markers=True, title="Top score over time",
        )
        st.plotly_chart(fig, use_container_width=True)

    top_counts = df["top_destination"].value_counts()
    fig2 = px.bar(
        x=top_counts.index, y=top_counts.values,
        labels={"x": "Destination", "y": "Times ranked #1"},
        title="Who wins most often",
    )
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("No searches logged yet — run one on the home page.")

st.subheader("Tables")
st.markdown("""
| Table | What's in it |
|---|---|
| `weather_cache` | OpenWeather responses |
| `places_cache` | Google Places responses |
| `cost_cache` | Scraped/estimated costs |
| `recommendation_log` | Your past searches |
""")
