"""The shared course loader walks the frozen seed course (golden lesson, task, check; conftest) correctly."""

from __future__ import annotations

from itcontent.course import ExerciseRef, TextRef, load_course, walk_course


def test_loads_units_in_course_order(seed_root):
    c = load_course(seed_root)
    assert [u.id for u in c.units][:3] == ["u00", "u01", "u02"]
    assert c.units[-1].id == "u99"
    assert not c.load_errors
    u02 = c.unit("u02")
    assert u02 is not None
    assert [d.path.name for d in u02.lessons] == ["lesson-1.yaml"]
    assert u02.task is not None and u02.check is not None
    assert not u02.complete  # lessons 2 and 3 don't exist yet (docs/04 § Partial content)


def test_walks_every_golden_exercise_and_text(seed_root):
    c = load_course(seed_root)
    found = list(walk_course(c))
    ex = {x.id: x for x in found if isinstance(x, ExerciseRef)}
    tx = {x.id: x for x in found if isinstance(x, TextRef)}
    # lesson 1: 3 questions, 13 block + 7 mix, 3 sounds, 1 use; task: conv1, talk, relay; check: 9 sample items
    lesson = [e for e in ex.values() if e.container == "lesson"]
    assert len(lesson) == 3 + 13 + 7 + 3 + 1
    assert ex["u02.l1.q1"].role == "comprehension"
    assert ex["u02.l1.ex15"].part == "mix"
    assert ex["u02.l1.ex25"].step_kind == "use"
    assert {"u02.task.conv1", "u02.task.talk", "u02.task.relay"} <= set(ex)
    assert ex["u02.check.07"].section == "speaking" and ex["u02.check.07"].role == "check"
    assert {"u02.l1.story", "u02.task.menu", "u02.check.01.audio"} <= set(tx)
    assert str(ex["u02.l1.ex01"].loc) == "content/units/02-al-bar/lesson-1.yaml › steps[3].block[0]"
