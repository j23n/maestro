# 5A. User Feedback Collection

**Phase 5 | Effort: S | Dependencies: Auth (Phase 1A)**

## Current State

- No way for users to submit feedback
- AI-generated lesson feedback exists (end of lesson) but no user-to-developer feedback channel
- `feedback.md` in repo root (empty/notes file, not a feature)

## What to Build

### Feedback model

New `Feedback` Beanie Document:

- `student_id`
- `text: str`
- `rating: Optional[int]` (1-5 or thumbs up/down)
- `page_url: str` (where feedback was submitted from)
- `created_at`

### In-app feedback form

- Feedback link in nav (or floating button) -> HTMX modal with textarea
- Captures current page URL automatically
- Simple submit, no complex flows

### Post-lesson rating

- On lesson completion page (`templates/lezione-complete.html`), add quick rating
- Thumbs up/down + optional text field
- High-signal moment — student just finished engaging with the product

### Admin view

- `GET /admin/feedback` — simple list of recent feedback entries
- Protected by `is_admin` flag on Account (added in Phase 1A)
- No full admin panel needed yet

## Key Files

- `src/maestro/models.py` (Feedback document)
- `src/maestro/routes/` (new: feedback routes, admin route)
- `templates/lezione-complete.html` (post-lesson rating)
- `templates/base.html` (feedback link/button)
- `templates/` (new: feedback modal partial, admin feedback list)

## Verification

- Can submit feedback from any page
- Post-lesson rating saves to DB
- Admin can view feedback list at `/admin/feedback`
