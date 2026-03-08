# 1A. Authentication & User Management

**Phase 1 | Effort: M | Dependencies: None**

## Current State

- `Student` model has only `name` and `created_at`. No email, no password.
- Auth (`auth.py`) reads a raw `student_id` cookie — no signing, no validation.
- `/students/` page lists all students; anyone can select any student.
- Cookie set without `httponly`, `secure`, or `samesite` flags.
- No CSRF protection on POST forms.
- No rate limiting.

## What to Build

### Account model

New `Account` Beanie Document, separate from `Student` (keeps learning data clean):

- `email` (unique, indexed)
- `password_hash` (bcrypt via `passlib`)
- `email_verified: bool`
- `stripe_customer_id: Optional[str]` (for Phase 4)
- `subscription_tier: str` (free/pro, for Phase 4)
- `is_admin: bool` (for Phase 5)
- `created_at`
- Links 1:1 to `Student`

### Session-based auth

- `passlib[bcrypt]` for password hashing
- `itsdangerous` for signed session cookies (no external session store needed)
- Cookie flags: `httponly=True`, `secure=True` (prod), `samesite="lax"`

### Routes

- `GET /auth/signup` — signup form
- `POST /auth/signup` — create Account + Student, set session cookie, redirect to `/lezione/`
- `GET /auth/login` — login form
- `POST /auth/login` — verify password, set session cookie
- `POST /auth/logout` — clear session cookie
- `GET /auth/forgot-password` — request reset (requires email workstream, Phase 4B)

### Auth rewrite

- Rewrite `get_current_student()` in `auth.py`: signed session cookie -> Account -> Student
- Remove `/students/` picker page and `students_select` route entirely

### Security

- CSRF protection via `starlette-csrf` middleware (all POST forms use HTMX)
- Rate limiting on login/signup with `slowapi` (prevent brute force)

## Key Files

- `src/maestro/auth.py` — core auth logic (rewrite)
- `src/maestro/models.py` — add Account document
- `src/maestro/routes/students.py` — replace with auth routes
- `src/maestro/main.py` — register middleware
- `templates/students.html` — replace with login/signup templates

## Verification

- Can sign up with email/password, log in, start a lesson
- Cookie is signed, httponly, secure (in prod)
- CSRF tokens present on all POST forms
- Login rate-limited (e.g., 5 attempts/minute)
- Old `/students/` page gone
