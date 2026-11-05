"""Switchyard, the model router, beside the agent in the sandbox.

The sandbox's start script runs this module twice before it starts the agent. In the background, it
writes the routes the web app passed in SWITCHYARD_ROUTES_B64 to a file and serves them on loopback.
Then, with --wait, it returns once Switchyard answers. The server is the Rust one that
nemo-switchyard embeds, hosted by python3.13, so the program that calls the models is the one the
sandbox policy's model rules name.
"""

from __future__ import annotations

import argparse
import base64
import os
import signal
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path

import httpx
from switchyard_rust.server import Server

# The routes, as base64 of their TOML, which the web app puts in the sandbox's environment.
ROUTES_ENV = "SWITCHYARD_ROUTES_B64"
# The loopback port Switchyard serves on, the one the agent's proxy URL names.
PORT_ENV = "SWITCHYARD_PORT"
DEFAULT_PORT = 4000
# /tmp is one of the folders the sandbox lets the agent's user write.
ROUTES_PATH = Path("/tmp/switchyard/routes.toml")


def write_routes(environ: Mapping[str, str], path: Path = ROUTES_PATH) -> Path:
    """Write the routes in environ[ROUTES_ENV], decoded from base64, to path, and return path.

    Raises SystemExit when the variable is unset or empty.
    """
    encoded = environ.get(ROUTES_ENV)
    if not encoded:
        raise SystemExit(f"{ROUTES_ENV} is not set")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(encoded))
    return path


def serve(path: Path, port: int, stop: threading.Event | None = None) -> None:
    """Serve the routes in path on 127.0.0.1:port until stop is set, then close the server.

    With no stop, it serves until SIGTERM or SIGINT.
    """
    if stop is None:
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
    server = Server(str(path), port=port)
    try:
        stop.wait()
    finally:
        server.close()


def wait(port: int, timeout_s: float = 20.0) -> None:
    """Return once Switchyard answers its health check on 127.0.0.1:port.

    Raises SystemExit, with a message that names Switchyard and the port, when it has not answered
    within timeout_s seconds.
    """
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            # trust_env off: no proxy variable in the sandbox's environment can send this loopback
            # call through the sandbox's proxy.
            if httpx.get(url, trust_env=False, timeout=1).is_success:
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() >= deadline:
            raise SystemExit(f"Switchyard did not answer on port {port} within {timeout_s:g} s")
        time.sleep(0.2)


def main(argv: list[str] | None = None) -> int:
    """Serve the routes the environment holds, or, with --wait, wait until Switchyard answers.

    The port is SWITCHYARD_PORT's, or DEFAULT_PORT.
    """
    parser = argparse.ArgumentParser(
        prog="python3.13 -m agent.switchyard_server",
        description="Run Switchyard on loopback beside the agent, or wait until it answers.",
    )
    parser.add_argument(
        "--wait", action="store_true", help="return once Switchyard answers, instead of serving"
    )
    args = parser.parse_args(argv)
    port = int(os.environ.get(PORT_ENV, DEFAULT_PORT))
    if args.wait:
        wait(port)
    else:
        serve(write_routes(os.environ), port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
