"""Tests for flowmacro.alerts.gmail — retry and backoff behavior."""
from unittest.mock import patch, MagicMock
import pytest

from flowmacro.alerts.gmail import send_alert


def _make_smtp(fail_times: int = 0):
    """Context-manager mock for smtplib.SMTP that fails `fail_times` then succeeds."""
    call_count = {"n": 0}

    class FakeSMTP:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self): pass
        def login(self, *a): pass
        def sendmail(self, *a):
            call_count["n"] += 1
            if call_count["n"] <= fail_times:
                raise OSError("connection refused")

    return FakeSMTP


# ── Cycle 5: Gmail retry delay doubles each attempt ───────────────────────────

@patch("flowmacro.alerts.gmail.time.sleep")
@patch("flowmacro.alerts.gmail.smtplib.SMTP")
@patch("flowmacro.alerts.gmail.settings")
def test_send_alert_retry_delay_doubles(mock_settings, mock_smtp, mock_sleep):
    mock_settings.gmail_sender = "a@b.com"
    mock_settings.gmail_app_password = "pw"
    mock_settings.gmail_recipient = "r@b.com"
    mock_smtp.return_value = _make_smtp(fail_times=2)()

    send_alert("subject", "body")

    delays = [c.args[0] for c in mock_sleep.call_args_list]
    assert delays == [2, 4]  # exponential: 2s → 4s
