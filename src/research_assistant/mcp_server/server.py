"""
MCP server — Streamable HTTP transport (mcp==2.0.0).

Exposes two tools:
  • query_research_papers(question) → calls core.answer_question — SAME function as REST API
  • list_ingested_papers()          → calls core.list_ingested_papers — SAME function as REST API

HARD REQUIREMENT: this file contains ZERO retrieval or generation logic.
If you find yourself writing embedding, pgvector, or LangGraph code here,
stop and move it to core.py instead.

Transport changes from the decorator-based draft (mcp<2.0):
  OLD: @mcp_server.list_tools() / @mcp_server.call_tool() decorators — removed in 2.0.
  OLD: SseServerTransport + manual Route("/sse") + Mount("/messages") Starlette wiring.

  NEW (mcp==2.0.0):
    - Handlers are plain async functions passed as on_list_tools= / on_call_tool=
      constructor keyword arguments.
    - SseServerTransport still exists in mcp.server.sse but is the legacy path.
      Server.streamable_http_app() returns a fully-wired Starlette app (path=/mcp)
      and is the recommended transport in 2.0.

Handler signatures required by mcp==2.0.0:
  on_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None)
      -> Awaitable[types.ListToolsResult]
  on_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams)
      -> Awaitable[types.CallToolResult | types.InputRequiredResult]

Claude Desktop config (update url to /mcp — SSE /sse endpoint no longer wired):
  {
    "mcpServers": {
      "tinyml-research": {
        "url": "http://localhost:8001/mcp"
      }
    }
  }
"""

from __future__ import annotations

import json

from mcp import types
from mcp.server import Server, ServerRequestContext

from research_assistant.config import settings
from research_assistant.core import answer_question, list_ingested_papers

_TOOLS = [
    types.Tool(
        name="query_research_papers",
        description=(
            "Answer a question about TinyML and embedded machine learning "
            "using a RAG pipeline over 15 curated arXiv papers. "
            "Returns the answer, inline citations, and groundedness status."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The research question to answer.",
                }
            },
            "required": ["question"],
        },
    ),
    types.Tool(
        name="list_ingested_papers",
        description="List all arXiv papers ingested into the research corpus.",
        inputSchema={"type": "object", "properties": {}},
    ),
]


async def _on_list_tools(
    ctx: ServerRequestContext,
    params: types.PaginatedRequestParams | None,
) -> types.ListToolsResult:
    return types.ListToolsResult(tools=_TOOLS)


async def _on_call_tool(
    ctx: ServerRequestContext,
    params: types.CallToolRequestParams,
) -> types.CallToolResult | types.InputRequiredResult:
    arguments = params.arguments or {}

    if params.name == "query_research_papers":
        question = arguments.get("question", "")
        result = answer_question(question)
        payload = {
            "answer": result.answer,
            "answerable": result.answerable,
            "is_grounded": result.is_grounded,
            "groundedness_note": result.groundedness_note,
            "retry_count": result.retry_count,
            "query_type": result.query_type,
            "rewritten_query": result.rewritten_query,
            "citations": result.citations,
            "retrieved_chunk_ids": result.retrieved_chunk_ids,
        }
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(payload, indent=2))]
        )

    if params.name == "list_ingested_papers":
        papers = list_ingested_papers()
        return types.CallToolResult(
            content=[types.TextContent(
                type="text",
                text=json.dumps([vars(p) for p in papers], indent=2),
            )]
        )

    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"Unknown tool: {params.name}")],
        is_error=True,
    )


mcp_server = Server(
    "tinyml-research-assistant",
    on_list_tools=_on_list_tools,
    on_call_tool=_on_call_tool,
)

# streamable_http_app() replaces the manual SseServerTransport wiring.
# It returns a fully-configured Starlette app mounted at /mcp.
app = mcp_server.streamable_http_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)
