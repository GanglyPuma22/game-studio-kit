# Operational review loop

Use this under `studio-review`, after defining the work card and the actual host
operator. Resolve `KIT` from the invoked skill path; run `$KIT/scripts/studio.py`
by absolute path. Output belongs in the explicit game/project root outside KIT.
No new desktop/control framework is provided. Read current host instructions:
a configured recorder is usable only when that exact recording route, target,
operator and interval are permitted. Human sustained movement is a valid named
route; label synthetic replay separately.

## First useful checkpoint

Before another integrated expansion, declare one connected reachable route,
expected action/state/cue outcomes, a timing floor, capture/analysis budget and
next decision. Preserve specimen close/play strengths while route experience
failures govern the next integrated change. Do not infer a coherent world from
a polished isolated asset. Ordinary motion, sound and temporal coverage remain
mandatory when the work card requires them.

## Commands and original example

`python "$KIT/examples/review-loop/create.py" --output /explicit/new/example`
creates eight original clips with separate truth annotations, records a file
through FFmpeg, fully decodes video/audio, saves PTS, extracts a fixed dense
interval, computes known synthetic timing failure, and repeats its affected
check on a clean control. Both original clips and immutable run directories
remain. It does not launch a game, listen or submit a model request.

The example's `artifacts/before-card.json`, `after-card.json`, profiles and
observations are usable JSON examples. Extend the existing work card with a
linked JSON validation section; do not maintain a second independent plan.
Card identity must match an existing candidate record, and the delivered
entrypoint must be hashed. Declare effective settings, route, launch intent,
expected actions, criterion kind/dimension/interval and bounded rechecks.

```sh
python "$KIT/scripts/studio.py" review validate-card --project "$GAME" --card artifacts/card.json
python "$KIT/scripts/studio.py" review prepare --project "$GAME" --card artifacts/card.json --role before
python "$KIT/scripts/studio.py" review capture --project "$GAME" --run artifacts/reviews/RUN --profile artifacts/recorder.json
python "$KIT/scripts/studio.py" review dense --project "$GAME" --run artifacts/reviews/RUN --interval 0.7 1.3
python "$KIT/scripts/studio.py" review analyze --project "$GAME" --run artifacts/reviews/RUN --budget artifacts/video-budget.json --dense artifacts/reviews/RUN/dense-0/frames.json
python "$KIT/scripts/studio.py" review assess --project "$GAME" --run artifacts/reviews/RUN --evidence artifacts/observations.json
python "$KIT/scripts/studio.py" review prepare --project "$GAME" --card artifacts/after-card.json --candidate artifacts/after-candidate.json --role after --previous artifacts/reviews/BEFORE --affected PERF
python "$KIT/scripts/studio.py" review compare --project "$GAME" --before artifacts/reviews/BEFORE --after artifacts/reviews/AFTER
```

`analyze` is an outbound operation: use only an applicable media/model/budget
authorization. Current zero-budget work ends after local preparation. A missing
optional observations file leaves affected criteria pending. Evidence files
use the existing `{path, sha256}` contract and are checked before dependent work.
`validate-run` additionally checks the currently selected candidate; historical
comparison uses preserved run identity and evidence without rebinding it to the
current game files. New source content always gets a new candidate and run.

## Recorder profiles and lifecycle

Installed FFmpeg/FFprobe are required; no setup is performed. `file` takes one
explicit local `source`, preserving its original bytes while writing a new MP4.
The CLI owns a foreground process and its logs. At duration or Ctrl-C it sends
FFmpeg `q`, allows five seconds to finalize, then cleans only its owned process
tree. Cancellation, force termination, failed starts, short or undecodable output
remain incomplete. A second capture cannot overwrite the first run. Record only
the agreed game region. Stop on reclaim; overlay/exclusion events invalidate
full capture coverage and require a new bounded run.

A Windows-native profile uses `route: windows_ddagrab`, current `host`,
`operator`, `target`, explicit integer `output_index`, `offset_x`, `offset_y`,
`width`, `height`, `fps` (<=60), and optional `audio_device` for an installed
DirectShow source. Its `authorization` object records `permitted_recorder:
ffmpeg_ddagrab`, matching `operator`/`target`, `receipt`, `deadline_utc` and
matching optional `audio_device`. This is an authorization record, not a grant.
The adapter requires native Windows; WSL interop cannot silently bypass the host
computer-use route. If FFmpeg subprocess capture is prohibited there, leave it
pending and use only the actual permitted host interface. No keyboard/mouse
operations are included. The bounded adapter does not detect user overlays.

Keep game Master PCM distinct from system-loopback/output listening. Record the
actual audio source, stream metadata, output backend, delivered wrapper args and
independent import/live-service state. Static wrapper inspection catches obvious
`Dummy`/`-Muted` errors but cannot resolve every dynamic wrapper; preserve the
real launch receipt and observe effective runtime behavior.

## Video adapter and authorization

One implemented backend: Gemini Developer API Interactions, explicit model in
budget, static full video at requested 1 FPS plus up to 180 original decoded PNG
frames in a fixed dense interval. Frames carry original PTS and source indexes.
The complete request must be below both the authorization byte cap and 20 MB;
large clips need an explicitly approved shorter run. This first adapter does not
upload persistent Files API objects, follow redirects, call tools or resubmit.
Model/API/auth/network operation remains unverified until an authorized run.

Host config names `credentials.gemini` (default `GEMINI_API_KEY`), never a key.
The budget JSON declares `authorization_id`, `upload_authorized`, an exact
`approved_media_sha256` list, `model`, `max_requests`, `max_total_usd`,
`reserve_per_request_usd`, `max_request_bytes`, `max_output_tokens`,
`rate_verified_utc`, and `rates_usd_per_million` for current input/output rates.
Reservations are serialized under the project and preserve ambiguous outcomes.
A changed budget identity, unresolved outcome, missing usage or overrun prevents
further submissions. Reconcile original provider/account evidence before any
new authorization; there is deliberately no automatic retry/reset command.
Money reservations are conservative local accounting, not a provider billing
hard limit. Full original response bytes, request identity and returned usage
are retained; credentials are never written in them.

Primary documentation checked 6 September 2026:
[video input/static sampling](https://ai.google.dev/gemini-api/docs/video-understanding),
[Interactions endpoint and structured output](https://ai.google.dev/api/interactions-api-v1),
[pricing](https://ai.google.dev/gemini-api/docs/pricing),
[FFmpeg stdin and progress](https://ffmpeg.org/ffmpeg.html),
[Windows ddagrab](https://ffmpeg.org/ffmpeg-filters.html#ddagrab).
The video docs expose static sampling and inline input, with default 1 FPS.
The deprecated [VideoMetadata API](https://ai.google.dev/api/generate-content#VideoMetadata)
caps its FPS field at 24. Requested sampling never proves effective perception.
Use the full clip for context and dense original frames for brief events; an
independent known-failure/clean-control run must establish the detection limit.

## Decisions, coverage and limits

The existing pass/fail/not_run/unverified/not_applicable vocabulary is retained.
No supplied `fixture_detection: pass` flag unlocks temporal acceptance. This
release always leaves temporal pass unverified pending actual independent model
qualification; a cited model defect is a provisional failure, never root cause.
An audio stream or model text cannot pass listening. Visual model success stays
unverified. Runtime action transitions and complete wall-frame timing can be
computed from bound raw evidence, with ordinary versus synthetic coverage named.
Synthetic results cannot complete native production acceptance.

Performance consumes complete per-frame wall times, aligns their clock explicitly,
checks continuous coverage and computes nearest-rank p50/p95/p99/max and >=100ms
stalls. Do not pool stationary/moving segments or infer game FPS from encoded FPS.
Unknown host interference/alignment prevents a performance pass. Preserve a matched
recorder-off reference to establish overhead independently. Comparisons require
matching criteria, route, settings, engine and evidence; preserve failures and
repeat only affected checks within the card's budget. Independent reviewer and
human artistic/listening acceptance remain separate from computed outcomes.
