"""
LangGraph StateGraph — the explicit orchestration layer.

Graph structure (nodes and edges):

  analyze_query ──────────────────────────────────────────┐
        │                                                  │ (retry: rewrite query)
        ▼                                                  │
     retrieve                                              │
        │                                                  │
        ▼                                                  │
  grade_relevance ──[too few relevant chunks + retries left]─┘
        │
        │ [sufficient chunks OR retries exhausted]
        ▼
     generate
        │
        ▼
  check_groundedness
        │
        ▼
       END

Conditional edge logic (after grade_relevance):
  - If len(graded_chunks) < MIN_GRADED and retry_count < MAX_RETRIES → loop back
    to analyze_query, which (on retry_count > 0) uses QUERY_REWRITE_PROMPT.
  - Otherwise → generate.

This conditional retry edge is the key LangGraph feature that distinguishes
this graph from a linear chain: the graph can traverse analyze_query →
retrieve → grade_relevance → analyze_query multiple times before committing
to a generation, giving the system a chance to reformulate before giving up.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, StateGraph

from research_assistant.config import settings
from research_assistant.rag.nodes import (
    analyze_query,
    check_groundedness,
    generate,
    grade_relevance,
    retrieve,
)
from research_assistant.rag.state import GraphState

MIN_GRADED_CHUNKS = 2  # minimum chunks that must survive grading to attempt generation


def _should_retry_or_generate(state: GraphState) -> Literal["analyze_query", "generate"]:
    """
    Conditional edge: route back to analyze_query (to rewrite the query) if
    too few chunks survived grading AND we haven't exhausted retries.
    Otherwise proceed to generate.
    """
    graded = state.get("graded_chunks", [])
    retry_count = state.get("retry_count", 0)

    if len(graded) < MIN_GRADED_CHUNKS and retry_count < settings.max_query_retries:
        return "analyze_query"
    return "generate"


def _increment_retry(state: GraphState) -> dict:
    """Thin node that increments retry_count before looping back."""
    return {"retry_count": state.get("retry_count", 0) + 1}


def build_graph() -> StateGraph:
    graph = StateGraph(GraphState)

    graph.add_node("analyze_query", analyze_query)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade_relevance", grade_relevance)
    graph.add_node("increment_retry", _increment_retry)
    graph.add_node("generate", generate)
    graph.add_node("check_groundedness", check_groundedness)

    graph.set_entry_point("analyze_query")
    graph.add_edge("analyze_query", "retrieve")
    graph.add_edge("retrieve", "grade_relevance")

    graph.add_conditional_edges(
        "grade_relevance",
        _should_retry_or_generate,
        {
            "analyze_query": "increment_retry",
            "generate": "generate",
        },
    )
    graph.add_edge("increment_retry", "analyze_query")
    graph.add_edge("generate", "check_groundedness")
    graph.add_edge("check_groundedness", END)

    return graph


# Compiled graph — module-level singleton; compiled once, invoked many times
_compiled_graph = None


def get_compiled_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph().compile()
    return _compiled_graph
