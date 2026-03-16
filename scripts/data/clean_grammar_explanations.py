"""
One-shot cleanup of grammar_points.yaml: strip redundant <span lang="en"> wrappers,
fix structural span issues, and extract "## Why this matters" into a separate field.

Run:  uv run python scripts/data/clean_grammar_explanations.py
Test: uv run python scripts/data/clean_grammar_explanations.py --test
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

DATA_DIR = (
    Path(__file__).resolve().parent.parent.parent / "src" / "maestro" / "data" / "it"
)
GP_YAML = DATA_DIR / "grammar_points.yaml"
LOCK_FILE = DATA_DIR / "grammar_points.lock"


class LiteralStr(str):
    pass


def _lit_repr(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(LiteralStr, _lit_repr)


# ---------------------------------------------------------------------------
# Transform functions
# ---------------------------------------------------------------------------


def strip_en_spans(text: str) -> str:
    """Remove all <span lang="en">...</span> wrappers, keeping inner content.

    Handles nesting correctly by tracking span depth so that an en span
    containing an it span removes only the en open/close tags.
    """
    EN_OPEN = re.compile(r'<span\s+lang="en"\s*>')

    while True:
        m = EN_OPEN.search(text)
        if not m:
            break
        # Find the matching </span> by counting nesting
        depth = 1
        pos = m.end()
        span_open = re.compile(r"<span\b")
        span_close = re.compile(r"</span>")
        close_end = None
        while depth > 0 and pos < len(text):
            next_open = span_open.search(text, pos)
            next_close = span_close.search(text, pos)
            if next_close is None:
                break
            if next_open and next_open.start() < next_close.start():
                depth += 1
                pos = next_open.end()
            else:
                depth -= 1
                if depth == 0:
                    close_end = next_close.end()
                pos = next_close.end()
        if close_end is None:
            # Malformed — remove the opening tag and move on
            text = text[: m.start()] + text[m.end() :]
        else:
            inner = text[m.end() : close_end - len("</span>")]
            text = text[: m.start()] + inner + text[close_end:]
    return text


def fix_it_headings(text: str) -> str:
    """Move heading markers outside <span lang="it"> that wraps them.

    <span lang="it">### Formazione\n\n</span> → ### <span lang="it">Formazione</span>\n\n
    """

    def _rewrite(m: re.Match) -> str:
        hashes = m.group(1)  # e.g. "###"
        title = m.group(2)  # heading text
        trailing = m.group(3)  # trailing whitespace/newlines
        return f'{hashes} <span lang="it">{title}</span>{trailing}'

    return re.sub(
        r'<span\s+lang="it"\s*>(#{1,6})\s+(.*?)([\s]*)</span>',
        _rewrite,
        text,
        flags=re.DOTALL,
    )


def strip_orphaned_closing_spans(text: str) -> str:
    """Remove </span> tags that have no matching opening <span>."""
    result = []
    depth = 0
    pos = 0
    for m in re.finditer(r"(<span\b[^>]*>|</span>)", text):
        if m.group().startswith("<span"):
            result.append(text[pos : m.end()])
            pos = m.end()
            depth += 1
        else:
            if depth > 0:
                result.append(text[pos : m.end()])
                pos = m.end()
                depth -= 1
            else:
                # Orphaned </span> — skip it
                result.append(text[pos : m.start()])
                pos = m.end()
    result.append(text[pos:])
    return "".join(result)


def fix_table_rows(text: str) -> str:
    """Strip all span tags from lines whose underlying text is a table row (starts with |)."""
    lines = []
    for line in text.split("\n"):
        if re.sub(r"</?span[^>]*>", "", line).lstrip().startswith("|"):
            line = re.sub(r"</?span[^>]*>", "", line)
        lines.append(line)
    return "\n".join(lines)


def extract_why_this_matters(text: str) -> tuple[str, str]:
    """Split out the '## Why this matters' section from explanation text.

    Returns (why_this_matters, remaining_explanation) with both stripped.
    """
    pattern = r"##\s+Why this matters\s*\n"
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return "", text.strip()

    after_heading = text[m.end() :]
    before_heading = text[: m.start()]

    # Find the next ## heading (if any)
    next_heading = re.search(r"^##\s+", after_heading, re.MULTILINE)
    if next_heading:
        why_content = after_heading[: next_heading.start()].strip()
        remaining = before_heading + after_heading[next_heading.start() :]
    else:
        why_content = after_heading.strip()
        remaining = before_heading

    return why_content, remaining.strip()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_entry(text: str, why: str, code: str, lang: str) -> list[str]:
    """Return a list of verification errors (empty = all good)."""
    errors = []
    if re.search(r'<span\s+lang="en"', text):
        errors.append(f'{code}/{lang}: residual <span lang="en"> in explanation')
    if re.search(r'<span\s+lang="en"', why):
        errors.append(f'{code}/{lang}: residual <span lang="en"> in why_this_matters')

    # Check balanced spans (counts all remaining lang spans, not just "it")
    opens = len(re.findall(r'<span\s+lang="[^"]*"[^>]*>', text))
    closes = len(re.findall(r"</span>", text))
    if opens != closes:
        errors.append(
            f"{code}/{lang}: unbalanced spans — {opens} opens vs {closes} closes"
        )

    # Orphaned </span> at start
    if text.lstrip().startswith("</span>"):
        errors.append(f"{code}/{lang}: orphaned </span> at start of explanation")

    return errors


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------


def process_json(json_items: list[dict], *, verbose: bool = False) -> list[str]:
    """Process all grammar points in-place. Returns list of verification errors."""
    all_errors: list[str] = []

    for gp in json_items:
        for lang, expl in gp.get("explanations", {}).items():
            text = expl.get("explanation", "")
            if not text:
                continue

            # 1. Strip en spans
            text = strip_en_spans(text)

            # 2. Clean up orphaned </span> left from unbalanced original data
            text = strip_orphaned_closing_spans(text)

            # 3. Fix structural issues with it spans
            text = fix_it_headings(text)
            text = fix_table_rows(text)

            # 4. Extract why this matters
            why, text = extract_why_this_matters(text)

            # 5. Verify
            errors = verify_entry(text, why, gp["code"], lang)
            all_errors.extend(errors)

            # Write back
            expl["explanation"] = text
            expl["why_this_matters"] = why

            if verbose and why:
                print(
                    f"  {gp['code']}/{lang}: extracted why_this_matters ({len(why)} chars)"
                )

    return all_errors


def update_lock(json_items: list[dict]) -> None:
    """Recompute and write grammar_points.lock."""
    content = GP_YAML.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    by_level: dict[str, dict[str, int]] = {}
    for gp in json_items:
        level = gp.get("cefr_level", "?")
        counts = by_level.setdefault(level, {})
        for lng in gp.get("explanations", {}):
            counts[lng] = counts.get(lng, 0) + 1
    # Only update generated_at when the content actually changed
    old_lock = {}
    if LOCK_FILE.exists():
        old_lock = json.loads(LOCK_FILE.read_text())
    generated_at = (
        old_lock.get("generated_at", datetime.now(timezone.utc).isoformat())
        if old_lock.get("sha256") == sha
        else datetime.now(timezone.utc).isoformat()
    )
    lock = {
        "sha256": sha,
        "gp_count": len(json_items),
        "explanations_by_level": by_level,
        "generated_at": generated_at,
    }
    LOCK_FILE.write_text(json.dumps(lock, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Inline tests
# ---------------------------------------------------------------------------


def run_tests() -> bool:
    """Run inline test cases. Returns True if all pass."""
    passed = 0
    failed = 0

    def check(label: str, got: str | tuple, expected: str | tuple) -> None:
        nonlocal passed, failed
        if got == expected:
            passed += 1
            print(f"  ✓ {label}")
        else:
            failed += 1
            print(f"  ✗ {label}")
            print(f"    expected: {expected!r}")
            print(f"    got:      {got!r}")

    print("--- strip_en_spans ---")

    # 1. Simple wrapper
    check(
        "1. Simple wrapper",
        strip_en_spans('<span lang="en">text</span>'),
        "text",
    )

    # 2. Adjacent en/it spans
    check(
        "2. Adjacent en/it spans",
        strip_en_spans(
            '<span lang="en">words — </span><span lang="it">caffè</span><span lang="en">, </span>'
        ),
        'words — <span lang="it">caffè</span>, ',
    )

    # 3. Span wrapping markdown heading
    check(
        "3. Span wrapping markdown heading",
        strip_en_spans('<span lang="en">## Why this matters</span>'),
        "## Why this matters",
    )

    # 4. Heading with trailing newlines inside span
    check(
        "4. Heading with trailing newlines",
        strip_en_spans('<span lang="en">## Section\n\n</span>'),
        "## Section\n\n",
    )

    # 5. en span with nested it span
    check(
        "5. en span with nested it span",
        strip_en_spans('<span lang="en">see <span lang="it">parola</span> here</span>'),
        'see <span lang="it">parola</span> here',
    )

    # 6. Multiple en spans on one line
    check(
        "6. Multiple en spans on one line",
        strip_en_spans('<span lang="en">A</span> <span lang="en">B</span>'),
        "A B",
    )

    # 7. lang="it" spans left intact
    check(
        "7. lang='it' spans intact",
        strip_en_spans('<span lang="it">buongiorno</span>'),
        '<span lang="it">buongiorno</span>',
    )

    print("\n--- fix_it_headings ---")

    # 8. Italian heading wrapped in span
    check(
        "8. Italian heading in span",
        fix_it_headings('<span lang="it">### Formazione</span>'),
        '### <span lang="it">Formazione</span>',
    )

    # 9. Italian heading with trailing newlines
    check(
        "9. Italian heading with trailing newlines",
        fix_it_headings('<span lang="it">### Formazione\n\n</span>'),
        '### <span lang="it">Formazione</span>\n\n',
    )

    # 10. Bare heading passes through
    check(
        "10. Bare heading unchanged",
        fix_it_headings("## Already clean"),
        "## Already clean",
    )

    print("\n--- fix_table_rows ---")

    # 11. Table row after en-strip
    check(
        "11. Clean table row passes through",
        fix_table_rows("| Singular | Plural |"),
        "| Singular | Plural |",
    )

    # 12. Table row with it spans inside cells — left intact (spans stripped because it's a table row)
    check(
        "12. Table row with it spans in cells — spans stripped",
        fix_table_rows(
            '| **Singular** | <span lang="it">quanto</span> | <span lang="it">quanta</span> |'
        ),
        "| **Singular** | quanto | quanta |",
    )

    # 13. Table row where it span wraps the | delimiter
    check(
        "13. it span wrapping table delimiter",
        fix_table_rows('<span lang="it">| col1 | col2 |</span>'),
        "| col1 | col2 |",
    )

    # 14. Closing span before table pipe
    check(
        "14. Closing span before table pipe",
        fix_table_rows('</span><span lang="it">| col1 |'),
        "| col1 |",
    )

    print("\n--- extract_why_this_matters ---")

    # 15. Standard "## Why this matters" followed by next heading
    why, expl = extract_why_this_matters(
        "## Why this matters\n\nMotivating text.\n\n## Formation\n\nRules..."
    )
    check("15. Standard extraction (why)", why, "Motivating text.")
    check("15. Standard extraction (expl)", expl, "## Formation\n\nRules...")

    # 16. At end of content
    why, expl = extract_why_this_matters("## Why this matters\n\nMotivating text.")
    check("16. At end (why)", why, "Motivating text.")
    check("16. At end (expl)", expl, "")

    # 17. No heading present
    why, expl = extract_why_this_matters("## Formation\n\nRules...")
    check("17. No heading (why)", why, "")
    check("17. No heading (expl)", expl, "## Formation\n\nRules...")

    # 18. After en-strip (heading should be clean)
    text = strip_en_spans(
        '<span lang="en">## Why this matters</span>\n\nText.\n\n## Next'
    )
    why, expl = extract_why_this_matters(text)
    check("18. After en-strip (why)", why, "Text.")
    check("18. After en-strip (expl)", expl, "## Next")

    print(f"\n{passed + failed} tests: {passed} passed, {failed} failed")
    return failed == 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Clean grammar_points.yaml explanations"
    )
    parser.add_argument(
        "--test", action="store_true", help="Run inline test cases only"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Process but don't write"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show per-entry details"
    )
    args = parser.parse_args()

    if args.test:
        ok = run_tests()
        sys.exit(0 if ok else 1)

    with open(GP_YAML) as f:
        json_items = yaml.safe_load(f)

    print(f"Loaded {len(json_items)} grammar points from {GP_YAML}")

    errors = process_json(json_items, verbose=args.verbose)

    if errors:
        print(f"\n{len(errors)} verification errors:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)

    # Stats
    with_why = sum(
        1
        for gp in json_items
        for expl in gp.get("explanations", {}).values()
        if expl.get("why_this_matters")
    )
    remaining_en = sum(
        1
        for gp in json_items
        for expl in gp.get("explanations", {}).values()
        if re.search(r'<span\s+lang="en"', expl.get("explanation", ""))
    )
    print(f"Extracted why_this_matters: {with_why} entries")
    print(f"Remaining <span lang='en'>: {remaining_en}")

    if args.dry_run:
        print("Dry run — no files written")
        sys.exit(0)

    # Wrap multiline strings for block-scalar output
    for gp in json_items:
        for key in ("description",):
            if isinstance(gp.get(key), str) and "\n" in gp[key]:
                gp[key] = LiteralStr(gp[key])
        for lang, expl in gp.get("explanations", {}).items():
            for field in ("explanation", "tip", "why_this_matters"):
                if isinstance(expl.get(field), str) and "\n" in expl[field]:
                    expl[field] = LiteralStr(expl[field])
    with open(GP_YAML, "w") as f:
        yaml.dump(
            json_items, f, default_flow_style=False, allow_unicode=True, width=200
        )
    print(f"Wrote {GP_YAML}")

    update_lock(json_items)
    print(f"Updated {LOCK_FILE}")
