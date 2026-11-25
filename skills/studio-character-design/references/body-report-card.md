# Body report card: a body that fails is replaced before it is rigged

A generated, found or hand-built body gets one pass or fail card before any skinning, paint or owner review. A fault on this card cannot be fixed later by weights, shaders or animation; it can only be worked around, every round, for the life of the character. Regenerating costs one generation. The pilot's body was the first one its game generated: made in the concept's stance with the arms down, a hanging mane fused into the body and an automatic texture layout in 6,249 pieces. It was kept, and part of the later look trouble traces to those three facts.

## Rig-fit picture

Do this before spending a generation. Take the picture the generator will be given (usually a clean three-quarter view made from the approved concept) and draw the game's rig over it at the same scale.

- **Limbs apart.** Arms held away from the trunk, legs apart, fingers and claws apart from each other and from the thighs. A generator joins surfaces that touch in the picture.
- **Legs under the rig's hips.** A wide concept stance on a narrow rig puts the feet beside the rig's feet; the body then has to be bent to stand. Either the picture or the rig changes now. Which one is the owner's choice only when it changes the approved silhouette.
- **Joints where the rig bends.** Shoulders, elbows, hips and knees fall near the rig's joints. Bones are later placed on the model's own joints ([generated mesh skin](../../studio-animation/references/generated-mesh-skin.md)), so this checks reach and proportion, not exact position.
- **Hanging parts left off.** Mane, chains, cape, tail and loose ornament are removed from the picture and built as their own parts.
- **Neutral face.** Mouth closed or nearly closed unless the hinge will be rebuilt; eyes where the target sheet draws them.

A picture that fails is redrawn. This is a builder's gate; the owner sees it only when fitting the rig would change the approved shape.

## The card

Run it on the mesh the game will use, after reduction, because reduction can create the faults. Keep the generator's dense original untouched beside its hash; every repair and every later bake starts from it.

| Row | Passes when | How to measure |
|---|---|---|
| Closed surface | No open edges, no edge shared by three faces, no inside-out or zero-volume pieces beyond the ones listed as intended | `studio blender inspect` on the reduced file ([studio-blender](../../studio-blender/SKILL.md)) |
| Triangle budget | Inside the game's budget for its class | `inspect`; reduce from the dense original with `studio blender reduce`, never a second paid remesh |
| Limbs separate | After welding by position, no limb shares surface with another limb or with the trunk outside its own joint | Automatic weights on the welded copy, then count vertices carrying weight from two limbs that are not neighbours; list where they are |
| Stance fits the rig | Feet land on the rig's feet and hands reach the rig's hands with every joint inside its range at rest | Rest pose overlaid on the rig; the joint ranges of the [move check](../../studio-animation/references/move-check.md) |
| Hanging parts absent | The body file holds no mane, chain, cape or tail geometry; every loose shell has a named owner | Connected components with their sizes ([generated mesh skin](../../studio-animation/references/generated-mesh-skin.md), step 2) |
| Shape matches the concept | Silhouette, proportions and the features the target sheet marks are present from front, side and back | Grey renders beside the target sheet's three views |
| Texture layout holds paint | Only when the target sheet names a painted texture. A line drawn across the chest stays one line, and a texel at the closest view is no larger than the thinnest mark on the target sheet | `uv_layout` from `studio blender inspect` (islands, map used, surface per unit of map), plus a test line and a checker baked through the layout and rendered at the closest view ([texture layout](../../studio-blender/references/texture-layout.md)) |

Reference points for the last row, from two bodies in one game: a generator's own layout had 722 islands using 57% of the map; a weld-and-collapse reduction of another body that kept the generator's coordinates used 53%; a remesh service's new automatic layout of the first body had 6,249 islands using 17%, and drawn lines broke at the island borders. Laying the same two bodies out again took about two minutes of machine time each and no spend: charts cut by strongest bone and facing side, small charts merged into the neighbour with the longest shared border unless it faces the other way, then Blender's angle-based unwrap, equal island scale and a pack. The second body went from 3,879 islands at 27% of the map to 100 at 43%, and the first from 6,411 at 14% to 610 at 40%. Of those 610, 552 were the fused mane alone, which is the hanging parts row showing up in the layout. Blender's Smart UV Project left 1,600 to 4,100 islands on the same mesh and xatlas 741, so neither replaces cutting by part. The same baked lines drew dashed and broken on the old layout and continuous on the new one at the closest view, and identical at fighting distance.

`studio blender inspect` reports these numbers as `uv_layout`, and the [relayout template](../../../templates/texture-relayout.py) does the cut, unwrap and pack; [texture layout](../../studio-blender/references/texture-layout.md) has the procedure and the checks.

Flat paint and shader detail skip the last row. That is the only saving they bring to the body; the other rows apply to every method.

## Fail means replace or repair now

- **Fused limbs, wrong stance, hanging parts in the mesh:** redraw the picture and regenerate. A regeneration changes proportions and colour, so check the shape row again.
- **Open edges and scraps from reduction:** reduce again from the dense original a different way (weld, then collapse) before trying to patch holes.
- **Texture layout:** lay the reduced mesh out again with the [relayout template](../../../templates/texture-relayout.py), which cuts by body part and facing side, then carry colour across from the old layout or bake it from the dense original. Move a seam by hand only where it crosses something the target sheet draws. This is done once, and before the look bench.
- **A narrow fused patch on an otherwise good body:** tear and cap it ([limits](../../studio-animation/references/generated-mesh-skin.md#limits)), and say on the card that the row passes by repair.

Budget three generations inside the approved cap. A fourth needs the owner, with the three cards side by side. Record the card as the `model` stage's check evidence in the run record; a body with a failing row does not reach `model_qa`.

## Checklist

- [ ] Rig drawn over the generation picture; limbs apart, legs under the hips, hanging parts off
- [ ] Dense original archived with its hash
- [ ] Card run on the reduced mesh
- [ ] Every row passes, or the body was regenerated or repaired
- [ ] Texture layout row run when the paint method is a painted texture
- [ ] Card saved as the model stage's evidence
