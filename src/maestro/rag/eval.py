from anthropic import Anthropic
from sqlmodel import Session, select
from maestro.db import engine
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


def build_dataset(top_k: int = 5) -> EvaluationDataset:
    cases = json.loads(EVAL_PATH.read_text())
    samples = []

    with Session(engine) as session:
        for case in cases:
            query = embed_query(case["query"])
            results = retrieve(query, top_k=top_k)
            retrieved_contexts = [result.chunk.content for result in results]

            reference_contexts = [
                chunk.content
                for ref_id in case["expected_rules"]
                if (
                    chunk := session.exec(
                        select(ItalianChunk).where(ItalianChunk.ref == ref_id)
                    ).first()
                )
            ]

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


def run_eval(top_k: int = 5, use_llm=False):
    dataset = build_dataset(top_k)

    if use_llm:
        evaluator_llm = LangchainLLMWrapper(
            ChatAnthropic(
                anthropic_api_key=settings.ANTHROPIC_API_KEY,
                model="claude-haiku-4-5-20251001",
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
    run_eval(top_k=7)
