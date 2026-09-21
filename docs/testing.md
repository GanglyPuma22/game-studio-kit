# Validation

From the complete repository root:

```text
python -m unittest discover -s tests -v
python -m studio_tools check-package --root .
```

The standard-library tests use temporary directories and mocked provider boundaries. They cover package relocation and reference closure, invalid config/missing tools, process timeout ownership, candidate content/capture mismatches, missing exports/clip metadata, nonhumanoid rig rejection, interrupted/ambiguous Meshy lifecycle, partial downloads, local PCM/trim/loop behavior, hosted audio error redaction, terrain dimensions/seams, Gaea capability/recipe checks, app command construction, and Blender MCP status/retry policy. They do not call a provider or control the visible desktop. `Test-LifecycleContracts.ps1` checks PowerShell parsing and static invariants; it is not a count of native lifecycle behavior tests.

For optional isolated native QOA success/failure regressions, set `STUDIO_TEST_GODOT`
to an existing native Godot executable before running the suite. The test creates
its own original audio/project/profile in temporary storage and checks both the
shipped assignment and a deliberately broken compressed-byte assignment. No app
GUI or listening is involved. Without that variable, the native test is explicitly
skipped. Native Windows also skips the POSIX-only historical-filename fixture;
literal inventory validation still runs on every host. Directory-symlink tests
skip only when creation is unavailable; non-symlink path assertions always run.

The repository includes a real original GLB/Blender source and cues; tests inspect their structure/hashes rather than pretending a mocked GLB demonstrates a real export. Optional real application checks are explicit commands, not surprise prerequisites of unit tests. See [compatibility](compatibility.md) for executed versions and honest limits.

For a fresh reproduction, extract the whole package into a path with spaces and set a temporary empty agent profile. From a different game working directory, run its absolute `scripts/studio.py` entrypoint, check-package, local audio/terrain, and the fixture/import/smoke route using explicit host executables. No original workspace or generic skills are required. This verifies resource resolution and local execution; actual registered-plugin invocation requires a new native host conversation.

Run the exact [Windows smoke procedure](windows-smoke.md) before claiming native plugin discovery, ordinary controls, perceptual animation/audio or GPU performance. Paid live smoke remains a separately authorized work-card operation with current account prices; mock tests do not establish provider entitlement or visual/audio output quality.

If a check fails, preserve source and task/evidence identity. Fix only the observed issue, rerun its affected checks, and update the compatibility record. Do not advance asset/candidate acceptance to make a package validation green.

For the production process/evidence regressions alone:

```text
python -m unittest discover -s tests -p test_production_reliability.py -v
```

These use small Python child processes and mocked application boundaries. They
check partial timeout logs, startup/nonzero receipts, unique repeated Godot logs,
late exit-zero errors, warning classification, and separate Gaea native/unattended
declarations. Native Windows also checks that a hidden Python child has no console
window; this does not prove any Gaea/Blender/Godot unattended capability. No provider,
desktop control, application fixture or native QOA run is required.

## Operational review file tests

`test_validation_loop.py` covers original encoder/decoder roundtrips, owned recorder
stop/cancel/timeout/failure, stale identities, hidden mute intent, request reservation
and ambiguity, dense timestamps and refusal of self-declared perception passes.
Run `examples/review-loop/create.py --output /explicit/new/root` for a persistent
original file example and affected synthetic timing recheck. FFmpeg-dependent
tests skip when the tools are absent. These are not native/model acceptance.
See the [operational procedure](../skills/studio-review/references/validation-loop.md)
for the independently required host, known-failure/clean-control and listening proof.

## Owned launch and identity tests

`test_launch_evidence.py` covers the blocking `launch` command with small Python
child processes standing in for the engine: engine SHA-256 refusal before launch,
receipts without argv values or environment, timeout returned as a verdict with
owned cleanup, exit-zero engine errors and missing result files reported as not
ok, cutoff refusal and timeout bounding, environment scrubbing and profile
isolation, launcher mode flags, scope persistence and refusal, engine bytes
replaced before or during a launch, descendants left running by the engine,
containment of the launch directory, refusal of a project that does not exist,
unreadable declared results, launch inventory pairing of exit and process
receipts including a declared record that is gone, and identity manifest
match/mismatch/missing receipts including host-config engine items, receipt
containment and absolute paths belonging to another host. The
descendant test needs POSIX `/proc` and skips elsewhere. No engine, provider or
desktop is involved.

```text
python -m unittest discover -s tests -p test_launch_evidence.py -v
```

`test_process_identity.py` covers the Windows side of the same cleanup on this
host, with the CIM rows and the process handle faked as in the cleanroom tests:
a PID reused after the root exited is reported and not walked into, a child
created during the root's lifetime is the only kind `taskkill` is reached for
and it is signalled on its own without `/T`, a candidate with no creation time
or no launch evidence is left running and reported in `unverified`, a process
already running before the launch is not a descendant, a verified PID that had
already exited at the kill counts as stopped while one whose lookup failed or
answered with another process is refused, a process seen as unverified only in
a mid-cleanup snapshot is still reported, a descendant that only appears in a
post-kill walk is signalled and held like the rest, the verified set is
signalled deepest first and a kill that failed deep in the tree is reported
rather than hidden by a walk that can no longer reach it, a signalled PID
nothing can be read about is `stop_unconfirmed`, every cleanup query is held to
one shrinking budget, the prelaunch snapshot is taken before the launcher's
last engine-digest and cutoff checks so a launch whose engine is replaced or
whose window closes during it never starts, `run` records the caller's baseline
and never enumerates on its own, and a receipt with unverified descendants
never claims `stopped`.
The POSIX case in the same file proves group cleanup is unchanged. No process is
terminated on Windows here, because there is no Windows here.

```text
python -m unittest discover -s tests -p test_process_identity.py -v
```

## Headless Blender script runs and provider credentials

`test_blender_run.py` covers `blender run`, the command for a project-owned
bake/export/repair script, with a small Python shim standing in for
`blender.exe`: the exact headless argument line including Blender's own `--`
separator, receipts that hold the executable, source and script hashes and the
passthrough *count* while the combined log holds the values, a private marker
passed through argv appearing in `stdout.log` and in no JSON receipt, a missing
declared result and a failing script returned as a verdict rather than an
exception, a declared result whose bytes predate the run reported as stale
instead of produced while a rewritten one is accepted, shared options given
before or after the operation name, a mistyped project that is refused without
being created, a declared result that cannot be read before the run refused for
want of a baseline, a helper the script left running stopped and reported with
`ok` false, an unenumerable process tree treated the same way, a
KeyboardInterrupt during the run, during the prelaunch process enumeration and
during the receipts it prepares writing an interrupted receipt before it
continues, a script edited while it ran reported
as both hashes and not ok while a sibling resolved through `__file__` still
works, the owned tree stopped before any result is hashed, a declared result
symlinked into the run's own directory reported invalid, an executable replaced
between its identity and the launch refused with a receipt and no process, a
timeout with owned cleanup, a refused label collision that leaves
the first run's receipt untouched, a declared result inside the run's own
directory refused before launch, and every input check running before anything
starts. Every flag is exercised through `cli.main`. No Blender is involved.

`test_mesh_topology.py` covers the topology audit and `blender reduce`. The
audit arithmetic is exercised directly on hand-built triangle lists with no
Blender and no numpy: a closed consistently wound tetrahedron reporting nothing,
one open triangle reporting three boundary edges, an edge shared by three faces
reporting one nonmanifold edge, two faces traversing a shared edge the same way
reporting one inconsistently wound edge, two closed shells touching at a single
welded vertex reporting one nonmanifold vertex while every edge count stays
zero, a flat collinear solid reporting every face degenerate while every edge
count stays zero, a closed but coplanar tetrahedron reporting one zero-volume
component while every edge, winding and face count stays zero, and a
duplicated texture-seam vertex welded by position rather than counted as a
hole.

Every measurement has two implementations: a readable one used without numpy
and on small meshes, and an array-based one for meshes with millions of
triangles. They are checked against each other on a tetrahedron, an open
triangle, an edge shared by three faces, opposed winding, a bowtie, a flat
solid, a coplanar closed tetrahedron, a closed torus, an empty mesh and sixty
seeded random index soups; those comparisons skip when numpy is absent, so run
the suite once in a virtualenv with numpy to exercise the array path. A closed
torus and a genuine (non-coplanar) tetrahedron are audited on whichever path
is available and must report no defect at all, while the coplanar tetrahedron
-- closed, manifold and consistently wound but folded flat onto itself --
must report one `zero_volume_components` and therefore not be clean.

Measured once on this box (Linux, Python 3.12, numpy 2.5.3), auditing a
synthetic closed torus of 2,000,000 triangles and 1,000,000 vertices through
the array path: **5.4 s wall, 1.76 GB peak RSS**, reporting zero of all five
defects. The readable path was measured on the same shape at two sizes: 51,200
triangles in 0.6 s / 0.10 GB and 405,000 triangles in 6.2 s / 0.66 GB, which
extrapolates to roughly 31 s and 3.2 GB at 2,000,000 triangles. That is the
reason the array path exists, and the reason the readable one is kept only for
small meshes and hosts without numpy. When numpy is installed the
vectorized path is checked against the plain-Python one and otherwise skipped,
so the numpy path is unverified on a host without it. `reduce` is covered with
the same shim standing in for `blender.exe`: the launch line reaching the
packaged `reduce.py` after Blender's own `--`, a receipt holding both audits and
the source hash, `ok` refused when the *source* audit was dirty, when the
reduction introduced a defect including a vertex-only one, when a result is
still over the requested budget, when a selected object holds no triangles,
when nothing was saved and when the build could not measure topology at all, a
source edited or deleted mid-run refused with both digests and the receipt
still written, an existing `--output`, an out-of-range `--target-triangles` and
an unconfigured Blender refused before launch with no directory left behind, a
repeated label refused with the earlier receipt intact, and no argv value
reaching any receipt, the selected object's name included.

The destination is claimed with one `O_CREAT|O_EXCL` open before Blender
starts, so two reductions with different labels cannot both write one output:
the second is refused, the first's receipt hashes the bytes that are actually
there, and the claim is released when nothing was saved. An interrupt during
the run still writes `reduce.json` with `status: interrupted` and `ok: false`
before the `KeyboardInterrupt` continues. The Blender executable is hashed
before launch, re-read immediately before process creation (a mismatch is
`status: refused` with no process started) and again after exit (a mismatch is
`ok: false` carrying both digests). Each shared
option is exercised before and after the operation name with the operation's
value winning, what the command needs is named by dispatch rather than by
argparse, and a mistyped `--project` is refused without being created. Every
flag runs through `cli.main`. No Blender and no mesh are involved.

`test_credential_files.py` covers the optional `credential_files` host
declaration: the environment still winning over a declared file, a file
answering when the environment is unset, `export`/quote/comment/blank-line
parsing, a byte-order mark, a relative entry resolved against the host config's
directory rather than two different working directories, missing files skipped
and the first declared hit winning, a value that reaches neither `os.environ`
nor a task record, a key rotated between the request and its redaction leaving
the sent key out of the record, and a malformed declaration refused when the
host config loads.

`test_meshy_balance.py` covers the read-only `meshy balance` command with the
provider transport replaced: the number and nothing else about the account
printed, a non-finite balance refused rather than serialized, a declared credential file used with no file written anywhere, every
failure returned as an error *type* rather than a provider message, a missing
credential refused before any request, and the operations that write still
requiring their project and record. No network call is made.

`test_meshy_image_profile.py` covers the image-to-3d profile's game-ready
fields: a request carrying `should_remesh`, `target_polycount`, `topology` and
`symmetry_mode` reaching the provider payload unchanged through `meshy submit`,
each of them refused at the bounds the other profiles already used, no polycount
invented by the helper, and an out-of-range request refused before any transport
is constructed.

```text
python -m unittest discover -s tests -p test_blender_run.py -v
python -m unittest discover -s tests -p test_mesh_topology.py -v
# and once where numpy is importable, to run the array-path comparisons
python -m unittest discover -s tests -p test_credential_files.py -v
python -m unittest discover -s tests -p test_meshy_balance.py -v
python -m unittest discover -s tests -p test_meshy_image_profile.py -v
```

## Interactive playtest

`playtest` and `launch --mode native` start the same engine with the same
native flags and check the same engine identity, and they are not
interchangeable. `launch` runs a project-owned script for a bounded, timed
window and returns one verdict an agent reads; the run is over when the command
returns, and a missing declared result makes it not ok. `playtest` runs a
session a person drives and judges: it has session modes instead of one
blocking wait, it may run uncapped while a human plays, it can keep the real
user profile so saves and settings survive, and it leaves a `relaunch` script
the player can run again later without this kit, without Python and without an
agent. Its `ok` means the engine ran cleanly, never that the game played well —
`acceptance` stays `not_established` in every mode. Choose the session mode and
the input route with
[studio-playtest](../skills/studio-playtest/SKILL.md).

`test_playtest.py` covers it with small Python child processes standing in for
the engine: a blocking `handoff` session writing both receipts with no argv
value or environment value in any of them while the combined log holds both,
`acceptance` staying `not_established` even when `ok` is true, an `attended`
session returning with no exit receipt and being completed by exactly one
`collect` with the second refused, the uncapped `--max-minutes 0` accepted
where a human is present and refused for `driven`, `--script` required for
`driven` and rejected for `handoff`, engine SHA-256 refusal before anything is
launched, the recorded profile for both isolated and host sessions, a label
collision refused, the emitted launcher carrying the engine path and scene but
no environment, and a declared result inside the playtest's own run directory
refused. A separate check reads the skill and template as files: that they name
the kit commands they describe, keep the two harness rules, and contain no
host-specific absolute path. No engine, provider or desktop is involved.

```text
python -m unittest discover -s tests -p test_playtest.py -v
```

## Cleanroom and host preflight tests

`test_cleanroom_host.py` covers the pure snapshot comparison (new, exited and
busy processes, agent-log timestamps inside the window, unavailable GPU as a
limit, a failed process enumeration refusing attribution), the mid-window
sampler against an injected enumerator and clock, including a recorder that
exists only between the two snapshots and the exclusion of the sampler's own
helper and of the owned capture tree, one owned capture between two snapshots
with an unrelated child left running, capture timeout ownership, the scope
rungs a scoped bench will and will not accept, this host's real snapshot
readers, the Windows Update readiness rules including the active-hours cases
that let a restart through, receipt paths refused inside the installed toolkit,
a receipt read back through a byte-order mark, the PowerShell apply command
line with `-WhatIf`, and static contracts of `Prepare-OvernightHost.ps1`
including the WhatIf-exempt, BOM-free receipt write. The script's behaviour on
a real Windows host is validated by hand; these tests are not native
evidence.

```text
python -m unittest discover -s tests -p test_cleanroom_host.py -v
```

## Receipt identity, startup phase, ready timing and kit provenance

These six files use temporary directories and small Python child processes; no
engine, provider, desktop or network is involved.

`test_capture_identity.py` covers the `current`/`historical`/`unknown` label a
capture, bench or cleanroom row gets when it is attached to a candidate verdict:
a receipt from this content labelled current, one from another content labelled
historical, a receipt carrying no digest labelled unknown rather than
historical, an archived capture labelling itself and its own `capture.json`, the
attached row keeping every hash it arrived with and the caller's dictionary left
unmutated, `evidence_total`/`evidence_current` recomputed on each attach and by
`refresh_rollups` over rows attached by hand, an unknown dimension refused, and
the shipped `templates/candidate.json` carrying the new keys at zero. It also
covers what `validate_candidate` now enforces: a pass backed by a current row
accepted, a pass whose only row is unlabelled, historical or unknown refused, a
stored `evidence_total`, `evidence_current` or `performance_class` that
disagrees with its own rows refused, an identity spelled anything other than
`current`, `historical` or `unknown` refused by the row's own path, a row with
no identity key reading as `unknown` and counting as not current without being
invalid, a legacy record storing no rollups still validating, acceptance refused when any mandatory dimension's row stops being
current, and a `not_applicable` dimension still needing only a reason.

`test_startup_failure.py` covers the log classifier's `phase` and `first_error`
and the verdict built on them: each load-time signature reported as `load`, a
script error naming a running callback reported as `runtime`, a load-worded
error raised from any project frame (`_process`, `_on_button_pressed`,
`_unhandled_input`, an ordinary method name) reported as runtime, a parse error
whose only frames are engine sources (`gdscript.cpp`, `resource_loader.cpp`,
`script_language.h`) or which has no frame at all reported as load, a frame in
neither form not counted, only the first error deciding the phase in either
order, no error meaning no phase, and the two shared log fixtures asserted to be
the two-line logs they claim to be. The rebuilt signature has its own tests:
each of the eighteen allowlisted phrases reporting its own words, a phrase
nobody listed reported as `unrecognized`, the first `res://` resource and its
line number kept, an API token and an email address in the message body
surviving into neither, a `user://` save path leaving nothing behind, terminal
escapes never reaching it, the cap at 200 characters, and a host path, a URL, a
token and an address in a real launch reaching neither `diagnostics.json` nor
`exit.json` while staying in `stdout.log`. Also the original
`status`/`error_count`/`warning_count` unchanged, a non-zero exit with a load
phase becoming `startup_failure` in both `launch` and `playtest`, a runtime
fault staying `failed`, a load phase with exit zero staying `engine_errors`, and
a timeout staying `timed_out` however the log reads.

`test_ready_marker.py` uses a `python -c` child that prints the marker after a
short sleep. It covers `ready_seconds` measured from process creation and
written to `process.json`, a child that never prints it recording null, a marker
printed just before exit still seen, a marker on an unterminated line counted,
a run without a marker never reading the log while it waits, the read paced at
no more than four times a second, a watched run still timing out with owned
cleanup, a run that came up and then hung keeping its load time in the
timed-out receipt, a marker written between the final poll and the deadline
still read, the wait's deadline taken when the wait begins so a marker never
shortens the granted window, `ready_seconds` measured from the spawn instant
rather than from the start of the command (both against a hand-advanced clock
and a scripted child), a marker with no log file, a marker that is not a
nonempty string and a marker spanning a line break all refused by both the
runner and the project declaration, the project's declared marker reaching the runner and `exit.json`
for both `launch` and a driven `playtest`, a malformed declaration refused
before a run label is reserved, the limit sentence present in both receipts, and
no argv value or environment value in any receipt of a watched run.

`test_performance_class.py` covers `clean_qualification` for an attributable
window around a completed capture, `diagnostic` for a contended window and for a
capture that timed out, `diagnostic` on a native launch that declared a result,
no class at all on a launch that declared none or ran headless, and the verdict
rollup: unverified on a fresh candidate, a bench class copied onto the row,
a human review alone rolling up to `subjective_acceptance`, differing classes
and a lone diagnostic rolling up to `mixed`, and a qualification taken from
other content counted in `evidence_total` but not in `evidence_current` and not
qualifying anything. It also covers the validation rule built on the rollup:
only `clean_qualification` carrying a performance pass, with a diagnostic, a
human review alone and a mixture each refused.

`test_kit_identity.py` covers `kit_identity()` naming this version and digesting
this source tree, being computed once and handed out as a copy, changing when a
`.py` file under the package changes and not when a neighbouring `.md` does, the
block appearing in both launch receipts, a new candidate and the doctor report,
and carrying no host path. It also covers `evidence verify`: unchanged results
reported `current` with `ok` true, changed bytes `changed`, a deleted result
`missing`, a receipt that recorded nothing not ok, a declared result the run
never produced listed as `unrecorded`, malformed `result_files` elements listed
by index and forcing `ok` false while the well-formed row beside them is still
checked and a non-string path is never echoed back, a null digest counted as
unrecorded rather than malformed, the project derived from the run directory or
given explicitly, a receipt with no `result_files` refused, and the same verdict
and exit code through `cli.main`.

`test_doctor_credentials.py` covers `credential_source` returning `environment`,
`file` or `none` in the same order `credential` resolves in, an empty value not
counting as a source, the declared-file report's `present`/`readable`/key names
including an unreadable file, each declared file identified only by its basename
and zero-based position with no directory anywhere in the report, a
Windows-spelled or UNC entry still reduced to a bare name, and the doctor report
itself: a file-backed host
reported `unverified` rather than `needs_setup` for both the providers and the
video-analysis credential, an unconfigured host still `needs_setup`, the setup
plan reading the same statuses, and no key value anywhere in the report.

```text
python -m unittest discover -s tests -p test_capture_identity.py -v
python -m unittest discover -s tests -p test_startup_failure.py -v
python -m unittest discover -s tests -p test_ready_marker.py -v
python -m unittest discover -s tests -p test_performance_class.py -v
python -m unittest discover -s tests -p test_kit_identity.py -v
python -m unittest discover -s tests -p test_doctor_credentials.py -v
```
