"""Model runners: one per backend, all consuming the same versioned
prompt templates from prompts/runtime/ that the app ships."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Protocol

import yaml

from evals.harness.schema import Case

PROMPTS_DIR = Path("prompts/runtime")


class PromptTemplate:
    def __init__(self, task: str, prompts_dir: Path = PROMPTS_DIR):
        raw = yaml.safe_load((prompts_dir / f"{task}.yaml").read_text())
        self.version: int = raw["version"]
        self.system: str = raw["system"]
        self.template: str = raw["template"]
        self.defaults: dict = raw.get("defaults") or {}

    def render(self, case: Case) -> str:
        variables = {
            **self.defaults,
            **case.input.model_dump(),
            "weakness_tags": ", ".join(case.input.weakness_tags) or "none",
        }
        return self.template.format(**variables)


class Runner(Protocol):
    name: str

    def run(self, case: Case, prompt: PromptTemplate) -> str: ...


class MockRunner:
    """Canned outputs keyed by case id — for harness tests and dry runs."""

    name = "mock"

    def __init__(self, outputs: dict[str, str]):
        self.outputs = outputs

    def run(self, case: Case, prompt: PromptTemplate) -> str:
        return self.outputs[case.id]


class AnthropicRunner:
    """The cloud reference backend (and regression baseline)."""

    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-5"):
        self.model = model

    def run(self, case: Case, prompt: PromptTemplate) -> str:
        import anthropic  # lazy

        client = anthropic.Anthropic()
        message = client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=prompt.system,
            messages=[{"role": "user", "content": prompt.render(case)}],
        )
        return "".join(b.text for b in message.content if b.type == "text")


class AppleFMRunner:
    """Apple Foundation Models via the Swift CLI (macOS 26, Apple silicon).

    Protocol: one JSON object per line on stdin
    ({"system": ..., "prompt": ...}), one JSON object per line on stdout
    ({"output": ...} or {"error": ...}). CLI source: evals/applefm-runner/.
    """

    name = "apple_fm"

    def __init__(
        self, binary: str = "evals/applefm-runner/.build/release/applefm-runner"
    ):
        self.binary = binary

    def run(self, case: Case, prompt: PromptTemplate) -> str:
        request = json.dumps({"system": prompt.system, "prompt": prompt.render(case)})
        proc = subprocess.run(
            [self.binary],
            input=request + "\n",
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        reply = json.loads(proc.stdout.strip().splitlines()[-1])
        if "error" in reply:
            raise RuntimeError(reply["error"])
        return reply["output"]
