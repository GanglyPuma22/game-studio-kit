---
name: studio-blender
description: Create, inspect, render and explicitly export game asset hierarchies in Blender, run a bake or export script headlessly with `studio blender run`, keeping editable source and verifying geometry, materials and animation after GLB round trip.
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

It runs `blender --background --factory-startup <source> --python-exit-code 1 --python <script> -- <arguments>`, waits (default 600 seconds, maximum 3600 with `--timeout`) and writes `artifacts/blender/runs/<label>/` holding `run.json`, `process/process.json` and the combined `process/stdout.log`. `run.json` records the Blender executable, the source and script hashes, how many arguments followed `--` (never their values), the return code, the elapsed time, whether the run timed out and whether each declared `--result` now exists. `ok` means the script exited zero and produced every declared result; it is not visual acceptance. A repeated `--label` is refused instead of overwriting the earlier run, and a `--result` inside the run's own directory is refused because this command writes those files itself. Do not hand-roll a Python wrapper around `processes.run` for this; it produces no receipt anyone can read afterwards.

## `run` or the interactive MCP

Use `run` when the work is a script: baking, exporting, repairing, measuring or batch-editing a file that already exists, in an unattended process that must leave evidence and be repeatable tomorrow. Use the optional native-Windows [MCP lifecycle](references/mcp.md) only when the decision needs an interactive session on an open scene — looking at a viewport, trying something and judging it. The MCP route needs a matched addon/server pair, a supervised host and a connected app client; `run` needs a Blender executable in the host config.

Author with a metric scale, declared ground/center pivot and intentional transforms. Keep cameras, lights, render helpers and unrelated collections outside the runtime collection. Include every weighted mesh, required armature and hierarchy node. The collection exporter rejects missing armature dependencies and exports NLA tracks; name and stage clips with [animation](../studio-animation/SKILL.md) first.

Keep editable `.blend` under source with `.gdignore`. Use simple Principled base color/roughness/metallic values for portable materials. Bake unsupported procedural detail to authored textures or explicitly recreate it in Godot. Name the decision in the asset record; GLB export alone does not prove shader equivalence. Texture color space, normal orientation, alpha mode and UVs need a target-engine check.

Inspect the fresh import: actual mesh/material/skin/clip counts, evaluated bounds, pivot and hierarchy. Exclude Blender bone-display custom shapes from geometry bounds. Review fixed-camera rest/stress images, multiple viewpoints and motion samples. GPU rendering is separate from finding a GPU; record the actual engine/device when tested. For fixed-camera or turntable evidence, use `blender render --source source/asset.blend --camera ReviewCamera --frames 1,13,25 --angles 0,90,180,270 --target 0,0,0.75 --output artifacts/turntable-001`. Target coordinates are Blender source-space metres; angle zero preserves the exact camera. Use a new empty evidence directory. This owned process does not save camera changes back to the source.

If structured production cannot answer a perceptual/UI question, save a checkpoint and use host-provided computer use on an owned app instance. On native Windows, the optional interactive MCP route has a packaged, receipt-owned lifecycle; read [the lifecycle recipe](references/mcp.md) before using it. It is not required to run the core fixture, and the background adapter remains independent.

Output `.blend`, GLB, metadata/hashes, roundtrip inspection and review images. Fill [asset record](../../templates/asset.json); a clean import advances exported/imported evidence, not the user's visual acceptance.

Declare generator versus edited-source authority before authoring/export. Follow [source authority and contact](../../references/source-and-contact.md) for preserving edits, explicit export, authored placement overrides and full support footprints including separate shelves. Never rerun a builder over the authoritative edited file merely to obtain a GLB.
