# Design assets (Libro direction)

| Path | What | Notes |
|---|---|---|
| `tokens.json` | colours (light, plus a dark proposal), type scale, spacing, radii, sizes, mascot poses | mirrored in `App/Italiano/DesignSystem/Tokens.swift` (M3.1) |
| `screens/*.png` | reference renders of the design canvas at 2× (Moka in place of Tito) | **placeholder text** predates the final syllabus; copy layout only |
| `source/*.dc.html`, `source/canvas.json` | the design-canvas sources | exact sizes and colours are in the inline styles; they need the canvas runtime to render, so use the PNGs to look |
| `mascot/moka-{hello,think,cheer,sleep}.svg` | the mascot (ADR-13) | import into `Assets.xcassets` with "Preserve Vector Data"; poses by meaning in `tokens.json` |
| `mascot/tito-*.svg`, `mascot/tazzina.svg`, `mascot/cappuccio.svg` | alternates (Q5) | not shipped unless the owner switches |
| `mascot/*-sheet.png`, `mascot/mascot-options-explored.png` | character sheets for reference | |
| `fonts/` | Literata and Instrument Sans variable fonts with their OFL licences | if `.weight()` doesn't select weights from the variable files, generate static instances (400, 600, italic) with fontTools' `instancer` in M3.1 |

## Screen index

| File | Canvas title | Device |
|---|---|---|
| `Welcome.png` | 1 · Welcome | iPhone |
| `Reason.png` | 2 · Why Italian? | iPhone |
| `Home.png` | 3 · Today | iPhone |
| `CourseMap.png` | 4 · Course contents (Indice) | iPad |
| `Unit.png` | 5 · Unit overview | iPhone |
| `Grammar.png` | 6 · Grammar note | iPhone |
| `Dictation.png` | 7 · Dictation | iPhone |
| `Pairs.png` | 8 · Sound pairs | iPhone |
| `TryAgain.png` | 9 · Try again (feedback) | iPhone |
| `Dialogue.png` | 10 · Talk to Giulia (conversation) | iPad |
| `Complete.png` | 11 · Session complete | iPhone |
| `Words.png` | 12 · Your words | Mac |
| `Settings.png` | 13 · Settings and sync | iPhone |
| `Main.png` | A · Libro story reader | iPad |
| `LibroPhone.png` | A · Libro review (cloze) | iPhone |

Known differences from the specs, where the specs win:

- The course map shows 8 units. The course has Unit 0, Units 1–12 and a final review.
- Settings says "Tito"; it is "Moka".
- Sample sentences use grammar that the syllabus introduces later.
- Story lines in `Main.png` have no speaker labels. `docs/06` adds small-caps labels when the speaker changes.
