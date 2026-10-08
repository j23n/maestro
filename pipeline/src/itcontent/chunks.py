"""Chunk matching (docs/04 § Annotation step 2).

Each chunk item's `match` sequences are tokenised like any Italian string and matched against consecutive word
tokens (punctuation, names, numbers and foreign words break a match). Scanning left to right, the longest match wins
(ties: the chunk ID sorting first). Matching ignores case unless the chunk has `case_sensitive: true`; a
case-sensitive chunk still matches when its first word is capitalised at the start of a sentence (`E Lei?` matches
`e Lei`, `e lei` does not).

A personal slot supplies the end of a chunk: `abito {ME.home}` matches `c:abito` (`abito in`, `abito negli`, …) when
the chunk's last word is one the slot's fillers start with (`slot_heads`: the first words of the countries'
`home_phrase` and `alt_home_phrases`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from itcontent.tokenize import SLOT, WORD, Token, fold, sentence_initial, tokenize


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

    def _hit(self, seq: ChunkSeq, toks: Sequence[Token], i: int, n: int | None = None) -> bool:
        words = seq.words[: len(seq.words) if n is None else n]
        window = toks[i : i + len(words)]
        if len(window) != len(words) or any(t.kind != WORD for t in window):
            return False
        for k, (t, w) in enumerate(zip(window, words, strict=True)):
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

    def _slot_hit(self, seq: ChunkSeq, toks: Sequence[Token], i: int, heads: Mapping[str, frozenset[str]]) -> bool:
        """All but the last word match, and a personal slot whose fillers start with that word follows."""
        n = len(seq.words) - 1
        if n < 1 or i + n >= len(toks) or toks[i + n].kind != SLOT:
            return False
        return fold(seq.words[-1]) in heads.get(str(toks[i + n].slot), frozenset()) and self._hit(seq, toks, i, n)

    def match(
        self, toks: Sequence[Token], slot_heads: Mapping[str, frozenset[str]] | None = None
    ) -> list[tuple[int, int, str]]:
        """Chunk matches as (first token, last token + 1, chunk ID), left to right, non-overlapping."""
        heads = slot_heads or {}
        out: list[tuple[int, int, str]] = []
        i = 0
        while i < len(toks):
            hit = next((s for s in self.seqs if self._hit(s, toks, i)), None)
            if hit is not None:
                out.append((i, i + len(hit.words), hit.chunk_id))
                i += len(hit.words)
                continue
            hit = next((s for s in self.seqs if heads and self._slot_hit(s, toks, i, heads)), None)
            if hit is not None:
                out.append((i, i + len(hit.words) - 1, hit.chunk_id))
                i += len(hit.words) - 1
                continue
            i += 1
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
