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
then, refuses a project that does not already exist (a mistyped `--project` is
never created), isolates the profile under `artifacts/launches/<label>/profile`,
re-reads the engine's bytes at the launch instant so only the verified identity
starts, removes child environment variables that match `--scrub-env` prefixes,
launches through the runner, waits, and returns
**one verdict JSON**. The calling agent never polls, sleeps or writes to the
child's stdin; it reads the verdict when the command returns.

```text
python <KIT>/scripts/studio.py launch --project <GAME> --config <HOST> \
  --sha256 <engine sha256> --mode native --script res://tests/probe.gd \
  --cutoff-utc 2026-09-15T13:00:00Z --label foundation-01 \
  --result artifacts/foundation/summary.json -- --regional-site coast
```

The run directory itself is contained like a declared result: a symlinked
`artifacts/` that would put the receipts outside the project, or inside the
installed toolkit, is refused before anything is written.

Each run directory holds `owned-launch.json` (engine identity before and after
the run, mode, script, passthrough count, profile, cutoff, effective timeout,
PID, surviving descendants), `process/` with the runner's `stdout.log` and
`process.json`, `diagnostics.json` from the complete log, and `exit.json` with
the verdict. Verdicts: `completed` (exit zero, no engine errors, every
`--result` present), `engine_errors`, `results_missing`, `results_unreadable`,
`failed`, `timed_out`, `start_failed`, `interrupted`, `cutoff_passed`,
`engine_replaced`, `descendants_survived`, `descendants_unverified`. Only
`completed` is `ok`; the command exits 1 otherwise and still prints the verdict
to stdout. Exit zero is not acceptance. A declared result that exists but cannot
be read is reported as `present: false, unreadable: true` with a null hash and
gives `results_unreadable`: the receipts are still written, because an
unreadable result is a verdict about the run, not a failure of the launcher.

The engine is hashed again at the launch instant and once more after the run.
Bytes that changed before the launch refuse it (`engine_replaced`, nothing
started); bytes that changed during it make the run `engine_replaced` too, and
`engine.sha256_after_exit` records what the file held at exit. After an engine
that was not interrupted and did not time out exits, anything still running in
its process group (POSIX) or its parent tree (Windows) is stopped and recorded
in `survivors`: found processes are `descendants_survived`, an enumeration this
host could not perform is `descendants_unverified`. A process that re-parented
out of both is not seen. Priority, highest first: `interrupted`,
`engine_replaced`, then the descendant verdicts.

On Windows a PID is only a slot in the process table, and the engine has been
reaped by the time its tree is walked, so a verified descendant is one whose
parent chain reaches the engine through rows that are themselves verified,
whose creation time falls inside the engine's own lifetime (both read from the
handle the launcher owned, not from the PID), and which was not already running
in the snapshot taken before the launch; only those are stopped, each one's
identity read once more immediately before the kill, and each one signalled on
its own rather than as a tree. The walk already names every verified child, so
the proven tree is covered PID by PID, while a tree kill would also take the
rows that same walk refused and anything spawned under them since the snapshot.
A verified PID the table no longer holds at the kill has exited by itself and
counts as stopped. The verified set is signalled deepest first, so a parent's
row is still in the table while its children are being accounted for, and each
PID that was signalled is then read on its own until it is proven gone: once a
parent is out of the table nothing below it is reachable from the engine's PID,
so an enumeration that comes back empty is not by itself proof that a tree
stopped. `stopped` is true only when every signalled PID was confirmed gone,
the final walk found no verified survivor and nothing was ever unverified; a
PID still present at the deadline is reported in `survivors.unstopped_pids`,
and one whose last lookup could not be read is `stop_unconfirmed` in
`survivors.unverified`. Everything else that merely hangs under that PID is listed
in `survivors.unverified` with a reason and left running, and the launch is
`descendants_unverified`: the operator has a process to look at and decide
about by hand, and the alternative would be this launcher killing a stranger's
process tree that happened to inherit the number. Every snapshot taken while
stopping contributes to that list, not only the first, so a process that
becomes visible mid-cleanup is still reported once the last snapshot comes back
clean. `stopped` is never true while anything is unverified.

The prelaunch snapshot belongs to the caller and is never taken by the runner:
on Windows it is a PowerShell enumeration of every process on the host, and a
caller measuring a quiet machine (the cleanroom bench) would otherwise see this
toolkit's own query as a newcomer with CPU time. A caller takes it where its
receipts, its measurements and its interrupt handling can afford it and passes
it in; a job whose descendants nobody will stop, such as the cleanroom bench's
own capture, takes none at all. Without
one, `windows_ownership` is recorded as unavailable with the note "no prelaunch
baseline was supplied", and cleanup then reports what it found instead of
signalling it.

Where a caller does take it, the order is snapshot, then bytes, then cutoff,
because enumerating every process can cost seconds: a snapshot taken after the
digest recheck would sit between a verified engine and the process that starts,
so bytes replaced during the query would run with the verified hash on record,
and a snapshot taken after the cutoff recheck would spend part of the
authorized window after it had been judged open and hand the engine a timeout
computed before that cost. `blender run` takes it before its own executable
recheck for the same reason, after writing a first `run.json`, and an interrupt
during the query ends in that run's `interrupted` receipt rather than a
reserved directory nothing explains.

Cleanup itself is bounded: every query it makes draws on one budget of
30 seconds, the identities of all the PIDs it is about to signal are read in a
single query rather than one each, and what the budget did not allow to be read
is reported unread rather than guessed at. A descendant that only becomes
visible in a walk taken after the first kill is signalled and held like the
rest, because once its parent's row is gone no later walk can reach it.

A `--result` must name engine output: a path inside
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
paired only when both receipts carry the matching kind, `label` and `scope`, and
a `process.json` beside them only when it is `schema_version` 1 and carries this
launch's PID; otherwise the entry reports `pairing: "mismatched"` with a reason,
lends no verdict, result files or process lifecycle summary (status, return
code, elapsed time, cleanup), is counted in `totals.mismatched` and makes the
inventory `ok: false` (the command exits 1). A launch whose `process_record`
names a receipt that is not there reports `pairing: "missing_process"` with
verdict `no_process_record`, is counted in `totals.missing_process` and makes
the inventory `ok: false` the same way; a refusal that never started the engine
declares no process record (`process_record: null`) and still pairs normally. A
relative `--output` must stay under the run root; only an absolute path may
leave it, and never into the installed toolkit. It is counts and hashes only; a
launch with no exit record is reported as `pairing: "missing_exit"`.

`candidate verify --manifest <identity-manifest.json>` hashes every item in an
[identity manifest](../templates/identity-manifest.json) (engine, helpers,
sources, packages, assets; absolute paths allowed for files outside GAME, in
this host's own spelling only — a Windows-absolute path read on POSIX, or a
POSIX-absolute one read on Windows, is refused as absolute for another host
rather than reported missing, and a drive-relative `C:name` is refused
everywhere) and writes a dated receipt under `artifacts/identity/`, contained
like any other output so a symlinked `artifacts/` cannot place it outside the
project or inside the installed toolkit, with per-item match/mismatch/missing
and one verdict. An `engine` item may omit `path` and
carry `"source": "host-config"` instead: it is resolved through
`executables.godot` from the host config given with `--config`, so a host path
stays in ignored host configuration and the receipt reports `path: null` with
`source: "host-config"`, never the resolved location. No configured engine, or a
configured one that is absent, is `missing`. Every other item still requires
`path`, and `source` is rejected anywhere else. A matching hash is byte
identity, not acceptance or entitlement.

## Interactive playtest receipts

`playtest` is the same machinery aimed at a session a person drives and judges.
It verifies the engine's expected SHA-256 the same way, refuses a project that
does not exist, re-reads the engine bytes at the launch instant, honours
`--cutoff-utc` and `--scrub-env`, and writes to
`artifacts/playtests/<label>/` — a separate namespace, so a playtest and an
owned launch can never collide on the label that refuses a reused run
directory. Each run directory holds `playtest.json` (session mode, scene and
its hash, harness script, engine identity before and after, profile, commit and
whether the tree was dirty, renderer and resolution, effective cap, PID),
`process/` with the runner's log and record, `diagnostics.json`, and `exit.json`.

**The renderer and window size come from the game, not from the kit.**
`launch --mode native` pins `1920x1080` and `forward_plus`, which suits a
bounded smoke of a known configuration. A playtest exists to show what a player
would see, and the renderer is exactly the variable that decides whether
flicker, banding and transparency artifacts appear at all — so forcing one can
invent a defect the player will never hit or hide one they will. `playtest`
therefore reads `renderer/rendering_method` and the viewport size from
`project.godot` and uses them; `--rendering-method` and `--resolution` override
them explicitly; a project that declares neither falls back to the pinned
defaults. `rendering_method_source` and `resolution_source` record which of
`project`, `override` or `default` applied, so a fallback is never mistaken for
the game's own configuration.

Two further things differ from `launch`, both deliberately. A session may exceed the
3600-second ceiling: `--max-minutes 0` runs until the player quits and is legal
only for `handoff` and `attended`, where a human decides when it ends, while
`driven` stays bounded because nobody is at the controls. And profile isolation
discards saves and settings between runs, which is usually wrong for a
playtest, so `--use-host-profile` plays on the real user profile and records
`"profile": "host"` — a receipt is never ambiguous about which profile ran. An
isolated session still refuses a self-contained `_sc_` Godot, because such an
install ignores the profile environment; a host-profile session accepts it,
since it claims no isolation to begin with.

**`ok` is run health, and nothing in these receipts is ever acceptance.** It
means the engine ran, exited cleanly, logged no errors and produced every
declared `--result`. No program can decide whether a playtest went well, so
`acceptance` is `"not_established"` in every mode including `driven`, and the
limits carry `a playtest launch is not acceptance; a human verdict is required`
alongside the existing `exit zero is not acceptance`. A green `driven` harness
establishes wiring, not normal-input usability.

`--session attended` starts the game and returns, so an agent keeps its desktop
and voice tools while somebody plays. Nothing waits for that process, so its
exit code, elapsed time and surviving descendants are never observed: the exit
receipt says `status: "unobserved"` with a null return code rather than
inventing either, and reports `engine_running_at_collect` as true, false, or
null on a host that cannot tell.

For the same reason an attended session takes no time cap. A `--max-minutes`
there could only be written into a receipt, never applied, so a non-zero value
is refused outright and `max_minutes_effective` is always null; `--cutoff-utc`
still gates whether the session may *start*, but nothing can end it except the
player. Liveness is answered from `/proc` on POSIX and from the same
`Win32_Process` table the descendant walk uses on Windows; a host with neither
reports null, and because a PID can be reused, a true answer is a statement
about the PID rather than proof the original process still holds it. Read a
null `engine_running_at_collect` as "not established", never as "the session
ended". A `collect` that finds the engine still running **refuses** instead of
writing a receipt: recording it would spend the one collection the session
gets, so a call that merely raced the player's last click would lock out the
real receipt for good. It is completed by exactly one `playtest
collect --label <label>`, run after the player says they are done; a second
call is refused, because calling it repeatedly to discover when the game closed
is polling.

A `driven` session is told where to write. The kit appends
`--studio-playtest=<run>/harness.json` itself, records the path in
`playtest.json` and hashes the report into `exit.json`, so the report path and
the recorded evidence cannot disagree; passing that argument explicitly is
refused. A missing, unparseable or failing report gives
`harness_report_missing`, `harness_report_unreadable` or `harness_failed`
rather than a clean `completed`. Declaring the report through `--result` is
neither needed nor possible, since it lives in the run directory the launcher
owns; `--result` remains for anything else the route must produce.

With `--emit-launcher` (the default) the run directory also gets `relaunch.cmd`
on Windows or `relaunch.sh` elsewhere, generated from the exact argument array
that ran so it cannot drift from the session it documents, with the label,
engine SHA-256, commit and profile in its header. It carries no environment:
reproducing one would either write scrubbed values into a file or silently
claim an isolation it does not set up, so the header names the profile the
recorded session used and the script plays on the runner's own. It changes to
the project directory first, because the session itself ran with the project as
its working directory: a launcher invoked from a desktop shortcut or another
directory would otherwise resolve a relative path against somewhere else while
claiming to reproduce the recorded command. A person runs it without this kit,
without Python and without an agent.

## Cleanroom windows and host readiness

A performance number is citable only with a cleanroom pair around it. `bench
cleanroom` takes a host snapshot (process names with parent pid, creation time,
CPU seconds and working set, `nvidia-smi` devices and compute apps, active
power scheme, battery, recorder processes), runs the capture command once
through the owned runner, snapshots again, and writes `before.json`,
`after.json`, `during.json`, the capture's job receipts and `cleanroom.json`
under `artifacts/bench/<label>/`. `cleanroom.json` cites each of those files as
a project-relative path with its SHA-256, so the receipt stays checkable on
another machine and an edited artifact shows; absolute paths appear only in the
command's stdout. The project must already exist: a mistyped `--project` is
refused, never created. Contamination thresholds
(`--busy-fraction`, `--busy-floor-seconds`, `--heavy-working-set-mb`) are
validated before the capture, so a non-finite or out-of-range threshold cannot
quietly label a dirty window clean:

```text
python <KIT>/scripts/studio.py bench cleanroom --project <GAME> --label settled-01 \
  --agent-log <path to the agent's activity log> -- \
  python <KIT>/scripts/studio.py launch --project <GAME> --sha256 <engine> --mode native \
  --script res://tests/regional_foundation_probe.gd --label settled-01
```

`attributable` is true only when nothing else changed inside the window: no
heavy process appeared or exited, no other process consumed CPU beyond the busy
threshold, no GPU compute process appeared or exited, the power scheme did not
change, the host was on AC power in both snapshots, no recorder process was
present, and the agent log (when supplied) stayed readable, with no timestamps
inside the window and none without a UTC offset. A log that was readable when
the bench started and cannot be read at the comparison is its own reason
("agent log became unreadable inside the window"); the receipt is still
written. Each violation is a named reason. Missing GPU counters, and an AC
line status the host reports as unknown, are limits, not reasons: Windows
answers "unknown" rather than "on battery" when it cannot tell, and the
difference is not invented here. The command never stops any process
other than its own capture. An agent must make no tool calls while the command
runs; the command owns the wait.

Two snapshots cannot see a program that lives entirely between them, so one
long-lived sampler walks the process table for the life of the capture
(`--sample-interval`, 1–60 seconds, default 10) and records recorder processes
and heavy newcomers with first/last-seen timestamps in `during.json` and under
`during` in the receipt. A recorder observed mid-window is a reason, and so is
a heavy process that ran and exited before the second snapshot. The sampler
only reads; its own enumeration helpers and the owned capture's process tree
are excluded from the newcomer count, and it never signals anything. Recorders
are the exception: one that the capture itself started still contaminates the
window and is still a reason. The sampler's baseline is the before snapshot,
not its own first sample, so a program that started in between belongs to the
window rather than to the quiet host. Anything shorter-lived than the interval
can still be missed, which is a stated limit rather than a clean result.

A process is identified by pid, name and creation time, not by pid alone. A pid
the OS hands to another program inside the window is therefore a newcomer to
the sampler and an exit plus an appearance to the before/after diff, rather
than one long-running process with a CPU delta, and a sampled newcomer counts
as still present afterwards only when that whole identity is in the after
snapshot.

If either snapshot's process query fails, `process_enumeration` says so and the
window is not attributable: an empty process table is a failed query, not a
quiet host.

`--scope <id>` names the scope rung the bench is evidence for and is persisted
in `cleanroom.json`. Asking for a rung is asking for proof of it, so the
capture's own receipt must name the same rung: `scope_check` reports `match`,
`mismatch`, `missing` or `unparsed`, and anything but `match` is a reason. A
lower-rung result is therefore never citable for a higher one.

`host preflight` reads Windows Update pause state, pending-reboot keys, active
hours, power scheme and battery without changing anything, and judges them
against an optional `--window-start/--window-end` (UTC). `host apply` runs the
packaged [Prepare-OvernightHost.ps1](../skills/studio-review/scripts/host/Prepare-OvernightHost.ps1)
with a mandatory receipt path; use `--what-if` first, which still writes a real
receipt because the `--what-if` run is itself the evidence. The script exits 2
when it refuses and 3 when a change failed part-way through, and writes its
receipt (with `refused`, `failure` and `partial`) before either; `host apply`
returns that receipt with `ok: false` rather than raising, so a half-applied
change is reported instead of lost. A window is judged only when it is between
one minute and eighteen hours long, and preflight refuses a window that has
already ended; a window under way is still judged. `host apply` refuses an
active-hours span longer than the 18 hours Windows allows before it launches
PowerShell at all. `--output` and `--receipt` must be outside
the installed toolkit, like every other output. On non-Windows hosts preflight
reports `host_kind: unsupported` and apply refuses.

## Fields that say what a receipt does not prove

**Evidence identity (`identity`, `evidence_current`, `evidence_total`).** Every
capture, bench or cleanroom row attached to a candidate verdict carries
`identity`: `current` when the receipt's recorded content digest is the
candidate's own, `historical` when it recorded a different one, and `unknown`
when it recorded none at all — a launch exit or a cleanroom bench knows a
project, never a candidate, so `unknown` means nothing was written down rather
than that something has moved on. The comparison is between two digests already
on record; no file is re-hashed, so `current` says the receipt was taken from
the inventory this candidate names, not that the files on disk still match it
(`validate-record` is what checks that). Each verdict also carries
`evidence_total` and `evidence_current`, recomputed whenever a row is attached.
A verdict whose two numbers differ is resting partly on content that has since
changed; neither number is a judgement about what the evidence showed.

**Startup failure (`phase`, `first_error`, `verdict: startup_failure`).** The log
classifier now reports `phase` — `load`, `runtime` or null — and `first_error`,
the first `ERROR:`/`SCRIPT ERROR:` line stripped of terminal colour escapes and
truncated to 240 characters. `load` means the first error in the log was a
load-time signature (a parse error, a script or resource that would not load, a
scene that would not instantiate) and that error's own `at:` continuation did
not name a running callback; anything else with an error is `runtime`. When a
launch or playtest exits non-zero and the phase is `load`, the verdict is
`startup_failure`, reported ahead of `engine_errors` because the game never
reached the point where its own diagnostics would mean anything. Elapsed time is
never consulted: a slow host is not a startup failure, and a fast one is no
evidence the game came up. A `load` phase alongside exit zero remains
`engine_errors`, and a timeout remains `timed_out` however the log reads.

**Ready marker (`ready_seconds`).** A project may declare
`settings.ready_marker` in its `project.json`: a literal line substring its
engine prints once it is up. The runner then checks the growing log no more than
four times a second while it waits for the child, and records `ready_seconds` —
monotonic seconds from process creation to the first line containing that
substring — in `process.json`, and `launch` and `playtest` copy it into
`exit.json`. It is null when nothing was declared and when the child never
printed it, and a run with no marker never reads the log while it waits at all.
This is a load-time measurement and nothing more: it does not show the game is
playable, that the scene finished loading, or that anything printed after the
marker was correct. `ready_seconds is a load-time measurement, never acceptance`
is in the `limits` of both receipts for that reason. A project whose declared
marker is not a nonempty string is refused before a run label is reserved.

**Performance class (`performance_class`).** A cleanroom bench writes
`clean_qualification` when its window was `attributable` and its capture
completed, and `diagnostic` otherwise. A native `launch` that had to produce a
declared result writes `diagnostic`; every other launch writes no class at all,
because it measured nothing worth classifying. When such a receipt is attached
to `verdicts.performance`, its class is copied onto the row and the verdict's
own `performance_class` rollup is recomputed over the `current` rows only:
`clean_qualification` when every one of them is a clean qualification,
`subjective_acceptance` when every one of them is a person's own review
(`native_visual`, `native_capture_review`, `listening`, `ordinary_input`) with
no measured class, `diagnostic` when every one of them is a diagnostic,
`mixed` when the classes differ, and `unverified` when no row still describes
this content. Only `clean_qualification` qualifies a performance claim.
`clean_qualification` means the number was measured in a window nothing else
contended for; it is not a claim that the number is good.

**Kit identity (`kit`) and result re-hashing.** Every receipt recording an
operation — `owned-launch.json`, `exit.json`, `playtest.json`, Blender's
`run.json`, `reduce.json` and inspection output, `cleanroom.json`, a new
`candidate.json`, the batch summary and the doctor report — carries `kit`:
`{"version", "source_digest"}`, where the digest is taken over every
`studio_tools/**/*.py` file with its path and byte length mixed in. The version
alone names a release, which a working tree, a half-applied update or a local
patch all keep; the digest names the Python that actually ran. It says nothing
about which skills, references or templates were present, and nothing about
whether the kit came from a release. `studio evidence verify --receipt <path>`
re-hashes the files a receipt recorded a digest for and reports each as
`current`, `changed` or `missing`, with `ok` true only when every one is
current and at least one was recorded. No result bytes are copied anywhere, and
a file still matching its digest is a statement about bytes alone — not that it
is correct, complete or acceptable.

**Credential source (`credential_source`, `credential_files`).** `doctor` now
reports, per provider, where a key would actually come from if something asked
for one right now: `environment` when the configured variable is set, `file`
when a declared `credential_files` entry holds a nonempty value for it, and
`none` otherwise — the same order `credential` resolves in, so the report cannot
name a source the next call would not use. `status` is `unverified` whenever a
key is present from either source and `needs_setup` otherwise; a host that keeps
its keys in a declared file is no longer told to set up a provider it has
already configured. The report also lists each declared file with `present`,
`readable` and the key names it declares. Names only: no value from any file or
environment variable is reported, and a name appearing in that list means the
file mentions it, not that it carries a usable value and not that any account is
entitled to use it. Nothing is loaded into `os.environ`, so nothing this kit
starts inherits a key it was not given deliberately, and `unverified` remains
what it always was — a key exists, no provider was contacted.
