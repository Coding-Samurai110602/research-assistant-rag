"""
pgvector CRUD and similarity search.

Embedding model choice (documented here per Stage 3 requirement):
  Provider: BAAI/bge-small-en-v1.5 via sentence-transformers (local, no API cost)
  Dimension: 384
  Rationale:
    - Zero per-embedding API cost during rapid iteration; switch to
      text-embedding-3-small (dim=1536) for production by updating
      EMBEDDING_PROVIDER=openai in .env and re-running ingestion.
    - bge-small-en-v1.5 scores ~62 NDCG@10 on BEIR benchmark, comparable to
      ada-002 on passage retrieval tasks, at 1/4 the dimension → faster ANN.
    - Runs fully offline; no latency spike from external API during eval.
  Extension point: see `_get_embedding_fn()` — swapping providers requires
  only changing config, not rewriting this module.
"""

from __future__ import annotations

import functools
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from research_assistant.config import settings
from research_assistant.db.models import Base, Chunk, Paper
from research_assistant.ingestion.arxiv_client import PaperMetadata
from research_assistant.ingestion.chunker import Chunk as ChunkData


class EmbeddingFn(Protocol):
    def __call__(self, texts: list[str]) -> list[list[float]]: ...


@functools.lru_cache(maxsize=1)
def _get_embedding_fn() -> EmbeddingFn:
    """
    Return the embedding callable for the configured provider.

    Decorated with lru_cache so the SentenceTransformer (local path) is loaded
    from disk exactly once per process — not once per query. Without caching,
    every call to retrieve() triggered a full model reload, which caused the
    'Loading weights' progress bar and ~1-2s latency on each request.
    """
    if settings.embedding_provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)

        def openai_embed(texts: list[str]) -> list[list[float]]:
            resp = client.embeddings.create(model="text-embedding-3-small", input=texts)
            return [d.embedding for d in resp.data]

        return openai_embed
    else:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("BAAI/bge-small-en-v1.5")

        def local_embed(texts: list[str]) -> list[list[float]]:
            vecs = model.encode(texts, normalize_embeddings=True)
            return vecs.tolist()

        return local_embed


def get_engine():
    return create_engine(settings.database_url, pool_pre_ping=True)


def ensure_schema(engine) -> None:
    Base.metadata.create_all(engine)


def insert_paper(session: Session, meta: PaperMetadata) -> Paper:
    existing = session.execute(
        select(Paper).where(Paper.arxiv_id == meta.arxiv_id)
    ).scalar_one_or_none()
    if existing:
        return existing

    paper = Paper(
        arxiv_id=meta.arxiv_id,
        title=meta.title,
        authors=meta.authors,
        abstract=meta.abstract,
        published=(
            datetime.fromisoformat(meta.published.replace("Z", "+00:00"))
            if meta.published
            else None
        ),
        categories=meta.categories,
        arxiv_url=meta.arxiv_url,
        local_path=meta.local_path,
        download_date=datetime.fromisoformat(meta.download_date) if meta.download_date else None,
        created_at=datetime.now(UTC),
    )
    session.add(paper)
    session.flush()
    return paper


def insert_chunks(
    session: Session,
    paper: Paper,
    chunk_data: list[ChunkData],
    embed_fn: EmbeddingFn,
    batch_size: int = 32,
) -> list[Chunk]:
    db_chunks = []
    texts = [c.text for c in chunk_data]

    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i : i + batch_size]
        batch_vecs = embed_fn(batch_texts)
        batch_pairs = zip(chunk_data[i : i + batch_size], batch_vecs, strict=True)
        for _j, (cd, vec) in enumerate(batch_pairs):
            db_chunks.append(
                Chunk(
                    paper_id=paper.id,
                    arxiv_id=cd.arxiv_id,
                    chunk_index=cd.chunk_index,
                    section_title=cd.section_title,
                    page=cd.page,
                    block_type=cd.block_type,
                    text=cd.text,
                    token_count=cd.token_count,
                    embedding=vec,
                    created_at=datetime.now(UTC),
                )
            )

    session.bulk_save_objects(db_chunks)
    session.flush()
    return db_chunks


def similarity_search(
    session: Session,
    query_vec: list[float],
    top_k: int = 6,
    arxiv_ids: list[str] | None = None,
) -> list[Chunk]:
    """
    Cosine similarity top-k search via pgvector <=> operator.
    Optional arxiv_ids filter restricts search to specific papers.
    """
    stmt = (
        select(Chunk)
        .order_by(Chunk.embedding.cosine_distance(query_vec))
        .limit(top_k)
    )
    if arxiv_ids:
        stmt = stmt.where(Chunk.arxiv_id.in_(arxiv_ids))

    return list(session.execute(stmt).scalars().all())


def hybrid_search(
    session: Session,
    query_vec: list[float],
    keyword: str,
    top_k: int = 6,
) -> list[Chunk]:
    """
    Hybrid search: cosine ANN filtered by tsvector keyword match.
    Extension point: not required for v1 but cleanly available here.
    """
    stmt = (
        select(Chunk)
        .where(text("tsv @@ plainto_tsquery('english', :kw)").bindparams(kw=keyword))
        .order_by(Chunk.embedding.cosine_distance(query_vec))
        .limit(top_k)
    )
    return list(session.execute(stmt).scalars().all())


def list_papers(session: Session) -> list[Paper]:
    return list(session.execute(select(Paper)).scalars().all())
