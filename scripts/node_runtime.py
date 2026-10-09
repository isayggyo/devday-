"""Resolve a normal Node installation or this machine's existing local runtime."""

import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def find_node():
    candidates = [
        os.environ.get("E2E_NODE"),
        shutil.which("node"),
        str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            version = subprocess.check_output([candidate, "--version"], text=True).strip()
            numbers = tuple(int(part) for part in version.lstrip("v").split("."))
            if numbers < (22, 12, 0):
                raise RuntimeError(f"Node >=22.12.0 required; found {version}")
            return str(Path(candidate).resolve())
    raise RuntimeError("Node >=22.12.0 not found. Install Node or set E2E_NODE to node.exe.")


def node_environment(node):
    environment = os.environ.copy()
    environment["PATH"] = str(Path(node).parent) + os.pathsep + environment.get("PATH", "")
    return environment
