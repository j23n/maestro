"""Draft a text from its brief with Claude, then check it and send the findings back.

    make draft TEXT=content/texts/inverno/inverno-01.md

The brief is the text file's front matter (curriculum.py). The draft replaces the file's body, keeps
the brief, and sets status: draft. A native speaker reviews every draft before it is marked reviewed.

Credentials: the Anthropic SDK reads ANTHROPIC_API_KEY or an `ant auth login` profile. On a Mac the
key can also live in the Keychain: security add-generic-password -s maestro-anthropic -a "$USER" -w.
Needs the SDK: pip install anthropic.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys

from . import curriculum, packs

MODEL = "claude-opus-5-5"
ROUNDS = 3  # drafts sent back with findings before giving up

FORMAT = (packs.__doc__ or "").split("\n\n", 1)[1]

SYSTEM = """You write graded Italian reading texts for Maestro, an app for adult learners of Italian. \
Learners read the plain text and tap words for help, so the Italian must be natural, correct and \
pitched exactly at the level: a native speaker would say it, and a learner at that level can read it \
with only the new words unknown.

Write in our own words. Don't reproduce or paraphrase published texts. Facts about holidays, places \
and customs must be well established; if a fact is uncertain, leave it out. No party politics, no \
crime or disaster stories about real victims, and no real private individuals by name.

Return the whole source file in one ```markdown block and nothing else."""


def _keychain_key() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(["security", "find-generic-password", "-s", "maestro-anthropic", "-w"],
                             capture_output=True, text=True, check=False)
    except OSError:
        return None
    return out.stdout.strip() or None


def client():
    try:
        import anthropic
    except ImportError:
        raise SystemExit("make draft needs the Anthropic SDK: pip install anthropic") from None
    key = os.environ.get("ANTHROPIC_API_KEY") or _keychain_key()
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


def front_matter(source: str) -> tuple[str, list[tuple[str, str]], str]:
    """(title, ordered key-value pairs, body) of a text source."""
    lines = source.splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError("a text starts with '# Title'")
    meta: list[tuple[str, str]] = []
    i = 1
    while i < len(lines) and lines[i].strip():
        key, _, value = lines[i].partition(":")
        meta.append((key.strip(), value.strip()))
        i += 1
    return lines[0][2:].strip(), meta, "\n".join(lines[i:]).strip("\n")


def merge(brief_source: str, drafted: str) -> str:
    """The draft's title and body under the brief's front matter, with status: draft."""
    _, brief, _ = front_matter(brief_source)
    title, theirs, body = front_matter(drafted)
    meta = dict(brief)
    keep = {k: v for k, v in theirs}
    for key in ("topics", "type"):
        if keep.get(key) and not meta.get(key):
            meta[key] = keep[key]
    meta["status"] = "draft"
    keys = [k for k, _ in brief] + [k for k in ("status", "topics", "type") if k in meta and k not in dict(brief)]
    lines = [f"# {title}"] + [f"{k}: {meta[k]}" for k in keys] + ["", body]
    return "\n".join(lines).rstrip() + "\n"


def markdown_block(text: str) -> str:
    m = re.search(r"```(?:markdown|md)?\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip() + "\n"


def describe_brief(lib: curriculum.Library, path: str) -> str:
    _, meta_pairs, _ = front_matter(open(path, encoding="utf-8").read())
    meta = dict(meta_pairs)
    level = meta["level"]
    plan = lib.plans[level]
    allowed = [t for t in sorted(lib.topics.values(), key=lambda t: t.order)
               if curriculum.level_index(t.level) <= curriculum.level_index(level)]
    lo, hi = curriculum.word_range(meta.get("words", "")) or plan.words
    parts = [
        f"Level {level}. Length {lo} to {hi} words, at most {plan.sentence_words:g} words per sentence on average.",
        "Use only very common words: at most the new words below plus two more that a learner at this level "
        "won't know. Use each new word at least twice.",
        "Grammar you may use: " + ", ".join(f"{t.id} ({t.title})" for t in allowed) + ". Nothing from a later "
        "level, unless an @unit note explains it.",
    ]
    if meta.get("introduces"):
        topic = lib.topics.get(meta["introduces"])
        parts.append(f"The text teaches {meta['introduces']}"
                     + (f" ({topic.title}: {topic.summary})" if topic else "")
                     + ". Use it at least three times and explain one use with an @unit note.")
    if meta.get("recycle"):
        parts.append(f"Also use: {meta['recycle']}.")
    if meta.get("avoid"):
        parts.append(f"Don't use: {meta['avoid']}.")
    if meta.get("newWords"):
        parts.append(f"New words (headword:part of speech): {meta['newWords']}.")
    if meta.get("reuse"):
        parts.append(f"Words from earlier texts to use again: {meta['reuse']}.")
    if meta.get("register"):
        parts.append(f"Register: {meta['register']}.")
    if meta.get("blocks"):
        parts.append(f"Mostly {meta['blocks']} (dialogue lines start with '> Name:').")
    if meta.get("persons"):
        parts.append(f"Include verbs in these persons: {meta['persons']}.")
    if meta.get("window"):
        parts.append(f"The library features the text in the window {meta['window']} (month-day, or days "
                     "from Easter); write about that time of year, in a way that stays true every year.")
    if meta.get("notes"):
        parts.append(meta["notes"])
    parts.append("Add 3 or 4 comprehension questions: multiple choice or yes/no/not stated, each pointing "
                 "at the sentence that answers it.")
    return "\n".join(f"- {p}" for p in parts)


def examples(lib: curriculum.Library, level: str, exclude: str) -> list[str]:
    same = [t for t in lib.texts if t.level == level and t.status == "reviewed" and t.path != exclude]
    other = [t for t in lib.texts if t.status == "reviewed" and t.path != exclude and t not in same]
    return [open(t.path, encoding="utf-8").read() for t in (same + other)[:2]]


def findings_for(conn: sqlite3.Connection, args, path: str) -> list[str]:
    try:
        lib = curriculum.load_library(conn, args.texts, args.curriculum, args.grammar, args.frequency, extra=[path])
        src = packs.parse_source(path)
    except (packs.PackError, ValueError, KeyError) as exc:
        return [f"The file doesn't parse: {exc}"]
    text, _ = packs.build_text(packs.Lexicon(conn), src)
    out = [f"Build: {e}" for e in packs.validate_text(text, packs.Lexicon(conn))]
    facts = next(t for t in lib.texts if os.path.abspath(t.path) == os.path.abspath(path))
    out += [f"{f.check}: {f.message}" for f in curriculum.check_text(lib, facts) if f.error]
    return out


def check_questions(api, source: str) -> list[str]:
    """A second, independent pass answers each question from the text alone."""
    src_path = None
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(source)
        src_path = fh.name
    try:
        src = packs.parse_source(src_path)
    finally:
        os.unlink(src_path)
    sentences = [s.text for b in src.blocks for s in b.sentences]
    numbered = "\n".join(f"s{i}: {s}" for i, s in enumerate(sentences, start=1))
    asked = []
    for q in src.questions:
        if q["type"] == "choice":
            opts = "; ".join(f"{i}: {o}" for i, o in enumerate(q["options"]))
            asked.append(f"{q['id']}: {q['prompt']} Options: {opts}. Answer with the option number.")
        else:
            asked.append(f"{q['id']}: {q['prompt']} Answer yes, no or notStated.")
    schema = {"type": "object", "additionalProperties": False, "required": ["answers"],
              "properties": {"answers": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False, "required": ["id", "answer"],
                  "properties": {"id": {"type": "string"}, "answer": {"type": "string"}}}}}}
    message = api.messages.create(
        model=MODEL, max_tokens=4000, output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": f"Text:\n{numbered}\n\nAnswer from the text alone:\n" + "\n".join(asked)}])
    if message.stop_reason == "refusal":
        return ["The question check was declined; check the questions by hand."]
    data = json.loads(next(b.text for b in message.content if b.type == "text"))
    got = {a["id"]: a["answer"].strip() for a in data["answers"]}
    out = []
    for q in src.questions:
        expected = str(q["answer"])
        if got.get(q["id"]) != expected:
            out.append(f"Question {q['id']} ({q['prompt']}): the marked answer is {expected}, but a reader "
                       f"answering from the text alone chose {got.get(q['id'])!r}. Make the text or the question "
                       "unambiguous.")
    return out


def run(args) -> int:
    path = os.path.abspath(args.text)
    brief_source = open(path, encoding="utf-8").read()
    _, meta, _ = front_matter(brief_source)
    if dict(meta).get("status", "reviewed") == "reviewed":  # the default, as in curriculum.TextFacts
        print(f"{path} is reviewed; drafting would overwrite it", file=sys.stderr)
        return 1
    conn = sqlite3.connect(args.db)
    lib = curriculum.load_library(conn, args.texts, args.curriculum, args.grammar, args.frequency)
    level = dict(meta)["level"]
    prompt = ["Write the text for this brief.", "", "Brief:", describe_brief(lib, path), "",
              "The file as it stands (keep its front matter):", "```markdown", brief_source.strip(), "```", "",
              "The source format:", FORMAT.strip()]
    for n, ex in enumerate(examples(lib, level, path), start=1):
        prompt += ["", f"Example {n} of a finished text:", "```markdown", ex.strip(), "```"]
    messages = [{"role": "user", "content": "\n".join(prompt)}]

    api = client()  # first, so a missing SDK gets its message rather than a traceback
    import anthropic

    try:
        return _rounds(api, args, conn, path, brief_source, messages)
    except TypeError as exc:  # the SDK found no credentials at all
        if "authentication" not in str(exc):
            raise
        print("No Anthropic credentials: set ANTHROPIC_API_KEY, run ant auth login, or add the key to "
              "the Keychain as maestro-anthropic", file=sys.stderr)
    except anthropic.AuthenticationError:
        print("No working Anthropic credentials: set ANTHROPIC_API_KEY, run ant auth login, or add the key to "
              "the Keychain as maestro-anthropic", file=sys.stderr)
    except anthropic.RateLimitError:
        print("Rate limited by the Anthropic API; try again in a minute", file=sys.stderr)
    except anthropic.APIStatusError as exc:
        print(f"Anthropic API error {exc.status_code}: {exc.message}", file=sys.stderr)
    except anthropic.APIConnectionError:
        print("Can't reach the Anthropic API; check the network", file=sys.stderr)
    return 1


def _rounds(api, args, conn: sqlite3.Connection, path: str, brief_source: str, messages: list) -> int:
    for round_ in range(1, ROUNDS + 2):
        with api.beta.messages.stream(
                model=MODEL, max_tokens=64000, system=SYSTEM, messages=messages,
                output_config={"effort": "high"}, betas=["server-side-fallback-2026-07-01"],
                fallbacks="default") as stream:
            message = stream.get_final_message()
        if message.stop_reason == "refusal":
            print("The draft was declined; write this brief by hand.", file=sys.stderr)
            return 1
        text = "".join(b.text for b in message.content if b.type == "text")
        source = merge(brief_source, markdown_block(text))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(source)
        problems = findings_for(conn, args, path)
        if not problems:
            problems = check_questions(api, source)
        print(f"round {round_}: {len(problems)} problems")
        for p in problems:
            print(f"  {p}")
        if not problems:
            print(f"wrote {path}; it needs a native speaker's review before status: reviewed")
            return 0
        if round_ > ROUNDS:
            break
        messages.append({"role": "assistant", "content": message.content})
        messages.append({"role": "user", "content": "The checker found these problems. Fix them and return the "
                                                    "whole file again:\n" + "\n".join(f"- {p}" for p in problems)})
    aside = set_aside(path, brief_source, source, problems)
    if aside:
        print(f"the draft doesn't build, so {path} is the brief again and the draft is in {aside}; fix it "
              "there and copy it back, or run make draft again", file=sys.stderr)
    else:
        print(f"wrote {path} with problems left; fix them by hand or run make draft again", file=sys.stderr)
    return 1


def set_aside(path: str, brief_source: str, source: str, problems: list[str]) -> str | None:
    """A draft that doesn't build would stop make content, and so the next make draft. Puts the brief
    back and the draft next to it, outside the pack build, and returns that path. None if it builds."""
    if not any(p.startswith(("Build:", "The file doesn't parse")) for p in problems):
        return None
    aside = path + ".failed"
    with open(aside, "w", encoding="utf-8") as fh:
        fh.write(source)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(brief_source)
    return aside
