"""
Scrape communicative functions from the Profilo della Lingua Italiana website.
Usage: uv run python -m maestro.data.scrape_comm_functions
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.unistrapg.it/profilo_lingua_italiana/site/"
INDEX_URL = BASE_URL + "funzioni_lista.html"
OUT_PATH = Path(__file__).parent / "comm_functions.json"


def get_text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split())


def parse_index(html: str) -> list[dict]:
    """Return list of {label, url} from the index page."""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("funz_"):
            links.append({"label": get_text(a), "url": urljoin(BASE_URL, href)})
    return links


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[àáâã]", "a", text)
    text = re.sub(r"[èéêë]", "e", text)
    text = re.sub(r"[ìíîï]", "i", text)
    text = re.sub(r"[òóôõ]", "o", text)
    text = re.sub(r"[ùúûü]", "u", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def parse_function_page(html: str, label: str, url: str) -> list[dict]:
    """
    Parse a function detail page and return one entry per CEFR level present.
    Each entry has: code, label, macro_category, cefr_level, description, examples, source_url
    """
    soup = BeautifulSoup(html, "html.parser")

    # Debug: print all text to understand the structure
    # print(soup.get_text("\n", strip=True)[:3000])

    # Try to find the breadcrumb to extract macro_category
    macro_category = ""
    breadcrumb_candidates = soup.find_all(string=re.compile(r"Interagire|Strutturare"))
    for bc in breadcrumb_candidates:
        text = bc.strip()
        if "informazioni" in text.lower():
            macro_category = "interagire_informazioni"
        elif "atteggiamenti" in text.lower() or "opinioni" in text.lower():
            macro_category = "interagire_opinioni_atteggiamenti"
        elif "emozioni" in text.lower() or "sentimenti" in text.lower():
            macro_category = "interagire_emozioni_sentimenti"
        elif "azioni" in text.lower() or "attività" in text.lower():
            macro_category = "interagire_attivita_azioni"
        elif "rituali" in text.lower() or "sociali" in text.lower():
            macro_category = "interagire_rituali_sociali"
        elif "discorso" in text.lower():
            macro_category = "strutturare_discorso"
        elif "interazione" in text.lower() or "verbale" in text.lower():
            macro_category = "strutturare_interazione_verbale"
        if macro_category:
            break

    # Also check the URL itself for macro_category hints
    if not macro_category:
        if "interag_" in url:
            macro_category = "interagire_informazioni"
        elif "intatt_" in url:
            macro_category = "interagire_opinioni_atteggiamenti"
        elif "intemo_" in url:
            macro_category = "interagire_emozioni_sentimenti"
        elif "intazio_" in url:
            macro_category = "interagire_attivita_azioni"
        elif "intritsoc_" in url:
            macro_category = "interagire_rituali_sociali"
        elif "strutdisc_" in url:
            macro_category = "strutturare_discorso"
        elif "strintverb_" in url:
            macro_category = "strutturare_interazione_verbale"

    # Find CEFR level sections — look for elements with A1/A2/B1/B2 text
    cefr_pattern = re.compile(r"\b(A1|A2|B1|B2)\b")
    entries = []

    # Collect all text blocks and find CEFR markers
    all_text = soup.get_text("\n", strip=True)
    # Find all CEFR level sections
    sections: dict[str, list[str]] = {}
    current_level = None
    current_lines: list[str] = []

    for line in all_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = cefr_pattern.fullmatch(line.strip())
        if m:
            if current_level and current_lines:
                sections[current_level] = current_lines
            current_level = m.group(1)
            current_lines = []
        elif current_level:
            current_lines.append(line)

    if current_level and current_lines:
        sections[current_level] = current_lines

    url_slug = url.split("/")[-1].replace(".html", "")
    code = slugify(label)

    if not sections:
        # Page has no CEFR structure — skip
        return []

    for level, lines in sorted(sections.items(), key=lambda x: x[0]):
        # Separate example phrases (lines starting with quotes or in italic-style markers)
        # from description text
        description_lines = []
        example_lines = []
        for line in lines:
            # Lines that look like example phrases (contain Italian quotes or are short phrases)
            if line.startswith(("«", "»", '"', "'", "–", "-")):
                example_lines.append(line)
            else:
                description_lines.append(line)

        description = " ".join(description_lines).strip()
        examples = example_lines

        entries.append({
            "code": f"{code}_{level.lower()}",
            "label": label,
            "macro_category": macro_category,
            "cefr_level": level,
            "description": description,
            "examples": examples,
            "source_url": url,
        })

    return entries


async def fetch(client: httpx.AsyncClient, url: str) -> str:
    r = await client.get(url, timeout=30)
    r.raise_for_status()
    return r.text


async def main():
    print("Fetching index...", file=sys.stderr)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        index_html = await fetch(client, INDEX_URL)
        links = parse_index(index_html)
        print(f"Found {len(links)} function links", file=sys.stderr)

        # Debug: just process first 3 pages
        debug = "--debug" in sys.argv
        if debug:
            links = links[:3]

        sem = asyncio.Semaphore(5)  # max concurrent requests

        async def fetch_and_parse(link: dict) -> list[dict]:
            async with sem:
                try:
                    html = await fetch(client, link["url"])
                    entries = parse_function_page(html, link["label"], link["url"])
                    print(f"  {link['label']}: {len(entries)} level(s)", file=sys.stderr)
                    return entries
                except Exception as e:
                    print(f"  ERROR {link['url']}: {e}", file=sys.stderr)
                    return []

        results = await asyncio.gather(*[fetch_and_parse(l) for l in links])

    all_entries = [e for group in results for e in group]
    print(f"\nTotal entries: {len(all_entries)}", file=sys.stderr)

    if debug:
        print(json.dumps(all_entries[:10], indent=2, ensure_ascii=False))
    else:
        OUT_PATH.write_text(json.dumps(all_entries, indent=2, ensure_ascii=False))
        print(f"Written to {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
