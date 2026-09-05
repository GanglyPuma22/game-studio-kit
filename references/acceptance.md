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
