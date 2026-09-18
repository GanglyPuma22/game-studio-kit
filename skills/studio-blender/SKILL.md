---
name: studio-blender
description: Create, inspect, render and explicitly export game asset hierarchies in Blender, run a bake or export script headlessly with `studio blender run`, reduce a dense mesh to a triangle budget with `studio blender reduce`, keeping editable source and verifying geometry, materials, topology and animation after GLB round trip.
---

# Studio Blender

Inputs: asset brief, source or references, collection/hierarchy name, dimensions/pivot, material and clip requirements. Resolve the helper from [portability](../../references/portability.md); run `doctor` with the host config. The core path is an owned background Blender process, independent of any addon or generic installed skill.

For the original pipeline fixture:

```text
python <KIT>/scripts/studio.py blender fixture --project <GAME> --output source/bell --config <HOST>
```

For project-owned sources:

```text
python <KIT>/scripts/studio.py blender export --project <GAME> --source source/asset.blend --collection RuntimeAsset --output assets/asset.glb --config <HOST>
python <KIT>/scripts/studio.py blender inspect --project <GAME> --source assets/asset.glb --output artifacts/asset-roundtrip.json --config <HOST>
```

For a bake, export, mesh-repair or measurement script the game project owns, `studio blender run` executes it headlessly inside a declared `.blend`:

```text
python <KIT>/scripts/studio.py blender run --project <GAME> --source source/asset.blend --script tools/rebake_normals.py --label arch-normal --result artifacts/bakes/arch_normal.png --config <HOST> -- --samples 8
```

It runs `blender --background --factory-startup <source> --python-exit-code 1 --python <script> -- <arguments>`, waits (default 600 seconds, maximum 3600 with `--timeout`) and writes `artifacts/blender/runs/<label>/` holding `run.json`, `process/process.json` and the combined `process/stdout.log`. `run.json` records the Blender executable, the source and script hashes, how many arguments followed `--` (never their values), the return code, the elapsed time, whether the run timed out, and each declared `--result` as it was before the run and after it. A result whose bytes are unchanged since before the run is reported as stale rather than produced, so yesterday's bake cannot pass for today's; a declared result that already exists but cannot be read is refused before launch, because there would be no baseline to compare against. Blender runs the script where the project keeps it, so a script that resolves its siblings through `__file__` finds them, and the working directory is the project as well. The script is hashed before the run and again after it: a script that changed while it ran is recorded as both hashes and is not `ok`. The Blender executable is re-read immediately before the process starts, and a run whose executable changed after its identity was recorded is refused with a receipt instead of started. Anything the script leaves running after Blender exits is stopped before any result is hashed and recorded in `survivors`; a run that left a process behind or whose process tree could not be enumerated is not `ok`. A declared result that has become a symlink into the run's own directory, or that no longer resolves inside the project, is reported invalid rather than produced. An interrupted run still writes its receipt before the interrupt continues. `ok` means the script exited zero and produced every declared result; it is not visual acceptance. Shared options (`--config`, `--project`, `--source`, `--output` and the render options) may be given before or after the operation name; the one after it wins. The script starts with the game project as its working directory, so a relative path it writes lands in the project and can be the `--result` the command checks for. A repeated `--label` is refused instead of overwriting the earlier run, and a `--result` inside the run's own directory is refused because this command writes those files itself. Do not hand-roll a Python wrapper around `processes.run` for this; it produces no receipt anyone can read afterwards.

## `run` or the interactive MCP

Use `run` when the work is a script: baking, exporting, repairing, measuring or batch-editing a file that already exists, in an unattended process that must leave evidence and be repeatable tomorrow. Use the optional native-Windows [MCP lifecycle](references/mcp.md) only when the decision needs an interactive session on an open scene — looking at a viewport, trying something and judging it. The MCP route needs a matched addon/server pair, a supervised host and a connected app client; `run` needs a Blender executable in the host config.

## Qualify before collision or rig

`blender inspect` reports, for every mesh object, `triangles`, `boundary_edges`, `nonmanifold_edges`, `inconsistent_winding_edges`, `nonmanifold_vertices`, `degenerate_faces` and `uv_layers`, and a top-level `topology` carrying those totals and `clean`. The vertex count is not redundant: two closed shells that meet at a single welded vertex have no boundary edge and no edge shared by three faces, so every edge count calls them clean while the surface still cannot be rigged, unwrapped or given collision there. A zero-area triangle passes every count the same way and has no normal to bake against, so `degenerate_faces` counts those too, with a tolerance relative to the mesh's own bounding box. Vertices are welded by position for the count only: duplicated texture-seam vertices are a correct part of an exported mesh and would otherwise read as thousands of holes. Nothing is modified by inspecting. On a Blender build without numpy, `topology` is `{"status": "unavailable", ...}` and the three edge counts are `null` — unmeasured, never assumed clean.

The loop before anything is rigged, baked or given collision is: inspect, reduce if it is too dense, inspect again.

```text
python <KIT>/scripts/studio.py blender reduce --project <GAME> --source source/tree-original.blend --target-triangles 300000 --output source/tree-300k.blend --label tree-300k --config <HOST>
```

It opens the `.blend` or imports the `.glb`, applies whatever modifier stack each selected object already carried (recorded as `applied_modifiers`, so what is measured is what is saved), welds coincident vertices at 1e-7, then applies Decimate (collapse, triangulate) at `target / current triangles` to each mesh object, skipping any object already at or below the target; `--object NAME` reduces one object instead of all of them. `--output` is a `.blend` that must not already exist, so the intact original is never the file a reduction overwrites. `artifacts/blender/reduce/<label>/reduce.json` holds the Blender and source hashes, the audit before and after per object and in total, the target, the achieved ratio and `ok`. `ok` is true only when the source audit was clean **and** the saved mesh still is **and** every object ended at or under the requested budget with at least one triangle; a reduction cannot qualify a mesh that arrived defective, a mesh with no triangles reports zero of every defect without having been qualified, and `reason` names which of those failed. The source is hashed before launch and again afterwards: a source that changed or became unreadable during the run is `ok: false` carrying both digests, and the receipt is still written. Objects appear in the receipt as an `index` and a `name_sha256`, never as the name you passed to `--object`, and every mesh in the file is reduced rather than only the ones the active scene links, with the file's `scenes` count recorded. `--output` is claimed with a single exclusive create before Blender starts, so two reductions cannot both write one file; the second is refused, and a claim nothing was saved to is released. An interrupt still writes the receipt before it continues, and the Blender executable is hashed before launch, re-checked before the process starts and again after it exits. `--target-triangles`, `--object` and `--label` are this operation's own; the shared options may be given before or after `reduce` exactly as they may for `run`, and the one after it wins.

Nothing in this path repairs. Holes are never filled and openings are never closed, because an intentional walk-through gap and a defect are the same thing to the arithmetic and different things to the person who modelled it. Both are counted as boundary edges and left alone.

Collision is a separate simplified surface aligned to the load-bearing parts — trunk and roots for a tree — authored or reduced on its own. It is never the render mesh, however cheap the render mesh has become, and intentional openings the player walks through stay open in it.

Author with a metric scale, declared ground/center pivot and intentional transforms. Keep cameras, lights, render helpers and unrelated collections outside the runtime collection. Include every weighted mesh, required armature and hierarchy node. The collection exporter rejects missing armature dependencies and exports NLA tracks; name and stage clips with [animation](../studio-animation/SKILL.md) first.

Keep editable `.blend` under source with `.gdignore`. Use simple Principled base color/roughness/metallic values for portable materials. Bake unsupported procedural detail to authored textures or explicitly recreate it in Godot. Name the decision in the asset record; GLB export alone does not prove shader equivalence. Texture color space, normal orientation, alpha mode and UVs need a target-engine check.

Inspect the fresh import: actual mesh/material/skin/clip counts, evaluated bounds, pivot and hierarchy. Exclude Blender bone-display custom shapes from geometry bounds. Review fixed-camera rest/stress images, multiple viewpoints and motion samples. GPU rendering is separate from finding a GPU; record the actual engine/device when tested. For fixed-camera or turntable evidence, use `blender render --source source/asset.blend --camera ReviewCamera --frames 1,13,25 --angles 0,90,180,270 --target 0,0,0.75 --output artifacts/turntable-001`. Target coordinates are Blender source-space metres; angle zero preserves the exact camera. Use a new empty evidence directory. This owned process does not save camera changes back to the source.

If structured production cannot answer a perceptual/UI question, save a checkpoint and use host-provided computer use on an owned app instance. On native Windows, the optional interactive MCP route has a packaged, receipt-owned lifecycle; read [the lifecycle recipe](references/mcp.md) before using it. It is not required to run the core fixture, and the background adapter remains independent.

Output `.blend`, GLB, metadata/hashes, roundtrip inspection and review images. Fill [asset record](../../templates/asset.json); a clean import advances exported/imported evidence, not the user's visual acceptance.

Declare generator versus edited-source authority before authoring/export. Follow [source authority and contact](../../references/source-and-contact.md) for preserving edits, explicit export, authored placement overrides and full support footprints including separate shelves. Never rerun a builder over the authoritative edited file merely to obtain a GLB.
