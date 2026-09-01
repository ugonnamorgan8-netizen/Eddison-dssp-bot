"""
DSSP Daily Updater - Fast Version
=================================
Speed improvements:
  - No browser dependency for login and trainee scraping
  - Concurrent threading - processes multiple students simultaneously
  - CSRF token cached per student - one fetch per student, not per day
  - Reduced wait times throughout
  - All 7 days including weekends
"""

import html
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_URL = "https://dssp.frsc.gov.ng"
LOGIN_URL = f"{BASE_URL}/Account/Login"
TRAINEES_URL = f"{BASE_URL}/Trainee"
LOG_TRAINING = f"{BASE_URL}/Trainee/LogTraining"
MAX_DAYS = 25
PAGE_SIZE = 50
HTTP_TIMEOUT = 60
MAX_WORKERS = 3
LOG_DIR = Path("logs")
SCREENSHOT_DIR = Path("screenshots")

TRAINING_OPTION = {
    "Classroom": "1",
    "Practical": "2",
    "CBT Test": "3",
}


def training_type_for_day(day: int) -> str:
    if day <= 5:
        return "Classroom"
    if day == 11:
        return "CBT Test"
    return "Practical"


LOG_DIR.mkdir(exist_ok=True)
SCREENSHOT_DIR.mkdir(exist_ok=True)
today_str = datetime.now().strftime("%Y-%m-%d")
log_file = LOG_DIR / f"daily_update_{today_str}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("DSSP")
log_lock = threading.Lock()


def log(level: str, msg: str) -> None:
    with log_lock:
        getattr(logger, level)(msg)


def create_portal_session() -> requests.Session:
    """Create a DSSP session that ignores broken machine-level proxy settings."""
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    return session


def clone_authenticated_session(source: requests.Session) -> requests.Session:
    """Copy cookies and headers into a fresh session for worker threads."""
    session = create_portal_session()
    session.headers.update(source.headers)
    session.cookies.update(source.cookies)
    return session


def extract_hidden_token(page_html: str) -> str:
    match = re.search(
        r'name="__RequestVerificationToken"[^>]+value="([^"]+)"',
        page_html,
        re.IGNORECASE,
    )
    return match.group(1) if match else ""


def clean_html_text(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", " ", fragment, flags=re.IGNORECASE)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return " ".join(html.unescape(fragment).split())


def login_portal(username: str, password: str) -> requests.Session:
    """Log in with requests and return an authenticated session."""
    log("info", "Logging in ...")
    session = create_portal_session()

    login_page = session.get(LOGIN_URL, timeout=HTTP_TIMEOUT)
    login_page.raise_for_status()
    token = extract_hidden_token(login_page.text)
    if not token:
        raise RuntimeError("Could not find DSSP login CSRF token.")

    payload = {
        "__RequestVerificationToken": token,
        "Email": username,
        "Password": password,
        "RememberMe": "false",
    }
    response = session.post(LOGIN_URL, data=payload, allow_redirects=True, timeout=HTTP_TIMEOUT)
    response.raise_for_status()

    if "account/login" in response.url.lower() or "Use a local account to log in." in response.text:
        raise RuntimeError("Login failed - check credentials in .env")

    log("info", "Login successful.")
    return session


def make_requests_session(source_session: requests.Session) -> requests.Session:
    """Create a per-thread session from the authenticated DSSP session."""
    session = clone_authenticated_session(source_session)
    session.headers.update(
        {
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": BASE_URL,
        }
    )
    return session


def get_all_trainees(session: requests.Session) -> list[dict]:
    """Scrape all enrolled trainees over plain HTTP."""
    trainees = []
    seen_ids = set()

    first_page = session.get(f"{TRAINEES_URL}?page=1&pgsize={PAGE_SIZE}", timeout=HTTP_TIMEOUT)
    first_page.raise_for_status()
    first_html = first_page.text

    last_page = 1
    match = re.search(
        r'<a[^>]+href="[^"]*page=(\d+)[^"]*"[^>]*>\s*Last\s*</a>',
        first_html,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        last_page = int(match.group(1))
    log("info", f"Pages to scrape: {last_page} (pgsize={PAGE_SIZE})")

    for page_num in range(1, last_page + 1):
        log("info", f"Scraping page {page_num}/{last_page} ...")
        page_html = first_html
        if page_num > 1:
            response = session.get(
                f"{TRAINEES_URL}?page={page_num}&pgsize={PAGE_SIZE}",
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status()
            page_html = response.text

        tbody = re.search(r"<tbody[^>]*>(.*?)</tbody>", page_html, re.IGNORECASE | re.DOTALL)
        if not tbody:
            break

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbody.group(1), re.IGNORECASE | re.DOTALL)
        if not rows:
            break

        for row_html in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.IGNORECASE | re.DOTALL)
            if len(cells) < 8:
                continue

            cleaned_cells = [clean_html_text(cell) for cell in cells]
            name = cleaned_cells[2]
            if not name or name.lower() == "name":
                continue

            try:
                sessions = int(cleaned_cells[7])
            except ValueError:
                sessions = 0

            trainee_id_match = re.search(r"TraineeId=(\d+)", row_html, re.IGNORECASE)
            trainee_id = trainee_id_match.group(1) if trainee_id_match else None
            if not trainee_id or trainee_id in seen_ids:
                continue

            seen_ids.add(trainee_id)
            trainees.append({"id": trainee_id, "name": name, "sessions": sessions})

    log("info", f"Total trainees found: {len(trainees)}")
    return trainees


def get_csrf_token(session: requests.Session, trainee_id: str) -> str:
    """Fetch a CSRF token for a trainee training-log page."""
    url = f"{BASE_URL}/Trainee/TrainingLog?TraineeId={trainee_id}"
    resp = session.get(url, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return extract_hidden_token(resp.text)


def get_instructor_id(session: requests.Session, trainee_id: str) -> str:
    """Auto-detect the first available instructor from the training log page."""
    url = f"{BASE_URL}/Trainee/TrainingLog?TraineeId={trainee_id}"
    resp = session.get(url, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    match = re.search(r'id="InstructorId".*?<option value="(\d+)"', resp.text, re.DOTALL)
    if match:
        return match.group(1)
    return os.getenv("DEFAULT_INSTRUCTOR_ID", "21598").strip()


def post_training_log(
    session: requests.Session,
    trainee_id: str,
    log_date: datetime,
    day_number: int,
    token: str,
    instructor_id: str,
) -> bool:
    """POST one training log entry directly to the server."""
    training_type = training_type_for_day(day_number)
    option_id = TRAINING_OPTION[training_type]
    date_str = log_date.strftime("%Y-%m-%d")

    payload = {
        "LogDetails.TraineeId": trainee_id,
        "LogDetails.TrainingDate": date_str,
        "LogDetails.InstructorId": instructor_id,
        "LogDetails.TrainingOptionId": option_id,
        "__RequestVerificationToken": token,
    }

    try:
        resp = session.post(LOG_TRAINING, data=payload, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()
        if result.get("IsSuccessful"):
            log("info", f"  OK [{trainee_id}] Day {day_number} ({training_type}) on {date_str}")
            return True

        log("warning", f"  FAIL [{trainee_id}] Day {day_number} failed: {result.get('Message', '?')}")
        return False
    except Exception as exc:
        log("error", f"  FAIL [{trainee_id}] POST error day {day_number}: {exc}")
        return False


def process_trainee(session: requests.Session, trainee: dict) -> int:
    """Process one trainee - fetch token once, then post all missing days."""
    trainee_id = trainee["id"]
    name = trainee["name"]
    done = trainee["sessions"]
    to_add = MAX_DAYS - done

    log("info", f"> {name} | {done}/{MAX_DAYS} done | Adding {to_add}")

    token = get_csrf_token(session, trainee_id)
    instructor_id = get_instructor_id(session, trainee_id)

    dates = []
    candidate = datetime.now()
    while len(dates) < to_add:
        dates.insert(0, candidate)
        candidate -= timedelta(days=1)

    added = 0
    for i, log_date in enumerate(dates):
        day_num = done + i + 1
        if day_num > MAX_DAYS:
            break
        if i > 0 and i % 5 == 0:
            token = get_csrf_token(session, trainee_id)
        if post_training_log(session, trainee_id, log_date, day_num, token, instructor_id):
            added += 1

    log("info", f"  Done: {name} - +{added} days. Total: {done + added}/{MAX_DAYS}")
    return added


def main() -> None:
    load_dotenv()
    username = os.getenv("DSSP_USERNAME", "").strip()
    password = os.getenv("DSSP_PASSWORD", "").strip()

    if not username or not password:
        print("[FATAL] DSSP_USERNAME and/or DSSP_PASSWORD missing from .env.")
        return

    log("info", "=" * 60)
    log("info", f"DSSP Daily Updater - {today_str} (FAST MODE)")
    log("info", f"Concurrent workers: {MAX_WORKERS}")
    log("info", "=" * 60)

    total_updated = 0
    total_skipped = 0
    total_failed = 0
    results_lock = threading.Lock()

    try:
        auth_session = login_portal(username, password)
        trainees = get_all_trainees(auth_session)
        needs_work = [t for t in trainees if t["sessions"] < MAX_DAYS]
        complete = [t for t in trainees if t["sessions"] >= MAX_DAYS]

        log("info", f"Need updates : {len(needs_work)}")
        log("info", f"Already at 25: {len(complete)}")
        log("info", "=" * 60)
    except Exception as exc:
        log("critical", f"Fatal error during setup: {exc}")
        return

    def worker(trainee: dict) -> int:
        nonlocal total_updated, total_skipped, total_failed
        session = make_requests_session(auth_session)
        try:
            added = process_trainee(session, trainee)
            with results_lock:
                if added > 0:
                    total_updated += 1
                else:
                    total_skipped += 1
            return added
        except Exception as exc:
            log("error", f"Failed for {trainee['name']}: {exc}")
            with results_lock:
                total_failed += 1
            return 0

    log("info", f"Processing {len(needs_work)} students with {MAX_WORKERS} parallel workers ...")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(worker, trainee): trainee for trainee in needs_work}
        for i, future in enumerate(as_completed(futures), 1):
            trainee = futures[future]
            try:
                future.result()
                log("info", f"[{i}/{len(needs_work)}] Completed: {trainee['name']}")
            except Exception as exc:
                log("error", f"[{i}/{len(needs_work)}] Error: {trainee['name']}: {exc}")

    log("info", "=" * 60)
    log("info", f"SUMMARY - Updated: {total_updated} | Skipped: {total_skipped} | Failed: {total_failed}")
    log("info", "=" * 60)


if __name__ == "__main__":
    main()
