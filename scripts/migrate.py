"""Apply versioned PostgreSQL migrations, optionally to the separate test database."""
import argparse
import os
import subprocess
import sys

from node_runtime import ROOT



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    arguments = parser.parse_args()
    environment = os.environ.copy()
    subprocess.run([str(ROOT / ".venv/Scripts/python.exe"), "-m", "backend.migrate", *(["--test"] if arguments.test else [])], cwd=ROOT, env=environment, check=True)
    print("Test database migrated" if arguments.test else "Development database migrated")


if __name__ == "__main__":
    main()
