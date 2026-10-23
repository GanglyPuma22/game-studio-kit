#!/bin/bash
# Service host side (the always-on box, e.g. Aptivio in WSL): run one job on a
# Colab GPU runtime from start to finish, then stop the runtime.
#   colab_job.sh JOB.json
# Needs: the colab CLI signed in by the person, git access to the job's repo
# (GH, default git@github.com:), python3. The job's commands run only on the
# runtime; this host packs the commit with git archive, copies it in, polls,
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
ID=$(J 'print(d["id"])'); REPO=$(J 'print(d["repo"])'); REF=$(J 'print(d["ref"])')
GPU=$(J 'print(d.get("gpu","L4"))'); MAXMIN=$(J 'print(int(d["max_minutes"]))'); CAPMB=$(J 'print(int(d.get("results_max_mb",200)))')
SESSION=${COLAB_SESSION:-studio-$ID}
mkdir -p "$WORK/results" "$WORK/repos"
RES=$(mktemp -d "$WORK/results/$ID-$(date -u +%Y%m%dT%H%M%SZ)-XXXX")   # fresh per run, even for a reused id
say() { echo "[cloudrun $(date -u +%T)] $*" | tee -a "$RES/driver.log"; }
command -v colab > /dev/null || { say "colab CLI not found: stop"; exit 1; }

# --- 0. the exact commit, packed here (no .git, no credentials go to the runtime)
MIRROR=$WORK/repos/${REPO//\//__}.git
[ -d "$MIRROR" ] || git clone -q --bare "$GH$REPO.git" "$MIRROR"
git -C "$MIRROR" fetch -q origin "+refs/heads/*:refs/heads/*" 2> /dev/null || git -C "$MIRROR" fetch -q origin
COMMIT=$(git -C "$MIRROR" rev-parse --verify -q "$REF^{commit}") || { say "ref $REF not found in $REPO: stop"; exit 1; }
git -C "$MIRROR" archive --format=tar "$COMMIT" > "$RES/repo.tar"
say "job $ID: $REPO $REF @ $COMMIT ($(( $(stat -c %s "$RES/repo.tar") / 1048576 )) MB), $GPU, cap $MAXMIN min"

# --- 1. runtime (the account holds a few GPUs at once; wait for a free one, no spend while waiting)
cat > "$RES/ssh.cfg" <<CFG
Host runtime
  HostName colab-runtime
  User root
  ProxyCommand colab ssh --proxy-mode -s $SESSION
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
  LogLevel ERROR
  ServerAliveInterval 30
CFG
ssh() { command ssh -F "$RES/ssh.cfg" "$@"; }
WAIT=${GPU_WAIT_MIN:-240}
for try in $(seq $(( WAIT / 5 + 1 ))); do
	colab new --gpu "$GPU" -s "$SESSION" && break
	[ "$try" -gt $(( WAIT / 5 )) ] && { say "no $GPU after $WAIT min: stop"; exit 1; }
	say "no free $GPU yet (try $try), waiting 5 min"; sleep 300
done
trap 'say "stopping runtime"; colab stop -s "$SESSION" || true; rm -f "$RES/repo.tar"' EXIT
T0=$(date +%s)
colab usage 2> /dev/null | head -3 >> "$RES/driver.log" || true
for try in 1 2 3 4 5; do
	ssh runtime 'mkdir -p /content/job/repo /content/job/out' && break
	[ "$try" = 5 ] && { say "ssh to the runtime failed 5 times: stop"; exit 1; }
	say "ssh not ready (try $try)"; sleep $((15 * try))
done
ssh runtime 'tar -xf - -C /content/job/repo' < "$RES/repo.tar"
ssh runtime 'cat > /content/job/job.json' < "$JOBFILE"
for f in runtime_display.sh runtime_job.sh; do ssh runtime "cat > /content/job/$f" < "$HERE/$f"; done
say "copied in after $(( $(date +%s) - T0 )) s"

# --- 2. screen, then the job (detached; polled)
ssh runtime 'bash /content/job/runtime_display.sh' >> "$RES/driver.log" 2>&1 || { say "no screen on the runtime: stop"; exit 1; }
ssh runtime 'cd /content/job && setsid nohup bash runtime_job.sh > runner.log 2>&1 < /dev/null &'
CAP=$(( (MAXMIN + 20) * 60 ))
while :; do
	sleep 60
	P=$(ssh runtime 'tail -1 /content/job/progress.txt 2>/dev/null' || true)
	echo "  $P" >> "$RES/driver.log"
	case "$P" in *" done") break ;; esac
	if [ $(( $(date +%s) - T0 )) -gt "$CAP" ]; then
		say "time cap reached: stopping the job, then fetching partial results"
		ssh runtime 'P=$(cat /content/job/runner.pid 2>/dev/null); [ -n "$P" ] && { kill -TERM -- -$P 2>/dev/null; sleep 3; kill -KILL -- -$P 2>/dev/null; }; true' || true
		break
	fi
done

# --- 3. results (size-capped)
ssh runtime "cd /content/job && cp progress.txt runner.log out/ 2>/dev/null; du -sm out | cut -f1" > "$RES/out-mb.txt" || true
MB=$(cat "$RES/out-mb.txt" 2>/dev/null || echo 0)
if [ "${MB:-0}" -gt "$CAPMB" ]; then
	say "OUT_DIR is $MB MB, over the job's $CAPMB MB: bringing back files under 10 MB only"
	ssh runtime 'cd /content/job/out && find . -type f -size -10M -print0 | tar --null -T - -cf -' | tar -xf - -C "$RES"
else
	ssh runtime 'tar -cf - -C /content/job/out .' | tar -xf - -C "$RES"
fi
say "runtime minutes: $(( ($(date +%s) - T0) / 60 ))"
colab usage 2> /dev/null | head -3 >> "$RES/driver.log" || true
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
[ "$RC" = 0 ] && [ "$PUSHED" = 0 ] && RC=3
say "job $ID: exit $RC; results in $RES"
exit "$RC"
