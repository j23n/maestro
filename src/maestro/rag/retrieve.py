from functools import lru_cache
from typing import Optional
from maestro.settings import Settings
from maestro.models import ItalianChunk, ItalianChunkResult

from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer("intfloat/multilingual-e5-large")


def embed_query(text: str) -> list[float]:
    # use asymmetric embedding for "multilingual-e5-large"
    # https://huggingface.co/intfloat/multilingual-e5-large
    return get_model().encode(f"query: {text}").tolist()


async def retrieve(
    query: list[float], top_k: int = 5, chunk_type: Optional[str] = None
):
    pipeline = [
        {
            "$vectorSearch": {
                "index": "embedding_index",
                "path": "embedding",
                "queryVector": query,
                "numCandidates": top_k * 10,
                "limit": top_k,
                **(
                    {"filter": {"chunk_type": {"$eq": chunk_type}}}
                    if chunk_type
                    else {}
                ),
            }
        },
        {"$addFields": {"similarity": {"$meta": "vectorSearchScore"}}},
    ]
    results = await ItalianChunk.aggregate(pipeline).to_list()
    return [
        ItalianChunkResult(
            chunk=ItalianChunk.model_validate(
                {k: v for k, v in r.items() if k != "similarity"}
            ),
            similarity=r["similarity"],
        )
        for r in results
    ]
