# TinyML Research Assistant — RAGAS Evaluation Report

## Summary

| Metric | Score |
|---|---|
| Faithfulness | 0.817 |
| Answer Relevance | 0.710 |
| Context Precision | 0.464 |
| Context Recall | 0.691 |
| Decline Rate (negatives) | 50% |

**Dataset**: 28 questions (4 deliberate negatives)

## Metric Definitions

- **Faithfulness**: fraction of answer claims that are directly supported by retrieved context (RAGAS LLM-based). Measures hallucination rate — 1.0 = zero hallucinations.
- **Answer Relevance**: cosine similarity between the question embedding and the answer embedding. Measures whether the answer addresses what was asked.
- **Context Precision**: of the retrieved chunks, what fraction are actually relevant? (signal-to-noise in retrieval)
- **Context Recall**: does the retrieved context cover all information needed to produce the ground-truth answer? (retrieval completeness)
- **Decline Rate**: percentage of "negative" questions (outside corpus scope) that the system correctly refused to answer, rather than hallucinating.

## Interpretation Notes

### ⚠ No verified clean eval run exists against the post-chunking-fix corpus

Two eval runs were conducted after the chunking fix. Neither can be treated as a verified,
complete result. **No post-fix RAGAS numbers should be cited in any summary, README, resume,
or interview context until a clean re-run is completed.**

#### Run 1 — `eval_report_raw_1787638321.json` (Aug 25, 02:12) — provenance uncertain

- Produced with the old `run_eval.py` before per-question reporting was added; contains no
  `per_question` breakdown.
- No stdout log was captured, so we cannot confirm or rule out the same credit-exhaustion
  failure mode that was directly observed in Run 2.
- Its `answer_relevancy: 0.716` sits suspiciously close to Run 2's documented-contaminated
  `0.710`, rather than near the ~0.90 expected for a clean, complete run. This is
  **circumstantial evidence of the same failure mode — not confirmed**, but enough to disqualify
  this file as a verified clean result.
- `decline_rate: 0.75` (3/4 correctly declined) is plausible and internally consistent, but
  cannot be treated as authoritative without corroboration from a clean run.

#### Run 2 — `eval_report_raw_1787639642.json` (Aug 25, 02:34) — contamination confirmed

This run experienced Anthropic API credit exhaustion partway through the RAGAS metric
computation phase. RAGAS's internal grading calls started failing with
`AnthropicInvalidRequestError: credit balance too low` during the final batch of jobs.

**Affected questions and symptoms:**

| id | category | answer_relevancy | faithfulness | cause |
|---|---|---|---|---|
| m03 | multi_hop | 0.0 (artifactual) | 0.88 (ok) | answer_relevancy LLM call failed |
| m08 | multi_hop | 0.0 (artifactual) | 0.77 (ok) | answer_relevancy LLM call failed |
| c01 | comparison | 0.0 (artifactual) | null | both LLM calls failed |
| c02 | comparison | 0.99 (ok) | null | faithfulness LLM call failed |
| c03 | comparison | 0.0 (artifactual) | null | both LLM calls failed |
| c04 | comparison | 0.0 (artifactual) | null | both LLM calls failed |

RAGAS returns 0.0 (not null) when its answer_relevancy synthetic-question generation fails and
`raise_exceptions=False` is set. These are grading infrastructure failures, not low-quality
answers. **The reported 0.710 answer_relevancy aggregate is not credible and should not be
cited.** Excluding the 5 artifactually-zeroed questions, the remaining 19 questions average
~0.896, consistent with the pre-fix run (0.912) and within normal LLM run-to-run variance.

### What can be stated with confidence

- The chunking fix (structural header detection + Roman numeral section support) corrected
  content loss and mislabeling in 13 of 15 papers. That is a code-level fact, verified by the
  before/after audit scripts, independent of any eval run.
- The pre-chunking-fix eval (`eval_report_PRECHUNKFIX.md`) reported `decline_rate: 25%` (1/4).
  Both post-fix runs show higher decline rates (0.75 and 0.50 respectively), suggesting a
  genuine improvement, but the inconsistency between the two runs means this cannot be stated
  as a confirmed delta yet.
- No post-fix metric (faithfulness, answer_relevancy, context_precision, context_recall) should
  be cited as a final number anywhere — README, resume, or interview — until a clean re-run
  with a full API budget and captured stdout log confirms the results.

### Required next step

Re-run the full 28-question eval with sufficient API budget to complete all 96 RAGAS grading
jobs cleanly, with stdout captured. Verify: no `AnthropicInvalidRequestError` or `TimeoutError`
lines appear in the log, and all 24 non-negative `per_question` entries have non-null,
non-zero scores for all four metrics. Only then should any aggregate be cited.

## Raw Scores

See `eval_report_raw_*.json` in this directory for per-question breakdown.
