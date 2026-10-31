"""The ID registry (HANDOFF.md 6.5).

Lemma and sense IDs are minted once and never reused. content/ids/lemmas.tsv and senses.tsv map
each ID to the fingerprint it was minted from, so a rebuild from a newer dump keeps old IDs.
Sense codes are hash-derived, so the same dump always yields the same IDs.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import os
from dataclasses import dataclass, field

from .normalize import fold, nfc


def headword_key(headword: str, pos: str) -> str:
    hw = nfc(headword.strip())
    if pos != "propn":
        hw = hw.lower()
    return hw.replace(" ", "_")


def base_lemma_id(headword: str, pos: str) -> str:
    return f"it:{headword_key(headword, pos)}:{pos}"


def sense_fingerprint(senseid: str | None, wikidata: str | None, lemma_id: str, gloss: str) -> str:
    if senseid:
        return f"senseid:{senseid}"
    if wikidata:
        return f"wikidata:{wikidata}"
    return f"gloss:{lemma_id}|{fold(gloss).strip()}"


def _code(fingerprint: str, length: int) -> str:
    digest = hashlib.sha256(fingerprint.encode("utf-8")).digest()
    return base64.b32encode(digest).decode("ascii").lower()[:length]


@dataclass
class Registry:
    # id -> (fingerprint, label); label is the headword or the last gloss, kept for retired IDs
    lemmas: dict[str, tuple[str, str]] = field(default_factory=dict)
    senses: dict[str, tuple[str, str]] = field(default_factory=dict)
    used_lemmas: set[str] = field(default_factory=set)
    used_senses: set[str] = field(default_factory=set)

    # --- persistence ---
    @classmethod
    def load(cls, directory: str | None) -> "Registry":
        reg = cls()
        if not directory:
            return reg
        for name, target in (("lemmas.tsv", reg.lemmas), ("senses.tsv", reg.senses)):
            path = os.path.join(directory, name)
            if os.path.exists(path):
                with open(path, encoding="utf-8", newline="") as fh:
                    for row in csv.reader(fh, delimiter="\t"):
                        if len(row) >= 3 and not row[0].startswith("#"):
                            target[row[0]] = (row[1], row[2])
        return reg

    def save(self, directory: str) -> None:
        os.makedirs(directory, exist_ok=True)
        for name, source in (("lemmas.tsv", self.lemmas), ("senses.tsv", self.senses)):
            with open(os.path.join(directory, name), "w", encoding="utf-8", newline="") as fh:
                fh.write("# id\tfingerprint\tlabel  (written by tools/maestro_content; never edit by hand)\n")
                writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
                for key in sorted(source):
                    writer.writerow([key, *source[key]])

    # --- minting ---
    def lemma_id(self, headword: str, pos: str, fingerprint: str) -> str:
        """The lemma's ID: reuse the one minted for this fingerprint, else the next free homograph slot."""
        base = base_lemma_id(headword, pos)
        candidates = [base] + [f"{base}:{n}" for n in range(2, 100)]
        for cid in candidates:
            known = self.lemmas.get(cid)
            if known and known[0] == fingerprint and cid not in self.used_lemmas:
                self.used_lemmas.add(cid)
                return cid
        for cid in candidates:
            if cid not in self.lemmas and cid not in self.used_lemmas:
                self.lemmas[cid] = (fingerprint, headword)
                self.used_lemmas.add(cid)
                return cid
        raise ValueError(f"too many homographs for {base}")

    def sense_id(self, lemma_id: str, fingerprint: str, gloss: str) -> str:
        for length in range(4, 13):
            sid = f"{lemma_id}#{_code(fingerprint, length)}"
            known = self.senses.get(sid)
            if known is None:
                self.senses[sid] = (fingerprint, gloss)
                self.used_senses.add(sid)
                return sid
            if known[0] == fingerprint:
                self.senses[sid] = (fingerprint, gloss)
                self.used_senses.add(sid)
                return sid
        raise ValueError(f"sense code collision for {lemma_id}")

    def retired_senses(self) -> list[tuple[str, str]]:
        """Senses minted earlier that the current dump no longer has: (id, last gloss)."""
        return [(sid, v[1]) for sid, v in self.senses.items() if sid not in self.used_senses]
