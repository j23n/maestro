# 4B. Transactional Email

**Phase 4 | Effort: S | Dependencies: Auth (Phase 1A, need email addresses)**

## Current State

- No email library or service
- No email addresses on users (added in Phase 1A)
- No transactional email capability

## What to Build

### Email service: Resend

- Simple REST API, Python SDK
- Free tier: 100 emails/day (plenty for launch)
- Add `resend` to dependencies, `RESEND_API_KEY` to settings

### Email types

**Launch:**
- Email verification (after signup)
- Password reset link
- Welcome email

**Later:**
- Weekly progress digest
- Subscription receipts (Stripe handles these automatically)

### Templates

- Simple HTML email templates (plain, not the Jinja2 HTMX templates)
- Keep minimal — most email clients strip complex CSS
- Separate directory: `templates/email/`

### Verification approach

- Soft verification initially: reminder banner in app, not blocking
- Reduces signup friction
- Can tighten later (require verification for certain features)

## Key Files

- `src/maestro/email.py` (new: send helper)
- `src/maestro/settings.py` (RESEND_API_KEY)
- `src/maestro/routes/auth.py` (trigger emails on signup, password reset)
- `templates/email/` (new: email templates)

## Verification

- Signup sends verification email
- Password reset email contains valid link
- Emails render correctly in Gmail, Apple Mail
