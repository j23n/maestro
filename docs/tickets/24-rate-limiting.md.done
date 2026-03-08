# Rate limiting on auth endpoints

**Area:** `main.py`, `routes/auth.py`
**Roadmap:** [01-auth](../roadmap/01-auth.md)
**Depends on:** #21 (signup/login routes)

## Goal

Prevent brute-force login attempts and signup spam.

## Work

### Add `slowapi`

- Add `slowapi` to `pyproject.toml`
- Initialize limiter in `main.py` with `get_remote_address` as key function
- Register `SlowAPIMiddleware` and the rate limit exceeded handler

### Apply rate limits

- `POST /auth/login` — 5 requests/minute per IP
- `POST /auth/signup` — 3 requests/minute per IP
- `POST /auth/forgot-password` — 3 requests/hour per IP (when added in Phase 4B)

### Error response

- Return 429 with a user-friendly message ("Troppi tentativi. Riprova tra qualche minuto.")
- For HTMX requests, return an HTML fragment that displays the error inline

## Tests

- Unit test: rate limiter triggers after N requests (mock the limiter or use test client)

## Notes

- `slowapi` uses in-memory storage by default — fine for a single-process deploy. If running multiple workers, switch to Redis backend later.
- Only rate-limit auth endpoints for now. Lesson creation rate limiting (cost protection) comes in Phase 3.
