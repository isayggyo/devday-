"""Real AI browser integration through Step 9, deliberately excluding Step 10."""
import subprocess
import sys
from node_runtime import ROOT, find_node, node_environment

if __name__ == '__main__':
    node = find_node()
    raise SystemExit(subprocess.run([node, str(ROOT/'e2e/transcription.mjs'), '--questions', '--visuals', *sys.argv[1:]],
        cwd=ROOT, env=node_environment(node)).returncode)
