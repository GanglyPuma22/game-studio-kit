# Testing and performance for Godot 4.x GDScript

Read alongside [studio-godot](../SKILL.md). This file covers headless test runners, frame-
stamped probes, `RenderingServer` counters, profiler workflow and performance budgets for a
large 3D project. It does not replace the kit's own owned-process launch model — every
invocation described here still goes through `studio.py godot smoke`/`godot run`, or a
project-owned script launched with [`launch`](../../../references/execution-evidence.md),
never a raw `godot --headless` shell-out that bypasses the kit's host-timeout and receipt
discipline described in [execution.md](execution.md).

## Choosing a test approach

Two third-party GDScript test frameworks exist in the wider ecosystem — GUT (GDScript-first,
mature, limited C# support) and GdUnit4 (GDScript and C#, more IDE integration). Neither is
assumed by this kit. Before adopting either, check what the project's own tests already use:
a project with an existing `tests/test_runner.gd` and a body of probe-style tests already has
a working, in-house convention, and bolting on a second framework alongside it produces two
non-interoperable test runners in the same repo — pick one, don't accumulate both. If starting
from nothing, a lightweight project-owned runner (a `test_runner.gd` that discovers test
scripts, runs their functions, and reports pass/fail as structured JSON) is often a better fit
for the kit's evidence model than a full framework, because it can be shaped to speak the
[studio-smoke-v1 protocol](execution.md) directly instead of translating a framework's own
report format into one. Note the wiring: `godot smoke` launches the project's main scene and
never passes `--script`, so a standalone runner only executes if the main scene delegates to
it (or it is the main scene). A runner that is not wired that way is run instead with
`python <KIT>/scripts/studio.py launch --project <GAME> --mode test --script res://tests/test_runner.gd ...`
and its own result files declared with `--result`. A script passed through `--script` must
extend `SceneTree` or `MainLoop`; an ordinary `Node` runner needs a small `SceneTree`
bootstrap that instantiates it, or Godot exits before any test runs.

## Decision tree: unit, scene, snapshot

- **Unit test** — pure logic with no node tree dependency (math, data transforms, state-
  machine transition tables). Fastest, run in bulk, no engine window needed.
- **Scene test** — behavior that depends on the node tree being live (a `CharacterBody3D`
  actually moving under `move_and_slide()`, a signal actually firing between two instantiated
  nodes). Requires a headless engine instance with the scene loaded; keep these scoped to one
  subsystem's own scene so a terrain test does not need the player, inventory and dialogue
  systems all loaded to pass (see the subsystem-boundary note in
  [architecture.md](architecture.md)).
- **Probe / frame-stamped assertion** — for behavior that only manifests over multiple frames
  or physics ticks (animation blending, a projectile's flight path, terrain streaming as the
  player moves), assert against a recorded sequence of frame-stamped samples rather than a
  single end-state check. Stamp every sample with `Time.get_ticks_usec()` (not
  `OS.get_ticks_msec()`, which is lower resolution) and the current physics/process frame
  count, so a failure report can show exactly which tick diverged rather than just "final state
  wrong."
- **What not to test headlessly.** Pixel-level rendering correctness, audible mix quality, and
  "does this feel good" judgments are not headless-test material — a headless pass never
  establishes appearance, audible output or ordinary controls, the same rule
  [studio-godot](../SKILL.md) already states for smoke checks. Route those to native review
  instead of trying to assert them in a headless probe.

## Headless test runners

Run every headless test through the kit's owned process model, not a bare shell command:

- For a project that has declared the `studio-smoke-v1` capability in its `project.json`, use
  `python <KIT>/scripts/studio.py godot smoke --project <GAME> --config <HOST> --output <GAME>/artifacts/smoke-<stamp>.json`
  with an absolute, project-rooted, fresh output path every time (the adapter takes the
  output as given, not relative to the project, so a bare relative path lands in the caller's
  working directory) (the default `artifacts/runtime-smoke.json` is refused
  once it exists, so a repeated recipe fails before Godot starts) (see
  [execution.md](execution.md)) — it launches the main scene headlessly with
  `--studio-smoke=<path>`, and requires the project's own script to write a report with
  `ok: true` only when every claimed assertion actually passed.
- For a project-owned script that must run once and return one verdict outside the smoke
  protocol — a probe suite, a `test`/`check` mode script — use
  [`launch`](../../../references/execution-evidence.md) with the engine's expected SHA-256,
  `--result` for every file the script must produce, and an explicit `--cutoff-utc`. This is the same
  blocking, non-polling launch used for native captures and unattended production stages; it
  is the correct home for a test-runner invocation too, not a separate ad hoc subprocess call.
- Never invoke `godot --headless -s addons/<framework>/bin/<tool>.gd` directly from outside
  these two paths. A raw invocation has no host timeout, no engine-identity verification, no
  descendant-process cleanup check, and its output never gets classified through
  `studio_tools.adapters.godot.classify_log` — meaning a WARNING-laden "pass" would slip
  through uninspected. Warnings and Orphan `StringName` counts are reported, not silently
  clean, per [execution-evidence.md](../../../references/execution-evidence.md); a shorter,
  cleaner comparison run does not clear a longer run's shutdown leak.

## `_physics_process` discipline under test

Tests that assert on physics behavior must run on the physics tick, not the render frame —
assert from a scene test hooked to `_physics_process` (or a fixed number of
`await get_tree().physics_frame` waits) rather than `_process`, or the assertion becomes
framerate-dependent and flaky across machines. When timing a physics-dependent sequence,
measure with `Time.get_ticks_usec()` against a known `physics_ticks_per_second`, and report
both the wall-clock and tick-count timing so a failure caused by an actual tick-rate change
(vs. a genuine regression) is distinguishable.

## `RenderingServer` counters and profiler workflow

For performance work, prefer `RenderingServer` (Godot 4's renderer-facing API; it replaced
the Godot 3-era `VisualServer`) over ad hoc frame-time guessing:

- `RenderingServer.get_rendering_info(RENDERING_INFO_*)` exposes draw calls, primitives, and
  memory counters to compare against a budget; sample them only in a native rendering run,
  since the smoke and `launch --mode test` paths start Godot with `--headless`, where no frame
  is rendered and draw-call/primitive counters are zero or unrepresentative (headless runs
  remain right for non-rendering probes), the same way a material or geometry claim needs a measured number rather than an
  assumption.
- Use the editor profiler (Debugger → Profiler and Monitors) for a first pass on the
  frame-time breakdown by category (physics, rendering, script, idle) before micro-profiling a
  specific function. A native probe cannot reproduce that breakdown: `Performance.get_monitor()`
  exposes whole-frame process and physics-process times only, and rendering time comes from
  `RenderingServer.viewport_get_measured_render_time_cpu/gpu` after
  `viewport_set_measure_render_time`; anything finer needs explicit `Time.get_ticks_usec()`
  instrumentation around the code in question; a native profiler run is
  native-review evidence and headless timing is smoke-level evidence — do not present one as
  the other.
- `Time.get_ticks_usec()` is the right primitive for both: microsecond resolution, monotonic,
  safe to call every frame. Do not use `OS.get_ticks_msec()` for anything performance-budget
  related; its millisecond resolution hides sub-frame variance that matters for a 33 ms-class
  budget.

## Performance budgets

State a budget as a percentile, not an average — a mean frame time hides the spikes players
actually notice. A common target for a 30 fps-class experience is a **p95** frame time of at
most 1000/30 = 33.334 ms (state the threshold with that rounding, or an explicit tolerance,
so a perfectly paced 30 fps run is not rejected by 33.333… > 33.3), not a p50: capture a distribution of frame times over a representative play/probe
session (not just the first few warm-up frames), sort it, and report the 95th-percentile
value alongside the sample count and session length used to produce it. State the budget
per-subsystem where practical (terrain streaming, physics step, rendering) so a regression can
be attributed rather than only detected at the whole-frame level. A budget number without the
sample count, session length and percentile method behind it is a claim, not evidence — the
same rule the kit already applies to geometry and material claims.

## Evidence rules

Every testing/performance claim in a candidate's evidence follows the same discipline as
everything else in this kit:

- A test "pass" is the process record showing zero exit **and** the classified log showing no
  ERROR/SCRIPT ERROR **and** the project's own report stating `ok: true` — any one of those
  missing means the run is not evidence of a pass. See
  [execution-evidence.md](../../../references/execution-evidence.md) for the full log/process
  discipline.
- A performance number is evidence only with its measurement method attached: which build
  (single/double precision — see [physics-and-precision.md](physics-and-precision.md)), which
  scene/scenario, sample count, and percentile, plus the target environment: CPU and GPU,
  rendering method, resolution, graphics settings and VSync/frame limiting. The kit's
  `launch --mode native` fixes `forward_plus` at 1920x1080, which may differ from the
  project's shipping configuration, so a result is budget evidence only against the
  configuration it names. A single stopwatch run is not a budget certification.
- Headless results — smoke, probes, unit/scene tests — never establish appearance, audible
  mix, or ordinary-input feel; those still require the native review step in
  [studio-godot](../SKILL.md) and [studio-review](../../studio-review/SKILL.md). Keep the two
  kinds of evidence labeled separately rather than citing a headless pass as if it covered
  both.

## Sources

Written for this kit after the 2026-09-11 audit of two community skill sets; the guidance is
restated in the kit's own words and no text or GDScript is copied from either:

- GodotPrompter, https://github.com/jame581/GodotPrompter (Superpowers-style skills; the
  `physics-system` and `scene-organization` skills were the research inputs).
- gd-agentic-skills, https://github.com/thedivergentai/gd-agentic-skills, LGPL-3.0 (the
  `godot-physics-3d`, `godot-3d-world-building`, `godot-genre-open-world`,
  `godot-performance-optimization` and `godot-debugging-profiling` skills were the research
  inputs). Under its licence, only the ideas are reused here, never its files.
