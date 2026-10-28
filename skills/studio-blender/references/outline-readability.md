# Detail that reads in a flat-colour, outlined look

Measured in one test lane (Skybreak, 2026-10-28): flat colour per material slot or per vertex colour, a hard light/shadow step, and an inverted-hull outline pushed out along vertex normals. Results will differ for a painterly or physically based look; the method transfers.

## Measure at play distance, at true pixel size

A detail is worth its triangles only if a player can see it. Judge it the way the player sees it, not in a close Blender viewport:

1. Build the variants as separate GLBs from one script: the same base shape, each with one detail, and the triangle count of each.
2. Load them in the engine with the game's own materials, sun and field of view, at the resolution players run (here 1920x1080, 75 degree vertical view).
3. Render each variant from the distances it is actually seen at (props 10, 30 and 80 m; a character 3, 8 and 20 m) and crop around its projected bounds at native pixels. If the window is scaled, convert the projected bounds by image size over visible-rect size, or the crop misses the object.
4. Compare side by side with far crops enlarged by whole numbers with nearest-neighbour scaling, so each screen pixel stays a square.
5. Put the detail on the face the camera sees. Blender's +Y is the engine's -Z after a Y-up glTF export, so a "front" face picked by +Y normal faces away from a camera standing at +Z. One test's first verdict on an inset panel came from the hidden face.

## Map prop results (4 x 3 x 1.5 m stone block)

| Detail | Triangles | 10 m | 30 m | 80 m | Verdict |
|---|---|---|---|---|---|
| Plain box | 12 | | | | baseline |
| Colour band in a darker slot (two edge loops) | 36 | yes | yes | yes | use |
| Rim or plinth 10 cm proud | 60 | yes | yes | yes | use |
| Grooves 6 cm wide, 5 cm deep | 76 | strong | strong | faint | use |
| Darker base course and underside | 20 | yes | yes | faint | use near the ground |
| World-projected lines texture (stone blocks) | 12 | yes | speckle | gone | near only |
| Inset panel 8 cm | 20 | no | no | no | skip |
| Chamfer 12 cm, 1 or 2 segments | 44 / 108 | noisy | noisy | noisy | skip |

The inset is lit and coloured like the face around it and carries no outline, so nothing marks it. The chamfer turns every corner into slivers: the outline shell breaks into dashes along the bevel and the narrow faces flash lighter or darker than their neighbours. Keep corners hard; spend the triangles on proud parts and colour.

## Character trim results (1.8 m figure, coat hem and cuffs)

| Detail | Extra triangles | 3 m | 8 m | 20 m | Verdict |
|---|---|---|---|---|---|
| Painted team-colour band | +48 | yes | yes | yes | use |
| Painted dark seams and dark hem | +48 | yes | yes | hem only | use |
| Painted stitching dashes | +96 | yes | faint | gone | close-ups only |
| Painted wear patches | +144 | glitchy | glitchy | | skip |
| Bevelled, flared hem 1.5 cm | +144 | barely | no | no | skip |
| Raised hem band 1.5 cm, hard edged | +144 | thin line | no | no | skip |

Painted colour is not free: a colour change needs an edge there, so each band costs its edge loops. Wear patches at the resolution of a 24-sided coat read as square glitches, not wear. Small hard-edged steps also crack the outline (dark specks at hem and cuffs), because split normals push the hull apart at the crease. On characters, trim is colour; spend triangles on silhouette (collars, straps and pouches that stand out).

## Shading the outline will not crack

Smooth-shade round forms (trunks, limbs, cloth tubes) so the outline hull stays continuous. Hard-edge only large flat faces, where the crack hides inside the silhouette.

## Vertex colours through glTF

Blender's glTF exporter with `export_vertex_color='ACTIVE'` writes the colour attribute set as the render colour (`mesh.color_attributes.render_color_index`), not merely the active one. A mesh whose attribute was created from bmesh has neither set and exports with no `COLOR_0`. Set both, and check the exported primitive for `COLOR_0` before rendering anything. Use a float, face-corner attribute so a band has a hard edge.
