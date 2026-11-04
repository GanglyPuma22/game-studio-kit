#!/bin/bash
# Service host side (the always-on box, e.g. Aptivio in WSL): run one job on a
# Colab runtime (a GPU, or a CPU-only runtime for "gpu": "CPU") from start to
# finish, then stop the runtime.
#   colab_job.sh JOB.json
# Needs: the colab CLI signed in by the person, git access to the job's repo
# (GH, default git@github.com:), python3.
# Colab login: COLAB_AUTH (default oauth2; on Aptivio, ADC is another Google
# account with no units). Each session gets its own private CLI state file
# ($WORK/state/<session>.json, mode 600, never copied into results) when the
# CLI accepts one; set COLAB_SHARED_CONFIG=1 to use the CLI's default state.
# The job's commands run only on the runtime; this host packs the commit with git archive, copies it in, polls,
# copies OUT_DIR back and stops the runtime on exit, on error and at the cap.
# Results: $WORK/results/<id>-<UTC time>-XXXX/ (runner.json first), and, when
# RESULTS_REPO is set, a fresh one-commit branch studio-results/<id> there.
# Live status: $WORK/status/<id>.json, updated every minute (stage, step, ETA,
# GPU use, units spent so far); read it with `live_status.py show` or
# `service.sh status`. With RESULTS_REPO set it is also pushed every
# STATUS_PUSH_MIN minutes (default 5, 0 = off) to branch studio-status/<id>.
# Guards: one run per job id and per session name on this host (a lock), a
# loud stop when the runtime has no running job (exit 5), and an early stop
# when a GPU job shows 0 % GPU for gpu_idle_minutes (default 5; exit 6).
# Exit codes: 0 done, 1 failed, 2 invalid job, 3 results not delivered,
# 4 results do not match, 5 runtime lost or no job on it, 6 GPU idle, 7 already running.
set -euo pipefail
JOBFILE=$(realpath "${1:?usage: colab_job.sh JOB.json}")
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
KIT=$(cd "$HERE/../../.." && pwd)
WORK=${CLOUDRUN_WORK:-$HOME/studio-cloudrun}; GH=${GH:-git@github.com:}
J() { python3 -c "import json,sys;d=json.load(open(sys.argv[1]));$1" "$JOBFILE"; }
ALLOW=(); for r in ${ALLOW_REPOS:-}; do ALLOW+=(--allow-repo "$r"); done
for r in ${ALLOW_REFS:-}; do ALLOW+=(--allow-ref "$r"); done
python3 "$KIT/scripts/studio.py" cloudrun validate --job "$JOBFILE" "${ALLOW[@]}" > /dev/null \
	|| { python3 "$KIT/scripts/studio.py" cloudrun validate --job "$JOBFILE" "${ALLOW[@]}"; exit 2; }
ID=$(J 'print(d["id"])'); TYPE=$(J 'print(d["type"])')
MAXMIN=$(J 'print(int(d["max_minutes"]))'); CAPMB=$(J 'print(int(d.get("results_max_mb",200)))')
if [ "$TYPE" = model-run ]; then
	# A kit recipe and the job's plan; no game repository.
	RECIPE=$(J 'print(d["recipe"])'); RDIR=$KIT/skills/studio-cloudrun/recipes/$RECIPE
	REPO="game-studio-kit recipe $RECIPE"; REF=$(git -C "$KIT" rev-parse --abbrev-ref HEAD 2> /dev/null || echo unknown)
	GPU=$(J "import json as j;print(d.get('gpu') or j.load(open('$RDIR/recipe.json')).get('gpu','L4'))")
	GATED=$(python3 -c "import json,sys;print(1 if json.load(open(sys.argv[1])).get('gated') else 0)" "$RDIR/recipe.json")
	MAXUNITS=$(J 'print(d["max_units"])'); MAXRATE=$(J 'print(d.get("max_rate",""))')
else
	REPO=$(J 'print(d["repo"])'); REF=$(J 'print(d["ref"])'); GPU=$(J 'print(d.get("gpu","L4"))')
	MAXUNITS=$(J 'print(d.get("max_units",""))'); MAXRATE=$(J 'print(d.get("max_rate",""))')
fi
# The runtime to ask for: "CPU" means no accelerator flag (a CPU-only runtime);
# high_mem adds the CLI's High-RAM option. A virtual screen only when the job
# draws: GPU jobs by default, CPU jobs only with "screen": true.
NEW=(--gpu "$GPU"); [ "$GPU" = CPU ] && NEW=()
[ "$(J 'print(1 if d.get("high_mem") else 0)')" = 1 ] && NEW+=(--high-mem)
SCREEN=$(J 'print(0 if d["type"]=="model-run" else int(d.get("screen", d.get("gpu","L4")!="CPU")))')
SESSION=${COLAB_SESSION:-studio-$ID}
# GPU idle limit in minutes (0 = off): the job's, else the recipe's, else GPU_IDLE_MIN, else 5. Never on CPU runtimes.
IDLE=$(J "import os;sys.path.insert(0,'$KIT');from studio_tools import cloudrun as c;print(c.idle_minutes(d,float(os.environ.get('GPU_IDLE_MIN',c.GPU_IDLE_MINUTES))))")
mkdir -p "$WORK/results" "$WORK/repos" "$WORK/status"
mkdir -p -m 700 "$WORK/locks"
# One run per job id and per Colab session name on this host. Taken before any
# runtime exists, so a refused duplicate never touches the other run's runtime.
exec 8> "$WORK/locks/job-$ID.lock"
flock -n 8 || { echo "[cloudrun $(date -u +%T)] job $ID is already running on this host ($WORK/status/$ID.json): refusing a second copy" >&2; exit 7; }
if [ "$SESSION" != "studio-$ID" ]; then
	exec 9> "$WORK/locks/session-$SESSION.lock"
	flock -n 9 || { echo "[cloudrun $(date -u +%T)] Colab session $SESSION is already in use on this host: refusing" >&2; exit 7; }
fi
RES=$(mktemp -d "$WORK/results/$ID-$(date -u +%Y%m%dT%H%M%SZ)-XXXX")   # fresh per run, even for a reused id
say() { echo "[cloudrun $(date -u +%T)] $*" | tee -a "$RES/driver.log"; }
STATUS=$RES/status.json; LIVE=$WORK/status/$ID.json
st() { python3 "$HERE/live_status.py" set --status "$STATUS" --mirror "$LIVE" "$@" || true; }
# The live status on branch studio-status/<id> of RESULTS_REPO, for agents
# that cannot reach this host. Never fails the run.
push_live() {
	[ -n "${RESULTS_REPO:-}" ] && [ "${STATUS_PUSH_MIN:-5}" -gt 0 ] || return 0
	local P; P=$(mktemp -d)
	cp "$STATUS" "$P/STATUS.json" 2> /dev/null; tail -n 60 "$RES/driver.log" > "$P/driver-tail.log" 2> /dev/null
	python3 "$HERE/live_status.py" line --status "$STATUS" > "$P/STATUS.txt" 2> /dev/null
	( cd "$P" && git init -q && git checkout -q -b "studio-status/$ID" && git add -A \
		&& git -c user.name=cloudrun -c user.email=cloudrun@localhost commit -qm "live status $ID $(date -u +%FT%TZ)" \
		&& timeout 120 git push -q -f "$GH$RESULTS_REPO.git" "studio-status/$ID" ) > /dev/null 2>&1 \
		|| echo "[cloudrun $(date -u +%T)] live status push failed" >> "$RES/driver.log"
	rm -rf "$P"; return 0
}
# On every way out: the runtime stopped once one exists (STOP_RUNTIME), the
# status marked failed unless the run was delivered, the last status pushed.
FINAL=failed; STOP_RUNTIME=0; WATCHDOG=""
on_exit() {
	# The watchdog and its sleep (a plain kill would leave the sleep behind).
	if [ -n "$WATCHDOG" ]; then pkill -P "$WATCHDOG" 2> /dev/null || true; kill "$WATCHDOG" 2> /dev/null || true; fi
	if [ "$STOP_RUNTIME" = 1 ]; then
		say "stopping runtime"; "${COLAB[@]}" stop -s "$SESSION" || true
	fi
	rm -f "$RES/repo.tar"
	[ "$FINAL" = done ] || st state=failed
	push_live
}
trap on_exit EXIT
st id="$ID" session="$SESSION" gpu="$GPU" res="$RES" state=running stage=packing started="$(date -u +%FT%TZ)" \
	max_units="$MAXUNITS" gpu_idle_limit_min="$IDLE"
COLAB_BIN=${COLAB_BIN:-$(command -v colab || true)}
[ -n "$COLAB_BIN" ] || { say "colab CLI not found: stop"; exit 1; }
COLAB=("$COLAB_BIN" "--auth=${COLAB_AUTH:-oauth2}")
mkdir -p -m 700 "$WORK/state"
if [ "${COLAB_SHARED_CONFIG:-0}" != 1 ]; then
	STATE=$WORK/state/$SESSION.json
	# Only if this CLI takes a separate state file and the login still works with it.
	if (umask 077; timeout 60 "${COLAB[@]}" --config "$STATE" usage < /dev/null > /dev/null 2>&1); then
		COLAB+=(--config "$STATE")
	else
		say "colab: separate state file refused, using the CLI's default state"
	fi
fi
say "colab: $("${COLAB[@]}" --version 2> /dev/null | head -1), auth ${COLAB_AUTH:-oauth2}"

# --- 0. what runs, packed here (no .git, no credentials go to the runtime)
RUNJOB=$JOBFILE
if [ "$TYPE" = model-run ]; then
	COMMIT=$(git -C "$KIT" rev-parse HEAD 2> /dev/null || echo unknown)$(git -C "$KIT" diff --quiet HEAD -- "$RDIR" 2> /dev/null || echo +local-changes)
	PACK=$(mktemp -d); cp -r "$RDIR"/. "$PACK/"
	python3 -c "import json,sys;json.dump(json.load(open(sys.argv[1]))['plan'],open(sys.argv[2],'w'),indent=2)" "$JOBFILE" "$PACK/plan.json"
	# The runtime's own job file: the recipe's setup and run, the job's caps.
	RUNJOB=$RES/runtime-job.json
	python3 -c "import json,sys;d=json.load(open(sys.argv[1]));json.dump({'id':d['id'],'max_minutes':d['max_minutes'],'setup':'bash setup.sh','command':'bash run.sh'},open(sys.argv[2],'w'))" "$JOBFILE" "$RUNJOB"
	tar -cf "$RES/repo.tar" --exclude=__pycache__ -C "$PACK" .; rm -rf "$PACK"
else
	MIRROR=$WORK/repos/${REPO//\//__}.git
	[ -d "$MIRROR" ] || git clone -q --bare "$GH$REPO.git" "$MIRROR"
	# Branches land under refs/remotes/origin/, which a worktree's checked-out
	# branch never blocks (a plain refs/heads/* fetch then refused every update).
	git -C "$MIRROR" fetch -q --prune origin "+refs/heads/*:refs/remotes/origin/*" \
		|| say "fetch of $REPO failed; using what the mirror already has"
	COMMIT=$(git -C "$MIRROR" rev-parse --verify -q "refs/remotes/origin/$REF^{commit}" \
		|| git -C "$MIRROR" rev-parse --verify -q "$REF^{commit}") || { say "ref $REF not found in $REPO: stop"; exit 1; }
	git -C "$MIRROR" archive --format=tar "$COMMIT" > "$RES/repo.tar"
fi
say "job $ID: $REPO $REF @ $COMMIT ($(( $(stat -c %s "$RES/repo.tar") / 1048576 )) MB), $GPU${NEW[*]:+ (colab new ${NEW[*]})}, screen $SCREEN, cap $MAXMIN min${MAXUNITS:+, ceiling $MAXUNITS units}"

# --- 1. runtime (the account holds a few runtimes at once; wait for a free one, no spend while waiting)
cat > "$RES/ssh.cfg" <<CFG
Host runtime
  HostName colab-runtime
  User root
  ProxyCommand ${COLAB[*]} ssh --proxy-mode -s $SESSION
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
  LogLevel ERROR
  ServerAliveInterval 30
  ServerAliveCountMax 4
  ConnectTimeout 60
CFG
ssh() { command ssh -F "$RES/ssh.cfg" "$@"; }
# Hourly rate from `colab usage` (account-wide; the CLI's wording may change).
rate() { python3 -c '
import re, sys
m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:compute\s*)?(?:units?\s*)?(?:/|per\s*)\s*h(?:ou)?r", sys.stdin.read(), re.I)
print(m.group(1) if m else "")'; }
# The other sessions on the account, without this one: compared before and
# after allocation to tell whether the rate difference is this session's alone.
others() { timeout 60 "${COLAB[@]}" sessions < /dev/null 2> /dev/null | grep -v -F -- "$SESSION"; return "${PIPESTATUS[0]}"; }
# 0: a Colab session with exactly this name exists; 1: none; 2: the list failed.
has_session() {
	local list; list=$(timeout 60 "${COLAB[@]}" sessions < /dev/null 2> /dev/null) || return 2
	awk -v s="$SESSION" '{ for (i = 1; i <= NF; i++) if ($i == s) f = 1 } END { exit !f }' <<< "$list"
}
# A second launch under the same name (another host, or a crashed run) would
# share, and later stop, that runtime: refuse instead.
if has_session; then
	say "a Colab session named $SESSION already exists (another run, or a stale one: check \`colab sessions\`, stop it with \`colab stop -s $SESSION\`): refusing"
	st state=failed stage=refused exit=7 note="session $SESSION already exists"; exit 7
fi
WAIT=${GPU_WAIT_MIN:-240}
st stage=waiting-gpu
for try in $(seq $(( WAIT / 5 + 1 ))); do
	# Sampled right before each try, so the window is seconds, not the wait.
	RATE0=$(timeout 60 "${COLAB[@]}" usage < /dev/null 2> /dev/null | rate || true)
	OTHERS0=$(others) && OK0=1 || OK0=0
	"${COLAB[@]}" new "${NEW[@]}" -s "$SESSION" && break
	[ "$try" -gt $(( WAIT / 5 )) ] && { say "no $GPU after $WAIT min: stop"; st state=failed exit=1 note="no free $GPU after $WAIT min"; exit 1; }
	say "no free $GPU yet (try $try), waiting 5 min"; st note="no free $GPU yet (try $try)"; sleep 300
done
T0=$(date +%s)
STOP_RUNTIME=1
st stage=starting runtime_started_s="$T0" note=""
CAP=$(( (MAXMIN + 20) * 60 ))
USAGE=$("${COLAB[@]}" usage 2> /dev/null || true)
echo "$USAGE" | head -5 >> "$RES/driver.log"
RATE1=$(echo "$USAGE" | rate || true)
# The ceilings use this session's own rate: the account's rate after allocation
# minus the rate sampled just before it, but only when `colab sessions` shows
# the same other sessions before and after (none started or stopped in
# between). Otherwise a GPU job beside a cheap CPU one would make the CPU job
# refuse its max_rate or stop after minutes. When the other sessions changed or
# can't be listed, or the difference is not above zero, the account's whole
# rate is used, which is never less than this session's own.
OTHERS1=$(others) && OK1=1 || OK1=0
SAME=0; [ "$OK0$OK1" = 11 ] && [ "$OTHERS0" = "$OTHERS1" ] && SAME=1
OWN=$(python3 -c "
import sys
a, b, same = sys.argv[1], sys.argv[2], sys.argv[3] == '1'
try:
    d = float(a) - float(b)
    print(f'{d:.3f}' if same and d > 0 else a)
except ValueError:
    print(a)" "${RATE1:-}" "${RATE0:-}" "$SAME")
st rate="$OWN" cap_min=$(( CAP / 60 ))
say "rate: account ${RATE1:-unknown} units/hour with this session (before it: ${RATE0:-unknown}; other sessions $([ "$SAME" = 1 ] && echo unchanged || echo 'changed or unknown')); ceilings use ${OWN:-unknown} units/hour"
if [ -n "$MAXUNITS" ]; then
	# A model run spends only with a known rate, under its ceiling, and no longer than its units allow.
	[ -n "$OWN" ] || { say "hourly rate unknown: refusing to spend; stop"; exit 1; }
	if [ -n "$MAXRATE" ] && python3 -c "import sys;sys.exit(0 if float(sys.argv[1])>float(sys.argv[2]) else 1)" "$OWN" "$MAXRATE"; then
		say "rate $OWN is over the job's max_rate $MAXRATE: stop"; exit 1
	fi
	UCAP=$(python3 -c "import sys;print(int(float(sys.argv[1])/float(sys.argv[2])*3600))" "$MAXUNITS" "$OWN")
	[ "$UCAP" -lt "$CAP" ] && { CAP=$UCAP; say "cap: $CAP s from the $MAXUNITS unit ceiling"; st cap_min=$(( CAP / 60 )); }
fi
# Watchdog over the whole runtime's life (start-up, copies, the job, results):
# at the cap it stops the runtime, which ends any ssh call still hanging.
( sleep "$CAP"; echo "[cloudrun $(date -u +%T)] watchdog: $CAP s since the runtime started, stopping it" >> "$RES/driver.log"
  "${COLAB[@]}" stop -s "$SESSION" > /dev/null 2>&1 ) > /dev/null 2>&1 < /dev/null &
WATCHDOG=$!
"${COLAB[@]}" usage 2> /dev/null | head -3 >> "$RES/driver.log" || true
for try in 1 2 3 4 5; do
	ssh runtime 'mkdir -p /content/job/repo /content/job/out' && break
	[ "$try" = 5 ] && { say "ssh to the runtime failed 5 times: stop"; exit 1; }
	say "ssh not ready (try $try)"; sleep $((15 * try))
done
st stage=copying
# Each start-up step is safe to repeat, so a dropped connection gets two more
# tries instead of ending a paid run (an A100 start once hung 2.5 min, then broke).
put() { # put REMOTE_COMMAND [LOCAL_FILE for stdin]
	local t
	for t in 1 2 3; do
		ssh runtime "$1" < "${2:-/dev/null}" && return 0
		say "ssh dropped (try $t of 3): ${1%% *}..."; sleep $((10 * t))
	done
	say "ssh failed 3 times: stop"; exit 1
}
put 'tar -xf - -C /content/job/repo' "$RES/repo.tar"
put 'cat > /content/job/job.json' "$RUNJOB"
if [ "${GATED:-0}" = 1 ]; then
	# Gated weights: short-lived links made here with the host's login; the token stays here.
	W=$WORK/state/$SESSION-weights.json
	python3 "$HERE/stage_hf.py" "$RDIR/recipe.json" "$W" >> "$RES/driver.log" 2>&1 || { say "weight staging failed (see driver.log): stop"; rm -f "$W"; exit 1; }
	OK=0; ( put 'umask 077; cat > /content/job/weights.json' "$W" ) || OK=1; rm -f "$W"; [ "$OK" = 0 ] || exit 1
	say "weights staged for $RECIPE"
fi
echo "$COMMIT" > "$RES/commit.txt"
put 'cat > /content/job/commit.txt' "$RES/commit.txt"
for f in runtime_display.sh runtime_job.sh runtime_probe.sh; do put "cat > /content/job/$f" "$HERE/$f"; done
say "copied in after $(( $(date +%s) - T0 )) s"

# --- 2. screen, then the job (detached; polled)
SCREEN_ARG=""; [ "$SCREEN" = 0 ] && SCREEN_ARG=--no-screen
st stage=preparing
ssh runtime "bash /content/job/runtime_display.sh $SCREEN_ARG" >> "$RES/driver.log" 2>&1 \
	|| ssh runtime "bash /content/job/runtime_display.sh $SCREEN_ARG" >> "$RES/driver.log" 2>&1 \
	|| { say "runtime preparation failed: stop"; exit 1; }
# Start the job once: a retry after a dropped connection sees runner.pid and
# only confirms the start.
put 'cd /content/job && if [ ! -s runner.pid ]; then setsid nohup bash runtime_job.sh > runner.log 2>&1 < /dev/null & sleep 3; fi; [ -s runner.pid ]'
# Every minute: one probe of the runtime, the live status updated from it,
# and a loud stop when the runtime has no running job or a GPU job idles.
kill_job() { ssh runtime 'P=$(cat /content/job/runner.pid 2>/dev/null); [ -n "$P" ] && { kill -TERM -- -$P 2>/dev/null; sleep 3; kill -KILL -- -$P 2>/dev/null; }; true' || true; }
FORCE_RC=""; LAST_PUSH=$(date +%s)
while :; do
	sleep "${POLL_S:-60}"
	set +e
	ssh runtime 'if [ -f /content/job/job.json ]; then bash /content/job/runtime_probe.sh; else echo job=0; fi' > "$RES/probe.txt" 2> /dev/null
	SRC=$?
	if [ "$SRC" -ne 0 ] || ! grep -q '^job=' "$RES/probe.txt"; then
		has_session; HS=$?
		{ echo ssh=fail; [ "$HS" = 1 ] && echo session=gone; } > "$RES/probe.txt"
	fi
	set -e
	ACT=$(python3 "$HERE/live_status.py" tick --status "$STATUS" --mirror "$LIVE" --probe "$RES/probe.txt" \
		--gpu-idle-min "$IDLE" --ssh-lost-min "${SSH_LOST_MIN:-5}" 2>> "$RES/driver.log" || echo ok)
	echo "  $(python3 "$HERE/live_status.py" line --status "$STATUS" 2> /dev/null)" >> "$RES/driver.log"
	case "$ACT" in
		finished) break ;;
		lost\ *) say "RUNTIME LOST: ${ACT#lost }. Stopping; nothing more will come from this runtime."
			st state=failed stage=lost exit=5 note="${ACT#lost }"; FORCE_RC=5; break ;;
		idle\ *) say "GPU IDLE: ${ACT#idle }. Stopping the job, then fetching partial results."
			st stage=stopping note="${ACT#idle }"; kill_job; FORCE_RC=6; break ;;
	esac
	if [ $(( $(date +%s) - T0 )) -gt "$CAP" ]; then
		say "time cap reached: stopping the job, then fetching partial results"
		st note="time cap reached"; kill_job
		break
	fi
	if [ "${STATUS_PUSH_MIN:-5}" -gt 0 ] && [ $(( $(date +%s) - LAST_PUSH )) -ge $(( ${STATUS_PUSH_MIN:-5} * 60 )) ]; then
		push_live; LAST_PUSH=$(date +%s)
	fi
done
if [ "$FORCE_RC" = 5 ]; then
	say "job $ID: exit 5 (runtime lost); partial files, if any, stay on the runtime until it stops; driver.log in $RES"
	exit 5
fi
st stage=results

# --- 3. results (size-capped)
# A file list with SHA-256 made on the runtime, checked here after the copy:
# a run counts only when what arrived matches what the runtime wrote.
ssh runtime "cd /content/job && cp progress.txt runner.log job-progress.txt gpu.csv out/ 2>/dev/null; (cd out && find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 -r sha256sum > MANIFEST.sha256); du -sm out | cut -f1" > "$RES/out-mb.txt" || true
MB=$(cat "$RES/out-mb.txt" 2>/dev/null || echo 0)
if [ "${MB:-0}" -gt "$CAPMB" ]; then
	say "OUT_DIR is $MB MB, over the job's $CAPMB MB: bringing back files under 10 MB only"
	ssh runtime 'cd /content/job/out && find . -type f -size -10M -print0 | tar --null -T - -cf -' | tar -xf - -C "$RES"
else
	ssh runtime 'tar -cf - -C /content/job/out .' | tar -xf - -C "$RES"
fi
VERIFIED=0
if [ -s "$RES/MANIFEST.sha256" ]; then
	if [ "${MB:-0}" -gt "$CAPMB" ]; then
		(cd "$RES" && sha256sum --quiet -c --ignore-missing MANIFEST.sha256) && VERIFIED=1
	else
		(cd "$RES" && sha256sum --quiet -c MANIFEST.sha256) && VERIFIED=1
	fi
fi
[ "$VERIFIED" = 1 ] && say "results match the runtime's SHA-256 list" || say "results do NOT match the runtime's SHA-256 list (or it is missing)"
say "runtime minutes: $(( ($(date +%s) - T0) / 60 ))"
"${COLAB[@]}" usage 2> /dev/null | head -3 >> "$RES/driver.log" || true
echo "build: $REPO $REF @ $COMMIT, $GPU, $(grep -m1 gpu= "$RES/env.txt" 2>/dev/null || echo 'gpu line missing')" > "$RES/BUILD.txt"

PUSHED=0; [ -n "${RESULTS_REPO:-}" ] || PUSHED=1   # no results repo: the local folder is the delivery
# Per-file size on a results branch: 10 MB for captures (clips are small), 95 MB
# for model runs (a 180 s FLAC is about 30 MB; GitHub refuses files over 100 MB).
FILE_MB=10; [ "$TYPE" = model-run ] && FILE_MB=95
LEFTOUT=0
if [ -n "${RESULTS_REPO:-}" ]; then
	P=$(mktemp -d); mkdir -p "$P/$ID"
	(cd "$RES" && find . -type f ! -name repo.tar ! -name ssh.cfg -size -${FILE_MB}M -print0 | tar --null -T - -cf -) | tar -xf - -C "$P/$ID"
	(cd "$RES" && find . -type f ! -name repo.tar -size +$((FILE_MB - 1))M -print) > "$P/$ID/LEFT-OUT-over-${FILE_MB}MB.txt"
	LEFTOUT=$(grep -c . "$P/$ID/LEFT-OUT-over-${FILE_MB}MB.txt" || true)
	[ "$LEFTOUT" -gt 0 ] && say "$LEFTOUT file(s) over $FILE_MB MB stay in $RES only (listed in LEFT-OUT-over-${FILE_MB}MB.txt)"
	( cd "$P" && git init -q && git checkout -q -b "studio-results/$ID" && git add -A \
		&& git -c user.name=cloudrun -c user.email=cloudrun@localhost commit -qm "cloudrun results $ID ($(basename "$RES"))" \
		&& git push -q -f "$GH$RESULTS_REPO.git" "studio-results/$ID" ) \
		&& { say "results pushed to $RESULTS_REPO branch studio-results/$ID"; PUSHED=1; } || say "results push FAILED (kept in $RES)"
	rm -rf "$P"
fi
RC=$(python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(0 if d.get('setup_exit')==0 and d.get('run_exit')==0 else 1)" "$RES/runner.json" 2>/dev/null || echo 1)
[ -n "$FORCE_RC" ] && RC=$FORCE_RC
# Results nobody can reach are a failed job: the queue stops and says so.
[ "$RC" = 0 ] && [ "$VERIFIED" = 0 ] && RC=4
[ "$RC" = 0 ] && [ "$PUSHED" = 0 ] && RC=3
# A model run's outputs are the product: any left behind means it was not delivered.
if [ "$TYPE" = model-run ] && [ "$RC" = 0 ] && { [ "${LEFTOUT:-0}" -gt 0 ] || [ "${MB:-0}" -gt "$CAPMB" ]; }; then
	say "model outputs not all delivered (size limits): exit 3"; RC=3
fi
say "job $ID: exit $RC; results in $RES"
[ "$RC" = 0 ] && FINAL=done
st state="$FINAL" stage=done exit="$RC"
exit "$RC"
