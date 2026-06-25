# Holiday Planner — project layout

```
main/                 ← Streamlit app (upload this folder to Streamlit Cloud)
venv/                 ← local Python environment (do not upload)
env                   ← optional shared API keys file (one level up from main/)
```

## Run locally

```bash
cd main
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```

See **`main/README.md`** for a full list of what each file does.

## Streamlit Cloud

Point the app at **`main/app.py`** and add your API keys as secrets (see `main/.env.example`).
