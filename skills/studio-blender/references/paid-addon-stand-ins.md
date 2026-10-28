# Paid Blender addons and free stand-ins

Four paid addons were proposed for environment work. None has been bought. Each entry states the job, how its output would reach Godot, what goes wrong, the licence verdict, and what a free stand-in showed in one test lane (Skybreak, 2026-10-28; renders in a flat-colour, outlined look, method in [outline readability](outline-readability.md)).

**Licence verdict stays UNVERIFIED** until someone quotes the vendor's own clause on commercial game use for the exact tier being bought. A product page or a reseller summary is not that clause.

## True Depth (image or video to depth-displaced geometry)

- Job: blockout and relief detail from a picture; depth meshes can also feed normal or height bakes.
- Path to Godot: displaced mesh, reduced with `studio blender reduce`, exported as GLB.
- Failure modes: dense, noisy meshes; depth from a single image guesses at hidden sides.
- Licence: UNVERIFIED. Runs locally per the vendor.
- Stand-in: a local depth model (for example a small Depth-Anything) would do the same job. Not tried: it needs a model download and running its code, which needs the owner's approval first.

## Botaniq (foliage library and scattering)

- Job: dressing with ready-made plants.
- Path to Godot: export chosen plants as GLB, reduce and add LODs; scatter as instances.
- Failure modes: assets tuned for offline renders, high triangle counts and alpha cards, so not drop-in game ready. Personal and studio tiers differ.
- Licence: UNVERIFIED.
- Stand-in tried: procedural trees and masked scatter ([vegetation and scatter](vegetation-and-scatter.md)). Result: a 2.4k-triangle procedural tree beat the shipped box tree; scatter needed to be sized against the trees before masks mattered.

## One Click Damage (OCD 2.0)

- Job: procedural chips, cracks and breaks on real geometry.
- Path to Godot: apply the damage, export damaged variants as their own GLBs.
- Failure modes: the vendor warns it can ruin a model, so work on a copy.
- Licence: UNVERIFIED.
- Stand-in tried: an Exact boolean DIFFERENCE script, no addon. On a 4 x 3 m stone block at 10/30/80 m:
  - a knocked-off corner (one large low-poly sphere) with its cut faces in a darker slot, plus a few turned rubble blocks at its foot, read at every distance (88 triangles);
  - edge chips (low-poly icosphere bites, radius 0.18-0.4 m) read through the silhouette; dark cut faces make small bites on flat faces readable at 30 m (168 triangles);
  - cracks 6 cm wide and 12 cm deep, as a chain of thin boxes, read at 10-30 m and thin out at 80 m.
  Cut a chain of overlapping crack boxes one segment at a time: as one cutter, the Exact solver returned an empty mesh. Check the triangle count after every cut.
  Result: no addon needed for this look.

## Buildify (geometry-nodes buildings)

- Job: procedural buildings from footprints.
- Path to Godot: realize the geometry, export GLB with simple box collision per wall or storey.
- Failure modes: geometry nodes are built for interactive use; an agent drives a parametric script more reliably.
- Licence: UNVERIFIED.
- Stand-in: the free Building Tools addon (MIT) was not run: executing downloaded addon code needed approval first. The project's own parametric house script was extended instead. Proud floor bands (0.35 m tall, 0.25 m out) and timber posts between window bays (0.1 m proud) made small and medium houses read as half-timbered at 15-100 m for 8-21% more triangles; on a five-storey block the even grid looked like graph paper, so thin the posts out on big facades.
