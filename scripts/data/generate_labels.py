"""
Generate concise Italian labels for all GrammarPoints and write them to grammar_points.json.

Labels are precise Italian noun phrases (5–12 words) using standard grammatical terminology.
They serve as the primary display name in LLM lesson-planning and scoring prompts.

Rules the LLM follows:
- Italian only
- 5–12 words, noun phrase form
- Standard grammatical terms (indicativo presente, congiuntivo, complemento di termine, …)
- Specific enough to distinguish sibling concepts
- No examples (strip "es. …" content)
- First word capitalised only

Idempotent — skips GPs that already have a `label` field. Use --force to regenerate.

Run with:  python -m maestro.grammar.generate_labels
"""

from __future__ import annotations

import argparse
import json
import logging

from maestro.llm import get_client
from maestro.utils import data_dir

logger = logging.getLogger(__name__)

_BATCH_SIZE = 25  # GPs per LLM call

_SYSTEM = """\
Sei un esperto di linguistica italiana. Generi etichette concise e precise per i punti grammaticali \
di un sistema di apprendimento dell'italiano basato sul CEFR.

Ogni etichetta deve:
- Essere in italiano
- Avere 5–12 parole in forma di sintagma nominale (non una frase completa)
- Usare la terminologia grammaticale standard (es. "indicativo presente", "congiuntivo imperfetto", \
"complemento di termine", "preposizione di con valore partitivo")
- Essere abbastanza specifica da distinguere concetti simili (es. \
"preposizione a con valore di luogo" ≠ "preposizione a con valore di tempo")
- Non contenere esempi (rimuovere il contenuto dopo "es." o dopo la virgola se è un esempio)
- Avere solo la prima parola in maiuscolo

Per i punti grammaticali che rappresentano un uso specifico di una preposizione, usa il formato:
"Preposizione [X] con valore di [uso]"

Per i tempi e modi verbali, usa il formato:
"[Modo] [tempo] [uso specifico se necessario]"
"""


def _build_prompt(batch: list[dict]) -> str:
    lines = []
    for i, gp in enumerate(batch, 1):
        source = gp.get("unistr_label") or gp.get("label", "")
        lines.append(f"{i}. [{gp['cefr_level']}] [{gp['category']}] {source}")

    return (
        "Per ogni punto grammaticale sotto, scrivi un'etichetta italiana precisa.\n\n"
        + "\n".join(lines)
        + f"\n\nRispondi SOLO con un array JSON di {len(batch)} etichette nello stesso ordine. "
        "Nessun altro testo.\n"
        'Esempio: ["Indicativo presente dei verbi regolari", "Passato prossimo con ausiliare essere"]'
    )


def _parse_response(raw: str, expected: int) -> list[str] | None:
    raw = raw.strip()
    # Strip markdown fences
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if "```" in raw:
            raw = raw.rsplit("```", 1)[0]
    try:
        labels = json.loads(raw)
        if isinstance(labels, list) and len(labels) == expected:
            return [str(lbl).strip() for lbl in labels]
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _generate_batch(batch: list[dict], client) -> list[str] | None:
    prompt = _build_prompt(batch)
    for attempt in range(3):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        labels = _parse_response(raw, len(batch))
        if labels:
            return labels
        logger.warning(f"  Attempt {attempt + 1}: bad response — {raw[:120]}")
    return None


def generate(force: bool = False, code: str | None = None) -> None:
    json_path = data_dir() / "grammar_points.json"
    with open(json_path) as f:
        items = json.load(f)

    if code:
        todo = [i for i, gp in enumerate(items) if gp["code"] == code]
        if not todo:
            logger.error(f"GP '{code}' not found")
            return
    else:
        todo = [i for i, gp in enumerate(items) if force or not gp.get("label")]

    if not todo:
        logger.info("All GPs already have labels. Use --force to regenerate.")
        return

    logger.info(f"Generating labels for {len(todo)} grammar points")
    client = get_client()

    total_batches = (len(todo) + _BATCH_SIZE - 1) // _BATCH_SIZE
    for batch_num, batch_start in enumerate(range(0, len(todo), _BATCH_SIZE), 1):
        batch_idxs = todo[batch_start : batch_start + _BATCH_SIZE]
        batch_gps = [items[i] for i in batch_idxs]
        logger.info(f"Batch {batch_num}/{total_batches} ({len(batch_gps)} GPs)…")

        labels = _generate_batch(batch_gps, client)
        if labels is None:
            logger.error(f"Batch {batch_num} failed after 3 attempts — aborting")
            return

        for idx, label in zip(batch_idxs, labels):
            items[idx]["label"] = label
            logger.info(f"  {items[idx]['code']:20s}  →  {label}")

    with open(json_path, "w") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
        f.write("\n")

    logger.info("Done. Updated grammar_points.json.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate Italian labels for grammar points"
    )
    parser.add_argument(
        "--force", action="store_true", help="Regenerate existing labels"
    )
    parser.add_argument(
        "--code", type=str, help="Regenerate label for a single GP by code"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.debug:
        logger.setLevel(logging.DEBUG)
    generate(force=args.force, code=args.code)
