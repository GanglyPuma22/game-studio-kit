#!/bin/bash
# Chatterbox (original English model) on a Colab runtime: Python 3.11 through
# uv, the engine at its pinned commit, Perth (its watermark) at a pinned commit
# instead of upstream's moving master. Weights come later, in run.sh, file by
# file against recipe.json's hashes. No account token is needed or present.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ENVDIR=/content/speech-env
python3 -m pip install -q uv
uv venv -q --python 3.11 "$ENVDIR"
PY="$ENVDIR/bin/python"
COMMIT=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['model']['commit'])" "$HERE/recipe.json")
echo "resemble-perth @ git+https://github.com/resemble-ai/Perth.git@ff1c8ac55a976971245cdd53c18d6131ca00d993" > "$HERE/overrides.txt"
uv pip install -q --python "$PY" --override "$HERE/overrides.txt" \
	"chatterbox-tts @ git+https://github.com/resemble-ai/chatterbox.git@$COMMIT" soundfile==0.13.1
MPLBACKEND=Agg "$PY" -c "import torch, soundfile, perth; from chatterbox.tts import ChatterboxTTS; assert torch.cuda.is_available(); print('imports ok', torch.__version__, torch.cuda.get_device_name(0))"
