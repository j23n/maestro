"""
Scrape grammar points from the Profilo della Lingua Italiana website.

Usage: python -m maestro.data.scrape_grammar_points [--debug]
Flags: --debug  Process 3 pages only; print JSON to stdout instead of writing file.

HTML structure (two variants observed):
  A) <div class="div"> with inline <b>N</b> numbering (verbi, avverbi, …)
  B) <ol>/<ul> with <li><strong>N</strong>. text</li>  (pronomi, nome, …)
"Vedi livelli" pages (e.g. articoli B2) contain only "Vedi A1, A2 e B1"
and no numbered items — they are silently skipped.
"""

import asyncio
import json
import re
import sys
import unicodedata
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.unistrapg.it/profilo_lingua_italiana/site/"
OUT_PATH = Path(__file__).parent / "grammar_points.json"

CATEGORIES = {
    "nome":              "gram_nome",
    "pronomi":           "gram_pronomi",
    "aggettivi":         "gram_aggettivi",
    "articoli":          "gram_articoli",
    "verbi":             "gram_verbi",
    "preposizioni":      "gram_preposizioni",
    "avverbi":           "gram_avverbi",
    "frase_semplice":    "gram_frasesemplice",
    "frase_complessa":   "gram_frasecomplessa",
    "costruzione_frase": "gram_costruz",
}
LEVELS = ["a1", "a2", "b1", "b2"]
LEVEL_MAP = {"a1": "A1", "a2": "A2", "b1": "B1", "b2": "B2"}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def get_text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split())


def clean_label(text: str) -> str:
    """Remove footnote superscript characters and trailing footnote text."""
    # Remove unicode superscript digits (¹ ² ³ etc., U+00B2/B3/B9)
    text = re.sub(r"[\u00B2\u00B3\u00B9\u2070-\u2079]+", "", text)
    # Remove "Nota: formula non analizzata" footnote text (common on this site)
    text = re.sub(r"\s*Nota:\s+formula\s+non\s+analizzata\s*", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s]+", "_", text.strip())
    if len(slug) > 80:
        slug = slug[:80].rsplit("_", 1)[0]
    return slug


def make_code(label: str, category: str, level: str, used_codes: set) -> str:
    base = slugify(label)
    if base not in used_codes:
        return base
    prefixed = f"{category}_{base}"
    if len(prefixed) > 80:
        prefixed = prefixed[:80].rsplit("_", 1)[0]
    if prefixed not in used_codes:
        return prefixed
    full = f"{category}_{level}_{base}"
    if len(full) > 80:
        full = full[:80].rsplit("_", 1)[0]
    return full


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

async def fetch_with_retry(
    client: httpx.AsyncClient, url: str, max_attempts: int = 3
) -> str:
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            r = await client.get(url, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_exc = e
            if attempt < max_attempts - 1:
                wait = 2 ** attempt
                print(
                    f"  Retry {attempt + 1}/{max_attempts} for {url}"
                    f" (sleeping {wait}s): {e}",
                    file=sys.stderr,
                )
                await asyncio.sleep(wait)
    raise RuntimeError(
        f"Failed to fetch {url} after {max_attempts} attempts: {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _has_numbered_items(container) -> bool:
    """Return True if container has <b>N</b> or <strong>N</strong> items."""
    for tag in container.find_all(["b", "strong"]):
        if re.match(r"^\d+$", tag.get_text(strip=True)):
            return True
    return False


def is_vedi_livelli_page(soup: BeautifulSoup) -> bool:
    """Detect pages that only cross-reference other levels (no new content)."""
    outer = soup.find("div", id="content") or soup
    text = outer.get_text(" ", strip=True).lower()
    is_vedi = "vedi livell" in text or bool(re.search(r"vedi\s+[ab]\d", text))
    if not is_vedi:
        return False
    # If numbered items exist the page has real content despite the cross-ref
    return not _has_numbered_items(outer)


def parse_grammar_page(
    html: str, category: str, level: str, source_url: str
) -> list[dict]:
    """Return one dict per grammar point found on the page."""
    soup = BeautifulSoup(html, "html.parser")
    cefr = LEVEL_MAP[level]

    # Strip footnote superscripts so they don't pollute text
    for sup in soup.find_all("sup"):
        sup.decompose()

    if is_vedi_livelli_page(soup):
        print(f"    SKIP (vedi livelli): {source_url}", file=sys.stderr)
        return []

    outer = soup.find("div", id="content") or soup
    entries: list[dict] = []
    used_codes: set[str] = set()

    # ------------------------------------------------------------------
    # Strategy 1: <li> items with <strong>N</strong> or <b>N</b> prefix
    # (seen on pronomi, nome pages)
    # ------------------------------------------------------------------
    numbered_lis = [
        li for li in outer.find_all("li")
        if (first := li.find(["strong", "b"]))
        and re.match(r"^\d+$", first.get_text(strip=True))
    ]
    if numbered_lis:
        for li in numbered_lis:
            first_tag = li.find(["strong", "b"])
            if first_tag:
                first_tag.decompose()
            label = clean_label(re.sub(r"^[\s.\:]+", "", get_text(li)).strip())
            if not label or len(label) < 3:
                continue
            code = make_code(label, category, level, used_codes)
            used_codes.add(code)
            entries.append({
                "code": code,
                "label": label,
                "cefr_level": cefr,
                "category": category,
                "description": label,
                "source_url": source_url,
            })
        return entries

    # ------------------------------------------------------------------
    # Strategy 2: <div class="div"> with inline <b>N</b> numbering
    # (seen on verbi, avverbi, aggettivi pages)
    # ------------------------------------------------------------------
    content_block = outer.find("div", class_="div")
    if content_block:
        html_str = str(content_block)
        # Replace <b>N</b> tags with a sentinel marker
        marked = re.sub(r"<b>\s*\d+\s*</b>", "|||ITEM|||", html_str)
        text = BeautifulSoup(marked, "html.parser").get_text(" ", strip=True)
        parts = [p.strip() for p in text.split("|||ITEM|||")]
        item_parts = parts[1:]  # Skip title/header before the first numbered item
        if item_parts:
            for part in item_parts:
                part = clean_label(re.sub(r"^[\s.\:]+", "", part).strip())
                if not part or len(part) < 3:
                    continue
                code = make_code(part, category, level, used_codes)
                used_codes.add(code)
                entries.append({
                    "code": code,
                    "label": part,
                    "cefr_level": cefr,
                    "category": category,
                    "description": part,
                    "source_url": source_url,
                })
            if entries:
                return entries

    # ------------------------------------------------------------------
    # Strategy 3: fallback — single entry from page title + content text
    # ------------------------------------------------------------------
    title_el = (
        outer.find("div", class_="titolocentrale")
        or outer.find(["h1", "h2", "h3", "h4"])
    )
    label = get_text(title_el) if title_el else f"{category} {cefr}"
    desc_block = outer.find("div", class_="div") or outer
    desc = get_text(desc_block) if desc_block else label
    code = make_code(f"{category}_{level}", category, level, used_codes)
    entries.append({
        "code": code,
        "label": label,
        "cefr_level": cefr,
        "category": category,
        "description": desc,
        "source_url": source_url,
    })
    return entries


def resolve_global_codes(entries: list[dict]) -> list[dict]:
    """Ensure all codes are globally unique across all categories and levels."""
    seen: set[str] = set()
    result = []
    for entry in entries:
        code = entry["code"]
        if code in seen:
            new_code = f"{entry['category']}_{code}"
            if len(new_code) > 80:
                new_code = new_code[:80].rsplit("_", 1)[0]
            if new_code in seen:
                new_code = f"{entry['category']}_{entry['cefr_level'].lower()}_{code}"
                if len(new_code) > 80:
                    new_code = new_code[:80].rsplit("_", 1)[0]
            code = new_code
        seen.add(code)
        result.append({**entry, "code": code})
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    debug = "--debug" in sys.argv

    pages = [
        (category, prefix, level)
        for category, prefix in CATEGORIES.items()
        for level in LEVELS
    ]
    if debug:
        pages = pages[:3]

    sem = asyncio.Semaphore(4)

    async with httpx.AsyncClient(follow_redirects=True) as client:

        async def process(category: str, prefix: str, level: str) -> list[dict]:
            url = f"{BASE_URL}{prefix}_{level}.html"
            async with sem:
                try:
                    html = await fetch_with_retry(client, url)
                except RuntimeError as e:
                    print(f"  ERROR: {e}", file=sys.stderr)
                    return []
                try:
                    result = parse_grammar_page(html, category, level, url)
                    print(
                        f"  {category}/{level}: {len(result)} grammar points",
                        file=sys.stderr,
                    )
                    return result
                except Exception as e:
                    import traceback
                    print(f"  PARSE ERROR {url}: {e}", file=sys.stderr)
                    traceback.print_exc(file=sys.stderr)
                    return []

        print(f"Fetching {len(pages)} pages...", file=sys.stderr)
        results = await asyncio.gather(*[process(c, p, level) for c, p, level in pages])

    all_entries = [e for group in results for e in group]
    all_entries = resolve_global_codes(all_entries)
    print(f"\nTotal grammar points: {len(all_entries)}", file=sys.stderr)

    output = json.dumps(all_entries, indent=2, ensure_ascii=False)
    if debug:
        print(output)
    else:
        OUT_PATH.write_text(output)
        print(f"Written to {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
