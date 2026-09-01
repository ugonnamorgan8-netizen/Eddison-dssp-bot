"""
DSSP Premium Dashboard Server
==============================
Flask server that wraps dssp_daily_updater.py without modifying it.
Features: Run Now, Schedule (internet-aware retry), Cancel, Log Streaming.

Security: Login-protected, CSRF tokens, rate limiting, security headers,
          path-traversal-safe log serving.
"""

import os
import hmac
import json
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue, Empty
from functools import wraps

import bcrypt
from dotenv import load_dotenv
from flask import (
    Flask, render_template, Response, jsonify, request,
    redirect, url_for, session, flash
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from apscheduler.schedulers.background import BackgroundScheduler

load_dotenv()

# ─── CONFIG ────────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
LOG_DIR        = BASE_DIR / "logs"
SCRIPT_PATH    = BASE_DIR / "dssp_daily_updater.py"
STATE_FILE     = BASE_DIR / "scheduler_state.json"
PORT           = int(os.getenv("PORT", 5050))
CHECK_INTERVAL = 30   # seconds between internet retries

# ─── FLASK SETUP ───────────────────────────────────────────────────────────────
app = Flask(__name__)

# Secret key — MUST be set in .env for production; fallback only for local dev
app.secret_key = os.getenv("SECRET_KEY", os.urandom(32))

# CSRF protection
csrf = CSRFProtect(app)

# Rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

# ─── AUTH CONFIG ───────────────────────────────────────────────────────────────
_DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "admin")
_DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "change_me")


def _check_password(plain: str) -> bool:
    """Compare plain-text login attempt against the stored credential.
    Accepts either a bcrypt hash (starts with $2b$) or a plain string
    so the dashboard still works with a simple password in .env."""
    stored = _DASHBOARD_PASSWORD
    if stored.startswith("$2b$"):
        return bcrypt.checkpw(plain.encode(), stored.encode())
    return hmac.compare_digest(plain, stored)


def login_required(f):
    """Decorator: redirect to /login if the user session is not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


# ─── SECURITY HEADERS ──────────────────────────────────────────────────────────
@app.after_request
def set_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "script-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    return response


# ─── GLOBAL STATE ──────────────────────────────────────────────────────────────
state = {
    "running":      False,
    "last_run":     None,
    "last_status":  "idle",   # idle | running | done | error
    "summary":      {"updated": 0, "skipped": 0, "failed": 0},
    "scheduled_at": None,     # "HH:MM" string or None
    "next_run":     None,     # ISO string of next scheduled run
}
state_lock = threading.Lock()

# SSE subscribers: list of Queue objects
log_subscribers = []
subs_lock = threading.Lock()

process_ref = [None]   # holds the running Popen subprocess


# ─── INTERNET CHECK ─────────────────────────────────────────────────────────────
def has_internet(host="8.8.8.8", port=53, timeout=3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return True
    except (socket.error, OSError):
        return False


# ─── SSE HELPERS ───────────────────────────────────────────────────────────────
def broadcast(line: str):
    """Send a log line to all connected SSE clients."""
    dead = []
    with subs_lock:
        for q in log_subscribers:
            try:
                q.put_nowait(line)
            except Exception:
                dead.append(q)
        for q in dead:
            log_subscribers.remove(q)


def parse_summary(log_path: Path):
    """Extract Updated/Skipped/Failed from the SUMMARY line."""
    s = {"updated": 0, "skipped": 0, "failed": 0}
    try:
        text = log_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "SUMMARY" in line and "Updated:" in line:
                import re
                m = re.search(r"Updated:\s*(\d+).*Skipped:\s*(\d+).*Failed:\s*(\d+)", line)
                if m:
                    s["updated"] = int(m.group(1))
                    s["skipped"] = int(m.group(2))
                    s["failed"]  = int(m.group(3))
    except Exception:
        pass
    return s


# ─── RUN SCRIPT ────────────────────────────────────────────────────────────────
def _run_script():
    """Spawns dssp_daily_updater.py and streams its output to all SSE clients."""
    import sys
    with state_lock:
        if state["running"]:
            return
        state["running"]     = True
        state["last_status"] = "running"
        state["last_run"]    = datetime.now().isoformat()

    today = datetime.now().strftime("%Y-%m-%d")
    log_path = LOG_DIR / f"daily_update_{today}.log"

    broadcast(f"[DASHBOARD] Starting updater — {datetime.now().strftime('%H:%M:%S')}")

    try:
        proc = subprocess.Popen(
            [sys.executable, str(SCRIPT_PATH)],
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
        process_ref[0] = proc

        for line in proc.stdout:
            line = line.rstrip()
            if line:
                broadcast(line)

        proc.wait()
        exit_ok = proc.returncode == 0

    except Exception as e:
        broadcast(f"[DASHBOARD ERROR] {e}")
        exit_ok = False

    finally:
        process_ref[0] = None

    summary = parse_summary(log_path) if log_path.exists() else {}
    with state_lock:
        state["running"]     = False
        state["last_status"] = "done" if exit_ok else "error"
        state["summary"]     = summary

    broadcast(f"[DASHBOARD] Run complete — status: {state['last_status']}")


def run_script_thread():
    t = threading.Thread(target=_run_script, daemon=True)
    t.start()


# ─── SCHEDULER ─────────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler(daemon=True)
scheduler.start()

# ─── MODULE-LEVEL INIT (runs under gunicorn AND __main__) ─────────────────────
_retry_thread = [None]   # holds the internet-wait thread


def _scheduled_job():
    """Called by APScheduler at the configured time. Waits for internet then runs."""
    broadcast("[SCHEDULER] Scheduled time reached — checking internet...")

    def wait_and_run():
        waited = False
        while not has_internet():
            if not waited:
                broadcast("[SCHEDULER] No internet — retrying every 30s...")
                waited = True
            time.sleep(CHECK_INTERVAL)

        broadcast("[SCHEDULER] Internet available — launching updater.")
        run_script_thread()

    t = threading.Thread(target=wait_and_run, daemon=True)
    _retry_thread[0] = t
    t.start()


def _save_state():
    try:
        with STATE_FILE.open("w") as f:
            json.dump({"scheduled_at": state["scheduled_at"]}, f)
    except Exception:
        pass


def _load_state():
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
            if data.get("scheduled_at"):
                _apply_schedule(data["scheduled_at"], persist=False)
    except Exception:
        pass


def _apply_schedule(time_str: str, persist=True):
    """Set or replace the daily scheduled job."""
    try:
        hour, minute = map(int, time_str.split(":"))
    except ValueError:
        return False

    if scheduler.get_job("daily_run"):
        scheduler.remove_job("daily_run")

    scheduler.add_job(
        _scheduled_job,
        trigger="cron",
        hour=hour,
        minute=minute,
        id="daily_run",
        replace_existing=True,
        misfire_grace_time=None,
    )

    now = datetime.now()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)

    with state_lock:
        state["scheduled_at"] = time_str
        state["next_run"]     = next_run.isoformat()

    if persist:
        _save_state()
    return True


# ─── AUTH ROUTES ───────────────────────────────────────────────────────────────

def _initialize_runtime():
    """Run one-time initialization needed for both gunicorn and local runs."""
    LOG_DIR.mkdir(exist_ok=True)
    _load_state()


_initialize_runtime()


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login_page():
    if session.get("authenticated"):
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == _DASHBOARD_USERNAME and _check_password(password):
            session["authenticated"] = True
            session.permanent = False  # session expires when browser closes
            return redirect(url_for("index"))
        else:
            flash("Invalid username or password.", "error")
            return render_template("login.html"), 401

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ─── MAIN ROUTES ───────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/run", methods=["POST"])
@login_required
@limiter.limit("5 per minute")
def run_now():
    with state_lock:
        if state["running"]:
            return jsonify({"ok": False, "message": "Already running"})
    if not has_internet():
        return jsonify({"ok": False, "message": "No internet connection"})
    run_script_thread()
    return jsonify({"ok": True})


@app.route("/schedule", methods=["POST"])
@login_required
@limiter.limit("20 per minute")
def set_schedule():
    data = request.get_json(silent=True) or {}
    time_str = data.get("time", "08:00")
    ok = _apply_schedule(time_str)
    if ok:
        return jsonify({"ok": True, "next_run": state["next_run"], "scheduled_at": time_str})
    return jsonify({"ok": False, "message": "Invalid time format. Use HH:MM"})


@app.route("/cancel_schedule", methods=["POST"])
@login_required
@limiter.limit("20 per minute")
def cancel_schedule():
    if scheduler.get_job("daily_run"):
        scheduler.remove_job("daily_run")
    with state_lock:
        state["scheduled_at"] = None
        state["next_run"]     = None
    _save_state()
    return jsonify({"ok": True})


@app.route("/status")
@login_required
def status():
    with state_lock:
        return jsonify({
            "running":      state["running"],
            "last_status":  state["last_status"],
            "last_run":     state["last_run"],
            "scheduled_at": state["scheduled_at"],
            "next_run":     state["next_run"],
            "summary":      state["summary"],
        })


@app.route("/logs")
@login_required
def list_logs():
    LOG_DIR.mkdir(exist_ok=True)
    files = sorted(LOG_DIR.glob("daily_update_*.log"), reverse=True)
    return jsonify([f.name for f in files])


@app.route("/logs/<filename>")
@login_required
def get_log(filename):
    """Serve a log file — protected against path traversal attacks."""
    # Resolve the real absolute paths and confirm the file is inside LOG_DIR
    log_dir_resolved = LOG_DIR.resolve()
    try:
        safe_path = (LOG_DIR / filename).resolve()
    except Exception:
        return jsonify({"error": "Not found"}), 404

    # The resolved path must be inside LOG_DIR (blocks ../ traversal)
    # It must start with "daily_update_" and end with ".log"
    if (
        log_dir_resolved not in safe_path.parents
        or not safe_path.name.startswith("daily_update_")
        or safe_path.suffix != ".log"
        or not safe_path.is_file()
    ):
        return jsonify({"error": "Not found"}), 404

    return Response(
        safe_path.read_text(encoding="utf-8", errors="replace"),
        mimetype="text/plain"
    )


@app.route("/stream")
@login_required
@limiter.limit("10 per minute")
def stream():
    """Server-Sent Events endpoint — push log lines to browser in real time."""
    q = Queue()
    with subs_lock:
        log_subscribers.append(q)

    def event_stream():
        try:
            while True:
                try:
                    # Send heartbeats often enough that Gunicorn's sync worker
                    # is not treated as stalled while the SSE stream is idle.
                    line = q.get(timeout=10)
                    yield f"data: {line}\n\n"
                except Empty:
                    yield ": heartbeat\n\n"   # keep-alive
        except GeneratorExit:
            pass
        finally:
            with subs_lock:
                if q in log_subscribers:
                    log_subscribers.remove(q)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ─── ENTRY POINT ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Init already ran at module level above; just print banner and start dev server
    print(f"\n{'='*55}")
    print(f"  DSSP Dashboard -> http://localhost:{PORT}")
    print(f"  Login with DASHBOARD_USERNAME / DASHBOARD_PASSWORD from .env")
    print(f"{'='*55}\n")
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
