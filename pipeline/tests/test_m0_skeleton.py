"""M0.4: the CLI exists, `content lint` passes on the live course, the data pins parse, IDs have formats."""

from __future__ import annotations

from typer.testing import CliRunner

from itcontent import ids, yamlio
from itcontent.cli import app
from itcontent.data_fetch import read_pins
from itcontent.lint import run_lint


def test_lint_passes_on_the_live_course(root):
    assert run_lint(root, echo=lambda _: None) == 0


def test_cli_lint_command(root):
    result = CliRunner().invoke(app, ["lint"])
    assert result.exit_code == 0, result.output


def test_yaml_12_keeps_italian_no_and_si_as_strings():
    doc = yamlio.loads("a: no\nb: sì\nc: on\nd: off\ne: yes\n")
    assert doc == {"a": "no", "b": "sì", "c": "on", "d": "off", "e": "yes"}


def test_data_pins_parse(root):
    pins = {p.path: p for p in read_pins(root / "pipeline" / "data" / "SOURCES.md")}
    assert set(pins) == {"morph-it/morph-it.txt", "frequency/it_50k.txt"}
    assert all(len(p.sha256) == 64 and p.sources for p in pins.values())


def test_id_formats():
    good = {
        "u02": "unit",
        "u02.l1": "lesson",
        "u02.l1.step-story": "lesson_step",
        "u02.step-conversation-1": "unit_step",
        "u02.l1.story": "text",
        "u02.check.01.audio": "text",
        "u02.l1.ex07": "exercise",
        "u02.task.conv1": "exercise",
        "pl.03": "exercise",
        "fin.listening.01": "exercise",
        "u02.l1.note": "note",
        "w:pesca~fruit": "item",
        "cd:order-food-drink": "can_do",
        "sy:gr.articles": "syllabus",
        "ch:zia-rosa": "character",
        "topic:food-drink": "topic",
        "gb-wls": "country",
        "a:3f9c0e1a2b4d": "audio",
        "u02.l1.step-preview.b1.w-cornetto": "generated_exercise",
        "gen:recall:w:cornetto": "generated_exercise",
    }
    for value, kind in good.items():
        assert ids.is_valid(value, kind), value
    for bad in ["U02", "w:Caffè", "u2.l1", "sy:xx.foo", "a:3f9c"]:
        assert ids.kind_of(bad) is None, bad


def test_slugify():
    assert ids.slugify("caffè") == "caffe"
    assert ids.slugify("quant'è") == "quant-e"
    assert ids.slugify("come si dice") == "come-si-dice"
