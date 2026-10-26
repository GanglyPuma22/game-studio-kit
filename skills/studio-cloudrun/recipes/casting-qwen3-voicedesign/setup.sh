#!/bin/bash
# Qwen3-TTS on a Colab runtime: Python 3.12 through uv, torch for CUDA 12.8,
# the engine at its pinned commit (its own pins: transformers 4.57.3,
# accelerate 1.12.0). Weights come later, in run.sh, checked file by file.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ENVDIR=/content/speech-env
python3 -m pip install -q uv
rm -rf "$ENVDIR"  # recipes share this path with different pins: start clean
uv venv -q --python 3.12 "$ENVDIR"
PY="$ENVDIR/bin/python"
COMMIT=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['model']['commit'])" "$HERE/recipe.json")
uv pip install -q --python "$PY" torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install -q --python "$PY" "qwen-tts @ git+https://github.com/QwenLM/Qwen3-TTS.git@$COMMIT" soundfile==0.13.1
MPLBACKEND=Agg "$PY" -c "import torch, soundfile; from qwen_tts import Qwen3TTSModel; assert torch.cuda.is_available(); print('imports ok', torch.__version__, torch.cuda.get_device_name(0))"
