# Texture layout a character can be painted on

Measured in one game (Tetherquake, 2026-11-22 and 23) on two generated giants of about 30,000 triangles each; the ice giant's relayout went into the game and its findings are marked below. A generator's or remesh service's automatic layout exists, passes every export check and still cannot hold paint: it cuts the body into thousands of scraps, so a line drawn across the chest breaks at each border and most of the map is empty. Laying the body out again is a two-minute machine step. Do it once, before anything is painted, baked or reviewed for looks.

## Measure first

`studio blender inspect` reports a `uv_layout` for every mesh object and a total:

| Field | Meaning |
|---|---|
| `islands` | Separate pieces of the layout. Two triangles are in one island when they share an edge on the surface and both ends of it sit at the same place on the map |
| `small_islands` | Islands of one or two triangles: too small to carry a mark |
| `largest_island_share` | Share of the triangles in the biggest island |
| `map_used` | Summed area of the triangles on the map. An overlapping layout reports more than it covers, and more than 1 means it overlaps |
| `outside_unit_square` | Triangles with a corner outside 0 to 1: a tiled layout, which cannot be baked to one map |
| `unmapped_triangles` | Triangles with surface but no area on the map |
| `surface_per_uv_median` | Length of surface one unit of the map covers, at the middle of the surface by area. Divide by the map width in texels for the size of one texel |
| `surface_per_uv_coarse` | The same at the ninetieth percentile: the coarse tenth of the surface |

Nothing is modified. On a Blender build without numpy, or a mesh without a layout, `uv_layout` is `null`: unmeasured, never zero islands.

What the numbers looked like:

| Body | Layout | Islands | Map used | Texel on a 2048 map |
|---|---|---|---|---|
| Rock giant | remesh service, automatic | 3,879 | 27% | 1.5 cm |
| Rock giant | relaid by part and facing | about 100 | 43% | 1.25 cm |
| Ice giant | remesh service, automatic | 6,411 | 14% | 2.7 cm |
| Ice giant | relaid, mane marked thin | 610 (body and arms 98, mane 552) | 40% | 1.6 cm |

A layout holds paint when the island count is in the low hundreds or less for a whole character, almost none of them are small, the map is around 40% used or better, and one texel at the closest view is no larger than the thinnest mark the look needs. A character whose count stays high after a relayout usually has a hanging part fused into the body; the ice giant's mane took nine tenths of its islands. Build hanging parts as their own meshes ([character design](../../studio-character-design/SKILL.md), rule 9).

## Lay it out again

Copy [the relayout template](../../../templates/texture-relayout.py) into the game's tools and run it with `studio blender run` on a `.blend` that holds the skinned body:

```text
python <KIT>/scripts/studio.py blender run --project <GAME> --source source/body.blend --script tools/texture_relayout.py --label body-relayout --result source/body-relayout.blend --result artifacts/relayout/body.json --config <HOST> -- --save source/body-relayout.blend --report artifacts/relayout/body.json --thin Mane
```

What it does:

1. Welds each mesh by position on a working copy, so the split vertices an exporter leaves along the old seams do not become new seams. The real mesh keeps its vertices, normals and weights.
2. Cuts charts by body part, by material, then by the side each face looks toward. The part is the vertex group a triangle mostly follows, or the object when the body is rigid pieces. Normals are smoothed over the surface first, so a pitted plate stays one chart.
3. Merges a chart smaller than 0.4% of the surface, or under 60 triangles, into the neighbour it shares the longest border with. It never merges onto a neighbour that faces the other way: the two halves of a closed shell would become one chart that cannot lie flat, and the unwrap answers with hundreds of one-triangle islands. It never merges across materials either, and refuses to write a chart that holds two: materials are painted by different rules, and on the ice giant one body quad inside a mane chart showed as a white diamond.
4. Unwraps along the chart borders, gives every island the same scale, and packs every chosen object into one map. The unwrap is minimum stretch where the Blender has it (4.3 and later) and angle based before; `--unwrap` forces one. Prefer minimum stretch, for the reason under the checks below.
5. Writes the result to a new layer named `relayout` and makes it the one that renders. The old layer stays, so maps can be carried across.
6. With `--carry old-map.png --carry-out new-map.png`, bakes an existing colour map from the old layout to the new one.

`--thin NAME` marks an object or vertex group made of thin blades (a mane, a cape, fins). The two sides of a blade are one face apart, so those faces keep their raw normals and their charts may stay small.

The report holds the layout numbers before and after, per object and in total, how many charts each part took, the unwrap method, and two counts against the map size given by `--size`: `thin_triangles`, narrower than half a texel at their thinnest, and `overlap_texels`, texels that lie under two faces. The first run on the rock giant took 28 seconds with the carry.

Two general tools were tried and are not a replacement: Blender's Smart UV Project left 1,600 to 4,100 islands on the rock giant at any angle limit, and xatlas left 741.

## Check before painting on it

- Bake a line and a checker through the new layout and look at them at the closest player view, in the game's renderer. The same baked lines drew dashed and broken on the old ice giant layout and continuous on the new one, and identical at fighting distance ([outline readability](outline-readability.md) for the crop method).
- Read `thin_triangles`. Angle based unwrapping flattens some triangles to nothing, mostly on spikes: 224 on the ice giant (1.3% of its surface), and a line painted next to one filled the whole triangle with ink. Minimum stretch left none there. On the rock giant it left 38 where angle based left 80; the rest are slivers on the surface itself, which no unwrap widens.
- Read `overlap_texels`. Neither method flips triangles, but a saddle still folds a chart a little: 314 texels on the ice giant with minimum stretch (0.025% of the map), and 353 on the rock giant against 2,820 with angle based. A few hundred scattered texels do not show; a block of them is a chart to cut.
- A chart stretched over a sharp ridge is cut along the ridge and unwrapped again. Smooth the dividing line first, or a pitted surface shatters into single faces. The template does not do this; the ice giant's own tool does.
- Read `surface_per_uv_coarse`. If the coarse tenth is much worse than the median, a chart was squeezed; lower `--min-share` or mark the part thin.
- Overlap: `map_used` should not change when the margin does. A layout packed by this template does not overlap, but a later hand edit can.

## Lines and other data stored in the map

Once charts are large, a map can carry more than colour: a distance to the nearest drawn line, a mask, a height. Two things found on the ice giant:

- Store a distance to a line signed, with a plain distance beside it if the line tapers. Unsigned, linear filtering rounds off the V at the line itself and the line beads.
- Do not mark the outside of a chart by pushing the value negative past its edge. That padding drew dashes along chart borders. Pad by repeating the nearest value.

## Carrying it into the game

- An exporter splits vertices along the new seams. That changes the vertex count and order of the runtime mesh, not the triangle surface, the weights or any move. Anything that indexes vertices by number (corrective shapes, per-vertex colour files, a second skin file) is rebuilt from the relaid source, not patched.
- Runtime code that takes a statistic over skin points shifts too, because the new seams split points in new places: a hinge placed at a percentile of a part's points, a cap sized by a radius over them. On the ice giant hinges moved 2 to 4 cm and one cap radius 8 cm, with identical weights at every point. Pin those values to the body, or compute them per welded place and not per stored point.
- Engines disagree on which way v runs. A map that comes out dark, garbled or mirrored after a correct bake is a v flip (`v = 1 - v`), not a layout fault.
- Fill the empty part of a painted map with the nearest paint before it is compressed, or the far mip levels pull the background colour in along every island border.
- Relay a body once, at the body stage. A relayout after paint exists means carrying every map across and checking every one again.

## What this does not decide

Whether a character needs a painted texture at all. Flat paint and shader detail need no layout; at fighting distance the three were nearly the same picture in the same test, and differed only at the closest view. That choice belongs to the character's target sheet ([paint method](../../studio-character-design/SKILL.md#paint-method)).
