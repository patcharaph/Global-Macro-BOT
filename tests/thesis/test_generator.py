import pytest
from unittest.mock import patch, MagicMock
from flowmacro.thesis.generator import _validate, generate_thesis, ThesisResult

_GOOD_JSON = '{"recommendation": "ถือ risk-on assets", "conviction": 7, "reasoning": "Growth สูง inflation ต่ำ", "risks": "Fed อาจ hawkish เกิน"}'
_GOOD_FENCED = '```json\n' + _GOOD_JSON + '\n```'


def test_validate_good_json():
    result = _validate(_GOOD_JSON)
    assert result["conviction"] == 7
    assert result["recommendation"] == "ถือ risk-on assets"


def test_validate_strips_code_fence():
    result = _validate(_GOOD_FENCED)
    assert result["conviction"] == 7


def test_validate_missing_field():
    bad = '{"recommendation": "ok", "conviction": 5, "reasoning": "r"}'
    with pytest.raises(ValueError, match="missing fields"):
        _validate(bad)


def test_validate_conviction_out_of_range():
    bad = '{"recommendation": "ok", "conviction": 11, "reasoning": "r", "risks": "s"}'
    with pytest.raises(ValueError, match="conviction must be int 1-10"):
        _validate(bad)


def test_validate_conviction_float_rejected():
    bad = '{"recommendation": "ok", "conviction": 7.5, "reasoning": "r", "risks": "s"}'
    with pytest.raises(ValueError, match="conviction must be int 1-10"):
        _validate(bad)


def test_validate_empty_string_rejected():
    bad = '{"recommendation": "", "conviction": 5, "reasoning": "r", "risks": "s"}'
    with pytest.raises(ValueError, match="non-empty string"):
        _validate(bad)


def test_validate_invalid_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        _validate("not json at all")


def test_generate_thesis_no_api_key(monkeypatch):
    monkeypatch.setattr("flowmacro.thesis.generator.settings.openrouter_api_key", "")
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        generate_thesis("GOLDILOCKS", 80.0, 65.0, 35.0)


def test_generate_thesis_calls_openrouter(monkeypatch):
    monkeypatch.setattr("flowmacro.thesis.generator.settings.openrouter_api_key", "test-key")

    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": _GOOD_JSON}}]
    }

    with patch("flowmacro.thesis.generator.requests.post", return_value=mock_resp) as mock_post:
        result = generate_thesis("GOLDILOCKS", 80.0, 65.0, 35.0)

    assert isinstance(result, ThesisResult)
    assert result.regime == "GOLDILOCKS"
    assert result.conviction == 7
    assert result.model == "anthropic/claude-sonnet-4-5"

    call_payload = mock_post.call_args.kwargs["json"]
    assert call_payload["model"] == "anthropic/claude-sonnet-4-5"
    assert call_payload["temperature"] == 0.3
    # Verify regime info appears in user message
    user_content = call_payload["messages"][1]["content"]
    assert "GOLDILOCKS" in user_content
    assert "80.0%" in user_content
