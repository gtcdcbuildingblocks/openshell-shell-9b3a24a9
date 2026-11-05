from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from typing import Annotated

import yaml
from pydantic import BaseModel, Field, model_validator


class Model(BaseModel):
    name: str = Field(description="The name of the model")
    url: str = Field(description="The URL of the model")
    api_key: None | str = Field(None, description="The API key to use for the model")
    temperature: float = Field(0.5, ge=0.0, le=1.0, description="The temperature to use for the model")
    top_p: float | None = Field(None, ge=0.0, le=1.0, description="The top p to use for the model")
    max_tokens: int = Field(None, ge=0.0, description="The maximum number of tokens to generate")


class Proxy(BaseModel):
    """Switchyard, the routing proxy the agent dials in place of models[0].

    The agent sends every call to ``url`` asking for ``model``, a route's id, and Switchyard picks
    the model that serves it. The sandbox runs Switchyard beside the agent; the twin runs without it.
    """

    url: str = Field(description="The OpenAI-compatible base URL of the proxy")
    model: str = Field(description="The route id the proxy takes as a model name")
    fallback: str | None = Field(
        None,
        description="The route that is asked again when a provider's filter stops a reply. None asks no route again",
    )
    session_header: str = Field(
        "x-switchyard-session-id",
        description="The header that carries the conversation id, so the proxy's session state lasts across calls",
    )


class MCPServer(BaseModel):
    """Definition of a single MCP server to connect to."""

    command: str | None = Field(None, description="The command to run the MCP server (required for stdio)")
    args: list[str] | None = Field(None, description="Arguments for the command")
    transport: str = Field("stdio", description="Transport type (e.g. 'stdio', 'streamable_http')")
    url: str | None = Field(None, description="URL for HTTP transport servers (e.g. streamable_http)")
    env: dict[str, str] | None = Field(
        None,
        description="Environment variables for the MCP subprocess, added to the agent's own environment",
    )
    headers: dict[str, str] | None = Field(
        None,
        description="HTTP headers (e.g. Authorization) for HTTP transport servers",
    )
    tools: list[str] | None = Field(
        None,
        description="Allowlist of tool names to expose from this server (None = all tools)",
    )

    @model_validator(mode="after")
    def _require_command_or_url(self) -> "MCPServer":
        if not self.command and not self.url:
            raise ValueError("MCPServer requires either 'command' (stdio) or 'url' (HTTP)")
        if self.url and not self.url.startswith("$") and not (
            self.url.startswith("http://") or self.url.startswith("https://")
        ):
            raise ValueError("MCPServer 'url' must start with 'http://' or 'https://'")
        return self


class Configuration(BaseModel):
    models: Annotated[
        list[Model],
        Field(min_length=1, description="The models available to the agent; the first one is used for inference"),
    ]

    proxy: Proxy | None = Field(
        None,
        description="The routing proxy to dial in place of models[0], whose sampling settings it still takes. None dials models[0]",
    )

    system_prompt: str = Field(
        "You are a helpful assistant",
        description="The system prompt for the agent",
    )

    mcp_servers: dict[str, MCPServer] = Field(
        default_factory=dict,
        description="Named MCP servers the agent can use for tools",
    )

    tool_prompt_hints: dict[str, str] = Field(
        default_factory=dict,
        description="Per-tool hint text appended to the last user message before each model call",
    )


_ENV_REF_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


def _resolve(value: str) -> str:
    """Replace $VAR_NAME patterns with values from os.environ. Unset vars resolve to ''."""
    return _ENV_REF_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _resolve_env_vars(config: Configuration) -> Configuration:
    """Return a copy of config with all $VAR_NAME refs substituted from os.environ."""
    resolved_models = [m.model_copy(update={"api_key": _resolve(m.api_key or "")}) for m in config.models]
    resolved_servers: dict[str, MCPServer] = {}
    for name, server in config.mcp_servers.items():
        resolved_servers[name] = MCPServer(
            command=server.command,
            # The MCP client needs an args key for a stdio server, even one that takes no arguments.
            args=[_resolve(a) for a in server.args] if server.args else ([] if server.command else None),
            transport=server.transport,
            url=_resolve(server.url) if server.url else None,
            env={k: _resolve(v) for k, v in server.env.items()} if server.env else None,
            headers={k: _resolve(v) for k, v in server.headers.items()} if server.headers else None,
            tools=server.tools,
        )
    resolved_hints = {k: _resolve(v) for k, v in config.tool_prompt_hints.items()}
    return config.model_copy(
        update={"models": resolved_models, "mcp_servers": resolved_servers, "tool_prompt_hints": resolved_hints}
    )


def load(path: str | None = None) -> Configuration:
    """Load the agent's config, resolve $VAR_NAME env refs, and return a validated Configuration.

    The config is the JSON in AGENT_CONFIG_JSON when that is set (a variable that is set but empty
    counts as unset). Otherwise it is the YAML file at ``path``, or at AGENT_CONFIG_PATH when no
    path is given. With none of the three, this raises FileNotFoundError.
    """
    if raw_json := os.environ.get("AGENT_CONFIG_JSON"):
        data = json.loads(raw_json)
    else:
        config_path = path or os.environ.get("AGENT_CONFIG_PATH")
        if not config_path:
            raise FileNotFoundError(
                "no agent config: set AGENT_CONFIG_JSON or AGENT_CONFIG_PATH, or pass a path"
            )
        with open(config_path) as f:
            data = yaml.safe_load(f.read())

    return _resolve_env_vars(Configuration.model_validate(data))


def mcp_connections(config: Configuration, environ: Mapping[str, str] | None = None) -> dict[str, dict]:
    """The connection dict MultiServerMCPClient takes for each of the config's MCP servers.

    A server with a ``command`` (stdio) inherits ``environ``, the process environment when that is
    None, with the server's own ``env`` layered on top. Left alone the MCP client starts it with only
    HOME, LOGNAME, PATH, SHELL, TERM and USER, so the sandbox's certificate variables would not reach
    it. A URL server's dict is just its fields. "tools" isn't a connection param the MCP client
    understands, so it is left out.
    """
    inherited = os.environ if environ is None else environ
    connections: dict[str, dict] = {}
    for name, server in config.mcp_servers.items():
        connection = server.model_dump(exclude_none=True, exclude={"tools"})
        if server.command:
            connection["env"] = {**inherited, **(server.env or {})}
        connections[name] = connection
    return connections
