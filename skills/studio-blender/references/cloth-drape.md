# Cloth drape baked to a mesh

Adapted from `cloth-sim/SKILL.md` and `cloth-sim/references/pin-and-collide.md` in blender-skills at revision `8f778d2405a214b508d4c7d80742be8e43acdd52`. Copyright (c) 2026 blender-skills contributors; MIT. See [license](../../../third_party/blender-skills/LICENSE).

Studio adaptation: the upstream skill runs the simulation in a live Blender over MCP and bakes to shape keys or caches. This route runs it headless with `studio blender run` and applies the settled frame as an ordinary mesh, which is what a real-time game ships. The settings and results below come from one test lane (a market stall canopy and a character mantle in a flat-colour, outlined style). The [Blender route](../SKILL.md), [game-asset pitfalls](game-asset-pitfalls.md) and [model QA](../../studio-model-qa/SKILL.md) are the complete reference closure.

## Where it pays and where it does not

- **Static drapes: use it.** Canvas over a frame, a tarp over crates, a hanging banner. A settled drape gives a sag and a falling edge that are slow to model by hand. A stall canopy settled in 2-15 seconds of simulation and passed model QA once unioned with its frame.
- **Skinned costume pieces: prefer a shell of the body.** A mantle draped on a character and then skinned looked best at rest and failed in motion. Draped in the bind (T) pose, the cloth over the arms folded into lumps once the arms came down. Draped in the idle pose and moved back to rest by inverse skinning, a flat ring pattern bunched into a ruff (soft) or stood out like a plate (stiff), and a longer settle slid it off the sloping shoulders. A real mantle is cut from shaped panels per body, which is tailoring, not a recipe. A shell made from the body's own surface (region kept, reduced, smoothed, pushed outside the body, thickened, given the body's weights) skinned cleanly in every clip.

## Recipe for a static drape

1. **Pattern**: a grid of even quads (about 0.2 m for a 6 m canopy), laid near its final shape (pitched over the ridge, not flat) so the simulation only settles it. Apply scale first.
2. **Pins**: pin the vertices that sit on the frame (rails and ridge, the collar ring) at full weight. Leave free only edges that can fall straight: a 1 m overhang on all four sides of a canopy crumpled into corner flaps like a sheet thrown over a table, while free eaves along the two long sides fell into a clean valance.
3. **Colliders**: a simplified copy of whatever the cloth rests on (a decimated, smoothed body; a box for crates), never the dense render mesh with fur tufts or small parts it will snag on. Collision outer thickness about 0.008 m at character scale.
4. **Settings that worked**: canvas quality 6, mass 0.4, tension and compression 40, bending 1, air 1; wool mantle (good at rest only) quality 8, mass 0.3, tension and compression 15, bending 2, air 1. Self collision off. Settle 40-60 frames, stepping every frame (`frame_set` each frame in a headless run, or the cache stays empty).
5. **Apply and reduce**: apply the cloth modifier at the last frame and remove the pin group. Reduce with a limited dissolve delimited by material (about 4 degrees), not collapse decimate: collapse ran across stripe borders and frayed them.
6. **Thickness**: solidify outward (offset +1) so the underside stays on the frame and the contact check sees the cloth touching it; give it a rim.
7. **Assemble and check**: join with the frame, union the closed parts ([asset brief](asset-brief.md#assemblies-that-pass-model-qa)), then run model QA on the exported GLB.

## Gotchas

- A mesh copied from a dressed body brings its vertex colours, which tint it in a glTF viewer and in the engine. Remove colour attributes before export.
- Assign material slots to a new mesh before writing faces into it; clearing and re-adding slots afterwards drops the per-face material index.
- Soft pin falloff is upstream's advice against creases; on a collar ring it let the cloth sag into a ruff. Pin the anchoring rings fully and soften only one ring beyond them.
