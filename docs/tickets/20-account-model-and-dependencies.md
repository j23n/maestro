# Account model and auth dependencies

**Area:** `models.py`, `pyproject.toml`, `db.py`
**Roadmap:** [01-auth](../roadmap/01-auth.md)

## Goal

Add the `Account` document and install the libraries needed for session-based auth.

## Work

### Account document (`models.py`)

New Beanie Document, separate from `Student`:

```python
class Account(Document):
    email: Indexed(str, unique=True)
    password_hash: str
    email_verified: bool = False
    student_id: PydanticObjectId          # links 1:1 to Student
    stripe_customer_id: Optional[str] = None
    subscription_tier: str = "free"       # free | pro
    is_admin: bool = False
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "accounts"
```

Keep `Student` as-is — it holds learning data. `Account` holds auth/billing concerns.

### Register in Beanie

Add `Account` to the document model list in `init_db()` (`db.py`).

### Dependencies (`pyproject.toml`)

Add:
- `passlib[bcrypt]` — password hashing
- `itsdangerous` — signed session cookies

### Settings (`settings.py`)

Add:
- `SECRET_KEY: str` — used by itsdangerous for cookie signing
- `ENVIRONMENT: str = "development"` — toggles cookie secure flag, etc.

## Tests

- Unit test: Account creation, email uniqueness constraint
- Integration test: Account + Student link (create both, look up Account by email, resolve Student)

## Notes

- `stripe_customer_id`, `subscription_tier`, `is_admin` are placeholder fields — they won't be used until later phases but should exist from the start to avoid a migration.
- `email_verified` defaults to False; verification flow comes in Phase 4B (email).
