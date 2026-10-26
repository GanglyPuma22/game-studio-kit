#!/bin/bash
# Stable Audio Open on a Colab runtime: pinned Python 3.12 environment, then
# the weights the host staged (weights.json: short-lived links or inline bytes,
# each with its SHA-256). No account token is ever on this machine.
# Learned: Colab's default Python was 3.13 and venv bootstrap failed (use uv);
# the scheduler needs torchsde; check imports before the 5 GB download.
set -euo pipefail
JOB=${JOB_ROOT:-/content/job}
ENVDIR=/content/sao-env
MODEL=/content/sao-model
python3 -m pip install -q uv
uv venv -q --python 3.12 "$ENVDIR"
PY="$ENVDIR/bin/python"
uv pip install -q --python "$PY" torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install -q --python "$PY" diffusers==0.35.2 transformers==4.57.1 accelerate==1.11.0 soundfile==0.13.1 \
	sentencepiece==0.2.1 torchsde==0.2.6 scipy==1.16.3 protobuf==6.33.0 numpy
MPLBACKEND=Agg "$PY" -c "import torch, diffusers, torchsde, soundfile, sentencepiece; from diffusers import StableAudioPipeline; assert torch.cuda.is_available(); print('imports ok', torch.__version__, diffusers.__version__, torch.cuda.get_device_name(0))"
"$PY" "$(dirname "$0")/fetch_weights.py" "$JOB/weights.json" "$MODEL"
