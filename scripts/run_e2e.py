"""Usage: python scripts/run_e2e.py --runs=3 (all arguments pass to Puppeteer)."""

import subprocess
import sys

from node_runtime import ROOT, find_node, node_environment


if __name__ == "__main__":
    try:
        node = find_node()
        result = subprocess.run(
            [node, str(ROOT / "e2e/smoke.mjs"), *sys.argv[1:]],
            cwd=ROOT,
            env=node_environment(node),
        )
        raise SystemExit(result.returncode)
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
