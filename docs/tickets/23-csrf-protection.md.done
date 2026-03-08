# CSRF protection

**Area:** `main.py`, `templates/base.html`
**Roadmap:** [01-auth](../roadmap/01-auth.md)
**Depends on:** #22 (session-based auth)

## Goal

Protect all POST forms against cross-site request forgery.

## Work

### Add `starlette-csrf` middleware

- Add `starlette-csrf` to `pyproject.toml`
- Register `CSRFMiddleware` in `main.py` with `SECRET_KEY` from settings
- The middleware sets a CSRF cookie and validates a matching token on POST requests

### Inject CSRF token in forms

HTMX sends POST requests via `hx-post` attributes and `<form method="post">` submissions. `starlette-csrf` expects a token in either:
- A hidden form field (`csrftoken`)
- Or a request header (`x-csrftoken`)

For HTMX:
- Add a `<meta>` tag with the CSRF token in `base.html`
- Configure HTMX to send it as a header on every request: `hx-headers='{"x-csrftoken": "..."}'` on the `<body>` tag
- This covers both `hx-post` and regular form submissions

### Exempt webhook endpoints

When the Stripe webhook handler is added later (Phase 4A), it will need to be exempt from CSRF. For now, no exemptions needed.

## Tests

- Integration: POST without CSRF token returns 403
- Integration: POST with valid CSRF token succeeds
- Update existing integration tests to include CSRF token in POST requests

## Notes

- This will require updating every integration test that makes POST requests. Consider a test helper or fixture that automatically includes the CSRF token.
- Alternative to `starlette-csrf`: roll a simple CSRF middleware using `itsdangerous` (already a dependency from #20). Evaluate which is simpler.
