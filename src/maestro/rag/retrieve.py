from functools import lru_cache
from typing import Optional
from maestro.settings import Settings
from maestro.models import ItalianChunk, ItalianChunkResult

from sentence_transformers import SentenceTransformer
from sqlmodel import Session, text

from maestro.db import engine, TABLE_CHUNKS


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer("intfloat/multilingual-e5-large")


def embed_query(text: str) -> list[float]:
    # use asymmetric embedding for "multilingual-e5-large"
    # https://huggingface.co/intfloat/multilingual-e5-large
    return get_model().encode(f"query: {text}").tolist()


def retrieve(query: list[float], top_k: int = 5, chunk_type: Optional[str] = None):
    filter_clause = "AND chunk_type = :chunk_type" if chunk_type else ""
    with Session(engine) as session:
        result = session.exec(
            text(f"""
                SELECT id, chunk, chunk_type, chunk_metadata, embedding, ref, 
                1 - (embedding <=> (:vec)::vector) AS similarity
                FROM {TABLE_CHUNKS}
                WHERE 1=1 {filter_clause}
                ORDER BY embedding <=> (:vec)::vector
                LIMIT :k
            """).params(vec=query, chunk_type=chunk_type, k=top_k),
        )
        return [
            ItalianChunkResult(
                chunk=ItalianChunk(
                    id=row[0],
                    content=row[1],
                    chunk_type=row[2],
                    chunk_metadata=row[3],
                    embedding=row[4],
                    ref=row[5],
                ),
                similarity=row[6],
            )
            for row in result.fetchall()
        ]
