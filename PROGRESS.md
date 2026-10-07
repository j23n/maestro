# Progress log

Append one entry per finished task (newest at the bottom). Agents read the tail of this file at session start.

Template:

```
## YYYY-MM-DD · <task ID> · <short title>
- Changed: <what, in a few bullets>
- Evidence: <test names / counts, screenshot paths, commands run>
- Decisions or findings: <e.g. pinned versions, permission behaviour, surprises in Morph-it! tags>
- Follow-ups: <new questions, proposals added to docs/13>
```

## 2026-10-07 · handoff · Repository seeded from the handoff pack
- Changed: specs (docs/), agent harness (.claude/, .mcp.json, scripts/), content seeds (syllabus, grammar points and detection rules, all unit specs, story bible, items for Units 0–2, golden Unit 2 Lesson 1 with its task and check), fixtures (FSRS-6 reference from py-fsrs 6.3.2; grading), design assets.
- Evidence: no app code yet. Seed YAML parses; every ID reference in the lesson, task and check files resolves (references into units not yet written are pending); the golden story's 106 tokens all resolve to items, chunks or the allowlist; every new P item of the golden lesson has ≥ 4 retrievals; the pack schema loads in SQLite; the hooks were exercised in a scratch repo; `scripts/check-contrast.py` passes.
- Decisions or findings: see docs/13 (bundle ID com.j23n.italian in ADR-18; the owner has an Italian teacher as content lead, Q1; ADR-19 to ADR-22, incl. the content review loop, and the content questions came out of two independent AI-agent reviews of the pack, engineering and Italian L2 content, plus a consistency check). Versions checked 7 Oct 2026: Xcode 27.0 (Swift 6.4), GRDB 7.11.1, swift-snapshot-testing 1.19.6, MobileBuildMCP 2.7.1, py-fsrs 6.3.2.
- Follow-ups: start with M0.1; the owner creates the Xcode project at M0.2.
