# The sandbox image OpenShell runs: Python 3.13 and Node 22, the agent, its MCP servers, the baseline
# policy, and decoy data. The build context is the repository root, so every COPY path is repo-relative:
#
#   docker build -f sandbox/Dockerfile -t shellblocks-sandbox:0.1.0 .
#
# scripts/build_image.sh regenerates sandbox/requirements.txt from uv.lock, then runs that build with
# the tag from ShellConfig. A policy rule names a program by the path the kernel reports for it, and
# tests/test_image.py checks that python, node, and curl resolve to the paths that
# shellblocks/policy/catalog.py pins.
FROM python:3.13-slim-bookworm

# Node 22, copied from the official image: the binary, the global modules, and the npm and npx links.
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# iproute2 is not in the slim base. The OpenShell supervisor builds the sandbox's network namespace with
# its `ip` command, and its error for a missing one says to install iproute2.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates git iproute2 \
    && rm -rf /var/lib/apt/lists/*

# The user the baseline policy runs the agent as.
RUN groupadd -g 1000 sandbox \
    && useradd -u 1000 -g 1000 -d /sandbox -m -s /bin/bash sandbox

# The Web Search tool's MCP server, which puts `tavily-mcp` on PATH.
RUN npm install -g tavily-mcp@0.2.17 \
    && npm cache clean --force

# The agent's Python packages, installed into the system Python so that python3.13 itself is the
# program every rule names.
COPY sandbox/requirements.txt /tmp/requirements.txt
RUN uv pip install --system --no-cache -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY agent/ /opt/shellblocks/agent/
COPY shellblocks_mcp/ /opt/shellblocks/shellblocks_mcp/
COPY langgraph.json /opt/shellblocks/langgraph.json
COPY shellblocks/policy/baseline.yaml /etc/openshell/policy.yaml

# Decoy data, all fictional. The notes sit in the workspace the agent may read and write. The payroll
# file is readable by every user on purpose, so that only the filesystem policy keeps the agent out.
COPY sandbox/decoys/notes.md /sandbox/workspace/notes.md
COPY sandbox/decoys/payroll.csv /srv/company-records/payroll.csv

COPY sandbox/start-agent.sh /usr/local/bin/start-agent

# Set owners and modes here, so that they do not depend on the modes of the files in the checkout.
RUN chown sandbox:sandbox /sandbox/workspace /sandbox/workspace/notes.md \
        /srv/company-records /srv/company-records/payroll.csv \
    && chmod 755 /sandbox/workspace /srv/company-records \
    && chmod 644 /sandbox/workspace/notes.md /srv/company-records/payroll.csv \
    && chmod -R a+rX,go-w /opt/shellblocks /etc/openshell \
    && chmod 755 /usr/local/bin/start-agent

ENV HOME=/sandbox PYTHONPATH=/opt/shellblocks PYTHONUNBUFFERED=1
USER sandbox
WORKDIR /sandbox/workspace
