# Resumable model factory

The factory orchestrates one versioned model brief, its complete LOD group,
mechanical QA, size measurements and exact external review attestations. It does
not design models, select reviewers, use providers, operate a queue, or choose
an upload service. The CLI is always a publication dry-run:

```text
python scripts/studio.py model-factory --project /game --brief models/brief.json --run-id specimen-v1 --config /host.json
python scripts/studio.py model-factory --project /game --brief models/brief.json --run-id specimen-v1 --approvals reviews/approved.json --config /host.json
```

`--cutoff-utc 2026-10-23T11:00:00Z` bounds the remaining time before each native
operation. Each native adapter receives the smaller of the configured timeout
and remaining time, rounded down to whole seconds, at most 3600 seconds. A
subsecond remainder stops further work. The existing host preflight runs once
before any native work in a new attempt, including QA of reused assets. Its
blocking reasons are honored; unsupported hosts are recorded as unsupported.
No packages are installed. `model_qa_python_site_packages` in the host config
selects an existing directory compatible with Blender's Python.

CLI exit 0 means **ready** or **published** according to these declared gates,
never player acceptance. A blocked dry-run is a useful diagnostic result, but
is not production success. The CLI has no publish switch. Native availability,
measurement validity, policy knowledge, human approvals and artistic acceptance
are separate facts.

## Model brief, schema 1

All objects reject unknown fields. All file references use project-relative
portable paths (no absolute paths, backslashes, traversal or escaping symlinks)
and lowercase SHA-256 hashes of the exact bytes:

```json
{"path":"references/concept.png","sha256":"<64 lowercase hexadecimal characters>"}
```

The full schema is:

```json
{
  "schema_version": 1,
  "id": "specimen",
  "version": "v1",
  "concept": {"path":"references/concept.png","sha256":"<sha256>"},
  "policy": {
    "reference": {"path":"references/policy.md","sha256":"<sha256>"},
    "allow_nonliving_na": false,
    "allow_clump_info": false
  },
  "ecology": {
    "living": true,
    "reference": {"path":"references/ecology.md","sha256":"<sha256>"},
    "reason": null
  },
  "size_m": [1.0, 2.0, 3.0],
  "tolerance_m": 0.01,
  "structure": "assembly",
  "ground_y_m": 0.0,
  "lods": [
    {"level":0,"maximum_triangles":10000,"switch_distance_m":2.0},
    {"level":1,"maximum_triangles":3000,"switch_distance_m":15.0}
  ],
  "build": {
    "mode":"blender",
    "source":{"path":"source/specimen.blend","sha256":"<sha256>"},
    "builder":{"path":"tools/export.py","sha256":"<sha256>"},
    "dependencies":[{"path":"source/input.glb","sha256":"<sha256>"}]
  }
}
```

`id` uses 1–128 letters, digits, hyphens or underscores, starting with a letter
or digit. `version` is a nonempty descriptive string. `concept` may be absent or
null. Policy reference and living ecology reference may be null. `size_m` and
`tolerance_m` may be null independently. A LOD maximum or distance may be null.
These unknowns permit diagnostic work; they never imply approval or a guessed
positive policy value. A supplied reference must exist and match its hash.

Known size is three positive finite dimensions in **glTF Y-up order [X,Y,Z]**;
tolerance is one nonnegative finite absolute tolerance applied to each axis
and every LOD. LODs must be contiguous from zero with at least two levels.
Known triangle maxima are positive integers, never minima. Known distances are
positive, finite and strictly increasing across the ordered levels, including
known distances separated by unknown entries. LOD0 is the preview distance;
later levels are incoming switch distances. `structure` is `assembly`, `scatter`
or `clump`; optional `ground_y_m` is finite and defaults to zero.

For a nonliving subject use
`{"living":false,"reference":null,"reason":"Manufactured object"}`. This
explicit rationale makes ecology N/A applicable only when the declared policy
also enables `allow_nonliving_na`. Clump overlap INFO is applicable only when
structure is clump and `allow_clump_info` is true. The external human policy
approval binds the referenced policy, numeric LOD and size policy, structure,
ground plane and living/nonliving applicability choices.

An existing exact group can replace the Blender build:

```json
{"mode":"reuse","models":[
  {"level":0,"path":"models/specimen-lod0.glb","sha256":"<sha256>"},
  {"level":1,"path":"models/specimen-lod1.glb","sha256":"<sha256>"}
]}
```

Reuse makes fresh diagnostic copies with canonical family names. It always
reports `operation: reused`, never a new export. The source files are unchanged.
The checked-in [example](../examples/model-factory/brief.json) is deliberately
unapproved and references nonexistent inputs with placeholder hashes. It is a
schema illustration, not a runnable asset or permission to publish.

## Builder contract

The caller owns and hashes the `.blend` source, `.py` builder and every extra
dependency. The factory calls `adapters.blender.script_run` with those paths,
a unique attempt label, every required output and exactly this passthrough:

```text
--factory-request artifacts/model-factory/RUN/attempt-N/request.json
```

The request contains `schema_version: 1`, `root` (absolute project root), the
complete `brief`, `brief_sha256` (raw brief file bytes), and
`outputs: [{level, path}, ...]`. Output paths are project-relative:
`artifacts/model-factory/RUN/attempt-N/build/ID-lodN.glb`. The builder must resolve
the request argument from its project context, use `root` to resolve all output
and dependency paths, produce every GLB there, leave declared inputs unchanged,
and exit nonzero on failure. It must not treat this request as permission for
provider calls or publication. Additional outputs are not implied; the kit
adapter's receipts remain the evidence for execution, separate from quality.

## Measurements and resume

The existing model-QA main runs synchronously with every LOD and its default
thresholds. When all caps are known, the runner receives their largest maximum;
the factory independently compares every measured triangle count with its exact
level's maximum. If any cap is unknown the runner receives `not-set`. If any
distance is unknown, no distance list is supplied, so QA's diagnostic fallback
and failure remain visible. Original report rows are preserved unchanged.

Exact model hashes, every expected check for every LOD, successful execution,
absence of report errors and known labels are required. FAIL, UNKNOWN,
UNMEASURED and NOT SET block publication. N/A and INFO are accepted only under
the explicit applicability rules above and are never relabeled PASS.

Each LOD also receives a fresh `adapters.blender.inspect` output. Its raw
`dimensions_m` use Blender Z-up, so comparison uses `[raw[0],raw[2],raw[1]]`.
The factory requests `rest_pose=True`: every imported armature is switched to
REST and the view layer updates before bounds are measured. Static mesh and
object transforms remain as imported. The inspector records
`bounds_pose: armature_rest`, which the factory requires before a known size can
qualify; a missing or different marker makes size UNMEASURED, retaining the raw
dimensions. Unsupported node animation remains blocked by model QA. This size
definition does not qualify animation envelopes. Other adapter callers retain
the default `rest_pose=False` behavior with `bounds_pose: imported`.
Raw JSON, log and diagnostic `.blend` outputs are preserved with hashes.
Missing capability or failed inspection leaves an incomplete attempt and its
evidence; it never substitutes old measurements.

Run identity binds raw brief bytes, all referenced inputs, current kit Python
source hashes, host configuration digest, resolved Blender executable hash,
and configured QA dependency contents (excluding generated bytecode caches).
Input or workflow changes require a **new run ID**. The callback is a trusted
wrapper boundary; generic core does not authenticate the wrapper's source.
Wrappers should pin their own implementation and upload-service identity.

Each attempt has immutable request/build/report/size evidence and a final
checkpoint. Build and finish checkpoints each have a separate confirmation
record hashing the checkpoint file. A successful completed attempt resumes only
after those confirmations and all evidence/output hashes verify. Required stage
records cannot be omitted from the finish evidence list. The factory reconstructs
QA from the raw report, execution receipt and recorded runner return code, and
size gates from each raw rest-pose inspection, then compares the saved gates and
cached candidate. Models, operation and group digest must match the confirmed
build. Editing cached finish gates cannot bypass this verification.

A missing finish confirmation is an interrupted finalization and requires
explicit retry; no cached candidate is trusted. A hash mismatch is refused.
An independently confirmed successful build can still be reused after that
interruption. A build without its confirmation cannot authorize reuse.
If a confirmation or previous finish records a build checkpoint that is now
missing, retry refuses instead of rerunning the builder.
These local links protect against isolated corruption, not an actor rewriting
the entire evidence chain. Failed/interrupted attempts require `--retry-failed`
and produce a new attempt directory. Explicit retry also reruns a completed but
unqualified diagnostic attempt. A committed successful build is hash-verified
and copied into the new attempt as `operation: reused_build`, with its original
operation and checkpoint recorded; a downstream QA/size failure never reruns
the artistic builder. Diagnostic stages are rerun. A missing or tampered build
checkpoint cannot authorize reuse. Previous failures remain intact. Successful
completed diagnostic evidence can acquire new external approvals without
changing the core brief or rerunning native measurements. A partially executed
attempt is never automatically resumed into native work or publication.

An OS file lock serializes writers of one run across processes. The lock file
is retained; a process crash releases the lock, not evidence. Different run IDs
are separate jobs; the caller still owns host/GPU scheduling and concurrency.
The factory does not stop unrelated native processes.

## Human approvals and visual review

An approval bundle can be added or replaced on resume. Every evidence reference
is rehashed each invocation. Schema validation verifies **attestations and
identities**, not the authenticity of a human author. The caller must supply
real original human evidence rather than treating this schema as an approval
generator. There is no default reviewer.

```json
{
  "schema_version": 1,
  "approvals": [
    {"kind":"concept","authority":"human","decision":"approved",
     "subject_sha256":"<exact concept file SHA-256>","reviewer":"Named human",
     "evidence":[{"path":"reviews/original.txt","sha256":"<sha256>"}]},
    {"kind":"policy","authority":"human","decision":"approved",
     "subject_sha256":"<exact policy subject digest>","reviewer":"Named human",
     "evidence":[{"path":"reviews/original.txt","sha256":"<sha256>"}]},
    {"kind":"model","authority":"human","decision":"approved",
     "subject_sha256":"<complete group digest>","reviewer":"Named human",
     "evidence":[{"path":"reviews/original.txt","sha256":"<sha256>"}]}
  ],
  "review": {
    "verdict":"pass",
    "group_sha256":"<complete group digest>",
    "concept_sha256":"<exact concept file SHA-256>",
    "brief_sha256":"<raw brief file SHA-256>",
    "observer":"Named observer",
    "method":"capture_comparison",
    "captures":[{"path":"reviews/capture.png","sha256":"<sha256>",
                 "metadata":{"path":"reviews/capture.json","sha256":"<sha256>"}}],
    "observations":["Specific observed result and limitations"]
  }
}
```

Living subjects additionally require kind `ecology` with the digest of the full
brief ecology object. Concept approval binds the concept file hash. Policy
approval binds `studio_tools.model_factory.policy_subject(brief)`: the digest
of an object containing `policy`, `lods`, `size_m`, `tolerance_m`, `structure`,
`ground_y_m` (zero when absent) and `ecology_applicability: {living,reason}`.
Changing a cap, distance, size, tolerance or applicability invalidates that
approval even when the referenced policy document is unchanged. Model
approval binds `digest([{level,sha256}, ...])` over **all** ordered LODs. These
object digests use `studio_tools.common.digest`: UTF-8 JSON with sorted keys,
compact separators and no nonfinite numbers. Each approval kind is unique.
Predictions, other authority types, missing original evidence, unknown reviewer
identities, missing concept bindings and placeholder reviews remain blocked.
Ecology structural completeness or a proposed document's status cannot supply
human approval. A metadata-valid policy can still have pending approval.

Supported visual methods are exactly `native_observation` and
`capture_comparison`; prediction methods cannot qualify. Each capture has a
hashed JSON sidecar with this strict schema:

```json
{
  "schema_version": 1,
  "capture_sha256": "<actual capture file SHA-256>",
  "group_sha256": "<complete group digest>",
  "models": [{"level":0,"sha256":"<actual LOD0 SHA-256>"},
             {"level":1,"sha256":"<actual LOD1 SHA-256>"}],
  "camera": {"name":"front","position_m":[0,1,3]},
  "viewport": [1920,1080],
  "lighting": "Neutral studio environment with fixed key light",
  "pose": "Rest pose",
  "renderer": "Workbench"
}
```

`models` must match the exact ordered full LOD hash list; the capture and group
hashes must match. Viewport is positive integer pixel width/height. Camera,
lighting, pose and renderer may be meaningful strings or structured descriptions
of the actual observed setup; every leaf must be known and finite. Empty,
unknown, unmeasured, predicted and placeholder values block review. The schema
does not establish that the described scene really produced those pixels; the
named observer and original evidence supply that attestation.

## Trusted grouped publication API

```python
from studio_tools.model_factory import execute

result = execute(project, "models/brief.json", "specimen-v1", config=host_config,
                 approvals="reviews/approved.json", publish=True,
                 publication_callback=trusted_group_uploader)
```

`execute(project, brief, run_id, *, config=None, approvals=None,
retry_failed=False, cutoff_utc=None, publish=False, publication_callback=None)`
returns a structured result. `config` is a host config dictionary; CLI resolves
its config path with the usual kit loader. `brief` and `approvals` are relative
JSON paths. The callback is never invoked during dry-run or with blocked gates.

The portable manifest contains `id`, `version`, `brief: {path,sha256}`,
`concept`, full `policy` and `ecology` descriptors, `group_sha256`,
`models: [{level,path,sha256}]`, declared `lods`, size policy, operation,
QA and size gates, approval bundle, review results and the trust limitation.
It contains project-relative artifact paths, not a machine's absolute root.
Local raw process receipts can contain private host paths and are not embedded.
Each evaluation writes a new immutable `review-N/manifest.json` and result.

The callback receives `(manifest, idempotency_key)` after an fsynced sending
intent. It must enforce its own bounded I/O timeout, implement grouped submission
and return:

```json
{"published":true,"idempotency_key":"<same key>",
 "group_sha256":"<same group>","remote_ref":"<service group identity>"}
```

The key binds brief bytes, full group, id and version independently of the run
ID. The callback must honor it across external retries and preserve any partial
submission receipts. A confirmed success returns the existing receipt on later
calls without a second upload. A crash after intent, callback exception or
ambiguous receipt is **publication_uncertain**, even if no remote write is
known to have happened. `--retry-failed` cannot clear that state. Reconcile with
the service outside the generic core; do not delete sending evidence or blindly
retry under a new run ID. This is conservative at-most-once invocation per run,
not a proof of exactly-once behavior in an arbitrary remote service. A separate
immutable confirmation record hashes the success receipt and sending intent;
the returned result also hashes that confirmation. Resume rechecks these hashes
and the original published review evidence. An interrupted confirmation remains
uncertain. These local integrity links detect isolated tampering, not a hostile
actor rewriting the entire evidence chain; there is no signing authority here.

## Focused CPU tests

```text
python -m unittest discover -s tests -p test_model_factory.py -v
```

Tests mock all native adapters, preflight measurements and network publication.
They do not establish visual acceptance, actual Blender compatibility, QA
dependency availability, remote service correctness or human authenticity.
