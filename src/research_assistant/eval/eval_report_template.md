# TinyML Research Assistant — RAGAS Evaluation Report

## Summary

| Metric | Score |
|---|---|
| Faithfulness | {faithfulness} |
| Answer Relevance | {answer_relevance} |
| Context Precision | {context_precision} |
| Context Recall | {context_recall} |
| Decline Rate (negatives) | {decline_rate} |

**Dataset**: {n_questions} questions ({n_negative} deliberate negatives)

## Metric Definitions

- **Faithfulness**: fraction of answer claims that are directly supported by retrieved context (RAGAS LLM-based). Measures hallucination rate — 1.0 = zero hallucinations.
- **Answer Relevance**: cosine similarity between the question embedding and the answer embedding. Measures whether the answer addresses what was asked.
- **Context Precision**: of the retrieved chunks, what fraction are actually relevant? (signal-to-noise in retrieval)
- **Context Recall**: does the retrieved context cover all information needed to produce the ground-truth answer? (retrieval completeness)
- **Decline Rate**: percentage of "negative" questions (outside corpus scope) that the system correctly refused to answer, rather than hallucinating.

## Interpretation Notes

<!-- Fill in after running eval — flag any metric that looks suspiciously perfect (1.0) -->

## Raw Scores

See `eval_report_raw_*.json` in this directory for per-question breakdown.
