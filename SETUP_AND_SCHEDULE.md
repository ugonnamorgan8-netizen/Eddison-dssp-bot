# DSSP Daily Updater — Setup & Scheduling Guide

## 1. Prerequisites
- Python 3.10 or newer: https://www.python.org/downloads/
- pip up-to-date: `python -m pip install --upgrade pip`

---

## 1a. Dashboard Login

The web dashboard is protected by a login screen.

| Setting | Default |
|---|---|
| **Username** | `admin` |
| **Password** | `admin1234` |
| **URL** | http://localhost:5050 |

> Credentials live in `.env` as `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD`.

### Changing the password

Run this once to generate a new bcrypt hash, then paste it into `.env`:

```powershell
python -c "import bcrypt; print(bcrypt.hashpw(b'YOURNEWPASSWORD', bcrypt.gensalt(12)).decode())"
```

Set `DASHBOARD_PASSWORD=<output>` in `.env`.

---


## 2. Project Structure
```
DSSP Automation/
├── dssp_daily_updater.py   ← main script
├── .env.example            ← copy → .env, then fill in credentials
├── students.csv            ← input/output data
├── logs/                   ← auto-created; daily_update_YYYY-MM-DD.log
└── screenshots/errors/     ← auto-created; PNG screenshots on failure
```

---

## 3. Install Dependencies

> ⚠️ **Important – Multiple Python versions detected on this machine.**  
> Use `py -3.13` explicitly for all commands. Do **not** use bare `python` or `python3`,  
> as those may resolve to a different version (e.g. 3.14) that does not have the packages.

Open PowerShell in the `DSSP Automation` folder:

```powershell
# Install packages directly into Python 3.13 (user install)
py -3.13 -m pip install playwright pandas python-dotenv tqdm

# Download Chromium browser binary (required by Playwright)
py -3.13 -m playwright install chromium
```

✅ **Already done** — if you followed the steps above, these are complete.

---

## 4. Configure Credentials

```powershell
# Copy the template and edit it
copy .env.example .env
notepad .env
```

Fill in:
```
DSSP_USERNAME=your_actual_username
DSSP_PASSWORD=your_actual_password
HEADLESS=True   # change to False to watch the browser (useful for debugging)
```

> ⚠️ **SECURITY**: Never commit `.env` to Git.  Add it to `.gitignore`.

---

## 5. Customise Navigation Selectors (IMPORTANT)

The script contains placeholder selectors marked  `←←← USER: INSERT YOUR EXACT ...`.
You **must** replace these before the script can run successfully:

1. Set `HEADLESS=False` in `.env`.
2. Open the portal manually in Chrome, press **F12** (DevTools).
3. Use the **Inspector** (pick element) to find the correct CSS selectors for:
   - Login username field
   - Login password field
   - Login submit button
   - Student search input
   - Search submit button
   - Session date field
   - Session status dropdown
   - Save/submit button
   - Success confirmation text
   - Logout link
4. Replace the placeholder selectors in `dssp_daily_updater.py`.
5. Set `HEADLESS=True` again for production.

---

## 6. Test Run (Manual)

```powershell
py -3.13 dssp_daily_updater.py
```

Expected output:
```
08:00:01 | INFO     | DSSP Daily Updater — 2026-03-24
08:00:01 | INFO     | Mode: HEADLESS
08:00:01 | INFO     | Loaded 4 rows from students.csv
08:00:01 | INFO     | 3 student(s) due for update ...
Updating students: 100%|████████████| 3/3 [00:45<00:00, 15s/student]
08:00:47 | INFO     | SUMMARY: 3 student(s) updated successfully, 0 failed.
```

---

## 7. Schedule Daily via Windows Task Scheduler

### Method A — Import XML (easiest)

1. Save the XML below as `DSSP_Task.xml`.
2. Open **Task Scheduler** → **Action → Import Task** → select `DSSP_Task.xml`.
3. Edit the `<Command>` and `<WorkingDirectory>` paths to match your system.

```xml
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-03-25T08:00:00</StartBoundary>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>C:\Windows\py.exe</Command>
      <Arguments>-3.13 dssp_daily_updater.py</Arguments>
      <WorkingDirectory>C:\Users\LENOVO\Desktop\DSSP Automation</WorkingDirectory>
    </Exec>
  </Actions>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd></IdleSettings>
  </Settings>
</Task>
```

### Method B — PowerShell one-liner

```powershell
$action  = New-ScheduledTaskAction `
           -Execute "C:\Windows\py.exe" `
           -Argument "-3.13 dssp_daily_updater.py" `
           -WorkingDirectory "C:\Users\LENOVO\Desktop\DSSP Automation"

$trigger = New-ScheduledTaskTrigger -Daily -At 8:00AM

Register-ScheduledTask `
    -TaskName "DSSP Daily Updater" `
    -Action $action `
    -Trigger $trigger `
    -RunLevel Highest `
    -Force
```

---

## 8. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `DSSP_USERNAME … missing` | Copy `.env.example` → `.env`, fill credentials |
| `TimeoutError` on selector | Re-inspect portal HTML; update selector in script |
| Screenshot in `screenshots/errors/` | Review the captured image + log for clues |
| Task Scheduler shows `0x1` exit code | At least one student failed; check today's log file |
| Browser visible but no action | Wrong selectors; switch to `HEADLESS=False` and debug |

---

## 9. Adding/Removing Students

Edit `students.csv` directly.  Rules:
- `student_name` — full name as appears on portal
- `dssp_id` — portal ID prefixed with `DSSP-` (or blank if unknown; name used instead)
- `current_sessions` — integer; script increments this on each successful update
- `last_updated_date` — `YYYY-MM-DD`; blank = always process
