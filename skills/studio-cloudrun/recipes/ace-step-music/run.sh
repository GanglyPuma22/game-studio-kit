#!/bin/bash
# MPLBACKEND=Agg: Colab's inline matplotlib backend is missing inside the uv env.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
cd /content/ace/ACE-Step-1.5
MPLBACKEND=Agg exec uv run --no-sync python "$HERE/worker.py" "$HERE/plan.json" "$HERE/recipe.json" "$OUT_DIR"
