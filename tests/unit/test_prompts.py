"""The runtime prompts are shared by the app and the eval harness — that
sharing is what makes "the eval measures what ships" true.

These tests pin the two ways that can quietly break: the app reading a
different copy than the harness, and a template growing a placeholder the
app doesn't supply (which renders a literal `{foo}` into the prompt and
degrades quality with nothing failing).
"""

import json
from pathlib import Path
from string import Formatter

import pytest

from authoring.prompts import TASKS, build_prompts, load_prompts

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "prompts" / "runtime"

# What the app fills in for every task (FeedbackService.variables). A
# template may use any of these plus its own `defaults`.
APP_SUPPLIED = {"level", "prompt", "submission", "weakness_tags"}
# Extra variables the app supplies for specific tasks only.
APP_SUPPLIED_PER_TASK = {
    "speaking_feedback": {"target_text", "alignment_summary"},
    "mistake_explanation": {
        "correct_answer",
        "response",
        "grammar_label",
        "standard_explanation",
    },
}


def placeholders(template: str) -> set[str]:
    """Named `{fields}`, ignoring `{{escaped}}` JSON braces."""
    return {f for _, f, _, _ in Formatter().parse(template) if f}


def test_every_task_has_a_runtime_prompt():
    prompts = load_prompts(RUNTIME)
    assert set(prompts) == set(TASKS)


@pytest.mark.parametrize("task", TASKS)
def test_template_placeholders_are_all_supplied(task):
    prompt = load_prompts(RUNTIME)[task]
    supplied = (
        APP_SUPPLIED | APP_SUPPLIED_PER_TASK.get(task, set()) | set(prompt["defaults"])
    )
    unknown = placeholders(prompt["template"]) - supplied
    assert not unknown, (
        f"{task}: template uses {sorted(unknown)}, which nothing supplies — "
        "the app would render these literally. Add them to FeedbackService "
        "and to APP_SUPPLIED_PER_TASK, or give them a default."
    )


@pytest.mark.parametrize("task", TASKS)
def test_template_renders_with_the_supplied_variables(task):
    """Beyond names: the template must actually format, so the escaped
    JSON braces in the output spec can't regress into format errors."""
    prompt = load_prompts(RUNTIME)[task]
    variables = {
        name: "x" for name in APP_SUPPLIED | APP_SUPPLIED_PER_TASK.get(task, set())
    }
    rendered = prompt["template"].format(**{**prompt["defaults"], **variables})
    assert "{" in rendered, "the JSON output spec should survive rendering"


def test_bundle_is_a_faithful_copy_of_the_yaml(tmp_path):
    """The app reads the JSON, the harness reads the YAML. If the emitter
    ever rewrote content, the two would drift apart silently."""
    out = tmp_path / "prompts.json"
    assert build_prompts(out, RUNTIME) == 0
    bundled = json.loads(out.read_text())
    source = load_prompts(RUNTIME)
    assert bundled == source
    for task in TASKS:
        assert bundled[task]["system"] == source[task]["system"]
        assert bundled[task]["version"] == source[task]["version"]
