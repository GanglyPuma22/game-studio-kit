#!/bin/bash
# Runtime side: one look at the running job, printed as key=value lines for
# live_status.py on the host. Cheap (no installs, no GPU call of its own: GPU
# use comes from the sampler runtime_job.sh starts). Read-only.
JOB=${JOB_ROOT:-/content/job}
if [ ! -f "$JOB/job.json" ]; then echo "job=0"; exit 0; fi
echo "job=1"
P=$(cat "$JOB/runner.pid" 2> /dev/null)
if [ -n "$P" ] && kill -0 "$P" 2> /dev/null; then echo "pid_alive=1"; else echo "pid_alive=0"; fi
[ -f "$JOB/finished" ] && echo "finished=1" || echo "finished=0"
echo "stage=$(cat "$JOB/stage" 2> /dev/null || echo starting)"
one() { tr -d '\r' | sed 's/\x1b\[[0-9;]*[A-Za-z]//g' | grep -v '^[[:space:]]*$' | tail -1 | cut -c1-240; }
echo "progress=$(tail -n 5 "$JOB/progress.txt" 2> /dev/null | one)"
# The job's own progress line, when it writes one to $STUDIO_PROGRESS.
echo "step=$(tail -n 5 "$JOB/job-progress.txt" 2> /dev/null | one)"
# Otherwise the last line of its log (progress bars rewrite one line with \r: keep the last piece).
LOG=$JOB/out/run.log; [ "$(cat "$JOB/stage" 2> /dev/null)" = setup ] && LOG=$JOB/out/setup.log
echo "log=$(tail -c 4000 "$LOG" 2> /dev/null | tr '\r' '\n' | one)"
if [ -s "$JOB/gpu.csv" ]; then
	# Samples from the last 70 s: the highest use, and the latest memory.
	NOW=$(date +%s)
	awk -F, -v now="$NOW" '$1 >= now - 70 { u = $2 + 0; if (u > m) m = u; n++; mem = $3 + 0 }
		END { if (n) { printf "gpu_util_max=%d\ngpu_mem_mb=%d\ngpu_samples=%d\n", m, mem, n } }' "$JOB/gpu.csv"
fi
exit 0
