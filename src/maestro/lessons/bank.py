"""Static content bank: pre-authored lesson content loaded from YAML.

Layout (per language, per CEFR level):

  data/<lang>/banks/<level>/drills/<gp_code>.yaml   — drill item pool per GP
  data/<lang>/banks/<level>/texts/<scenario>.yaml   — per-depth texts + prompts

Bank content is the pedagogically load-bearing material (drill items with
answer keys, level-validated reading/listening texts, CF prompts). It is
authored/generated offline (scripts/generate_content_bank.py), reviewable in
git, and optionally pre-annotated with verified vocab mappings.

Loaders cache per (language, level); call invalidate() in tests.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from maestro.models import ExerciseType, VocabAnnotation
from maestro.utils import data_dir

logger = logging.getLogger(__name__)


class BankDrillItem(BaseModel):
    exercise_type: ExerciseType = ExerciseType.FILL_BLANK
    prompt: str
    correct_answer: str
    hint: str | None = None
    vocab_annotations: list[VocabAnnotation] = Field(default_factory=list)


class BankDrillFile(BaseModel):
    grammar_point_code: str
    items: list[BankDrillItem] = Field(default_factory=list)


class BankQuestion(BaseModel):
    text: str
    correct_answer: str = ""
    grammar_point_codes: list[str] = Field(default_factory=list)


class BankText(BaseModel):
    text: str
    questions: list[BankQuestion] = Field(default_factory=list)
    vocab_annotations: list[VocabAnnotation] = Field(default_factory=list)


class BankPrompt(BaseModel):
    prompt: str
    vocab_annotations: list[VocabAnnotation] = Field(default_factory=list)


class BankSpeaking(BankPrompt):
    cf_code: str


class BankDepth(BaseModel):
    listenings: list[BankText] = Field(default_factory=list)
    readings: list[BankText] = Field(default_factory=list)
    writings: list[BankPrompt] = Field(default_factory=list)


class BankScenarioFile(BaseModel):
    scenario: str
    # Speaking prompts are scenario-scoped (CF practised in scenario context);
    # listening/reading/writing material is depth-scoped.
    speakings: list[BankSpeaking] = Field(default_factory=list)
    depths: dict[int, BankDepth] = Field(default_factory=dict)

    @field_validator("depths", mode="before")
    @classmethod
    def _coerce_depth_keys(cls, v):
        if isinstance(v, dict):
            return {int(k): val for k, val in v.items()}
        return v


_drill_cache: dict[tuple[str, str], dict[str, BankDrillFile]] = {}
_text_cache: dict[tuple[str, str], dict[str, BankScenarioFile]] = {}


def bank_dir(language: str, level: str) -> Path:
    return data_dir(language) / "banks" / level.lower()


def _load_yaml_dir(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.is_dir():
        return out
    for f in sorted(path.glob("*.yaml")):
        try:
            with open(f) as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict):
                out[f.stem] = data
        except Exception:
            logger.exception("failed to load bank file %s", f)
    return out


def load_drill_bank(language: str, level: str) -> dict[str, BankDrillFile]:
    """Return {gp_code: BankDrillFile} for the level. Invalid files are skipped."""
    key = (language, level.lower())
    if key not in _drill_cache:
        bank: dict[str, BankDrillFile] = {}
        for stem, data in _load_yaml_dir(bank_dir(language, level) / "drills").items():
            try:
                parsed = BankDrillFile.model_validate(data)
            except Exception:
                logger.exception("invalid drill bank file: %s", stem)
                continue
            bank[parsed.grammar_point_code] = parsed
        _drill_cache[key] = bank
        logger.info(
            "drill bank loaded",
            extra={
                "language": language,
                "level": level,
                "n_gps": len(bank),
                "n_items": sum(len(b.items) for b in bank.values()),
            },
        )
    return _drill_cache[key]


def load_text_bank(language: str, level: str) -> dict[str, BankScenarioFile]:
    """Return {scenario_slug: BankScenarioFile} for the level."""
    key = (language, level.lower())
    if key not in _text_cache:
        bank: dict[str, BankScenarioFile] = {}
        for stem, data in _load_yaml_dir(bank_dir(language, level) / "texts").items():
            try:
                parsed = BankScenarioFile.model_validate(data)
            except Exception:
                logger.exception("invalid text bank file: %s", stem)
                continue
            bank[parsed.scenario or stem] = parsed
        _text_cache[key] = bank
        logger.info(
            "text bank loaded",
            extra={"language": language, "level": level, "n_scenarios": len(bank)},
        )
    return _text_cache[key]


def get_drill_items(language: str, level: str, gp_code: str) -> list[BankDrillItem]:
    entry = load_drill_bank(language, level).get(gp_code)
    return entry.items if entry else []


def get_scenario_texts(
    language: str, level: str, scenario_slug: str
) -> BankScenarioFile | None:
    return load_text_bank(language, level).get(scenario_slug)


def invalidate() -> None:
    """Clear bank caches (tests, after offline regeneration)."""
    _drill_cache.clear()
    _text_cache.clear()
