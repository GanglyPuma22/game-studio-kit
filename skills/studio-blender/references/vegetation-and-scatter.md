# Giant trees and ground scatter

The tree advice is adapted from `vegetation-artist/SKILL.md` in blender-skills at revision `8f778d2405a214b508d4c7d80742be8e43acdd52` (Copyright (c) 2026 blender-skills contributors; MIT; see [license](../../../third_party/blender-skills/LICENSE)) and tested in one lane: Skybreak's 88 m Tallgrove trees in a flat-colour, outlined look, rendered in Godot from a warden's views (ground, mid-swing, across the map, beside a branch). Read [outline readability](outline-readability.md) for how the comparisons were made.

## A stylized giant tree

Today's box tree (two octagon boxes per trunk section, box limbs, box leaf masses; 204 triangles) was compared with three rebuilds at the same size and branch layout:

| Variant | Triangles (LOD0 / LOD1) | Read |
|---|---|---|
| Box trunk, box leaves | 204 | blocks |
| Round trunk, box leaves | 1,331 / 740 | better trunk, leaves still crates |
| Box trunk, leaf clouds | 1,228 | better crown, trunk still a post |
| Round trunk, leaf clouds | 2,355 / 1,764 | reads as a tree from every view |

The winning build:

- **Trunk**: a 16-sided tube on a gently wandering axis, tapering where the gameplay collision steps in, a root flare (radius x1.55 at the ground, decaying over about 3 m) and five buttress roots as tapered 7-sided tubes running down and out into the ground. Painted furrows (every fourth column in a second bark slot, stepping round as it rises) instead of carved ones.
- **Branches**: tapered 8-sided tubes rising slightly with one kink, plus a short fork near the tip. Keep each limb's height and reach on its collision box.
- **Leaves**: clouds of 20-face icosahedra (flat shaded, squashed to 0.72 in height), 7 per branch tip and 11/7/3 in a stacked crown, faces turned down coloured in the darkest leaf colour. The first try (5 blobs at radius 0.24-0.36 of the clump size) looked like broccoli; the clouds need roughly the volume of the canopy they replace (radius 0.3-0.42, spread 0.36).
- **Collision** stays the simple boxes the game already had. Keep the drawn trunk within about 5% of that collision so a grapple or a footstep lands where the bark is drawn.

Alpha leaf cards, the upstream skill's default, were not used: a flat-colour, outlined material has no alpha, so each card draws as an opaque quad with an outline round it.

## LOD for low-poly foliage

Do not collapse-decimate leaf blobs that are already 20 faces: at 40% they shattered into floating shards, and model QA failed the LOD on floating parts and a 9.6% silhouette change. Rebuild LOD1 from the same seed with half the tube sides instead (1,764 triangles; 0.27% silhouette change at 200 m). Model QA's default 3 mm part match then flags rebuilt tubes as missing parts on an 88 m tree; a tolerance that scales with the model (150 mm here) left 5 thin twigs flagged, which is a fair call.

## Scatter: size before masks

Ground dressing was scattered under the trees two ways with the same clump count: plain random, and masked (density from a root-zone falloff round each trunk, noise patches for grass, and a proximity mask that keeps a path clear, combined the way Polygonflow Dash combines its height, noise, proximity and object masks).

- At 1 m clumps (700 of them, about 10k triangles) both read as speckle under 88 m trees. The masks made no visible difference.
- At four times the size (ferns about 5 m, boulders about 4 m; 260 clumps, about 3.5k triangles) the ground reads as a forest floor, and the masks add composition: ferns and rocks gather at the roots, grass comes in patches, the path stays open.
- Size the dressing against the hero objects first, then add masks. Decide drawn-only versus collision per clump type before shipping anything large enough to stand behind.
