"""YAML loading for content (docs/04): ruamel.yaml in safe mode, YAML 1.2, so `no`, `sì`, `on`, `off` stay strings.

Never use PyYAML's default loader on content. Loaded documents are plain dicts and lists; line numbers for error
messages come from a separate round-trip load (`locate`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError


class ContentYAMLError(Exception):
    """A YAML file that does not parse. The message names the file and position.

    `problem` is a one-line description and `line` the 1-based line of the problem (when the parser knows them).
    """

    def __init__(self, message: str, *, problem: str | None = None, line: int | None = None) -> None:
        super().__init__(message)
        self.problem = problem or message
        self.line = line


def _safe() -> YAML:
    y = YAML(typ="safe", pure=True)
    y.version = (1, 2)
    return y


def _rt() -> YAML:
    y = YAML(typ="rt", pure=True)
    y.version = (1, 2)
    return y


def load(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ContentYAMLError(f"{path}: not UTF-8 ({exc})") from exc
    return loads(text, str(path))


def loads(text: str, name: str = "<string>") -> Any:
    try:
        return _safe().load(text)
    except YAMLError as exc:
        problem = getattr(exc, "problem", None)
        context = getattr(exc, "context", None)
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        line = mark.line + 1 if mark is not None else None
        short = " ".join(str(problem or exc).split())
        if context:
            short += f" ({' '.join(str(context).split())})"
        raise ContentYAMLError(f"{name}: {exc}", problem=short, line=line) from exc


def load_roundtrip(path: Path) -> Any:
    """Round-trip load (keeps line numbers) for error locations."""
    return _rt().load(path.read_text(encoding="utf-8"))


def locate(doc: Any, json_path: list[str | int]) -> int | None:
    """1-based line of the node at `json_path` in a round-trip document, or None."""
    node = doc
    line: int | None = None
    for key in json_path:
        try:
            if isinstance(node, CommentedMap) and key in node:
                pos = node.lc.key(key)
                line = pos[0] + 1 if pos else line
                node = node[key]
            elif isinstance(node, CommentedSeq) and isinstance(key, int) and key < len(node):
                pos = node.lc.item(key)
                line = pos[0] + 1 if pos else line
                node = node[key]
            else:
                break
        except (KeyError, IndexError, TypeError, AttributeError):
            break
    return line
