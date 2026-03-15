"""
Re-map grammar points to grammar book chunks using embedding similarity.

Embeds all 124 chunks (passage: prefix) and all GP labels (query: prefix) using
intfloat/multilingual-e5-large, then assigns each GP the closest chunk by cosine sim.

Results are written directly into grammar_points.yaml as chunk_ref.

Run:  uv run python scripts/remap_chunks.py [--threshold 0.5] [--show-top N]
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import yaml

DATA_DIR = "src/maestro/data/it"


class LiteralStr(str):
    pass


def _lit_repr(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(LiteralStr, _lit_repr)


def cosine_sim(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cosine similarity between a (1, D) query and b (N, D) matrix."""
    a_norm = a / np.linalg.norm(a, axis=1, keepdims=True)
    b_norm = b / np.linalg.norm(b, axis=1, keepdims=True)
    return (a_norm @ b_norm.T).squeeze(0)


def main(threshold: float, show_top: int, dry_run: bool) -> None:
    # --- load data ---
    with open(f"{DATA_DIR}/grammar_points.yaml") as f:
        gps = yaml.safe_load(f)

    with open(f"{DATA_DIR}/chunk_enrichment.json") as f:
        enrichment: dict[str, str] = json.load(f)

    chunks = {k: v for k, v in enrichment.items() if not k.startswith("__")}
    chunk_refs = list(chunks.keys())
    chunk_texts = [f"passage: {v}" for v in chunks.values()]

    print(f"Chunks: {len(chunk_refs)}, GPs: {len(gps)}")

    # --- load model ---
    print("Loading intfloat/multilingual-e5-large…")
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("intfloat/multilingual-e5-large")

    # --- embed chunks ---
    print("Embedding chunks…")
    chunk_embs = model.encode(
        chunk_texts, batch_size=32, show_progress_bar=True, normalize_embeddings=True
    )  # (N, 1024)

    # --- embed GP labels ---
    gp_texts = [f"query: {gp.get('label') or gp.get('unistr_label', '')}" for gp in gps]
    print("Embedding GP labels…")
    gp_embs = model.encode(
        gp_texts, batch_size=32, show_progress_bar=True, normalize_embeddings=True
    )  # (M, 1024)

    # --- cosine similarity ---
    # shape: (M, N)
    sims = gp_embs @ chunk_embs.T

    # --- assign best chunk per GP ---
    updated = skipped = 0
    for i, gp in enumerate(gps):
        scores = sims[i]  # (N,)
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        best_ref = chunk_refs[best_idx]

        if show_top:
            top_idxs = np.argsort(scores)[::-1][:show_top]
            print(f"\n{gp['code']:20s} {gp['cefr_level']}  {gp.get('label', '')[:60]}")
            for j in top_idxs:
                marker = "→" if j == best_idx else " "
                print(f"  {marker} {scores[j]:.3f}  {chunk_refs[j]}")

        if best_score >= threshold:
            old = gp.get("chunk_ref")
            gp["chunk_ref"] = best_ref
            if old != best_ref:
                updated += 1
                if not show_top:
                    change = f"  (was: {old})" if old else ""
                    print(f"  {gp['code']:20s} {best_score:.3f}  {best_ref}{change}")
        else:
            skipped += 1
            if not show_top:
                print(f"  {gp['code']:20s} {best_score:.3f}  BELOW THRESHOLD — skipped")

    print(f"\nUpdated: {updated}, Skipped (below {threshold}): {skipped}")

    if dry_run:
        print("[DRY RUN] Not writing.")
        return

    # Wrap multiline strings for block-scalar output
    for gp in gps:
        for key in ("description",):
            if isinstance(gp.get(key), str) and "\n" in gp[key]:
                gp[key] = LiteralStr(gp[key])
        for lang, expl in gp.get("explanations", {}).items():
            for field in ("explanation", "tip", "why_this_matters"):
                if isinstance(expl.get(field), str) and "\n" in expl[field]:
                    expl[field] = LiteralStr(expl[field])
    with open(f"{DATA_DIR}/grammar_points.yaml", "w") as f:
        yaml.dump(gps, f, default_flow_style=False, allow_unicode=True, width=200)
    print(f"Written to {DATA_DIR}/grammar_points.yaml")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Min cosine similarity to assign a chunk_ref (default 0.5)",
    )
    p.add_argument(
        "--show-top",
        type=int,
        default=0,
        metavar="N",
        help="Print top N candidates per GP (for inspection, implies dry-run)",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.show_top:
        args.dry_run = True
    main(threshold=args.threshold, show_top=args.show_top, dry_run=args.dry_run)
