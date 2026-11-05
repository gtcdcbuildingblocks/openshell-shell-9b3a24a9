#!/usr/bin/env bash
# providers.sh: put your API keys in OpenShell Providers.
#
# A Provider is the key vault. The real key stays on this machine. The agent in the sandbox only
# gets a placeholder, and the Supervisor swaps in the real key on requests to the one host the key
# is for.
#
# A Provider is made from a profile, so each profile is imported first. A 0.1.x gateway has no
# built-in profiles. Importing a profile twice is an error, which does no harm here.
#
# Keys are read from the environment, or from .env. Your build needs every one of them, so this
# script names each key that is not set, and then stops, before it makes anything.
# Switchyard does not start in the sandbox without the key of each cloud model it calls.
#
# `./providers.sh --check` checks the keys and makes nothing. run.sh runs it first, so that a key
# that is not set stops it before it builds the image.
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

missing=no
if [ -z "${NVIDIA_API_KEY:-}" ]; then
  echo 'providers.sh: NVIDIA_API_KEY is not set. Your NVIDIA API key, for Nemotron 3.5 Super VL 120B. Get one at https://build.nvidia.com' >&2
  missing=yes
fi
if [ -z "${TAVILY_API_KEY:-}" ]; then
  echo 'providers.sh: TAVILY_API_KEY is not set. Your Tavily API key, for Web Search. Get one at https://app.tavily.com' >&2
  missing=yes
fi
if [ "$missing" = yes ]; then
  echo "providers.sh: no provider was made. Put the keys named above in .env, as env.example shows, and try again." >&2
  exit 1
fi
if [ "${1:-}" = --check ]; then
  exit 0
fi

# nvidia
openshell provider profile import --file sandbox/profiles/nvidia-shellblocks.yaml --workspace shellblocks 2>/dev/null || true
openshell provider create --name nvidia --type nvidia-shellblocks --credential NVIDIA_API_KEY --workspace shellblocks \
  || echo "providers.sh: the nvidia provider was not created. It may exist already."

# tavily
openshell provider profile import --file sandbox/profiles/tavily-shellblocks.yaml --workspace shellblocks 2>/dev/null || true
openshell provider create --name tavily --type tavily-shellblocks --credential TAVILY_API_KEY --workspace shellblocks \
  || echo "providers.sh: the tavily provider was not created. It may exist already."
