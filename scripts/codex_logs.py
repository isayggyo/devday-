"""Collect project-scoped public Codex transcript events without dependencies."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "logs" / "runtime"
OUTPUT = ROOT / "logs" / "codex"
START = "2026-10-09T01:28:01.041Z"
KST = timezone(timedelta(hours=9))


def now():
    return datetime.now(timezone.utc).isoformat()


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def config():
    path = RUNTIME / "config.json"
    if not path.exists():
        write_json(path, {
            "started_at": START,
            "project_root": str(ROOT),
            "codex_home": str(Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))),
            "interval_seconds": 5,
        })
    return json.loads(path.read_text(encoding="utf-8"))


def in_project(cwd, root):
    if not cwd:
        return False
    candidate = os.path.normcase(os.path.abspath(cwd))
    project = os.path.normcase(os.path.abspath(root))
    try:
        return os.path.commonpath([candidate, project]) == project
    except ValueError:
        return False


def public_record(row):
    payload = row.get("payload", {})
    kind = row.get("type")
    subtype = payload.get("type")
    if kind == "session_meta":
        keys = ("id", "session_id", "timestamp", "cwd", "originator", "cli_version", "source", "model_provider")
        return {**row, "payload": {key: payload[key] for key in keys if key in payload}}
    if kind == "event_msg" and subtype in {
        "user_message", "agent_message", "task_started", "task_complete",
        "task_aborted", "token_count", "web_search_end",
    }:
        return row
    if kind == "response_item":
        if subtype == "message":
            if payload.get("role") in {"user", "assistant"} and payload.get("channel") != "analysis":
                return row
        elif subtype in {
            "function_call", "function_call_output", "custom_tool_call",
            "custom_tool_call_output", "web_search_call",
        }:
            return row
    if kind == "token_usage_record":
        return row
    return None


def collect(settings):
    cutoff = stamp(settings["started_at"])
    source_home = Path(settings["codex_home"])
    sources = set()
    for directory in (source_home / "sessions", source_home / "archived_sessions"):
        if directory.exists():
            sources.update(directory.rglob("*.jsonl"))
    collected = []
    errors = []
    for source in sorted(sources):
        try:
            with source.open("rb") as handle:
                first = handle.readline()
                meta = json.loads(first)
                if meta.get("type") != "session_meta" or not in_project(meta.get("payload", {}).get("cwd"), settings["project_root"]):
                    continue
                records = [public_record(meta)]
                for line in handle:
                    # A live writer may not have finished its last line yet.
                    if not line.endswith(b"\n"):
                        break
                    row = json.loads(line)
                    if row.get("timestamp") and stamp(row["timestamp"]) >= cutoff:
                        visible = public_record(row)
                        if visible is not None:
                            records.append(visible)
            if len(records) == 1:
                continue
            data = b"".join((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8") for row in records)
            target = OUTPUT / source.name
            if not target.exists() or target.read_bytes() != data:
                atomic_write(target, data)
            collected.append({"file": target.name, "records": len(records), "bytes": len(data)})
        except (OSError, ValueError) as error:
            errors.append({"file": source.name, "error": str(error)})
    result = {"collected_at": now(), "started_at": settings["started_at"], "sessions": collected, "errors": errors}
    write_json(RUNTIME / "manifest.json", result)
    return result


def status():
    path = RUNTIME / "watcher.json"
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    active = value.get("running", False) and time.time() - stamp(value["heartbeat"]).timestamp() < 20
    manifest_path = RUNTIME / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    return {"active": active, "watcher": value, "collection": manifest}


def watch(settings):
    try:
        while not (RUNTIME / "stop").exists():
            result = collect(settings)
            write_json(RUNTIME / "watcher.json", {"pid": os.getpid(), "running": True, "heartbeat": now(), "errors": result["errors"]})
            time.sleep(settings["interval_seconds"])
    finally:
        write_json(RUNTIME / "watcher.json", {"pid": os.getpid(), "running": False, "heartbeat": now()})


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "watch", "collect", "status", "export", "stop"))
    command = parser.parse_args().command
    settings = config()
    if command == "watch":
        watch(settings)
    elif command == "start":
        if not status()["active"]:
            (RUNTIME / "stop").unlink(missing_ok=True)
            options = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
            with (RUNTIME / "watcher-output.log").open("ab") as output:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "watch"], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=output, close_fds=True, **options)
            print(json.dumps({"started_pid": process.pid, "log_directory": str(OUTPUT)}, ensure_ascii=False))
        else:
            print(json.dumps(status(), ensure_ascii=False, indent=2))
    elif command == "collect":
        print(json.dumps(collect(settings), ensure_ascii=False, indent=2))
    elif command == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=2))
    elif command == "stop":
        (RUNTIME / "stop").touch()
        print("Collector stop requested; original Codex logging continues.")
    elif command == "export":
        result = collect(settings)
        if result["errors"] or not result["sessions"]:
            raise SystemExit("Export cancelled: collection is empty or has errors. Run status.")
        destination = ROOT / "logs" / "exports" / ("codex-logs-" + datetime.now(KST).strftime("%Y%m%d-%H%M%S") + ".zip")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
            for entry in result["sessions"]:
                archive.write(OUTPUT / entry["file"], "codex/" + entry["file"])
            archive.writestr("manifest.json", json.dumps(result, ensure_ascii=False, indent=2))
            archive.write(ROOT / "docs" / "work-log.md", "work-log.md")
        print(destination)


if __name__ == "__main__":
    main()
