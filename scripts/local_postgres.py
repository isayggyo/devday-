"""Project-local PostgreSQL for Windows; no system service or global installation."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools/postgres"
DATA = ROOT / "infra/data/postgres"
STATE = ROOT / "infra/data/postgres-config.json"
BIN = TOOLS / "pgsql/bin"
URL = "https://get.enterprisedb.com/postgresql/postgresql-17.11-3-windows-x64-binaries.zip"


def native_root():
    if str(ROOT).isascii():
        return ROOT
    alias = Path(tempfile.gettempdir()) / ("gyeol-pg-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:12])
    if alias.exists():
        if not os.path.samefile(alias, ROOT):
            raise RuntimeError("Temporary PostgreSQL alias belongs to another directory")
    else:
        def literal(value):
            return "'" + str(value).replace("'", "''") + "'"
        command = f"New-Item -ItemType Junction -Path {literal(alias)} -Target {literal(ROOT)} | Out-Null"
        subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return alias


def native_arguments(arguments):
    alias = native_root()
    return [str(alias / value.relative_to(ROOT)) if isinstance(value, Path) and value.is_relative_to(ROOT) else str(value) for value in arguments]


def configuration():
    if not STATE.exists():
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({"port": 55432, "user": "lecture", "password": secrets.token_urlsafe(32)}), encoding="utf-8")
    return json.loads(STATE.read_text(encoding="utf-8"))


def run(arguments, **kwargs):
    if "start" in arguments and any(str(value).endswith("pg_ctl.exe") for value in arguments):
        # A Windows daemon may inherit pipe handles, preventing communicate() from finishing.
        output_path = ROOT / "artifacts/infra/pg-start.log"
        with output_path.open("wb") as output:
            result = subprocess.run(native_arguments(arguments), cwd=native_root(), stdin=subprocess.DEVNULL, stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW, timeout=40, **kwargs)
        message = output_path.read_text(encoding="utf-8", errors="replace")
        if result.returncode:
            raise RuntimeError(message.strip())
        return message.strip()
    result = subprocess.run(native_arguments(arguments), cwd=native_root(), capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW, **kwargs)
    if result.returncode:
        # The supplied command lines never contain database passwords.
        raise RuntimeError((result.stdout + result.stderr).strip())
    return result.stdout.strip()


def install():
    if (BIN / "postgres.exe").exists():
        return
    TOOLS.mkdir(parents=True, exist_ok=True)
    archive = TOOLS / "postgres.zip"
    if not archive.exists():
        print("Downloading official EDB PostgreSQL binaries into .tools/postgres", flush=True)
        with urllib.request.urlopen(URL, timeout=60) as response, archive.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            target = (TOOLS / entry.filename).resolve()
            if not target.is_relative_to(TOOLS.resolve()):
                raise RuntimeError("Archive contains an unexpected path")
        bundle.extractall(TOOLS)
    print("PostgreSQL binaries ready", flush=True)


def start():
    install()
    settings = configuration()
    DATA.parent.mkdir(parents=True, exist_ok=True)
    if not (DATA / "PG_VERSION").exists():
        password_file = STATE.parent / "postgres-password"
        password_file.write_text(settings["password"] + "\n", encoding="utf-8")
        try:
            run([BIN / "initdb.exe", "-D", DATA, "-U", settings["user"], "-A", "scram-sha-256", "-E", "UTF8", "--locale=C", "--pwfile", password_file])
        finally:
            password_file.unlink(missing_ok=True)
    status = subprocess.run(native_arguments([BIN / "pg_ctl.exe", "status", "-D", DATA]), capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    if status.returncode:
        log = ROOT / "artifacts/infra/postgres.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        run([BIN / "pg_ctl.exe", "start", "-D", DATA, "-l", log, "-o", f"-h 127.0.0.1 -p {settings['port']}", "-w", "-t", "30"])
    environment = os.environ.copy()
    environment["PGPASSWORD"] = settings["password"]
    for database in ("lecture_dev", "lecture_test"):
        exists = run([BIN / "psql.exe", "-h", "127.0.0.1", "-p", settings["port"], "-U", settings["user"], "-d", "postgres", "-tAc", f"SELECT 1 FROM pg_database WHERE datname='{database}'"], env=environment)
        if exists != "1":
            run([BIN / "createdb.exe", "-h", "127.0.0.1", "-p", settings["port"], "-U", settings["user"], database], env=environment)
    env_file = ROOT / ".env"
    if not env_file.exists():
        env_file.write_text(
            "APP_ENV=development\nAUTH_MODE=development\n"
            f"DATABASE_URL=postgresql+psycopg://{settings['user']}:{settings['password']}@127.0.0.1:{settings['port']}/lecture_dev\n"
            f"TEST_DATABASE_URL=postgresql+psycopg://{settings['user']}:{settings['password']}@127.0.0.1:{settings['port']}/lecture_test\n"
            "FRONTEND_ORIGIN=http://127.0.0.1:3000\nAPI_BASE_URL=http://127.0.0.1:8000\n",
            encoding="utf-8",
        )
    print(f"PostgreSQL ready at 127.0.0.1:{settings['port']}; dev/test databases prepared; credentials stay in ignored .env", flush=True)


def main():
    if os.name != "nt":
        raise SystemExit("Use your PostgreSQL service or Docker on this platform and set DATABASE_URL.")
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["install", "start", "stop", "status"])
    command = parser.parse_args().command
    if command == "install":
        install()
    elif command == "start":
        start()
    elif command == "stop":
        if (DATA / "postmaster.pid").exists():
            run([BIN / "pg_ctl.exe", "stop", "-D", DATA, "-m", "fast", "-w"])
    else:
        print(run([BIN / "pg_ctl.exe", "status", "-D", DATA]))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
