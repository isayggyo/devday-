"""Install dependencies only for the requested implementation step."""

import argparse
import subprocess

from node_runtime import ROOT, find_node, node_environment
from setup_e2e import project_npm


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", type=int, required=True, choices=[1])
    parser.parse_args()
    python = ROOT / ".venv/Scripts/python.exe"
    packages = [
        "SQLAlchemy>=2.0,<2.1", "psycopg[binary]>=3.2,<4", "alembic>=1.14,<2",
        "pydantic-settings>=2.8,<3", "pytest>=8,<10", "httpx>=0.28,<1",
    ]
    subprocess.run([str(python), "-m", "pip", "install", *packages, "--cache-dir", str(ROOT / ".tools/pip-cache")], cwd=ROOT, check=True)
    node = find_node()
    subprocess.run([node, str(project_npm()), "install", "--save-dev", "--save-exact", "typescript@5.9.3", "@types/react@19", "@types/react-dom@19", "@types/node@24", "--no-audit", "--no-fund"], cwd=ROOT, env=node_environment(node), check=True)
    frozen = subprocess.check_output([str(python), "-m", "pip", "freeze"], text=True)
    (ROOT / "backend/requirements.lock.txt").write_text(frozen, encoding="utf-8")


if __name__ == "__main__":
    main()
