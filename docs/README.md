# Specs index

Read what your task needs. Each task in `11-milestones.md` names its specs.

| Doc | Read it when you… |
|---|---|
| [01-product.md](01-product.md) | start any task (scope, non-goals, principles, glossary) |
| [02-architecture.md](02-architecture.md) | touch module boundaries, dependencies, app structure, budgets |
| [03-content-model.md](03-content-model.md) | read or write `content/` (with its writing rules and style guide), the pack, IDs, answer patterns, the learner DB |
| [04-pipeline.md](04-pipeline.md) | work in `pipeline/`, the ten checks, TTS, the content workflow |
| [05-learning-engine.md](05-learning-engine.md) | work on events, FSRS, grading, feedback, eligibility, planner, scoring, placement |
| [06-lesson-types.md](06-lesson-types.md) | build or change any lesson type or exercise format |
| [07-ui.md](07-ui.md) | build UI (tokens, components, screens, layouts, accessibility, screenshots) |
| [08-sync.md](08-sync.md) | work on CloudKit sync or settings |
| [09-speech-audio.md](09-speech-audio.md) | work on playback, read-along or speech recognition |
| [10-quality.md](10-quality.md) | set up tests or CI, or need the definition of done |
| [11-milestones.md](11-milestones.md) | pick your next task |
| [12-study-privacy.md](12-study-privacy.md) | touch telemetry, consent, exports, privacy |
| [appstore-metadata.md](appstore-metadata.md) | prepare an App Store submission (draft listing, privacy answers, review notes; owner task M9.3) |
| [13-decisions.md](13-decisions.md) | wonder "why X and not Y?", meet a licence question, or want to propose a change |

Precedence when two sources disagree:

- `13-decisions.md` beats the other specs; the specs beat code comments.
- `schemas/content-pack.sql` is normative for the pack.
- Where a **fixture** (`fixtures/`) or a **seed file** (`content/`) is more specific than the prose, the fixture or seed file wins, and the prose is updated in the same change.
- Anything else: don't resolve the contradiction yourself. Write it under "Proposed changes" in `13-decisions.md` and ask.

Background (for humans): the plan documents this pack implements are "Italian App MVP Plan: Full A1" (scope, syllabus, rules, lesson types, QA, timeline) and "Italian iPad App: Research & MVP Plan" (research, platform facts, architecture). Agents don't need them; everything they need is here.
