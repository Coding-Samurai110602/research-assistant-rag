"""
LangGraph node functions.

Each function takes the full GraphState and returns a partial dict with only
the keys it modifies — LangGraph merges these dicts automatically.

Node inventory (in execution order; see graph.py for wiring):
  1. analyze_query    — classify + rewrite query
  2. retrieve         — pgvector similarity search
  3. grade_relevance  — per-chunk LLM relevance scoring
  4. generate         — grounded answer generation with inline citations
  5. check_groundedness — hallucination check on generated answer
"""

from __future__ import annotations

import functools
import json
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from sqlalchemy.orm import Session

from research_assistant.config import settings
from research_assistant.db.vector_store import get_engine, similarity_search
from research_assistant.rag.prompts import (
    GENERATION_PROMPT,
    GROUNDEDNESS_PROMPT,
    QUERY_ANALYSIS_PROMPT,
    QUERY_REWRITE_PROMPT,
    RELEVANCE_GRADING_PROMPT,
)
from research_assistant.rag.state import Citation, GraphState, RetrievedChunk


@functools.lru_cache(maxsize=1)
def _get_llm() -> BaseChatModel:
    """
    Construct and cache the LLM client for the configured provider.

    Cached so the client object is built once per process, not once per node
    invocation (analyze_query, grade_relevance, generate, check_groundedness
    each call this — four times per query without caching).

    Anthropic notes:
    - temperature omitted: Sonnet 5 rejects it as deprecated.
    - thinking={"type": "disabled"}: Sonnet 5 has adaptive thinking ON by
      default when thinking is omitted. All four RAG nodes are either
      mechanical classification tasks (grade_relevance, check_groundedness,
      analyze_query) or context-bounded synthesis (generate) where the strict
      grounding rules explicitly prohibit reasoning beyond the provided passages.
      Extended thinking is counterproductive in all four cases — it costs tokens
      to reason about things the model is then instructed to ignore.
    """
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=settings.llm_model,
            api_key=settings.anthropic_api_key,
            thinking={"type": "disabled"},
        )
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )


def _get_embed_fn():
    from research_assistant.db.vector_store import _get_embedding_fn
    return _get_embedding_fn()


def _parse_json_field(text: str, field: str, default: Any = None) -> Any:
    """Extract a single field from an LLM JSON response, tolerating markdown fences."""
    clean = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    try:
        data = json.loads(clean)
        return data.get(field, default)
    except (json.JSONDecodeError, AttributeError):
        return default


def _parse_json(text: str) -> dict:
    clean = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        return {}


def _extract_content(response: Any) -> str:
    """Coerce an LLM response's .content to a plain str.

    LangChain's AIMessage.content is str for simple completions but
    list[str | dict] when the model returns structured blocks — Anthropic
    does this for thinking/text block responses.  Only dict items with
    key "text" contribute content; blocks of other types (e.g. "thinking")
    are intentionally dropped because they are internal reasoning, not the
    answer the rest of the pipeline expects.  Parts are joined without a
    separator — the model already spaces them correctly.
    """
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text", "")
                if text:
                    parts.append(text)
        return "".join(parts)
    return str(content)


# ── Node 1: analyze_query ─────────────────────────────────────────────────────

def analyze_query(state: GraphState) -> dict:
    llm = _get_llm()
    chain = QUERY_ANALYSIS_PROMPT | llm

    query = state.get("rewritten_query") or state["original_query"]
    # On retry, use the retry-rewrite prompt instead
    retry_count = state.get("retry_count", 0)
    if retry_count > 0:
        rewrite_chain = QUERY_REWRITE_PROMPT | llm
        result = rewrite_chain.invoke({
            "original_query": state["original_query"],
            "previous_rewrite": state.get("rewritten_query", state["original_query"]),
        })
        rewritten = _extract_content(result).strip()
        return {"rewritten_query": rewritten, "retry_count": retry_count}

    result = chain.invoke({"question": query})
    parsed = _parse_json(_extract_content(result))
    return {
        "query_type": parsed.get("query_type", "factual"),
        "rewritten_query": parsed.get("rewritten_query", query),
        "retry_count": retry_count,
    }


# ── Node 2: retrieve ──────────────────────────────────────────────────────────

def retrieve(state: GraphState) -> dict:
    embed_fn = _get_embed_fn()
    engine = get_engine()

    query_text = state.get("rewritten_query") or state["original_query"]
    [query_vec] = embed_fn([query_text])

    with Session(engine) as session:
        chunks = similarity_search(session, query_vec, top_k=settings.retrieval_top_k)
        retrieved: list[RetrievedChunk] = [
            {
                "id": c.id,
                "arxiv_id": c.arxiv_id,
                "section_title": c.section_title or "",
                "page": c.page or 0,
                "block_type": c.block_type or "body",
                "text": c.text,
                "token_count": c.token_count or 0,
                "distance": 0.0,  # pgvector doesn't return distance in ORM mode; fine for grading
            }
            for c in chunks
        ]
    return {"retrieved_chunks": retrieved}


# ── Node 3: grade_relevance ───────────────────────────────────────────────────

def grade_relevance(state: GraphState) -> dict:
    llm = _get_llm()
    chain = RELEVANCE_GRADING_PROMPT | llm

    query = state.get("rewritten_query") or state["original_query"]
    graded: list[RetrievedChunk] = []

    for chunk in state.get("retrieved_chunks", []):
        result = chain.invoke({"query": query, "passage": chunk["text"][:1500]})
        verdict = _parse_json_field(_extract_content(result), "relevant", "no")
        if str(verdict).lower() == "yes":
            graded.append(chunk)

    return {"graded_chunks": graded}


# ── Node 4: generate ──────────────────────────────────────────────────────────

def generate(state: GraphState) -> dict:
    graded = state.get("graded_chunks", [])
    if not graded:
        return {
            "answer": (
                "The provided papers do not contain enough information"
                " to answer this question."
            ),
            "citations": [],
            "answerable": False,
        }

    context_parts = []
    for c in graded:
        label = f"[{c['arxiv_id']} | {c['section_title']} | p.{c['page']}]"
        context_parts.append(f"{label}\n{c['text']}")
    context = "\n\n---\n\n".join(context_parts)

    llm = _get_llm()
    chain = GENERATION_PROMPT | llm
    result = chain.invoke({
        "context": context,
        "question": state["original_query"],
    })
    answer = _extract_content(result).strip()

    # Always populate citations from graded chunks — we reached this point only
    # because graded_chunks is non-empty (the empty-chunks path exits early above).
    # answerable is always True here for the same reason: the system made a genuine
    # attempt with real retrieved context.
    #
    # Previously a substring match on "do not contain enough information" set
    # answerable=False and cleared citations even when graded chunks existed. This
    # caused check_groundedness to fire its early-return ("declined — no relevant
    # chunks") on responses that were real, detailed, and cited. The fix: treat
    # answerable as a retrieval flag, not a content flag. If the model says the
    # context is insufficient despite real chunks existing, that's a groundedness
    # concern — caught by check_groundedness — not an answerability one.
    citations: list[Citation] = []
    seen_ids: set[int] = set()
    for c in graded:
        if c["id"] not in seen_ids:
            citations.append({
                "arxiv_id": c["arxiv_id"],
                "title": "",  # filled in by core.py from paper metadata
                "section_title": c["section_title"],
                "page": c["page"],
                "chunk_id": c["id"],
                "text": c["text"],  # preserved for RAGAS context metrics
            })
            seen_ids.add(c["id"])

    return {
        "answer": answer,
        "citations": citations,
        "answerable": True,
    }


# ── Node 5: check_groundedness ────────────────────────────────────────────────

def check_groundedness(state: GraphState) -> dict:
    if not state.get("answerable", True):
        return {"is_grounded": True, "groundedness_note": "declined — no relevant chunks"}

    graded = state.get("graded_chunks", [])
    context = "\n\n".join(c["text"][:800] for c in graded)

    llm = _get_llm()
    chain = GROUNDEDNESS_PROMPT | llm
    result = chain.invoke({
        "answer": state.get("answer", ""),
        "context": context,
    })
    parsed = _parse_json(_extract_content(result))
    return {
        "is_grounded": bool(parsed.get("grounded", True)),
        "groundedness_note": parsed.get("note", ""),
    }
