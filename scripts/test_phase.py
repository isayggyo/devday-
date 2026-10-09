"""Run the current phase step's backend, frontend, and browser validations."""

import argparse
import os
import subprocess

from node_runtime import ROOT, find_node, node_environment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", type=int, required=True, choices=range(1, 10))
    step = parser.parse_args().step
    node = find_node()
    environment = node_environment(node)
    environment["PYTHONIOENCODING"] = "utf-8"
    commands = [
        [str(ROOT / ".venv/Scripts/python.exe"), "-m", "pytest", *( ["backend/tests/test_foundation.py"] if step == 1 else ["backend/tests"]), "-q"],
        [node, "--experimental-strip-types", "--test", *[str(path) for path in (ROOT / 'frontend/tests').glob('*.test.ts')]],
        [node, "node_modules/typescript/bin/tsc", "--project", "frontend/tsconfig.json", "--noEmit"],
    ]
    if step != 7:
        commands.append([node, {1: "e2e/foundation.mjs", 2: "e2e/sessions.mjs", 3: "e2e/materials.mjs", 4: "e2e/audio.mjs"}.get(step, 'e2e/transcription.mjs'),
                         *(['--notes'] if step == 6 else ['--questions'] if step == 8 else ['--questions', '--visuals'] if step == 9 else [])])
    for command in commands:
        subprocess.run(command, cwd=ROOT, env=environment, check=True)


if __name__ == "__main__":
    main()
