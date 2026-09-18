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
descendant test needs POSIX `/proc` and skips elsewhere; the Windows parent walk
is unexercised. No engine, provider or desktop is involved.

```text
python -m unittest discover -s tests -p test_launch_evidence.py -v
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
KeyboardInterrupt during the run and during the receipts it prepares writing an
interrupted receipt before it continues, a script edited while it ran reported
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
reporting one inconsistently wound edge, and a duplicated texture-seam vertex
welded by position rather than counted as a hole. When numpy is installed the
vectorized path is checked against the plain-Python one and otherwise skipped,
so the numpy path is unverified on a host without it. `reduce` is covered with
the same shim standing in for `blender.exe`: the launch line reaching the
packaged `reduce.py` after Blender's own `--`, a receipt holding both audits and
the source hash, `ok` refused when the *source* audit was dirty, when the
reduction introduced a defect, when nothing was saved and when the build could
not measure topology at all, an existing `--output` and an out-of-range
`--target-triangles` refused before launch, a repeated label refused with the
earlier receipt intact, and no argv value reaching any receipt. Each shared
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
