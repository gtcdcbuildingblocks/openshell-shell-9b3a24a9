#!/usr/bin/env bash
# run.sh: build the sandbox image, seal your agent inside it, and open a tunnel to it.
#
# In order, this:
#   1. builds the sandbox image from sandbox/Dockerfile
#   2. makes the OpenShell workspace shellblocks, if it is not there already
#   3. makes the Providers, the key vault, with ./providers.sh
#   4. creates the Sandbox my-agent with the policy in policy.yaml and Switchyard's routes in
#      switchyard.toml, and starts NeMo Switchyard and the agent in it
#   5. opens a tunnel from http://127.0.0.1:2025 to the agent, and waits until the agent answers
#
# Before step 1, ./providers.sh --check makes sure that every key your build needs is set, so that
# a key that is not set stops this at once, not after the image build.
#
# To start over, delete the sandbox and run this again:
#   openshell sandbox delete my-agent --workspace shellblocks
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# Your keys, if your build needs any, are in .env, or in your shell's environment.
# A key that .env leaves blank, as env.example does, keeps the value your shell gave it.
if [ -f .env ]; then
  shell_NVIDIA_API_KEY="${NVIDIA_API_KEY:-}"
  shell_TAVILY_API_KEY="${TAVILY_API_KEY:-}"
  set -a
  . ./.env
  set +a
  if [ -z "${NVIDIA_API_KEY:-}" ]; then
    NVIDIA_API_KEY="$shell_NVIDIA_API_KEY"
  fi
  if [ -z "${TAVILY_API_KEY:-}" ]; then
    TAVILY_API_KEY="$shell_TAVILY_API_KEY"
  fi
fi

# A key that is not set stops this here, with a line that names it and says where to get it.
./providers.sh --check

echo "1/5 Building the sandbox image. The first build takes a few minutes."
docker build -f sandbox/Dockerfile -t shellblocks-sandbox:0.1.0 .

echo "2/5 Making the workspace."
openshell workspace create --name shellblocks 2>/dev/null || true

echo "3/5 Making the providers."
./providers.sh

echo "4/5 Creating the sandbox."
# The agent's settings go into the sandbox as one environment variable, as JSON.
AGENT_CONFIG_JSON="$(python3 -c 'import json,yaml;print(json.dumps(yaml.safe_load(open("agent_config.yaml"))))')"
# Switchyard's routes, which say where each of the agent's model calls goes, go in as one line of
# base64, with the port that Switchyard listens on beside the agent.
SWITCHYARD_ROUTES_B64="$(python3 -c 'import base64;print(base64.b64encode(open("switchyard.toml","rb").read()).decode())')"
# Only the providers named below are attached. The telemetry settings keep the agent from making
# calls that the policy would block.
openshell sandbox create \
  --workspace shellblocks \
  --name my-agent \
  --from shellblocks-sandbox:0.1.0 \
  --policy policy.yaml \
  --provider nvidia \
  --provider tavily \
  --env AGENT_CONFIG_JSON="$AGENT_CONFIG_JSON" \
  --env SWITCHYARD_ROUTES_B64="$SWITCHYARD_ROUTES_B64" \
  --env SWITCHYARD_PORT=4000 \
  --env LANGSMITH_TRACING=false \
  --env LANGCHAIN_TRACING_V2=false \
  --env LANGGRAPH_CLI_NO_ANALYTICS=1 \
  --env LANGGRAPH_NO_VERSION_CHECK=true \
  --env DO_NOT_TRACK=1 \
  --no-auto-providers --no-credential-warnings --detach \
  -- start-agent

echo "5/5 Opening a tunnel to the agent."
# The tunnel stays open while this script runs.
openshell forward service my-agent --workspace shellblocks --target-port 2024 --local 127.0.0.1:2025 &
FORWARD_PID=$!
trap 'kill "$FORWARD_PID" 2>/dev/null || true' EXIT

ready=no
for ((attempt = 0; attempt < 120; attempt++)); do
  if curl -sf http://127.0.0.1:2025/ok >/dev/null; then
    ready=yes
    break
  fi
  if ! kill -0 "$FORWARD_PID" 2>/dev/null; then
    echo "The tunnel closed. Is something else using port 2025 on this machine?" >&2
    exit 1
  fi
  sleep 1
done
if [ "$ready" != yes ]; then
  echo "The agent did not answer within 120 seconds. To see why, run:" >&2
  echo "  openshell logs my-agent --tail --source sandbox --workspace shellblocks" >&2
  exit 1
fi

echo
echo "Your agent is running in the sandbox my-agent."
echo
echo "Chat with it from a second terminal, in this folder:"
echo "  . .venv/bin/activate"
echo "  python chat.py"
echo
echo "Or open it in LangGraph Studio:"
echo "  https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2025"
echo
echo "Leave this window open: the tunnel closes when this script ends. Press Ctrl-C to close it."
wait "$FORWARD_PID"
