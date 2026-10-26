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
# wetext 0.0.4 (CosyVoice's pin) downloads its grammars from modelscope.cn at
# first use, which refuses anonymous downloads; 0.1.8 ships them in the wheel
# and keeps the same Normalizer API.
grep -v -E '^(tensorrt|deepspeed|gradio|fastapi|uvicorn)' "$R/requirements.txt" | sed 's/^wetext==.*/wetext==0.1.8/' > "$HERE/requirements.txt"
grep -qx 'wetext==0.1.8' "$HERE/requirements.txt" || { echo "CosyVoice no longer pins wetext: check the frontend" >&2; exit 1; }
# openai-whisper 20231117 builds from source and its setup.py imports
# pkg_resources, which setuptools 81 removed: keep build envs below 81.
echo "setuptools<81" > "$HERE/build-constraints.txt"
uv pip install -q --python "$PY" -r "$HERE/requirements.txt" --index-strategy unsafe-best-match --build-constraints "$HERE/build-constraints.txt"
cd "$R" && PYTHONPATH="$R:$R/third_party/Matcha-TTS" MPLBACKEND=Agg "$PY" -c "import torch, soundfile, wetext; from cosyvoice.cli.cosyvoice import CosyVoice3; from wetext import Normalizer; Normalizer(lang='en'); assert torch.cuda.is_available(); print('imports ok', torch.__version__, torch.cuda.get_device_name(0))"
