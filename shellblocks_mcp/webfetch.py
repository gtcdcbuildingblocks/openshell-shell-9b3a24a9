"""Web Fetch MCP server: GET and POST tools for the sandboxed agent, served over stdio."""

import re
from html import unescape

import httpx
from mcp.server.fastmcp import FastMCP

MAX_CHARS = 20000
_REPLY_PREVIEW_CHARS = 500

# A script or style block goes with its contents; an unclosed one runs to the end, as in a browser.
_SKIPPED_BLOCK = re.compile(r"<(script|style)\b.*?(?:</\1\s*>|\Z)", re.IGNORECASE | re.DOTALL)
# Comments, doctypes and tags. A "<" that does not start a tag name is ordinary text.
_TAG = re.compile(r"<!--.*?-->|<[!/?]?[a-zA-Z][^>]*>", re.DOTALL)
_WHITESPACE = re.compile(r"\s+")

mcp = FastMCP("webfetch")


def make_client() -> httpx.Client:
    # No verify argument: httpx then honors SSL_CERT_FILE, which OpenShell sets inside the sandbox.
    return httpx.Client(timeout=20, follow_redirects=True)


# The tools look this up on each call, so tests replace it through monkeypatch.
_client_factory = make_client


def html_to_text(html: str) -> str:
    text = _SKIPPED_BLOCK.sub(" ", html)
    # Each tag becomes a space so words from neighbouring elements do not run together.
    text = _TAG.sub(" ", text)
    return _WHITESPACE.sub(" ", unescape(text)).strip()


def _truncate(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    return text[:MAX_CHARS] + "\n[truncated]"


@mcp.tool()
def fetch_url(url: str) -> str:
    """Fetch a web page or API response by URL and return its text."""
    try:
        with _client_factory() as client:
            response = client.get(url)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        return f"Request failed: {type(e).__name__}: {e}"
    text = response.text
    if "text/html" in response.headers.get("content-type", ""):
        text = html_to_text(text)
    text = _truncate(text)
    if response.status_code >= 400:
        # An error body may be a policy denial rather than page content, so the status goes first.
        return f"{response.status_code} {response.reason_phrase}\n{text}"
    return text


@mcp.tool()
def post_url(url: str, body: str, content_type: str = "text/plain") -> str:
    """Send a POST request with a text body to a URL and return the response status and the start of its body."""
    try:
        with _client_factory() as client:
            response = client.post(url, content=body.encode(), headers={"Content-Type": content_type})
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        return f"Request failed: {type(e).__name__}: {e}"
    return f"{response.status_code} {response.reason_phrase}\n{response.text[:_REPLY_PREVIEW_CHARS]}"


if __name__ == "__main__":
    mcp.run()
