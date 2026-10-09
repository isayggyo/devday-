"""Install project-local JS/Python dependencies; never downloads a browser."""

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request

from node_runtime import ROOT, find_node, node_environment

NPM_VERSION = "11.6.2"


def project_npm():
    destination = ROOT / ".tools/npm"
    cli = destination / "package/bin/npm-cli.js"
    if cli.is_file():
        return cli
    with urllib.request.urlopen(f"https://registry.npmjs.org/npm/{NPM_VERSION}", timeout=30) as response:
        metadata = json.load(response)
    with urllib.request.urlopen(metadata["dist"]["tarball"], timeout=60) as response:
        archive = response.read()
    expected = metadata["dist"]["integrity"].split("-", 1)
    if expected[0] != "sha512" or base64.b64encode(hashlib.sha512(archive).digest()).decode() != expected[1]:
        raise RuntimeError("npm archive integrity check failed")
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        for member in bundle.getmembers():
            resolved = (destination / member.name).resolve()
            if not resolved.is_relative_to(destination.resolve()) or not (member.isfile() or member.isdir()):
                raise RuntimeError("Unexpected archive path or link")
        bundle.extractall(destination)
    return cli


def main():
    node = find_node()
    environment = node_environment(node)
    environment.update({
        "PUPPETEER_SKIP_DOWNLOAD": "true",
        "NEXT_TELEMETRY_DISABLED": "1",
        "npm_config_cache": str(ROOT / ".tools/npm-cache"),
    })
    # Use npm's JS entrypoint even on Windows, without shell command interpolation.
    npm_cli = project_npm()
    action = "ci" if (ROOT / "package-lock.json").exists() else "install"
    subprocess.run([node, str(npm_cli), action, "--no-audit", "--no-fund"], cwd=ROOT, env=environment, check=True)
    virtualenv = ROOT / ".venv"
    python = virtualenv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(virtualenv)], cwd=ROOT, check=True)
    requirements = ROOT / "backend/requirements.lock.txt"
    if not requirements.exists():
        requirements = ROOT / "backend/requirements.txt"
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(requirements), "--cache-dir", str(ROOT / ".tools/pip-cache")], cwd=ROOT, check=True)
    print("Ready. Run: python scripts/run_e2e.py --runs=3", flush=True)


if __name__ == "__main__":
    main()
