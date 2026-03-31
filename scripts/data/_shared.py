"""Shared utilities for data generation scripts."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

from maestro.language import LANGUAGES
from maestro.llm import compute_cost_usd
from maestro.utils import parse_llm_json

logger = logging.getLogger(__name__)

LANGUAGE_NAMES: dict[str, str] = {code: lc.name for code, lc in LANGUAGES.items()}
CEFR_ORDER = ["A0", "A1", "A2", "B1", "B2"]


# ---------------------------------------------------------------------------
# YAML literal-string helper (preserves multiline block scalars on write)
# ---------------------------------------------------------------------------


class LiteralStr(str):
    pass


def _lit_repr(dumper: yaml.Dumper, data: LiteralStr):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(LiteralStr, _lit_repr)


def _wrap_multiline(items: list[dict]) -> None:
    """Convert multiline strings to LiteralStr for block-scalar YAML output."""
    for item in items:
        for key in ("description",):
            if isinstance(item.get(key), str) and "\n" in item[key]:
                item[key] = LiteralStr(item[key])
        for _lang, expl in item.get("explanations", {}).items():
            for field in ("explanation", "tip", "why_this_matters"):
                if isinstance(expl.get(field), str) and "\n" in expl[field]:
                    expl[field] = LiteralStr(expl[field])


_GP_KEY_ORDER = [
    "code",
    "cefr_level",
    "category",
    "subcategory",
    "unistr_code",
    "unistr_label",
    "label",
    "description",
    "examples",
    "chunk_ref",
    "prerequisites",
    "source_note",
    "language",
    "explanations",
]

_EXPL_KEY_ORDER = ["title", "tip", "explanation", "language", "why_this_matters"]


def _ordered_gp(gp: dict) -> dict:
    """Return GP dict with keys in canonical display order."""
    ordered: dict = {}
    for key in _GP_KEY_ORDER:
        if key in gp:
            if key == "explanations":
                ordered[key] = {
                    lang: {k: expl[k] for k in _EXPL_KEY_ORDER if k in expl}
                    for lang, expl in gp[key].items()
                }
            else:
                ordered[key] = gp[key]
    # Append any unexpected keys at the end
    for key in gp:
        if key not in ordered:
            ordered[key] = gp[key]
    return ordered


def write_gp_yaml(path: Path, items: list[dict]) -> None:
    """Write grammar points to YAML with block scalars for multiline strings."""
    ordered = [_ordered_gp(gp) for gp in items]
    _wrap_multiline(ordered)
    raw = yaml.dump(
        ordered, default_flow_style=False, allow_unicode=True, sort_keys=False
    )
    # Add blank line between top-level list entries for readability
    raw = raw.replace("\n- code:", "\n\n- code:")
    with open(path, "w") as f:
        f.write(raw)


def write_cf_json(path: Path, items: list[dict]) -> None:
    """Write communicative functions to JSON."""
    with open(path, "w") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------------------
# Lock file helpers
# ---------------------------------------------------------------------------


def compute_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_lock(lock_path: Path, lock_data: dict) -> None:
    lock_data["generated_at"] = datetime.now(timezone.utc).isoformat()
    lock_path.write_text(json.dumps(lock_data, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# LLM response helpers
# ---------------------------------------------------------------------------


_EXPLANATION_FIELDS = ("title", "tip", "why_this_matters", "explanation")


def parse_response(raw: str) -> dict | None:
    """Parse JSON response from LLM. Returns the dict or None on failure."""
    data = parse_llm_json(raw)
    if not isinstance(data, dict):
        return None
    return data


def validate_explanation(expl: dict, lang: str) -> dict | None:
    """Validate and normalise an explanation dict."""
    if not expl.get("explanation"):
        return None
    return {
        "title": str(expl.get("title", "")).strip(),
        "tip": str(expl.get("tip", "")).strip(),
        "why_this_matters": str(expl.get("why_this_matters", "")).strip(),
        "explanation": str(expl["explanation"]).strip(),
        "language": lang,
    }


class UsageStats:
    """Accumulates token counts and cost across multiple LLM calls."""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0
        self.calls = 0

    def record(self, response) -> float:
        """Record usage from an LLM response. Returns cost for this call."""
        usage = response.usage
        model = response.model
        cost = compute_cost_usd(model, usage.input_tokens, usage.output_tokens)
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cost_usd += cost
        self.calls += 1
        return cost

    def log_summary(self) -> None:
        logger.info(
            "Token usage: %d calls, %d input + %d output = %d tokens, $%.4f",
            self.calls,
            self.input_tokens,
            self.output_tokens,
            self.input_tokens + self.output_tokens,
            self.cost_usd,
        )
