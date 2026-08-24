"""Graph state shared across all LangGraph nodes."""

from __future__ import annotations

from typing import Literal

from typing_extensions import TypedDict


class RetrievedChunk(TypedDict):
    id: int
    arxiv_id: str
    section_title: str
    page: int
    block_type: str
    text: str
    token_count: int
    distance: float


class Citation(TypedDict):
    arxiv_id: str
    title: str
    section_title: str
    page: int
    chunk_id: int


class GraphState(TypedDict):
    # Input
    original_query: str

    # Set by analyze_query
    query_type: Literal["factual", "multi_hop", "comparison", "negative"]
    rewritten_query: str

    # Set by retrieve — REPLACEMENT semantics (deliberate)
    # LangGraph uses dict.update() for plain TypedDict fields: when retrieve returns
    # {"retrieved_chunks": [new list]}, the old value is OVERWRITTEN, not appended.
    # Append behavior would require Annotated[list, operator.add] reducers.
    # We explicitly do NOT use reducers here so the retry loop (grade → retry →
    # retrieve again) always starts with a fresh chunk set from the new query,
    # never accumulating stale results from prior passes.
    retrieved_chunks: list[RetrievedChunk]

    # Set by grade_relevance — REPLACEMENT semantics (same reason as above)
    graded_chunks: list[RetrievedChunk]

    # Set by generate
    answer: str
    citations: list[Citation]

    # Set by check_groundedness
    is_grounded: bool
    groundedness_note: str

    # Control
    retry_count: int
    answerable: bool  # False → system declined (negative / no relevant chunks)
    error: str | None
