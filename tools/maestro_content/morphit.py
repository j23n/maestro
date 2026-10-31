"""Read Morph-it! (form TAB lemma TAB analysis), an optional second source of form-to-lemma links."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from . import tags as tagmap
from .normalize import nfc


@dataclass
class MorphForm:
    form: str
    lemma: str
    pos: str
    tag: str


def read(path: str) -> Iterator[MorphForm]:
    with open(path, "rb") as fh:
        for raw in fh:
            try:
                line = raw.decode("utf-8")
            except UnicodeDecodeError:
                line = raw.decode("latin-1")
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) != 3:
                continue
            form, lemma, analysis = (nfc(p.strip()) for p in parts)
            pos = tagmap.morphit_pos(analysis)
            tag = tagmap.morphit_tag(analysis)
            if pos is None or tag is None or not form or " " in form:
                continue
            yield MorphForm(form=form, lemma=lemma, pos=pos, tag=tag)
