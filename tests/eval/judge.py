"""Shared LLM-as-judge helper for eval tests."""
import anthropic

from maestro.config import settings
from maestro.utils import parse_llm_json

_SYSTEM = (
    "You are an expert Italian language teacher evaluating AI-generated teaching content. "
    "Be strict but fair. Reply ONLY with valid JSON."
)


def judge(prompt: str) -> tuple[bool, str]:
    """Single synchronous LLM judge call. Returns (acceptable: bool, reason: str)."""
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=settings.EVAL_MODEL,
        max_tokens=256,
        system=_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": prompt + '\n\nReply: {"acceptable": true/false, "reason": "one sentence"}',
            }
        ],
    )
    data = parse_llm_json(response.content[0].text.strip())
    if isinstance(data, dict) and "acceptable" in data:
        return bool(data["acceptable"]), str(data.get("reason", ""))
    return False, "parse error"


def judge_against_reference(
    generated: str,
    reference: str,
    context: str = "",
) -> tuple[bool, str]:
    """Judge whether generated output matches a reference answer.

    Accept paraphrasing — exact wording is not required.
    Returns (acceptable: bool, reason: str).
    """
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    ctx = f"Context: {context}\n\n" if context else ""
    response = client.messages.create(
        model=settings.EVAL_MODEL,
        max_tokens=256,
        system=_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"{ctx}"
                    f"Reference answer:\n{reference}\n\n"
                    f"Generated answer:\n{generated}\n\n"
                    "Does the generated answer convey the same meaning as the reference? "
                    "Accept paraphrasing — exact wording is not required. "
                    'Reply: {"acceptable": true/false, "reason": "one sentence"}'
                ),
            }
        ],
    )
    data = parse_llm_json(response.content[0].text.strip())
    if isinstance(data, dict) and "acceptable" in data:
        return bool(data["acceptable"]), str(data.get("reason", ""))
    return False, "parse error"
