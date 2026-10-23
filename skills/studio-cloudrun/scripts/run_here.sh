#!/bin/bash
# Run one job on this machine (a cloud agent box or a Linux workstation):
#   run_here.sh JOB.json CHECKOUT OUT_DIR
# CHECKOUT is the game repository at the job's ref (the caller checks it out;
# this script refuses a checkout whose HEAD is not that ref). A virtual screen
# comes from xvfb-run; Vulkan uses whatever driver the box has (lavapipe in a
# cloud box: apt install xvfb ffmpeg mesa-vulkan-drivers). Free, no approval,
# much slower than a GPU runtime. Results land in OUT_DIR as on a runtime.
set -u
JOBFILE=$(realpath "${1:?usage: run_here.sh JOB.json CHECKOUT OUT_DIR}")
CHECKOUT=$(realpath "${2:?usage: run_here.sh JOB.json CHECKOUT OUT_DIR}")
DEST=${3:?usage: run_here.sh JOB.json CHECKOUT OUT_DIR}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
KIT=$(cd "$HERE/../../.." && pwd)
python3 "$KIT/scripts/studio.py" cloudrun validate --job "$JOBFILE" > /dev/null || { python3 "$KIT/scripts/studio.py" cloudrun validate --job "$JOBFILE"; exit 2; }
REF=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['ref'])" "$JOBFILE")
WANT=$(git -C "$CHECKOUT" rev-parse --verify -q "$REF^{commit}" || git -C "$CHECKOUT" rev-parse --verify -q "origin/$REF^{commit}" || true)
HEAD=$(git -C "$CHECKOUT" rev-parse HEAD)
[ -n "$WANT" ] && [ "$WANT" = "$HEAD" ] || { echo "checkout HEAD $HEAD is not the job's ref $REF ($WANT)" >&2; exit 2; }
for t in xvfb-run python3; do command -v "$t" > /dev/null || { echo "missing $t" >&2; exit 2; }; done
mkdir -p "$DEST"; DEST=$(realpath "$DEST")
JOB=$(mktemp -d); trap 'rm -rf "$JOB"' EXIT
cp "$JOBFILE" "$JOB/job.json"; ln -s "$CHECKOUT" "$JOB/repo"
DEV=$(vulkaninfo --summary 2> /dev/null | grep -m1 deviceName | sed 's/.*= //')
case "$DEV" in
	"") GPU="gpu=unknown (no vulkaninfo; the engine log names the device)" ;;
	*llvmpipe*|*lavapipe*|*SwiftShader*) GPU="gpu=software ($DEV, this machine)" ;;
	*) GPU="gpu=$DEV (this machine)" ;;
esac
{ echo "nproc $(nproc)"; echo "$GPU"; } > "$JOB/env.txt"
xvfb-run -a -s "-screen 0 1920x1080x24" env JOB_ROOT="$JOB" STUDIO_COMMIT="$HEAD" bash "$HERE/runtime_job.sh"
RC=$?
cp -a "$JOB/out/." "$DEST/"; cp "$JOB/progress.txt" "$DEST/progress.txt" 2>/dev/null
echo "job exit $RC; results in $DEST"
exit $RC
