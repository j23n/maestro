from functools import lru_cache
from maestro.settings import Settings
from maestro.models import ItalianChunk, ItalianChunkResult

@lru_cache(maxsize=1)
def get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("intfloat/multilingual-e5-large")


def embed_query(text: str) -> list[float]:
    # use asymmetric embedding for "multilingual-e5-large"
    # https://huggingface.co/intfloat/multilingual-e5-large
    return get_model().encode(f"query: {text}").tolist()


async def retrieve_for_grammar_point(
    gp_label: str, gp_description: str, top_k: int = 3
) -> list["ItalianChunkResult"]:
    """Semantic search for book chunks relevant to a grammar point.

    Does not filter by chunk_type to avoid requiring a token index on that field.
    All current chunks are of type 'grammar', so the filter is not needed.
    """
    query = embed_query(f"{gp_label}: {gp_description}")
    return await retrieve(query, top_k=top_k)


async def get_chunks_for_refs(refs: list[str]) -> list[ItalianChunk]:
    if not refs:
        return []
    return await ItalianChunk.find({"ref": {"$in": refs}}).to_list()


async def retrieve(query: list[float], top_k: int = 5):
    pipeline = [
        {
            "$vectorSearch": {
                "index": "embedding_index",
                "path": "embedding",
                "queryVector": query,
                "numCandidates": top_k * 10,
                "limit": top_k,
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
