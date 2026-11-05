"""Answer patterns for open answers (HANDOFF.md 3.9): `(optional)` words and `{a|b}` choices, nestable.

    {Volentieri|Con piacere}!          Volentieri!  Con piacere!
    Credo di sì(, perché)?             Credo di sì?  Credo di sì, perché?
    {Ci vediamo|Vediamoci} (prima)     four answers

The app's PracticeKit (PatternGrader) reads the same syntax. The build expands each pattern to check
it parses and stays small, and to test that it accepts what it should.
"""

from __future__ import annotations

MAX_VARIANTS = 256


class PatternError(ValueError):
    pass


def _parse(s: str, i: int, closer: str | None) -> tuple[list[list], int]:
    """Alternatives (lists of parts) up to the closer; a part is a string or ("opt"|"alt", alternatives)."""
    alts: list[list] = [[]]
    buf = ""
    while i < len(s):
        c = s[i]
        if c in "({":
            if buf:
                alts[-1].append(buf)
                buf = ""
            inner, i = _parse(s, i + 1, ")" if c == "(" else "}")
            alts[-1].append(("opt" if c == "(" else "alt", inner))
            continue
        if c in ")}":
            if c != closer:
                raise PatternError(f"unexpected {c!r} in {s!r}")
            if buf:
                alts[-1].append(buf)
            return alts, i + 1
        if c == "|" and closer is not None:
            if buf:
                alts[-1].append(buf)
                buf = ""
            alts.append([])
            i += 1
            continue
        buf += c
        i += 1
    if closer is not None:
        raise PatternError(f"missing {closer!r} in {s!r}")
    if buf:
        alts[-1].append(buf)
    return alts, i


def _expand(parts: list) -> list[str]:
    out = [""]
    for part in parts:
        if isinstance(part, str):
            choices = [part]
        else:
            kind, alts = part
            choices = [v for alt in alts for v in _expand(alt)]
            if kind == "opt":
                choices = [""] + choices
        out = [a + b for a in out for b in choices]
        if len(out) > MAX_VARIANTS:
            raise PatternError(f"more than {MAX_VARIANTS} answers")
    return out


def expand(pattern: str) -> list[str]:
    """Every answer the pattern accepts, with spaces collapsed, in a stable order."""
    alts, _ = _parse(pattern, 0, None)
    seen: dict[str, None] = {}
    for alt in alts:
        for v in _expand(alt):
            v = " ".join(v.split())
            v = v.replace(" ,", ",").replace(" .", ".").replace(" !", "!").replace(" ?", "?")
            if v:
                seen[v] = None
    return list(seen)
