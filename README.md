# TinyML Research Assistant

A production-structured RAG system over 10–15 curated arXiv papers on TinyML and embedded ML deployment.

**Stack**: LangGraph · pgvector (PostgreSQL) · FastAPI · MCP Server (HTTP/SSE) · RAGAS eval · Docker · GitHub Actions CI

---

## Architecture

```
arXiv API
    │  (Stage 1)
    ▼
PDF Download + metadata.json
    │  (Stage 2)
    ▼
PyMuPDF extraction (two-column reading order) + section-aware chunker
    │  (Stage 3)
    ▼
BAAI/bge-small-en-v1.5 embeddings → PostgreSQL + pgvector (HNSW index)
    │  (Stage 4)
    ▼
┌─────────────────────── LangGraph StateGraph ─────────────────────────┐
│                                                                        │
│  analyze_query → retrieve → grade_relevance ──[retry loop]──┐         │
│                                       │                      │         │
│                                       ▼                      │         │
│                                   generate                   │         │
│                                       │                      │         │
│                                 check_groundedness           │         │
└─────────────────────────────────────────────────────────────┘─────────┘
    │
    ▼
core.answer_question()  ← single entry point
    │                    ← REST API and MCP server both call ONLY this
    ├── FastAPI POST /query
    └── MCP tool: query_research_papers
```

### LangGraph Graph — Node and Edge Map

| From | To | Condition |
|---|---|---|
| `analyze_query` | `retrieve` | always |
| `retrieve` | `grade_relevance` | always |
| `grade_relevance` | `increment_retry` | `len(graded) < 2` AND `retry_count < max_retries` |
| `grade_relevance` | `generate` | otherwise |
| `increment_retry` | `analyze_query` | always (loops back for query rewrite) |
| `generate` | `check_groundedness` | always |
| `check_groundedness` | END | always |

The conditional retry edge is the key LangGraph feature: if too few chunks survive relevance grading, the graph reformulates the query (using `QUERY_REWRITE_PROMPT`) and re-retrieves, up to `MAX_QUERY_RETRIES=2` times.

### Vector Index

HNSW index on `chunks.embedding` (`vector_cosine_ops`). Choice rationale (mirroring production experience from Geode co-op with spatial indexes):
- Sub-linear ANN query time without partition tuning (IVFFlat requires VACUUM before queries on a small corpus)
- Better recall at low k (k=6) than IVFFlat — IVFFlat can miss vectors that fall into the wrong partition
- Memory overhead acceptable for corpus of ~600–750 vectors

## Project Structure

```
src/research_assistant/
├── config.py                  # pydantic Settings
├── ingestion/
│   ├── arxiv_client.py        # arXiv API + PDF download, 3s rate limit
│   ├── pdf_parser.py          # PyMuPDF, two-column reading order fix
│   └── chunker.py             # section-boundary-first, 450-token max, 15% overlap
├── db/
│   ├── schema.sql             # papers + chunks tables, HNSW index, tsvector hybrid
│   ├── models.py              # SQLAlchemy ORM
│   └── vector_store.py        # insert, cosine search, hybrid search extension point
├── rag/
│   ├── state.py               # GraphState TypedDict
│   ├── prompts.py             # all prompt templates (centralised)
│   ├── nodes.py               # analyze_query, retrieve, grade_relevance, generate, check_groundedness
│   └── graph.py               # StateGraph definition + conditional retry edge
├── core.py                    # answer_question() — the ONLY RAG entry point
├── api/
│   ├── main.py                # FastAPI app
│   └── routes.py              # POST /query, GET /papers (import only from core.py)
├── mcp_server/
│   └── server.py              # MCP HTTP/SSE server (import only from core.py)
└── eval/
    ├── qa_dataset.json         # 28 hand-written ground-truth Q&A pairs
    ├── run_eval.py             # RAGAS harness
    └── eval_report_template.md
```

## Chunking Strategy

See `src/research_assistant/ingestion/chunker.py` for full rationale. Summary:

- **Section-boundary-first**: split at detected headers (numbered sections + known section names). Keeps all text for "Quantization Method" together — prevents retrieval misses where the query matches the header but the answer is in subsequent paragraphs.
- **Paragraph fallback**: within oversized sections, split at paragraph boundaries, not mid-sentence.
- **450-token target / 512 hard max**: both embedding models (bge-small and text-embedding-3-small) have 512-token context windows; exceeding silently truncates and degrades embedding quality.
- **15% overlap (~67 tokens)**: ensures cross-boundary sentences appear in at least one full chunk; kept below 20% to avoid near-duplicate pairs that inflate retrieval sets.
- **Captions**: standalone chunks, never merged with body.
- **References**: excluded entirely from retrieval corpus.

## Embedding Model

`BAAI/bge-small-en-v1.5` (local, via sentence-transformers). 384 dimensions. Rationale:
- Zero per-embedding API cost during development and CI
- ~62 NDCG@10 on BEIR benchmark — comparable to ada-002 on passage retrieval
- Fully offline; no latency spike from external API during RAGAS eval runs
- Switch to `text-embedding-3-small` (1536 dim) by setting `EMBEDDING_PROVIDER=openai` in `.env` and re-running ingestion — no code changes required

## Setup

### Prerequisites
- Docker + Docker Compose
- Python 3.11+
- `uv` (`pip install uv`)

### Local development

```bash
cp .env.example .env
# Edit .env — set OPENAI_API_KEY or leave EMBEDDING_PROVIDER=local

docker compose up -d postgres
bash scripts/setup_db.sh
uv pip install -e ".[dev]"
bash scripts/run_ingestion.sh   # downloads PDFs + embeds chunks

uvicorn research_assistant.api.main:app --reload
python -m research_assistant.mcp_server.server
```

### Run tests

```bash
pytest tests/ --ignore=tests/test_vector_store.py   # unit tests (no real DB)
pytest tests/test_vector_store.py                    # requires Docker
```

## MCP Server — Claude Desktop Config

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tinyml-research": {
      "url": "http://localhost:8001/sse"
    }
  }
}
```

Restart Claude Desktop. The tools `query_research_papers` and `list_ingested_papers` will appear.

## Evaluation

```bash
python -m research_assistant.eval.run_eval
```

Produces `src/research_assistant/eval/eval_report.md` with RAGAS scores (faithfulness, answer relevance, context precision, context recall) and manual decline rate on negative questions.

## Known Limitations

- **Figure/diagram label leakage**: PyMuPDF occasionally extracts axis labels, node labels, or block-diagram text from architecture figures as body-text blocks adjacent to the figure, rather than as part of the figure's caption. These short strings (e.g. "Fully-connected", "Convolution", "Pooling") embed into the vector store as body chunks. If a retrieval query returns an unexpectedly short, list-like result during Stage 6 eval, check whether it is a leaked diagram label rather than a real passage — and flag it in the eval report as a false-positive retrieval artifact of the PDF extraction layer, not of the RAG ranking.

## Deferred

- **AWS deployment**: deferred until Stage 7 local verification is complete. Resource needs (Postgres persistence, always-on vs. burst for MCP) are not yet characterized.
- **PDF corpus in git**: deferred pending arXiv redistribution licensing review and repo size assessment.
