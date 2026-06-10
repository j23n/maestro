# Maestro

Self-hostable language tutor (Italian + German). FastAPI + MongoDB (Beanie ODM) + Claude API + htmx/Jinja2.

## Quick Start

```bash
uv sync --group dev          # install deps (Python 3.13+)
cp .env.example .env         # fill in ANTHROPIC_API_KEY, SECRET_KEY, MONGO_URL
uv run fastapi dev src/maestro/main.py
```

## Commands

```bash
uv run pytest -m unit tests/unit/             # fast, no DB
uv run pytest -m integration tests/integration/  # uses mongomock, no real DB
uv run pytest tests/                          # everything (some tests have no marker)
uv run ruff check src/ tests/                 # lint
uv run ruff format src/ tests/                # format
```

Eval tests (`-m llm_eval`) hit the real Anthropic API — skip in normal dev.

## Architecture

```
src/maestro/
├── main.py              # FastAPI app, lifespan, middleware, error handlers
├── config.py            # Pydantic Settings (.env)
├── models.py            # All Beanie document models
├── db.py                # MongoDB init
├── routes/
│   ├── lessons.py       # Lesson lifecycle (index, create, generating, retry, complete)
│   ├── activities.py    # Activity rendering + submission (drill, writing, speaking, etc.)
│   ├── auth.py          # Login, signup, password reset
│   ├── admin.py         # Admin dashboard
│   ├── vocab.py         # Vocabulary management
│   ├── account.py       # Settings, GDPR export/delete
│   ├── feedback.py      # LLM critique/flagging
│   ├── grammar.py       # Grammar reference + practice
│   ├── functions.py     # Communicative functions
│   └── profile.py       # Student profile, skill tree
├── lessons/
│   ├── planner.py       # Two-phase lesson generation (immediate + background)
│   ├── bank.py          # Static content bank loader (data/<lang>/banks/<level>/)
│   ├── bank_assembly.py # Assemble lesson content from bank (no LLM)
│   ├── adapt.py         # Small LLM pass: personalised framing for bank lessons
│   ├── lifecycle.py     # State machine (advance, complete, scoring)
│   ├── a0_static.py     # A0 lessons from YAML (no LLM)
│   └── drill_scoring.py # Drill answer evaluation
├── learning/
│   ├── profile.py       # Learning profile management
│   ├── scorer.py        # Writing/speaking LLM feedback
│   └── weakness.py      # Grammar weakness detection
├── vocab/
│   ├── discover.py      # Inline vocab popovers + cards from verified annotations only
│   ├── annotate.py      # Generation-time LLM lemma annotation (word-index validated)
│   ├── srs.py           # SM-2 spaced repetition
│   └── cache.py         # Vocab word cache
├── llm.py               # Anthropic client wrapper + cost tracking
├── auth.py              # Session auth, profile cache
├── tts.py / stt.py      # Azure TTS/STT
├── rag.py               # Vector search for grammar chunks (optional)
├── templates.py         # Jinja2 rendering with vocab discover pipeline
└── i18n/                # Translations (UI language)
```

## Key Patterns

- **Beanie ODM**: all models in `models.py`, atomic `$set` updates (no `.save()` for partial changes)
- **Lesson paths**: A0 = static YAML; A1+ = content-bank assembly + small adaptation LLM call when bank covers the lesson (`Lesson.content_source="bank"`), full LLM generation as fallback (`"llm"`)
- **Content banks**: `data/<lang>/banks/<level>/` (drill pools per GP, texts per scenario/depth); generate with `scripts/generate_content_bank.py`, validate with `scripts/bank_lint.py`
- **Vocab annotation**: lesson content gets verified surface→lemma mappings (bank files or `vocab/annotate.py` post-pass); only validated mappings create vocabulary cards
- **Activity flow**: `lessons.py` manages lifecycle, `activities.py` handles per-type rendering/submission
- **Auth**: signed session cookies (`itsdangerous`), double-submit CSRF, bcrypt passwords
- **LLM calls**: always through `llm.llm_messages_create()` for automatic cost tracking
- **Tests**: mongomock-motor for DB, mocked LLM clients, `test_app` fixture has auth pre-set

## Worktree Discipline

When working inside a git worktree, stay in that worktree for every tool call,
agent spawn, and file read/write. Never `cd` to the main repo or another worktree.
