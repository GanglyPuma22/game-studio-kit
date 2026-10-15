# Game-asset pitfalls seen in real lanes

Each item cost at least one review round in a production pilot. Check for them before a critic run, not after.

## Reduction and LODs

- **Weld before decimating.** glTF import splits vertices at every UV seam. Decimating an unwelded import opens a crack along each seam (one creature went from 0 to 6,874 boundary edges) and can shatter a shell into hundreds of loose pieces. `blender reduce` welds first; a hand-written decimation must too. Compare boundary edges (`blender inspect`) and loose-part counts before and after every reduction. `blender inspect` does not count loose parts yet; on a copy of the mesh, run `bpy.ops.mesh.separate(type='LOOSE')` in Edit Mode and count the resulting objects.
- **Per-part budgets with a floor.** A whole-mesh Decimate on a multi-part asset collapses its small parts to single triangles at the coarse levels. Reduce each loose part on its own share, with a minimum (about 14-20 triangles for a small rock).
- **Vertex-group protection does not protect.** Decimate with a vertex group never collapses weight-0 vertices, so "protect the face" can leave the mesh far over budget. Reduce in two passes: the protected share first, then the rest with the group inverted.
- **Chain LODs from the previous level** and keep skin weights and the armature modifier order when the mesh is skinned. Record every level's triangle count in one receipt.
- **Dense small plants** (cushions, mosses, lichens) usually pass faster as dense detail baked onto a simple low mesh than as hand-modelled tubes; tube or stem plants under about 2k triangles often fail at distance without a card.

## Baking and textures

- **Image rows vs UV rows.** Row 0 of a PIL or numpy array is the top of the image; UV v = 0 in Blender and glTF is the bottom. Flip rows when saving a painted texture, and flip the height before deriving a normal map, not the normal map itself. Check with a UV test pattern render.
- **Bake cage misses** leave black specks, garbled normal texels or smeared triangular patches on deep partings. Bake a ray-miss mask, or count near-black texels inside UV islands, and widen the cage where it misses.
- **Atlas format.** Some Blender glTF exporters ignore a JPEG export setting for generated (packed) images and embed PNG, which can make a GLB several times its budget. Check the exported file size against a budget and re-encode opaque atlases if needed.
- **Far cards and colour.** A flat-lit albedo bake for a crossed-plane card multiplies small saturated parts (each plane shows them). Compare mean hue and saturation per dominant colour group between the model and its card, not one global brightness factor.

## Export and review

- **Render from the exported file.** Procedural shader nodes (noise, waves) export to glTF as a flat colour. Review renders made from the source `.blend` show detail the game never draws; re-import the GLB and render that.
- **Hide what the game hides.** Collision proxies and helper meshes exported with the asset render white or z-fight in a raw viewer and raise false defects. Strip or hide them before capture.
- **Save with blend-relative paths** and copy reference originals into the work tree. Textures saved relative to the working directory load magenta from elsewhere, and a branch switch can delete originals a build step imports mid-run.
- **Grazing Fresnel.** Principled BSDF keeps a strong grazing reflection even at a very low specular level, so dark materials can render silver at a low sun. When a look problem resists two changes, render a one-variable A/B (specular off, base colour only, backface culling on) to find the lever.
- **Translucent colour.** On alpha-blended parts, opacity, emission and specular set the rendered colour more than albedo does. Report the material values next to any measured colour.
- **Diff geometry between rounds.** A scripted one-line edit can silently drop a part. Diff the new GLB against the previous round per mesh and list which parts moved before the critic sees it.

## Skinned meshes and clearance

- **Intended embeds are not clipping.** Fins, wing roots and leg sockets sit inside the body by design and produce hundreds of overlapping triangle pairs at rest. Measure clearance against a rest-pose baseline, list intended embeds (part pairs or vertex groups), count a part's faces that newly touch the body per clip frame, and attach x-ray stills of the joins.
- **Vertices outside is not enough.** A vertex can sit outside the body while its triangle still cuts the skin; re-check with a BVH after any push-out fix. Lifting attached-part root vertices a few millimetres off the decimated skin is a cheap standard step.

## Headless Blender in containers

Some cloud containers have Blender only as the pip `bpy` module, with no `blender` executable. The kit's `blender` commands need an executable that accepts `--background ... --python <script> -- <args>`; until the kit ships a module route, a small shim script that parses those arguments and runs the script under the module's Python lets them run unchanged. Record that the shim was used in the work card.
