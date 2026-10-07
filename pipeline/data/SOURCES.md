# Reference data (`make data`)

Build-time only: never shipped, never committed (`.gitignore`). `make data` runs `python -m itcontent.data_fetch`, which
downloads each file below, verifies its SHA-256 and writes the licence notices next to it. CI caches this folder
keyed on this file, so **change a pin here and the cache refreshes**. Licences: `docs/13` § Licences.

The fetcher reads the table between the `pins` markers. Columns: path under `pipeline/data/`, SHA-256 of the file
as stored (raw bytes), and the sources tried in order (`tgz:` = an archive from which the `.txt` member is taken).

<!-- pins:start -->
| File | SHA-256 | Sources |
|---|---|---|
| `morph-it/morph-it.txt` | `705da3220c8b7dafa0731f057303da0c474efe248abe6d7ae331d1e470fd55fa` | `tgz:https://docs.sslmit.unibo.it/lib/exe/fetch.php?media=resources:morph-it.tgz` `https://raw.githubusercontent.com/giodegas/morphit-lemmatizer/master/master/morph-it_048.txt` `https://raw.githubusercontent.com/TraMOOC-Impleval/lemmatize_italian_data/master/morph-it_048.txt` |
| `frequency/it_50k.txt` | `bb96cdcb56d28342c1e909db6b2525448b7767136b7e86a2ccc649a1be66fc19` | `https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/it/it_50k.txt` |
<!-- pins:end -->

## Morph-it! (Zanchetta & Baroni)

- Version **0.4.8** (`morph-it_048.txt`, 2009-02-23), the last release; `docs/13` names 0.4.7, whose lemma
  coverage is the same for our purposes. 505,074 forms, 35,056 lemmas.
- Licence: dual, **CC BY-SA 2.0** or LGPL. The notice is internally inconsistent (headed LGPL, text says GPL); we
  rely on CC BY-SA 2.0 (`docs/13`). Build-time lookup only; nothing derived from it ships apart from lemma names.
- Pinned on 2026-10-07. The official page (docs.sslmit.unibo.it) was unreachable from the cloud session that pinned
  it, so the hash was taken from two independent GitHub mirrors of `morph-it_048.txt`, which agree byte for byte.
  The fetcher tries the official archive first and accepts it only if its `.txt` member has the same hash.
- **Encoding:** ISO-8859-1 (Latin-1), LF line endings. The loader decodes it and normalises to UTF-8 NFC
  (`docs/04`; a unit test asserts that `caffè` and `perché` are found).
- **Categories in this file** (counted on 2026-10-07): VER 391,285 · ADJ 72,371 · NOUN-M 20,875 · NOUN-F 14,689 ·
  NPR 2,848 · ADV 871 · MOD 381 · DET-NUM-CARD 279 · PRO-NUM 278 · AUX 257 · CAU 134 · INT 107 · ASP 82 · SMI 68 ·
  CON 56 · PRE 51 · DET-INDEF 44 · ABL 35 · DET-POSS 32 · ARTPRE-M 28 · PON 25 · DET-DEMO 19 · DET-WH 19 · WH 16 ·
  ARTPRE-F 15 · SYM 13 · ART-M 10 · ART-F 8 · PRO-INDEF-*, PRO-POSS-*, PRO-DEMO-*, PRO-WH-*, PRO-PERS-* (with
  person, gender and number in the category) · TALE · SENT · WH-CHE · NE · CE · CI · SI.
- **Surprises** (they shape `docs/04` § Annotation and the detection rules):
  - Gender is part of the category for nouns, articles and articulated prepositions (`NOUN-M:s`, `ART-F:s`,
    `ARTPRE-M:p`); pronouns carry person, gender and number in the category with `-` (`PRO-PERS-CLI-3-F-S`) and
    have no features after a colon. So a `pos` matcher is a **category prefix on `-` boundaries**: `ART` matches
    `ART-M` and `ART-F` but not `ARTPRE-M`; `NOUN` matches `NOUN-M`; `PRO-PERS` matches `PRO-PERS-CLI-3-F-S`.
  - Articles' lemma is the surface or an odd base (`uno` → `un`, `dei` → `del`); `un`, `una`, `un'` are `ART-*`,
    never `DET-INDEF` (which holds *alcun*, *nessun*…). `una` is also `PRO-INDEF-F-S`.
  - Several course nouns are missing as nouns: `spremuta` exists only as `VER:part+past+s+f` of *spremere*;
    item surface forms (`it`, `forms`) therefore resolve first and keep only analyses compatible with the item's
    POS, falling back to an analysis synthesised from the item (`docs/04` § Annotation step 4).
  - `c'` is `ADV` with lemma `c'`, and `quant'` is missing: the elision table maps them (`c'` → *ci*, `quant'` →
    *quanto*). `dov'`, `com'` are `WH`. `perché` is `WH`, not `CON`.
  - Infinitives are `VER:inf+pres` (so unlock patterns use `^inf`); `vorrei` is both `VER:cond+pres+1+s` and
    `MOD:cond+pres+1+s`; `è` and `sei` are both `VER` and `AUX`; `sei` is also `DET-NUM-CARD` and `PRO-NUM`.
  - Proper nouns are `NPR` and capitalised (`Bologna`, `Marco`, `Rosa`); `Lei` (formal you) is absent, so a
    capitalised form is looked up lowercased (`docs/04` step 3).
  - Many capitalised forms have their own NPR line (`Al`, `Marco`): a capitalised word token also takes the lowercase
    form's analyses and drops the NPR readings (allowlisted names are name tokens and never get there).
  - `uno` is `ART-M:s` (lemma `un`), `NOUN-M:s` and `PRO-INDEF-M-S`, never `DET-NUM-CARD`: the number item `w:uno`
    gets a synthesised `DET-NUM-CARD` reading. Truncated adjectives have their own lemma (`buon`, `bel` → ADJ).
  - Verb forms are often filed under several moods: `parliamo` is ind, impr and sub; `fai`, `capisci`, `vieni`, `hai`,
    `sei` are ind and impr; participles are also adjectives (`finito`, `venuto`, `andato`). Detection rules on verb
    morphology therefore use `any: true` (one analysis is enough) instead of the default every-analysis rule.
  - Inflected determiners and pronouns have their own lemmas besides the base one: `molti` (PRO-INDEF, lemma `molti`),
    `tutti`, `pochi`, `quella`, `questi`, `mia`, `sua` (PRO-POSS, lemma `mia`). Rules for these match the form.
  - `quando` is only `WH`, never `CON`, so the conjunction can't be told from the question word.
  - Two lines use spaces instead of tabs (`seppur`); the loader splits on any whitespace when a line has no tab.
  - After Latin-1 decoding the text is already NFC; line endings are LF.

## FrequencyWords (hermitdave), OpenSubtitles 2018 `it_50k`

- Licence: lists **CC BY-SA 4.0**, code MIT (`LICENSE`, fetched alongside). Build-time word ordering only
  (`content freq`, `content suggest`); ranks are not shipped.
- UTF-8, `word count` per line, most frequent first.
