# Holiday Planner

Streamlit app that ranks **tropical destinations** by weather, cost, nightlife, and adventure.

## Project layout

```
Project_Holiday_Group1/     ← repo root (you are here after git clone)
├── main/                   ← all app code — run commands from this folder
│   ├── app.py              ← start here
│   ├── requirements.txt
│   ├── .env.example
│   └── ...
├── README.md               ← this file
```

## First-time setup (new PC)

### 1. Install prerequisites

| Requirement | Notes |
|-------------|--------|
| **Python 3.10+** | [python.org/downloads](https://www.python.org/downloads/) — tick **“Add Python to PATH”** on Windows |
| **Git** | [git-scm.com](https://git-scm.com/) — to clone the repo |
| **Google Chrome** | Required only for **Airbnb listing scrape** on the Costs tab (optional feature) |
| **Internet** | Needed for APIs, scraping, and ChromeDriver download |

Check Python:

```bash
python --version
```

### 2. Clone the repo

```bash
git clone https://github.com/estherjames26/Project_Holiday_Group1.git
cd Project_Holiday_Group1/main
```

> If you downloaded a ZIP instead, open a terminal in the **`main`** folder (the one that contains `app.py`).

### 3. Create a virtual environment (recommended)

**Windows (PowerShell):**

```powershell
cd main
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**macOS / Linux:**

```bash
cd main
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

> Skip the venv steps if you prefer a global install — still run `pip install -r requirements.txt` from **`main/`**.

### 4. Configure API keys (optional)

The app runs **without keys** using demo/fallback data. For live weather, maps, and venues:

**Windows:**

```powershell
copy .env.example .env
```

**macOS / Linux:**

```bash
cp .env.example .env
```

Edit **`main/.env`** and add your keys (see `.env.example`).  
**Do not commit `.env`** — it is in `.gitignore`.

| Key | Required? | Purpose |
|-----|-----------|---------|
| `OPENWEATHER_API_KEY` | Optional | Live weather |
| `GOOGLE_MAPS_API_KEY` | Optional | Places, maps, geocoding |
| `OPENAI_API_KEY` | Optional | AI summary text |
| `ORIGIN_AIRPORT` | Optional | Default departure airport (e.g. `LHR`) |

### 5. Run the app

From the **`main`** folder (with venv activated if you use one):

```bash
streamlit run app.py
```

Your browser should open at **http://localhost:8501**.

If it does not open automatically, paste that URL into Chrome or Edge.

### 6. Quick test

1. Pick preferences in the **sidebar** (airport, budget, weights).
2. Click **Find destinations**.
3. Open a result → **Costs** tab (Airbnb needs Chrome + internet).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `'python' is not recognized` | Reinstall Python with **Add to PATH**, or try `py -3` instead of `python` |
| `'streamlit' is not recognized` | Run `pip install -r requirements.txt` from **`main/`**, or activate your venv |
| `ImportError` after git pull | Delete `main/__pycache__`, restart Streamlit |
| PowerShell blocks venv activate | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then retry |
| No live data | Add API keys to `.env`, or use demo mode (no keys) |
| Airbnb tab empty | Install Chrome; run `pip install selenium webdriver-manager` |
| Results look stale after changing sidebar | Click **Find destinations** again (yellow banner will warn you) |

---

## Streamlit Cloud

1. Point the app at **`main/app.py`**.
2. Add secrets matching `main/.env.example`.
3. Do **not** upload `.env`, `venv/`, or `data/*.db`.

---

## More detail

See **`main/README.md`** for a file-by-file guide and deploy checklist.
