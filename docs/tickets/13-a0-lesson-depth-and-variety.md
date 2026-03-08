# A0 lessons: more depth and activity variety

**Severity:** Medium
**Area:** `data/it/a0_lessons.yaml`, `lezione/a0.py`, `strings.py`
**Status:** DONE

## Problems (all addressed)

### 1. A0 lessons were too short

Each A0 lesson had only 2-4 real activities. Now 5-7 per lesson.

### 2. All A0 drills were fill-in-the-blank

Added `error_correction` drills to lessons 2, 4, 6, 8, 10.

### 3. No reading or writing activities at A0

Added reading activities (short dialogues) to lessons 2-10.
Added writing activities to lessons 5, 7, 8, 9, 10.

### 4. No spiral review before lesson 10

Added spiral review drills that mix earlier material into lessons 3-9.

## Changes made

**`src/maestro/data/it/a0_lessons.yaml`** — 19 new activities added:
- 9 reading activities (dialogues with comprehension questions)
- 5 writing prompts (from lesson 5 onwards)
- 5 error_correction drills
- 6 spiral review fill_blank drills (mixing earlier GP codes)

**`src/maestro/lezione/a0.py`** — added `ActivityType.WRITING` handler
**`src/maestro/strings.py`** — added `a0_writing_title` string

| Lesson | Before | After | Added |
|--------|--------|-------|-------|
| 1 Benvenuto | 7 | 7 | — |
| 2 Saluti | 3 | 5 | reading, error_correction drill |
| 3 Numeri | 4 | 6 | reading, spiral review drill |
| 4 Sì e no | 2 | 5 | reading, error_correction drill, spiral review |
| 5 Per favore | 2 | 5 | reading, writing, spiral review |
| 6 Che cos'è | 2 | 5 | reading, error_correction drill, spiral review |
| 7 Io sono | 2 | 5 | reading, writing, spiral review |
| 8 Mi piace | 2 | 5 | reading, writing, error_correction drill |
| 9 Dov'è | 2 | 5 | reading, writing, spiral review |
| 10 Ripasso | 3 | 6 | reading, error_correction drill, writing |
| **Total** | **29** | **54** | **+25** |
