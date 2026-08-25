"""
RAGAS evaluation harness.

Usage:
  python -m research_assistant.eval.run_eval [--dataset qa_dataset.json] [--output eval_report.md]

Metrics computed:
  - faithfulness        (RAGAS): are claims in the answer supported by retrieved context?
  - answer_relevance    (RAGAS): does the answer address the question?
  - context_precision   (RAGAS): are top retrieved chunks actually relevant?
  - context_recall      (RAGAS): do retrieved chunks cover the ground truth answer?
  - decline_rate        (manual): % of negative questions correctly declined

RAGAS requires ground-truth answers for context_recall; we provide them via
ground_truth in each qa_dataset.json entry.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from datasets import Dataset

from research_assistant.config import settings
from research_assistant.core import answer_question

EVAL_DIR = Path(__file__).parent


def load_dataset(path: Path) -> list[dict]:
    with path.open() as f:
        data = json.load(f)
    # Filter out _comment entries (placeholder)
    return [d for d in data if "question" in d]


def _patch_ragas_vertexai_import() -> None:
    """
    Stub out langchain_community.chat_models.vertexai before ragas loads it.

    ragas 0.4.x hard-imports ChatVertexAI from langchain_community.chat_models.vertexai
    at module load time.  This module was removed in langchain-community 0.4.x when
    Google integrations moved to langchain-google-vertexai.  We never use VertexAI,
    so a stub empty class satisfies the import without functionality.
    """
    import sys
    from types import ModuleType

    _MOD = "langchain_community.chat_models.vertexai"
    if _MOD not in sys.modules:
        stub = ModuleType(_MOD)
        stub.ChatVertexAI = type("ChatVertexAI", (), {})  # type: ignore[attr-defined]
        sys.modules[_MOD] = stub


def run_eval(dataset_path: Path, output_path: Path) -> dict[str, Any]:
    _patch_ragas_vertexai_import()
    from langchain_anthropic import ChatAnthropic
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from ragas import evaluate

    # ragas 0.4.x split metrics into two tiers:
    #   - ragas.metrics.collections.*  (new-style, require OpenAI via instructor library)
    #   - ragas.metrics._*             (old-style, accept any LangChain LLM via llm= injection)
    # We use the old-style tier so we can inject our Anthropic LLM via evaluate(llm=...).
    from ragas.embeddings.base import LangchainEmbeddingsWrapper
    from ragas.llms.base import LangchainLLMWrapper
    from ragas.metrics._answer_relevance import answer_relevancy
    from ragas.metrics._context_precision import context_precision
    from ragas.metrics._context_recall import context_recall
    from ragas.metrics._faithfulness import faithfulness

    qa_pairs = load_dataset(dataset_path)
    if not qa_pairs:
        raise ValueError(f"No valid Q&A pairs found in {dataset_path}")

    questions, answers, ground_truths, contexts = [], [], [], []
    negative_results = []
    non_negative_pairs: list[dict] = []  # parallel to the RAGAS dataset rows, in order

    for qa in qa_pairs:
        question = qa["question"]
        ground_truth = qa["ground_truth_answer"]
        is_negative = qa.get("category") == "negative"

        result = answer_question(question)
        time.sleep(0.5)  # light rate-limit on LLM calls during eval

        if not is_negative:
            questions.append(question)
            answers.append(result.answer)
            ground_truths.append(ground_truth)
            contexts.append([c["text"] for c in result.citations] if result.citations else [""])
            non_negative_pairs.append(qa)

        if is_negative:
            negative_results.append({
                "question": question,
                "correctly_declined": not result.answerable,
                "answer_snippet": result.answer[:120],
            })

    ragas_dataset = Dataset.from_dict({
        "question": questions,
        "answer": answers,
        "ground_truth": ground_truths,
        "contexts": contexts,
    })

    # bypass_temperature=True: Sonnet 5 rejects the temperature param that ragas
    # normally appends to every metric call via LangchainLLMWrapper.
    eval_llm = LangchainLLMWrapper(
        ChatAnthropic(
            model=settings.llm_model,
            api_key=settings.anthropic_api_key,
            thinking={"type": "disabled"},
        ),
        bypass_temperature=True,
    )
    # Use local bge-small for answer_relevancy embeddings — no OpenAI key needed.
    eval_emb = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    )
    scores = evaluate(
        ragas_dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        llm=eval_llm,
        embeddings=eval_emb,
        raise_exceptions=False,
    )
    # _repr_dict holds pre-computed per-metric means (avoids .mean() on mixed-type DataFrame)
    scores_dict = dict(scores._repr_dict)

    # Per-row scores from the RAGAS result DataFrame — same row order as non_negative_pairs
    import math
    scores_df = scores.to_pandas()
    metric_cols = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    per_question = []
    for qa, (_, row) in zip(non_negative_pairs, scores_df.iterrows(), strict=True):
        entry: dict = {
            "id": qa.get("id", ""),
            "question": qa["question"],
            "category": qa.get("category", ""),
        }
        for col in metric_cols:
            val = row.get(col)
            entry[col] = (
                None
                if (val is None or (isinstance(val, float) and math.isnan(val)))
                else round(float(val), 4)
            )
        per_question.append(entry)

    decline_count = sum(1 for r in negative_results if r["correctly_declined"])
    decline_rate = decline_count / len(negative_results) if negative_results else None

    report = {
        "ragas_scores": scores_dict,
        "decline_rate": decline_rate,
        "n_questions": len(qa_pairs),
        "n_negative": len(negative_results),
        "negative_detail": negative_results,
        "per_question": per_question,
    }

    # Write raw JSON dump (gitignored intermediate artifact)
    raw_path = output_path.parent / f"eval_report_raw_{int(time.time())}.json"
    with raw_path.open("w") as f:
        json.dump(report, f, indent=2)
    print(f"Raw report: {raw_path}")

    # Fill in the markdown template
    template_path = EVAL_DIR / "eval_report_template.md"
    if template_path.exists():
        with template_path.open() as f:
            template = f.read()
        filled = template.format(
            faithfulness=f"{scores_dict.get('faithfulness', 'N/A'):.3f}",
            answer_relevance=f"{scores_dict.get('answer_relevancy', 'N/A'):.3f}",
            context_precision=f"{scores_dict.get('context_precision', 'N/A'):.3f}",
            context_recall=f"{scores_dict.get('context_recall', 'N/A'):.3f}",
            decline_rate=f"{decline_rate:.0%}" if decline_rate is not None else "N/A",
            n_questions=len(qa_pairs),
            n_negative=len(negative_results),
        )
        with output_path.open("w") as f:
            f.write(filled)
        print(f"Markdown report: {output_path}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(EVAL_DIR / "qa_dataset.json"))
    parser.add_argument("--output", default=str(EVAL_DIR / "eval_report.md"))
    args = parser.parse_args()
    run_eval(Path(args.dataset), Path(args.output))
