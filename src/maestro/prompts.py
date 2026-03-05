"""
Prompt template loader. All prompts live in prompts/*.yaml at the repo root.

Each YAML file has a top-level `version` string and named entries.
Each entry has `user` and/or `system` fields with {{variable}} placeholders.

Substitution rules:
  {{variable_name}}  →  replaced at render time via render(**kwargs)
  {anything}         →  left untouched (JSON schemas, drill item format, etc.)

This means prompts can be pasted directly into the Claude Workbench
(which uses the same {{variable}} syntax) for manual iteration.

Usage:
    from maestro import prompts
    text = prompts.analyzer.analyze_message.render(text=..., grammar_lines=..., ...)
    version = prompts.analyzer.version   # e.g. "1"
    system = prompts.vocab.definitions_system.render_system()
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def _substitute(template: str, kwargs: dict) -> str:
    """Replace {{variable}} placeholders; leave single {braces} untouched."""
    return re.sub(
        r"\{\{(\w+)\}\}",
        lambda m: str(kwargs.get(m.group(1), m.group(0))),
        template,
    )


@dataclass
class PromptTemplate:
    name: str
    version: str
    description: str
    system: Optional[str] = None
    user: Optional[str] = None

    def render(self, **kwargs) -> str:
        """Return the user prompt with {{variable}} placeholders filled in."""
        return _substitute(self.user or "", kwargs)

    def render_system(self, **kwargs) -> Optional[str]:
        """Return the system prompt with {{variable}} placeholders filled in."""
        if not self.system:
            return None
        return _substitute(self.system, kwargs)


class _PromptFile:
    """Lazy-loaded collection of PromptTemplates from a single YAML file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._templates: Optional[dict[str, PromptTemplate]] = None
        self._version: str = "unknown"

    def _load(self) -> None:
        if self._templates is not None:
            return
        raw: dict = yaml.safe_load(self._path.read_text())
        self._version = str(raw.get("version", "1"))
        self._templates = {}
        for name, val in raw.items():
            if name == "version" or not isinstance(val, dict):
                continue
            self._templates[name] = PromptTemplate(
                name=name,
                version=self._version,
                description=val.get("description", ""),
                system=val.get("system"),
                user=val.get("user"),
            )

    @property
    def version(self) -> str:
        self._load()
        return self._version

    def __getattr__(self, name: str) -> PromptTemplate:
        # Only called for attributes not found through normal lookup.
        self._load()
        if self._templates and name in self._templates:
            return self._templates[name]
        raise AttributeError(f"No prompt '{name}' in {self._path.name}")


# ---------------------------------------------------------------------------
# Module-level file objects — loaded lazily on first attribute access
# ---------------------------------------------------------------------------

analyzer = _PromptFile(_PROMPTS_DIR / "analyzer.yaml")
lesson_analyzer = _PromptFile(_PROMPTS_DIR / "lesson_analyzer.yaml")
planner = _PromptFile(_PROMPTS_DIR / "planner.yaml")
vocab = _PromptFile(_PROMPTS_DIR / "vocab_definitions.yaml")
grammar = _PromptFile(_PROMPTS_DIR / "grammar_explanations.yaml")
