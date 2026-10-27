# Prop brief, silhouette tiers and colliders

Adapted from `blender-director/SKILL.md`, `prop-artist/SKILL.md`, `references/asset-pipeline.md`, `references/reference-image-match.md` and `collision-proxy/references/collider-recipes.md` in blender-skills at revision `8f778d2405a214b508d4c7d80742be8e43acdd52`. Copyright (c) 2026 blender-skills contributors; MIT. See [license](../../../third_party/blender-skills/LICENSE).

Studio adaptation: the upstream skills drive a live Blender over MCP and route between 94 specialist skills; that routing, the MCP execution plan, engine-specific naming (UCX/UHX, `MAT_` prefixes) and the AAA polycount tables are not included. What is kept is the order of decisions before geometry and the review loop. The [Blender route](../SKILL.md), [game-asset pitfalls](game-asset-pitfalls.md), [model QA](../../studio-model-qa/SKILL.md) and the [asset family decision](../../studio-art-direction/references/asset-production.md) are the complete reference closure.

## Write the brief before any geometry

Fill this in the builder script's docstring (or the asset record) so the next session can read why the shape is what it is:

- **Type and role**: prop / environment / character part, and what the player does with it (cover, perch, landmark).
- **Scale**: real-world sizes against a 1.8 m figure (a mooring pile 0.4 m round, a bollard 0.5 m tall). Fix scale before any detail.
- **Shape language**: one sentence on what the silhouette says and which shape carries it (a square base reads stable, triangle teeth on a rim read broken or felled). Exaggerate the one feature that names the object at play distance.
- **Part logic**: which parts are separate shapes because their material, motion or LOD differs.
- **Wear hierarchy**: where contact and weather show (dark wet band at a water line, pale sun-bleached top), carried by colour slots rather than micro-geometry when the game draws flat colour.
- **Budget**: the project's own comparable assets, not a generic table. One test lane's props ranged 284-1,128 triangles; a blender-skills "standard prop 500-2k" row was too loose for that game.
- **Pivot**: ground contact, grip or hinge.
- **Tiers** (below), **collider recipe** (below) and **LOD plan**.

## Build in silhouette tiers

1. **Silhouette**: the largest readable forms only. Review from four angles at play distance before anything else.
2. **Breaks**: the forms that stop it reading as a box or a cylinder: buttresses merged into a trunk, a crown of staggered pile tops, lashings, a valance. These are what a distant player sees as "detail".
3. **Small features**: only what survives at the closest gameplay camera. In a flat-colour, outlined style this tier is often empty; an outline shell already draws the edges a bevel would.

Fix tier 1 before starting tier 2. A test lane's first pass of a stump flared the roots into a skirt and the dolphin's fender beams stuck out like arms; both were tier-1 problems that showed only in the four-view render.

## Screenshot gap loop

After each tier, render the exported file (not the source scene) from fixed views in the game's own look, write a short gap list (what reads wrong and the one change for each), apply it and render again. Stop at three passes or when the gap list is empty. A checklist without a render did not find a single defect that [model QA](../../studio-model-qa/SKILL.md) later caught; run model QA after the loop, not instead of it.

## Collider recipes

Build collision as separate simple shapes, never the render mesh:

| Asset | Recipe |
|---|---|
| Crate, booth, wall | 1 box |
| Trunk, pile cluster | 1 convex hull, plus a low box on each part a character stands on |
| Chair, table | top box plus leg boxes |
| Character | capsule |
| Stairs | box per step or one ramp |
| Vehicle | 3-8 convex pieces |

Inset a collider slightly from the render mesh where snagging is a problem, and keep every opening the player walks through open.

## Assemblies that pass model QA

Props built from overlapping closed parts (piles through a cap, a lashing sunk into timber) clip and float by construction. Two moves made every such test asset pass:

- **Union the closed parts** into one shell (Exact boolean, self intersection, hole tolerant), then merge the coplanar slivers it leaves with a 1-degree limited dissolve delimited by material. Do not union an open shell (a trunk with no bottom face split into ten loose pieces).
- **Two LODs for small props.** Collapse-decimating the unioned shell to 50-75% kept every part; a 25% third level failed the LOD silhouette check on missing parts at the distance where the prop is a few pixels. See [one plan, every LOD](game-asset-pitfalls.md#separate-parts-clipping-and-floating) for multi-part assets that cannot be unioned.
