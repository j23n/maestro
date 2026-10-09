"""ID formats (docs/03 § IDs). IDs are permanent, lowercase ASCII and unique across the course.

`PATTERNS` is the single source of truth for ID formats: the JSON Schemas refer to these kinds through the custom
format `id:<kind>` (or `id:<kind>|<kind>` for a choice), which `itcontent.schemas` checks with `is_valid`.
"""

from __future__ import annotations

import re
import unicodedata

SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
SENSE = rf"(?:~{SLUG})?"
STEP_KINDS = "preview|story|listening|reading|note|practice|sounds|use"
UNIT_STEP = r"opener|conversation-\d+|talk|writing|relay|check|fluency"
SKILLS = "read|listen|recall|speak"

LESSON_STEP_KINDS: tuple[str, ...] = tuple(STEP_KINDS.split("|"))
UNIT_STEP_KINDS: tuple[str, ...] = ("opener", "conversation", "talk", "writing", "relay", "check", "fluency")
SKILL_LIST: tuple[str, ...] = tuple(SKILLS.split("|"))
FORMATS: tuple[str, ...] = (
    "cloze",
    "recall",
    "sentence-building",
    "dictation",
    "sound-pair",
    "repeat",
    "choice",
    "true-false",
    "match",
    "conversation",
    "talk",
    "writing",
    "relay",
)
SECTIONS: tuple[str, ...] = ("listening", "reading", "structures", "writing", "speaking")
SYLLABUS_AREAS: tuple[str, ...] = ("gr", "fn", "tp", "ss", "cefr", "ex")

_UNIT = r"u\d{2}"
_LESSON = rf"{_UNIT}\.l\d+"
_EXERCISE = (
    rf"(?:{_LESSON}\.ex\d{{2}}|{_LESSON}\.q\d+|{_UNIT}\.task\.{SLUG}|{_UNIT}\.check\.\d{{2}}"
    rf"|pl\.\d{{2}}|fin\.{SLUG}\.\d{{2}})"
)
# A check text's name: a slug starting with a letter (never a check exercise's NN) and other than `items` (the review
# target `uNN.check.items` is the unit spec's check plan).
CHECK_TEXT_NAME = r"(?!items(?![a-z0-9-]))[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
_TEXT = rf"(?:{_LESSON}\.{SLUG}|{_UNIT}\.task\.{SLUG}|{_UNIT}\.check\.{CHECK_TEXT_NAME}|{_EXERCISE}\.audio)"
_NODE = r"[a-z][a-z0-9-]*"
_ALL_KINDS = "|".join((*LESSON_STEP_KINDS, *UNIT_STEP_KINDS))

PATTERNS: dict[str, re.Pattern[str]] = {
    "unit": re.compile(rf"^{_UNIT}$"),
    "lesson": re.compile(rf"^{_LESSON}$"),
    "lesson_step": re.compile(rf"^{_LESSON}\.step-(?:{STEP_KINDS})(?:-\d+)?$"),
    "unit_step": re.compile(rf"^{_UNIT}\.step-(?:{UNIT_STEP})$"),
    "text": re.compile(rf"^{_TEXT}$"),
    "text_line": re.compile(rf"^{_TEXT}#[1-9]\d*$"),
    "exercise": re.compile(rf"^{_EXERCISE}$"),
    "generated_exercise": re.compile(
        rf"^(?:{_LESSON}\.step-preview(?:-\d+)?\.b\d+\.(?:match|[wcgs]-{SLUG}{SENSE})|gen:(?:{SKILLS}):[wcgs]:{SLUG}{SENSE})$"
    ),
    "task_file": re.compile(rf"^{_UNIT}\.task$"),
    "check_file": re.compile(rf"^(?:{_UNIT}\.check|final|placement)$"),
    "note": re.compile(rf"^{_LESSON}\.note(?:-\d+)?$"),
    "item": re.compile(rf"^[wcgs]:{SLUG}{SENSE}$"),
    "word": re.compile(rf"^w:{SLUG}{SENSE}$"),
    "chunk": re.compile(rf"^c:{SLUG}{SENSE}$"),
    "grammar": re.compile(rf"^g:{SLUG}$"),
    "sound": re.compile(rf"^s:{SLUG}$"),
    "can_do": re.compile(rf"^cd:{SLUG}$"),
    "syllabus": re.compile(rf"^sy:(?:{'|'.join(SYLLABUS_AREAS)})\.{SLUG}$"),
    "character": re.compile(rf"^ch:{SLUG}$"),
    "topic": re.compile(rf"^topic:{SLUG}$"),
    "country": re.compile(r"^(?:[a-z]{2}|gb-(?:eng|sct|wls|nir))$"),
    "audio": re.compile(r"^a:[0-9a-f]{12}$"),
    "conversation_node": re.compile(rf"^{_NODE}$"),
    # Added in M1.2. Kinds above keep their order, so `kind_of` answers as before.
    "lexical_item": re.compile(rf"^[wcs]:{SLUG}{SENSE}$"),  # what an items/uNN.yaml file may define
    "step": re.compile(rf"^(?:{_LESSON}\.step-(?:{STEP_KINDS})(?:-\d+)?|{_UNIT}\.step-(?:{UNIT_STEP}))$"),
    "speaker": re.compile(rf"^(?:narrator|announcer|ch:{SLUG})$"),
    "conversation_node_ref": re.compile(rf"^{_EXERCISE}/{_NODE}$"),  # review targets: <exerciseId>/<nodeId>
    "coverage_ref": re.compile(
        rf"^(?:g:{SLUG}|s:{SLUG}|cd:{SLUG}|topic:{SLUG}|kind:(?:{_ALL_KINDS})"
        rf"|format:(?:{'|'.join(FORMATS)})|section:(?:{'|'.join(SECTIONS)}))$"
    ),
    "spec_path": re.compile(r"^u\d{2}(?:\.[a-z_]+(?:\[\d+\])*)+$"),  # review targets into a unit spec: u02.can_do[1]
}

RESERVED_SPEAKERS = {"narrator": "ch:narrator", "announcer": "ch:announcer"}

KIND_NAMES: dict[str, str] = {
    "unit": "unit",
    "lesson": "lesson",
    "lesson_step": "lesson step",
    "unit_step": "unit-level step",
    "step": "step",
    "text": "text",
    "text_line": "text line",
    "exercise": "exercise",
    "generated_exercise": "generated exercise",
    "task_file": "task file",
    "check_file": "check",
    "note": "note",
    "item": "item",
    "lexical_item": "word, chunk or sound",
    "word": "word",
    "chunk": "chunk",
    "grammar": "grammar point",
    "sound": "sound",
    "can_do": "can-do",
    "syllabus": "syllabus entry",
    "character": "character",
    "speaker": "speaker",
    "topic": "topic",
    "country": "country",
    "audio": "audio",
    "conversation_node": "conversation node",
    "conversation_node_ref": "conversation node",
    "coverage_ref": "coverage reference",
    "spec_path": "spec path",
}


EXAMPLES: dict[str, str] = {
    "unit": "u02",
    "lesson": "u02.l1",
    "lesson_step": "u02.l1.step-story",
    "unit_step": "u02.step-conversation-1",
    "step": "u02.l1.step-story",
    "text": "u02.l1.story",
    "text_line": "u02.l1.story#3",
    "exercise": "u02.l1.ex07",
    "task_file": "u02.task",
    "check_file": "u02.check",
    "note": "u02.l1.note",
    "item": "w:cornetto",
    "lexical_item": "w:cornetto",
    "word": "w:cornetto",
    "chunk": "c:quant-e",
    "grammar": "g:indefinite-article",
    "sound": "s:double-consonants",
    "can_do": "cd:order-food-drink",
    "syllabus": "sy:gr.articles",
    "character": "ch:giulia",
    "speaker": "ch:giulia",
    "topic": "topic:food-drink",
    "country": "gb-wls",
    "conversation_node": "n1",
    "coverage_ref": "g:noun-gender",
}


def kind_of(identifier: str) -> str | None:
    """The first ID kind whose pattern matches, or None."""
    for kind, pat in PATTERNS.items():
        if pat.match(identifier):
            return kind
    return None


def is_valid(identifier: str, kind: str) -> bool:
    return bool(PATTERNS[kind].match(identifier))


LOCAL_KINDS = ("conversation_node", "coverage_ref", "spec_path")  # names inside a file or reference syntax, not IDs


def is_global(identifier: str) -> bool:
    """A course-wide ID of any kind (what ids.lock and retired.yaml hold); `n1` or `drink` are local names."""
    return any(p.match(identifier) for k, p in PATTERNS.items() if k not in LOCAL_KINDS)


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


# ---------------------------------------------------------------- structure of IDs (M1.2)


def describe(kinds: str | tuple[str, ...]) -> str:
    """Human name for one kind or a choice of kinds: ('can_do', 'syllabus') → 'can-do or syllabus entry'."""
    if isinstance(kinds, str):
        kinds = tuple(kinds.split("|"))
    names = [KIND_NAMES.get(k, k) for k in kinds]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


def unit_of(identifier: str) -> str | None:
    """`u02.l1.ex07` → `u02`; None for IDs outside a unit."""
    m = re.match(r"^(u\d{2})(?:\.|$)", identifier)
    return m.group(1) if m else None


def lesson_of(identifier: str) -> str | None:
    """`u02.l1.step-story` → `u02.l1`."""
    m = re.match(r"^(u\d{2}\.l\d+)(?:\.|$)", identifier)
    return m.group(1) if m else None


def split_line_ref(ref: str) -> tuple[str, int] | None:
    """`u02.l1.story#3` → ('u02.l1.story', 3); None if `ref` is not a text line reference."""
    if not PATTERNS["text_line"].match(ref):
        return None
    text, n = ref.rsplit("#", 1)
    return text, int(n)


def base_of(item_id: str) -> str:
    """`w:pesca~fruit` → `w:pesca`."""
    return item_id.split("~", 1)[0]


def unit_from_folder(slug: str) -> str:
    """`02-al-bar` → `u02`."""
    return "u" + slug.split("-", 1)[0]


def step_kind_of(step_id: str) -> str | None:
    """`u02.l1.step-story-2` → 'story'; `u02.step-conversation-1` → 'conversation'."""
    m = re.match(rf"^(?:{_LESSON}|{_UNIT})\.step-([a-z]+)(?:-\d+)?$", step_id)
    return m.group(1) if m else None
