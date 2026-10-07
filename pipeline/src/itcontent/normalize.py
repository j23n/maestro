"""Answer normalisation (docs/05 § Normalisation), shared with LearningCore's `Normalizer` through
`fixtures/grading/normalizer.json`.

1. Unicode NFC.  2. ’ ‘ ʼ ´ ` → '.  3. Lowercase (it_IT).  4. Punctuation → space, except . , : between two digits;
a hyphen survives only between two letters.  5. No spaces next to apostrophes.  6. Collapse whitespace and trim.

`normalize_marked` runs the same steps over characters that carry an attribute (focus, slot), so the answer-pattern
expander (`itcontent.patterns`) can tell which normalised tokens came from a focus group or a slot. Characters whose
attribute is *protected* (slots) are neither lowercased nor treated as punctuation.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Sequence

APOSTROPHES = frozenset("’‘ʼ´`")
PUNCTUATION = frozenset('.,;:!?¡¿«»"“”„()[]–—…')
DIGIT_JOINERS = frozenset(".,:")

#: Words that never get accent tolerance (docs/05): e/è, si/sì, la/là, li/lì, da/dà, se/sé, ne/né, te/tè, di/dì.
ACCENT_SENSITIVE: frozenset[str] = frozenset(
    ["e", "è", "si", "sì", "la", "là", "li", "lì", "da", "dà", "se", "sé", "ne", "né", "te", "tè", "di", "dì"]
)


def _is_letter(ch: str) -> bool:
    return ch.isalpha()


def _is_digit(ch: str) -> bool:
    return ch.isdigit()


def normalize_marked[A](
    chars: Sequence[str], attrs: Sequence[A], protected: Callable[[A], bool] = lambda _: False
) -> tuple[list[str], list[A]]:
    """Normalise a character sequence whose characters carry attributes; returns the normalised characters and the
    attribute of each. `chars` should already be NFC (the caller normalises the whole string first)."""
    # 2 + 3: apostrophes and lowercase (a lowercased character may expand; it keeps its attribute)
    cs: list[str] = []
    ats: list[A] = []
    for ch, at in zip(chars, attrs, strict=True):
        if protected(at):
            cs.append(ch)
            ats.append(at)
            continue
        if ch in APOSTROPHES:
            ch = "'"
        for low in ch.lower():
            cs.append(low)
            ats.append(at)
    # 4: punctuation and hyphens
    out: list[str] = []
    for i, ch in enumerate(cs):
        if protected(ats[i]):
            out.append(ch)
            continue
        prev = cs[i - 1] if i > 0 else ""
        nxt = cs[i + 1] if i + 1 < len(cs) else ""
        if ch in PUNCTUATION:
            if ch in DIGIT_JOINERS and prev and nxt and _is_digit(prev) and _is_digit(nxt):
                out.append(ch)
            else:
                out.append(" ")
        elif ch == "-":
            out.append(ch if prev and nxt and _is_letter(prev) and _is_letter(nxt) else " ")
        elif ch.isspace():
            out.append(" ")
        else:
            out.append(ch)
    # 5: drop spaces next to apostrophes; 6: collapse and trim
    keep: list[int] = []
    for i, ch in enumerate(out):
        if ch == " " and not protected(ats[i]):
            j = i - 1
            while j >= 0 and out[j] == " ":
                j -= 1
            k = i + 1
            while k < len(out) and out[k] == " ":
                k += 1
            if (j >= 0 and out[j] == "'" and not protected(ats[j])) or (
                k < len(out) and out[k] == "'" and not protected(ats[k])
            ):
                continue
            if not keep or out[keep[-1]] == " ":  # leading space or a run of spaces
                continue
        keep.append(i)
    while keep and out[keep[-1]] == " ":
        keep.pop()
    return [out[i] for i in keep], [ats[i] for i in keep]


def normalize(text: str) -> str:
    """Normalise an answer or a pattern expansion for comparison (docs/05 § Normalisation)."""
    nfc = unicodedata.normalize("NFC", text)
    chars, _ = normalize_marked(list(nfc), [None] * len(nfc))
    return "".join(chars)


def tokens(text: str) -> list[str]:
    """The space-separated tokens of the normalised text."""
    n = normalize(text)
    return n.split(" ") if n else []


def strip_accents(text: str) -> str:
    """Remove combining marks after NFD (`perché` → `perche`); the result is NFC."""
    nfd = unicodedata.normalize("NFD", text)
    return unicodedata.normalize("NFC", "".join(ch for ch in nfd if not unicodedata.combining(ch)))


def is_accent_sensitive(token: str) -> bool:
    return token in ACCENT_SENSITIVE
