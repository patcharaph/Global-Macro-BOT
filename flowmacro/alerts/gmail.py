import smtplib
from email.mime.text import MIMEText
from loguru import logger
from flowmacro.config import settings

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587


def send_alert(subject: str, body: str) -> None:
    """Send a plain-text alert email via Gmail SMTP."""
    if not settings.gmail_sender or not settings.gmail_app_password:
        raise EnvironmentError("GMAIL_SENDER and GMAIL_APP_PASSWORD must be set in .env")

    recipient = settings.gmail_recipient or settings.gmail_sender

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"[FlowMacro] {subject}"
    msg["From"] = settings.gmail_sender
    msg["To"] = recipient

    with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(settings.gmail_sender, settings.gmail_app_password)
        smtp.sendmail(settings.gmail_sender, recipient, msg.as_string())

    logger.info(f"Alert sent → {recipient}: {subject}")
