import json
import re
from pathlib import Path

CEFR_ORDER = ["A1", "A2", "B1", "B2"]

# Absolute path to src/maestro/data/
DATA_DIR = Path(__file__).parent / "data"


def parse_llm_json(text: str) -> dict | list | None:
    """Strip markdown fences and extract the first JSON object or array from an LLM response."""
    text = re.sub(r"^```(?:json)?\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text)
    match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None
