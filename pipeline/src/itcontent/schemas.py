"""JSON Schemas for content files, review files and ledgers (`schemas/*.schema.json`, draft 2020-12).

`schema_for` maps a repo-relative path to its schema; `validate` returns (YAML path, message) pairs written for
authors ("missing required key 'targets' (format cloze)"), not jsonschema's raw messages. ID formats are the custom
format `id:<kind>[|<kind>…]` (or `id:*` for any ID), checked with `itcontent.ids`, so ID patterns live in one place.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError, best_match
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from itcontent import ids

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas"

# Repo-relative path → schema name (docs/03 § Files, docs/04 § Content review loop). First match wins.
SCHEMA_FOR_PATH: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p), name)
    for p, name in (
        (r"^content/course\.yaml$", "course"),
        (r"^content/checker\.yaml$", "checker"),
        (r"^content/syllabus/[^/]+\.yaml$", "syllabus"),
        (r"^content/grammar/points\.yaml$", "grammar-points"),
        (r"^content/grammar/detection\.yaml$", "detection"),
        (r"^content/items/[^/]+\.yaml$", "items"),
        (r"^content/story-bible\.yaml$", "story-bible"),
        (r"^content/voices\.yaml$", "voices"),
        (r"^content/countries\.yaml$", "countries"),
        (r"^content/allowlist\.yaml$", "allowlist"),
        (r"^content/disambiguation\.yaml$", "disambiguation"),
        (r"^content/pronunciation\.yaml$", "pronunciation"),
        (r"^content/retired\.yaml$", "retired"),
        (r"^content/units/[^/]+/unit\.yaml$", "unit"),
        (r"^content/units/[^/]+/lesson-[^/]+\.yaml$", "lesson"),
        (r"^content/units/[^/]+/task\.yaml$", "task"),
        (r"^content/units/[^/]+/check\.yaml$", "check"),
        (r"^content/assessments/placement\.yaml$", "placement"),
        (r"^content/assessments/final-check\.yaml$", "final-check"),
        (r"^reviews/[^/]+\.yaml$", "review-ledger"),
        (r"^reviews/inbox/[^/]+\.json$", "review-file"),
    )
)

TYPE_NAMES = {
    str: "string",
    bool: "boolean",
    int: "integer",
    float: "number",
    list: "list",
    dict: "mapping",
    type(None): "null",
}


def schema_for(rel: str) -> str | None:
    """The schema name for a repo-relative path, or None if no schema covers it."""
    for pat, name in SCHEMA_FOR_PATH:
        if pat.match(rel):
            return name
    return None


# ---------------------------------------------------------------- loading


def _schema_files() -> list[Path]:
    return sorted(SCHEMA_DIR.rglob("*.schema.json"))


@cache
def _documents() -> dict[str, dict[str, Any]]:
    """Every schema document by name ('lesson', 'exercises/cloze', …)."""
    out = {}
    for p in _schema_files():
        name = p.relative_to(SCHEMA_DIR).as_posix().removesuffix(".schema.json")
        out[name] = json.loads(p.read_text(encoding="utf-8"))
    return out


@cache
def _registry() -> Registry:
    resources = [
        (doc["$id"], Resource.from_contents(doc, default_specification=DRAFT202012)) for doc in _documents().values()
    ]
    return Registry().with_resources(resources)


def _formats_used(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        if isinstance(node.get("format"), str):
            yield node["format"]
        for v in node.values():
            yield from _formats_used(v)
    elif isinstance(node, list):
        for v in node:
            yield from _formats_used(v)


def _id_checker(kinds: str):
    names = kinds.split("|")

    def check(value: object) -> bool:
        if not isinstance(value, str):
            return True  # `type` reports it
        if names == ["*"]:
            return ids.is_global(value)
        return any(ids.is_valid(value, k) for k in names)

    return check


def _check_regex(value: object) -> bool:
    if isinstance(value, str):
        re.compile(value)
    return True


def _check_date(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    dt.date.fromisoformat(value)
    return True


def _check_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if "T" not in value:
        return False
    dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return True


@cache
def format_checker() -> FormatChecker:
    """Our formats only: `id:…`, `regex`, `date`, `date-time`. An unknown format in a schema is a load error."""
    checker = FormatChecker(formats=())
    checker.checks("regex", raises=re.error)(_check_regex)
    checker.checks("date", raises=ValueError)(_check_date)
    checker.checks("date-time", raises=ValueError)(_check_datetime)
    for fmt in sorted({f for doc in _documents().values() for f in _formats_used(doc)}):
        if fmt in ("regex", "date", "date-time"):
            continue
        if not fmt.startswith("id:"):
            raise ValueError(f"schemas use an unknown format '{fmt}'")
        kinds = fmt.removeprefix("id:")
        unknown = [k for k in kinds.split("|") if k != "*" and k not in ids.PATTERNS]
        if unknown:
            raise ValueError(f"schemas use format '{fmt}' with unknown ID kinds {unknown} (itcontent.ids.PATTERNS)")
        checker.checks(fmt)(_id_checker(kinds))
    return checker


@cache
def validator(name: str) -> Draft202012Validator:
    docs = _documents()
    if name not in docs:
        raise KeyError(f"no schema named '{name}' in {SCHEMA_DIR}")
    return Draft202012Validator(docs[name], registry=_registry(), format_checker=format_checker())


def schema_names() -> list[str]:
    return sorted(_documents())


# ---------------------------------------------------------------- validation and messages


def to_jsonable(node: Any) -> Any:
    """YAML → JSON data model: dates become ISO strings, keys become strings."""
    if isinstance(node, dict):
        return {k if isinstance(k, str) else str(k): to_jsonable(v) for k, v in node.items()}
    if isinstance(node, (list, tuple)):
        return [to_jsonable(v) for v in node]
    if isinstance(node, (dt.date, dt.datetime)):
        return node.isoformat()
    return node


def validate(name: str, data: Any) -> list[tuple[tuple[str | int, ...], str]]:
    """Schema problems as (path, message), deduplicated, in document order."""
    out: list[tuple[tuple[str | int, ...], str]] = []
    seen = set()
    for err in validator(name).iter_errors(to_jsonable(data)):
        for path, msg in _messages(err):
            if (path, msg) not in seen:
                seen.add((path, msg))
                out.append((path, msg))
    # An exercise whose format isn't allowed in its container: that is the problem, not the format's own fields.
    wrong = {p[:-1] for p, m in out if p and p[-1] == "format" and NOT_ALLOWED in m}
    return [(p, m) for p, m in out if not any(p[: len(w)] == w and p != (*w, "format") for w in wrong)]


NOT_ALLOWED = "isn't allowed here"


def _short(value: Any, limit: int = 80) -> str:
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _type_name(value: Any) -> str:
    return TYPE_NAMES.get(type(value), type(value).__name__)


def _context(instance: Any) -> str:
    """' (format cloze)' for the object an error is about, so messages say which kind of thing is wrong."""
    if isinstance(instance, dict):
        for key in ("format", "kind", "type"):
            if isinstance(instance.get(key), str):
                return f" ({key} {instance[key]})"
    return ""


def _listing(values: list[Any]) -> str:
    return ", ".join(str(v) for v in values)


def _required_key(err: ValidationError) -> str:
    m = re.match(r"^'(.*)' is a required property$", err.message)
    if m:
        return m.group(1)
    missing = [k for k in err.validator_value if isinstance(err.instance, dict) and k not in err.instance]
    return missing[0] if missing else "?"


def _extra_keys(instance: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    props = schema.get("properties", {})
    patterns = schema.get("patternProperties", {})
    return [k for k in instance if k not in props and not any(re.search(p, k) for p in patterns)]


def _messages(err: ValidationError) -> list[tuple[tuple[str | int, ...], str]]:
    path = tuple(err.absolute_path)
    schema = err.schema if isinstance(err.schema, dict) else {}
    v = err.validator
    inst = err.instance
    if v in ("anyOf", "oneOf") and err.context:
        return _messages(best_match(err.context))
    if "propertyNames" in err.relative_schema_path:
        path = (*path, str(inst))
    if v == "additionalProperties" and isinstance(inst, dict):
        allowed = sorted(k for k in schema.get("properties", {}))
        hint = f"; allowed: {_listing(allowed)}" if allowed and len(allowed) <= 16 else ""
        if isinstance(schema.get("x-keys"), str):
            hint = f"; allowed: {schema['x-keys']}"
        return [((*path, k), f"unknown key '{k}'{_context(inst)}{hint}") for k in _extra_keys(inst, schema)]
    custom = schema.get("x-message")
    if isinstance(custom, str):
        missing = _required_key(err) if v == "required" else ""
        return [(path, custom.replace("{value}", _short(inst)).replace("{missing}", missing))]
    return [(path, _message(err, v, inst, schema, path))]


def _message(err: ValidationError, v: str, inst: Any, schema: dict[str, Any], path: tuple[str | int, ...]) -> str:
    vv = err.validator_value
    key = path[-1] if path else None
    if v == "required":
        return f"missing required key '{_required_key(err)}'{_context(inst)}"
    if v == "enum":
        title = schema.get("title", "")
        allowed = _listing(list(vv))
        if key == "format" and isinstance(inst, str):
            if inst not in ids.FORMATS:
                return f"unknown format '{inst}' (docs/06: {_listing(list(ids.FORMATS))})"
            return f"format '{inst}' {NOT_ALLOWED} (allowed: {allowed})"
        if title == "step kind":
            return f"unknown step kind '{_short(inst)}' (allowed: {allowed})"
        if title:
            return f"'{_short(inst)}' is not a valid {title} (allowed: {allowed})"
        return f"'{_short(inst)}' is not one of: {allowed}"
    if v == "const":
        return f"must be '{_short(vv)}', not '{_short(inst)}'"
    if v == "type":
        want = " or ".join(vv) if isinstance(vv, list) else vv
        got = _type_name(inst)
        shown = "" if isinstance(inst, (dict, list)) or inst is None else f" ({_short(inst)})"
        return f"expected {want}, got {got}{shown}"
    if v == "format":
        if isinstance(vv, str) and vv.startswith("id:"):
            kinds = vv.removeprefix("id:")
            if kinds == "*":
                return f"'{_short(inst)}' is not an ID (docs/03 § IDs)"
            examples = [ids.EXAMPLES[k] for k in kinds.split("|") if k in ids.EXAMPLES]
            like = f" like {' or '.join(examples)}" if examples else ""
            return f"'{_short(inst)}' is not a valid {ids.describe(kinds)} ID{like} (docs/03 § IDs)"
        if vv == "regex":
            cause = f" ({err.cause})" if err.cause else ""
            return f"'{_short(inst)}' is not a valid regular expression{cause}"
        if vv == "date":
            return f"'{_short(inst)}' is not a date like 2026-10-07"
        if vv == "date-time":
            return f"'{_short(inst)}' is not a timestamp like 2026-10-20T09:12:00Z"
        return f"'{_short(inst)}' is not a valid {vv}"
    if v == "pattern":
        title = schema.get("title")
        return f"'{_short(inst)}' is not a valid {title}" if title else f"'{_short(inst)}' doesn't match {vv}"
    if v in ("minItems", "minProperties", "minLength"):
        if vv == 1:
            return "must not be empty"
        unit = {"minItems": "items", "minProperties": "keys", "minLength": "characters"}[v]
        return f"needs at least {vv} {unit}"
    if v in ("maxItems", "maxProperties", "maxLength"):
        unit = {"maxItems": "items", "maxProperties": "keys", "maxLength": "characters"}[v]
        return f"has {len(inst)} {unit}; at most {vv} allowed"
    if v == "minimum":
        return f"must be at least {vv}, not {_short(inst)}"
    if v == "maximum":
        return f"must be at most {vv}, not {_short(inst)}"
    if v == "exclusiveMinimum":
        return f"must be greater than {vv}, not {_short(inst)}"
    if v == "dependentRequired" and isinstance(inst, dict):
        for k, deps in vv.items():
            for d in deps:
                if k in inst and d not in inst:
                    return f"'{k}' needs '{d}' as well"
    if v == "uniqueItems":
        return "has duplicate items"
    if v in ("not", "false"):
        return "is not allowed here"
    return err.message
