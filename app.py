"""Smart Hospital Queue System - Flask + SQLite demo.
Run:  pip install -r requirements.txt && python app.py
Patient app:  http://127.0.0.1:5000/
Staff login:  http://127.0.0.1:5000/login   (demo: hospital1 / demo123)
"""
import functools
import hmac
import math
import os
import random
import re
import sqlite3
import threading
import time

from flask import Flask, g, jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

DB = os.environ.get("DB_PATH", "queue.db")
TTL_MIN = 30          # a reservation expires if the patient doesn't arrive in time
SPEED_KMH = 30        # assumed average travel speed
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
CAMERA_KEY = os.environ.get("CAMERA_KEY", "camera-demo-key")  # used by the CCTV counting script
DEMO_PASSWORD = "demo123"
fails = {}  # ip -> recent failed login times

# Demo hospitals placed around Haripur (change lat/lng to test elsewhere)
SEED = [
    ("City General Hospital", 33.9946, 72.9333, 1, 12, 6),
    ("Al-Shifa Medical Complex", 34.0050, 72.9500, 1, 4, 5),
    ("Green Valley Clinic", 33.9800, 72.9200, 0, 2, 4),
    ("Margalla Emergency Care", 34.0200, 72.9000, 1, 22, 7),
    ("Taxila Road Hospital", 33.9600, 72.9700, 1, 8, 6),
]

def connect():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c

def db():
    if "db" not in g:
        g.db = connect()
    return g.db

@app.teardown_appcontext
def close_db(_):
    c = g.pop("db", None)
    if c:
        c.close()

def init_db():
    c = connect()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS hospitals(id INTEGER PRIMARY KEY, name TEXT, lat REAL, lng REAL,
        has_er INT, walk_in INT, avg_min INT);
    CREATE TABLE IF NOT EXISTS tokens(id INTEGER PRIMARY KEY, hospital_id INT, name TEXT, phone TEXT,
        number INT, status TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, hospital_id INT, name TEXT, phone TEXT,
        eta_min INT, created REAL, ack INT DEFAULT 0);
    CREATE TABLE IF NOT EXISTS staff(id INTEGER PRIMARY KEY, hospital_id INT, username TEXT UNIQUE, pw_hash TEXT);
    CREATE TABLE IF NOT EXISTS history(hospital_id INT, ts REAL, walk_in INT);
    """)
    if not c.execute("SELECT 1 FROM hospitals").fetchone():
        c.executemany("INSERT INTO hospitals(name,lat,lng,has_er,walk_in,avg_min) VALUES(?,?,?,?,?,?)", SEED)
    if not c.execute("SELECT 1 FROM staff").fetchone():
        for (hid,) in c.execute("SELECT id FROM hospitals").fetchall():
            c.execute("INSERT INTO staff(hospital_id,username,pw_hash) VALUES(?,?,?)",
                      (hid, f"hospital{hid}", generate_password_hash(DEMO_PASSWORD)))
    c.commit()
    c.close()

def err(msg, code=400):
    return jsonify(error=msg), code

def staff_only(f):
    """Staff must be logged in, and may only manage their own hospital."""
    @functools.wraps(f)
    def wrapper(*a, **k):
        if "hid" not in session:
            return err("Please log in.", 401)
        if "hid" in k and k["hid"] != session["hid"]:
            return err("You can only manage your own hospital.", 403)
        return f(*a, **k)
    return wrapper

def haversine(a, b, c, d):
    p = math.radians
    x = math.sin(p(c - a) / 2) ** 2 + math.cos(p(a)) * math.cos(p(c)) * math.sin(p(d - b) / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))

def expire_old(c):
    c.execute("UPDATE tokens SET status='expired' WHERE status='waiting' AND created<?",
              (time.time() - TTL_MIN * 60,))
    c.commit()

def waiting_count(c, hid):
    return c.execute("SELECT COUNT(*) FROM tokens WHERE hospital_id=? AND status='waiting'", (hid,)).fetchone()[0]

# ---------- pages ----------
@app.get("/healthz")
def healthz():
    return jsonify(status="ok")

@app.get("/")
def patient_page():
    return render_template("patient.html")

@app.get("/login")
def login_page():
    return render_template("login.html")

@app.get("/dashboard")
def dashboard_page():
    if "hid" not in session:
        return redirect("/login")
    return render_template("dashboard.html")

# ---------- patient API ----------
@app.get("/api/hospitals")
def hospitals():
    lat = float(request.args.get("lat", 33.9946))
    lng = float(request.args.get("lng", 72.9333))
    mode = request.args.get("mode", "regular")
    c = db()
    expire_old(c)
    out = []
    for h in c.execute("SELECT * FROM hospitals"):
        if mode == "emergency" and not h["has_er"]:
            continue
        queue = h["walk_in"] + waiting_count(c, h["id"])
        km = haversine(lat, lng, h["lat"], h["lng"])
        travel = round(km / SPEED_KMH * 60)
        wait = queue * h["avg_min"]
        out.append(dict(id=h["id"], name=h["name"], lat=h["lat"], lng=h["lng"],
                        has_er=bool(h["has_er"]), km=round(km, 1), travel_min=travel, queue=queue,
                        wait_min=wait, total_min=travel + wait,
                        level="low" if queue <= 8 else "medium" if queue <= 18 else "high"))
    # Emergency: nearest ER first. Regular: shortest (travel + wait) first.
    out.sort(key=lambda x: x["km"] if mode == "emergency" else x["total_min"])
    return jsonify(out)

@app.post("/api/reserve")
def reserve():
    d = request.get_json(force=True)
    name = (d.get("name") or "").strip()
    phone = re.sub(r"\D", "", d.get("phone") or "")
    if not name or len(phone) < 10:
        return err("Enter your name and a phone number with at least 10 digits.")
    c = db()
    expire_old(c)
    hid = d.get("hospital_id")
    if not c.execute("SELECT 1 FROM hospitals WHERE id=?", (hid,)).fetchone():
        return err("Hospital not found.", 404)
    if c.execute("SELECT 1 FROM tokens WHERE phone=? AND status='waiting'", (phone,)).fetchone():
        return err("You already have an active reservation. Cancel it first.", 409)
    num = (c.execute("SELECT MAX(number) FROM tokens WHERE hospital_id=?", (hid,)).fetchone()[0] or 0) + 1
    cur = c.execute("INSERT INTO tokens(hospital_id,name,phone,number,status,created) VALUES(?,?,?,?,?,?)",
                    (hid, name, phone, num, "waiting", time.time()))
    c.commit()
    return jsonify(id=cur.lastrowid, number=num)

@app.get("/api/token/<int:tid>")
def token_status(tid):
    c = db()
    expire_old(c)
    t = c.execute("SELECT t.*, h.name hname, h.avg_min FROM tokens t JOIN hospitals h ON h.id=t.hospital_id "
                  "WHERE t.id=?", (tid,)).fetchone()
    if not t:
        return err("Token not found.", 404)
    pos = eta = None
    if t["status"] == "waiting":
        ahead = c.execute("SELECT COUNT(*) FROM tokens WHERE hospital_id=? AND status='waiting' AND number<?",
                          (t["hospital_id"], t["number"])).fetchone()[0]
        pos, eta = ahead + 1, ahead * t["avg_min"]
    left = max(0, round(TTL_MIN - (time.time() - t["created"]) / 60))
    return jsonify(id=tid, number=t["number"], status=t["status"], hospital=t["hname"],
                   position=pos, eta_min=eta, expires_in_min=left)

@app.post("/api/token/<int:tid>/cancel")
def cancel(tid):
    c = db()
    c.execute("UPDATE tokens SET status='cancelled' WHERE id=? AND status='waiting'", (tid,))
    c.commit()
    return jsonify(ok=True)

@app.post("/api/emergency")
def emergency():
    d = request.get_json(force=True)
    c = db()
    h = c.execute("SELECT * FROM hospitals WHERE id=? AND has_er=1", (d.get("hospital_id"),)).fetchone()
    if not h:
        return err("This hospital has no emergency department.", 404)
    c.execute("INSERT INTO alerts(hospital_id,name,phone,eta_min,created) VALUES(?,?,?,?,?)",
              (h["id"], (d.get("name") or "Unknown").strip(), re.sub(r"\D", "", d.get("phone") or ""),
               int(d.get("eta_min") or 0), time.time()))
    c.commit()
    return jsonify(ok=True, hospital=h["name"])

# ---------- staff auth ----------
@app.post("/api/login")
def login():
    ip, now = request.remote_addr, time.time()
    recent = [t for t in fails.get(ip, []) if now - t < 60]
    fails[ip] = recent
    if len(recent) >= 5:
        return err("Too many attempts. Wait a minute and try again.", 429)
    d = request.get_json(force=True)
    s = db().execute("SELECT * FROM staff WHERE username=?", (d.get("username", ""),)).fetchone()
    if not s or not check_password_hash(s["pw_hash"], d.get("password", "")):
        fails[ip].append(now)
        return err("Wrong username or password.", 401)
    session.clear()
    session["hid"], session["user"] = s["hospital_id"], s["username"]
    return jsonify(ok=True)

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)

@app.get("/api/me")
@staff_only
def me():
    h = db().execute("SELECT id,name FROM hospitals WHERE id=?", (session["hid"],)).fetchone()
    return jsonify(hospital_id=h["id"], hospital=h["name"], user=session["user"])

# ---------- hospital dashboard API (staff only) ----------
@app.get("/api/dashboard/<int:hid>")
@staff_only
def dash(hid):
    c = db()
    expire_old(c)
    h = c.execute("SELECT * FROM hospitals WHERE id=?", (hid,)).fetchone()
    if not h:
        return err("Hospital not found.", 404)
    toks = c.execute("SELECT id,number,name,phone,created FROM tokens WHERE hospital_id=? AND status='waiting' "
                     "ORDER BY number", (hid,)).fetchall()
    alerts = c.execute("SELECT id,name,phone,eta_min,created FROM alerts WHERE hospital_id=? AND ack=0 "
                       "ORDER BY id DESC", (hid,)).fetchall()
    return jsonify(name=h["name"], walk_in=h["walk_in"], avg_min=h["avg_min"],
                   tokens=[dict(t) for t in toks], alerts=[dict(a) for a in alerts])

@app.post("/api/dashboard/<int:hid>/next")
@staff_only
def serve_next(hid):
    c = db()
    t = c.execute("SELECT id FROM tokens WHERE hospital_id=? AND status='waiting' ORDER BY number LIMIT 1",
                  (hid,)).fetchone()
    if t:
        c.execute("UPDATE tokens SET status='served' WHERE id=?", (t["id"],))
    else:
        c.execute("UPDATE hospitals SET walk_in=MAX(0,walk_in-1) WHERE id=?", (hid,))
    c.commit()
    return jsonify(ok=True)

@app.post("/api/dashboard/<int:hid>/camera")
def set_camera(hid):
    """People-counter endpoint. A CCTV script sends header X-Camera-Key and JSON {"count": N};
    logged-in staff of that hospital may also set it by hand."""
    key_ok = hmac.compare_digest(request.headers.get("X-Camera-Key", ""), CAMERA_KEY)
    if not key_ok and session.get("hid") != hid:
        return err("Not authorised.", 401)
    n = max(0, int(request.get_json(force=True).get("count", 0)))
    c = db()
    c.execute("UPDATE hospitals SET walk_in=? WHERE id=?", (n, hid))
    c.commit()
    return jsonify(ok=True, walk_in=n)

@app.get("/api/dashboard/<int:hid>/history")
@staff_only
def history(hid):
    rows = db().execute("SELECT walk_in FROM history WHERE hospital_id=? ORDER BY ts", (hid,)).fetchall()
    return jsonify([r["walk_in"] for r in rows])

@app.post("/api/dashboard/<int:hid>/service-time")
@staff_only
def service_time(hid):
    m = min(60, max(1, int(request.get_json(force=True).get("avg_min", 5))))
    c = db()
    c.execute("UPDATE hospitals SET avg_min=? WHERE id=?", (m, hid))
    c.commit()
    return jsonify(ok=True, avg_min=m)

@app.post("/api/alerts/<int:aid>/ack")
@staff_only
def ack(aid):
    c = db()
    c.execute("UPDATE alerts SET ack=1 WHERE id=? AND hospital_id=?", (aid, session["hid"]))
    c.commit()
    return jsonify(ok=True)

# ---------- simulated surveillance camera ----------
def simulator():
    while True:
        time.sleep(4)
        c = connect()
        for hid, w in c.execute("SELECT id,walk_in FROM hospitals").fetchall():
            w = max(0, min(40, w + random.choice([-2, -1, 0, 1, 1, 2])))
            c.execute("UPDATE hospitals SET walk_in=? WHERE id=?", (w, hid))
            c.execute("INSERT INTO history VALUES(?,?,?)", (hid, time.time(), w))
        c.execute("DELETE FROM history WHERE ts<?", (time.time() - 600,))
        c.commit()
        c.close()

def main():
    init_db()
    if app.secret_key == "dev-only-change-me":
        print("WARNING: using the default SECRET_KEY. Set SECRET_KEY before any real deployment.")
    if os.environ.get("SIMULATE", "1") == "1":   # set SIMULATE=0 when a real camera feeds the counts
        threading.Thread(target=simulator, daemon=True).start()
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")),
            debug=False, use_reloader=False)

if __name__ == "__main__":
    main()
