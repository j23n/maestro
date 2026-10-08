"""M1.3 and M8.3 in a real browser: the review page's script comments, saves, downloads and signs off.

Playwright drives headless Chromium over the page opened from disk (file://), as the teacher would open it. Skipped
when the `playwright` package or a Chromium build isn't installed (never runs `playwright install`): the default
browser is tried first, then any Chromium under PLAYWRIGHT_BROWSERS_PATH or ~/.cache/ms-playwright.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from itcontent import schemas
from itcontent.review_export import export

sync_api = pytest.importorskip("playwright.sync_api")

EXECUTABLES = (
    "chromium_headless_shell-*/chrome-linux*/headless_shell",
    "chromium-*/chrome-linux*/chrome",
    "chromium_headless_shell-*/chrome-mac*/headless_shell",
    "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
)


def _launch(p: Any) -> Any:
    try:
        return p.chromium.launch()
    except Exception:
        pass
    base = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or Path.home() / ".cache" / "ms-playwright")
    for pattern in EXECUTABLES:
        for exe in sorted(base.glob(pattern), reverse=True):
            try:
                return p.chromium.launch(executable_path=str(exe))
            except Exception:
                continue
    pytest.skip("no Chromium build for Playwright on this machine")


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_api.sync_playwright() as p:
        b = _launch(p)
        yield b
        b.close()


@pytest.fixture
def page(browser: Any) -> Iterator[Any]:
    context = browser.new_context(accept_downloads=True)
    pg = context.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    yield pg
    context.close()
    assert errors == [], errors


def _open(page: Any, path: Path) -> None:
    page.goto(path.resolve().as_uri())
    page.wait_for_selector("body[data-ready='1']")


def _el(page: Any, key: str) -> Any:
    return page.locator(f'.el-review[data-key="{key}"]')


def _download(page: Any, click: Any, into: Path) -> dict[str, Any]:
    with page.expect_download() as info:
        click()
    dl = info.value
    target = into / dl.suggested_filename
    dl.save_as(target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert schemas.validate("review-file", data) == [], "the download is a valid review file"
    assert dl.suggested_filename == f"review-{data['scope']}-{data['created'][:10]}.json"
    return data


def test_comment_autosave_download_and_sign_off(page, course_copy, tmp_path):
    result = export("u02", root=course_copy, out=tmp_path / "u02.html")
    files = result.model.files
    _open(page, result.path)
    page.fill("#reviewer", "Maria Rossi")
    line = _el(page, "u02.l1.story#3")
    line.locator("button[data-v=change]").click()
    line.locator("select[name=category]").select_option("naturalness")
    line.locator("textarea[name=comment]").fill("Buongiorno + vorrei sounds stiff at the counter.")
    line.locator("input[name=suggestion]").fill("Buongiorno! Un cappuccino, per favore.")
    _el(page, "w:cornetto").locator("button[data-v=ok]").click()
    assert page.inner_text("#progress-count") == "2"

    page.reload()  # saved in the browser as the teacher types
    page.wait_for_selector("body[data-ready='1']")
    line = _el(page, "u02.l1.story#3")
    assert line.locator("button[data-v=change]").get_attribute("aria-pressed") == "true"
    assert line.locator("textarea[name=comment]").input_value() == "Buongiorno + vorrei sounds stiff at the counter."
    assert page.input_value("#reviewer") == "Maria Rossi" and page.inner_text("#progress-count") == "2"

    first = _download(page, lambda: page.click("#download"), tmp_path)
    assert first["reviewer"] == "Maria Rossi" and first["scope"] == "u02" and first["channel"] == "page"
    assert first["files"] == files and first["signoff"] is None
    assert set(first["elements"]) == {e.target for e in result.model.elements() if e.fp}
    by = {c["target"]: c for c in first["comments"]}
    assert set(by) == {"u02.l1.story#3", "w:cornetto"}
    story = by["u02.l1.story#3"]
    assert (story["verdict"], story["category"], story["file"]) == (
        "change",
        "naturalness",
        "content/units/02-al-bar/lesson-1.yaml",
    )
    assert story["quote"] == "Buongiorno. Vorrei un cappuccino, per favore."
    assert story["suggestion"] == "Buongiorno! Un cappuccino, per favore."
    assert (by["w:cornetto"]["verdict"], by["w:cornetto"]["comment"]) == ("ok", None)

    # Sign-off is blocked while a comment asks for a change.
    page.click("#signoff")
    assert page.is_visible("#signoff-blockers") and page.is_disabled("#signoff-confirm")
    page.click("#signoff-cancel")
    line.locator("button[data-v=ok]").click()  # the teacher settles it: OK after all
    page.click("#signoff")
    assert page.is_enabled("#signoff-confirm")
    page.fill("#signoff-name", "Maria Rossi")
    signed = _download(page, lambda: page.click("#signoff-confirm"), tmp_path)
    assert signed["signoff"]["name"] == "Maria Rossi" and signed["signoff"]["files"] == files
    story2 = next(c for c in signed["comments"] if c["target"] == "u02.l1.story#3")
    assert story2["verdict"] == "ok" and story2["id"] != story["id"]  # edited after a download: a new comment
    assert "Signed off by Maria Rossi" in page.inner_text("#signoff-status")


def test_adjudicate_rejected_answers(page, course_copy, fixtures_dir, tmp_path):
    from itcontent.beta import run_beta_import

    run_beta_import(fixtures_dir / "beta" / "events.jsonl", tmp_path / "beta")
    result = export("u02", root=course_copy, rejected=tmp_path / "beta" / "rejected.json", out=tmp_path / "p.html")
    assert result.adjudications == 3
    _open(page, result.path)
    page.fill("#reviewer", "Maria Rossi")
    accept = _el(page, "adj:u02.l1.ex04:il cornetto")
    accept.locator("button[data-v=accept]").click()
    near = _el(page, "adj:u02.task.conv1/n1:vorrei cappuccino")
    near.locator("button[data-v=near]").click()
    near.locator("input[name=hint]").fill("Don't forget the article.")
    near.locator("input[name=almost]").check()
    _el(page, "adj:u02.l1.ex04:una cornetto").locator("button[data-v=wrong]").click()
    data = _download(page, lambda: page.click("#download"), tmp_path)
    by = {c["response"]: c for c in data["comments"]}
    assert by["il cornetto"]["adjudication"] == {
        "decision": "accept",
        "hint": None,
        "outcome": None,
        "intent": None,
        "count": 1,
    }
    assert (by["il cornetto"]["target"], by["il cornetto"]["verdict"]) == ("u02.l1.ex04", "change")
    assert by["vorrei cappuccino"]["adjudication"]["hint"] == "Don't forget the article."
    assert by["vorrei cappuccino"]["adjudication"]["outcome"] == "almost"
    assert by["una cornetto"]["verdict"] == "ok" and by["una cornetto"]["adjudication"]["count"] == 3
    assert all(c["category"] == "answer-key" for c in data["comments"])
