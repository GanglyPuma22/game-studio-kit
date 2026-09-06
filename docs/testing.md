# Validation

From the complete repository root:

```text
python -m unittest discover -s tests -v
python -m studio_tools check-package --root .
```

The standard-library tests use temporary directories and mocked provider boundaries. They cover package relocation and reference closure, invalid config/missing tools, process timeout ownership, candidate content/capture mismatches, missing exports/clip metadata, nonhumanoid rig rejection, interrupted/ambiguous Meshy lifecycle, partial downloads, local PCM/trim/loop behavior, hosted audio error redaction, terrain dimensions/seams, Gaea capability/recipe checks and app command construction. They do not call a provider or control the visible desktop.

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
