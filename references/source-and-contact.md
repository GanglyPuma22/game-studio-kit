# Source authority and complete support contact

Before an operation, name the authoritative artifact and its owner in the asset/work record. A generator owns reproducible starting geometry; a hand-edited `.blend` owns subsequent manual changes unless explicitly reconciled back into parameters. `blender export` loads that edited file and exports the named runtime collection without running a generator or saving the source. Record source hash before/after and the fresh GLB hash. A generator change is a separate operation into a new source path followed by a diff/merge decision; never regenerate over an authoritative edited file.

Keep authored transforms in a small project-owned placement/override table (asset instance ID, position, rotation, scale, reason, substrate identity). A builder must reapply these overrides after defaults, or explicitly transfer authority to the edited scene. Export, reimport, and inspect at least one manual change plus hierarchy/pivots/materials/clips. Source bytes unchanged proves preservation, not visual equivalence.

## Worked contact check

A four-pad lander stands on a base terrain mesh, while a separate raised shelf crosses the edge of pad B. A center-height query against the base misses it. For every pad, transform its complete sole polygon and underside into final world space. Include the actual final base, shelves, rocks and any other support geometry, not just the terrain generator's height function.

Use triangle/solid intersection against the entire support volume to detect penetration. For support coverage, intersect the projected sole polygon with each substrate triangle and evaluate height differences over overlap vertices/edges; for planar triangles extrema occur there. Include interior vertices where terrain triangles cross the footprint. Ray grids alone can miss thin shelves; if used for screening, report spacing and uncertainty, then inspect exact overlaps. Meshes with overhangs need full 3D intersections rather than a single-valued height map.

For each pad record substrate hashes, world transform, tolerance, maximum penetration, maximum gap, supported area and unresolved intersections. Adjust the authored transform or geometry; do not hide an intersection with a center-only offset. Check strut-to-pad and strut-to-hull joins after moving supports. Render multiple native angles and a normal play view; rerun after any substrate or transform edit. Example acceptance: no sole penetrates more than the declared 2 mm tolerance and intended load-bearing areas contact within that tolerance. Choose tolerance for the asset, not as a universal constant.

A reusable adversarial case is a flat pad over a flat base with a thin separate shelf under one corner. The test must report that intersection while the center probe remains unchanged; remove the shelf and it must clear. This guide does not claim an automatic geometry checker is implemented.
