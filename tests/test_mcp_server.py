"""
MCP server tests — exercise handler functions directly and verify the /mcp endpoint
exists. All external I/O (core.answer_question, core.list_ingested_papers) is mocked.

Transport note: mcp==2.0.0 uses Streamable HTTP (Server.streamable_http_app(), path=/mcp).
The old decorator-based @mcp_server.list_tools() / @mcp_server.call_tool() API and the
SseServerTransport /sse endpoint are no longer used. Handler functions are plain async
callables passed to Server(..., on_list_tools=..., on_call_tool=...) and are tested here
by calling them directly with a MagicMock context (ctx is unused in both handlers).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from mcp import types

from research_assistant.core import PaperSummary, RAGResponse
from research_assistant.mcp_server.server import (
    _on_call_tool,
    _on_list_tools,
    app as mcp_app,
)

MOCK_RESPONSE = RAGResponse(
    answer="MCUNet uses INT8 post-training quantization.",
    citations=[
        {
            "arxiv_id": "2401.00001",
            "title": "MCUNet: Tiny Deep Learning on IoT Devices",
            "section_title": "Method",
            "page": 3,
            "chunk_id": 42,
        }
    ],
    retrieved_chunk_ids=[42],
    retry_count=0,
    answerable=True,
    is_grounded=True,
    groundedness_note="",
    query_type="factual",
    rewritten_query="MCUNet quantization",
)

MOCK_PAPERS = [
    PaperSummary(
        arxiv_id="2401.00001",
        title="MCUNet: Tiny Deep Learning on IoT Devices",
        authors=["Ji Lin"],
        published="2020-07-20T00:00:00",
        categories=["cs.LG"],
        arxiv_url="https://arxiv.org/abs/2007.10319",
    )
]


def test_mcp_endpoint_mounted():
    """
    Verify the /mcp Streamable HTTP route is registered on the app.

    StreamableHTTPSessionManager requires a running task group (lifespan) before
    it can service requests, so we verify route presence structurally rather than
    making an actual HTTP request in this unit-test context.
    """
    paths = {r.path for r in mcp_app.routes if hasattr(r, "path")}
    assert "/mcp" in paths, "/mcp route not found — streamable_http_app() not wired"


@pytest.mark.asyncio
async def test_list_tools_returns_two_tools():
    """_on_list_tools returns the expected two tool definitions."""
    ctx = MagicMock()
    result = await _on_list_tools(ctx, None)

    assert isinstance(result, types.ListToolsResult)
    names = {t.name for t in result.tools}
    assert names == {"query_research_papers", "list_ingested_papers"}


@pytest.mark.asyncio
async def test_query_research_papers_tool():
    """
    _on_call_tool("query_research_papers") delegates to core.answer_question —
    not any duplicate retrieval logic.
    """
    ctx = MagicMock()
    params = types.CallToolRequestParams(
        name="query_research_papers",
        arguments={"question": "What is TinyML?"},
    )

    with patch("research_assistant.mcp_server.server.answer_question", return_value=MOCK_RESPONSE) as mock_core:
        result = await _on_call_tool(ctx, params)

    assert mock_core.called
    assert isinstance(result, types.CallToolResult)
    assert result.is_error is not True
    payload = json.loads(result.content[0].text)
    assert payload["answerable"] is True
    assert payload["citations"][0]["arxiv_id"] == "2401.00001"


@pytest.mark.asyncio
async def test_list_ingested_papers_tool():
    ctx = MagicMock()
    params = types.CallToolRequestParams(name="list_ingested_papers", arguments=None)

    with patch("research_assistant.mcp_server.server.list_ingested_papers", return_value=MOCK_PAPERS):
        result = await _on_call_tool(ctx, params)

    assert isinstance(result, types.CallToolResult)
    payload = json.loads(result.content[0].text)
    assert len(payload) == 1
    assert payload[0]["arxiv_id"] == "2401.00001"


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_result():
    ctx = MagicMock()
    params = types.CallToolRequestParams(name="nonexistent_tool", arguments={})
    result = await _on_call_tool(ctx, params)

    assert isinstance(result, types.CallToolResult)
    assert result.is_error is True
    assert "Unknown tool" in result.content[0].text


FORBIDDEN_MODULES = frozenset({
    "research_assistant.db.vector_store",
    "research_assistant.rag.graph",
    "research_assistant.rag.nodes",
    "research_assistant.rag.prompts",
})


def _check_no_forbidden_imports(source: str, label: str = "file") -> None:
    """Raise AssertionError if source contains any forbidden import (both styles)."""
    import ast

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in FORBIDDEN_MODULES, (
                f"{label} imports {node.module} directly — "
                "all RAG logic must go through core.py"
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in FORBIDDEN_MODULES, (
                    f"{label} imports {alias.name} directly — "
                    "all RAG logic must go through core.py"
                )


def test_mcp_server_imports_only_from_core():
    """
    Structural guard: verify mcp_server/server.py does NOT import from
    db.vector_store, rag.graph, rag.nodes, or rag.prompts directly.
    Checks both 'import X' and 'from X import Y' styles.
    This enforces the 'zero duplicated business logic' requirement.
    """
    from pathlib import Path

    src = (Path(__file__).parent.parent / "src/research_assistant/mcp_server/server.py").read_text()
    _check_no_forbidden_imports(src, label="mcp_server/server.py")


def test_ast_guard_catches_plain_import():
    """
    Proof that the guard actually fires on a plain 'import X' statement
    (not just 'from X import Y'). Without the ast.Import branch, this
    style of forbidden import would have passed silently.
    """
    fixture_with_plain_import = (
        "import research_assistant.rag.graph\n"
        "from research_assistant.core import answer_question\n"
    )
    with pytest.raises(AssertionError, match="imports research_assistant.rag.graph directly"):
        _check_no_forbidden_imports(fixture_with_plain_import, label="fixture")
