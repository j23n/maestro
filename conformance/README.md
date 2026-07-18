# conformance — golden vectors for core behavior

Each `*.json` vector is self-contained: a curriculum-spec fragment, an
event log (with explicit `at` timestamps), a `now`, and the expected
derived state and/or session plan. The Rust core must reproduce every
expectation (`cargo test --test conformance`); any future second
implementation (Swift, Kotlin) must pass the same files.

Vectors pin the semantics ported from the legacy Python — mastery decay
(`learning/mastery.py`), SM-2 (`vocab/srs.py`), unlock/archetype rules
(`lessons/curriculum.py`) — plus the new can-do rollup and CEFR estimate.
Add a vector whenever a behavioral decision is made; never edit an
existing vector's expectations without recording the change in
docs/plans/decisions.md.
