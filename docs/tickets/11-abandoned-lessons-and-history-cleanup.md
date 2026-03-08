# Abandoned lessons and history cleanup

**Severity:** Low
**Area:** lesson lifecycle, `routes/lezione.py`, `templates/profilo.html`

## Problems

### 1. No way to abandon or cancel an in-progress lesson

If a student starts a lesson but doesn't finish it, the lesson stays in `status=active` forever. There's no "Cancel lesson" or "Start over" button. Starting a new lesson creates a second active lesson alongside the abandoned one.

Over time, this leads to multiple active lessons accumulating in the database.

### 2. Lessons with "---" topic appear in history

The lesson history shows entries with "---" as the topic and an empty scenario. These are likely:
- Legacy lessons from before the scenario system (Phase 6)
- Lessons where background generation failed silently
- Lessons with `topic=None` stored in DB

These clutter the history and look broken.

### 3. Lessons with `topic=None` show as "---"

At least one lesson has `topic=None` and `scenario=None` in the database, displayed as "---" with no scenario label.

## Suggested fixes

1. **Auto-abandon stale lessons:** When starting a new lesson, mark any existing `active` lessons as `abandoned`
2. **Add a cancel button:** Allow students to abandon a lesson from the lesson activity page
3. **Filter history:** Don't show lessons with no topic or with status `abandoned` in the lesson history, or show them with a distinct style ("cancelled", greyed out)

## Acceptance criteria

- [ ] Starting a new lesson auto-abandons any existing active lessons
- [ ] Lesson history hides or visually distinguishes abandoned/failed lessons
- [ ] Lessons with null/empty topics don't show as "---"
