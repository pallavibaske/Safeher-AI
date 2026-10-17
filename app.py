import os
import sqlite3
import smtplib
import json
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from functools import wraps

from flask import (Flask, g, jsonify, redirect, render_template, request,
                   session, url_for, flash)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-me")
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "safeher.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, phone TEXT,
  password_hash TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS contacts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL, name TEXT NOT NULL, phone TEXT,
  email TEXT, relation TEXT);
CREATE TABLE IF NOT EXISTS sos_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL, kind TEXT NOT NULL, lat REAL, lng REAL,
  message TEXT, notified INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS checkins(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.executescript(SCHEMA)


init_db()


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if "uid" not in session:
            if request.path.startswith("/api/"):
                return jsonify(error="login required"), 401
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper


def current_user():
    return get_db().execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()


# ---------- auth ----------
@app.route("/")
def index():
    return redirect(url_for("dashboard") if "uid" in session else url_for("login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        pw = request.form["password"]
        if not name or not email or len(pw) < 6:
            flash("Name, email and a password of 6+ characters are required.")
            return render_template("signup.html")
        try:
            db = get_db()
            db.execute("INSERT INTO users(name,email,phone,password_hash) VALUES(?,?,?,?)",
                       (name, email, request.form.get("phone", "").strip(), generate_password_hash(pw)))
            db.commit()
        except sqlite3.IntegrityError:
            flash("That email is already registered.")
            return render_template("signup.html")
        flash("Account created. Please sign in.")
        return redirect(url_for("login"))
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = get_db().execute("SELECT * FROM users WHERE email=?",
                             (request.form["email"].strip().lower(),)).fetchone()
        if u and check_password_hash(u["password_hash"], request.form["password"]):
            session.clear()
            session["uid"] = u["id"]
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- pages ----------
@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    n = db.execute("SELECT COUNT(*) c FROM contacts WHERE user_id=?", (session["uid"],)).fetchone()["c"]
    last = db.execute("SELECT * FROM sos_history WHERE user_id=? ORDER BY id DESC LIMIT 1",
                      (session["uid"],)).fetchone()
    return render_template("dashboard.html", user=current_user(), contacts=n, last=last)


@app.route("/assistant")
@login_required
def assistant():
    return render_template("assistant.html", user=current_user())


@app.route("/route")
@login_required
def safe_route():
    return render_template("route.html", user=current_user())


@app.route("/sos")
@login_required
def sos_page():
    return render_template("sos.html", user=current_user())


@app.route("/checkin")
@login_required
def checkin_page():
    rows = get_db().execute("SELECT * FROM checkins WHERE user_id=? ORDER BY id DESC LIMIT 20",
                            (session["uid"],)).fetchall()
    return render_template("checkin.html", user=current_user(), rows=rows)


@app.route("/history")
@login_required
def history():
    rows = get_db().execute("SELECT * FROM sos_history WHERE user_id=? ORDER BY id DESC",
                            (session["uid"],)).fetchall()
    return render_template("history.html", user=current_user(), rows=rows)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    db = get_db()
    uid = session["uid"]
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            db.execute("UPDATE users SET name=?, phone=? WHERE id=?",
                       (request.form["name"].strip(), request.form.get("phone", "").strip(), uid))
        elif action == "add_contact" and request.form.get("name", "").strip():
            db.execute("INSERT INTO contacts(user_id,name,phone,email,relation) VALUES(?,?,?,?,?)",
                       (uid, request.form["name"].strip(), request.form.get("phone", "").strip(),
                        request.form.get("email", "").strip(), request.form.get("relation", "").strip()))
        elif action == "delete_contact":
            db.execute("DELETE FROM contacts WHERE id=? AND user_id=?", (request.form["id"], uid))
        db.commit()
        return redirect(url_for("profile"))
    contacts = db.execute("SELECT * FROM contacts WHERE user_id=?", (uid,)).fetchall()
    return render_template("profile.html", user=current_user(), contacts=contacts)


# ---------- alerts ----------
def send_email_alert(user, contacts, subject, body):
    """Sends via SMTP if configured. Returns number of emails sent."""
    host, usr, pwd = os.environ.get("SMTP_HOST"), os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS")
    if not (host and usr and pwd):
        return 0
    sent = 0
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)), timeout=15) as s:
            s.starttls()
            s.login(usr, pwd)
            for c in contacts:
                if not c["email"]:
                    continue
                m = EmailMessage()
                m["From"], m["To"], m["Subject"] = usr, c["email"], subject
                m.set_content(body)
                s.send_message(m)
                sent += 1
    except Exception as e:  # network/auth errors must not break the SOS record
        app.logger.error("SMTP failure: %s", e)
    return sent


@app.post("/api/sos")
@login_required
def api_sos():
    d = request.get_json(force=True, silent=True) or {}
    kind = d.get("kind", "sos")
    if kind not in ("sos", "battery", "checkin_help"):
        kind = "sos"
    lat, lng = d.get("lat"), d.get("lng")
    user = current_user()
    db = get_db()
    contacts = db.execute("SELECT * FROM contacts WHERE user_id=?", (user["id"],)).fetchall()
    loc = f"https://www.google.com/maps?q={lat},{lng}" if lat is not None and lng is not None else "Location unavailable"
    title = {"sos": "EMERGENCY SOS", "battery": "LOW BATTERY ALERT", "checkin_help": "HELP REQUESTED (check-in)"}[kind]
    body = (f"{title}\n\n{user['name']} needs help.\nPhone: {user['phone'] or 'n/a'}\n"
            f"Location: {loc}\nTime: {datetime.now():%Y-%m-%d %H:%M:%S}\n{d.get('message', '')}")
    sent = send_email_alert(user, contacts, f"[SafeHer AI] {title} - {user['name']}", body)
    db.execute("INSERT INTO sos_history(user_id,kind,lat,lng,message,notified) VALUES(?,?,?,?,?,?)",
               (user["id"], kind, lat, lng, d.get("message", ""), sent))
    db.commit()
    return jsonify(ok=True, notified=sent, contacts=len(contacts),
                   email_configured=bool(os.environ.get("SMTP_HOST")),
                   share_text=body)


@app.post("/api/checkin")
@login_required
def api_checkin():
    status = (request.get_json(force=True, silent=True) or {}).get("status")
    if status not in ("safe", "help"):
        return jsonify(error="bad status"), 400
    db = get_db()
    db.execute("INSERT INTO checkins(user_id,status) VALUES(?,?)", (session["uid"], status))
    db.commit()
    return jsonify(ok=True)


# ---------- AI assistant ----------
SYSTEM_PROMPT = ("You are SafeHer AI, a calm women-safety assistant. Give short, practical, "
                 "step-by-step safety advice. For immediate danger always tell the user to call "
                 "India emergency number 112 (women helpline 1091) first. Reply in the user's language "
                 "(English, Hindi or Marathi).")

FALLBACK = ("I'm in offline mode (no AI key configured). If you're in danger: call 112 or women's helpline 1091, "
            "move to a crowded, well-lit place, and press SOS to alert your guardians. "
            "Share your live location with someone you trust.")


@app.post("/api/chat")
@login_required
def api_chat():
    msg = (request.get_json(force=True, silent=True) or {}).get("message", "").strip()[:2000]
    if not msg:
        return jsonify(error="empty"), 400
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return jsonify(reply=FALLBACK, mode="fallback")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {"system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
               "contents": [{"role": "user", "parts": [{"text": msg}]}]}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.load(r)
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return jsonify(reply=text, mode="gemini")
    except Exception as e:
        app.logger.error("Gemini failure: %s", e)
        return jsonify(reply=FALLBACK, mode="fallback")


@app.get("/api/contacts")
@login_required
def api_contacts():
    rows = get_db().execute("SELECT id,name,phone,email,relation FROM contacts WHERE user_id=?",
                            (session["uid"],)).fetchall()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG") == "1")
