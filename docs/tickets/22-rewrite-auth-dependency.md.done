# Rewrite get_current_student auth dependency

**Area:** `auth.py`, `routes/students.py`
**Roadmap:** [01-auth](../roadmap/01-auth.md)
**Depends on:** #20 (Account model), #21 (signup/login routes)

## Goal

Replace the raw `student_id` cookie reader with signed session-based auth. Remove the student picker page.

## Work

### Rewrite `get_current_student()` in `auth.py`

Current flow:
```
cookie "student_id" (raw ObjectId) → Student.get(id)
```

New flow:
```
cookie "session" (signed) → deserialize with itsdangerous → account_id → Account.get(id) → Student.get(account.student_id)
```

- If cookie missing or signature invalid → redirect to `/auth/login`
- If Account or Student not found → clear cookie, redirect to `/auth/login`
- Keep `RedirectToStudents` exception but rename to `RedirectToLogin` (or keep name, change handler target)

### Update exception handler in `main.py`

Change the `RedirectToStudents` handler to redirect to `/auth/login` instead of `/students/`.

### Remove student picker

Delete or gut these:
- `routes/students.py`: remove `GET /students/`, `POST /students/`, `POST /students/{id}/select`
- Keep `DELETE /students/{id}` if needed for account deletion, or move to an account management route later
- `templates/students.html`: delete

### Update landing page

`GET /` in `main.py`: change cookie check from `student_id` to `session`.

### Migration path for existing local data

Existing local dev setups have Students without Accounts. Options:
- Add a one-time migration script (`scripts/migrate_auth.py`) that creates Account records for existing Students with a placeholder email
- Or just document that existing local data needs a fresh start (acceptable for pre-launch)

## Tests

- Integration: unauthenticated request redirects to `/auth/login`
- Integration: valid session cookie resolves to correct Student
- Integration: tampered cookie rejected
- Integration: expired cookie rejected
- Update all existing integration tests that use the `student` fixture to go through the new auth flow (or provide a test helper that sets a valid session cookie)

## Notes

- This is the highest-risk ticket — it touches the auth dependency used by every protected route. Run the full integration suite after.
- The `test_app` fixture in `tests/integration/conftest.py` will need updating to set a signed session cookie instead of a raw `student_id` cookie.
