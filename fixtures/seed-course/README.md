# The frozen seed course

`content/` here is the course as it was before the first drafts were merged (commit `eae7998`): course-wide files, the
items of Units 0–2, the unit specs, the golden Unit 2 Lesson 1 with its task and check, and their annotation lock files
(`content/.annotations/`). It is a test fixture, not course content: nothing here ships, and the content lead doesn't
review it.

It is the input for

- **pipeline tests that pin facts about a course** (counts, step tables, retrievals, line numbers, report rows,
  lint and check findings): `seed_root` and `course_copy` in `pipeline/tests/conftest.py`. Tests about the live course
  (it lints and checks without errors, its lock files are fresh, its review pages resolve, its dev pack builds
  deterministically) read `content/` instead;
- **the mini pack**: `make mini-pack` (`content build --mini`) builds `fixtures/packs/mini.sqlite`,
  `mini-payloads.json` and, from them, `assessment.sqlite` from this course, so the Storage, App and LearningCore
  tests don't change when a lesson is drafted.

## When to refresh it

Never automatically, and never just because `content/` changed: growing the course must not touch it.

- **The annotator changed** and `test_seed_course_lock_files_are_fresh` fails: regenerate the lock files only, from
  the repository root, and review the diff:

  ```
  tmp=$(mktemp -d) && cp -R fixtures/seed-course/content "$tmp/" && mkdir -p "$tmp/pipeline/data" \
    && ln -s "$PWD/pipeline/data/morph-it" "$tmp/pipeline/data/morph-it" \
    && ITALIANO_ROOT="$tmp" uv run --project pipeline content annotate \
    && rm -rf fixtures/seed-course/content/.annotations && cp -R "$tmp/content/.annotations" fixtures/seed-course/content/
  ```

- **A content format or schema changed** (specs, code and fixtures change together): migrate these files the way
  `content/` is migrated, in the same change, then refresh the lock files as above and run `make mini-pack`.
- **Re-freezing at a later state of the course** is a deliberate change of its own: every test expectation that pins
  a fact, the mini pack and the Swift tests that count its contents change with it.
