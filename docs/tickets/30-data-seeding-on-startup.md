# Data seeding on startup

**Area:** `main.py`, `scripts/`
**Roadmap:** [02-deploy](../roadmap/02-deploy.md)
**Depends on:** #29 (MongoDB Atlas support)

## Goal

Automatically seed curriculum data on first deploy so the app works without manual steps. Use a database dump rather than running raw ingest scripts — faster, more predictable, and avoids re-running transformation logic in production.

## Work

### Create the seed dump

- Run ingest scripts locally to produce a fully seeded database
- Export relevant collections with `mongodump`: GrammarPoints, GrammarPointExplanations, CommunicativeFunctions, CurriculumScenarios, DrillTemplates, VocabularyWords, VocabularyWordDefinitions
- Store the dump in `data/seed/` (BSON files, committed to the repo)
- Add a script `scripts/create_seed_dump.sh` to regenerate the dump from a local DB

### Startup check

- In the app lifespan, check if a key collection is empty (e.g., `GrammarPoint.count() == 0`)
- If empty, restore the seed dump using `mongorestore` (or Motor bulk inserts from the BSON files)
- Log what was seeded

### Docker integration

- Ensure `mongorestore` (or equivalent) is available in the Docker image, or implement restore via Motor/PyMongo direct inserts

## Tests

- Integration test: verify seeding runs when collections are empty
- Integration test: verify seeding is skipped when data already exists

## Notes

- Only seed on empty collections, not on every startup — keeps startup fast after first deploy.
- A0 lessons data (`a0_lessons.yaml`) is loaded at runtime by the lesson planner, not via ingest — no change needed there.
- When curriculum data changes (new scenarios, GPs, etc.), regenerate the dump with `scripts/create_seed_dump.sh` and commit the updated BSON files.
