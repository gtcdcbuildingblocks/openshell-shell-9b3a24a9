"""The agent's Files and Shell tools: one backend for both."""

from __future__ import annotations

import os

from deepagents.backends import LocalShellBackend


def make_backend() -> LocalShellBackend:
    """Files and Shell on the real filesystem, starting in the working folder, with the full
    environment, so the shell keeps the sandbox's proxy and certificate variables.

    Virtual mode stays off. In a sandbox the kernel is the enforcer: a path the filesystem policy
    forbids has to reach the kernel to be refused with "Permission denied". In virtual mode the
    Files tools would map /srv/... into the working folder and answer "not found" first. The Shell
    tool sees the real filesystem either way, so this opens nothing new.
    """
    return LocalShellBackend(root_dir=os.getcwd(), virtual_mode=False, inherit_env=True)
