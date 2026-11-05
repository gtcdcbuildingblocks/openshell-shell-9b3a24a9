"""Custom middleware: modify each model call at call time.

Uses wrap_model_call to intercept each LLM call and prepend/append context
(current date, tool hints) to the system message. With Switchyard, two more
send the conversation's id along and ask a filtered reply again.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain.agents.middleware import wrap_model_call
from langchain.agents.middleware.types import AgentMiddleware, AgentState, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.config import get_config

from .configuration import Configuration, Proxy

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


def _prepend_to_system(existing: SystemMessage | None, text: str) -> SystemMessage:
    """Prepend *text* to an existing system message (or create one)."""
    if existing is None:
        return SystemMessage(content=text)
    content = existing.content
    if isinstance(content, str):
        return SystemMessage(content=text + "\n\n" + content)
    return SystemMessage(content=[{"type": "text", "text": text + "\n\n"}] + list(content))


def _append_to_system(existing: SystemMessage | None, text: str) -> SystemMessage:
    """Append *text* to an existing system message (or create one)."""
    if existing is None:
        return SystemMessage(content=text)
    content = existing.content
    if isinstance(content, str):
        return SystemMessage(content=content + "\n\n" + text)
    return SystemMessage(content=list(content) + [{"type": "text", "text": "\n\n" + text}])


# ---------------------------------------------------------------------------
# Current-date middleware (always on)
# ---------------------------------------------------------------------------


def build_current_date_middleware() -> AgentMiddleware[AgentState[Any], Any, Any]:
    """Prepend the current Pacific date/time to the system message on every model call."""

    @wrap_model_call
    async def _inject_date(request: ModelRequest, handler: Callable) -> ModelResponse:
        now = datetime.now(PACIFIC_TZ)
        date_str = now.strftime("Current date: %A, %B %d, %Y %H:%M %Z")
        new_system = _prepend_to_system(request.system_message, date_str)
        return await handler(request.override(system_message=new_system))

    return _inject_date


# ---------------------------------------------------------------------------
# Tool-hint middleware (conditional on config)
# ---------------------------------------------------------------------------


def get_system_prompt_additions(config: Configuration) -> str:
    """Return tool-specific hint text to append to the system message on each model call.

    Built from config.tool_prompt_hints, which holds one hint per tool.
    """
    if not config.tool_prompt_hints:
        return ""
    return "\n\n".join(config.tool_prompt_hints.values())


def build_system_prompt_addition_middleware(addition: str) -> AgentMiddleware[AgentState[Any], Any, Any]:
    """Append *addition* to the system message on each model call."""
    if not addition.strip():

        @wrap_model_call
        async def _noop(request: ModelRequest, handler: Callable) -> ModelResponse:
            return await handler(request)

        return _noop

    text = addition.strip()

    @wrap_model_call
    async def _append_hints(request: ModelRequest, handler: Callable) -> ModelResponse:
        new_system = _append_to_system(request.system_message, text)
        return await handler(request.override(system_message=new_system))

    return _append_hints


# ---------------------------------------------------------------------------
# Switchyard middleware (only when the config names a proxy)
# ---------------------------------------------------------------------------

# The response header in which Switchyard names the model that served a call.
SELECTED_MODEL_HEADER = "x-model-router-selected-model"
# The response_metadata key, on an answer from the fallback route, that names the model whose
# filter stopped the reply before it.
FILTERED_KEY = "switchyard_filtered"


def build_session_header_middleware(header: str) -> AgentMiddleware[AgentState[Any], Any, Any]:
    """Send the conversation id to the routing proxy on every model call.

    Switchyard keeps a session's state, such as an escalation's hold, only across
    requests that carry its id. The header rides through ``model_kwargs`` rather
    than ``default_headers`` so the underlying HTTP client isn't rebuilt per call,
    and on a copy of the model, which every conversation shares.
    """

    @wrap_model_call
    async def _inject_session(request: ModelRequest, handler: Callable) -> ModelResponse:
        try:
            thread_id = get_config()["configurable"]["thread_id"]
        except (KeyError, TypeError, RuntimeError):
            return await handler(request)

        if not thread_id:
            return await handler(request)

        kwargs = dict(getattr(request.model, "model_kwargs", None) or {})
        kwargs["extra_headers"] = {**(kwargs.get("extra_headers") or {}), header: str(thread_id)}
        model = request.model.model_copy(update={"model_kwargs": kwargs})
        return await handler(request.override(model=model))

    return _inject_session


def _reply(response: ModelResponse) -> AIMessage | None:
    """The model's message in a response, which may also hold a structured-output ToolMessage."""
    return next((message for message in response.result if isinstance(message, AIMessage)), None)


def _is_filtered(reply: AIMessage | None) -> bool:
    """Whether a provider's content filter stopped the reply before it said or asked for anything."""
    return (
        reply is not None
        and reply.response_metadata.get("finish_reason") == "content_filter"
        and not reply.text
        and not reply.tool_calls
    )


def build_filtered_reply_middleware(fallback: str) -> AgentMiddleware[AgentState[Any], Any, Any]:
    """Ask the ``fallback`` route once more when a provider's filter stops a reply.

    A provider's content filter can stop a model before it writes a word, and the
    agent would end its turn on the empty reply. The same call then goes to the
    fallback route. Its answer names, under FILTERED_KEY, the model whose filter
    stopped the first reply; an answer that is filtered too is returned as it came.
    """

    @wrap_model_call
    async def _ask_again_when_filtered(request: ModelRequest, handler: Callable) -> ModelResponse:
        response = await handler(request)
        first = _reply(response)
        if not _is_filtered(first):
            return response

        model = request.model.model_copy(update={"model_name": fallback})
        retry = await handler(request.override(model=model))
        answer = _reply(retry)
        if answer is not None and not _is_filtered(answer):
            headers = first.response_metadata.get("headers") or {}
            answer.response_metadata[FILTERED_KEY] = headers.get(SELECTED_MODEL_HEADER)
        return retry

    return _ask_again_when_filtered


def build_switchyard_middleware(proxy: Proxy | None) -> list[AgentMiddleware[AgentState[Any], Any, Any]]:
    """The middleware that every call to Switchyard takes, in order: the session header's, then the
    filtered reply's when the proxy names a fallback route, inside the session header's, so that the
    call it makes again carries the header too. An empty list without a proxy, as for the twin.

    Each call makes new ones: the agent's stack takes one pair, and the general-purpose subagent's,
    to which the `task` tool hands a step, another.
    """
    if proxy is None:
        return []
    middleware = [build_session_header_middleware(proxy.session_header)]
    if proxy.fallback:
        middleware.append(build_filtered_reply_middleware(proxy.fallback))
    return middleware
