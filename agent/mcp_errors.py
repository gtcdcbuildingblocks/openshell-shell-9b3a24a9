"""Keep recoverable MCP failures inside the agent conversation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from langchain_core.tools import BaseTool, ToolException
from langchain_mcp_adapters.interceptors import (
    MCPToolCallRequest,
    MCPToolCallResult,
)
from mcp.types import CallToolResult, TextContent

_LOGGER = logging.getLogger(__name__)
_MAX_ERROR_LENGTH = 4_000


def _truncate(message: str) -> str:
    message = message.strip() or "Tool execution failed without an error message."
    if len(message) <= _MAX_ERROR_LENGTH:
        return message
    return f"{message[:_MAX_ERROR_LENGTH]}\n[error details truncated]"


def format_mcp_tool_error(error: ToolException) -> str:
    """Give the model an actionable error instead of terminating the run."""
    return (
        "MCP tool call failed, but the agent can continue.\n\n"
        f"{_truncate(str(error))}\n\n"
        "Inspect the current state before retrying. Do not repeat the identical "
        "call unchanged; use different arguments or another strategy."
    )


async def recover_mcp_exceptions(
    request: MCPToolCallRequest,
    handler: Callable[[MCPToolCallRequest], Awaitable[MCPToolCallResult]],
) -> MCPToolCallResult:
    """Convert MCP transport exceptions into normal MCP error results."""
    try:
        result = await handler(request)
    except Exception as error:
        _LOGGER.exception(
            "MCP tool %s.%s raised %s",
            request.server_name,
            request.name,
            type(error).__name__,
        )
        return CallToolResult(
            isError=True,
            content=[
                TextContent(
                    type="text",
                    text=f"{type(error).__name__}: {_truncate(str(error))}",
                )
            ],
        )

    if isinstance(result, CallToolResult) and result.isError:
        _LOGGER.warning(
            "MCP tool %s.%s returned an error",
            request.server_name,
            request.name,
        )
    return result


def configure_mcp_tool_error_handling(tools: list[BaseTool]) -> list[BaseTool]:
    """Configure LangChain to return MCP ToolExceptions to the model."""
    for tool in tools:
        tool.handle_tool_error = format_mcp_tool_error
    return tools
