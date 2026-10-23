#!/bin/bash
# Service host: the standing queue. Every POLL seconds it reads queue.txt on
# QUEUE_BRANCH of QUEUE_REPO (a private repository; jobs/<id>.json next to it)
# and runs each new line through colab_job.sh, with the runner scripts taken
# from this kit checkout (update it only on purpose).
#
#   service.sh run     the loop (systemd starts this; see studio-cloudrun.service)
#   service.sh go      the person's typed go: clears a stop and starts the service
#   service.sh stop    stop launching; running jobs finish and push results
#   service.sh status  last lines of the log
#
# Bounds (a standing go covers only these): jobs listed in queue.txt only;
# repos in ALLOW_REPOS and refs in ALLOW_REFS only; MAX_PAR queued jobs at
# once (default 1; a job run directly with colab_job.sh runs beside these,
# when the person asks for it to run now); MAX_JOBS
# (10) launched per go; MAX_HOURS (16) per go; no new launch after a job
# fails. On a clean stop the service writes $WORK/stopped and stays stopped,
# across reboots, until the next go. A crash or a reboot mid-go restarts it.
set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
KIT=$(cd "$HERE/../../.." && pwd)
WORK=${CLOUDRUN_WORK:-$HOME/studio-cloudrun}; mkdir -p "$WORK"
[ -f "$WORK/service.env" ] && . "$WORK/service.env"   # the host's own settings, never in git
GH=${GH:-git@github.com:}
QUEUE_REPO=${QUEUE_REPO:?set QUEUE_REPO (owner/name of a private repo) in $WORK/service.env}
QUEUE_BRANCH=${QUEUE_BRANCH:-studio-queue}
export ALLOW_REPOS=${ALLOW_REPOS:?set ALLOW_REPOS in $WORK/service.env}
export ALLOW_REFS=${ALLOW_REFS:-claude/* codex/* main}
export RESULTS_REPO=${RESULTS_REPO:-$QUEUE_REPO}
MAX_PAR=${MAX_PAR:-1}; MAX_JOBS=${MAX_JOBS:-10}; MAX_HOURS=${MAX_HOURS:-16}
LOG=$WORK/service.log; DONE=$WORK/service.done; touch "$DONE"
say() { echo "[service $(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }

push_status() {
	local P; P=$(mktemp -d)
	tail -n 300 "$LOG" > "$P/QUEUE-STATUS.txt"
	( cd "$P" && git init -q && git checkout -q -b studio-results/queue-status && git add -A \
		&& git -c user.name=cloudrun -c user.email=cloudrun@localhost commit -qm "queue status $(date -u +%FT%TZ)" \
		&& git push -q -f "$GH$RESULTS_REPO.git" studio-results/queue-status ) > /dev/null 2>&1 || echo "status push failed" >> "$LOG"
	rm -rf "$P"
}

case "${1:-run}" in
	go)
		rm -f "$WORK/stopped" "$WORK/stop"; : > "$WORK/go-$(date -u +%Y%m%dT%H%M%SZ)"
		say "go typed by the person"
		systemctl --user start studio-cloudrun.service 2> /dev/null || { nohup bash "$0" run > /dev/null 2>&1 & }
		exit 0 ;;
	stop) touch "$WORK/stop"; say "stop asked"; exit 0 ;;
	status) tail -n 40 "$LOG"; [ -f "$WORK/stopped" ] && echo "stopped: $(cat "$WORK/stopped")"; exit 0 ;;
	run) ;;
	*) echo "usage: service.sh run|go|stop|status" >&2; exit 2 ;;
esac

[ -f "$WORK/stopped" ] && { echo "stopped ($(cat "$WORK/stopped")); waiting for a go"; exit 0; }
exec 7> "$WORK/service.lock"; flock -n 7 || { echo "another service.sh is running"; exit 1; }
GO=$(ls -t "$WORK"/go-* 2> /dev/null | head -1)
[ -n "$GO" ] || { echo "no go on record; run: service.sh go"; echo "never started" > "$WORK/stopped"; exit 0; }
T0=$(stat -c %Y "$GO")
QDIR=$WORK/queue; [ -d "$QDIR/.git" ] || git clone -q --depth 1 -b "$QUEUE_BRANCH" "$GH$QUEUE_REPO.git" "$QDIR" || { say "cannot clone $QUEUE_REPO $QUEUE_BRANCH"; exit 1; }
LAUNCHED=$(cat "$WORK/launched-$(basename "$GO")" 2> /dev/null | grep -c "^launched " || true)
declare -A PIDS=()
STOPPED=""
say "start: $QUEUE_REPO:$QUEUE_BRANCH, $MAX_PAR at once, $MAX_JOBS jobs, $MAX_HOURS h from $(date -u -d @"$T0" +%FT%TZ); repos: $ALLOW_REPOS; refs: $ALLOW_REFS"
push_status
while :; do
	for pid in "${!PIDS[@]}"; do
		kill -0 "$pid" 2> /dev/null && continue
		wait "$pid"; rc=$?; id=${PIDS[$pid]}; unset "PIDS[$pid]"
		say "done $id: exit $rc"
		[ "$rc" != 0 ] && STOPPED=${STOPPED:-"job $id exit $rc"}
		push_status
	done
	[ -f "$WORK/stop" ] && STOPPED=${STOPPED:-"stop asked"}
	[ $(( $(date +%s) - T0 )) -gt $(( MAX_HOURS * 3600 )) ] && STOPPED=${STOPPED:-"$MAX_HOURS h limit"}
	[ "$LAUNCHED" -ge "$MAX_JOBS" ] && STOPPED=${STOPPED:-"$MAX_JOBS jobs launched"}
	if [ -n "$STOPPED" ]; then
		if [ ${#PIDS[@]} -eq 0 ]; then
			echo "$STOPPED at $(date -u +%FT%TZ)" > "$WORK/stopped"; rm -f "$WORK/stop"
			say "stopped: $STOPPED; waiting for the next go"; push_status; exit 0
		fi
		sleep 60; continue
	fi
	if git -C "$QDIR" fetch -q --depth 1 origin "$QUEUE_BRANCH" && git -C "$QDIR" reset -q --hard FETCH_HEAD; then
		if ! LIST=$(python3 "$KIT/scripts/studio.py" cloudrun queue --queue "$QDIR/queue.txt" 2>> "$LOG"); then
			say "queue.txt unreadable; nothing launched"
		else
			STOPLINE=$(python3 -c "import json,sys;print(json.load(sys.stdin)['stop'])" <<< "$LIST")
			[ "$STOPLINE" = True ] && STOPPED="STOP line in queue.txt"
			while read -r name; do
				[ -z "$name" ] && continue
				grep -qxF "$name" "$DONE" && continue
				[ ${#PIDS[@]} -ge "$MAX_PAR" ] || [ "$LAUNCHED" -ge "$MAX_JOBS" ] && break
				echo "$name" >> "$DONE"
				mkdir -p "$WORK/jobs"; cp "$QDIR/jobs/$name" "$WORK/jobs/$name" 2> /dev/null || { say "skip $name: no jobs/$name"; continue; }
				nohup bash "$HERE/colab_job.sh" "$WORK/jobs/$name" > "$WORK/run-${name%.json}.log" 2>&1 &
				PIDS[$!]=${name%.json}; LAUNCHED=$((LAUNCHED + 1))
				echo "launched $name" >> "$WORK/launched-$(basename "$GO")"
				say "launched ${name%.json} ($LAUNCHED of $MAX_JOBS)"; push_status
				sleep 30
			done < <(python3 -c "import json,sys;print('\n'.join(json.load(sys.stdin)['jobs']))" <<< "$LIST")
		fi
	else
		say "fetch $QUEUE_BRANCH failed"
	fi
	sleep "${POLL:-300}"
done
