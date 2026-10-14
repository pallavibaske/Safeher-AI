# SafeHer AI – Smart Women Safety System

Flask + SQLite web application: SOS alert with countdown, live location, trusted contacts,
AI safety assistant (Google Gemini), safety check-in, safe route (Leaflet/OpenStreetMap),
low-battery alert and SOS history.

## Run locally
```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # Mac/Linux: cp .env.example .env   then edit .env
python app.py
```
Open http://127.0.0.1:5000

Note: browsers allow location access only on `localhost` or `https`.

## .env settings
| Key | Purpose |
|---|---|
| SECRET_KEY | Long random string (required in production) |
| GEMINI_API_KEY | Enables the AI assistant. Without it, built-in safety tips are used |
| SMTP_HOST / SMTP_USER / SMTP_PASS | Optional email alerts (Gmail: use an App Password) |
| DEFAULT_COUNTRY_CODE | Added to 10-digit phone numbers (India = 91) |
| COOKIE_SECURE | Set 1 on HTTPS |

## Deploy on Render
1. Push this folder to GitHub (`.env` is ignored by .gitignore).
2. Render → New Web Service → pick the repo.
3. Build command: `pip install -r requirements.txt`  Start command: `gunicorn app:app`
4. Add the environment variables above (set COOKIE_SECURE=1).
5. SQLite on Render's free plan is wiped on each deploy/restart. Attach a Persistent Disk and set
   `DATABASE_PATH=/var/data/safeher.db`, or move to PostgreSQL for a real deployment.

## How alerts are delivered
- Email: sent automatically if SMTP is configured.
- WhatsApp / SMS: after the countdown, the app shows ready-to-send buttons for each contact
  (opens the user's own WhatsApp/SMS with the message and map link filled in).
  Fully automatic SMS needs a paid gateway such as Twilio or MSG91 (can be added in `api_sos`).

## Limits to be honest about
- The check-in timer runs in the open browser tab.
- Battery API works in Chrome/Android only.
- Not a replacement for 112 / 1091. Do security testing and a privacy review before real use.
