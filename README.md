# Your agent in its OpenShell shell

At the booth your agent thought with Nemotron 3.5 Lightning and GPT-6 Astra. GPT-6 Astra ran on NVIDIA's internal Inference Hub, which you can't reach from home, so this repo gives your agent **Nemotron 3.5 Lightning** on your own machine for the routine steps and **Nemotron 3.5 Super VL 120B** at build.nvidia.com, with your own NVIDIA API key, for the hard ones; NeMo Switchyard picks between them for each step. Its tools are Files & Shell, Web Fetch, Weather, Web Search.

You put it in a shell made of OpenShell's ten building blocks, and the shell sealed in 4.9 seconds. You built it on 2026-11-05. This folder holds the agent and its tools (`agent/`, `shellblocks_mcp/`, `agent_config.yaml`, and Switchyard's routes in `switchyard.toml`), the shell around it (`sandbox/`, `policy.yaml`), and the scripts that build both again on your own machine (`run.sh`, `providers.sh`).

## What is in the shell

OpenShell keeps an agent in a box and guards the only door. The shell around your agent has ten blocks. Each one keeps its real OpenShell name:

- **Sandbox** (A room with one door): The agent runs as an unprivileged user with no Linux capabilities, in an environment with no network device at all. The only way out is the door.
- **Supervisor** (The guard at the door): Every connection and DNS lookup the agent attempts is handed to the Supervisor, which checks policy, adds credentials if allowed, and opens the connection itself. The agent never talks to the network directly.
- **Gateway** (Mission control): Keeps the policy, the credentials, and the approvals, and talks to the Supervisor over a private channel. The agent cannot reach it.
- **Filesystem policy** (What it may touch): Enforced by the Linux kernel through Landlock: system paths are read-only, only the workspace is writable, and anything not listed is invisible even if file permissions would allow it. It cannot be loosened while running.
- **Process policy** (Who it runs as): The agent runs as a non-root user with no capabilities and no privilege escalation, and dangerous system calls are filtered. Becoming root or installing software system-wide fails.
- **Network policy** (Who it may call): Deny by default: each rule names a program, a host and port, and for web APIs the allowed methods and paths, so reading GitHub can be allowed while writing to it stays blocked. Rules hot-reload, so they can change while the sandbox runs.
- **Provider** (The key vault): Real API keys stay on the host. The agent is given an opaque placeholder, and the Supervisor swaps in the real key only on requests to the endpoint the key is bound to.
- **Inference route** (How it reaches its model): Model calls leave through the same door as everything else. NeMo Switchyard, beside the agent in the sandbox, sends each one to its model's own address: Nemotron 3.5 Lightning at `http://host.openshell.internal:8000/v1`, or Nemotron 3.5 Super VL 120B at `https://integrate.api.nvidia.com/v1`. A cloud model's key stays with its Provider, so the agent never holds it.
- **Approver** (You): Blocked requests become pending rules, and the Policy Prover checks each for risky expansions before you see it. You approve or reject, and approvals hot-reload into the running sandbox.
- **Audit log** (The flight recorder): Every allow and deny is recorded with the program and the destination. The records use the Open Cybersecurity Schema Framework (OCSF), ready for a security team's tools.

## Decisions you made

The shell blocks every host that the policy does not list. Then it asks you whether to allow it.

You made none. No rule was approved or rejected, so `policy.yaml` is exactly as it was sealed.

## Run it

You need Docker, Python 3 with its venv module (the python3-venv package on Debian and Ubuntu), and the OpenShell command line (0.0.116) with a gateway running. See https://docs.nvidia.com/openshell/latest/ for how to set those up. The scripts also use two Python packages. Put them in a virtual environment in this folder:

```
python3 -m venv .venv
. .venv/bin/activate
pip install pyyaml langgraph-sdk
```

Your agent thinks with a model on this machine. Start a server for `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` that speaks the OpenAI API. The sandbox calls it at `http://host.openshell.internal:8000/v1`, where `host.openshell.internal` is the sandbox's name for this machine.

Copy `env.example` to `.env`, and fill in the keys your build needs:

```
cp env.example .env
```

- `NVIDIA_API_KEY`: Your NVIDIA API key, for Nemotron 3.5 Super VL 120B. Get one at https://build.nvidia.com
- `TAVILY_API_KEY`: Your Tavily API key, for Web Search. Get one at https://app.tavily.com

Every key in this list is needed: `./run.sh` stops, and names the key, when one is not set. Switchyard does not start without the key of each cloud model it calls.

1. Run `./run.sh`. It builds the image, makes the workspace and the providers, creates the sandbox `my-agent`, and opens a tunnel to your agent at http://127.0.0.1:2025. Leave it running.
2. In a second terminal, in this folder, run `. .venv/bin/activate`, then `python chat.py` to talk to your agent. Or open LangGraph Studio at https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2025
3. To start over, run `openshell sandbox delete my-agent --workspace shellblocks`, and then `./run.sh` again. Edit `agent_config.yaml` to change the agent, `policy.yaml` to change its rules, or `switchyard.toml` to change which model Switchyard sends each step to, before you do.

## Tested on OpenShell 0.0.116

This shell was sealed and tried on OpenShell 0.0.116. The commands in `run.sh` and `providers.sh` are the ones that version understands. OpenShell 0.1.x changed a few things. If you move to it, change these:

- **Image.** `sandbox create --from` takes only a full image name. Push the image to a registry, and put its full name in `run.sh`.
- **Workspace.** Every command needs `--workspace`. The scripts here already pass it. Do the same for any command you add.
- **No `inference.local`.** The `openshell inference` commands are gone. Your agent already calls its model at the model's own address, with a Provider holding the key for a cloud model, so nothing changes.
- **Policy updates.** `policy update` needs `--rule-name` and every `--binary`.
- **Policy fields.** The fields `harness` and `tls: terminate` are removed, and a field OpenShell does not know is an error. Do not use them in `policy.yaml`.
- **Profiles.** A 0.1.x gateway has no built-in provider profiles. `providers.sh` imports each profile before it creates the provider. Keep that order.

## No secrets

Nothing in this folder is a real key. A key is blank in `env.example`, or it is a placeholder such as `openshell:resolve:env:…` (what the agent sees when a Provider holds the real key), or it is a decoy, such as the made-up key in `sandbox/decoys/notes.md`. `.env` is ignored by git, so your own keys stay on your machine.
