#!/bin/bash
set -euo pipefail
MPLBACKEND=Agg exec /content/sao-env/bin/python "$(dirname "$0")/worker.py" "$(dirname "$0")/plan.json" /content/sao-model "$OUT_DIR"
