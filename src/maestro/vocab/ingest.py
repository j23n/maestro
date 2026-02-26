import asyncio
import gzip
import json
import re
from pathlib import Path

import anthropic
import httpx
from bs4 import BeautifulSoup

from maestro.db import init_db
from maestro.models import UserVocabularyCard, VocabularyWord
from maestro.settings import Settings
from maestro.vocab.nlp import get_nlp


WORDLISTS = [
    (
        "A1",
        "https://www.unistrapg.it/profilo_lingua_italiana/site/liste_lessicali_a1.html",
    ),
    (
        "A2",
        "https://www.unistrapg.it/profilo_lingua_italiana/site/liste_lessicali_a2.html",
    ),
    (
        "B1",
        "https://www.unistrapg.it/profilo_lingua_italiana/site/liste_lessicali_b1.html",
    ),
    (
        "B2",
        "https://www.unistrapg.it/profilo_lingua_italiana/site/liste_lessicali_b2.html",
    ),
]

# Italian grammatical abbreviation → English part of speech
POS_MAP = {
    "v.t.": "verb",
    "v. t.": "verb",
    "v.int.": "verb",
    "v. int.": "verb",
    "v.": "verb",
    "s.m.": "noun",
    "s.f.": "noun",
    "s.m./f.": "noun",
    "agg.": "adjective",
    "avv.": "adverb",
    "prep.": "preposition",
    "pron.": "pronoun",
    "art.": "article",
    "cong.": "conjunction",
    "inter.": "interjection",
    "num.": "numeral",
}

# Download with:
#   curl -L https://raw.githubusercontent.com/snizio/italian-wiktionary-parser/master/it-dictionary.gz \
#        -o src/maestro/data/it-dictionary.gz
DATA_DIR = Path(__file__).parent.parent / "data"
GLAW_IT_PATH = DATA_DIR / "it-dictionary.gz"

BATCH_SIZE = 50


def load_glaw_it() -> dict:
    if not GLAW_IT_PATH.exists():
        raise FileNotFoundError(
            f"GLAW-IT dictionary not found. Download with:\n"
            f"  curl -L https://raw.githubusercontent.com/snizio/italian-wiktionary-parser/master/it-dictionary.gz"
            f" -o {GLAW_IT_PATH}"
        )
    print(f"Loading GLAW-IT dictionary from {GLAW_IT_PATH}...")
    with gzip.open(GLAW_IT_PATH, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def _extract_glosses(entry: dict) -> str | None:
    defs = []
    for key, meaning in entry["meanings"].items():
        if key.startswith("verb form"):
            continue
        glossa = meaning.get("glossa", "")
        glossa = re.sub(r"\[ESEMPIO:[^\]]*\]", "", glossa)
        glossa = re.sub(r"##[^#]+##", "", glossa)
        glossa = glossa.strip()
        if glossa:
            defs.append(glossa)
    return "; ".join(defs) if defs else None


def lookup_glaw_it(word: str, index: dict, nlp) -> dict | None:
    lemma = nlp(word)[0].lemma_.lower()
    candidates = {word, word.lower(), word.title(), lemma}
    entry = next((index[c] for c in candidates if c in index), None)
    if not entry:
        return None
    definition = _extract_glosses(entry)
    return {"definition": definition} if definition else None


def translate_batch(
    words_with_defs: list[tuple[str, str]], client: anthropic.Anthropic
) -> dict[str, str]:
    if not words_with_defs:
        return {}
    entries = "\n".join(f"- {word}: {defn}" for word, defn in words_with_defs)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": (
                    "Translate these Italian vocabulary words to English. "
                    "For each word, provide a concise English translation (1-8 words). If multiple, sort the translations by their commonness."
                    "Return ONLY a JSON object mapping each word to its English translation.\n\n"
                    f"{entries}"
                ),
            }
        ],
    )
    text = response.content[0].text.strip()
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


def generate_definitions_batch(
    words: list[tuple[str, str]], client: anthropic.Anthropic
) -> dict[str, dict]:
    """For words absent from GLAW-IT, ask the LLM for both definition and translation."""
    if not words:
        return {}
    entries = "\n".join(f"- {word} ({pos})" for word, pos in words)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": (
                    "For each of these Italian vocabulary words, provide:\n"
                    '1. "definition": a concise Italian-language definition (1-2 sentences)\n'
                    '2. "translation": a concise English translation (1-8 words). If multiple, rank the translations by their commonness.\n\n'
                    "Return ONLY a JSON object where each key is the word and the value is "
                    '{"definition": "...", "translation": "..."}.\n\n'
                    f"{entries}"
                ),
            }
        ],
    )
    text = response.content[0].text.strip()
    text = re.sub(r"^```(?:json)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


async def fetch_wordlist(
    url: str, cefr_level: str, client: httpx.AsyncClient
) -> list[tuple[str, str, str]]:
    response = await client.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    legend = soup.find("table", class_="tablelegenda")
    word_table = legend.find_next_sibling("table")
    # Use a dict keyed by word to deduplicate within the list (last POS wins)
    seen: dict[str, tuple[str, str, str]] = {}
    for a in word_table.find_all("a"):
        word = a.get_text(strip=True).split("(")[0].split("/")[0].strip().lower()
        trailing = a.next_sibling or ""
        match = re.search(r"\(([^)]+)\)", str(trailing))
        raw_pos = match.group(1).strip() if match else ""
        pos = POS_MAP.get(raw_pos, "unknown")
        if word:
            seen[word] = (word, pos, cefr_level)
    return list(seen.values())


HEADERS = {
    "User-Agent": "maestro-italian-tutor/1.0 (language learning app; contact via github)"
}


async def ingest():
    await init_db()
    glaw_it = load_glaw_it()
    nlp = get_nlp()
    settings = Settings()
    llm = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    print("Clearing existing vocabulary...")
    await UserVocabularyCard.find_all().delete()
    await VocabularyWord.find_all().delete()

    ingested: set[str] = set()  # track across CEFR levels

    async with httpx.AsyncClient(headers=HEADERS) as client:
        for cefr_level, url in WORDLISTS:
            print(f"\n=== {cefr_level} ===")
            wordlist = await fetch_wordlist(url, cefr_level, client)
            print(f"Found {len(wordlist)} words")

            # First pass: split into GLAW-IT hits and misses, skip cross-level dupes
            found: list[tuple[str, str, str, str]] = []  # word, pos, level, italian_def
            missing: list[tuple[str, str, str]] = []  # word, pos, level
            for word, pos, level in wordlist:
                if word in ingested:
                    continue
                data = lookup_glaw_it(word, glaw_it, nlp)
                if data:
                    found.append((word, pos, level, data["definition"]))
                else:
                    missing.append((word, pos, level))

            # Second pass: LLM generates definition + translation for GLAW-IT misses
            llm_defs: dict[str, dict] = {}
            if missing:
                print(f"  Generating {len(missing)} missing definitions via LLM...")
                for i in range(0, len(missing), BATCH_SIZE):
                    batch = missing[i : i + BATCH_SIZE]
                    llm_defs.update(
                        generate_definitions_batch([(w, p) for w, p, _ in batch], llm)
                    )

            # Third pass: batch-translate GLAW-IT Italian definitions → English
            translations: dict[str, str] = {}
            if found:
                print(f"  Translating {len(found)} GLAW-IT definitions...")
                for i in range(0, len(found), BATCH_SIZE):
                    batch = found[i : i + BATCH_SIZE]
                    translations.update(
                        translate_batch([(w, d) for w, _, _, d in batch], llm)
                    )
                    print(
                        f"  translated {min(i + BATCH_SIZE, len(found))}/{len(found)}"
                    )

            # Fourth pass: insert all into DB
            all_entries: list[tuple[str, str, str, str | None, str | None]] = [
                (w, p, l, d, translations.get(w)) for w, p, l, d in found
            ] + [
                (
                    w,
                    p,
                    l,
                    llm_defs.get(w, {}).get("definition"),
                    llm_defs.get(w, {}).get("translation"),
                )
                for w, p, l in missing
            ]
            for word, pos, level, italian_def, translation in all_entries:
                if not italian_def or not translation:
                    print(f"  skipping {word} (no definition/translation)")
                    continue
                await VocabularyWord(
                    word=word,
                    part_of_speech=pos,
                    cefr_level=level,
                    definition=italian_def,
                    translation=translation,
                ).insert()
                ingested.add(word)
                print(f"  ingested: {word} ({pos}, {level})")


if __name__ == "__main__":
    asyncio.run(ingest())
