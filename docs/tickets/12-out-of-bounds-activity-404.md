# Out-of-bounds activity index returns raw 404

**Severity:** Medium
**Area:** `routes/lezione.py`, lesson navigation

## Problem

When a client requests `/lezione/{id}/activity/{idx}` with `idx >= len(lesson.activities)`, the server raises `HTTPException(404)` and renders a generic "Pagina non trovata" page.

**File:** `src/maestro/routes/lezione.py:223-226`

```python
if idx >= len(lesson.activities):
    if lesson.generating:
        return RedirectResponse(url=f"/lezione/{lesson_id}/generating", status_code=303)
    raise HTTPException(404)
```

### How it happens

- A stale browser tab or back-button navigation requests an index beyond the last activity
- A programmatic client iterating activities doesn't know how many exist without parsing the HTML
- The "generating" case is handled (redirects to generating page), but the "lesson is done" case is not

### Expected behavior

If the lesson is complete (not generating, all activities done), redirect to `/lezione/{id}/complete` instead of returning 404.

## Fix

```python
if idx >= len(lesson.activities):
    if lesson.generating:
        return RedirectResponse(url=f"/lezione/{lesson_id}/generating", status_code=303)
    return RedirectResponse(url=f"/lezione/{lesson_id}/complete", status_code=303)
```

This is a one-line change. The complete page already handles its own guards.
