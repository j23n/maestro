# 5B. Admin Basics

**Phase 5 | Effort: S | Dependencies: Auth (Phase 1A), Monitoring (Phase 2B)**

## Current State

- No admin panel
- No admin authentication
- No analytics or dashboard
- No content management

## What to Build

### Admin access

- `is_admin: bool` flag on Account document (added in Phase 1A)
- FastAPI dependency: `get_admin_account()` that checks the flag
- Set via database directly (no self-service admin creation)

### Admin dashboard

`GET /admin/` — single page with:

- **User stats**: total accounts, signups this week, active users (lesson in last 7 days)
- **Lesson stats**: lessons/day, average duration, completion rate
- **LLM costs**: tokens/day, estimated cost/day (from Phase 2B token tracking)
- **Subscription stats**: free vs pro users, MRR (from Phase 4A)

### Feedback list

- `GET /admin/feedback` — recent feedback entries (from Phase 5A)

### Not building (yet)

- Content management (scenarios, grammar points edited via YAML + ingest scripts)
- User impersonation
- Full CRUD admin panel

## Key Files

- `src/maestro/models.py` (is_admin on Account)
- `src/maestro/routes/` (new: admin routes)
- `templates/` (new: admin dashboard, admin feedback list)

## Verification

- Admin can access `/admin/` dashboard
- Non-admin gets 403
- Stats reflect actual data
