"""Run a real loopback-only SeaweedFS S3 object store with private credentials."""
import argparse
import json
import os
import secrets
import socket
import subprocess
import time

from node_runtime import ROOT
from material_tools import install_weed

STATE = ROOT / "infra/data/storage-process.json"
CONFIG = ROOT / "infra/data/storage-config.json"


def identity(pid):
    command = f"Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}' | Select-Object ProcessId,CreationDate,ExecutablePath | ConvertTo-Json -Compress"
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return json.loads(result.stdout) if result.stdout.strip() else None


def start():
    install_weed()
    if STATE.exists():
        recorded = json.loads(STATE.read_text(encoding="utf-8"))
        if identity(recorded["ProcessId"]) == recorded:
            print("Local S3 object store already running", flush=True)
            return
        STATE.unlink()
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 8333)) == 0:
            raise RuntimeError("S3 port 8333 belongs to an existing process")
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG.exists():
        credential = {"accessKey": "lecture-" + secrets.token_hex(8), "secretKey": secrets.token_urlsafe(40)}
        CONFIG.write_text(json.dumps({"identities": [{"name": "lecture", "credentials": [credential], "actions": ["Admin", "Read", "Write", "List", "Tagging"]}]}), encoding="utf-8")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    credential = config["identities"][0]["credentials"][0]
    env_file = ROOT / ".env"
    content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    if "S3_ACCESS_KEY=" not in content:
        with env_file.open("a", encoding="utf-8") as output:
            output.write(f"\nS3_ENDPOINT=http://127.0.0.1:8333\nS3_ACCESS_KEY={credential['accessKey']}\nS3_SECRET_KEY={credential['secretKey']}\nS3_BUCKET=lecture-dev\nS3_TEST_BUCKET=lecture-test\n")
    data = ROOT / "infra/data/objects"
    data.mkdir(parents=True, exist_ok=True)
    log = ROOT / "artifacts/infra/storage.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [str(ROOT / ".tools/seaweedfs/weed.exe"), "mini", "-dir=" + str(data), "-ip=127.0.0.1", "-ip.bind=127.0.0.1", "-s3.port=8333", "-s3.config=" + str(CONFIG), "-s3.port.iceberg=0", "-s3.port.lance=0", "-webdav=false"]
    environment = os.environ.copy()
    # Go's flag package reads DEBUG; the parent development runtime uses DEBUG=release.
    environment.pop("DEBUG", None)
    environment.pop("debug", None)
    with log.open("ab") as output:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW)
    metadata = identity(process.pid)
    if not metadata:
        raise RuntimeError("Object store exited; inspect private artifacts/infra/storage.log")
    STATE.write_text(json.dumps(metadata), encoding="utf-8")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        check = subprocess.run([str(ROOT / ".venv/Scripts/python.exe"), "-m", "backend.storage"], cwd=ROOT, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if check.returncode == 0:
            print("Real S3 object store ready: 127.0.0.1:8333; development/test buckets initialized", flush=True)
            return
        if process.poll() is not None:
            raise RuntimeError("Object store exited; inspect private artifacts/infra/storage.log")
        time.sleep(0.5)
    stop()
    raise RuntimeError("Object storage health check timed out; inspect private artifacts/infra/storage.log")


def stop():
    if STATE.exists():
        recorded = json.loads(STATE.read_text(encoding="utf-8"))
        if identity(recorded["ProcessId"]) == recorded:
            subprocess.run(["taskkill", "/PID", str(recorded["ProcessId"]), "/T", "/F"], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        STATE.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "stop"])
    args = parser.parse_args()
    start() if args.command == "start" else stop()
