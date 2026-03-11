import json
import asyncio

from pathlib import Path
from markdownify import markdownify
from bs4 import BeautifulSoup
import re
from pymongo import AsyncMongoClient

from maestro.models import GrammarChunk
from maestro.config import settings
from maestro.db import init_db, init_indices
from maestro.rag.retrieve import get_model

from maestro.utils import data_dir

ENRICHMENT_FILE = data_dir("it") / "chunk_enrichment.json"


BOOK_DIR = data_dir("it") / "book_contents/OEBPS/Text"
CHAPTER_FILES = sorted(
    f for f in BOOK_DIR.glob("*.xhtml") if re.search(r"_c\d+\.xhtml$", f.name)
)
SPLIT_H3_CHAPTERS = {
    "9788811136859_c04.xhtml",
    "9788811136859_c07.xhtml",
    "9788811136859_c08.xhtml",
}


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[''']", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _parse_prospetto(tags) -> list[tuple[str | None, list]]:
    """One group per model-verb table, labelled with the verb name.
    The overview table (no sgc-4 header) gets label None."""
    groups = []
    current: list = []
    current_label: str | None = None
    for tag in tags:
        if tag.name == "table" and tag.find("td", class_="sgc-4"):
            if current:
                groups.append((current_label, current))
            current_label = tag.find("td", class_="sgc-4").get_text(strip=True)
            current = [tag]
        else:
            current.append(tag)
    if current:
        groups.append((current_label, current))
    return groups


def _parse_tavola(tags) -> list[tuple[str | None, list]]:
    """One group per first letter of the bold verb name."""
    buckets: dict[str, list] = {}
    for tag in tags:
        bold = tag.find("b") if hasattr(tag, "find") else None
        if bold:
            letter = bold.get_text(strip=True)[0].upper()
            buckets.setdefault(letter, []).append(tag)
    return [(letter, buckets[letter]) for letter in sorted(buckets)]


SECTION_HANDLERS = {
    "prospetto_dei_modi_e_dei_tempi_del_verbopresente_passato_futuro": _parse_prospetto,
    "tavola_dei_verbi_irregolari": _parse_tavola,
}


def _make_chunk(
    chapter: str,
    heading: str,
    tags: list,
    filepath: Path,
    tag_index: int,
    ref_context: str | None = None,
) -> dict:
    html = "".join(str(t) for t in tags)
    content = markdownify(html, heading_style="ATX", bullets="-").strip()

    ref_heading = heading if heading != chapter else ""
    if ref_context:
        ref_slug = f"{slugify(ref_context)}_{slugify(ref_heading)}"
    else:
        ref_slug = slugify(ref_heading)

    return {
        "ref": f"book_{slugify(chapter)}_{ref_slug}".lower()
        .strip("_")
        .replace(" ", "_")[:100],
        "content": f"## {heading}\n\n{content}",
        "chunk_type": "grammar",
        "metadata": {
            "source": "grammar_book",
            "chapter": chapter,
            "heading": heading,
            "file": filepath.name,
            "section_index": tag_index,
        },
    }


def _flush(
    chapter: str,
    heading: str,
    tags: list,
    filepath: Path,
    chunks: list,
    ref_context: str | None = None,
):
    slug = slugify(heading)
    handler = SECTION_HANDLERS.get(slug)
    if handler:
        for label, group in handler(tags):
            sub_heading = f"{heading} — {label}" if label else heading
            chunks.append(
                _make_chunk(chapter, sub_heading, group, filepath, len(chunks))
            )
    else:
        chunks.append(
            _make_chunk(
                chapter, heading, tags, filepath, len(chunks), ref_context=ref_context
            )
        )


def parse_chapter(filepath: Path, split_h3: bool = False) -> list[dict]:
    """
    Notes on the epub structure:
    - Every chapter has exactly one h1 - the chapter title
    - Every chapter has [0..n] h2 - the semantic topics, what we use for chunks
        - c02 has an h1 with no h2 at all
        - c09 and c12 have an h1 followed immediately by h3s with no h2 parent
        - Some chapters have h3 under h2 (c04, c07, c08...)

    We chunk at the h2 level,
        - h3 content is treated as part of the h2 parent
        - when no h2 exists, the whole chapter body becomes the chunk content
    """
    soup = BeautifulSoup(filepath.read_text(encoding="utf-8"), "html.parser")

    chapter_title = soup.find("h1")
    assert chapter_title
    assert soup.body

    chapter_name = chapter_title.get_text(strip=True)

    chunks = []
    current_heading = chapter_name
    current_h2 = chapter_name
    current_tags = []

    def ref_context_for_current():
        # Include h2 context in ref when we're at h3 level, to disambiguate
        # headings that repeat across (or within) different h2 sections.
        return current_h2 if (split_h3 and current_heading != current_h2) else None

    for tag in soup.body.children:
        if not hasattr(tag, "name") or tag.name is None:
            continue
        if tag.name == "h1":
            current_heading = tag.get_text(strip=True)
            current_h2 = current_heading
            current_tags = []
        elif tag.name == "h2":
            if current_tags:
                _flush(
                    chapter_name,
                    current_heading,
                    current_tags,
                    filepath,
                    chunks,
                    ref_context_for_current(),
                )
            current_h2 = tag.get_text(strip=True)
            current_heading = current_h2
            current_tags = []
        elif split_h3 and tag.name == "h3":
            if current_tags:
                _flush(
                    chapter_name,
                    current_heading,
                    current_tags,
                    filepath,
                    chunks,
                    ref_context_for_current(),
                )
            current_heading = tag.get_text(strip=True)
            current_tags = []
        else:
            current_tags.append(tag)

    if current_tags:
        _flush(
            chapter_name,
            current_heading,
            current_tags,
            filepath,
            chunks,
            ref_context_for_current(),
        )

    return chunks


async def ingest_grammar_rules(client, no_embed: bool = False):
    init_indices(client)

    all_chunks = []

    print(f"Ingesting {BOOK_DIR}...")

    for filepath in CHAPTER_FILES:
        print(f"Parsing {filepath.name}...")
        all_chunks.extend(
            parse_chapter(filepath, split_h3=filepath.name in SPLIT_H3_CHAPTERS)
        )

    # Deduplicate refs that are still identical after context-qualified slugification
    # (e.g. same h3 heading appearing twice within the same h2 section).
    seen: dict[str, int] = {}
    for chunk in all_chunks:
        ref = chunk["ref"]
        if ref in seen:
            seen[ref] += 1
            chunk["ref"] = f"{ref}_{seen[ref]}"
        else:
            seen[ref] = 0

    print(f"Total chunks: {len(all_chunks)}")
    for i, c in enumerate(all_chunks):
        print(f"\t{c['ref']} length: {len(c['content'])}")

    if no_embed:
        embeddings = [[] for _ in all_chunks]
    else:
        # use asymmetric embeddings for "multilingual-e5-large"
        # https://huggingface.co/intfloat/multilingual-e5-large
        enrichment = (
            json.loads(ENRICHMENT_FILE.read_text()) if ENRICHMENT_FILE.exists() else {}
        )
        texts = [
            f"passage: {enrichment[c['ref']]}\n\n{c['content']}"
            if c["ref"] in enrichment
            else f"passage: {c['content']}"
            for c in all_chunks
        ]
        embeddings = get_model().encode(texts, batch_size=64, show_progress_bar=True)
        embeddings = [e.tolist() for e in embeddings]

    chunks = []
    for chunk, embedding in zip(all_chunks, embeddings):
        chunks.append(
            GrammarChunk(
                ref=chunk["ref"],
                content=chunk["content"],
                chunk_type=chunk["chunk_type"],
                embedding=embedding,
                chunk_metadata=chunk["metadata"],
            )
        )
    await GrammarChunk.insert_many(chunks)

    print("Done.")
    print(f"Inserted: {await GrammarChunk.count()}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-embed", action="store_true", help="Skip vector embeddings"
    )
    args = parser.parse_args()

    async def main():
        client = AsyncMongoClient(settings.MONGO_URL)
        await init_db()
        await GrammarChunk.delete_all()
        await ingest_grammar_rules(client, no_embed=args.no_embed)

    asyncio.run(main())
