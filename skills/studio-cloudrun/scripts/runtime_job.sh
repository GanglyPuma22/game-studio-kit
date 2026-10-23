#!/bin/bash
# Runs one job where it was copied: $JOB_ROOT (default /content/job) holds
# job.json, repo/ (the game at the job's commit) and these scripts. Used on a
# Colab runtime (after runtime_display.sh) and, through run_here.sh, on any
# Linux box. Writes $JOB_ROOT/out (the job's OUT_DIR), progress.txt and
# out/runner.json (exit codes, minutes, gpu line). Never needs credentials.
set -u
JOB=${JOB_ROOT:-/content/job}
OUT=$JOB/out; mkdir -p "$OUT"
echo $$ > "$JOB/runner.pid"
log() { echo "$(date -u +%T) $*" | tee -a "$JOB/progress.txt"; }
J() { python3 -c "import json,sys;d=json.load(open('$JOB/job.json'));$1"; }
ID=$(J 'print(d["id"])')
MAXMIN=$(J 'print(int(d["max_minutes"]))')
SETUP=$(J 'print(d.get("setup",""))')
CMD=$(J 'print(d["command"])')
[ -f "$JOB/display.env" ] && . "$JOB/display.env"
# The job's own environment, then the names the runner owns.
while IFS= read -r line; do [ -n "$line" ] && export "${line?}"; done < <(J 'print("\n".join(f"{k}={v}" for k,v in d.get("env",{}).items()))')
export OUT_DIR=$OUT JOB_ID=$ID
export GODOT=${GODOT:-}
T0=$(date +%s)
log "job $ID: start (cap $MAXMIN min)"
if J 'sys.exit(0 if d.get("godot") else 1)'; then
	URL=$(J 'print(d["godot"]["url"])'); SUM=$(J 'print(d["godot"]["sha256"])')
	mkdir -p "$JOB/engine"
	curl -sfL -o "$JOB/engine/godot.zip" "$URL" || { log "godot download failed"; echo '{"setup_exit": 90}' > "$OUT/runner.json"; log "done"; exit 1; }
	echo "$SUM  $JOB/engine/godot.zip" | sha256sum -c --quiet || { log "godot SHA-256 mismatch"; echo '{"setup_exit": 91}' > "$OUT/runner.json"; log "done"; exit 1; }
	unzip -q -o "$JOB/engine/godot.zip" -d "$JOB/engine"
	GODOT=$(find "$JOB/engine" -maxdepth 2 -type f -name 'Godot_v*' ! -name '*.zip' | head -1)
	chmod +x "$GODOT"; export GODOT
	log "godot $("$GODOT" --version 2>/dev/null | head -1)"
fi
cd "$JOB/repo" || exit 1
SRC=0
if [ -n "$SETUP" ]; then
	log "setup: $SETUP"
	timeout --foreground $((MAXMIN * 60)) bash -c "$SETUP" > "$OUT/setup.log" 2>&1; SRC=$?
	log "setup exit $SRC"
fi
RC=99
if [ "$SRC" = 0 ]; then
	LEFT=$(( MAXMIN * 60 - ($(date +%s) - T0) )); [ "$LEFT" -lt 60 ] && LEFT=60
	log "run: $CMD"
	timeout --foreground "$LEFT" bash -c "$CMD" > "$OUT/run.log" 2>&1; RC=$?
	log "run exit $RC"
fi
GPU=$(grep -m1 '^gpu=' "$JOB/env.txt" 2>/dev/null || echo "gpu=unknown (no runtime_display.sh)")
python3 - "$OUT/runner.json" "$ID" "$SRC" "$RC" "$(( ($(date +%s) - T0) / 60 ))" "$GPU" <<'PY'
import json, sys
p, jid, s, r, m, gpu = sys.argv[1:7]
json.dump({"id": jid, "setup_exit": int(s), "run_exit": int(r), "minutes": int(m), "gpu": gpu}, open(p, "w"), indent=2)
PY
cp "$JOB/env.txt" "$OUT/env.txt" 2>/dev/null
log "done"
[ "$SRC" = 0 ] && [ "$RC" = 0 ]
