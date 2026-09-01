"""
DSSP Notifier — Email summary after each run.
=============================================
Set NOTIFY_EMAIL, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS in .env
to enable. If any variable is missing, notifications are silently skipped.
"""

import os
import smtplib
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("DSSP.notifier")


def _cfg():
    """Return SMTP config dict, or None if any required var is missing."""
    keys = ("NOTIFY_EMAIL", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS")
    vals = {k: os.getenv(k, "").strip() for k in keys}
    if not all(vals.values()):
        return None
    try:
        vals["SMTP_PORT"] = int(vals["SMTP_PORT"])
    except ValueError:
        logger.warning("SMTP_PORT is not a valid integer — notifications disabled.")
        return None
    return vals


def send_run_summary(status: str, summary: dict, log_path: str = ""):
    """
    Send an email notification after a run completes.

    Parameters
    ----------
    status   : "done" | "error"
    summary  : dict with keys updated, skipped, failed
    log_path : absolute path to the log file (optional, shown in email)
    """
    cfg = _cfg()
    if not cfg:
        return  # Notifications not configured — silently skip

    updated = summary.get("updated", "—")
    skipped = summary.get("skipped", "—")
    failed  = summary.get("failed",  "—")
    now     = datetime.now().strftime("%d %b %Y at %H:%M")
    icon    = "✅" if status == "done" else "❌"

    subject = f"{icon} DSSP Update {'Completed' if status == 'done' else 'Failed'} — {now}"

    # Plain-text body
    text_body = f"""DSSP Daily Update — Run Report
==============================
Time    : {now}
Status  : {status.upper()}

Results
-------
Updated : {updated}
Skipped : {skipped}
Failed  : {failed}

Log file: {log_path or 'N/A'}

──────────────────────────────
This is an automated message from your DSSP Dashboard.
"""

    # HTML body
    status_color = "#22c55e" if status == "done" else "#ef4444"
    status_label = "COMPLETED" if status == "done" else "FAILED"

    html_body = f"""
<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px;">
  <div style="max-width:520px;margin:auto;background:#1e293b;border-radius:12px;
              padding:32px;border:1px solid #334155;">
    <h2 style="margin:0 0 4px;color:#f8fafc;">DSSP Daily Update</h2>
    <p style="margin:0 0 24px;color:#94a3b8;font-size:13px;">{now}</p>

    <div style="background:{status_color}22;border:1px solid {status_color};
                border-radius:8px;padding:12px 16px;margin-bottom:24px;">
      <span style="color:{status_color};font-weight:bold;font-size:15px;">
        {icon} {status_label}
      </span>
    </div>

    <table style="width:100%;border-collapse:collapse;">
      <tr>
        <td style="padding:10px 0;border-bottom:1px solid #334155;color:#94a3b8;">Updated</td>
        <td style="padding:10px 0;border-bottom:1px solid #334155;
                   color:#22c55e;font-weight:bold;text-align:right;">{updated}</td>
      </tr>
      <tr>
        <td style="padding:10px 0;border-bottom:1px solid #334155;color:#94a3b8;">Skipped</td>
        <td style="padding:10px 0;border-bottom:1px solid #334155;
                   color:#f59e0b;font-weight:bold;text-align:right;">{skipped}</td>
      </tr>
      <tr>
        <td style="padding:10px 0;color:#94a3b8;">Failed</td>
        <td style="padding:10px 0;color:#ef4444;font-weight:bold;
                   text-align:right;">{failed}</td>
      </tr>
    </table>

    {"<p style='margin-top:20px;font-size:12px;color:#64748b;word-break:break-all;'>Log: " + log_path + "</p>" if log_path else ""}

    <p style="margin-top:28px;font-size:11px;color:#475569;border-top:1px solid #334155;
              padding-top:16px;">Automated message · DSSP Automation Dashboard</p>
  </div>
</body>
</html>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = cfg["SMTP_USER"]
    msg["To"]      = cfg["NOTIFY_EMAIL"]
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
            server.sendmail(cfg["SMTP_USER"], cfg["NOTIFY_EMAIL"], msg.as_string())
        logger.info(f"[NOTIFIER] Email sent to {cfg['NOTIFY_EMAIL']}")
    except Exception as e:
        logger.warning(f"[NOTIFIER] Failed to send email: {e}")
