import asyncio
from maestro.db import init_db
from pymongo import AsyncMongoClient
from anthropic import Anthropic
import json
from pathlib import Path

from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.metrics import (
    LLMContextRecall,
    ContextPrecision,
    NonLLMContextRecall,
    NonLLMContextPrecisionWithReference,
)
from ragas.llms import LangchainLLMWrapper
from langchain_anthropic import ChatAnthropic

from maestro.rag.retrieve import retrieve, embed_query
from maestro.models import ItalianChunk
from maestro.settings import Settings

settings = Settings()


EVAL_PATH = Path(__file__).parent.parent / "data" / "grammar_eval.json"


async def build_dataset(client: AsyncMongoClient, top_k: int = 5) -> EvaluationDataset:
    cases = json.loads(EVAL_PATH.read_text())
    samples = []

    for case in cases:
        query = embed_query(case["query"])
        results = await retrieve(query, top_k=top_k)
        retrieved_contexts = [result.chunk.content for result in results]

        reference_contexts = []
        for ref_id in case["expected_rules"]:
            chunk = await ItalianChunk.find_one({"ref": ref_id})
            if chunk:
                reference_contexts.append(chunk.content)

        reference = reference_contexts[0] if reference_contexts else ""

        samples.append(
            SingleTurnSample(
                user_input=case["query"],
                retrieved_contexts=retrieved_contexts,
                reference_contexts=reference_contexts,
                reference=reference,
            )
        )
    return EvaluationDataset(samples=samples)


def run_eval(dataset: EvaluationDataset, top_k: int = 5, use_llm=False):
    if use_llm:
        evaluator_llm = LangchainLLMWrapper(
            ChatAnthropic(
                anthropic_api_key=settings.ANTHROPIC_API_KEY,
                model_name="claude-haiku-4-5-20251001",
                temperature=1,
            )
        )

        results = evaluate(
            dataset=dataset,
            metrics=[
                LLMContextRecall(llm=evaluator_llm),
                ContextPrecision(llm=evaluator_llm),
            ],
        )
        df = results.to_pandas()
        print(df[["user_input", "context_recall", "context_precision"]].to_string())
        print(results)
    else:
        results = evaluate(
            dataset=dataset,
            metrics=[NonLLMContextRecall(), NonLLMContextPrecisionWithReference()],
        )
        df = results.to_pandas()
        print(
            df[
                [
                    "user_input",
                    "non_llm_context_recall",
                    "non_llm_context_precision_with_reference",
                ]
            ].to_string()
        )
        print(results)

    return results


if __name__ == "__main__":

    async def main():
        settings = Settings()
        client = AsyncMongoClient(settings.database_url)
        await init_db()
        dataset = await build_dataset(client, 5)
        run_eval(dataset)

    asyncio.run(main())
