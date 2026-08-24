"""
Single public entry point for the RAG pipeline.

Both the FastAPI REST API (api/routes.py) and the MCP server
(mcp_server/server.py) MUST import ONLY from this module.
Zero retrieval logic lives outside this file and the rag/ package.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from research_assistant.db.vector_store import get_engine, list_papers
from research_assistant.rag.graph import get_compiled_graph
from research_assistant.rag.state import Citation, GraphState


@dataclass
class RAGResponse:
    answer: str
    citations: list[Citation]
    retrieved_chunk_ids: list[int]
    retry_count: int
    answerable: bool
    is_grounded: bool
    groundedness_note: str
    query_type: str
    rewritten_query: str


@dataclass
class PaperSummary:
    arxiv_id: str
    title: str
    authors: list[str]
    published: str
    categories: list[str]
    arxiv_url: str


def answer_question(query: str) -> RAGResponse:
    """
    Run the full LangGraph RAG pipeline and return a structured response.

    This is the ONLY function the REST API and MCP server are permitted to call
    from the RAG layer.  If you find yourself adding retrieval or generation
    logic in api/ or mcp_server/, stop and put it here instead.
    """
    if not query or not query.strip():
        return RAGResponse(
            answer="Query cannot be empty.",
            citations=[],
            retrieved_chunk_ids=[],
            retry_count=0,
            answerable=False,
            is_grounded=True,
            groundedness_note="empty query",
            query_type="factual",
            rewritten_query="",
        )

    initial_state: GraphState = {
        "original_query": query.strip(),
        "query_type": "factual",
        "rewritten_query": "",
        "retrieved_chunks": [],
        "graded_chunks": [],
        "answer": "",
        "citations": [],
        "is_grounded": False,
        "groundedness_note": "",
        "retry_count": 0,
        "answerable": True,
        "error": None,
    }

    graph = get_compiled_graph()
    final_state: GraphState = graph.invoke(initial_state)

    # Enrich citations with paper titles from DB
    engine = get_engine()
    with Session(engine) as session:
        papers = {p.arxiv_id: p for p in list_papers(session)}

    enriched_citations: list[Citation] = []
    for c in final_state.get("citations", []):
        paper = papers.get(c["arxiv_id"])
        enriched_citations.append(
            {
                **c,
                "title": paper.title if paper else c["arxiv_id"],
            }
        )

    return RAGResponse(
        answer=final_state.get("answer", ""),
        citations=enriched_citations,
        retrieved_chunk_ids=[c["id"] for c in final_state.get("graded_chunks", [])],
        retry_count=final_state.get("retry_count", 0),
        answerable=final_state.get("answerable", True),
        is_grounded=final_state.get("is_grounded", True),
        groundedness_note=final_state.get("groundedness_note", ""),
        query_type=final_state.get("query_type", "factual"),
        rewritten_query=final_state.get("rewritten_query", query),
    )


def list_ingested_papers() -> list[PaperSummary]:
    """Return metadata for all ingested papers. Used by both REST API and MCP server."""
    engine = get_engine()
    with Session(engine) as session:
        papers = list_papers(session)
        return [
            PaperSummary(
                arxiv_id=p.arxiv_id,
                title=p.title,
                authors=p.authors or [],
                published=p.published.isoformat() if p.published else "",
                categories=p.categories or [],
                arxiv_url=p.arxiv_url or "",
            )
            for p in papers
        ]
