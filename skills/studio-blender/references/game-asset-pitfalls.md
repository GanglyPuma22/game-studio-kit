# Game-asset pitfalls seen in real lanes

Each item cost at least one review round in a production pilot. Check for them before a critic run, not after.

## Reduction and LODs

- **Weld before decimating.** glTF import splits vertices at every UV seam. Decimating an unwelded import opens a crack along each seam (one creature went from 0 to 6,874 boundary edges) and can shatter a shell into hundreds of loose pieces. `blender reduce` welds first; a hand-written decimation must too. Compare boundary edges (`blender inspect`) and loose-part counts before and after every reduction. `blender inspect` does not count loose parts yet; on a copy of the mesh in Edit Mode, select all (`bpy.ops.mesh.select_all(action='SELECT')`), run `bpy.ops.mesh.separate(type='LOOSE')` and count the copy plus the objects it produced.
- **Per-part budgets with a floor.** A whole-mesh Decimate on a multi-part asset collapses its small parts to single triangles at the coarse levels. Reduce each loose part on its own share, with a minimum (about 14-20 triangles for a small rock).
- **Vertex-group protection does not protect.** Decimate with a vertex group never collapses weight-0 vertices, so "protect the face" can leave the mesh far over budget. Reduce in two passes: the protected share first, then the rest with the group inverted.
- **Chain LODs from the previous level** and keep skin weights and the armature modifier order when the mesh is skinned. Record every level's triangle count in one receipt.
- **Dense small plants** (cushions, mosses, lichens) usually pass faster as dense detail baked onto a simple low mesh than as hand-modelled tubes; tube or stem plants under about 2k triangles often fail at distance without a card.

## Baking and textures

- **Image rows vs UV rows.** Row 0 of a PIL or numpy array is the top of the image. Blender puts UV (0, 0) at the lower left; glTF puts texture coordinates (0, 0) at the upper left, and the Blender glTF exporter converts between the two, so a script working in Blender UVs flips only once (image rows against Blender's v) and leaves the glTF conversion to the exporter. Flip rows when saving a painted texture from Blender UVs, and flip the height before deriving a normal map, not the normal map itself. Check with a UV test pattern render of the exported file.
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

## Separate parts: clipping and floating

Models built from many separate parts (leaves, blades, plates, grains, spines) clip and float far more than a reviewer can see in stills. Both have measured review rows ([critic loop](../../studio-review/references/critic-loop.md)); build so they pass the first time.

- **Seat roots, don't hover.** Seat each root a few millimetres into a socket, ridge or boss on its parent, never above the surface with a safety gap. Put any hinge inside the socket so folding keeps the root covered.
- **Test each piece while placing it.** Keep a BVH per placed piece (plus a box index). Build the candidate, drop only the part of it that sits inside its parent, and keep it only if it crosses nothing else; otherwise retry with a new angle or skip it. Test the candidate at every LOD level it will appear in, against that level's placed pieces. Thin sibling pieces (leaves of one stem) must test against each other, not share one ignore group.
- **One plan, every LOD.** Record pieces once and mesh each LOD from that record. Lower levels should be subsets of the same pieces, or the same pieces with fewer sides; scaling pieces up or resampling a curved stem into fewer points moves them off their parent or into each other. Keep a stem's full path at every level and drop sides instead.
- **Clean-up pass on the real export.** After building, export every LOD the way the game will load it and run both checks. Tag each piece as it is meshed so a reported part maps back to its piece, then drop the smaller piece of each clipping pair (a leaf before its stem, the later-placed piece before the earlier) and any piece left floating. Repeat until both pass. Checking a stand-in file instead of the real export lets clips through, because triangulation and welding differ.
- **Know what counts as closed.** A useful split is the share of boundary edges: closed parts (tubes, domes, grains) have few, open sheets (blades, leaves) have many. A terrain grid has few boundary edges too; treat a wide sheet spanning the model's footprint at its base as ground, which plants may sit in.

## Headless Blender in containers

Some cloud containers have Blender only as the pip `bpy` module, with no `blender` executable. The kit's `blender` commands need an executable that accepts `--background ... --python <script> -- <args>`; until the kit ships a module route, a small shim script that parses those arguments and runs the script under the module's Python lets them run unchanged. Record that the shim was used in the work card.
