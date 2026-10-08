"""Answer adjudication (task M8.3; docs/04 check 7, docs/12 § Beta and study data loop).

1. `content beta-import` writes the typed answers the app graded `wrong`, grouped by exercise (and conversation turn),
   to `build/reports/beta/rejected.json`.
2. `content review-export --unit uNN` shows the unit's rejected answers that nobody has adjudicated yet as "Answers to
   adjudicate": the teacher decides **accept**, **near-miss** (with a hint; "nearly right" makes it `almost`) or
   **wrong**. The page files each decision as an answer-key comment with `response` (the answer) and `adjudication`.
3. `content review-import` turns every unresolved decision in the ledger, and every "This should be accepted"
   comment from the app (an answer-key change with a `response`), into a **proposal**: the pattern change an agent
   applies (accept: add the answer as an alternative; near: add a `near` entry). Approved files need `content reopen`
   by the owner first; `apply_proposal` refuses them, like the hooks do.

Answers are escaped before they go into a pattern (`{ } [ ] ( ) | \\` become literals), and an accepted answer
never changes the model answer: a top-level `{…|…}` group gets one more alternative at the end, anything else is
wrapped as `{<old>|<answer>}`, whose first expansion is the old one's.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from itcontent import approval, ids, yamlio
from itcontent.beta import norm
from itcontent.course import Course, ExerciseRef
from itcontent.findings import format_path
from itcontent.review import find_exercise
from itcontent.review_elements import Context, Element, Section, _map, _seq, en, esc, it, label, row

# ---------------------------------------------------------------- patterns


SPECIAL = set("{}[]()|\\")


def escape_literal(text: str) -> str:
    """A learner answer as a literal inside an answer pattern."""
    return "".join("\\" + ch if ch in SPECIAL else ch for ch in text)


def _group_end(pattern: str, start: int) -> int | None:
    """Index of the `}` closing the `{` at `start` (escapes respected), or None."""
    depth = 0
    i = start
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def add_alternative(pattern: str, answer: str) -> str:
    """`pattern` accepting `answer` as well, with the same model answer (first expansion)."""
    lit = escape_literal(answer)
    whole_group = pattern.startswith("{") and _group_end(pattern, 0) == len(pattern) - 1
    gendered_or_slot = pattern.startswith(("{m:", "{f:", "{NAME}", "{NUMBER}", "{ME."))
    if whole_group and not gendered_or_slot and "|" in pattern:
        return f"{pattern[:-1]}|{lit}}}"
    return f"{{{pattern}|{lit}}}"


def raw_alternatives(pattern: str) -> set[str]:
    """Normalised literal alternatives of a pattern without expanding it (enough to spot an answer already there)."""
    body = pattern[1:-1] if pattern.startswith("{") and _group_end(pattern, 0) == len(pattern) - 1 else pattern
    out = set()
    depth, cur = 0, ""
    for ch in body:
        if ch in "{(":
            depth += 1
        elif ch in "})":
            depth -= 1
        if ch == "|" and depth == 0:
            out.add(cur)
            cur = ""
        else:
            cur += ch
    out.add(cur)
    return {norm(a.replace("[", "").replace("]", "")) for a in out if not any(c in a for c in "{(")}


# ---------------------------------------------------------------- proposals


@dataclass
class Proposal:
    """One pattern change for an agent to apply (after `content reopen` when the file is approved)."""

    comment: str  # ledger comment id
    target: str
    file: str
    path: list[str | int]  # YAML path of the field to change
    line: int | None
    action: str  # replace | append | add-near | none | manual
    decision: str  # accept | near
    answer: str
    old: Any = None
    new: Any = None
    note: str = ""
    approved: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _decision(entry: dict[str, Any]) -> dict[str, Any] | None:
    """The adjudication of a ledger comment, or an implied accept for "This should be accepted" (the app)."""
    adj = entry.get("adjudication")
    if isinstance(adj, dict) and adj.get("decision") in ("accept", "near", "wrong"):
        return adj
    if entry.get("category") == "answer-key" and entry.get("verdict") == "change" and entry.get("response"):
        return {"decision": "accept"}
    return None


def _status(course: Course, file: str) -> bool:
    review = approval.read_review(course.root / file) if (course.root / file).is_file() else None
    return bool(review and review.get("status") == "approved")


def _line(course: Course, file: str, path: list[str | int]) -> int | None:
    try:
        return yamlio.locate(yamlio.load_roundtrip(course.root / file), path)
    except Exception:
        return None


def propose(course: Course, entry: dict[str, Any]) -> Proposal | None:
    """The pattern change a ledger comment asks for, or None when it asks for none (wrong, or not answer-key)."""
    adj = _decision(entry)
    if adj is None or adj["decision"] == "wrong":
        return None
    answer = " ".join(str(entry.get("response") or "").split())
    target = str(entry.get("target", ""))
    exercise_id, _, node_id = target.partition("/")
    ref = find_exercise(course, exercise_id)
    base = Proposal(
        str(entry.get("id")), target, str(entry.get("file", "")), [], None, "manual", adj["decision"], answer
    )
    if ref is None or not answer:
        base.note = "the exercise no longer exists" if ref is None else "the comment has no answer"
        return base
    base.file = ref.loc.file
    base.approved = _status(course, ref.loc.file)
    near_entry: dict[str, Any] = {"answer": escape_literal(answer), "hint": adj.get("hint") or None}
    if adj.get("outcome") == "almost":
        near_entry["outcome"] = "almost"
    if node_id:
        return _propose_node(course, ref, node_id, adj, base, near_entry)
    data = ref.data
    fmt = ref.format
    if adj["decision"] == "near":
        return _add_near(course, base, [*ref.loc.path], data.get("near"), near_entry)
    if fmt == "recall" and isinstance(data.get("answer"), str):
        old = data["answer"]
        if norm(answer) in raw_alternatives(old):
            return _fill(course, base, [*ref.loc.path, "answer"], "none", old, old, "already an alternative")
        return _fill(course, base, [*ref.loc.path, "answer"], "replace", old, add_alternative(old, answer))
    if fmt == "cloze" and isinstance(data.get("text"), str):
        old = data["text"]
        start, end = old.find("[["), old.find("]]")
        if start < 0 or end < start or old.count("[[") != 1:
            return _fill(course, base, [*ref.loc.path, "text"], "manual", old, None, "the gap can't be found")
        gap = old[start + 2 : end]
        if norm(answer) in raw_alternatives(gap):
            return _fill(course, base, [*ref.loc.path, "text"], "none", old, old, "already an alternative")
        new = old[: start + 2] + add_alternative(gap, answer) + old[end:]
        return _fill(course, base, [*ref.loc.path, "text"], "replace", old, new)
    base.path = [*ref.loc.path]
    base.line = _line(course, base.file, base.path)
    base.note = f"a {fmt} exercise has no answer pattern to extend; decide by hand"
    return base


def _fill(
    course: Course, p: Proposal, path: list[str | int], action: str, old: Any, new: Any, note: str = ""
) -> Proposal:
    p.path, p.action, p.old, p.new, p.note = path, action, old, new, note
    p.line = _line(course, p.file, path)
    return p


def _add_near(course: Course, p: Proposal, owner: list[str | int], near: Any, entry: dict[str, Any]) -> Proposal:
    existing = [x for x in _seq(near) if isinstance(x, dict)]
    if any(norm(p.answer) in raw_alternatives(str(x.get("answer", ""))) for x in existing):
        return _fill(course, p, [*owner, "near"], "none", near, near, "already a near-miss")
    if not entry["hint"]:
        p.note = "the teacher gave no hint: write one that points at the problem without giving the answer away"
    path = [*owner, "near"]
    p.path, p.action, p.old, p.new = path, "add-near", near, [*existing, entry]
    p.line = _line(course, p.file, path if near is not None else owner)
    return p


def _propose_node(
    course: Course, ref: ExerciseRef, node_id: str, adj: dict[str, Any], p: Proposal, near_entry: dict[str, Any]
) -> Proposal:
    node = _map(_map(ref.data.get("nodes")).get(node_id))
    owner = [*ref.loc.path, "nodes", node_id]
    if not node:
        p.note = f"conversation {ref.id} has no node {node_id}"
        return p
    if adj["decision"] == "near":
        return _add_near(course, p, owner, node.get("near"), near_entry)
    intents = [_map(x) for x in _seq(node.get("expect"))]
    names = [str(x.get("intent")) for x in intents]
    chosen = adj.get("intent")
    if chosen not in names:
        if len(intents) != 1:
            p.path, p.line = owner, _line(course, p.file, owner)
            p.note = f"choose the intent it belongs to ({', '.join(names)})"
            return p
        chosen = names[0]
    k = names.index(str(chosen))
    accept = [str(a) for a in _seq(intents[k].get("accept"))]
    path = [*owner, "expect", k, "accept"]
    if any(norm(p.answer) in raw_alternatives(a) for a in accept):
        return _fill(course, p, path, "none", accept, accept, "already accepted")
    return _fill(course, p, path, "append", accept, [*accept, escape_literal(p.answer)], f"intent {chosen}")


def proposals(course: Course, ledger_entries: list[dict[str, Any]]) -> list[Proposal]:
    """Proposals for every unresolved answer-key decision in `ledger_entries`."""
    out = []
    for e in ledger_entries:
        status = _map(e.get("resolution")).get("status", "open")
        if status not in ("open", "owner"):
            continue
        p = propose(course, e)
        if p is not None:
            out.append(p)
    return out


def _yaml_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def proposals_markdown(scope: str, props: list[Proposal]) -> list[str]:
    lines = [
        f"# Answer-key changes for {scope}",
        "",
        'From the teacher\'s adjudications and "This should be accepted" comments (docs/04 check 7, task M8.3).',
        "Apply each one, run `make annotate` and `make check-content`, then resolve the comment in the ledger.",
        "Files marked **approved** need `content reopen` by the owner first.",
        "",
    ]
    if not props:
        return [*lines, "Nothing to apply."]
    for p in props:
        where = f"{p.file}" + (f" line {p.line}" if p.line else "") + f" › {format_path(tuple(p.path))}"
        flag = " **approved: needs content reopen**" if p.approved else ""
        lines.append(f"## `{p.target}`: {p.decision} *{p.answer}*{flag}")
        lines.append("")
        lines.append(f"- comment `{p.comment}`; {where}")
        if p.action in ("replace", "append", "add-near"):
            lines.append(f"- {p.action}: `{_yaml_value(p.old)}`")
            lines.append(f"- with: `{_yaml_value(p.new)}`")
        else:
            lines.append(f"- {p.action}")
        if p.note:
            lines.append(f"- note: {p.note}")
        lines.append("")
    return lines


def write_proposals(out_dir: Path, scope: str, props: list[Proposal]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path, json_path = out_dir / f"{scope}-answers.md", out_dir / f"{scope}-answers.json"
    md_path.write_text("\n".join(proposals_markdown(scope, props)).rstrip() + "\n", encoding="utf-8")
    blob = [p.as_dict() for p in props]
    json_path.write_text(json.dumps(blob, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return [md_path, json_path]


class ApplyError(Exception):
    pass


def apply_proposal(root: Path, p: Proposal) -> None:
    """Apply a `replace` proposal to its file: the old scalar on the field's line becomes the new one (as a
    double-quoted YAML scalar); every other byte stays. Refuses approved files (content reopen first)."""
    if p.action != "replace":
        raise ApplyError(f"only replace proposals apply mechanically; edit {p.file} by hand ({p.action})")
    path = root / p.file
    review = approval.read_review(path)
    if review and review.get("status") == "approved":
        raise ApplyError(f"{p.file} is approved: the owner runs content reopen first (ADR-15)")
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    if not p.line or p.line > len(lines):
        raise ApplyError(f"{p.file}: can't find {format_path(tuple(p.path))}")
    old, new = str(p.old), _yaml_value(p.new)
    current = lines[p.line - 1]
    for rendering in (_yaml_value(old), "'" + old.replace("'", "''") + "'", old):
        key = f"{p.path[-1]}: "
        at = current.find(key + rendering)
        if at >= 0:
            lines[p.line - 1] = current[: at + len(key)] + new + current[at + len(key) + len(rendering) :]
            break
    else:
        raise ApplyError(f"{p.file} line {p.line}: the field doesn't hold {old!r} any more")
    path.write_text("\n".join(lines), encoding="utf-8")
    node: Any = yamlio.load(path)
    for k in p.path:
        node = node[k]
    if node != p.new:
        path.write_text(text, encoding="utf-8")
        raise ApplyError(f"{p.file} line {p.line}: the edit didn't produce the new value; file restored")


# ---------------------------------------------------------------- answers to adjudicate (the page)


@dataclass
class Rejected:
    target: str  # exercise ID or <exerciseId>/<nodeId>
    response: str
    count: int
    notes: list[str] = field(default_factory=list)


def in_scope(target: str, scope: str) -> bool:
    exercise = target.split("/", 1)[0]
    if scope == "assessments":
        return exercise.startswith(("pl.", "fin."))
    return ids.unit_of(exercise) == scope


def rejected_answers(path: Path | None, scope: str, ledger_entries: list[dict[str, Any]]) -> list[Rejected]:
    """The beta's rejected answers for `scope` that no ledger comment has adjudicated yet, most frequent first."""
    if path is None or not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    done = {
        (str(e.get("target")), norm(str(e.get("response") or "")))
        for e in ledger_entries
        if _decision(e) is not None or isinstance(e.get("adjudication"), dict)
    }
    out = []
    for target in sorted(data):
        if not in_scope(target, scope):
            continue
        for a in data[target]:
            resp = str(a.get("response", ""))
            if resp and (target, norm(resp)) not in done:
                out.append(Rejected(target, resp, int(a.get("count", 1))))
    return sorted(out, key=lambda r: (-r.count, r.target, r.response))


def adjudication_section(ctx: Context, rejected: list[Rejected]) -> Section | None:
    """The "Answers to adjudicate" section: each rejected answer with its exercise's key, and accept / near / wrong."""
    entries: list[Element] = []
    for r in rejected:
        exercise_id, _, node_id = r.target.partition("/")
        ref = find_exercise(ctx.course, exercise_id)
        if ref is None:
            continue  # the exercise is gone; nothing to adjudicate against
        data = ref.data
        parts = [f'<p class="rejected">{it(r.response, "it big")} {en(f"rejected {r.count}×")}</p>']
        intents: list[str] = []
        if node_id:
            node = _map(_map(data.get("nodes")).get(node_id))
            parts.append(row(ctx.name(data.get("with", "")), it(node.get("say", ""))))
            for intent in (_map(x) for x in _seq(node.get("expect"))):
                intents.append(str(intent.get("intent", "")))
                parts.append(ctx.answers(_seq(intent.get("accept")), title=f"Accepted for {intent.get('intent', '')}"))
            parts.append(ctx.nears(node.get("near")))
            quote = node.get("say")
        else:
            for key in ("prompt_en", "question_en", "prompt_it", "context_it", "text"):
                if data.get(key):
                    parts.append(row(label(key), esc(data[key])))
            if isinstance(data.get("answer"), str):
                parts.append(ctx.model_line(data["answer"]))
                parts.append(ctx.answers([data["answer"]]))
            gap = re.search(r"\[\[(.+?)\]\]", str(data.get("text", ""))) if ref.format == "cloze" else None
            if gap:
                parts.append(ctx.answers([gap.group(1)], title="Accepted in the gap"))
            parts.append(ctx.nears(data.get("near")))
            quote = data.get("answer") if isinstance(data.get("answer"), str) else data.get("text")
        meta = {"adjudicate": True, "response": r.response, "count": r.count}
        if len(intents) > 1:
            meta["intents"] = intents
        key = f"adj:{r.target}:{r.response}"
        name = f"Answer to adjudicate · {ref.format} {r.target}"
        quote_s = " ".join(str(quote).split()) if quote else None
        entries.append(
            Element(key, r.target, ref.loc.file, "adjudication", name, "".join(parts), quote_s, None, True, 0, meta)
        )
    if not entries:
        return None
    return Section("", "Answers to adjudicate", None, list(entries), "Answers to adjudicate")
