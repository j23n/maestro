"""
Scrape communicative functions from the Profilo della Lingua Italiana website.
Usage: uv run python -m maestro.data.scrape_comm_functions [--debug]
"""

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.unistrapg.it/profilo_lingua_italiana/site/"
INDEX_URL = BASE_URL + "funzioni_lista.html"
OUT_PATH = Path(__file__).parent / "comm_functions.json"

LEVEL_MAP = {"1": "A1", "2": "A2", "3": "B1", "4": "B2"}

URL_TO_MACRO = {
    "funz_interag_": "interagire_informazioni",
    "funz_intatt_":  "interagire_opinioni_atteggiamenti",
    "funz_intemo_":  "interagire_emozioni_sentimenti",
    "funz_intazio_": "interagire_attivita_azioni",
    "funz_intritsoc_": "interagire_rituali_sociali",
    "funz_strutdisc_": "strutturare_discorso",
    "funz_strintverb_": "strutturare_interazione_verbale",
}


def get_text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split())


def macro_from_url(url: str) -> str:
    filename = url.split("/")[-1]
    for prefix, cat in URL_TO_MACRO.items():
        if filename.startswith(prefix):
            return cat
    return ""


def slugify(filename: str) -> str:
    """Turn e.g. 'funz_interag_asserire.html' → 'interag_asserire'."""
    name = filename.replace(".html", "")
    # strip leading funz_
    if name.startswith("funz_"):
        name = name[len("funz_"):]
    return name


def parse_index(html: str) -> list[dict]:
    """Return [{label, page_url}] for all funz_*.html links."""
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("funz_") and href not in seen:
            seen.add(href)
            links.append({
                "label": get_text(a),
                "page_url": urljoin(BASE_URL, href),
                "include_url": urljoin(BASE_URL, "include/inc_" + href),
                "slug": slugify(href),
            })
    return links


def cell_lines(td) -> list[str]:
    """
    Extract lines from a table cell, splitting on <br> tags.
    Italic text within a line is included inline, not as separate items.
    """
    # Replace <br> with a sentinel, then get full text
    for br in td.find_all("br"):
        br.replace_with("\n")
    full_text = td.get_text(" ", strip=False)
    lines = []
    for line in full_text.split("\n"):
        # Normalize whitespace
        line = " ".join(line.split()).strip()
        if line and line not in ("…", "..."):
            lines.append(line)
    return lines


def parse_include(html: str, link: dict) -> list[dict]:
    """
    Parse an include file and return one entry per CEFR level with content.
    Structure: <a class="slidecontrol" id="slidecontrol_N">Livello Ax</a>
               <div id="slidedisplay_N"> <table> <tr> <td>patterns</td><td>examples</td> </tr> </table> </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    macro = macro_from_url(link["page_url"])
    entries = []

    controls = soup.find_all("a", class_="slidecontrol")
    for ctrl in controls:
        ctrl_id = ctrl.get("id", "")          # e.g. "slidecontrol_1"
        num = ctrl_id.replace("slidecontrol_", "")
        level = LEVEL_MAP.get(num)
        if not level:
            continue

        display_id = f"slidedisplay_{num}"
        display_div = soup.find("div", id=display_id)
        if not display_div:
            continue

        # Check for empty level
        text_content = display_div.get_text(strip=True)
        if "Nessun descrittore" in text_content or not text_content:
            continue

        # Extract patterns and examples from table cells
        patterns: list[str] = []
        examples: list[str] = []

        tds = display_div.find_all("td")
        if len(tds) >= 2:
            patterns = cell_lines(tds[0])
            examples = cell_lines(tds[1])
        elif len(tds) == 1:
            # Single-column: treat as examples
            examples = cell_lines(tds[0])

        entries.append({
            "code": f"{link['slug']}_{level.lower()}",
            "label": link["label"],
            "macro_category": macro,
            "cefr_level": level,
            "patterns": patterns,
            "examples": examples,
            "source_url": link["page_url"],
        })

    return entries


async def fetch(client: httpx.AsyncClient, url: str) -> str:
    r = await client.get(url, timeout=30)
    r.raise_for_status()
    return r.text


async def main():
    debug = "--debug" in sys.argv

    print("Fetching index...", file=sys.stderr)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        index_html = await fetch(client, INDEX_URL)
        links = parse_index(index_html)
        print(f"Found {len(links)} function pages", file=sys.stderr)

        if debug:
            links = links[:5]

        sem = asyncio.Semaphore(8)

        async def process(link: dict) -> list[dict]:
            async with sem:
                include_url = link["include_url"]
                try:
                    html = await fetch(client, include_url)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        # Fallback: read the actual iframe src from the main page
                        try:
                            main_html = await fetch(client, link["page_url"])
                            soup = BeautifulSoup(main_html, "html.parser")
                            iframe = soup.find("iframe", src=True)
                            if iframe:
                                include_url = urljoin(BASE_URL, iframe["src"])
                                html = await fetch(client, include_url)
                            else:
                                print(f"  SKIP (no iframe) {link['page_url']}", file=sys.stderr)
                                return []
                        except Exception as e2:
                            print(f"  ERROR {link['page_url']}: {e2}", file=sys.stderr)
                            return []
                    else:
                        print(f"  ERROR {include_url}: {e}", file=sys.stderr)
                        return []
                except Exception as e:
                    print(f"  ERROR {include_url}: {e}", file=sys.stderr)
                    return []
                try:
                    entries = parse_include(html, link)
                    print(f"  {link['label']}: {[e['cefr_level'] for e in entries]}", file=sys.stderr)
                    return entries
                except Exception as e:
                    print(f"  PARSE ERROR {include_url}: {e}", file=sys.stderr)
                    return []

        results = await asyncio.gather(*[process(link) for link in links])

    all_entries = [e for group in results for e in group]
    print(f"\nTotal entries: {len(all_entries)}", file=sys.stderr)

    output = json.dumps(all_entries, indent=2, ensure_ascii=False)
    if debug:
        print(output)
    else:
        OUT_PATH.write_text(output)
        print(f"Written to {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
