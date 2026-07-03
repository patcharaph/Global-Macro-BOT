import time
import requests
from loguru import logger
from flowmacro.config import settings

_PUSH_URL = "https://api.line.me/v2/bot/message/push"
_MAX_CHARS = 4900   # LINE text message hard limit is 5000
_RETRIES = 3
_RETRY_BASE_DELAY = 2  # seconds; doubles each attempt


def send_line(message: str) -> bool:
    """Push a text message via the LINE Messaging API. Returns True on success."""
    if not settings.line_channel_access_token or not settings.line_user_id:
        logger.warning("LINE credentials not set — skipping LINE push")
        return False

    if len(message) > _MAX_CHARS:
        message = message[: _MAX_CHARS - 20] + "\n... (truncated)"

    headers = {
        "Authorization": f"Bearer {settings.line_channel_access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": settings.line_user_id,
        "messages": [{"type": "text", "text": message}],
    }

    delay = _RETRY_BASE_DELAY
    for attempt in range(1, _RETRIES + 1):
        try:
            resp = requests.post(_PUSH_URL, headers=headers, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info("LINE push sent")
                return True
            logger.warning(f"LINE push attempt {attempt}/{_RETRIES} failed: {resp.status_code} {resp.text}")
        except Exception as exc:
            logger.warning(f"LINE push attempt {attempt}/{_RETRIES} failed: {exc}")

        if attempt < _RETRIES:
            time.sleep(delay)
            delay *= 2

    logger.error("LINE push failed after all retries")
    return False
