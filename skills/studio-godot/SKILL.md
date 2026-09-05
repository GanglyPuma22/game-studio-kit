---
name: studio-godot
description: Import explicit game assets into Godot, recreate materials, wire bounded player interaction, animation and audio, and build a reviewable runtime candidate.
---

# Studio Godot

Inputs: engine-pinned project or new work card, source/runtime asset records, animation/audio event tables and target settings. Preserve existing gameplay interfaces; broad physics/engine migrations are separate tasks. Output a runnable scene, recipe and candidate identity with import/behavior evidence.

Use [portability](../../references/portability.md) for the absolute helper route. The original Godot 4.5.1 standard example can be generated with `fixture --project <empty GAME>` or copied from [harbor-pocket](../../examples/harbor-pocket/README.md). It includes a walkable area, 1.8 m marker, rigged bell, heightfield mound and E-triggered response/cue.

```text
python <KIT>/scripts/studio.py godot import --project <GAME> --config <HOST>
python <KIT>/scripts/studio.py godot smoke --project <GAME> --config <HOST>
python <KIT>/scripts/studio.py godot run --project <GAME> --config <HOST>
```

The `run` helper owns a bounded process (host timeout); a longer manual editor/play session can be launched by the host with its own ownership record. To export, first configure a real project preset and install the matching export templates, then use `godot export --preset <name> --output <relative build path>`. The studio does not invent credentials, export presets or target SDKs.

Prefer explicit GLB interchange and retain `.blend` under ignored source. Inspect mesh/skin/clip identity after import. Map Principled base color to StandardMaterial3D albedo, roughness/metallic to matching properties, baked normal with correct orientation and alpha to intentional transparency/cutout. Blender node networks require bake/recreation; compare runtime lighting visually. See [material notes](references/materials.md).

Set imported idle looping and response non-looping explicitly. Make one gameplay action own state; transition animation with a bounded blend and trigger its cue once. Verify repeated input/cooldown, walk-away/reset and collision at player scale. The fixture's technical smoke shares action names and verifies movement, pose changes, response count, audio-player start and return to idle. It uses injected actions and headless audio; it is not ordinary-input or listening evidence.

Create the content-identified candidate after final changes, then pass the ordinary route, settings and captures to [review](../studio-review/SKILL.md). Inspect appearance, motion, sound and frame behavior independently. A headless launch alone does not pass any artistic or target-native acceptance claim.
