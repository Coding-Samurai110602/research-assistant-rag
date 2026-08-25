# TinyML Research Assistant — RAGAS Evaluation Report

## Summary

| Metric | Score |
|---|---|
| Faithfulness | 0.840 |
| Answer Relevance | 0.674 |
| Context Precision | 0.445 |
| Context Recall | 0.688 |
| Decline Rate (negatives) | 50% |

**Dataset**: 28 questions (4 deliberate negatives)

## Metric Definitions

- **Faithfulness**: fraction of answer claims that are directly supported by retrieved context (RAGAS LLM-based). Measures hallucination rate — 1.0 = zero hallucinations.
- **Answer Relevance**: cosine similarity between the question embedding and the answer embedding. Measures whether the answer addresses what was asked.
- **Context Precision**: of the retrieved chunks, what fraction are actually relevant? (signal-to-noise in retrieval)
- **Context Recall**: does the retrieved context cover all information needed to produce the ground-truth answer? (retrieval completeness)
- **Decline Rate**: percentage of "negative" questions (outside corpus scope) that the system correctly refused to answer, rather than hallucinating.

## Interpretation Notes

**answer_relevancy = 0.0 on 6/24 non-negative questions (m05, m06, m07, m08, c01, c03) is a real, understood property of the system, not a measurement failure.**

These six questions are all `multi_hop` or `comparison` category. The RAGAS `answer_relevancy` metric works by asking the grader LLM to generate a reverse question from the RAG answer, then classify whether that answer is "noncommittal" (evasive, vague, or ambiguous). When all three paraphrases in a single scoring call are marked `noncommittal=1`, the metric returns exactly 0.0. No exception is suppressed, no API call fails, and no timeout fires — the grader is simply judging the answers as hedged.

The hedging is intentional. The system was deliberately tuned earlier in this project to be groundedness-first and avoid overclaiming beyond retrieved evidence; on multi-hop and comparison questions, it appropriately adds epistemic caveats ("a direct comparison is not fully supported by the available context…", "the retrieved papers do not provide a direct head-to-head measurement…"). The RAGAS metric penalises exactly this style.

It is unknown whether this hedging behaviour is new to the post-fix corpus (one hypothesis: the chunking fix restored more complete context, giving the model more evidence to qualify its claims against) or was already present pre-fix and simply not visible — the pre-fix eval run predates per-question score logging, so there is no per-question `answer_relevancy` breakdown from that run to compare against. Both are plausible; neither can be confirmed from available data.

Cross-run stability confirms this is semantic, not probabilistic noise: **m08, c01, and c03 reproduce as 0.0 identically across two separate eval runs**, while the remaining three (m05, m06, m07) sit near the noncommittal boundary and can flip depending on LLM temperature.

**Reliable metrics for multi_hop/comparison questions**: use `faithfulness`, `context_precision`, and `context_recall`. These scores are healthy on the same six questions (faithfulness 0.71–0.95, context_recall up to 1.0 on c01 and m08), confirming retrieval and grounding are working correctly.

**Do not treat this as a signal to make the system less cautious.** Removing epistemic caveats would improve `answer_relevancy` at the cost of faithfulness and factual honesty. `answer_relevancy` should be considered unreliable for `multi_hop` and `comparison` categories in this corpus.

## Raw Scores

See `eval_report_raw_*.json` in this directory for per-question breakdown.
