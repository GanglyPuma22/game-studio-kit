#!/bin/bash
# Service host side (the always-on box, e.g. Aptivio in WSL): run one job on a
# Colab GPU runtime from start to finish, then stop the runtime.
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
	MAXUNITS=""; MAXRATE=""
fi
SESSION=${COLAB_SESSION:-studio-$ID}
mkdir -p "$WORK/results" "$WORK/repos"
RES=$(mktemp -d "$WORK/results/$ID-$(date -u +%Y%m%dT%H%M%SZ)-XXXX")   # fresh per run, even for a reused id
say() { echo "[cloudrun $(date -u +%T)] $*" | tee -a "$RES/driver.log"; }
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
	git -C "$MIRROR" fetch -q origin "+refs/heads/*:refs/heads/*" 2> /dev/null || git -C "$MIRROR" fetch -q origin
	COMMIT=$(git -C "$MIRROR" rev-parse --verify -q "$REF^{commit}") || { say "ref $REF not found in $REPO: stop"; exit 1; }
	git -C "$MIRROR" archive --format=tar "$COMMIT" > "$RES/repo.tar"
fi
say "job $ID: $REPO $REF @ $COMMIT ($(( $(stat -c %s "$RES/repo.tar") / 1048576 )) MB), $GPU, cap $MAXMIN min"

# --- 1. runtime (the account holds a few GPUs at once; wait for a free one, no spend while waiting)
cat > "$RES/ssh.cfg" <<CFG
Host runtime
  HostName colab-runtime
  User root
  ProxyCommand ${COLAB[*]} ssh --proxy-mode -s $SESSION
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
  LogLevel ERROR
  ServerAliveInterval 30
CFG
ssh() { command ssh -F "$RES/ssh.cfg" "$@"; }
# Hourly rate from `colab usage` (account-wide; the CLI's wording may change).
rate() { python3 -c '
import re, sys
m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:compute\s*)?(?:units?\s*)?(?:/|per\s*)\s*h(?:ou)?r", sys.stdin.read(), re.I)
print(m.group(1) if m else "")'; }
RATE0=$("${COLAB[@]}" usage 2> /dev/null | rate || true)
WAIT=${GPU_WAIT_MIN:-240}
for try in $(seq $(( WAIT / 5 + 1 ))); do
	"${COLAB[@]}" new --gpu "$GPU" -s "$SESSION" && break
	[ "$try" -gt $(( WAIT / 5 )) ] && { say "no $GPU after $WAIT min: stop"; exit 1; }
	say "no free $GPU yet (try $try), waiting 5 min"; sleep 300
done
T0=$(date +%s)
trap '"${COLAB[@]}" stop -s "$SESSION" > /dev/null 2>&1 || true' EXIT
CAP=$(( (MAXMIN + 20) * 60 ))
USAGE=$("${COLAB[@]}" usage 2> /dev/null || true)
echo "$USAGE" | head -5 >> "$RES/driver.log"
RATE1=$(echo "$USAGE" | rate || true)
# This session's rate: the account's rate now less before (other sessions may run beside it).
OWN=$(python3 -c "import sys;a,b=sys.argv[1:3];a=float(a) if a else 0.0;print('' if not b else (float(b)-a if float(b)-a>0.05 else float(b)))" "$RATE0" "$RATE1")
say "rate: ${OWN:-unknown} units/hour for this session (account ${RATE1:-unknown}, before ${RATE0:-unknown})"
if [ -n "$MAXUNITS" ]; then
	# A model run spends only with a known rate, under its ceiling, and no longer than its units allow.
	[ -n "$OWN" ] || { say "hourly rate unknown: refusing to spend; stop"; exit 1; }
	if [ -n "$MAXRATE" ] && python3 -c "import sys;sys.exit(0 if float(sys.argv[1])>float(sys.argv[2]) else 1)" "$OWN" "$MAXRATE"; then
		say "rate $OWN is over the job's max_rate $MAXRATE: stop"; exit 1
	fi
	UCAP=$(python3 -c "import sys;print(int(float(sys.argv[1])/float(sys.argv[2])*3600))" "$MAXUNITS" "$OWN")
	[ "$UCAP" -lt "$CAP" ] && { CAP=$UCAP; say "cap: $CAP s from the $MAXUNITS unit ceiling"; }
fi
# Watchdog over the whole runtime's life (start-up, copies, the job, results):
# at the cap it stops the runtime, which ends any ssh call still hanging.
( sleep "$CAP"; echo "[cloudrun $(date -u +%T)] watchdog: $CAP s since the runtime started, stopping it" >> "$RES/driver.log"
  "${COLAB[@]}" stop -s "$SESSION" > /dev/null 2>&1 ) &
WATCHDOG=$!
trap 'kill "$WATCHDOG" 2> /dev/null; say "stopping runtime"; "${COLAB[@]}" stop -s "$SESSION" || true; rm -f "$RES/repo.tar"' EXIT
"${COLAB[@]}" usage 2> /dev/null | head -3 >> "$RES/driver.log" || true
for try in 1 2 3 4 5; do
	ssh runtime 'mkdir -p /content/job/repo /content/job/out' && break
	[ "$try" = 5 ] && { say "ssh to the runtime failed 5 times: stop"; exit 1; }
	say "ssh not ready (try $try)"; sleep $((15 * try))
done
ssh runtime 'tar -xf - -C /content/job/repo' < "$RES/repo.tar"
ssh runtime 'cat > /content/job/job.json' < "$RUNJOB"
if [ "${GATED:-0}" = 1 ]; then
	# Gated weights: short-lived links made here with the host's login; the token stays here.
	W=$WORK/state/$SESSION-weights.json
	python3 "$HERE/stage_hf.py" "$RDIR/recipe.json" "$W" >> "$RES/driver.log" 2>&1 || { say "weight staging failed (see driver.log): stop"; rm -f "$W"; exit 1; }
	ssh runtime 'umask 077; cat > /content/job/weights.json' < "$W"; rm -f "$W"
	say "weights staged for $RECIPE"
fi
echo "$COMMIT" | ssh runtime 'cat > /content/job/commit.txt'
for f in runtime_display.sh runtime_job.sh; do ssh runtime "cat > /content/job/$f" < "$HERE/$f"; done
say "copied in after $(( $(date +%s) - T0 )) s"

# --- 2. screen, then the job (detached; polled)
SCREEN_ARG=""; [ "$TYPE" = model-run ] && SCREEN_ARG=--no-screen
ssh runtime "bash /content/job/runtime_display.sh $SCREEN_ARG" >> "$RES/driver.log" 2>&1 || { say "runtime preparation failed: stop"; exit 1; }
ssh runtime 'cd /content/job && setsid nohup bash runtime_job.sh > runner.log 2>&1 < /dev/null &'
while :; do
	sleep 60
	P=$(ssh runtime 'tail -1 /content/job/progress.txt 2>/dev/null; [ -f /content/job/finished ] && echo RUNNER-FINISHED' || true)
	echo "  $P" >> "$RES/driver.log"
	case "$P" in *RUNNER-FINISHED) break ;; esac
	if [ $(( $(date +%s) - T0 )) -gt "$CAP" ]; then
		say "time cap reached: stopping the job, then fetching partial results"
		ssh runtime 'P=$(cat /content/job/runner.pid 2>/dev/null); [ -n "$P" ] && { kill -TERM -- -$P 2>/dev/null; sleep 3; kill -KILL -- -$P 2>/dev/null; }; true' || true
		break
	fi
done

# --- 3. results (size-capped)
# A file list with SHA-256 made on the runtime, checked here after the copy:
# a run counts only when what arrived matches what the runtime wrote.
ssh runtime "cd /content/job && cp progress.txt runner.log out/ 2>/dev/null; (cd out && find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 -r sha256sum > MANIFEST.sha256); du -sm out | cut -f1" > "$RES/out-mb.txt" || true
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
if [ -n "${RESULTS_REPO:-}" ]; then
	P=$(mktemp -d); mkdir -p "$P/$ID"
	(cd "$RES" && find . -type f ! -name repo.tar ! -name ssh.cfg -size -10M -print0 | tar --null -T - -cf -) | tar -xf - -C "$P/$ID"
	(cd "$RES" && find . -type f ! -name repo.tar -size +10M -print) > "$P/$ID/LEFT-OUT-over-10MB.txt"
	( cd "$P" && git init -q && git checkout -q -b "studio-results/$ID" && git add -A \
		&& git -c user.name=cloudrun -c user.email=cloudrun@localhost commit -qm "cloudrun results $ID ($(basename "$RES"))" \
		&& git push -q -f "$GH$RESULTS_REPO.git" "studio-results/$ID" ) \
		&& { say "results pushed to $RESULTS_REPO branch studio-results/$ID"; PUSHED=1; } || say "results push FAILED (kept in $RES)"
	rm -rf "$P"
fi
RC=$(python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(0 if d.get('setup_exit')==0 and d.get('run_exit')==0 else 1)" "$RES/runner.json" 2>/dev/null || echo 1)
# Results nobody can reach are a failed job: the queue stops and says so.
[ "$RC" = 0 ] && [ "$VERIFIED" = 0 ] && RC=4
[ "$RC" = 0 ] && [ "$PUSHED" = 0 ] && RC=3
say "job $ID: exit $RC; results in $RES"
exit "$RC"
