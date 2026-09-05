# What the evidence actually establishes

Keep visual, interaction, motion, audio and performance verdicts separate. Use `not_run` for work not done and `unverified` for insufficient evidence. A compile, provider status, screenshot or thumbnail cannot imply all five passed.

- **Visual:** inspect normal camera/FOV at player scale and close views under runtime lighting, comparing exact approved reference IDs. Rendered Blender PNGs establish source appearance only. Method: `native_visual` or `native_capture_review` with named observer.
- **Interaction:** use the documented ordinary route (walk, approach, press E); record input, visible contact, response and reset. Method: `ordinary_input` or `native_capture_review`. Script-injected input in `godot smoke` establishes wiring, not normal-input usability.
- **Motion:** observe at least two loops, the loop seam, rest/stress pose and idle→response→idle transition. Check foot/root stability, deformation and silhouette in the actual runtime. Bone-count/pose-change assertions establish import and execution only.
- **Audio:** listen to the captured game mix on a known route; check event timing, attenuation, clipping, overlaps and loop seam. Method: `listening` or `native_capture_review`; name the playback/listening route. `AudioStreamPlayer.playing` establishes that playback was requested, not that anyone heard it. Voice identity/suitability is a separate creative decision.
- **Performance:** measure the candidate at declared resolution/renderer/hardware and input route. Frame-time capture and its method belong in evidence. Method: `profiler_measurement` or `native_capture_review`. A headless fixed physics step is not a GPU benchmark.

An evidence entry adds `content_digest`, `method`, `observer` to a hashed artifact entry. For example, a narrated/captured review note can link the video/audio file hashes it actually examined. Keep raw captures as well as the verdict. Do not label a still as an audio capture.

Acceptance requires all relevant verdicts passed, reasons for inapplicable dimensions, no unresolved defects, and an explicit reviewer/rationale. `validate-record` refuses missing or mismatched evidence and changed content; it cannot authenticate invented captures or replace judgment.

If the native route is unavailable, finish independent generation/import and provide [the native smoke procedure](../docs/windows-smoke.md), exact candidate identity, commands, expected observations and remaining questions. The package can be implementation-complete while target-host verification and production pilot acceptance remain pending.


Evidence portability: candidate schema stays at 1. New candidates add `inventory_version: 2` and exact relative POSIX paths sorted by Unicode code-point order, with case-colliding files/directories rejected. Missing inventory_version means legacy version 1: preserve the original ordered list and digest, then compare sorted path/hash content against disk. Never rewrite historical digests to match the current host. Every evidence file and recursively attached file is hash-checked at every verdict status, including unverified/not_run.

For an audio pass, evidence must include `listening: {"performed": true, "playback_route": "actual device/player route", "interval_seconds": [0, 12]}` and a nonempty observer; use the actual reviewed interval. Old audio passes without those facts cannot be promoted by migration: keep historical bytes and add a new review record. A declared method alone is insufficient.

Archive captures with `studio_tools.evidence.archive_capture(project, source, candidate, label)` or an equivalently unique immutable host capture path. Each archive gets a UUID capture_id/path bound to candidate/content; never overwrite a previous capture. Capture metadata should record camera/FOV, renderer, internal render size, actual window/display size and captured pixel dimensions separately. Measure wall duration using a monotonic host clock rather than summing engine delta. Report moving/stationary time and ordinary-input coverage; physical keyboard and captured-mouse operation are separate from injected smoke inputs. These metadata declarations still need actual native observation.

For bounded environments, exercise every reachable edge through ordinary movement and observe collision, escape, reset/respawn and recovery outcomes. A timed capture alone does not establish boundary coverage. Include continuous movement and camera pitch limits, record stationary intervals, and separate each observation from injected tests or artistic/listening acceptance.
