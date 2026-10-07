"""ID formats (docs/03 § IDs). IDs are permanent, lowercase ASCII and unique across the course."""

from __future__ import annotations

import re
import unicodedata

SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
SENSE = rf"(?:~{SLUG})?"
STEP_KINDS = "preview|story|listening|reading|note|practice|sounds|use"
UNIT_STEP = r"opener|conversation-\d+|talk|writing|relay|check|fluency"
SKILLS = "read|listen|recall|speak"

PATTERNS: dict[str, re.Pattern[str]] = {
    "unit": re.compile(r"^u\d{2}$"),
    "lesson": re.compile(r"^u\d{2}\.l\d+$"),
    "lesson_step": re.compile(rf"^u\d{{2}}\.l\d+\.step-(?:{STEP_KINDS})(?:-\d+)?$"),
    "unit_step": re.compile(rf"^u\d{{2}}\.step-(?:{UNIT_STEP})$"),
    "text": re.compile(
        rf"^(?:u\d{{2}}\.l\d+\.{SLUG}|u\d{{2}}\.task\.{SLUG}|u\d{{2}}\.(?:check\.\d{{2}}|l\d+\.ex\d{{2}})\.audio)$"
    ),
    "text_line": re.compile(rf"^(?:u\d{{2}}\.(?:l\d+|task)\.{SLUG})#[1-9]\d*$"),
    "exercise": re.compile(
        rf"^(?:u\d{{2}}\.l\d+\.ex\d{{2}}|u\d{{2}}\.l\d+\.q\d+|u\d{{2}}\.task\.{SLUG}|u\d{{2}}\.check\.\d{{2}}"
        rf"|pl\.\d{{2}}|fin\.{SLUG}\.\d{{2}})$"
    ),
    "generated_exercise": re.compile(
        rf"^(?:u\d{{2}}\.l\d+\.step-preview(?:-\d+)?\.b\d+\.(?:match|[wcgs]-{SLUG}{SENSE})|gen:(?:{SKILLS}):[wcgs]:{SLUG}{SENSE})$"
    ),
    "task_file": re.compile(r"^u\d{2}\.task$"),
    "check_file": re.compile(r"^(?:u\d{2}\.check|final|placement)$"),
    "note": re.compile(r"^u\d{2}\.l\d+\.note(?:-\d+)?$"),
    "item": re.compile(rf"^[wcgs]:{SLUG}{SENSE}$"),
    "word": re.compile(rf"^w:{SLUG}{SENSE}$"),
    "chunk": re.compile(rf"^c:{SLUG}{SENSE}$"),
    "grammar": re.compile(rf"^g:{SLUG}$"),
    "sound": re.compile(rf"^s:{SLUG}$"),
    "can_do": re.compile(rf"^cd:{SLUG}$"),
    "syllabus": re.compile(rf"^sy:(?:gr|fn|tp|ss|cefr|ex)\.{SLUG}$"),
    "character": re.compile(rf"^ch:{SLUG}$"),
    "topic": re.compile(rf"^topic:{SLUG}$"),
    "country": re.compile(r"^(?:[a-z]{2}|gb-(?:eng|sct|wls|nir))$"),
    "audio": re.compile(r"^a:[0-9a-f]{12}$"),
    "conversation_node": re.compile(r"^[a-z][a-z0-9-]*$"),
}

RESERVED_SPEAKERS = {"narrator": "ch:narrator", "announcer": "ch:announcer"}


def kind_of(identifier: str) -> str | None:
    """The first ID kind whose pattern matches, or None."""
    for kind, pat in PATTERNS.items():
        if pat.match(identifier):
            return kind
    return None


def is_valid(identifier: str, kind: str) -> bool:
    return bool(PATTERNS[kind].match(identifier))


def slugify(text: str) -> str:
    """Slug rule (docs/03): strip accents, apostrophe → '-', spaces → '-', lowercase ASCII."""
    nfd = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")
    s = stripped.lower().replace("’", "'").replace("'", "-")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def generated_item_suffix(item_id: str) -> str:
    """`w:cornetto` → `w-cornetto` for generated preview exercise IDs (docs/03)."""
    return item_id.replace(":", "-")
