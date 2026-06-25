# Holiday Planner

Streamlit app that ranks tropical destinations by weather, cost, nightlife, and adventure.

## Run locally

```bash
cd main
pip install -r requirements.txt
copy .env.example .env   # add your API keys
streamlit run app.py
```

## Where everything lives

All the Python code sits in the `main/` folder — no nested `src/` package to dig through.

| File | What it does |
|------|----------------|
| **`app.py`** | Home page — start here |
| **`settings.py`** | API keys and config from `.env` |
| **`ranking.py`** | Scores and filters destinations |
| **`places.py`** | Destination list + backup cities |
| **`find_destinations.py`** | Finds cities via Google Places |
| **`scrape_costs.py`** | Scrapes Numbeo + Cheapflights for prices |
| **`api_weather.py`** | OpenWeather API |
| **`api_google_places.py`** | Bars, restaurants, clubs nearby |
| **`api_geocoding.py`** | Lat/lon → city name |
| **`api_openai.py`** | Optional AI summary at top of results |
| **`trip_notes.py`** | Pros/cons text on each card |
| **`database.py`** | SQLite cache and search history |
| **`charts.py`** | Plotly comparison charts |
| **`folium_maps.py`** | Map pins and heatmaps |
| **`sidebar.py`** | Sidebar presets and sliders |
| **`page_styling.py`** | CSS and layout HTML |
| **`pages/1_Compare.py`** | Compare two or three destinations |
| **`pages/2_History.py`** | Past searches and cache stats |

## Deploy on Streamlit Cloud

1. Upload the **`main/`** folder.
2. Set **Main file** to `app.py`.
3. Add secrets matching `.env.example`.

| Secret | Purpose |
|---|---|
| `OPENWEATHER_API_KEY` | Live weather |
| `GOOGLE_MAPS_API_KEY` | Places, maps, geocoding |
| `OPENAI_API_KEY` | Optional AI summary |
| `ORIGIN_AIRPORT` | Departure airport, e.g. `LHR` |

Works without API keys — it falls back to demo data.

## What to upload

```
app.py
settings.py
ranking.py
places.py
find_destinations.py
scrape_costs.py
api_*.py
trip_notes.py
database.py
charts.py
folium_maps.py
sidebar.py
page_styling.py
pages/
requirements.txt
.streamlit/
.env.example
data/                 # optional — DB created on first run
```

Do **not** upload `.env` (contains your keys) or `venv/`.
