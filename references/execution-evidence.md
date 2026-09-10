# Process and evidence lifecycle

Use the existing argument-array runner for a bounded, verified local operation.
Python callers may import it from the selected KIT on their module path:

```python
from pathlib import Path
from uuid import uuid4
from studio_tools.processes import run

job = Path(game) / "artifacts" / "jobs" / uuid4().hex
result = run(
    args, cwd=game, timeout=180, env=child_environment,
    hide_window=True, job_dir=job,
)
```

Supply a **new** job directory. Reusing it fails before launch. The runner writes
combined stdout/stderr bytes to stdout.log while the process runs and atomically
records process.json at starting/running/final states. Records include owned PID,
UTC timestamps, monotonic elapsed seconds, return code and timeout cleanup status.
They exclude argv and environment; keep application logs private because the
application itself may print sensitive data. Explicit child environment overrides
do not mutate the parent environment.

Timeout and nonzero exit retain the partial/final log. Startup failure records a
null PID and start_failed. Only bytes flushed by the child reach the log; a hard
kill may lose output still buffered inside the application.
A failed cleanup is unverified, never "stopped"; inspect
that owned PID before another heavy job. Cleanup targets the launched process tree,
not a process name. Commands must stay in the foreground until their work finishes;
daemonized work needs an operation-specific lifecycle, not a successful parent exit.

The older log=path argument remains available and deliberately replaces that
caller-selected log after a successful launch; a failed launch restores its prior
bytes. Use job_dir for repeated runs and immutable history; do not
supply both. Successful returns name the log and process_record. The raw log bytes
are preserved; stdout in the returned value is decoded as UTF-8 with replacement.

On Windows, hide_window requests CREATE_NO_WINDOW for the console and its timeout
cleanup command. It cannot suppress a GUI that an application chooses to open.
Blender background operations and Godot headless operations request it; ordinary
Godot run remains visible. [Gaea](../skills/studio-terrain/references/gaea.md) needs
separate verification of a genuinely unattended operation. A hidden console or
an installed executable is not sufficient capability evidence.

## Complete logs before status

Godot operations store a fresh artifacts/jobs/godot-<mode>-<id>/ directory for
each run. Zero-exit runs also get diagnostics.json; nonzero/timeout/start failures
retain their process record and log, with the job identity in the exception.
Inspect the returned process_evidence paths
instead of relying on a fixed godot-import.log that a later run overwrites.

A process record saying completed means the child exited zero. It is distinct
from engine success. The Godot adapter classifies the **complete** output after
exit; ERROR and SCRIPT ERROR fail the operation. WARNING and Orphan StringName
are counted and reported as warnings, not clean. Empty captured output is
unverified and fails headless operations. Project-owned Godot checks can
reuse studio_tools.adapters.godot.classify_log(completed_output). The function
only classifies text; it cannot tell whether the caller supplied the full log or
whether a warning is acceptable. Keep original diagnostics and record the review
decision separately. A shorter clean comparison does not clear a longer run's
shutdown leak.

Keep input/revision paths as explicit parameters. Never derive a new revision by
replacing a short substring throughout source code or filenames: that can mutate
extensions and parent source identities. Verify every required input first and
stop dependent work if preparation fails. Use distinct output identities and
derived-from hashes; archive a new assessment rather than editing old verdicts.
Use [archive_capture](acceptance.md) for existing capture bytes.

## Time and pass accounting

Reuse the work card's authorization and budget. Keep a single event ledger of
active/idle intervals, grant start/expiry/release and export/composition use.
Reserve a pass before starting it; record its outcome and consumption. Within one
process use monotonic elapsed time. Across resumptions retain explicit UTC offsets
and interval identities; never subtract an unspecified local time from UTC or
count an idle wait as active work. Every derived remaining-budget report states
its cutoff. A fresh receipt does not require asking again within an existing
valid grant.

## Owned blocking launch and inventory

`launch` is the one-call form of the runner for a project-owned engine run:
probes, native captures, unattended production stages. It verifies the engine's
expected SHA-256 before anything else, refuses a self-contained Godot
(`_sc_`/`._sc_` beside the executable) because such an install ignores the
profile environment, refuses to start after `--cutoff-utc`, rechecks that
cutoff immediately before starting and bounds the wait by what is left of it
then, isolates the profile under `artifacts/launches/<label>/profile`, removes
child environment variables that match `--scrub-env` prefixes, launches through
the runner, waits, and returns
**one verdict JSON**. The calling agent never polls, sleeps or writes to the
child's stdin; it reads the verdict when the command returns.

```text
python <KIT>/scripts/studio.py launch --project <GAME> --config <HOST> \
  --sha256 <engine sha256> --mode native --script res://tests/probe.gd \
  --cutoff-utc 2026-09-15T13:00:00Z --label foundation-01 \
  --result artifacts/foundation/summary.json -- --regional-site coast
```

Each run directory holds `owned-launch.json` (engine identity, mode, script,
passthrough count, profile, cutoff, effective timeout, PID), `process/` with the
runner's `stdout.log` and `process.json`, `diagnostics.json` from the complete log,
and `exit.json` with the verdict. Verdicts: `completed` (exit zero, no engine
errors, every `--result` present), `engine_errors`, `results_missing`, `failed`,
`timed_out`, `start_failed`, `interrupted`, `cutoff_passed`. Only `completed` is
`ok`; the command exits 1 otherwise and still prints the verdict to stdout.
Exit zero is not acceptance. A `--result` must name engine output: a path inside
this launch's own directory (its receipts, log or profile) is refused before
anything is written, so a file this launcher wrote is never counted as evidence
that the engine produced something. Receipts never contain argv values or
environment; passthrough arguments are counted, not recorded. `--scope <id>`
names the scope rung the launch is evidence for; it is validated like a label
and persisted as `scope` in `owned-launch.json`, `exit.json`, the returned
verdict and every inventory entry (`null` when omitted), so a lower-rung result
cannot be cited for a higher rung.

`evidence launches <run root>` indexes every `owned-launch.json` under a root,
pairs it with its `exit.json` and process record, hashes both receipts, counts
log bytes and result files, and writes a dated `launch-inventory-*.json`. Each
receipt is hashed from the same bytes that were summarized. An `exit.json` is
paired only when both receipts carry the matching kind, `label` and `scope`;
otherwise the entry reports `pairing: "mismatched"` with a reason, lends no
verdict or result files, is counted in `totals.mismatched` and makes the
inventory `ok: false` (the command exits 1). A relative `--output` must stay
under the run root; only an absolute path may leave it, and never into the
installed toolkit. It is counts and hashes only; a launch with no exit record is
reported as `pairing: "missing_exit"`.

`candidate verify --manifest <identity-manifest.json>` hashes every item in an
[identity manifest](../templates/identity-manifest.json) (engine, helpers,
sources, packages, assets; absolute paths allowed for files outside GAME) and
writes a dated receipt under `artifacts/identity/` with per-item
match/mismatch/missing and one verdict. A matching hash is byte identity, not
acceptance or entitlement.
