# conformance — golden vectors for core behavior

Each `*.json` vector is self-contained: a curriculum-spec fragment, an
event log (with explicit `at` timestamps), a `now`, and the expected
derived state and/or session plan. The Rust core must reproduce every
expectation (`cargo test --test conformance`); any future second
implementation (Swift, Kotlin) must pass the same files.

Vectors pin the semantics ported from the legacy Python — mastery decay
(`learning/mastery.py`), SM-2 (`vocab/srs.py`), unlock/archetype rules
(`lessons/curriculum.py`) — plus the new can-do rollup and CEFR
classification.

**CEFR is deliberately not a port.** The legacy `_compute_cefr` required
≥90% of a level's entire reference inventory to be mastered *and* ≥90% of
its functions demonstrated. Against the Profilo's 351 Italian grammar
points that gate is unreachable — it reports "A0" more or less forever,
whatever the learner does. Since can-do descriptors are the learner-facing
progress spine, the level does not need to be a gate at all, so
`folds::classify_cefr` computes a rough descriptive classification
instead: the highest level where the learner has met enough grammar points
to judge and mastered most of the ones they met, published with a
`confidence` band derived from how much of the level they have actually
seen. `04_cefr_classification.json` pins it, along with the
`level_assessed` event that lets a future CEFR level test override the
estimate upward.
Add a vector whenever a behavioral decision is made; never edit an
existing vector's expectations without recording the change in
docs/plans/decisions.md.
