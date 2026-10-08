"""Payload JSON for exercises, notes and real-world layouts (docs/06 § Payloads; the contract is
`schemas/pack-payloads.schema.json`, validated by the build).

Keys are camelCase and every optional key is present (null when absent). Italian strings travel as `TokenizedText`
built from the lock files; answer patterns as `{source, expansions}`, where `expansions` are the learner-independent
normalised expansions (slots stay placeholders) for the review mode's answer key. Audio IDs are null until TTS (M5.1).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from itcontent.annotate import italian_options
from itcontent.normalize import normalize
from itcontent.pack.common import BuildError, mapping, opt_str, seq
from itcontent.pack.locks import LockFile, LockString, has_words, tokenized
from itcontent.patterns import PatternError, expand

PathT = tuple[str | int, ...]
GAP = re.compile(r"\[\[(.*?)\]\]")
LAYOUT_NON_TEXT = frozenset({"type", "style", "ignore"})
# Optional layout keys, present as null when not authored (docs/06 § 4).
LAYOUT_OPTIONAL: dict[str, tuple[str, ...]] = {
    "receipt": ("footer",),
    "sign": ("style",),
    "hours": ("note",),
    "ad": ("contact",),
    "message": ("time",),
    "postcard": ("address",),
    "list": ("title",),
}
LAYOUT_ROW_OPTIONAL: dict[str, tuple[str, ...]] = {"menu": ("note",), "receipt": ("qty",)}


def pattern(source: str, where: str) -> dict[str, Any]:
    """`{source, expansions}` for an answer pattern; empty expansions (an all-optional pattern's) are left out."""
    try:
        exps = [e.text for e in expand(source)]
    except PatternError as exc:
        raise BuildError(f"{where}: pattern {source!r}: {exc}") from exc
    shown = [e for e in exps if e]
    if not shown:
        raise BuildError(f"{where}: pattern {source!r} has no non-empty expansion")
    return {"source": source, "expansions": shown}


def near_list(raw: Any, where: str) -> list[dict[str, Any]]:
    out = []
    for j, n in enumerate(seq(raw)):
        n = mapping(n)
        if not isinstance(n.get("answer"), str):
            raise BuildError(f"{where}.near[{j}]: a near-miss needs an answer pattern")
        out.append(
            {
                "answer": pattern(n["answer"], f"{where}.near[{j}]"),
                "outcome": str(n.get("outcome") or "wrong"),
                "hint": opt_str(n.get("hint")),
            }
        )
    return out


def int_or(value: Any, default: int | None) -> int | None:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise BuildError(f"expected a whole number, got {value!r}")


@dataclass
class ExerciseInput:
    """An authored exercise and everything its payload needs from the compiler."""

    data: Mapping[str, Any]
    path: PathT  # YAML path of the exercise in its file
    lock: LockFile
    unit_id: str
    step_id: str | None
    step_kind: str | None
    role: str
    targets: frozenset[str]  # the lesson's target grammar points (token flag 4)
    source: dict[str, Any] | None  # {textId, line} or None
    audio_text_id: str | None
    item_gloss: Callable[[str], str | None]

    @property
    def id(self) -> str:
        return str(self.data.get("id", ""))

    @property
    def format(self) -> str:
        return str(self.data.get("format", ""))

    def where(self, *keys: str | int) -> str:
        out = f"{self.lock.file} › {self.id}"
        for k in keys:
            out += f"[{k}]" if isinstance(k, int) else f".{k}"
        return out

    def text(self, *keys: str | int) -> dict[str, Any]:
        """The TokenizedText of an Italian string at a path below the exercise."""
        node: Any = self.data
        for k in keys:
            node = node[k]
        value = str(node) if isinstance(node, int | float) and not isinstance(node, bool) else node
        if not isinstance(value, str):
            raise BuildError(f"{self.where(*keys)}: expected an Italian string")
        return tokenized(self.lock.plain((*self.path, *keys), value), self.targets)

    def opt_text(self, key: str) -> dict[str, Any] | None:
        value = self.data.get(key)
        return self.text(key) if isinstance(value, str) and value.strip() else None


def exercise_payload(x: ExerciseInput) -> dict[str, Any]:
    ex = x.data
    score = int_or(ex.get("score"), 1)
    common: dict[str, Any] = {
        "id": x.id,
        "format": x.format,
        "role": x.role,
        "unitId": x.unit_id,
        "stepId": x.step_id,
        "score": score,
        "targets": [
            {"itemId": str(t["item"]), "skill": str(t["skill"])} for t in seq(ex.get("targets")) if isinstance(t, dict)
        ],
        "tags": [str(t) for t in seq(ex.get("tags"))],
        "source": None if x.format == "relay" else x.source,
        "hint": opt_str(ex.get("hint")),
        "rule": opt_str(ex.get("rule")),
        "near": near_list(ex.get("near"), x.where()),
        "audioAfter": bool(ex.get("audio_after", False)),
    }
    body = BODIES.get(x.format)
    if body is None:
        raise BuildError(f"{x.where()}: unknown format {x.format!r}")
    return {**common, **body(x)}


# ---------------------------------------------------------------- per format


def cloze(x: ExerciseInput) -> dict[str, Any]:
    text = str(x.data.get("text", ""))
    gaps = GAP.findall(text)
    if len(gaps) != 1:
        raise BuildError(f"{x.where('text')}: a cloze has exactly one [[gap]] (found {len(gaps)})")
    s = x.lock.model((*x.path, "text"), gaps[0])
    if s.gap is None or s.gap[0] > s.gap[1]:
        raise BuildError(f"{s.where()}: the annotation has no gap tokens; run `make annotate`")
    first, last = s.gap
    before = tokenized(s, x.targets, start=0, end=first)
    after = tokenized(s, x.targets, start=last + 1, lead=str(s.tokens[last].get("trailing", "")))
    return {
        "before": before,
        "gap": pattern(gaps[0], x.where("text")),
        "after": after,
        "promptEn": opt_str(x.data.get("prompt_en")),
        "bank": [str(b) for b in x.data["bank"]] if isinstance(x.data.get("bank"), list) else None,
        "audioId": None,
    }


def recall(x: ExerciseInput) -> dict[str, Any]:
    answer = x.data.get("answer")
    if not isinstance(answer, str):
        raise BuildError(f"{x.where('answer')}: a recall needs an answer pattern")
    return {
        "promptEn": str(x.data.get("prompt_en", "")),
        "contextIt": x.opt_text("context_it"),
        "answer": pattern(answer, x.where("answer")),
        "answerAudioId": None,
    }


def sentence_building(x: ExerciseInput) -> dict[str, Any]:
    return {
        "promptEn": str(x.data.get("prompt_en", "")),
        "tiles": [str(t) for t in seq(x.data.get("tiles"))],
        "distractors": [str(t) for t in seq(x.data.get("distractors"))],
        "answers": [normalize(str(a)) for a in seq(x.data.get("answer"))],
        "answerAudioId": None,
    }


def dictation(x: ExerciseInput) -> dict[str, Any]:
    return {
        "say": x.text("say"),
        "audioId": None,
        "slow": bool(x.data.get("slow", False)),
        "plays": int_or(x.data.get("plays"), None),
    }


def repeat(x: ExerciseInput) -> dict[str, Any]:
    say = x.text("say")
    norm = normalize(say["text"])
    return {"say": say, "audioId": None, "accept": {"source": escape_literal(norm), "expansions": [norm]}}


def escape_literal(text: str) -> str:
    return "".join("\\" + ch if ch in "\\{}[]()|" else ch for ch in text)


def sound_pair(x: ExerciseInput) -> dict[str, Any]:
    ex = x.data
    glosses = {str(k): str(v) for k, v in mapping(ex.get("glosses")).items()}

    def word(keys: tuple[str | int, ...], value: str) -> dict[str, Any]:
        s = x.lock.plain((*x.path, *keys), value)
        token_gloss = next((t.get("gloss") for t in s.tokens if t.get("gloss")), None)
        item = next((t.get("item") for t in s.tokens if t.get("item")), None)
        gloss = glosses.get(value) or token_gloss or (x.item_gloss(item) if item else None)
        return {"it": value, "gloss": gloss, "audioId": None}

    question = str(ex.get("question") or "which-word")
    pair_raw = [str(w) for w in seq(ex.get("pair"))]
    pair = [word(("pair", j), w) for j, w in enumerate(pair_raw)] if pair_raw else None
    play = None
    if pair_raw and isinstance(ex.get("play"), str):
        if ex["play"] not in pair_raw:
            raise BuildError(f"{x.where('play')}: {ex['play']!r} is not a word of the pair")
        play = pair_raw.index(ex["play"])
    w = ex.get("word")
    return {
        "question": question,
        "pair": pair,
        "play": play,
        "word": word(("word",), str(w)) if isinstance(w, str) else None,
        "answer": ex.get("answer") if ex.get("answer") in ("single", "double") else None,
        "tipEn": opt_str(ex.get("tip_en")),
    }


def choice(x: ExerciseInput) -> dict[str, Any]:
    ex = x.data
    italian = italian_options(ex, x.step_kind)
    options = []
    for j, opt in enumerate(seq(ex.get("options"))):
        options.append({"text": str(opt), "it": x.text("options", j) if italian else None})
    return {
        "promptIt": x.opt_text("prompt_it"),
        "promptAudioId": None,
        "audioTextId": x.audio_text_id,
        "plays": int_or(ex.get("plays"), None),
        "questionEn": str(ex.get("question_en", "")),
        "options": options,
        "answer": int_or(ex.get("answer"), 0),
    }


def true_false(x: ExerciseInput) -> dict[str, Any]:
    return {
        "statementEn": str(x.data.get("statement_en", "")),
        "answer": bool(x.data.get("answer")),
        "audioTextId": x.audio_text_id,
        "plays": int_or(x.data.get("plays"), None),
    }


def match(x: ExerciseInput) -> dict[str, Any]:
    pairs = []
    for j, pair in enumerate(seq(x.data.get("pairs"))):
        if not (isinstance(pair, list) and len(pair) == 2):
            raise BuildError(f"{x.where('pairs', j)}: a pair is [Italian, English]")
        pairs.append({"left": x.text("pairs", j, 0), "right": str(pair[1]), "leftAudioId": None})
    return {"pairs": pairs}


def conversation(x: ExerciseInput) -> dict[str, Any]:
    ex = x.data
    nodes = []
    for nid, node in mapping(ex.get("nodes")).items():
        node = mapping(node)
        keys = ("nodes", str(nid))
        expect = []
        for j, intent in enumerate(seq(node.get("expect"))):
            intent = mapping(intent)
            if not isinstance(intent.get("next"), str):
                raise BuildError(f"{x.where(*keys, 'expect', j)}: an intent needs `next`")
            expect.append(
                {
                    "intent": str(intent.get("intent", "")),
                    "goal": opt_str(intent.get("goal")),
                    "accept": [
                        pattern(str(p), x.where(*keys, "expect", j, "accept", a))
                        for a, p in enumerate(seq(intent.get("accept")))
                    ],
                    "next": intent["next"],
                }
            )
        nodes.append(
            {
                "id": str(nid),
                "say": x.text(*keys, "say"),
                "en": str(node.get("en", "")),
                "audioId": None,
                "expect": expect,
                "near": near_list(node.get("near"), x.where(*keys)),
                "help": [x.text(*keys, "help", j) for j in range(len(seq(node.get("help"))))],
                "hintEn": opt_str(node.get("hint_en")),
                "register": node.get("register") if node.get("register") in ("tu", "lei") else None,
                "final": bool(node.get("final", False)),
            }
        )
    title = mapping(ex.get("title"))
    return {
        "with": str(ex.get("with", "")),
        "register": str(ex.get("register", "lei")),
        "titleEn": str(title.get("en", "")),
        "goals": [{"id": str(g.get("id")), "en": str(g.get("en", ""))} for g in map(mapping, seq(ex.get("goals")))],
        "start": str(ex.get("start", "")),
        "nodes": nodes,
    }


def points(x: ExerciseInput) -> list[dict[str, Any]]:
    return [
        {
            "id": str(p.get("id")),
            "en": str(p.get("en", "")),
            "accept": [pattern(str(a), x.where("points", j, "accept", k)) for k, a in enumerate(seq(p.get("accept")))],
        }
        for j, p in enumerate(map(mapping, seq(x.data.get("points"))))
    ]


def min_max(raw: Any) -> dict[str, int] | None:
    m = mapping(raw)
    if "min" not in m and "max" not in m:
        return None
    return {"min": int_or(m.get("min"), 0) or 0, "max": int_or(m.get("max"), 0) or 0}


def talk(x: ExerciseInput) -> dict[str, Any]:
    duration = min_max(x.data.get("duration_s"))
    if duration is None:
        raise BuildError(f"{x.where('duration_s')}: a talk needs duration_s {{min, max}}")
    return {
        "promptEn": str(x.data.get("prompt_en", "")),
        "points": points(x),
        "pass": int_or(x.data.get("pass"), 0),
        "model": x.text("model"),
        "modelAudioId": None,
        "durationS": duration,
    }


def writing(x: ExerciseInput) -> dict[str, Any]:
    ex = x.data
    fields = None
    if isinstance(ex.get("fields"), list):
        fields = []
        for j, f in enumerate(map(mapping, ex["fields"])):
            accept = f.get("accept")
            fields.append(
                {
                    "labelIt": x.text("fields", j, "label_it"),
                    "labelEn": str(f.get("label_en", "")),
                    "type": str(f.get("type", "text")),
                    "accept": [pattern(str(a), x.where("fields", j, "accept", k)) for k, a in enumerate(accept)]
                    if isinstance(accept, list)
                    else None,
                }
            )
    return {
        "kind": str(ex.get("kind", "")),
        "promptEn": str(ex.get("prompt_en", "")),
        "fields": fields,
        "words": min_max(ex.get("words")),
        "points": points(x) if isinstance(ex.get("points"), list) else None,
        "pass": int_or(ex.get("pass"), None),
        "model": x.opt_text("model"),
    }


def relay(x: ExerciseInput) -> dict[str, Any]:
    ans = mapping(x.data.get("answer_en"))
    kind = str(ans.get("type", ""))
    value = ans.get("value")
    if kind in ("price", "number") and isinstance(value, int | float) and not isinstance(value, bool):
        value = value if kind == "price" else int(value)
    elif kind == "time":
        value = str(value)
    else:
        value = None
    source_text = x.source["textId"] if x.source and x.audio_text_id is None else None
    return {
        "sourceTextId": source_text,
        "audioTextId": x.audio_text_id,
        "friendEn": str(x.data.get("friend_en", "")),
        "answerEn": {
            "type": kind,
            "value": value,
            "accept": [str(a) for a in ans["accept"]] if isinstance(ans.get("accept"), list) else None,
        },
    }


BODIES: dict[str, Callable[[ExerciseInput], dict[str, Any]]] = {
    "cloze": cloze,
    "recall": recall,
    "sentence-building": sentence_building,
    "dictation": dictation,
    "repeat": repeat,
    "sound-pair": sound_pair,
    "choice": choice,
    "true-false": true_false,
    "match": match,
    "conversation": conversation,
    "talk": talk,
    "writing": writing,
    "relay": relay,
}


# ---------------------------------------------------------------- real-world layouts (texts.layout)


def layout_payload(layout: Mapping[str, Any], lock: LockFile, path: PathT, targets: frozenset[str]) -> dict[str, Any]:
    """The authored layout with every Italian string as a TokenizedText; strings in `ignore`, and strings with only
    digits and punctuation (prices, times), stay plain strings."""
    ignore = {str(v) for v in seq(layout.get("ignore"))}

    def walk(node: Any, p: PathT) -> Any:
        if isinstance(node, dict):
            return {k: (v if k in LAYOUT_NON_TEXT else walk(v, (*p, k))) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, (*p, i)) for i, v in enumerate(node)]
        if node is None or isinstance(node, bool):
            return node
        text = str(node)
        if text in ignore or not text.strip():
            return text
        s: LockString = lock.plain(p, text)
        return tokenized(s, targets) if has_words(s) else text

    out = walk(dict(layout), path)
    kind = str(layout.get("type", ""))
    out.setdefault("ignore", [])
    for key in LAYOUT_OPTIONAL.get(kind, ()):
        out.setdefault(key, None)
    row_keys = LAYOUT_ROW_OPTIONAL.get(kind, ())
    if row_keys:
        rows = [r for sec in seq(out.get("sections")) for r in seq(mapping(sec).get("rows"))] + seq(out.get("rows"))
        for row in rows:
            if isinstance(row, dict):
                for key in row_keys:
                    row.setdefault(key, None)
    return out
