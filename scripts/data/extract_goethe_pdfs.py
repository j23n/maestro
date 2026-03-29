"""
Extract grammar inventory and communicative function (Sprachhandlungen) sections
from Goethe-Institut Prüfungsziele/Testbeschreibung PDFs for A1 and A2.

Requires: pdftotext (from poppler-utils) installed on the system.

Source PDFs (downloaded from goethe.de, stored in src/maestro/data/de/pdfs/):
  - Pruefungsziele_Testbeschreibung_A1_SD1.pdf  (Start Deutsch 1)
  - Pruefungsziele_Testbeschreibung_A2_SD2.pdf  (Start Deutsch 2)

Output: cleaned text files in src/maestro/data/de/extracted/
  - A1_grammatik.txt, A2_grammatik.txt
  - A1_sprachhandlungen.txt, A2_sprachhandlungen.txt
  - A1_strategien.txt, A2_strategien.txt
  - A1_notionen.txt, A2_notionen.txt

The A2 SD2 document covers both A1 and A2 grammar. Entries without a star (*)
are A1; entries marked with * are A2 additions. This script extracts both
levels separately.

Usage: uv run python scripts/data/extract_goethe_pdfs.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "de"
PDF_DIR = DATA_DIR / "pdfs"
OUT_DIR = DATA_DIR / "extracted"

# Section markers found via grep on the full-text output of each PDF.
# Format: (pdf_filename, section_name, start_pattern, end_pattern)
# The start_pattern is inclusive; end_pattern is exclusive.
SECTIONS = [
    # A1 SD1
    {
        "pdf": "Pruefungsziele_Testbeschreibung_A1_SD1.pdf",
        "sections": {
            "sprachhandlungen": {
                "start": r"^Sprachhandlungen$",
                "end": r"^Strategien$",
                "output": "A1_sprachhandlungen.txt",
                # Skip the first two occurrences (TOC + intro), use the 3rd
                "skip_matches": 2,
            },
            "strategien": {
                "start": r"^Strategien$",
                "end": r"^Allgemeine Begriffe",
                "output": "A1_strategien.txt",
                # Skip TOC + chapter 5 intro list occurrences
                "skip_matches": 2,
            },
            "notionen": {
                "start": r"^Allgemeine Begriffe",
                "end": r"^Themen$",
                "output": "A1_notionen.txt",
                # Skip TOC occurrence
                "skip_matches": 1,
            },
            "grammatik": {
                "start": r"^Grammatik$",
                "end": r"^Literatur$",
                "output": "A1_grammatik.txt",
                # Skip TOC occurrence, use the inventory section
                "skip_matches": 1,
            },
        },
    },
    # A2 SD2 (contains both A1 and A2 items; * marks A2 additions)
    {
        "pdf": "Pruefungsziele_Testbeschreibung_A2_SD2.pdf",
        "sections": {
            "sprachhandlungen": {
                "start": r"^Sprachhandlungen$",
                "end": r"^Strategien$",
                "output": "A2_sprachhandlungen.txt",
                # Skip the first two occurrences (TOC + intro), use the 3rd
                "skip_matches": 2,
            },
            "strategien": {
                "start": r"^Strategien$",
                "end": r"^Allgemeine Begriffe",
                "output": "A2_strategien.txt",
                # Skip TOC + chapter 6 intro list occurrences
                "skip_matches": 2,
            },
            "notionen": {
                "start": r"^Allgemeine Begriffe",
                "end": r"^Themen$",
                "output": "A2_notionen.txt",
                # Skip TOC occurrence
                "skip_matches": 1,
            },
            "grammatik": {
                "start": r"^GRAMMATIK$",
                # 7 LITERATUR appears mid-content due to two-column interleaving;
                # use the first Literatur reference line as reliable end marker
                "end": r"^Gemeinsamer europäischer Referenzrahmen",
                "output": "A2_grammatik.txt",
            },
        },
    },
]

# Lines to strip from extracted text (page footers, headers, version stamps)
NOISE_PATTERNS = [
    re.compile(r"^VS_\d{2}_\d{6}$"),  # version stamp e.g. VS_08_190422
    re.compile(r"^Seite \d+$"),  # page numbers
    re.compile(r"^Inventare$"),  # repeated section header
    re.compile(r"^6 INVENTARE$"),  # A2 repeated section header
    re.compile(r"^\d{2,3}$"),  # bare page numbers (A2 style)
    re.compile(r"^7 LITERATUR$"),  # A2 Literatur header (interleaved by pdftotext)
    re.compile(r"^ALTE Handbuch"),  # Literatur reference (interleaved by pdftotext)
    re.compile(
        r"^Breakthrough Level"
    ),  # Literatur reference (interleaved by pdftotext)
    re.compile(r"^Hg\. Association"),  # Literatur reference (interleaved by pdftotext)
    re.compile(r"^von John Trim"),  # Literatur reference (interleaved by pdftotext)
]


def extract_full_text(pdf_path: Path) -> list[str]:
    """Run pdftotext and return lines."""
    result = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"ERROR: pdftotext failed for {pdf_path}: {result.stderr}", file=sys.stderr
        )
        sys.exit(1)
    return result.stdout.splitlines()


def find_section(
    lines: list[str],
    start_pattern: str,
    end_pattern: str,
    skip_matches: int = 0,
) -> list[str]:
    """Extract lines between start_pattern and end_pattern.

    skip_matches: how many times to skip the start_pattern before capturing.
    """
    start_re = re.compile(start_pattern)
    end_re = re.compile(end_pattern)

    capturing = False
    matches_seen = 0
    result = []

    for line in lines:
        if not capturing:
            if start_re.match(line.strip()):
                matches_seen += 1
                if matches_seen > skip_matches:
                    capturing = True
                    result.append(line)
        else:
            if end_re.match(line.strip()):
                break
            result.append(line)

    return result


def clean_lines(lines: list[str]) -> list[str]:
    """Remove noise lines and collapse excessive blank lines."""
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if any(p.match(stripped) for p in NOISE_PATTERNS):
            continue
        cleaned.append(line)

    # Collapse runs of 3+ blank lines to 2
    result = []
    blank_count = 0
    for line in cleaned:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)

    # Strip trailing blanks
    while result and result[-1].strip() == "":
        result.pop()

    return result


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for pdf_config in SECTIONS:
        pdf_name = pdf_config["pdf"]
        pdf_path = PDF_DIR / pdf_name
        if not pdf_path.exists():
            print(f"SKIP: {pdf_path} not found (download from goethe.de first)")
            continue

        print(f"Processing {pdf_name}...")
        lines = extract_full_text(pdf_path)
        print(f"  Total lines: {len(lines)}")

        for section_name, section_config in pdf_config["sections"].items():
            out_file = section_config.get("output", f"{pdf_name}_{section_name}.txt")
            out_path = OUT_DIR / out_file

            section_lines = find_section(
                lines,
                section_config["start"],
                section_config["end"],
                skip_matches=section_config.get("skip_matches", 0),
            )

            if not section_lines:
                print(f"  WARNING: could not find {section_name} section")
                continue

            cleaned = clean_lines(section_lines)
            out_path.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
            print(f"  {section_name}: {len(cleaned)} lines → {out_path.name}")

    print("\nDone. Extracted text files are in data/de/extracted/")


if __name__ == "__main__":
    main()
