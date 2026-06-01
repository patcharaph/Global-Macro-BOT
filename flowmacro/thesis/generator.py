import json
from dataclasses import dataclass
from datetime import date
import requests
from loguru import logger
from flowmacro.config import settings

_MODEL = "anthropic/claude-sonnet-4-5"
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_SYSTEM_PROMPT = """\
คุณคือนักวิเคราะห์เศรษฐกิจมหภาค (Global Macro Analyst) ที่เชี่ยวชาญด้าน regime-based investing
ตอบเป็นภาษาไทย กระชับ ตรงประเด็น ไม่เยิ่นเย้อ

ตอบเป็น JSON เท่านั้น ตาม schema นี้:
{
  "recommendation": "คำแนะนำสั้น 1-2 ประโยค",
  "conviction": <int 1-10>,
  "reasoning": "เหตุผล 2-3 ประโยค",
  "risks": "ความเสี่ยงหลัก 1-2 ประโยค"
}

conviction 1-10:
1-3 = ไม่มั่นใจ / signal หลอก
4-6 = กลางๆ / รอยืนยัน
7-9 = มั่นใจดี
10 = Strong conviction (ใช้ได้แค่เมื่อ signal ชัดเจนทุกด้าน)
"""


@dataclass
class ThesisResult:
    run_date: date
    regime: str
    confidence: float
    growth_score: float
    inflation_score: float
    recommendation: str
    conviction: int
    reasoning: str
    risks: str
    model: str = _MODEL


def generate_thesis(
    regime: str,
    confidence: float,
    growth_score: float,
    inflation_score: float,
) -> ThesisResult:
    """Call OpenRouter to generate a macro thesis for the current regime.

    Raises ValueError if the API key is missing or the response fails validation.
    """
    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY is not set")

    user_msg = (
        f"วันที่: {date.today()}\n"
        f"Regime: {regime}\n"
        f"Confidence: {confidence:.1f}%\n"
        f"Growth Score: {growth_score:.1f} (percentile rank, 50 = neutral)\n"
        f"Inflation Score: {inflation_score:.1f} (percentile rank, 50 = neutral)\n\n"
        f"วิเคราะห์ regime นี้และให้ macro thesis"
    )

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/flowmacro",
        "X-Title": "FlowMacro",
    }
    payload = {
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.3,
        "max_tokens": 512,
    }

    resp = requests.post(_OPENROUTER_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()

    raw_content = resp.json()["choices"][0]["message"]["content"]
    logger.debug(f"OpenRouter raw response: {raw_content[:200]}")

    validated = _validate(raw_content)
    return ThesisResult(
        run_date=date.today(),
        regime=regime,
        confidence=confidence,
        growth_score=growth_score,
        inflation_score=inflation_score,
        **validated,
        model=_MODEL,
    )


def _validate(content: str) -> dict:
    """Parse and validate LLM JSON output. Raises ValueError on schema violations."""
    # Strip markdown code fences if present
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response is not valid JSON: {exc}\nContent: {content[:300]}")

    required = {"recommendation", "conviction", "reasoning", "risks"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"LLM response missing fields: {missing}")

    conviction = data["conviction"]
    if not isinstance(conviction, int) or not (1 <= conviction <= 10):
        raise ValueError(f"conviction must be int 1-10, got: {conviction!r}")

    for field in ("recommendation", "reasoning", "risks"):
        if not isinstance(data[field], str) or not data[field].strip():
            raise ValueError(f"'{field}' must be a non-empty string")

    return {
        "recommendation": data["recommendation"].strip(),
        "conviction": conviction,
        "reasoning": data["reasoning"].strip(),
        "risks": data["risks"].strip(),
    }


def save_thesis(result: ThesisResult, client=None) -> str:
    """Save thesis to Supabase thesis_runs table. Returns the inserted row id."""
    if client is None:
        from flowmacro.data.store import _client
        client = _client()

    row = {
        "run_date":        str(result.run_date),
        "regime":          result.regime,
        "confidence":      result.confidence,
        "growth_score":    result.growth_score,
        "inflation_score": result.inflation_score,
        "recommendation":  result.recommendation,
        "conviction":      result.conviction,
        "reasoning":       result.reasoning,
        "risks":           result.risks,
        "model":           result.model,
    }
    resp = client.table("thesis_runs").insert(row).execute()
    row_id = resp.data[0]["id"] if resp.data else "unknown"
    logger.info(f"Thesis saved: id={row_id}, conviction={result.conviction}")
    return str(row_id)
