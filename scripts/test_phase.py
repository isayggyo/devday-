"""Run the current phase step's backend, frontend, and browser validations."""

import argparse
import os
import subprocess

from node_runtime import ROOT, find_node, node_environment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", type=int, required=True, choices=[1, 2])
    step = parser.parse_args().step
    node = find_node()
    environment = node_environment(node)
    environment["PYTHONIOENCODING"] = "utf-8"
    commands = [
        [str(ROOT / ".venv/Scripts/python.exe"), "-m", "pytest", *( ["backend/tests/test_foundation.py"] if step == 1 else ["backend/tests"]), "-q"],
        [node, "--experimental-strip-types", "--test", "frontend/tests/api.test.ts"],
        [node, "node_modules/typescript/bin/tsc", "--project", "frontend/tsconfig.json", "--noEmit"],
        [node, "e2e/foundation.mjs" if step == 1 else "e2e/sessions.mjs"],
    ]
    for command in commands:
        subprocess.run(command, cwd=ROOT, env=environment, check=True)


if __name__ == "__main__":
    main()
