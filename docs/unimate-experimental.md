# Experimental UniMate worker foundation

This is an optional protocol boundary, not a bundled inference implementation or
production-supported motion provider. No model, worker, environment, Blender
bridge or download is installed. Model/condition semantics, creature quality,
actual offline execution and game adoption remain unverified. The provider's
task completion cannot advance an asset's acceptance stage.

Use the existing animation, Blender authoring/export and review routes. The
foundation is a lazy CLI branch, stdlib request/receipt adapter and the existing
owned process runner. `doctor` reports configuration presence without running the
interpreter or loading ML. Keep host paths in explicit ignored host config.

```text
python <KIT>/scripts/studio.py unimate inspect --project <EXPERIMENT> --config <HOST> --request request.json
python <KIT>/scripts/studio.py unimate generate --project <EXPERIMENT> --config <HOST> --request request.json --record artifacts/unimate/<new-id>/task.json
```

Inspection writes nothing and never starts a worker, Blender, CUDA or network
client. Generation requires an existing project and a new run directory. There
is exactly one attempt, batch size 1, at most 8 samples, and timeout <=3600 s
bounded again by an explicit UTC cutoff. There is no retry, model/seed fallback
or cache download. CPU uses no visible CUDA device. GPU requires a hashed external
reservation naming the owner/device and valid through the cutoff; this is a
declaration from the coordinator, not GPU arbitration or proof of a quiet host.
The request's `execution.device` names the physical device for reservation and
provenance. For `cuda:3`, the child receives `CUDA_VISIBLE_DEVICES=3` and must
address its single visible GPU as `worker_device: cuda:0` from input.json.
Never pass the physical ordinal to an ML device constructor after masking.
CPU receives `worker_device: cpu` and an empty CUDA visibility mask. The task
receipt retains both names in `device_mapping`; request identity stays physical.

## Request and rig contracts

Request schema version 1: `provider: unimate`, `experimental: true`, `work_card`,
`mode: text_tpos`, `model_profile`, hashed project-relative `rig_manifest`, and
`clips`. Each clip has `name` (idle/walk/graze/startle), nonempty `prompt`, uint32
`seed`, boolean `loop` (true except startle), `root_motion: in_place`, and optional
distinct `sample_id`. The latter defaults to the clip name; use `walk-42` and
`walk-43` to compare two seeds with the same named clip role.

`limits` declares `batch_size: 1`, `maximum_attempts: 1`, `maximum_samples` and
`timeout_seconds`. `execution` declares `resource_owner`, `device: cpu` or one
`cuda:<index>`, `cutoff_utc` and a hashed reservation if GPU is requested.

The rig manifest declares schema 1, `subject: chalk_mite`, `preparation:
rest_only`, `reference_motion_clips: []`, hashed `.blend` `source`, untouched
animated `.glb` `baseline`, prepared `.npy` `condition`, `canonical_axes:
Y_up_Z_forward`, a proper uniform `canonical_from_source` 4x4 similarity, and
canonical-order `joints` entries `{name, parent}`. The adapter inspects the
baseline GLB's single skin and verifies the exact 31 Mite names/parent relations,
irrespective of ordering. It verifies condition bytes by hash; it does **not**
parse NumPy values or authenticate a declared preparation. The isolated worker
must validate actual shapes, topology, stats, bindings and rest matrices.

The original Mite has four clips. An animated `preprocess_char` path can prune
bones. Prepare a disposable rest-only export or call pinned `cond_from_rest`,
prove all 31 joints/rest/parents survive, and bake onto an original-source copy
through existing `blender run`. Preserve the baseline. Kite/slug conditioning,
in-betweening and editing are unsupported by this foundation. Preserve slug's
contact shape-key authoring outside this route.

## Host inventory and offline policy

Host `unimate` block: `protocol_version: 1`; hashed absolute local `python` and
`worker` entries `{id, path, sha256}`; `provenance` with immutable 40-hex
`code_revision`, `bridge_revision`, `model_revision`, nonempty `model_profile`,
`normalizer_profile`, `license`; and `assets` entries `{id, role, path, sha256}`.
Required roles: checkpoint, model_config, statistics, encoder_weights,
encoder_config, tokenizer, normalizer. Multiple files per role are allowed. The
worker must inventory every required tokenizer/normalization file, not just one
representative cache file. Missing files fail with OFFLINE_ASSET_MISSING before
execution; hashes/ref/profile mismatches refuse execution.

Host `capabilities` must partition all 31 joint names into distinct
`independent_rotation_joints` and `unsupported_rotation_joints`, with
`unsupported_joint_policy: source_rest_only`. The current pilot decoder cannot
independently propose leaf-bone rotations: both L_Mandible and R_Mandible and
all 14 L/R00..06_Lower bones must be disclosed as unsupported. List any other
unsupported joints too. This limits graze and gait and must be shown alongside
the comparison. Inspection and task
receipts retain the disclosure as `capability_validation: declared_only`.
Generated position or inherited parent movement is not an independent jaw
or distal-leg rotation proposal. The worker must leave unsupported local rotations at source
rest; do not fill them with original clip motion or label every skeletal DOF as
generated. Any later manual or borrowed articulation requires a separate,
explicitly labelled authoring provenance and review.

A separately authorized setup may provision local assets. Runtime passes
HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1, PYTHONNOUSERSITE=1 and requests
`local_files_only: true`, `downloads: false`. The child environment contains only
basic Windows/path/temp variables and these settings, not inherited credentials.
The adapter cannot enforce network denial inside an arbitrary supplied worker;
`offline_execution` remains unverified even when the task succeeds. The validated
bridge must use explicit local paths and local_files_only loaders, prohibit
spaCy's download fallback, and fail for missing language-model/normalizer files
without switching profiles. Prove a full run with network disabled plus tests
that remove each required asset and intercept every download/network path,
including spaCy. Flags or fake-worker tests alone are not that proof.

## Isolated worker protocol for the pilot

Run the configured interpreter/worker with `--input <input.json> --output
<result.json>` once. Input carries schema 1, request, request_digest, rig,
project root, resolved hashed local assets, provenance, new output directory,
capabilities, and offline_policy. It is a private local artifact with host paths.
Input also carries the explicit worker-local `worker_device`; use this field
for text/model/tensor placement, while retaining the physical request unchanged.

The worker result carries schema 1, matching `request_digest`, `rig_sha256`
(request's rig-manifest hash), `provenance_digest` (Kit canonical JSON digest of
input provenance), and `clips`. It also carries `capabilities_digest`, the same
canonical digest of input capabilities, so a result cannot omit or substitute
its declared limitations. Each result clip repeats name/sample_id, seed and
loop/root_motion and reports measured finite duration_seconds/sample_rate.
`raw` and `decoded` are hashed project-relative file entries under this run's
output directory, respectively `.npy` and `.npz`. Missing/skipped/duplicate or
misattributed samples fail; filenames and seeds must not be substituted.
The result and file hashes validate the manifest, not array semantics or quality.
Archive the pilot's generation.json and model-hashes.json separately with the
validated worker's actual timings/allocator peaks; do not invent those measures.

### What the completed pilot can supply

The reviewed local interface notes are `DELIVERY-HANDOFF.md` and
`ARTIFACT-INTERFACE.md` from the separate experiment. They document an
**animated-reference** route on `chalk-mite-runtime-v3.blend`, earlier than the
selected mineral v6 source. It used the real authored walk, released Objaverse
statistics and the stock dataset/condition factories. Static-position
idle/graze/startle references were filtered. No general rest-only bridge was
validated. Do not configure that hardcoded `infer.py` as this protocol worker:
it has fixed cases/current-directory paths, no request/result interface and
different preparation semantics. The foundation continues to refuse declared
animated-reference preparation. A separately validated rest-only bridge is
still needed; expanding preparation modes would require explicit design review.

Useful future bridge inputs are the pinned canonical condition and permutation,
original names/parents/rest checks, released normalization/config, exact prompts
and seeds. Its `(60,31,12)` raw `.npy` output and decoded `.npz` keys
`positions`, `rotations`, `offsets`, `parents`, `tpos_global_rot`, `joint_names`
are retained separately. The existing source bake uses official
`compute_bone_keyframes` rest conjugation and checks original mesh, skin, rest,
hierarchy and material preservation. Raw Root trajectories remain present;
viewer whole-Root compensation is presentation only. Export timings cover
0..1.966667 s for 60 samples at 30 Hz, not proven two-second seamless loops.

Pilot source revision: `f7f2fec067996f206e819f0fe81b0c264f78077d`.
Checkpoint: `unimate_uniml3d_f60_v2/checkpoints/checkpoint_step_100000.pt`, SHA-256
`cbcfb7a057e45f967d5964fecf6b3f83358096f1306f25831e1644a18a50eb34`.
Text-model revision: `7bcac572ce56db69c1ea7c8af255c5d7c9672fc2`.
Full hashes and dependency versions belong in the experiment's
`model-hashes.json`, `text-model.json` and `environment-lock.txt`; these three
pins alone do not establish all host assets or licenses.

Four observed GPU cases completed on an RTX 4060 Laptop 8 GB in 39.6..80.2 s
per clip, batch 1/float32/CFG 3/stock dopri5/v2 EMA, with CPU text encoding before
GPU sampling. This establishes that bounded local sampling can work on that
host profile. It does not establish cleanroom throughput, offline enforcement,
quality or game performance. Initial archived runner receipts omitted the
Windows ownership baseline; do not backfill proof. Future protocol runs must
use this foundation's baseline/cleanup contract. Its worker remains unbundled.

Stock `unimate/utils/motion_utils.py` recovery initializes rotations to identity
and assigns represented-child rotations to parents. Leaf rotations remain
identity. The 16 unsupported Mite jaw/lower-leg channels therefore affect both
graze and gait; prompts or bone renaming cannot recover absent independent
channels. This foundation's explicit source-rest policy is not permission for
an unlabelled authored/generated hybrid.

The adapter rechecks pinned assets/source after ownership preflight and exit,
uses the existing runner with a fresh process receipt, and checks post-exit
descendants using recorded ownership. Interrupted/nonzero/invalid-output runs
retain receipts and partial bytes. Never reuse an old run or signal a PID from
an old receipt. Input/result/logs stay private until audited for sharing.

## Frame math and promotion gates

The stdlib `unimate_motion` helpers are synthetic contract math, not a complete
feature decoder or Blender retargeter. With column vectors, Y-up and +Z forward,
Mite extracts planar Root position/yaw at a fixed frame-zero reference height.
Kite extracts the entire rigid Root transform. Both apply
`B_j = A_ref * inverse(P) * G_j` to every joint, where A_ref is the fixed source
rest anchor in canonical space. Mite preserves bob/tilt subject to contact
review; Kite leaves root fixed and retains descendant articulation. Reconstruct
`G_j = P * inverse(A_ref) * B_j`, inverse-map position/rotation/scale consistently,
and solve original parents before Blender rest/bind authoring. Root-channel
zeroing by itself is insufficient. Tests exercise trajectory invariance,
nonidentity source axes/scale and parent-relative reconstruction.
Stable norm computation and finite arithmetic-result checks reject invalid or
overflowing transforms with structured errors, including correctly hashed
extreme-value manifests; no worker starts for a refused transform.

Packaging/promotion needs user-reviewed generated motion on the same original
31-joint Mite, original-source bake/export/fresh-process round trip, at least one
worthwhile clip with preparation/generation/cleanup cost, a completed bounded
host profile and proven offline operation. A stock/proxy demo or successful GPU
sampling does not close this gate. Native runtime adoption is separate: preserve
controller-owned contact/flight, use the pinned double-precision engine, ordinary
route motion review and attributable cleanroom performance. No push/PR follows
automatically from these foundation tests.

### PR-base compatibility gate

This isolated branch starts at installed 0.1.6
`c9fbe5b55ca9a6dfebed8d2b18d6ebdcbd56d917`; it is not an upgrade of the active
development checkout that declares 0.1.1. Read-only history review found
divergence at `93e88ae` and 96 unrelated files on the installed side. An eventual
PR must choose a compatible target or deliberately cherry-pick/rebase these
bounded commits into a separately planned isolated migration, with the required
ownership runner APIs and package/version checks repeated. Do not wholesale
merge the installed tree into development or reconcile the active checkout as
part of this experiment. This gate is separate from comparison review and
provider packaging acceptance.
