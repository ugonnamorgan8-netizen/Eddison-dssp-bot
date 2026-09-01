---
title: DSSP Automation
emoji: 🚗
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# DSSP Automation Dashboard

A web-based automation dashboard for DSSP (Driver's Skill Standardisation Programme) training management. Automatically logs daily training sessions for enrolled students on the [FRSC DSSP portal](https://dssp.frsc.gov.ng), with a real-time monitoring dashboard.

---

## Features

- 🚀 **Run Now** — trigger the updater instantly from the browser
- 📅 **Daily Schedule** — set a time for automatic daily runs
- 📶 **Internet-aware retry** — if offline at scheduled time, runs automatically once connected
- 📊 **Live log streaming** — real-time output via Server-Sent Events
- 📁 **Log history** — browse and view logs from previous runs
- 🔒 **Secure login** — session auth with bcrypt-hashed passwords + CSRF protection
- 📧 **Email notifications** — get an email summary after each run *(optional)*
- ⚡ **Concurrent processing** — handles multiple students in parallel threads

---

## Requirements

- Python 3.10+
- Google Chrome (used internally by Playwright)

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/ugonnamorgan8-netizen/dssp-automation.git
cd dssp-automation
```

### 2. Create a virtual environment

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

| Variable | Description |
|---|---|
| `DSSP_USERNAME` | Your FRSC DSSP portal email |
| `DSSP_PASSWORD` | Your FRSC DSSP portal password |
| `DASHBOARD_USERNAME` | Username to log into this dashboard |
| `DASHBOARD_PASSWORD` | Password for this dashboard |
| `SECRET_KEY` | Random secret key for Flask sessions |
| `HEADLESS` | `True` for servers, `False` to see the browser |
| `NOTIFY_EMAIL` | *(Optional)* Email address to receive run summaries |
| `SMTP_HOST` | *(Optional)* SMTP server (e.g. `smtp.gmail.com`) |
| `SMTP_PORT` | *(Optional)* SMTP port (e.g. `587`) |
| `SMTP_USER` | *(Optional)* SMTP login email |
| `SMTP_PASS` | *(Optional)* SMTP password or app password |

Generate a secure `SECRET_KEY`:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 5. Add your student data

Place a `students.csv` file in the project root. This file is excluded from git (contains PII). The CSV should have at minimum a column for student names/IDs as used by the updater.

### 6. Run the dashboard

```bash
python dashboard.py
```

Open **http://localhost:5050** in your browser and log in.

---

## Usage

| Action | How |
|---|---|
| Run immediately | Click **Run Now** |
| Set daily schedule | Click **Set Schedule**, pick a time |
| Cancel schedule | Click **Cancel Schedule** |
| View live output | Watch the **Live Log** console |
| Browse past logs | Click **View Log History** |

---

## Security Notes

- `.env` is **never committed** — blocked by `.gitignore`
- `students.csv` is **never committed** — blocked by `.gitignore`
- All routes are login-protected
- CSRF tokens on every form/POST
- Rate limiting on login endpoint
- Secure HTTP headers (CSP, HSTS, X-Frame-Options, etc.)

---

## Project Structure

```
dssp-automation/
├── dashboard.py            # Flask web server & scheduler
├── dssp_daily_updater.py   # Core automation script
├── notifier.py             # Email notification module
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variable template
├── .gitignore
├── run_dashboard.bat       # Windows one-click launcher
├── templates/
│   ├── index.html          # Main dashboard UI
│   └── login.html          # Login page
└── static/
    ├── app.js              # Dashboard frontend logic
    └── style.css           # Stylesheet
```

---

## Deployment Notes

This app is designed to run on a **local Windows laptop** as a lightweight background service. For a always-on deployment, you can run it on any Linux VPS or cloud instance. Set `HEADLESS=True` in `.env` when running without a display.

---

## License

Private — internal use only.
