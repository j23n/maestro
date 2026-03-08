# Signup and login routes

**Area:** `routes/auth.py` (new), `templates/signup.html`, `templates/login.html`
**Roadmap:** [01-auth](../roadmap/01-auth.md)
**Depends on:** #20 (Account model)

## Goal

Users can create an account and log in with email/password. Sessions use signed cookies.

## Work

### New route file: `routes/auth.py`

**Signup:**
- `GET /auth/signup` — render signup form (email, password, password confirmation)
- `POST /auth/signup` — validate input, check email uniqueness, hash password with `passlib[bcrypt]`, create Account + Student, set signed session cookie, redirect to `/lezione/`
- If email already taken, re-render form with error message

**Login:**
- `GET /auth/login` — render login form (email, password)
- `POST /auth/login` — verify password against hash, set signed session cookie, redirect to `/lezione/`
- If credentials wrong, re-render form with generic error ("email o password non validi")

**Logout:**
- `POST /auth/logout` — clear session cookie, redirect to `/`

### Session cookie

- Use `itsdangerous.URLSafeTimedSerializer` with `SECRET_KEY` from settings
- Cookie payload: `{"account_id": str(account.id)}`
- Cookie name: `session`
- Cookie flags: `httponly=True`, `samesite="lax"`, `secure=True` if `ENVIRONMENT == "production"`
- Max age: 30 days

### Templates

- `templates/signup.html` — form with email, password, confirm password fields. Link to login.
- `templates/login.html` — form with email, password fields. Link to signup.
- Style consistently with existing form UI (`.form-section`, `.config-text-input` patterns from `lezione-index.html`).

### Register router

Add the auth router to `main.py`.

### i18n

Add strings to `i18n/it.json` and `i18n/en.json`:
- Form labels (email, password, confirm password)
- Error messages (email taken, invalid credentials, passwords don't match)
- Button text (signup, login, logout)

## Tests

- Integration: signup creates Account + Student, sets cookie
- Integration: login with correct password succeeds
- Integration: login with wrong password returns error
- Integration: signup with duplicate email returns error
- Integration: logout clears cookie

## Notes

- Password reset (`/auth/forgot-password`) deferred to Phase 4B (requires email service).
- No email verification check at login yet — just store `email_verified=False` and move on.
