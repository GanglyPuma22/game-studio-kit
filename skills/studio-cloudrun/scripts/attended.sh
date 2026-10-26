#!/bin/bash
# The free route: run one model-run job on a runtime the person started and
# watches (a Colab notebook on their own account, notebooks/speech-audition.ipynb).
# Nothing here starts, prices or pays for a runtime: the job must say
# "where": "attended" and "max_units": 0.
#   attended.sh JOB.json INPUTS_DIR RESULTS_DIR
# INPUTS_DIR holds the job's inputs (checked against their SHA-256; may be
# empty for casting). RESULTS_DIR gets the outputs and receipt.json, and
# RESULTS_DIR.zip is made for download. Private inputs never land there: a
# result that is a byte copy of one is deleted and the run fails.
set -uo pipefail
JOBFILE=$(realpath "${1:?usage: attended.sh JOB.json INPUTS_DIR RESULTS_DIR}")
INPUTS=$(realpath "${2:?usage: attended.sh JOB.json INPUTS_DIR RESULTS_DIR}")
DEST=${3:?usage: attended.sh JOB.json INPUTS_DIR RESULTS_DIR}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
KIT=$(cd "$HERE/../../.." && pwd)
J() { python3 -c "import json,sys;d=json.load(open(sys.argv[1]));$1" "$JOBFILE"; }
VARGS=(); [ "$(J 'print(len(d.get("inputs") or []))')" -gt 0 ] && VARGS=(--inputs "$INPUTS")
python3 "$KIT/scripts/studio.py" cloudrun validate --job "$JOBFILE" "${VARGS[@]}" > /dev/null \
	|| { python3 "$KIT/scripts/studio.py" cloudrun validate --job "$JOBFILE" "${VARGS[@]}"; exit 2; }
[ "$(J 'print(d["type"], d.get("where"))')" = "model-run attended" ] || { echo "attended.sh runs model-run jobs with \"where\": \"attended\" only" >&2; exit 2; }
RECIPE=$(J 'print(d["recipe"])'); RDIR=$KIT/skills/studio-cloudrun/recipes/$RECIPE
JOB=$(mktemp -d "${TMPDIR:-/tmp}/attended-XXXX"); mkdir -p "$JOB/repo"; (umask 077; mkdir -p "$JOB/inputs")
cp -r "$RDIR"/. "$JOB/repo/"
grep -q speech_common "$RDIR/worker.py" && cp "$KIT/skills/studio-cloudrun/recipes/speech_common.py" "$JOB/repo/"
echo "$RECIPE" > "$JOB/repo/recipe.name"
python3 -c "import json,sys;json.dump(json.load(open(sys.argv[1]))['plan'],open(sys.argv[2],'w'),indent=2)" "$JOBFILE" "$JOB/repo/plan.json"
J 'print(json.dumps({"id":d["id"],"max_minutes":d["max_minutes"],"setup":"bash setup.sh","command":"bash run.sh"}))' > "$JOB/job.json"
J 'print("\n".join(i["path"] for i in d.get("inputs") or []))' | while IFS= read -r p; do
	[ -n "$p" ] || continue
	mkdir -p "$JOB/inputs/$(dirname "$p")"; cp -L "$INPUTS/$p" "$JOB/inputs/$p"
done
J 'print("\n".join(i["sha256"] for i in d.get("inputs") or [] if i.get("private", True)))' > "$JOB/private.sha256"
COMMIT=$(git -C "$KIT" rev-parse HEAD 2> /dev/null || echo unknown)$(git -C "$KIT" diff --quiet HEAD -- "$RDIR" 2> /dev/null || echo +local-changes)
echo "$COMMIT" > "$JOB/commit.txt"
GPU=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2> /dev/null | head -1)
echo "gpu=${GPU:-none (no nvidia-smi)}" > "$JOB/env.txt"
echo "attended run: recipe $RECIPE @ kit $COMMIT, ${GPU:-no GPU}"
JOB_ROOT="$JOB" STUDIO_COMMIT="$COMMIT" bash "$HERE/runtime_job.sh"; RC=$?
mkdir -p "$DEST"; DEST=$(realpath "$DEST")
cp -a "$JOB/out/." "$DEST/"; cp "$JOB/progress.txt" "$DEST/" 2> /dev/null
LEAK=$(python3 - "$DEST" "$JOB/private.sha256" <<'PY'
import hashlib, sys
from pathlib import Path
res, bad = Path(sys.argv[1]), set(Path(sys.argv[2]).read_text().split())
n = 0
for p in res.rglob("*"):
    if p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest() in bad:
        p.unlink(); n += 1
print(n)
PY
)
rm -rf "$JOB/inputs" "$JOB/private.sha256"
if [ "$LEAK" -gt 0 ]; then echo "$LEAK result file(s) were copies of a private input: deleted; this run fails" >&2; RC=5; fi
(cd "$(dirname "$DEST")" && python3 -m zipfile -c "$DEST.zip" "$(basename "$DEST")") && echo "results: $DEST.zip"
echo "exit $RC"
exit "$RC"
