# TinyML Research Assistant — Build Progress

_Last updated: 2026-08-19. New sessions: read this file first, then check `git log` and `git status` before touching anything._

---

## Stage Completion Status

### Stage 0 — Repo Bootstrap ✅ Reviewer-approved
- Full directory scaffold created (`src/research_assistant/{ingestion,db,rag,api,mcp_server,eval}/`)
- `pyproject.toml` using `uv`, Python 3.11
- `config.py` — pydantic `Settings` reading `.env`
- `docker-compose.yml` — postgres (pgvector/pgvector:pg16), api, mcp_server services with healthchecks
- `Dockerfile.api` and `Dockerfile.mcp` — multi-stage, non-root user, uv layer caching
- `.github/workflows/ci.yml` — ruff lint, mypy, pytest (unit, mocked), Docker image builds
- All placeholder source files and `tests/` stubs committed
- **Four pre-Stage-1 fixes applied and reviewer-approved:**
  1. `chunker.py` — overflow fix in overlap-carry branch (`safe_overlap = min(OVERLAP_TOKENS, max(0, MAX_TOKENS - len(para_tokens)))`)
  2. `chunker.py` — `_SECTION_HEADER_RE` wired as fallback header detector via `_is_untagged_header()`; confirmed to fire zero times on real corpus
  3. `test_mcp_server.py` — AST guard extended to catch `import X` (not just `from X import Y`); negative proof-of-fire test added
  4. `rag/state.py` — plain `list[RetrievedChunk]` annotations confirmed as replacement (not append) semantics; `test_retry_loop_replaces_not_accumulates_chunks` added to prove it with a live LangGraph graph

### Stage 1 — arXiv Ingestion ✅ Reviewer-approved
- 5 search queries run against arXiv API (3-second rate limit respected)
- 58 unique candidates surfaced, 15 selected by reviewer after sanity check
- All 15 PDFs downloaded to `data/raw_pdfs/` (gitignored; see open questions)
- `data/metadata.json` written with all required fields: `arxiv_id`, `title`, `authors`, `abstract`, `published`, `categories`, `arxiv_url`, `local_path`, `download_date`
- Integrity check: all 15 PDFs open cleanly with PyMuPDF, all ≥ 6 pages, no truncated downloads
- Total corpus: **15 papers, 206 pages**

**Approved corpus (arxiv_id → title):**
| arxiv_id | Title |
|---|---|
| 1801.06601v1 | CMSIS-NN: Efficient Neural Network Kernels for Arm Cortex-M CPUs |
| 1911.03314v3 | FANN-on-MCU: Open-Source Toolkit for Energy-Efficient NN Inference at Edge IoT |
| 2007.01348v1 | Efficient Neural Network Deployment for Microcontroller |
| 2010.11267v6 | MicroNets: NN Architectures for Deploying TinyML on Commodity Microcontrollers |
| 2105.13331v2 | Quantization and Deployment of Deep Neural Networks on Microcontrollers |
| 2211.17246v2 | Pex: Memory-efficient Microcontroller Deep Learning through Partial Execution |
| 2303.10702v1 | Evaluation of Convolution Primitives for Embedded NNs on 32-bit Microcontrollers |
| 2407.10734v2 | On-Device Training of Fully Quantized DNNs on Cortex-M Microcontrollers |
| 2512.09786v2 | TinyDéjàVu: Smaller RAM and Faster Inference with NNs on MCUs for Sensor Data |
| 2506.10851v1 | Energy-Efficient Deep Learning for Traffic Classification on Microcontrollers |
| 2603.15106v2 | PrototypeNAS: Rapid Design of DNNs for Microcontroller Units |
| 2106.10652v1 | TinyML: Analysis of Xtensa LX6 Microprocessor for NN Applications by ESP32 SoC |
| 2104.10645v1 | Measuring what Really Matters: Optimizing Neural Networks for TinyML |
| 2011.14325v1 | XpulpNN: Energy-Efficient QNN Inference on RISC-V IoT End Nodes _(borderline: RISC-V)_ |
| 2101.08744v3 | Enabling Large NNs on Tiny Microcontrollers with Swapping _(borderline: niche technique)_ |

### Stage 2 — PDF Parsing + Chunking ✅ Reviewer-approved
- `pdf_parser.py` — PyMuPDF extraction with two-column reading-order sort
- `chunker.py` — section-boundary-first, paragraph-fallback, 450-token max, 15% dynamic overlap
- Fallback header detector (`_is_untagged_header`) fires **zero times** on real corpus (all 15 papers have PyMuPDF-detectable headers)
- Fallback header trip log printed at end of `chunk_document` for eyeball verification; stays in for Stage 2 inspection, may be removed after Stage 6 eval confirms no misfires
- **Column-sort bug found and fixed during reviewer checkpoint** (see Decisions below)
- Final corpus: **709 chunks, 207,311 tokens**

---

## Non-Negotiables (Do Not Quietly Remove)

From the original build spec. Each must be verifiable in the final diff:

1. **Full-text PDF ingestion** — 15 real arXiv PDFs, not abstracts or toy strings. ✅ Done.
2. **Documented chunking strategy** — rationale written in `chunker.py` docstring, not just default settings. ✅ Done.
3. **pgvector inside real PostgreSQL** — not FAISS/Chroma. Schema at `db/schema.sql`, HNSW index named explicitly. ✅ Done.
4. **LangGraph with real conditional retry edge** — `rag/graph.py` defines a 6-node `StateGraph` with `grade_relevance → increment_retry → analyze_query` loop, max `MAX_QUERY_RETRIES=2`. Stage 4 pending.
5. **RAGAS evaluation harness** — 28 hand-written Q&A pairs (12 factual / 8 multi-hop / 4 comparison / 4 negatives), real numeric report. Stage 6 pending.
6. **FastAPI REST + MCP server both calling `core.answer_question()` only** — zero duplicated retrieval logic. Enforced by `test_mcp_server_imports_only_from_core` (AST check, both import styles). Stages 5/5.5 pending.
7. **Docker + GitHub Actions CI** — same rigor as prior project. Stage 7 pending.
8. **AWS deployment explicitly deferred** — do not provision anything until after Stage 7.

---

## Decisions Made and Why

### Chunking strategy (`ingestion/chunker.py`)
- **Section-boundary-first**: primary split at detected headers. Academic papers are sectioned; keeping "Quantization Method" together avoids retrieval misses where the query matches the header but the answer is paragraphs away.
- **Token limit: 450 / hard cap 512**: both `BAAI/bge-small-en-v1.5` and `text-embedding-3-small` have 512-token windows; exceeding silently truncates. 450 gives 12% headroom.
- **Dynamic safe overlap**: `safe_overlap = min(OVERLAP_TOKENS, max(0, MAX_TOKENS - len(para_tokens)))`. Fixed at 67 tokens (15%) but shrinks when the incoming paragraph is large enough that full overlap would overflow the cap. Pre-Stage-1 bug; fixed and regression-tested with a real 420-token paragraph fixture.
- **Captions**: standalone chunks, never merged into body. Dense, self-contained, high-signal for factual queries.
- **References**: excluded entirely. Citation strings embed as author-name/venue noise and pollute nearest-neighbor results.

### Embedding model (`db/vector_store.py`)
- **Model**: `BAAI/bge-small-en-v1.5` via `sentence-transformers` (local, no API cost)
- **Dimension**: 384
- **Rationale**: ~62 NDCG@10 on BEIR benchmark (comparable to ada-002 on passage retrieval), fully offline (no latency spike or API cost during RAGAS eval runs), 1/4 the dimension of `text-embedding-3-small` → faster ANN queries
- **Switch path**: set `EMBEDDING_PROVIDER=openai` in `.env` → `vector_store._get_embedding_fn()` returns OpenAI client instead; re-run ingestion script. No code changes required.
- **Schema impact**: `chunks.embedding` is `vector(384)`. Changing to 1536 requires `ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1536)` and re-ingestion.

### HNSW index (`db/schema.sql`)
```sql
CREATE INDEX chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```
- **Why HNSW over IVFFlat**: sub-linear ANN time without partition tuning or VACUUM-before-query requirement. Better recall at low k (k=6) since IVFFlat can miss vectors in the wrong partition.
- **m=16**: standard starting value; controls graph connectivity. Higher → better recall, more memory.
- **ef_construction=64**: standard starting value; controls build-time quality. Increase to 128 for a larger corpus.
- Explicitly called out in README as a callback to Geode co-op spatial index experience (same HNSW tradeoff: memory overhead justified by recall gains).

### Two-column PDF reading-order sort (`ingestion/pdf_parser.py`)
- **Bug found during Stage 2 reviewer checkpoint**: original y-merge interleaved left and right column blocks by raw y-coordinate, producing `RIGHT(y=421) → LEFT(y=434) → RIGHT(y=432)` instead of full left column then full right column.
- **Fix**: section-based ordering. Wide blocks (x-span > 60% of page width) act as section dividers. Within each section, all left-column blocks are emitted top-to-bottom, then all right-column blocks top-to-bottom.
- **Thresholds are dynamic per page per block** — computed from `page.rect.width` for each page, no hardcoded values. Midpoint = `page_width / 2`; wide threshold = `page_width * 0.6`. A block spanning >60% of the page is classified WIDE regardless of whether it crosses the midpoint.
- **Per-block, not per-page**: the wide/left/right decision is made independently for each block. On a single page, the Abstract block (73.2% span) is WIDE while the body paragraph below it (38.5% span) is LEFT — handled in the same loop, same call.
- **Chunk count impact**: 716 → 709 (−7 chunks). Correct column ordering grouped text that the interleaving had been splitting across spurious section boundaries.
- **CMSIS-NN finding**: its body text is extracted as wide-span blocks by PyMuPDF (the IEEE column gutter is narrow enough that PyMuPDF merges adjacent line segments into single wide blocks). No genuine narrow two-column sort case in CMSIS-NN; Pex (2211.17246v2) provided the real two-column verification.

---

## Known Limitations (also in README.md)

- **Figure/diagram label leakage**: PyMuPDF occasionally extracts axis labels, node labels, or block-diagram text (e.g. "Fully-connected", "Convolution", "Pooling" from architecture figures) as body-text blocks. These embed as body chunks. If a retrieval query returns an unexpectedly short, list-like result during Stage 6 eval, check whether it is a leaked diagram label — flag it as a PDF extraction artifact, not a RAG ranking failure.

---

## Current Corpus Statistics (post-Stage-2, post-column-sort-fix)

| Metric | Value |
|---|---|
| Papers | 15 |
| Total pages | 206 |
| Total chunks | **709** |
| Total tokens | **207,311** |
| Min / max chunk tokens | 7 / 450 |
| Mean / median chunk tokens | 292.4 / 355 |
| Stdev | 153.0 |
| body chunks | 557 (78.6%) |
| caption chunks | 125 (17.6%) |
| table chunks | 27 (3.8%) |
| Chunks exceeding MAX_TOKENS (450) | **0** |
| Fallback header fires | **0** |

Token histogram (verified with `safe_overlap` fix in place on real data):
```
[  0– 50):  102
[ 50–100):   41
[100–150):   23
[150–200):   27
[200–250):   37
[250–300):   53
[300–350):   64
[350–400):  102
[400–450):  245   ← bulk of chunks near ceiling, none above it
[450–512):   15   ← sitting exactly at 450, not above
```

---

## Stage 3 — Postgres/pgvector Embedding Insertion ✅ Reviewer-approved

- `docker compose up -d postgres` — pulled `pgvector/pgvector:pg16`; schema applied automatically via `docker-entrypoint-initdb.d/01_schema.sql` mount.
- **pgvector extension**: v0.8.6 active; `vector(384)` column confirmed.
- **HNSW index**: `chunks_embedding_hnsw_idx USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)` — confirmed in `pg_indexes`.
- **GIN index**: `chunks_tsv_idx USING gin (tsv)` — confirmed.
- Ingestion run: all 15 papers processed, 709 chunks inserted with 384-dim embeddings.
- **NUL-byte fix applied during this stage**: PyMuPDF extracts occasional `\x00` bytes from PrototypeNAS (2603.15106v2). Fixed in `pdf_parser.py` line 155: `text = (bd["text"] or "").replace("\x00", "").strip()`. Chunk count unaffected (still 709).
- **Verification queries** (all passed):
  - `SELECT COUNT(*) FROM papers` = **15**
  - `SELECT COUNT(*) FROM chunks` = **709**
  - `SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL` = **709**
- **Synthetic similarity search**: query "ARM Cortex-M neural network inference" → top result is CMSIS-NN (`1801.06601v1`) Conclusion section, followed by Cortex-M training paper (`2407.10734v2`). Nearest-neighbor retrieval is semantically correct.

---

## Open Questions / Revisit Later

### AWS deployment target
- **Deferred until after Stage 7** (local Docker verified end-to-end)
- Decision needed: EKS vs ECS/Lambda vs EC2
- Key unknown: does the MCP server need to be always-on (ECS/EKS) or can it tolerate cold starts (Lambda)? Measure from real usage during Stage 8 frontend testing before committing.
- Do not provision any AWS resources until this decision is made with the reviewer.

### Raw PDF corpus in git
- Currently gitignored: `data/raw_pdfs/*.pdf`
- `data/metadata.json` is trackable (and untracked but clean in git status)
- Decision needed: arXiv PDFs are open-access but re-hosting at scale raises redistribution questions; repo size would be ~26 MB for 15 PDFs (acceptable for a portfolio project)
- Revisit once ingestion pipeline is confirmed stable so re-running it from `metadata.json` is always an option

### Fallback header trip log
- `_is_untagged_header` logging in `chunk_document` is currently active (prints to stdout on any fire)
- Zero fires on current 15-paper corpus — all headers are PyMuPDF-detectable
- **Revisit after Stage 6 eval**: if the log stays silent through eval, consider removing the print or converting to a `logging.debug` call to keep production output clean

### Stage 6 RAGAS eval was run against a since-fixed corpus
- The `eval_report.md` numbers (faithfulness, answer relevance, context precision, context recall) were generated against a corpus with a since-fixed chunking bug: header misclassification caused content loss or mislabeling in 13 of 15 papers — fused heading+body blocks were classified as pure headers, silently swallowing prose into section-title strings, and Roman numeral section headers (IEEE format: `I. INTRODUCTION`, `II. RELATED WORK`, etc.) were completely undetected by `_HEADER_RE`, causing entire papers to be labeled under the abstract section rather than their real sections.
- The bug was fixed via structural heading detection (length ≤ 120 chars gate in `_classify_block`) and Roman numeral support added to `_HEADER_RE` and `_SECTION_HEADER_RE`. The corrected corpus has **725 chunks** (vs. the original 709 used during eval).
- The eval has not yet been re-run against the corrected, re-ingested corpus. **Re-running the full RAGAS eval is a recommended next step before treating `eval_report.md`'s numbers as final or representative.**

---

## File Map (key files a new session should read first)

```
src/research_assistant/
  config.py                    # pydantic Settings — all env vars in one place
  core.py                      # answer_question() — THE ONLY RAG entry point
  ingestion/
    pdf_parser.py              # parse_pdf(), _sort_blocks_reading_order() (section-sort fix here)
    chunker.py                 # chunk_document(), _chunk_text_with_overlap(), safe_overlap fix
  db/
    schema.sql                 # Postgres DDL — apply before Stage 3 ingestion
    vector_store.py            # insert_paper(), insert_chunks(), similarity_search()
  rag/
    state.py                   # GraphState TypedDict — replacement semantics, documented
    graph.py                   # build_graph() — 6-node StateGraph, conditional retry edge
    nodes.py                   # analyze_query, retrieve, grade_relevance, generate, check_groundedness
    prompts.py                 # all 5 prompt templates
  api/routes.py                # POST /query, GET /papers — imports only from core.py
  mcp_server/server.py         # MCP HTTP/SSE — imports only from core.py
  eval/
    qa_dataset.json            # PLACEHOLDER — 28 real Q&A pairs needed in Stage 6
    run_eval.py                # RAGAS harness — ready to run once QA pairs are written
tests/
  test_chunker.py              # 8 tests incl. overflow regression + untagged-header fallback
  test_graph.py                # node unit tests + conditional-edge + retry-replacement proof
  test_mcp_server.py           # AST import guard (both styles) + negative proof-of-fire
  test_api.py                  # TestClient, all external calls mocked
  test_vector_store.py         # testcontainers — requires Docker, skipped in CI unit run
data/
  metadata.json                # 15 papers, all fields populated — source of truth for ingestion
  raw_pdfs/                    # gitignored — re-download with scripts/run_ingestion.sh if needed
```
