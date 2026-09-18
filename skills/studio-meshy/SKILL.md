---
name: studio-meshy
description: Generate or transform a game-asset candidate with Meshy using durable task records, explicit budgets, supported profiles and local output archival, checking what is left with the read-only `studio meshy balance` before asking for spend approval and qualifying the returned mesh's topology in Blender before anything is built on it.
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

Each listed file is `KEY=VALUE` lines, tolerating a leading `export `, surrounding quotes, blank lines, `#` comments and a byte-order mark; a relative path in that list is read from beside the host config file, not from the current directory. The environment wins when both are set, and a listed file that is missing is skipped. Never copy the key into a request, budget, task record or command argument.

For a game asset, always send `should_remesh: true` with an explicit `target_polycount`, and choose the topology the next step needs. An image-to-3d request without them returns the raw dense sculpt — millions of triangles — and the only ways out are a second paid remesh task or a decimation pass in Blender, which is the wrong place to discover it.

| Role of the asset | Starting `target_polycount` |
|---|---|
| Hero landmark the player walks up to | 40000–60000 |
| Creature or character that will be rigged | 20000–30000 |
| Prop, set dressing, background object | 5000–15000 |

Those are starting points to adjust after inspecting the first import against the scene's budget, not provider recommendations; the helper accepts 100–300000 and sets no default, because the request has to state the size it wants. Use `topology: "triangle"` when the mesh goes straight to the engine and `"quad"` when Blender sculpt or retopology follows. `symmetry_mode` is `off`, `auto` or `on`; leave it at the provider's `auto` unless the reference is deliberately asymmetric.

## Polycount and topology: what was measured

Measured on one hero tree and one creature. Triangle and edge counts are what `studio blender inspect` now reports for every mesh object.

| Mesh | Request | Triangles | Boundary edges | Nonmanifold edges |
|---|---|---|---|---|
| Hero tree | image-to-3d, no polycount asked for | 4,853,274 | 0 | 0 |
| Hero tree | provider remesh of that tree, `target_polycount: 120000`, 5 credits | 125,485 | 91 | 87 |
| Creature | image-to-3d, `target_polycount: 30000` | 30,816 | 83 | 90 |
| Hero tree | `studio blender reduce` from the intact 4.85M original, no credits | 300,000 | 0 | 0 |

The dense original was clean: once duplicated texture-seam vertices are welded by position, no boundary edges, no edge shared by more than two faces and no vertex where the surrounding faces fall into more than one fan. Dense, but nothing wrong with it. Both polycount-constrained provider meshes were defective, and not recoverably: a coincident weld plus conservative degenerate cleanup fixed neither, and removing the unambiguous dangling faces left 11 boundary / 47 nonmanifold edges on the tree and 27 / 62 on the creature. The tree's pores were visibly angular underneath at 125K. Neither is ready for rigging or collision. The local weld-and-decimate from the intact original reported zero of all three defects and kept better underside detail than the paid 125K mesh.

So:

- **Request the polycount at generation, for cost.** A raw sculpt is millions of triangles, and every route out of it costs credits or time.
- **Treat every provider mesh as unqualified until `studio blender inspect` reports clean topology.** A triangle count inside budget is not a usable mesh, and a viewport that looks right is not evidence: the defects above were underneath.
- **When a provider mesh is defective, prefer `studio blender reduce` from the intact archived original over a paid remesh.** One remesh at 120K came back defective; paying again buys another sample of the same process, while the local reduction is free, repeatable and audited before and after.
- **A dense clean original is an asset to archive, not a failure.** It is the only input a local reduction can be qualified from, and `reduce` refuses to call its result ok when the source it started from was already defective.

Choose image generation for an exact reference; preview then a separately authorized refine when text generation needs shape approval. Retexture changes appearance; remesh changes topology and needs new deformation/UV checks. The supported rig profile requires a checked textured humanoid biped. Nonhumanoid or unchecked assets route to [studio-animation](../studio-animation/SKILL.md) **before any paid call**, even if a newer provider offers other experimental rig types.

1. Create a request and budget JSON in the game project. Budget records prior authorization, work card, checked date, units, estimated single-request cost and maximum. Configure the credential as above; do not put keys in records.
2. `meshy submit` claims the record before its only POST. Never reuse its path for another request. A crash/timeout before receiving a task ID is `SUBMISSION_UNKNOWN`, not permission to retry. Reconcile against provider history with the request digest and attach the verified task ID using `reconcile`.
3. `meshy observe` resumes the same task with bounded attempts. Pending, failed, canceled, expired and unavailable states preserve work. Do not turn an observation into a resubmission. Polling/retrieval is separate from paid generation.
4. On success, `meshy archive` downloads outputs atomically and saves hashes after each file. Outputs live under `<archive-root>/<task-id>/`; completed files resume only when this task record owns the path and its hash still matches. Existing unowned or modified files are preserved and cause refusal; choose a fresh archive root or explicitly reconcile them. Repeat archive to resume completed downloads; a partial or invalid GLB is not accepted. Record provider-returned credit/expiry metadata and archive promptly because URLs are temporary. Task JSON may contain signed private asset URLs; do not publish it blindly.
5. Inspect actual geometry with [Blender](../studio-blender/SKILL.md): topology, dimensions, UVs/materials, collision suitability and skeleton/clips. Retain source/provider provenance, output hashes and eligibility evidence in the asset record. Provider success remains separate from stage/review.

Return the existing resumable task record, local outputs, inspected asset record, spent/returned metadata and next review question. An exhausted budget or unknown request outcome stops further paid work, not unrelated local preparation.
