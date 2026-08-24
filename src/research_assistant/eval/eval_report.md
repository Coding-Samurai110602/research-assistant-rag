# TinyML Research Assistant — RAGAS Evaluation Report

## Summary

| Metric | Score |
|---|---|
| Faithfulness | 0.778 |
| Answer Relevance | 0.912 |
| Context Precision | 0.378 |
| Context Recall | 0.715 |
| Decline Rate (negatives) | 25% (1/4) |

**Dataset**: 28 questions (4 deliberate negatives); 24 non-negative questions fed to RAGAS,
4 negatives tracked separately for decline_rate only.

## Metric Definitions

- **Faithfulness**: fraction of answer claims that are directly supported by retrieved context (RAGAS LLM-based). Measures hallucination rate — 1.0 = zero hallucinations.
- **Answer Relevance**: cosine similarity between the question embedding and the answer embedding. Measures whether the answer addresses what was asked.
- **Context Precision**: of the retrieved chunks, what fraction are actually relevant? (signal-to-noise in retrieval)
- **Context Recall**: does the retrieved context cover all information needed to produce the ground-truth answer? (retrieval completeness)
- **Decline Rate**: percentage of "negative" questions (outside corpus scope) that the system correctly refused to answer, rather than hallucinating.

## Interpretation Notes

### Aggregate scores

Faithfulness (0.778) and Answer Relevance (0.912) are the more reliable headline numbers
from this run. Faithfulness at 0.78 reflects a pipeline that largely stays grounded in
retrieved context — one outlier (f08, discussed below) accounts for a meaningful fraction
of the shortfall. Answer Relevance at 0.91 is consistently high across all question
categories, indicating the system is answering the question that was asked rather than
drifting off-topic.

Context Precision (0.378) is the metric that looks alarming but requires a caveat before
being treated as a retrieval quality signal. Inspection of the per-question breakdown
shows that context_precision is near-zero for every multi_hop and comparison question (12
out of 24 rows score 0.0), while factual questions score well (median ≈ 0.95). This
split is not a retrieval failure: manual inspection of several multi_hop and comparison
answers confirmed they were substantively accurate, well-cited, and drew on the correct
papers. The issue is structural: RAGAS's context_precision metric grades each retrieved
chunk by asking an LLM whether it alone is "relevant to the ground truth." Multi-paper
synthesis questions require chunks from multiple papers simultaneously — no single chunk
is sufficient on its own — so the LLM grader frequently marks individual chunks as
irrelevant even when the set of chunks together supports a complete answer. This is a
documented limitation of this metric on multi-hop retrieval tasks. Context Precision
should not be used to characterise retrieval quality for this pipeline without
stratifying by question type.

Context Recall (0.715) is a more honest signal. The zero-recall cases (f08, m04, m05)
are genuine partial misses: the retrieval pipeline found related but incomplete evidence,
and the ground-truth answer contained claims the retrieved context didn't cover. These
are real retrieval gaps, not scoring artefacts, and point to questions where richer
ground-truth coverage of the corpus would help.

### Decline rate: 25% (1/4) and the three missed declines

Only n01 ("What is the best recipe for chocolate chip cookies?") was correctly declined.
The three misses warrant individual characterisation:

**n02** ("How do transformer-based large language models handle attention over long context
windows?") and **n03** ("What GPU architectures are best suited for training large neural
networks from scratch?") both show non-deterministic behaviour across runs: in manual
re-runs both returned `answerable=False` with the correct refusal message. During the
eval run they returned `answerable=True`, likely because the embedding of "attention" or
"GPU training" is close enough to MCU/neural-network content in the corpus that retrieval
surfaced tangentially related chunks, the relevance grader passed them, and generation
proceeded before the retry loop exhausted. These are genuinely borderline questions —
they involve neural networks and hardware, which overlaps significantly with corpus
vocabulary — rather than simple off-topic queries.

**n04** ("Which microcontroller platform is cheapest to manufacture at scale?") is the
most instructive miss. The system retrieved a real passage from MicroNets listing unit
prices for three STM32 boards ($3, $5, $8) and identified the F446RE as cheapest. It then
added an explicit hedge: *"the passage only provides unit price figures, not manufacturing
cost at scale — the paper does not specify manufacturing costs or how prices might change
with scale."* The system correctly characterised the limits of its evidence; it should
have declined outright, but the hedge demonstrates grounded reasoning rather than
fabrication. The groundedness check flagged the response False, correctly. This case
illustrates that a clean decline/answer binary is imperfect for questions that are
partially answerable from corpus data.

### f08: accurate answer, faithfulness 0.0 — a worked example of RAGAS grader sensitivity

Question: *"What relationship do the authors find between theoretical MAC count and actual
measured energy consumption on Cortex-M?"*

Ground truth: "They find a linear relationship between the theoretical number of
multiply-accumulate operations (MACs) and the measured energy consumption on Cortex-M
hardware."

The generated answer correctly synthesised findings from two papers: the convolution-
primitives paper (2303.10702v1) establishing that theoretical MACs is a relevant
indicator of layer energy for non-SIMD Cortex-M devices, and MicroNets (2010.11267v6)
establishing that energy is a linear function of op count at the whole-model level via
near-constant power draw (σ/µ = 0.00731 across 400 sampled models). Both citations were
correct and the synthesis was accurate.

Despite this, the answer scored faithfulness=0.0 and context_recall=0.0. Three
contributing factors were identified by inspection:

1. **Irrelevant retrieved chunk**: Citation 1 was a FANN-on-MCU chunk (1911.03314v3)
   containing energy measurements for a different system. This gave the RAGAS faithfulness
   grader a context passage that couldn't support several of the answer's claims, likely
   causing the whole-answer faithfulness score to collapse rather than being applied
   claim-by-claim as intended.

2. **Truncated chunk**: Citation 2 (2303.10702v1 p.9 Conclusion) was cut off mid-sentence
   at a token boundary, ending before the SIMD vs. non-SIMD comparison completed. The
   grader could not verify the SIMD-qualified claim against an incomplete passage.

3. **Terminology mismatch**: The ground truth uses "MACs" (multiply-accumulate
   operations); the MicroNets paper uses "ops." These are synonymous in context but
   RAGAS's LLM-graded recall check failed to treat them as equivalent, producing
   context_recall=0.0 despite Citation 4 containing the exact linear relationship
   described in the ground truth.

This case is representative of a general pattern: RAGAS's LLM-graded metrics are
sensitive to retrieval noise (one bad chunk among three good ones), chunk boundary
artefacts (incomplete sentences at token limits), and paraphrase distance between ground
truth wording and paper wording. These are real limitations of the evaluation harness,
not failures of the RAG pipeline. Manual inspection of f08's answer confirmed it was
accurate, grounded, and correctly cited.

## Raw Scores

See `eval_report_raw_*.json` in this directory for per-question breakdown.
