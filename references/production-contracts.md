# Minimal production contracts

Use [project](../templates/project.json), [work card](../templates/work-card.md), [asset](../templates/asset.json), [audio cues](../templates/audio-cues.json) and [candidate](../templates/candidate.json). Templates are starting structures, not passed evidence. Schema version is `1`; supported kinds are project, asset, audio-cues and candidate. Terrain/provider records are validated by their adapters.

All stored artifact entries have `path` relative to GAME and `sha256` of actual bytes. Paths escaping GAME, missing files and mismatched hashes fail validation. Units are metres. Record exact reference IDs/version and decision status; retain the image/file with its rights and hash. A name such as “painterly” cannot replace a reference.

An asset moves `working → exported → imported → reviewed → accepted`. Source is always explicit; exported stages require actual runtime files. Imported stages require hashed `import_evidence`, reviewed stages also need `review_evidence`, accepted stages an explicit acceptance decision. Animated assets have rig identity and named clip duration/sample rate/loop/root-motion metadata. A provider success is a separate task status and cannot advance these stages by itself.

Audio cues link the preserved original to prepared runtime audio, event/location, bus, priority, variation, loop bounds, measured duration/channel/rate, rights and listening verdict. Use `audio measure` for 16-bit PCM WAV; prepare keeps the original intact. Encoded provider audio is measured/transcoded with an explicitly configured FFmpeg/FFprobe route. Output format is not proof of listening quality.

Create a candidate **after final content changes**:

```text
python <KIT>/scripts/studio.py candidate --project <GAME> --id harbor-001
python <KIT>/scripts/studio.py validate-record --project <GAME> --record artifacts/candidate.json
```

The candidate stores a sorted content-file inventory and digest, the workflow file inventory/digest/version, declared engine version, settings/input route from project.json and five independent verdicts. Missing settings or route stay unverified/not_defined and block acceptance. Match declared engine/settings to actual build/capture evidence; the inventory does not invent a build identity. `.git`, `.godot`, `.studio`, `artifacts`, Python caches and the ignored host file are excluded from the content inventory. Put evidence under `artifacts/`; adding or changing project content invalidates the candidate and requires a new inventory. Do not change the excluded-directory list to hide game changes.

`pass`/`fail` needs actual hashed evidence with matching `content_digest`, a method and observer. `not_applicable` needs a reason. `not_run`/`unverified` are honest incomplete states. Candidate validation checks evidence consistency, not the truth of a human judgment; the reviewer must inspect the capture. [Acceptance](acceptance.md) defines appropriate methods.

Commands expose `--help`: `check-package`, `doctor`, `setup`, `validate-record`, `fixture`, `blender`, `terrain`, `audio`, `meshy`, `gaea`, `godot`, `candidate`. `setup` emits exact actions and makes no installations. Paid operations require a budget record naming the work card, authorization, current rate-check date, units, estimated request cost and maximum. This records existing session authorization; it is not a demand to ask twice.

Keep one compact session routing receipt in the work card or linked evidence:
actual KIT root/version and manifest/selected-skill hashes; actual read time or
tool-call reference; registered/direct_file/pending status; chosen capability and
the current four-fact decision. Reuse unchanged reads; refresh only changed
scope, hashes or capability assumptions. A retrospective receipt points to the
earlier calls rather than inventing times. Distinguish following skill guidance,
running a kit helper and running project-owned tests. A menu listing or file read
does not prove registered invocation. This receipt needs neither a new schema
nor mandatory reads of every sibling.

Use [process and evidence lifecycle](execution-evidence.md) for bounded hidden
jobs, unique run evidence, completed-log status and active/idle budget accounting.
