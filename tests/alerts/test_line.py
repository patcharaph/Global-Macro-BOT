"""Tests for flowmacro.alerts.line — LINE Messaging API push notifications."""
from unittest.mock import patch, MagicMock

from flowmacro.alerts.line import send_line, _MAX_CHARS


def _make_response(status_code: int, text: str = "error body"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


# ── Missing credentials ────────────────────────────────────────────────────

@patch("flowmacro.alerts.line.requests.post")
@patch("flowmacro.alerts.line.settings")
def test_missing_token_skips_without_request(mock_settings, mock_post):
    mock_settings.line_channel_access_token = ""
    mock_settings.line_user_id = "Uabc"

    assert send_line("hello") is False
    mock_post.assert_not_called()


@patch("flowmacro.alerts.line.requests.post")
@patch("flowmacro.alerts.line.settings")
def test_missing_user_id_skips_without_request(mock_settings, mock_post):
    mock_settings.line_channel_access_token = "token"
    mock_settings.line_user_id = ""

    assert send_line("hello") is False
    mock_post.assert_not_called()


# ── Successful push ────────────────────────────────────────────────────────

@patch("flowmacro.alerts.line.requests.post")
@patch("flowmacro.alerts.line.settings")
def test_successful_push_returns_true_with_correct_payload(mock_settings, mock_post):
    mock_settings.line_channel_access_token = "token-123"
    mock_settings.line_user_id = "Uabc"
    mock_post.return_value = _make_response(200)

    result = send_line("hello world")

    assert result is True
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer token-123"
    assert kwargs["json"]["to"] == "Uabc"
    assert kwargs["json"]["messages"] == [{"type": "text", "text": "hello world"}]


# ── Retry / backoff ────────────────────────────────────────────────────────

@patch("flowmacro.alerts.line.time.sleep")
@patch("flowmacro.alerts.line.requests.post")
@patch("flowmacro.alerts.line.settings")
def test_retries_on_non_200_then_succeeds(mock_settings, mock_post, mock_sleep):
    mock_settings.line_channel_access_token = "token"
    mock_settings.line_user_id = "Uabc"
    mock_post.side_effect = [_make_response(500), _make_response(200)]

    result = send_line("hello")

    assert result is True
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once_with(2)


@patch("flowmacro.alerts.line.time.sleep")
@patch("flowmacro.alerts.line.requests.post")
@patch("flowmacro.alerts.line.settings")
def test_retries_on_request_exception_then_succeeds(mock_settings, mock_post, mock_sleep):
    mock_settings.line_channel_access_token = "token"
    mock_settings.line_user_id = "Uabc"
    mock_post.side_effect = [ConnectionError("network down"), _make_response(200)]

    result = send_line("hello")

    assert result is True
    mock_sleep.assert_called_once_with(2)


@patch("flowmacro.alerts.line.time.sleep")
@patch("flowmacro.alerts.line.requests.post")
@patch("flowmacro.alerts.line.settings")
def test_returns_false_after_all_retries_exhausted(mock_settings, mock_post, mock_sleep):
    mock_settings.line_channel_access_token = "token"
    mock_settings.line_user_id = "Uabc"
    mock_post.return_value = _make_response(500)

    result = send_line("hello")

    assert result is False
    assert mock_post.call_count == 3
    assert [c.args[0] for c in mock_sleep.call_args_list] == [2, 4]


# ── Message truncation ─────────────────────────────────────────────────────

@patch("flowmacro.alerts.line.requests.post")
@patch("flowmacro.alerts.line.settings")
def test_long_message_is_truncated_to_max_chars(mock_settings, mock_post):
    mock_settings.line_channel_access_token = "token"
    mock_settings.line_user_id = "Uabc"
    mock_post.return_value = _make_response(200)

    send_line("x" * (_MAX_CHARS + 500))

    sent_text = mock_post.call_args.kwargs["json"]["messages"][0]["text"]
    assert len(sent_text) <= _MAX_CHARS
    assert sent_text.endswith("... (truncated)")


@patch("flowmacro.alerts.line.requests.post")
@patch("flowmacro.alerts.line.settings")
def test_short_message_is_not_truncated(mock_settings, mock_post):
    mock_settings.line_channel_access_token = "token"
    mock_settings.line_user_id = "Uabc"
    mock_post.return_value = _make_response(200)

    send_line("short message")

    sent_text = mock_post.call_args.kwargs["json"]["messages"][0]["text"]
    assert sent_text == "short message"
