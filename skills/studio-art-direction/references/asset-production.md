# Asset families and handoff

Adapted from `create-game-assets/SKILL.md` in awesome-gamedev-agent-skills at revision `7110607ab816ece9669274bc84937857a8819796`. Copyright 2026 Abhishek Barali and contributors; Apache-2.0. See [license](../../../third_party/gamedev-skills/LICENSE) and [NOTICE](../../../third_party/gamedev-skills/NOTICE).

Write an asset brief before generating a family: gameplay role, theme, silhouette, dimensions, palette, material treatment, camera distance, expected animation/collision and export target. Prototype one representative asset and inspect it inside the game before expanding the set. Consistency needs an explicit family contract and a comparison at actual play scale.

Keep source files, runtime exports and a manifest together. Name each variant deliberately, retain provenance, and record dimensions/pivot/material/texture expectations. Check that the engine imported the file, uses the intended material treatment and presents a readable silhouette under scene lighting. An attractive generation is an input to that process.

Studio adaptation: broad tool/engine routers, image-generation command assumptions and external skill links have been removed. The local [art-direction entrypoint](../SKILL.md), [asset template](../../../templates/asset.json), [Blender route](../../studio-blender/SKILL.md) and [Godot route](../../studio-godot/SKILL.md) are the complete reference closure. No upstream script is required at runtime.
