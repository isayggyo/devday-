"""Exercise harness guards and real-browser error/media observations."""

import subprocess

from node_runtime import ROOT, find_node, node_environment


if __name__ == "__main__":
    node = find_node()
    files = sorted(str(path) for path in (ROOT / "e2e/tests").glob("*.test.mjs"))
    result = subprocess.run([node, "--test", *files], cwd=ROOT, env=node_environment(node))
    raise SystemExit(result.returncode)
