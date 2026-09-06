# Operational review loop

Resolve `KIT` from the invoked skill location and invoke its absolute
`scripts/studio.py` path. Use an explicit project root outside KIT. Keep the
work card, candidate, connected ordinary route, expected outcomes, timing floor,
affected criteria and bounded attempts together. Preserve failures before another
integrated expansion. A polished specimen does not establish a coherent world.

## Runnable offline examples

```sh
python "$KIT/examples/review-loop/create.py" --output /explicit/new/recording-example
python "$KIT/examples/review-loop/qualification.py" --output /explicit/new/qualification-example
```

The first generates original geometry/audio, records and decodes files, retains
actual PTS, computes a known synthetic timing failure, then rechecks PERF on a
clean file. Other criteria remain pending. Its cards/profiles/timing-context
files are usable examples. The second executes the entire qualification and
named review contract with deliberately simulated responses and observations.
It closes test TEMP/SOUND/WORLD criteria while production acceptance stays
pending. Neither example contacts a provider, listens, launches a game, or uses
a desktop. Its `performed: true` listening fields are explicitly **test scope**,
not claims that someone heard the clips.

## CLI flow

```sh
python "$KIT/scripts/studio.py" review validate-card --project "$GAME" --card artifacts/card.json
python "$KIT/scripts/studio.py" review prepare --project "$GAME" --card artifacts/card.json --role before
python "$KIT/scripts/studio.py" review capture --project "$GAME" --run artifacts/reviews/RUN --profile artifacts/recorder.json
python "$KIT/scripts/studio.py" review dense --project "$GAME" --run artifacts/reviews/RUN --interval 0.7 1.3
python "$KIT/scripts/studio.py" review analyze --project "$GAME" --run artifacts/reviews/RUN --budget artifacts/video-budget.json --dense artifacts/reviews/RUN/dense-0/frames.json
python "$KIT/scripts/studio.py" review qualify --config /explicit/host.json --project "$GAME" --review artifacts/evaluation.json
python "$KIT/scripts/studio.py" review ingest --config /explicit/host.json --project "$GAME" --run artifacts/reviews/RUN --review artifacts/named-review.json
python "$KIT/scripts/studio.py" review assess --config /explicit/host.json --project "$GAME" --run artifacts/reviews/RUN --evidence artifacts/observations.json
python "$KIT/scripts/studio.py" review prepare --config /explicit/host.json --project "$GAME" --card artifacts/after-card.json --candidate artifacts/after-candidate.json --role after --previous artifacts/reviews/BEFORE --affected PERF
python "$KIT/scripts/studio.py" review compare --config /explicit/host.json --project "$GAME" --before artifacts/reviews/BEFORE --after artifacts/reviews/AFTER
```

`analyze` requires an applicable exact-media/model/money authorization before use.
Host configuration can also be selected with `STUDIO_CONFIG`. Work cards require
compatible kind/dimension pairs: temporal/motion, performance/performance,
interaction/interaction, audio/audio, visual/visual. Interactions require an
expected state and existing action IDs. Temporal criteria declare separate
`minimum_event_seconds`, `max_gap_seconds` and optional `dense_interval` inside
the criterion interval. Sparse full-video sampling plus dense submitted frames
must be independently evaluated; requested FPS is not observed model sampling.

Run directories are immutable. `validate-run` checks current candidate files;
historical comparisons use preserved identities. Assessment validation recomputes
decisions from retained inputs, including adopted reviews and raw telemetry.
Editing status, completion, intervals or an adjacent hash cannot confer a pass.
A recheck must reference the exact selected before record, retain original
criteria/actions, and name affected IDs. Sibling and concurrent attempts consume
a single lineage budget; failed/incomplete attempts still consume it. A busy or
interrupted reservation requires inspection, not deleting the ledger. Unaffected
criteria remain not_run for the new candidate; historical passes are not copied.
Comparisons report per-criterion changes. They require known applicable settings,
nominal cadence/time base and codec/encoder profile. Recorded drops are outcomes;
they need not equal a repaired clip's realized PTS.

## Capture and timing

Installed FFmpeg and FFprobe are prerequisites, not verified native capability.
`file` accepts an explicit local source and preserves it while producing a new
MP4. Each required stream must cover the interval from its first decoded PTS
through the final frame duration. Long audio cannot conceal short/delayed video.
Full decode and stream coverage are retained separately from container duration.

`windows_ddagrab` requires native Windows and current host/operator/target.
Declare integer `output_index`, `offset_x`, `offset_y`, `width`, `height`, `fps`
(<=60), `encoder: h264_nvenc`, optional installed DirectShow `audio_device`,
`startup_seconds` (0–30, default 5), and `finalize_seconds` (0.01–30, default 5).
The authorization record needs `permitted_recorder: ffmpeg_ddagrab`, matching
operator/target, original grant `receipt`, aware UTC `deadline_utc`, matching
optional `audio_device`, and a `capture` object containing those exact geometry,
encoder, audio, startup and finalization fields. Changing any fails before start.
The full startup + interval + finalization budget must fit the grant, rechecked
after installed encoder discovery. A failed preflight gets an immutable receipt.
These fields document an existing grant; they do not create authority.

The operator must confirm the intended input driver is ready before arming.
Use the current permitted host interface and one desktop operator. This helper
contains no keyboard/mouse control and cannot detect overlays or readiness.
Cancellation is checked before process start and during recording; a latched
cancel callback prevents a queued start after reclaim. CLI Ctrl-C cancels the
owned process. Let FFmpeg's `-t` finish naturally within the startup allowance;
the watchdog then sends `q`, bounds muxer finalization and cleans only its own
process tree. Timeout/failed cleanup stays incomplete. Native output uses
`dup_frames=0` and `fps_mode passthrough`; do not duplicate frames to hide loss.
Pair audio/video coverage, and defer external WAV saving or expensive diagnostic
work until outside the measured interval. Preserve logs and malformed-container
failures; do not overwrite or automatically recapture.

Record effective game args/backend separately from Dummy import or quiet branches.
Static wrapper scanning does not execute a wrapper or resolve its dynamic branches;
retain the actual launch receipt for effective behavior. Master/file capture and
speaker/system output are different sources and need an explicit relationship.

Performance requires raw complete wall-frame rows, clock offset/uncertainty and
precision, plus `timing.context` referencing observer/provenance, run and timing
hashes, effective settings, host interference observation, `host_evidence` and
`clock_evidence`. The context's `clock` repeats the mapped offset, uncertainty and
precision. Total durations must cover the full interval, with consistent adjacent
rows; per-row tolerances cannot accumulate missing wall time. p50/p95/p99/max and
>=100 ms stalls are computed; GPU/encoded FPS are not wall-frame timing. Missing
provenance stays unverified. Synthetic provenance remains test scope; real raw
operator evidence is labeled operator_reported.

`timing.recorder_off` optionally supplies a **distinct** matched raw measurement
and context, with settings/route/candidate digest, different `measurement_id`,
`recording_active: false`, its own timing/clock/host evidence. The recorder-on
context must declare its ID and `recording_active: true`. Relabeling the same
rows as off is rejected. Only this pair supports a measured p95 delta; without
it no capture overhead claim is made. `requires_recorder_off` keeps a criterion
pending until the reference exists. Model proposals cannot override measured
performance. Raw interaction evidence similarly needs exact run/media/input
route, observer/provenance, source evidence and mapped clock; ordering uncertainty
must support the claimed input-before-outcome transition.

## Named evidence and qualification

An established reviewer is adopted at one checkpoint by configuring host
`review_trust` with a named observer, allowed roles, scope and approved original
record hashes. This is not a permission question for every criterion. Example:

```json
{"review_trust":{"Named reviewer":{"roles":["independent_reviewer","independent_qualifier"],"scope":"operational","approved_sha256":["EXACT_ORIGINAL_RECORD_SHA256"]}}}
```

`ingest` validates an observations record: schema 1, kind `observations`, observer,
role (`independent_reviewer`, `listener`, or `operator`), scope, exact run/clip
hashes, and observations with criterion ID/kind/status/full interval/concrete
observation/retained files. Independent reviewers differ from the run owner.
Listener roles cover only audio. Temporal reviews include bounded actual
`temporal_coverage`; visual reviews retain inspection notes. Audio includes
`listening` (performed, playback_route, interval_seconds) and `audio_relation`
(source_sha256, capture_source, mode recorded_playback/live_output, output_route).
The named speakers can differ from the capture label; output_route must match
listening playback_route. `requires_local_output` rejects file-only listening.
Named interactions include route, bounded action/state timestamps and uncertainty.
Named performance observations include `wall_timing` with method wall_frame_time,
p95_ms, max_ms, clock_uncertainty_seconds and host_interference; pass must meet the
card thresholds. Recorder overhead still requires the paired raw on/off route.
The command returns a receipt reference for `observations.reviews`. Retain the
host config when assessing, validating or comparing those records.

`qualify` consumes an approved schema-1 `qualification-evaluation` from an
`independent_qualifier`. Use the executable example for the exact record schema:
corpus reference plus ten cases, each binding run path/hash, analysis hash, clip
hash, selected finding indexes and independently reviewed coverage/evidence.
The original provider steps/usage, request/config and tool identities are retained
and rechecked. Corpus audio roles also require named bounded listening records.
Scores are recomputed, not accepted from a `qualified: true` assertion. The
qualification receipt is supplied as `observations.qualification`.

Acceptance corpus **v2** deliberately uses eight original two-second files for
ten roles. It supersedes the earlier six-second proposal only as an explicit
versioned acceptance revision; it does not rewrite earlier evidence. Frozen
roles: M01 clean temporal, M02 three-frame disappearance at 30 FPS (0.9–1.0s),
M03 single 60 FPS frame challenge (56/60–57/60s), M04 game stall with raw timing,
M05 recorder loss with smooth game timing/PTS loss, M06/M07 controlled blue input
marker and present/absent green outcome with logs, M08 original cue (clean file),
M09 silent audio negative, M10 clean file in a distinct affected recheck of M02.
The clean file serves three roles and is never counted as three independent
media items. Retain generator, media hashes, decoded PTS, timing, action/cue/state
truth separately. Truth is excluded from actual analyzer prompts and uploads.

The common dense window is 0.7–1.3s. Mandatory disappearance length (100 ms),
submitted dense gap (<=33.4 ms), and boundary localization (+/-33.4 ms) are separate
requirements. Audio cue localization tolerance is +/-100 ms. M03 remains explicitly
unsupported on a miss and cannot excuse M02 failure. Scores retain detections,
clean controls, misses, false positives and unsupported roles. File-only M10
checks evidence lineage; a live recorder/input M10 still needs native validation.

Trust boundary: approved named records attest what people reviewed; hashes detect
drift and do not prove someone listened or that a server processed every frame.
Host configuration and the executing code must remain controlled by the adopting
operator. Consumers recheck host approval and recompute records; changing arbitrary
project files/self-hashes is insufficient. A privileged operator who alters both
host trust and evidence can lie. Test transport and test observer records never
qualify operational capability. Even a qualified empirical detection envelope
leaves internal model sampling unknown and human production acceptance separate.

## Provider profile, limits and accounting

Implemented backend: Gemini Developer API Interactions, `gemini-3.7-flash`, full
continuous video requested at static 1 FPS, supplemented by at most 180 decoded
PNG images at high resolution; thinking low, store false, bounded output tokens.
Before submission, dense images are regenerated from the approved video and
compared byte-for-byte. Self-declared sidecar hashes do not authorize other media.
The entire encoded request must fit the authorized byte cap (<20 MB). No redirects,
persistent Files API upload, automatic retry or automatic recapture is provided.
Doctor reports absent configured credentials as needs_setup and present credentials
as unverified, without a network probe or key output.

The budget requires exact approved_media_sha256, authorization_id, upload_authorized,
model, max_requests (1–20), max_total_usd (<=100), reserve_per_request_usd,
max_request_bytes (<=19,000,000), max_output_tokens (1–8192), rate_verified_utc
(aware, within seven days), rates_model matching the model, rates_profile
`standard-all-context`, and rates_usd_per_million for input/output/thought.
The supported September 2026 price floors are $0.75/$3.75/$3.75 per million
respectively; floors double in 2027 under the documented price schedule.

Compressed byte size and approximate media token counts are not a defensible cost
ceiling. The current conservative bound uses the documented 1,048,576 input and
65,536 output ceiling plus a separate 65,536-token thought allowance. At those
2026 rates the preflight bound is **$1.277952/request**, even for a small file.
The previous $0.25 reservation/$2 total proposal therefore fails preflight; it
has not been expanded or authorized by this implementation. Smaller reservations
need a separately justified tighter bound. Local reservations are conservative
accounting, not a provider-enforced spending cap. Report reserved amount separately
from returned usage and the conservative cost calculated from that usage.

Keep exact original request and bounded response bytes, provider ID/model/usage,
request/outcome receipts and ledger. HTTP rejections (400/401/429 etc.) preserve
bounded redacted error bodies and selected headers. Received invalid/schema/usage
results differ from uncertain transport. All unresolved states block subsequent
submissions. With store=false, later server retrieval cannot be assumed; reconcile
retained bytes and account evidence before any new authorization. Never reset or
automatically resubmit an ambiguous request.

Primary references checked 6 September 2026:
[Interactions steps/config/schema](https://ai.google.dev/api/interactions-api-v1),
[Gemini 3.7 Flash limits](https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash),
[pricing schedule](https://ai.google.dev/gemini-api/docs/pricing),
[media resolution](https://ai.google.dev/gemini-api/docs/media-resolution),
[video/static sampling](https://ai.google.dev/gemini-api/docs/video-understanding),
[FFmpeg stdin/fps_mode](https://ffmpeg.org/ffmpeg.html),
[Windows ddagrab](https://ffmpeg.org/ffmpeg-filters.html#ddagrab).
The documented response uses `steps` with `type: model_output` and `content`;
`outputs[]` is not substituted based on old recall. Actual endpoint/auth/provider
behavior and perception remain unverified until authorized independently evaluated
runs. Native capture/control/audio, frozen-game pilot and registered adoption are
separate pending gates.
