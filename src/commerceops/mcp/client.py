"""Typed client adapter that invokes CommerceOps tools through MCP."""

from collections.abc import Mapping
from uuid import uuid4

from mcp import Client

from commerceops.mcp.context import FixedRuntimeContextProvider, ToolRuntimeContext
from commerceops.mcp.server import create_mcp_server
from commerceops.mcp.tools.executor import SessionFactory, default_session_factory
from commerceops.mcp.tools.schemas import ToolErrorData, ToolResult


class CommerceOpsMCPClient:
    """In-process MCP adapter used by graph nodes and contract tests."""

    def __init__(
        self,
        runtime_context: ToolRuntimeContext,
        session_factory: SessionFactory = default_session_factory,
    ) -> None:
        self._server = create_mcp_server(
            FixedRuntimeContextProvider(runtime_context), session_factory
        )

    async def call_tool(
        self, tool_name: str, arguments: Mapping[str, object]
    ) -> ToolResult:
        if "tenant_id" in arguments:
            return _client_failure("INVALID_INPUT", "Tool input is invalid.")
        async with Client(self._server) as client:
            result = await client.call_tool(tool_name, dict(arguments))
        if result.structured_content is None:
            return _client_failure(
                "MCP_PROTOCOL_ERROR", "The tool returned an invalid response."
            )
        try:
            return ToolResult.model_validate(result.structured_content)
        except ValueError:
            return _client_failure(
                "MCP_PROTOCOL_ERROR", "The tool returned an invalid response."
            )


def _client_failure(code: str, message: str) -> ToolResult:
    return ToolResult(
        ok=False,
        data=None,
        error=ToolErrorData(code=code, message=message),
        audit_id=str(uuid4()),
    )
