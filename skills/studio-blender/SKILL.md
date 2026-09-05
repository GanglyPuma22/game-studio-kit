---
name: studio-blender
description: Create, inspect, render and explicitly export game asset hierarchies in Blender, keeping editable source and verifying geometry, materials and animation after GLB round trip.
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

Author with a metric scale, declared ground/center pivot and intentional transforms. Keep cameras, lights, render helpers and unrelated collections outside the runtime collection. Include every weighted mesh, required armature and hierarchy node. The collection exporter rejects missing armature dependencies and exports NLA tracks; name and stage clips with [animation](../studio-animation/SKILL.md) first.

Keep editable `.blend` under source with `.gdignore`. Use simple Principled base color/roughness/metallic values for portable materials. Bake unsupported procedural detail to authored textures or explicitly recreate it in Godot. Name the decision in the asset record; GLB export alone does not prove shader equivalence. Texture color space, normal orientation, alpha mode and UVs need a target-engine check.

Inspect the fresh import: actual mesh/material/skin/clip counts, evaluated bounds, pivot and hierarchy. Exclude Blender bone-display custom shapes from geometry bounds. Review fixed-camera rest/stress images, multiple viewpoints and motion samples. GPU rendering is separate from finding a GPU; record the actual engine/device when tested. For fixed-camera or turntable evidence, use `blender render --source source/asset.blend --camera ReviewCamera --frames 1,13,25 --angles 0,90,180,270 --target 0,0,0.75 --output artifacts/turntable-001`. Target coordinates are Blender source-space metres; angle zero preserves the exact camera. Use a new empty evidence directory. This owned process does not save camera changes back to the source.

If structured production cannot answer a perceptual/UI question, save a checkpoint and use host-provided computer use on an owned app instance. For optional interactive MCP read [the pinned connection recipe](references/mcp.md). It is not required to run the core fixture.

Output `.blend`, GLB, metadata/hashes, roundtrip inspection and review images. Fill [asset record](../../templates/asset.json); a clean import advances exported/imported evidence, not the user's visual acceptance.

Declare generator versus edited-source authority before authoring/export. Follow [source authority and contact](../../references/source-and-contact.md) for preserving edits, explicit export, authored placement overrides and full support footprints including separate shelves. Never rerun a builder over the authoritative edited file merely to obtain a GLB.
