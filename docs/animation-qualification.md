# Selected animation qualification

`qualify-animation` prepares an isolated project from an existing selected
fieldbook attempt, runs bounded Godot checks and appends evidence to that same
attempt through the existing registration API. The fieldbook stays the sole
catalog. Selection, comments, model/game pins and readiness are preserved.

The command does not generate, select, retarget, accept or replace assets.
Human review and an explicitly authorized production decision remain separate.

## Prepare

```text
python <KIT>/scripts/studio.py qualify-animation prepare --project <NEW-ROOT> --plan <PLAN.json> --url http://127.0.0.1:8791
```

The destination must not exist and must be outside Kit. A plan contains:

- `id`, `attempt` and `baseline`: each identity names `model_id`, immutable
  `attempt_id`, whole-GLB `sha256` and `target`. Candidate must be selected now;
  baseline must match the model's current game content pin.
- `source_commit`: full committed game revision. `source_repository` and each
  source input's `git_path` let Kit verify its bytes against `git show` from that
  revision. Local adapter inputs have separate explicit content hashes and are
  never claimed to be a released Kit package.
- `engine`: exact installed executable SHA-256 and descriptive build version.
  Execution checks the executable hash before and after the owned run.
- `inputs`: `source` path, portable destination `path`, and `sha256`. Include
  `project.godot`, a project-owned adapter, unchanged controller dependencies,
  context assets and data. Kit copies verified bytes and fetches candidate and
  baseline GLBs from the existing fieldbook blob service.
- `script`: project-relative adapter path. The adapter implements the bounded
  scenario; it receives `--role=baseline|candidate` and `--output=...`.
- `settings`: exactly `{"resolution":[1920,1080],"renderer":"forward_plus",
  "physics_hz":60}` for the existing native launch profile. CPU mode remains
  headless and has no renderer/performance acceptance.
- `camera`, `replay`, `thresholds` and explicit `limits`: hashed within the
  immutable plan. Thresholds must be finite and nonnegative.

The Kite example is under `examples/animation-qualification/`. It expects
unchanged `kite_approach.gd`, `kite_reach.gd`, `kite_flight_cues.gd` and
`kite_perch_controller.gd` at `features/living_colony/`. Optional
`coupled_colony:true` adds actual `mite_actor.gd`, `colony_population.gd`,
`route_surface_fit.gd`, colony C routes and `context/{mite,colony,bank}.glb`.
The source controller drives flight; the candidate stays on its original
skeleton. No channels, root translation or root rotation are removed.

The example records parent motion, clip position and local bone poses as JSONL.
The coupled variant records Mite states, distance, visibility, movement speed
and playback rate, with source seed 41 and a bounded running-observer input.
The bank projection uses the actual source fitter and an explicitly flat
terrain query. It does not reproduce the planetary presentation frame bridge.

## Run and inspect

```text
python <KIT>/scripts/studio.py qualify-animation run --project <ROOT> --config <HOST.json> --url http://127.0.0.1:8791 --phase import --label kite-import-01 --cutoff-utc <UTC>
python <KIT>/scripts/studio.py qualify-animation run --project <ROOT> --config <HOST.json> --url http://127.0.0.1:8791 --phase cpu --label kite-cpu-01 --cutoff-utc <UTC>
python <KIT>/scripts/studio.py qualify-animation run --project <ROOT> --config <HOST.json> --url http://127.0.0.1:8791 --phase native --label kite-native-01 --cutoff-utc <UTC> --reservation <WINDOW.json>
```

Import is separate from playback. Baseline and candidate playback run
sequentially through Kit's existing owned process runner with separate labels,
isolated user profiles, 60-second caps and an absolute deadline. Review and game
pins are fetched again before running. Each changed input or stale decision is a
refusal, never an automatic reconciliation or review write.

Native admission requires a parent-coordinated reservation containing
`plan_digest`, `coordinator`, `start_utc`, `end_utc`, `host_preflight`,
`host_preflight_sha256` and `competing_heavy_jobs_verified:true`. A passing
preflight, a readable process snapshot and no competing Godot/Blender/FFmpeg
process are required. Unknown processes are left untouched. The coordinator
must check other heavy jobs; this is a reservation receipt, not an OS resource
lock. Do not launch another GPU job during the reserved window.

An explicitly authorized bounded native diagnostic may retain a failed host
readiness preflight without changing host settings. Its reservation must add
`bounded_diagnostic_authorization` with the coordinating `instruction` and
`source_thread_id`. Process/heavy-job checks, hashes and deadlines still apply.
Such a run captures actual native evidence but keeps performance qualification
unverified, even when numerical budgets pass. This exception never grants
unattended operation or production acceptance.

Each native role uses its own existing `bench cleanroom` attribution window.
Only both attributable completed windows can apply performance budgets:
`frame_p95_ms`, `gpu_p95_ms`, `controller_cpu_p95_ms`, and
`max_relative_frame_cost`. At least 120 finite samples are required for each
metric and GPU timings must be nonzero. Missing or contaminated measurements
remain unverified. Frame timing includes fixture instrumentation; controller
CPU timing covers the adapter's update, and viewport GPU timing is Godot's
reported viewport cost, not whole-process GPU utilization. This bounded
fixture cannot establish full-game frame cost. Warmup and capture overhead
must be considered when setting a production comparison plan.

Receipts retain plan/input/build identities, imported scene/settings hashes,
owned launch/cleanup records, replay and capture hashes, observations,
automated verdict, human review and performance qualification separately.
Native captures are PNGs; JSONL is the deterministic replay/recording. There
is no claim of an encoded audiovisual recording or listening review.

The example tests exact current rig identity, unit import scale, loop endpoint
pose distance, finite controller movement, phase coverage, disturbance and
speed. Loop endpoints do not establish velocity continuity. The current
colony controller plays glide with additive wing/reach overlays; it does not
switch authored glide/flap clips. Generated flap plus this overlay can double
the flap. The example reports missing transition and authored banking
coverage rather than presenting them as passed. A reviewed transition/rig
adapter and native visual evidence are required before broader qualification.

## Append evidence

```text
python <KIT>/scripts/studio.py qualify-animation attach --project <ROOT> --url http://127.0.0.1:8791 --receipt artifacts/qualification/kite-cpu-01.json --actor game-studio-kit:qualification
```

Failed diagnostic receipts are useful evidence and may be attached. The
command validates immutable attempt/plan/file identities, uses the existing
verified blob, re-registers unchanged metadata with stable structured
provenance, and verifies the returned attempt ID and preserved decisions,
comments and game pins. It never calls review, amendments or notes endpoints.
The API stores receipt references/hashes; it does not execute or validate
native receipt semantics. No new viewer endpoint is needed for this milestone.
Media serving for remote review remains a coordinated future extension:
provenance can reference local evidence now but does not upload PNG/JSONL bytes
to the viewer. Do not add a second catalog or edit the viewer concurrently.

Preserve previous output roots and labels. After any content correction, use a
new plan hash and root; old receipts remain valid only for their original
tested bytes. Readiness and final acceptance remain pending regardless of
automated or performance passes.
