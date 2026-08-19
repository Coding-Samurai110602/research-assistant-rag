"""
Vector store tests using testcontainers (real Postgres + pgvector).

Verifies insert + cosine similarity search returns expected nearest neighbor
for a synthetic embedding.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("testcontainers", reason="testcontainers not installed")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

from research_assistant.db.models import Base, Paper
from research_assistant.db.vector_store import insert_chunks, similarity_search

PGVECTOR_IMAGE = "pgvector/pgvector:pg16"
DIM = 4  # tiny synthetic embeddings for test speed


@pytest.fixture(scope="module")
def pg_engine():
    with PostgresContainer(PGVECTOR_IMAGE) as pg:
        engine = create_engine(pg.get_connection_url().replace("psycopg2", "psycopg"))
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        Base.metadata.create_all(engine)
        # Add vector column at test dimension
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE chunks ALTER COLUMN embedding TYPE vector({DIM})"))
            conn.commit()
        yield engine


@pytest.fixture
def session(pg_engine):
    # Wrap each test in a connection-level transaction that is always rolled back.
    # Using join_transaction_mode="create_savepoint" means the test's own
    # session.commit() calls only release a SAVEPOINT, not the outer transaction,
    # so teardown rollback undoes everything — including data committed by the test.
    conn = pg_engine.connect()
    trans = conn.begin()
    with Session(conn, join_transaction_mode="create_savepoint") as s:
        yield s
    trans.rollback()
    conn.close()


def _make_paper(session: Session) -> Paper:
    p = Paper(
        arxiv_id="2401.00001",
        title="Test TinyML Paper",
        authors=["Author A"],
        abstract="Abstract",
        categories=["cs.LG"],
        arxiv_url="https://arxiv.org/abs/2401.00001",
    )
    session.add(p)
    session.flush()
    return p


def test_insert_and_exact_neighbor(session):
    from research_assistant.ingestion.chunker import Chunk as ChunkData

    paper = _make_paper(session)

    # Three chunks with known embeddings; target_vec is closest to chunk 0
    target_vec = [1.0, 0.0, 0.0, 0.0]
    chunk_data = [
        ChunkData(
            text="Quantization for MCU deployment", arxiv_id="2401.00001",
            section_title="Method", page=1, chunk_index=0, block_type="body", token_count=5
        ),
        ChunkData(
            text="TinyML on Cortex-M4", arxiv_id="2401.00001",
            section_title="Experiments", page=2, chunk_index=1, block_type="body", token_count=4
        ),
        ChunkData(
            text="References and citations", arxiv_id="2401.00001",
            section_title="References", page=5, chunk_index=2, block_type="body", token_count=3
        ),
    ]
    # Synthetic embed function: chunk 0 → target_vec, others orthogonal
    vecs = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
    ]

    def fake_embed(texts: list[str]) -> list[list[float]]:
        return vecs[: len(texts)]

    insert_chunks(session, paper, chunk_data, fake_embed)
    session.commit()

    results = similarity_search(session, target_vec, top_k=1)
    assert len(results) == 1
    assert results[0].chunk_index == 0
    assert results[0].text == "Quantization for MCU deployment"


def test_top_k_returns_correct_count(session):
    from research_assistant.ingestion.chunker import Chunk as ChunkData

    paper = _make_paper(session)
    chunk_data = [
        ChunkData(
            text=f"Chunk {i}", arxiv_id="2401.00001",
            section_title="Sec", page=1, chunk_index=i, block_type="body", token_count=2
        )
        for i in range(5)
    ]

    def fake_embed(texts):
        n = len(texts)
        vecs = np.eye(DIM, DIM).tolist()
        return [vecs[i % DIM] for i in range(n)]

    insert_chunks(session, paper, chunk_data, fake_embed)
    session.commit()

    results = similarity_search(session, [1.0, 0.0, 0.0, 0.0], top_k=3)
    assert len(results) == 3
