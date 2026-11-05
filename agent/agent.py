"""Bridge between the sandbox's agent config and LangGraph.

Reads the agent config from AGENT_CONFIG_JSON (or the file AGENT_CONFIG_PATH names), builds a
LangGraph agent, and exports ``graph`` for ``langgraph dev``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from deepagents import create_deep_agent
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

from .backend import make_backend
from .configuration import Configuration, load, mcp_connections
from .mcp_errors import configure_mcp_tool_error_handling, recover_mcp_exceptions
from .middleware import (
    build_current_date_middleware,
    build_switchyard_middleware,
    build_system_prompt_addition_middleware,
    get_system_prompt_additions,
)


async def _build():
    """Build a LangGraph agent from a resolved Configuration."""
    # initialize config
    config: Configuration = load()

    # initialize model — Switchyard picks the model for each call when the config names it as the
    # proxy (in the sandbox), else the first model serves every call (the twin). The sampling
    # settings come from the first model either way. Switchyard's response headers name the model
    # that served each call.
    selected = config.models[0]
    proxy = config.proxy
    model = ChatOpenAI(
        model=proxy.model if proxy else selected.name,
        base_url=proxy.url if proxy else selected.url,
        api_key="switchyard" if proxy else (selected.api_key or "dummy"),
        temperature=selected.temperature,
        max_tokens=selected.max_tokens,
        use_responses_api=False,
        include_response_headers=proxy is not None,
        **({"top_p": selected.top_p} if selected.top_p is not None else {}),
    )

    # initialize tools
    tools: list[Any] = []
    if config.mcp_servers:
        client = MultiServerMCPClient(
            mcp_connections(config),
            tool_interceptors=[recover_mcp_exceptions],
        )
        for name, server in config.mcp_servers.items():
            available_tools = await client.get_tools(server_name=name)
            if server.tools:
                # filter tools to only include the ones in the server config
                available_tools = [t for t in available_tools if t.name in server.tools]
            tools.extend(configure_mcp_tool_error_handling(available_tools))

    # initialize middleware
    middleware = [build_current_date_middleware()]
    addition = get_system_prompt_additions(config)
    if addition:
        middleware.append(build_system_prompt_addition_middleware(addition))
    middleware += build_switchyard_middleware(proxy)

    # deepagents gives the general-purpose subagent, to which the `task` tool hands a step, only the
    # middleware that replaces one of its own. With Switchyard it is given its own pair: a delegated
    # step's calls name the conversation, and its filtered reply is asked again, as the agent's are.
    # Otherwise it is deepagents' own.
    subagents = [{**GENERAL_PURPOSE_SUBAGENT, "middleware": build_switchyard_middleware(proxy)}] if proxy else None

    # initialize backend: the real filesystem, so the sandbox's filesystem policy answers
    backend = make_backend()

    # initialize agent
    return create_deep_agent(
        model=model,
        tools=tools or None,
        system_prompt=config.system_prompt,
        middleware=tuple(middleware),
        subagents=subagents,
        backend=backend,
    )


graph = asyncio.run(_build())
