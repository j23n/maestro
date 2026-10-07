"""Chunk matching (docs/04 § Annotation step 2).

Each chunk item's `match` sequences are tokenised like any Italian string and matched against consecutive word
tokens (punctuation, names, numbers and foreign words break a match). Scanning left to right, the longest match wins
(ties: the chunk ID sorting first). Matching ignores case unless the chunk has `case_sensitive: true`; a
case-sensitive chunk still matches when its first word is capitalised at the start of a sentence (`E Lei?` matches
`e Lei`, `e lei` does not).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from itcontent.tokenize import WORD, Token, fold, sentence_initial, tokenize


@dataclass(frozen=True)
class ChunkSeq:
    chunk_id: str
    words: tuple[str, ...]  # folded, or apostrophe-normalised only when case-sensitive
    case_sensitive: bool


def _apos(text: str) -> str:
    return text.replace("’", "'").replace("ʼ", "'")


class ChunkMatcher:
    def __init__(self, chunk_items: Iterable[dict[str, Any]]) -> None:
        seqs: list[ChunkSeq] = []
        for item in chunk_items:
            cs = bool(item.get("case_sensitive"))
            for m in item.get("match") or []:
                _, toks = tokenize(str(m))
                words = tuple(_apos(t.surface) if cs else t.norm for t in toks if t.kind == WORD)
                if words:
                    seqs.append(ChunkSeq(str(item["id"]), words, cs))
        # longest first, then by chunk ID: the first hit at a position is the winner
        self.seqs = sorted(seqs, key=lambda s: (-len(s.words), s.chunk_id, s.words))

    def _hit(self, seq: ChunkSeq, toks: Sequence[Token], i: int) -> bool:
        window = toks[i : i + len(seq.words)]
        if len(window) != len(seq.words) or any(t.kind != WORD for t in window):
            return False
        for k, (t, w) in enumerate(zip(window, seq.words, strict=True)):
            if not seq.case_sensitive:
                if t.norm != w:
                    return False
                continue
            s = _apos(t.surface)
            if s == w:
                continue
            if k == 0 and sentence_initial(toks, i) and s == w[:1].upper() + w[1:]:
                continue
            return False
        return True

    def match(self, toks: Sequence[Token]) -> list[tuple[int, int, str]]:
        """Chunk matches as (first token, last token + 1, chunk ID), left to right, non-overlapping."""
        out: list[tuple[int, int, str]] = []
        i = 0
        while i < len(toks):
            hit = next((s for s in self.seqs if self._hit(s, toks, i)), None)
            if hit is None:
                i += 1
                continue
            out.append((i, i + len(hit.words), hit.chunk_id))
            i += len(hit.words)
        return out


def find_sequences(toks: Sequence[Token], phrase: str, kinds: frozenset[str]) -> list[tuple[int, int]]:
    """Every (start, end) where the phrase's word tokens occur as consecutive tokens of the given kinds,
    case-insensitively (gloss, recognise and lemmas keys on a line)."""
    _, ptoks = tokenize(phrase)
    words = [fold(t.surface) for t in ptoks if t.kind not in ("punct",)]
    out: list[tuple[int, int]] = []
    if not words:
        return out
    for i in range(len(toks) - len(words) + 1):
        window = toks[i : i + len(words)]
        if all(t.kind in kinds for t in window) and [t.norm for t in window] == words:
            out.append((i, i + len(words)))
    return out
