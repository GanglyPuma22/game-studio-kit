#!/bin/bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
JOB=${JOB_ROOT:-/content/job}
MPLBACKEND=Agg exec /content/speech-env/bin/python "$HERE/worker.py" "$HERE/plan.json" /content/speech-model "$OUT_DIR" "$JOB/inputs"
