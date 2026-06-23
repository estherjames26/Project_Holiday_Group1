# Holiday Planner

Streamlit app that ranks tropical destinations by weather, cost, nightlife, and adventure.

## Run locally

```bash
cd main
pip install -r requirements.txt
copy .env.example .env   # add your API keys
streamlit run app.py
```

## Deploy on Streamlit Cloud

1. Upload the **`main/`** folder (or set repo root and point main file to `main/app.py`).
2. Set **Main file** to `app.py` (if uploading `main/` as the app root) or `main/app.py` (if uploading the whole project).
3. Add secrets in the app settings (same names as `.env.example`).

| Secret | Purpose |
|---|---|
| `OPENWEATHER_API_KEY` | Live weather |
| `GOOGLE_MAPS_API_KEY` | Places, maps, geocoding |
| `OPENAI_API_KEY` | Optional AI summary |
| `ORIGIN_AIRPORT` | Departure airport, e.g. `LHR` |

The app runs without keys — it uses demo data as a fallback.

## What to upload

```
app.py
pages/
src/
requirements.txt
.streamlit/
.env.example          # optional — reference for secrets only
data/                 # optional — DB is created on first run
```

**Do not upload** `not_for_streamlit/` — that folder holds docs, tests, and assignment files. Delete it (or leave it out of the repo) before deploying.

Full project documentation lives in `not_for_streamlit/README.md`.
