import smtplib
import time
from email.mime.text import MIMEText
from loguru import logger
from flowmacro.config import settings

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587
_RETRIES = 3
_RETRY_BASE_DELAY = 2  # seconds; doubles each attempt


def send_alert(subject: str, body: str) -> bool:
    """Send a plain-text alert email via Gmail SMTP. Returns True on success."""
    if not settings.gmail_sender or not settings.gmail_app_password:
        logger.warning("Gmail credentials not set — skipping alert: " + subject)
        return False

    recipient = settings.gmail_recipient or settings.gmail_sender

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"[FlowMacro] {subject}"
    msg["From"] = settings.gmail_sender
    msg["To"] = recipient

    delay = _RETRY_BASE_DELAY
    for attempt in range(1, _RETRIES + 1):
        try:
            with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=10) as smtp:
                smtp.starttls()
                smtp.login(settings.gmail_sender, settings.gmail_app_password)
                smtp.sendmail(settings.gmail_sender, recipient, msg.as_string())
            logger.info(f"Alert sent → {recipient}: {subject}")
            return True
        except Exception as exc:
            logger.warning(f"Gmail attempt {attempt}/{_RETRIES} failed: {exc}")
            if attempt < _RETRIES:
                time.sleep(delay)
                delay *= 2

    logger.error(f"Gmail alert failed after {_RETRIES} attempts: {subject}")
    return False
