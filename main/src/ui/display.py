# UI bits — kept separate from the engine so Streamlit reloads don't break imports.

from __future__ import annotations

import streamlit as st

CUSTOM_CSS = """
<style>
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1100px; }
    div[data-testid="stSidebar"] { background-color: #f8fafc; }

    .hero {
        background: linear-gradient(135deg, #0d9488 0%, #0284c7 55%, #0369a1 100%);
        padding: 2rem 2.2rem;
        border-radius: 16px;
        color: white;
        margin-bottom: 1.25rem;
        box-shadow: 0 8px 24px rgba(13, 148, 136, 0.18);
    }
    .hero h1 { color: white !important; margin: 0 0 0.35rem 0; font-size: 2rem; }
    .hero p { color: #e0f2fe; margin: 0; font-size: 1.05rem; }

    .status-row {
        display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1.5rem;
    }
    .status-pill {
        background: #f1f5f9; color: #334155; padding: 0.35rem 0.75rem;
        border-radius: 999px; font-size: 0.85rem; border: 1px solid #e2e8f0;
    }

    .summary-box {
        background: #f0fdfa; border: 1px solid #99f6e4; border-radius: 12px;
        padding: 1rem 1.25rem; margin-bottom: 1rem; color: #134e4a;
    }
    .takeaway-box {
        background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
        padding: 0.85rem 1.1rem; margin-bottom: 0.5rem; color: #334155;
        line-height: 1.5;
    }

    .dest-card {
        background: white; border: 1px solid #e2e8f0; border-radius: 14px;
        padding: 1.1rem 1.2rem; margin-bottom: 0.75rem;
        box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
    }
    .dest-card h3 { margin: 0 0 0.25rem 0; color: #0f172a; font-size: 1.15rem; }
    .dest-card .meta { color: #64748b; font-size: 0.9rem; margin-bottom: 0.6rem; }
    .dest-card .score {
        display: inline-block; background: #ccfbf1; color: #0f766e;
        padding: 0.2rem 0.55rem; border-radius: 6px; font-weight: 600; font-size: 0.85rem;
    }

    .insight-card {
        background: #f0fdf4; border-left: 3px solid #22c55e;
        padding: 0.55rem 0.85rem; border-radius: 0 8px 8px 0; margin: 0.3rem 0;
        font-size: 0.92rem; color: #166534;
    }
    .con-card {
        background: #fff7ed; border-left: 3px solid #f97316;
        padding: 0.55rem 0.85rem; border-radius: 0 8px 8px 0; margin: 0.3rem 0;
        font-size: 0.92rem; color: #9a3412;
    }

    .section-title {
        font-size: 1.15rem; font-weight: 600; color: #0f172a;
        margin: 1.5rem 0 0.75rem 0;
    }

    div[data-testid="stMetric"] {
        background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 0.5rem;
    }
    div[data-testid="stMetricValue"] { font-size: 1.25rem; color: #0f766e; }
</style>
"""


def inject_styles() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def render_hero() -> None:
    st.markdown(
        """
        <div class="hero">
            <h1>🌴 Holiday Planner</h1>
            <p>Pick a tropical holiday — we show weather, nightlife, and rough costs side by side.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_status_pills(openweather_ok: bool, google_ok: bool, openai_ok: bool, origin: str) -> None:
    pills = [
        f"OpenWeather {'live' if openweather_ok else 'demo mode'}",
        f"Google Maps {'live' if google_ok else 'demo mode'}",
        f"AI summary {'on' if openai_ok else 'off'}",
        f"Flying from {origin}",
    ]
    html = '<div class="status-row">' + "".join(f'<span class="status-pill">{p}</span>' for p in pills) + "</div>"
    st.markdown(html, unsafe_allow_html=True)


def render_summary_box(text: str) -> None:
    clean = text.replace("**", "").replace("_", "")
    st.markdown(f'<div class="summary-box">{clean}</div>', unsafe_allow_html=True)


def render_takeaway(text: str) -> None:
    st.markdown(f'<div class="takeaway-box">• {text}</div>', unsafe_allow_html=True)


def render_dest_card(rank: int, dest: dict) -> None:
    st.markdown(
        f"""
        <div class="dest-card">
            <h3>#{rank} {dest['name']}</h3>
            <div class="meta">{dest['country']} · {dest['temp_max_c']}°C · ${dest['total_cost_usd']:,.0f} (7 nights) · {dest['nightlife_total']} nightlife spots</div>
            <span class="score">Score {dest['score']}/100</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
