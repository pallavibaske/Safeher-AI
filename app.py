"""SafeHer AI - Smart Women Safety System (Flask backend)."""
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import urllib.parse
from datetime import datetime
from email.message import EmailMessage
from functools import wraps

import requests
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "safeher.db"))
DEFAULT_CC = os.environ.get("DEFAULT_COUNTRY_CODE", "91")
MAX_CONTACTS = 5

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
    MAX_CONTENT_LENGTH=64 * 1024,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT DEFAULT '',
    password_hash TEXT NOT NULL,
    countdown INTEGER NOT NULL DEFAULT 5,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    phone TEXT DEFAULT '',
    email TEXT DEFAULT '',
    relation TEXT DEFAULT '',
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS sos_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    trigger TEXT NOT NULL,
    lat REAL, lng REAL, accuracy REAL, battery INTEGER,
    message TEXT NOT NULL,
    notified TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    response TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""


# ---------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        get_db().executescript(SCHEMA)
        get_db().commit()


init_db()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- auth + csrf
@app.before_request
def load_user_and_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    if request.method == "POST":
        token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
        if not secrets.compare_digest(token, session["csrf"]):
            abort(400, "Invalid or missing security token. Refresh the page and try again.")
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if g.user is None:
            session.clear()


@app.context_processor
def inject_globals():
    return {"csrf_token": session.get("csrf", ""), "user": g.get("user")}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return jsonify(error="Please sign in again."), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.get("/")
def index():
    if g.user:
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:80]
        email = request.form.get("email", "").strip().lower()[:120]
        phone = request.form.get("phone", "").strip()[:20]
        password = request.form.get("password", "")
        error = None
        if not name:
            error = "Enter your name."
        elif not EMAIL_RE.match(email):
            error = "Enter a valid email address."
        elif len(password) < 8:
            error = "Use a password with at least 8 characters."
        elif get_db().execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            error = "An account with this email already exists. Sign in instead."
        if error:
            flash(error, "error")
            return render_template("auth.html", mode="signup", form=request.form), 400
        cur = get_db().execute(
            "INSERT INTO users (name, email, phone, password_hash, created_at) VALUES (?,?,?,?,?)",
            (name, email, phone, generate_password_hash(password), now()))
        get_db().commit()
        session.clear()
        session["uid"] = cur.lastrowid
        flash("Account created. Add a trusted contact so SOS alerts have someone to reach.", "ok")
        return redirect(url_for("contacts"))
    return render_template("auth.html", mode="signup", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        row = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
            session.clear()
            session["uid"] = row["id"]
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
        flash("Email or password is incorrect.", "error")
        return render_template("auth.html", mode="login", form=request.form), 401
    return render_template("auth.html", mode="login", form={})


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------------------------------------------------------------- pages
@app.get("/dashboard")
@login_required
def dashboard():
    db = get_db()
    n_contacts = db.execute("SELECT COUNT(*) FROM contacts WHERE user_id = ?", (g.user["id"],)).fetchone()[0]
    last = db.execute("SELECT * FROM sos_events WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                      (g.user["id"],)).fetchone()
    last_checkin = db.execute("SELECT * FROM checkins WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                              (g.user["id"],)).fetchone()
    return render_template("dashboard.html", n_contacts=n_contacts, last=last, last_checkin=last_checkin)


@app.route("/contacts", methods=["GET", "POST"])
@login_required
def contacts():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:80]
        phone = request.form.get("phone", "").strip()[:20]
        email = request.form.get("email", "").strip().lower()[:120]
        relation = request.form.get("relation", "").strip()[:40]
        count = db.execute("SELECT COUNT(*) FROM contacts WHERE user_id = ?", (g.user["id"],)).fetchone()[0]
        if not name or not (phone or email):
            flash("Enter a name and at least a phone number or an email.", "error")
        elif email and not EMAIL_RE.match(email):
            flash("That email address doesn't look right.", "error")
        elif count >= MAX_CONTACTS:
            flash(f"You can keep up to {MAX_CONTACTS} contacts. Remove one to add another.", "error")
        else:
            db.execute("INSERT INTO contacts (user_id, name, phone, email, relation) VALUES (?,?,?,?,?)",
                       (g.user["id"], name, phone, email, relation))
            db.commit()
            flash(f"{name} added.", "ok")
        return redirect(url_for("contacts"))
    rows = db.execute("SELECT * FROM contacts WHERE user_id = ? ORDER BY id", (g.user["id"],)).fetchall()
    return render_template("contacts.html", rows=rows, max_contacts=MAX_CONTACTS)


@app.post("/contacts/<int:cid>/delete")
@login_required
def delete_contact(cid):
    db = get_db()
    db.execute("DELETE FROM contacts WHERE id = ? AND user_id = ?", (cid, g.user["id"]))
    db.commit()
    flash("Contact removed.", "ok")
    return redirect(url_for("contacts"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:80]
        phone = request.form.get("phone", "").strip()[:20]
        try:
            countdown = max(0, min(15, int(request.form.get("countdown", 5))))
        except ValueError:
            countdown = 5
        if not name:
            flash("Name can't be empty.", "error")
        else:
            get_db().execute("UPDATE users SET name=?, phone=?, countdown=? WHERE id=?",
                             (name, phone, countdown, g.user["id"]))
            get_db().commit()
            flash("Profile saved.", "ok")
        return redirect(url_for("profile"))
    return render_template("profile.html")


@app.get("/history")
@login_required
def history():
    db = get_db()
    events = db.execute("SELECT * FROM sos_events WHERE user_id = ? ORDER BY id DESC LIMIT 50",
                        (g.user["id"],)).fetchall()
    checks = db.execute("SELECT * FROM checkins WHERE user_id = ? ORDER BY id DESC LIMIT 20",
                        (g.user["id"],)).fetchall()
    return render_template("history.html", events=events, checks=checks)


@app.get("/assistant")
@login_required
def assistant():
    return render_template("assistant.html")


@app.get("/route")
@login_required
def route():
    return render_template("route.html")


@app.get("/checkin")
@login_required
def checkin():
    return render_template("checkin.html")


# ---------------------------------------------------------------- SOS
def phone_digits(phone):
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        digits = DEFAULT_CC + digits
    return digits


def build_message(user, lat, lng, accuracy, trigger, battery):
    if trigger == "battery":
        head = f"Low battery alert from {user['name']} (SafeHer AI)."
    else:
        head = f"SOS! {user['name']} needs help (SafeHer AI)."
    parts = [head]
    if lat is not None and lng is not None:
        link = f"https://www.google.com/maps?q={lat:.6f},{lng:.6f}"
        acc = f" (accuracy about {int(accuracy)} m)" if accuracy else ""
        parts.append(f"Location: {link}{acc}")
    else:
        parts.append("Location is not available. Please call her now.")
    if battery is not None:
        parts.append(f"Battery: {battery}%")
    if user["phone"]:
        parts.append(f"Phone: {user['phone']}")
    parts.append("Time: " + datetime.now().strftime("%d %b %Y, %I:%M %p"))
    return "\n".join(parts)


def send_email(recipients, subject, body):
    host, user, pwd = os.environ.get("SMTP_HOST"), os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS")
    if not (host and user and pwd and recipients):
        return 0, "Email is not configured."
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, os.environ.get("MAIL_FROM") or user, ", ".join(recipients)
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)), timeout=10) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(user, pwd)
            s.send_message(msg)
        return len(recipients), None
    except Exception as exc:  # network / auth problems should not break the SOS response
        return 0, f"Email failed: {exc.__class__.__name__}"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@app.post("/api/sos")
@login_required
def api_sos():
    data = request.get_json(silent=True) or {}
    lat, lng, acc = _num(data.get("lat")), _num(data.get("lng")), _num(data.get("accuracy"))
    if lat is not None and not (-90 <= lat <= 90) or lng is not None and not (-180 <= lng <= 180):
        lat = lng = None
    battery = data.get("battery")
    battery = int(battery) if isinstance(battery, (int, float)) and 0 <= battery <= 100 else None
    trigger = data.get("trigger") if data.get("trigger") in ("button", "battery", "checkin") else "button"

    message = build_message(g.user, lat, lng, acc, trigger, battery)
    db = get_db()
    contacts_ = db.execute("SELECT * FROM contacts WHERE user_id = ?", (g.user["id"],)).fetchall()

    emails = [c["email"] for c in contacts_ if c["email"]]
    sent, email_note = send_email(emails, f"SafeHer AI alert from {g.user['name']}", message)
    notified = f"emailed {sent}" if sent else (email_note or "links only")

    cur = db.execute(
        "INSERT INTO sos_events (user_id, created_at, trigger, lat, lng, accuracy, battery, message, notified)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (g.user["id"], now(), trigger, lat, lng, acc, battery, message, notified))
    db.commit()

    text = urllib.parse.quote(message)
    links = []
    for c in contacts_:
        d = phone_digits(c["phone"])
        links.append({
            "name": c["name"],
            "whatsapp": f"https://wa.me/{d}?text={text}" if d else None,
            "sms": f"sms:+{d}?body={text}" if d else None,
            "tel": f"tel:+{d}" if d else None,
        })
    return jsonify(id=cur.lastrowid, message=message, emailed=sent, email_note=email_note,
                   links=links, has_contacts=bool(contacts_), has_location=lat is not None)


@app.post("/api/checkin")
@login_required
def api_checkin():
    resp = (request.get_json(silent=True) or {}).get("response")
    if resp not in ("safe", "help", "no_response"):
        return jsonify(error="Unknown response."), 400
    get_db().execute("INSERT INTO checkins (user_id, created_at, response) VALUES (?,?,?)",
                     (g.user["id"], now(), resp))
    get_db().commit()
    return jsonify(ok=True, escalate=resp != "safe")


# ---------------------------------------------------------------- AI assistant
SYSTEM_PROMPT = (
    "You are SafeHer AI, a calm and practical personal-safety assistant for women in India. "
    "Give short, concrete, step-by-step advice (under 150 words). If someone may be in immediate "
    "danger, tell them first to call 112 (emergency) or 1091 (women helpline) and use the SOS button. "
    "Reply in the same language the user writes in (English, Marathi or Hindi). "
    "Never give legal or medical certainty; suggest professionals when needed."
)

FALLBACK_TIPS = [
    (("follow", "stalk", "पाठलाग", "पीछा"),
     "If you think someone is following you: stay in a lit, busy place, cross the street and see if they follow, "
     "walk into a shop or any place with people, and call a trusted contact. Call 112 if you feel unsafe. "
     "Use the SOS button to share your location."),
    (("cab", "taxi", "uber", "ola", "auto", "रिक्षा"),
     "Before a cab ride: check the number plate and driver photo, share the trip with a contact, sit behind the "
     "driver, keep your phone charged and don't share personal details. Open Safe Route to share your trip."),
    (("night", "alone", "late", "रात्री", "एकटी"),
     "Walking alone at night: stay on main, well-lit roads, keep one ear free of headphones, tell someone your route "
     "and arrival time, and start a Safety Check-in so we ask if you reached safely."),
    (("harass", "touch", "eve", "छेड"),
     "If you are being harassed: move away to a crowded place, say loudly and clearly that you want them to stop, "
     "note details if safe, and call 112 or 1091. You can report it later at the nearest police station."),
    (("home", "house", "घर"),
     "At home: lock doors and windows, don't open the door to unknown people, keep emergency numbers handy "
     "(112, 1091) and make sure your trusted contacts are saved in SafeHer AI."),
]
GENERIC_TIP = ("Stay aware of your surroundings, keep your phone charged and your trusted contacts updated. "
               "In immediate danger, call 112 or 1091 and press the SOS button. "
               "(The AI service is not connected right now, so this is a general tip.)")


def fallback_answer(msg):
    low = msg.lower()
    for keys, answer in FALLBACK_TIPS:
        if any(k in low for k in keys):
            return answer
    return GENERIC_TIP


@app.post("/api/assistant")
@login_required
def api_assistant():
    msg = ((request.get_json(silent=True) or {}).get("message") or "").strip()[:1000]
    if not msg:
        return jsonify(error="Type a question first."), 400
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return jsonify(reply=fallback_answer(msg), source="offline")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={"system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                  "contents": [{"role": "user", "parts": [{"text": msg}]}]},
            timeout=20)
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        return jsonify(reply=text, source="gemini")
    except Exception:
        return jsonify(reply=fallback_answer(msg), source="offline")


@app.errorhandler(400)
def bad_request(e):
    if request.path.startswith("/api/"):
        return jsonify(error=str(e.description)), 400
    return render_template("error.html", message=e.description), 400


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", message="That page doesn't exist."), 404


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
