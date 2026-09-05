---
name: studio-review
description: Review a concrete game candidate using ordinary player input and native visual, motion, audio and performance evidence, keeping technical checks and human acceptance distinct.
---

# Studio review

Inputs: declared game root, candidate/content/workflow identity, work card, reference files and expected ordinary route. Read [acceptance](../../references/acceptance.md). Output an evidence pack, defects with reproduction steps and separate verdicts plus the human decision needed.

First validate the actual candidate record with `validate-record`. Check that captures belong to the same content digest and engine/settings, not another branch, render or stale build. Technical logs can establish import and assertion results; only the appropriate inspected evidence supports a perceptual claim.

Determine the active host's real tools. Python doctor cannot discover computer use. If the host offers a desktop tool, identify the owned app/window and perform a bounded inspection before claiming native access. Save existing work and respect one visible-desktop operator. Do not close user-open apps or substitute a remote/private desktop assumption.

Walk the documented route with ordinary controls. In the original example use WASD/arrows, click for mouse look, approach within 3 m and press E; Escape releases the mouse. Capture the normal 70-degree camera, 1.8 m scale marker, close object, at least two idle loops, stress/response transition and return. Repeat input and walk away to inspect reset/feedback.

Capture the audible runtime route and listen through actual available playback. Check attenuation, cue timing, clipping, overlap and loop seams. Record who listened and how. If you cannot hear or inspect audio, mark listening not_run; do not infer it from a waveform or `playing` flag.

Measure performance under declared resolution, renderer and hardware with real frame timing; avoid claiming a fixed headless physics tick is GPU performance. Keep defects actionable with expected/observed behavior and evidence hashes. A bounded correction within the card can proceed under existing authorization; re-capture only affected evidence after content changes and create a new candidate identity.

If the native tool is missing, complete independent technical review and provide [the exact Windows smoke handoff](../../docs/windows-smoke.md). Leave target-native/ordinary-input/perceptual statuses pending. Acceptance requires explicit reviewer/rationale and passed relevant dimensions; a functional fixture does not prove production art achieved. Return candidate pointer, evidence paths, five verdicts, unresolved defects and the precise remaining decision.
