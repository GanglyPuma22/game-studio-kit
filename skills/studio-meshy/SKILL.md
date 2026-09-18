---
name: studio-meshy
description: Generate or transform a game-asset candidate with Meshy using durable task records, explicit budgets, supported profiles and local output archival, checking what is left with the read-only `studio meshy balance` before asking for spend approval.
---

# Studio Meshy

Inputs: reference/prompt and rights, approved asset brief, desired operation, work-card budget, configured credential, output root and unique task-record path. Read [supported provider profiles](references/api.md) only for this route.

Before asking the human to approve spend, check what the account has left. `studio meshy balance` is read-only: it makes one GET, writes no record and prints the number:

```text
python <KIT>/scripts/studio.py meshy balance --config <HOST>
```

It takes no `--project` and no `--record`, prints `{"balance": <number>, "read_only": true}`, and on any failure prints an error *type* (`credential_missing`, `provider_http_401`, `provider_unavailable`, `unexpected_response`) with exit 1 and never the key. A balance is not a price list: current unit rates, entitlement and rights still need your account check.

The credential is read from the configured environment variable. A host that keeps keys in a file instead declares them in its host JSON, and the helper reads the key straight out of that file without putting it in the environment or handing it to any child process:

```json
{"credentials": {"meshy": "MESHY_API_KEY"}, "credential_files": ["C:\\Studio Host\\keys\\meshy.env"]}
```

Each listed file is `KEY=VALUE` lines, tolerating a leading `export `, surrounding quotes, blank lines and `#` comments. The environment wins when both are set, and a listed file that is missing is skipped. Never copy the key into a request, budget, task record or command argument.

Choose image generation for an exact reference; preview then a separately authorized refine when text generation needs shape approval. Retexture changes appearance; remesh changes topology and needs new deformation/UV checks. The supported rig profile requires a checked textured humanoid biped. Nonhumanoid or unchecked assets route to [studio-animation](../studio-animation/SKILL.md) **before any paid call**, even if a newer provider offers other experimental rig types.

1. Create a request and budget JSON in the game project. Budget records prior authorization, work card, checked date, units, estimated single-request cost and maximum. Configure the credential as above; do not put keys in records.
2. `meshy submit` claims the record before its only POST. Never reuse its path for another request. A crash/timeout before receiving a task ID is `SUBMISSION_UNKNOWN`, not permission to retry. Reconcile against provider history with the request digest and attach the verified task ID using `reconcile`.
3. `meshy observe` resumes the same task with bounded attempts. Pending, failed, canceled, expired and unavailable states preserve work. Do not turn an observation into a resubmission. Polling/retrieval is separate from paid generation.
4. On success, `meshy archive` downloads outputs atomically and saves hashes after each file. Outputs live under `<archive-root>/<task-id>/`; completed files resume only when this task record owns the path and its hash still matches. Existing unowned or modified files are preserved and cause refusal; choose a fresh archive root or explicitly reconcile them. Repeat archive to resume completed downloads; a partial or invalid GLB is not accepted. Record provider-returned credit/expiry metadata and archive promptly because URLs are temporary. Task JSON may contain signed private asset URLs; do not publish it blindly.
5. Inspect actual geometry with [Blender](../studio-blender/SKILL.md): topology, dimensions, UVs/materials, collision suitability and skeleton/clips. Retain source/provider provenance, output hashes and eligibility evidence in the asset record. Provider success remains separate from stage/review.

Return the existing resumable task record, local outputs, inspected asset record, spent/returned metadata and next review question. An exhausted budget or unknown request outcome stops further paid work, not unrelated local preparation.
