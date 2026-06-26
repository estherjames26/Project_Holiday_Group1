# Holiday Planner — `main/` app

All runnable code lives in this folder.

## Run (quick reference)

```bash
# From repo root:
cd main

# First time only:
python -m venv venv
# Windows:  .\venv\Scripts\Activate.ps1
# Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env    # Windows — use `cp` on Mac/Linux

# Every time:
streamlit run app.py
```

Open **http://localhost:8501** → set sidebar preferences → **Find destinations**.

Full first-time steps (clone, venv, keys, troubleshooting): see **`../README.md`** in the repo root.

---

## Requirements

- Python **3.10+**
- Packages in **`requirements.txt`** (Streamlit, Pandas, Plotly, Folium, Selenium, SQLAlchemy, etc.)
- **Google Chrome** — only for live Airbnb scraping on the destination **Costs** tab
- **API keys** in `.env` — optional; app uses demo data without them

---

## Where everything lives

| File | What it does |
|------|----------------|
| **`app.py`** | Home page — start here |
| **`settings.py`** | API keys and config from `.env` |
| **`ranking.py`** | Scores and filters destinations |
| **`places.py`** | Destination list + backup cities |
| **`find_destinations.py`** | Finds cities via Google Places |
| **`scrape_costs.py`** | Scrapes Numbeo + flight costs (origin-aware) |
| **`scrape_airbnb.py`** | Selenium Airbnb scraper (Costs tab) |
| **`api_weather.py`** | OpenWeather API |
| **`api_google_places.py`** | Bars, restaurants, clubs nearby |
| **`api_geocoding.py`** | Lat/lon → city name |
| **`api_openai.py`** | Optional AI summary at top of results |
| **`trip_notes.py`** | Pros/cons text on each card |
| **`database.py`** | SQLite cache and search history |
| **`charts.py`** | Plotly comparison charts |
| **`folium_maps.py`** | Map pins and heatmaps |
| **`sidebar.py`** | Sidebar presets, airport picker, scoring weights |
| **`page_styling.py`** | CSS and layout HTML |
| **`pages/1_Compare.py`** | Compare two or three destinations |
| **`pages/2_History.py`** | Past searches and cache stats |

Code flow diagram: **`../FLOWCHART.md`**

---

## Environment file

Copy **`.env.example`** → **`.env`** in this folder and add keys.

Optional: team can put shared keys in a file named **`env`** (no dot) in the **repo root** (parent of `main/`) — `settings.py` loads it automatically.

Never commit `.env` or real API keys to GitHub.

---

## Deploy on Streamlit Cloud

1. Upload this **`main/`** folder (or point Cloud at `main/app.py`).
2. Set **Main file** to `app.py`.
3. Add secrets matching `.env.example`.

| Secret | Purpose |
|--------|---------|
| `OPENWEATHER_API_KEY` | Live weather |
| `GOOGLE_MAPS_API_KEY` | Places, maps, geocoding |
| `OPENAI_API_KEY` | Optional AI summary |
| `ORIGIN_AIRPORT` | Default departure airport, e.g. `LHR` |

Works without API keys — falls back to demo data.

---

## What to upload (not `.env` or `venv/`)

```
app.py
settings.py
ranking.py
places.py
find_destinations.py
scrape_costs.py
scrape_airbnb.py
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
```

The SQLite database is created automatically at **`data/holiday_planner.db`** on first run.
