#!/bin/sh
set -eu
# `langgraph dev` asks pypi.org for its latest version at start-up. The sandbox policy denies that,
# and the denial drafts a pending rule before anyone has spoken to the agent. So the check is off.
export LANGGRAPH_NO_VERSION_CHECK=true
cd /sandbox/workspace
# A build that routes its model calls passes Switchyard its routes. Switchyard then runs beside the
# agent on loopback, and the agent starts only once it answers, so no call finds it still starting.
if [ -n "${SWITCHYARD_ROUTES_B64:-}" ]; then
    python3.13 -m agent.switchyard_server &
    python3.13 -m agent.switchyard_server --wait
fi
exec langgraph dev --config /opt/shellblocks/langgraph.json --host 127.0.0.1 --port 2024 --no-browser --no-reload
