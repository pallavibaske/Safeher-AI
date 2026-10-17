# SafeHer AI – Smart Women Safety System
Flask + SQLite + Leaflet + Gemini.

## Run locally
    python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
    pip install -r requirements.txt
    export SECRET_KEY=something GEMINI_API_KEY=...     # optional; see .env.example
    python app.py        # http://localhost:5000

Geolocation works on http://localhost or HTTPS only.

## Deploy on Render
Build: `pip install -r requirements.txt` · Start: `gunicorn app:app`
Env vars: SECRET_KEY, GEMINI_API_KEY, SMTP_* (optional). Note: SQLite on Render's free tier resets on redeploy; attach a disk (set DB_PATH) for persistence.
