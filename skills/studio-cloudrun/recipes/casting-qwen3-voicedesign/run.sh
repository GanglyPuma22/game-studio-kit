#!/bin/bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
MPLBACKEND=Agg exec /content/speech-env/bin/python "$HERE/worker.py" "$HERE/plan.json" /content/models/casting-qwen3-voicedesign "$OUT_DIR"
