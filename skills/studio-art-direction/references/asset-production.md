# Asset families and handoff

Adapted from `create-game-assets/SKILL.md` in awesome-gamedev-agent-skills at revision `7110607ab816ece9669274bc84937857a8819796`. Copyright 2026 Abhishek Barali and contributors; Apache-2.0. See [license](../../../third_party/gamedev-skills/LICENSE) and [NOTICE](../../../third_party/gamedev-skills/NOTICE).

Write an asset brief before generating a family: gameplay role, theme, silhouette, dimensions, palette, material treatment, camera distance, expected animation/collision and export target. Prototype one representative asset and inspect it inside the game before expanding the set. Consistency needs an explicit family contract and a comparison at actual play scale.

Keep source files, runtime exports and a manifest together. Name each variant deliberately, retain provenance, and record dimensions/pivot/material/texture expectations. Check that the engine imported the file, uses the intended material treatment and presents a readable silhouette under scene lighting. An attractive generation is an input to that process.

Studio adaptation: broad tool/engine routers, image-generation command assumptions and external skill links have been removed. The local [art-direction entrypoint](../SKILL.md), [asset template](../../../templates/asset.json), [Blender route](../../studio-blender/SKILL.md) and [Godot route](../../studio-godot/SKILL.md) are the complete reference closure. No upstream script is required at runtime.

## The decision before expansion

Build one representative of each distinct family, not a collection of variants. Compare reference and candidate at both close and normal play scale using named camera/FOV, lighting and exact source/export identities. Record the visible difference, chosen correction, deliberate simplifications, and whether the remaining uncertainty permits replication. Include comparison capture hashes and the source owner in the existing asset/work record. A successful export or number of variants cannot substitute for this decision.

In an authorized unattended run, make a provisional choice and explain it; do not invent a required user gate. If the specimen still fails its intended silhouette/material reading, correct that specimen before expanding. Retain the chosen editable source, parameter ranges and authored overrides when multiplying it. A terrain change invalidates earlier contact evidence: use [complete support contact](../../../references/source-and-contact.md).

Worked original example: a porous sea plant reads as a solid paddle at the play camera. Compare one branched specimen with one perforated specimen in the same light; choose branching if its gaps survive that view, retain broad color bands, and defer tiny pores. Record that rationale and the two captures before producing size variants. This is an illustrative decision, not measured artistic acceptance.

Worked-decision method: [Kate Compton, So you want to build a generator](https://www.galaxykate.com/blog/generator.html). The sea-plant example is an original proposed application, not observed artistic validation.
