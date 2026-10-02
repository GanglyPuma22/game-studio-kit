# Registered source-context baselines

Use this path when the current game has a registered asset but no selected
animation target. It does not replace `qualify-animation`, select a take or call
the fieldbook registration API. An actual candidate still needs the user's
selection and a matched source-slot game pin before same-attempt publication.

Prepare an isolated game project from a named game commit. Copy the exact
hydrated assets locally and verify their hashes; never run from an active game
checkout or download missing LFS files. Use `studio launch --mode import`, then
run each project-owned source fixture with `studio launch --mode test|native` and
a distinct `--label`, `--scope`, bounded `--timeout`, `--cutoff-utc` and
`--result`. The native process must have a parent-coordinated window and a
fresh competing-job check. Run one instance at a time. This verifier requires
a ready native host. Failed-preflight diagnostic evidence remains unverified;
an authorization schema for that exception is not implemented.

After the runs, record a JSON manifest with `schema_version:1`,
`kind:"source-context-baseline"`, `source_commit`, `source_repository`, the
hashed read-only `catalog_snapshot`, the installed `engine.path` and SHA-256,
`producer_kit`, `retained_evidence:{path,sha256}`, `slots`, and `runs`.
`producer_kit` is copied from the original Kit launch receipts; the verifier
records its own, potentially newer `kit_identity()` separately. The retained
evidence is a prior local, hash-pinned baseline receipt from the original runs.
Its original manifest digest must match the current plan after removing only
these retrospective pins. It anchors each run's exit receipt, report, committed
fixture hash and every PNG hash for retrospective integrity. Do not use the
receipt being generated as its own retained evidence. Each run also pins its
original `owned_launch_sha256` and `process_sha256` from the Kit receipts. New capture
work needs its own retained evidence pin before this retrospective command can
verify it. Each slot names a distinct role, `model_id`, registered
`attempt_id`, whole-GLB SHA-256 and project-relative asset. A runtime slot
also names its copied GDScript `source`, committed `git_path`, and the exact
`path_constant` and `sha_constant` that bind that slot. A comparison asset can
set `runtime_slot:false`; it cannot claim to be a game source slot.
Set `catalog_current:true` only when both its SHA and path must equal the
fieldbook model's current-game pin. Every slot records the catalog relationship
separately, so a matching SHA at a different path is visible rather than
silently treated as the same runtime role.

Slots and runs must both be nonempty. Run names and execution labels must each
be distinct; separate names cannot reuse a single launch.
Each run uses mode `test` or `native` and at least one functional assertion.
Each run names its Kit launch `label`, `scope`, `mode`, `script`, project-relative
JSON `report`, explicit `captures`, and checks. Checks support dotted-path
`equal`, finite numeric `minimum`/`maximum`, and array-of-record `coverage`
with a field and required values. Equality preserves exact JSON types recursively;
Boolean values do not equal integers. When captures are claimed, `capture_report`
must name a report field holding the full planned capture manifest with successful
integer `save_error:0` records. The verifier requires paired owned
launch, exit and process identities, completed process/descendant cleanup,
finish before both launch cutoff and native reservation window end, the exact
engine hash before and after,
the exact project and committed fixture script, an unchanged result file,
complete source/fieldbook attempt hashes, committed
asset bytes or LFS OID, and decoded 1920×1080 PNGs with valid CRCs and retained
per-file hashes. It writes a new local receipt and refuses an existing
destination:

Every run binds `project.godot` and its script to the source commit. Use the
project-relative `fixture_inputs` list for additional scripts, scenes, data or
assets read by that fixture. The retained run must already contain matching
`fixture_inputs` file and committed-blob hashes; historical receipts without
that proof cannot establish the configuration used by a prior run. Text inputs
permit CRLF normalization; binary inputs require exact bytes or a complete
matching LFS pointer.

Process proof follows the hash-verified engine executable format: PE requires
Windows FILETIME ownership; ELF and Mach-O use the retained paired process PID,
timestamps and completed process-group cleanup. POSIX cleanup receipts need no
Windows-only `unstopped_pids` field. Unknown executable formats fail closed.
The verifier's current operating system and a missing Windows ownership object
never select the proof route. These receipt checks do not demonstrate native
behavior on an untested platform.

For a native run, include `reservation:{"path":"<READ-ONLY-RECORD>",
"sha256":"<HASH>"}` in that run's manifest entry. The record must contain
`checked_utc`, `window_end_utc`, `process_status:"ok"`,
`competing_godot_blender_ffmpeg:[]`, and
`competing_heavy_jobs_verified:true`, and `host_ready:true`. The verifier requires the snapshot within
five minutes before that exact owned launch, and the Kit exit receipt must
finish by the reservation end. This proves a recorded check, not
an OS-level lock or performance attribution.

```text
python <KIT>/scripts/studio.py baseline-context verify --project <ISOLATED-GAME> --manifest <PINNED-MANIFEST.json> --receipt artifacts/run/<RUN>/baseline-evidence.json
```

The receipt explicitly says `selected_animation_qualification:not_attempted`,
`fieldbook_mutation:false`, `performance_qualification:unverified` and
`acceptance:pending`. Baseline source behavior, contact, state coverage and
rendered diagnostic captures may pass independently of those decisions.
Neither the command nor the receipt uploads captures, adds a viewer endpoint,
or changes comments, picks, game pins or readiness. Keep source-slot variants
separate: a catalog pin may describe a different asset from the actual Pocket
or habitat controller input.
