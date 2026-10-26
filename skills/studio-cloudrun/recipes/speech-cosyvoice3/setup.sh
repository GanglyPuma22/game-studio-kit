#!/bin/bash
# Fun-CosyVoice3 on a Colab runtime: CosyVoice and Matcha-TTS at their pinned
# commits, Python 3.10 through uv with CosyVoice's own pinned requirements.
# TensorRT and vLLM stay off (not needed for a few takes). Weights come later,
# in run.sh, checked file by file. The text frontend is wetext (ttsfrd is not
# installed); its resources are fetched here, during setup, not mid-run.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
R=/content/cosyvoice; ENVDIR=/content/speech-env
read -r COMMIT MATCHA < <(python3 -c "import json,sys;m=json.load(open(sys.argv[1]))['model'];print(m['commit'],m['submodules']['third_party/Matcha-TTS'])" "$HERE/recipe.json")
rm -rf "$R"  # a fresh checkout each run, so a second run on the same runtime works
git clone -q https://github.com/FunAudioLLM/CosyVoice.git "$R"
git -C "$R" checkout -q --detach "$COMMIT"
git -C "$R" submodule -q update --init third_party/Matcha-TTS
[ "$(git -C "$R/third_party/Matcha-TTS" rev-parse HEAD)" = "$MATCHA" ] || { echo "Matcha-TTS is not at its pinned commit" >&2; exit 1; }
python3 -m pip install -q uv
rm -rf "$ENVDIR"  # recipes share this path with different pins: start clean
uv venv -q --python 3.10 "$ENVDIR"
PY="$ENVDIR/bin/python"
# Not needed here and heavy: TensorRT, deepspeed, the web UI and server.
grep -v -E '^(tensorrt|deepspeed|gradio|fastapi|uvicorn)' "$R/requirements.txt" > "$HERE/requirements.txt"
uv pip install -q --python "$PY" -r "$HERE/requirements.txt" --index-strategy unsafe-best-match
cd "$R" && PYTHONPATH="$R:$R/third_party/Matcha-TTS" MPLBACKEND=Agg "$PY" -c "import torch, soundfile, wetext; from cosyvoice.cli.cosyvoice import CosyVoice3; from wetext import Normalizer; Normalizer(lang='en'); assert torch.cuda.is_available(); print('imports ok', torch.__version__, torch.cuda.get_device_name(0))"
