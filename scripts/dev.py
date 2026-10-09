"""Start/stop the project's local development servers without visible windows."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import socket
import time
import urllib.request

from node_runtime import ROOT, find_node, node_environment
from local_postgres import start as start_postgres
from local_storage import start as start_storage

STATE = ROOT / ".tools/dev/servers.json"


def process_identity(pid):
    script = f"Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}' | Select-Object ProcessId,CreationDate,ExecutablePath | ConvertTo-Json -Compress"
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return json.loads(result.stdout) if result.stdout.strip() else None


def start(e2e=False):
    if STATE.exists():
        raise SystemExit("Server state exists. Stop the development servers before starting again.")
    for port in (8000, 3000):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"Port {port} is already in use; existing processes were left running.")
    start_postgres()
    start_storage()
    subprocess.run([str(ROOT / ".venv/Scripts/python.exe"), "-m", "backend.migrate"], cwd=ROOT, check=True)
    node = find_node()
    environment = node_environment(node)
    environment.update({"NEXT_TELEMETRY_DISABLED": "1", "E2E_MODE": "1" if e2e else "0", "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    commands = [
        ("backend", [str(ROOT / ".venv/Scripts/python.exe"), "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "8000"]),
        ("frontend", [node, str(ROOT / "node_modules/next/dist/bin/next"), "dev", str(ROOT / "frontend"), "--webpack", "--hostname", "127.0.0.1", "--port", "3000"]),
    ]
    STATE.parent.mkdir(parents=True, exist_ok=True)
    logs = ROOT / "artifacts/dev"
    logs.mkdir(parents=True, exist_ok=True)
    processes = []
    for label, command in commands:
        with (logs / (label + ".log")).open("ab") as output:
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
        identity = process_identity(process.pid)
        if not identity:
            raise RuntimeError(f"{label} exited immediately; inspect artifacts/dev/{label}.log")
        processes.append({"name": label, "pid": process.pid, "identity": identity})
        STATE.write_text(json.dumps(processes), encoding="utf-8")
    STATE.write_text(json.dumps(processes), encoding="utf-8")
    try:
        for url in ("http://127.0.0.1:8000/health", "http://127.0.0.1:3000/api/backend-health"):
            deadline = time.monotonic() + 60
            while True:
                try:
                    with urllib.request.urlopen(url, timeout=5) as response:
                        payload = json.load(response)
                    if payload.get("database") == "ok":
                        break
                except Exception:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("Development server health check failed; inspect artifacts/dev")
                time.sleep(0.5)
    except Exception:
        stop()
        raise
    print("Development servers ready: http://127.0.0.1:3000 ; logs: artifacts/dev")


def stop():
    if not STATE.exists():
        return
    for process in json.loads(STATE.read_text(encoding="utf-8")):
        # PID + creation time + executable prevent killing a reused PID or unrelated process.
        current = process_identity(process["pid"])
        if current and current == process.get("identity"):
            subprocess.run(["taskkill", "/PID", str(int(process["pid"])), "/T", "/F"], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    STATE.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "stop"])
    parser.add_argument("--e2e", action="store_true")
    arguments = parser.parse_args()
    start(arguments.e2e) if arguments.command == "start" else stop()
