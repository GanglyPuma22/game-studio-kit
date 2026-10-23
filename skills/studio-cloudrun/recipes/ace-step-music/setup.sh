#!/bin/bash
# ACE-Step 1.5 on a Colab runtime: the upstream repo at its pinned commit and
# its own locked environment (Python 3.12 through uv).
set -euo pipefail
R=/content/ace
COMMIT=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['model']['commit'])" "$(dirname "$0")/recipe.json")
mkdir -p "$R"
git clone -q --depth 1 https://github.com/ace-step/ACE-Step-1.5.git "$R/ACE-Step-1.5"
git -C "$R/ACE-Step-1.5" fetch -q --depth 1 origin "$COMMIT"
git -C "$R/ACE-Step-1.5" checkout -q --detach "$COMMIT"
python3 -m pip install -q uv
(cd "$R/ACE-Step-1.5" && uv sync -q --python 3.12)
(cd "$R/ACE-Step-1.5" && MPLBACKEND=Agg uv run --no-sync python -c "import torch, soundfile; from acestep.handler import AceStepHandler; assert torch.cuda.is_available(); print('imports ok', torch.__version__, torch.cuda.get_device_name(0))")
