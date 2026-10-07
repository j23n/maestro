"""The annotation tokeniser (docs/04 § Annotation step 1).

- Words are runs of letters (with combining marks); a hyphen between two letters stays inside (`e-mail`).
- An apostrophe after a letter ends the word and stays with it: `l'amica` → `l'` + `amica`, `c'è` → `c'` + `è`,
  `quant'è` → `quant'` + `è`, `po'`. An apostrophe that opens a quotation is punctuation, and so is the one that
  closes it.
- Digits (with `.` `,` `:` between digits: `6,20`, `10:15`) are `number` tokens.
- A line's `foreign` entries (one or more words, case-insensitive) become `foreign` tokens.
- Allowlisted names become `name` tokens, matched **case-sensitively** (`Rosa` is a name, `rosa` is pink).
  `lemmas:` on the line overrides a name (`{Rosa: w:rosa}`).
- Every other non-space character is a `punct` token (one per character).
- Protected spans (pattern slots such as `{NAME}`) are single `slot` tokens.

Each token keeps the text up to the next token in `trailing` (whitespace, and markup characters such as the `*` of
note fragments when `markup` is given), and `tokenize` returns the text before the first token, so
`lead + Σ(surface + trailing)` re-renders the input exactly.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

APOSTROPHES = frozenset("'’ʼ")
NUMBER_JOINERS = frozenset(".,:")
SENTENCE_END = frozenset(".!?…")
QUOTES_AND_OPENERS = frozenset("\"“”„«»'’‘()[]–—-")

WORD = "word"
NAME = "name"
NUMBER = "number"
FOREIGN = "foreign"
PUNCT = "punct"
SLOT = "slot"


@dataclass
class Token:
    surface: str
    start: int
    end: int
    kind: str
    trailing: str = ""
    slot: str | None = None

    @property
    def norm(self) -> str:
        """Lowercase with plain apostrophes: the form used for lookups and matching."""
        return fold(self.surface)


def fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower().replace("’", "'").replace("ʼ", "'")


def _is_letter(ch: str) -> bool:
    return ch.isalpha() or unicodedata.category(ch).startswith("M")


def _raw_tokens(text: str, markup: frozenset[str], protected: Sequence[tuple[int, int, str]]) -> list[Token]:
    out: list[Token] = []
    prot = {s: (e, name) for s, e, name in protected}
    open_quote = False
    i = 0
    n = len(text)
    while i < n:
        if i in prot:
            e, name = prot[i]
            out.append(Token(text[i:e], i, e, SLOT, slot=name))
            i = e
            continue
        ch = text[i]
        if ch.isspace() or ch in markup:
            i += 1
            continue
        if _is_letter(ch):
            j = i + 1
            while j < n and j not in prot:
                c = text[j]
                if _is_letter(c) or (c == "-" and j + 1 < n and _is_letter(text[j + 1]) and _is_letter(text[j - 1])):
                    j += 1
                else:
                    break
            if j < n and text[j] in APOSTROPHES:
                follows_letter = j + 1 < n and _is_letter(text[j + 1])
                if follows_letter or not open_quote:
                    j += 1
            out.append(Token(text[i:j], i, j, WORD))
            i = j
            continue
        if ch.isdigit():
            j = i + 1
            while j < n:
                if text[j].isdigit() or (text[j] in NUMBER_JOINERS and j + 1 < n and text[j + 1].isdigit()):
                    j += 1
                else:
                    break
            out.append(Token(text[i:j], i, j, NUMBER))
            i = j
            continue
        if ch in APOSTROPHES:
            open_quote = not open_quote
        out.append(Token(ch, i, i + 1, PUNCT))
        i += 1
    return out


def tokenize(
    text: str,
    *,
    foreign: Iterable[str] = (),
    names: Iterable[str] = (),
    not_names: Iterable[str] = (),
    markup: str = "",
    protected: Sequence[tuple[int, int, str]] = (),
) -> tuple[str, list[Token]]:
    """Tokenise one Italian string; returns (lead, tokens).

    `not_names` are surfaces the line's `lemmas:` maps to items (they stay words even if they are names)."""
    toks = _raw_tokens(text, frozenset(markup), protected)
    # foreign sequences (longest first, case-insensitive, over consecutive word tokens)
    seqs = sorted(
        {tuple(fold(t.surface) for t in _raw_tokens(f, frozenset(), ()) if t.kind == WORD) for f in foreign},
        key=len,
        reverse=True,
    )
    seqs = [s for s in seqs if s]
    if seqs:
        i = 0
        while i < len(toks):
            for s in seqs:
                window = toks[i : i + len(s)]
                if len(window) == len(s) and all(t.kind == WORD for t in window) and tuple(t.norm for t in window) == s:
                    for t in window:
                        t.kind = FOREIGN
                    i += len(s) - 1
                    break
            i += 1
    name_set = set(names)
    blocked = {fold(x) for x in not_names}
    for t in toks:
        if t.kind == WORD and t.surface in name_set and t.norm not in blocked:
            t.kind = NAME
    for k, t in enumerate(toks):
        nxt = toks[k + 1].start if k + 1 < len(toks) else len(text)
        t.trailing = text[t.end : nxt]
    lead = text[: toks[0].start] if toks else text
    return lead, toks


def render(lead: str, tokens: Iterable[Token]) -> str:
    return lead + "".join(t.surface + t.trailing for t in tokens)


def sentence_initial(tokens: Sequence[Token], k: int) -> bool:
    """True if token k starts a sentence: the first non-punctuation token, or one after . ! ? … (quotes skipped)."""
    j = k - 1
    while j >= 0 and tokens[j].kind == PUNCT and tokens[j].surface in QUOTES_AND_OPENERS:
        j -= 1
    if j < 0:
        return True
    return tokens[j].kind == PUNCT and tokens[j].surface in SENTENCE_END
