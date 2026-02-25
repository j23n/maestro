from typing import Optional
import json
from maestro.settings import Settings
from maestro.models import ItalianChunk, ItalianChunkResult

from pathlib import Path
from sentence_transformers import SentenceTransformer
from sqlmodel import create_engine, SQLModel, Session, text


TABLE_NAME = "italian_chunks"

# Database stuff
settings = Settings()
# engine = create_engine(settings.database_url)
engine = create_engine(
    f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@100.64.0.2:5432/{settings.POSTGRES_DB}"
)

# Set up the embedder
model = SentenceTransformer("intfloat/multilingual-e5-large")


def retrieve(query: list[float], top_k: int, chunk_type: Optional[str] = None):
    filter_clause = "AND chunk_type = :chunk_type" if chunk_type else ""
    with Session(engine) as session:
        result = session.exec(
            text(f"""
                SELECT id, chunk, chunk_type, chunk_metadata, embedding
                1 - (embedding <=> (:vec)::vector) AS similarity
                FROM {TABLE_NAME}
                WHERE 1=1 {filter_clause}
                ORDER BY embedding <=> (:vec)::vector
                LIMIT :k
            """).params(vec=query, chunk_type=chunk_type, k=top_k),
        )
        return [
            ItalianChunkResult(
                chunk=ItalianChunk(
                    chunk=row[0],
                    chunk_type=row[1],
                    chunk_metadata=row[2],
                    embedding=row[3],
                ),
                similarity=row[4],
            )
            for row in result.fetchall()
        ]


def inference(sentence: str, k: int = 2):
    query = model.encode(sentence)
    results = retrieve(query, k)

    print(f"Input sentence: {sentence}")

    print("Output:")
    for r in results:
        print(f"\t{r.similarity:.2f}: {r.chunk.chunk}\n\tMetadata: {r.metadata}")
