"""Chat with your agent from this terminal.

Start the shell with ./run.sh and leave it running. Then, in a second terminal, in this folder,
with the virtual environment that README.md makes:

    . .venv/bin/activate
    python chat.py

Type a message and press Enter. Type /quit, or press Ctrl-D, to leave.
"""

# The one package this needs is langgraph-sdk, which README.md installs in .venv.
from langgraph_sdk import get_sync_client

# The tunnel that run.sh opens to the agent inside its sandbox.
BASE_URL = "http://127.0.0.1:2025"


def content_text(content):
    """The text of a message: a string, or a list of blocks of which some hold text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else str(block.get("text", ""))
            for block in content
            if isinstance(block, (str, dict))
        )
    return ""


def reply_text(state):
    """The text of the agent's latest reply, from the thread's state after a run.

    The state holds the whole conversation. Only the messages after your last one belong to this
    run, so an answer to an earlier message is never shown again.
    """
    messages = state.get("messages", []) if isinstance(state, dict) else []
    asked = [i for i, message in enumerate(messages) if message.get("type") == "human"]
    new = messages[asked[-1] + 1 :] if asked else messages
    replies = [content_text(m.get("content")) for m in new if m.get("type") == "ai"]
    replies = [text for text in replies if text.strip()]
    return replies[-1] if replies else "(no reply)"


def main():
    # No api_key: the SDK would otherwise send a LangSmith or LangGraph key of this machine's
    # environment to the agent's server, which needs none.
    client = get_sync_client(url=BASE_URL, api_key=None)
    try:
        thread_id = client.threads.create()["thread_id"]
    except Exception as error:
        raise SystemExit(
            f"Cannot reach your agent at {BASE_URL}: {error}\nIs ./run.sh still running?"
        ) from None
    print(f"Connected to your agent at {BASE_URL}. Type /quit to leave.")
    while True:
        try:
            text = input("you> ").strip()
        except EOFError:
            print()
            break
        if text == "/quit":
            break
        if not text:
            continue
        try:
            state = client.runs.wait(
                thread_id, "agent", input={"messages": [{"role": "user", "content": text}]}
            )
        except Exception as error:
            print(f"agent> The run failed: {error}")
            continue
        print(f"agent> {reply_text(state)}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
