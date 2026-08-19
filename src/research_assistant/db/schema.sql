-- Research Assistant RAG — PostgreSQL schema
-- Requires pgvector extension (available in pgvector/pgvector Docker image)

CREATE EXTENSION IF NOT EXISTS vector;

-- ── Papers ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS papers (
    id            SERIAL PRIMARY KEY,
    arxiv_id      TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    authors       TEXT[] NOT NULL,
    abstract      TEXT,
    published     TIMESTAMPTZ,
    categories    TEXT[],
    arxiv_url     TEXT,
    local_path    TEXT,
    download_date TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ── Chunks ────────────────────────────────────────────────────────────────────
-- embedding dimensionality:
--   text-embedding-3-small → 1536
--   BAAI/bge-small-en-v1.5 → 384
-- The column size is set by the ingestion pipeline at first insert via ALTER TABLE
-- if it differs; here we default to 384 (local model, no API cost during iteration).
-- To switch to 1536, run: ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1536);

CREATE TABLE IF NOT EXISTS chunks (
    id            SERIAL PRIMARY KEY,
    paper_id      INT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    arxiv_id      TEXT NOT NULL,          -- denormalised for fast filtering without join
    chunk_index   INT NOT NULL,
    section_title TEXT,
    page          INT,
    block_type    TEXT DEFAULT 'body',    -- 'body' | 'caption' | 'table'
    text          TEXT NOT NULL,
    token_count   INT,
    embedding     vector(384),            -- matches BAAI/bge-small-en-v1.5
    created_at    TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (paper_id, chunk_index)
);

-- ── HNSW index on cosine similarity ──────────────────────────────────────────
-- Deliberate design choice (see README § Vector Index):
--   HNSW (Hierarchical Navigable Small World) provides sub-linear ANN query time
--   (O(log n)) vs. IVFFlat's partition-based approach, at the cost of higher
--   build memory. For a corpus of 10–15 papers × ~50 chunks each (≈600–750
--   vectors), either would be fast, but HNSW is preferred because:
--     1. No need to tune nlist (number of partitions) or run VACUUM before queries.
--     2. Better recall at low k (k=6) since HNSW's graph traversal doesn't miss
--        vectors that fall into the wrong IVFFlat partition.
--     3. Directly parallels production usage (Geode co-op used HNSW-style indexes
--        on spatial data; same tradeoff: memory overhead justified by recall).
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- tsvector column for optional hybrid (vector + keyword) search
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED;

CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING GIN (tsv);
