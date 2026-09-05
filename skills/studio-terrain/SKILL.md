---
name: studio-terrain
description: Author a bounded terrain heightfield and dimension/mask contract, using a local procedural route or an installed-version verified Gaea graph build.
---

# Studio terrain

Inputs: playable footprint, elevation range, resolution, coordinate convention, tile/seam requirements, mask roles and the scene's walking constraints. Prefer the local heightfield route for a functional test or a small authored surface. Output editable/source data, height/masks/mesh, dimensions and runtime seam/scale evidence.

```text
python <KIT>/scripts/studio.py terrain --project <GAME> --output source/terrain --width 12 --depth 12 --elevation 0.7 --resolution 33
```

The original local helper writes 16-bit big-endian PGM, an 8-bit shore mask and Y-up OBJ. Its record names footprint, elevation, origin, row direction and single-tile layout. Flat boundaries support a deterministic seam check; they are not a rich landscape. Validate the record and mesh, then inspect collision, walking slopes and seams under ordinary camera in [Godot](../studio-godot/SKILL.md).

For Gaea read [the installed-version recipe](references/gaea.md). Start with a graph which already builds in the native UI. Expose only declared variables, verify the exact executable/arguments for the installed version and entitlement, and hash the graph. The helper launches that verified argument array into a new empty output directory and checks expected files. It does not invent `.terrain` schema or claim a comprehensive graph-authoring API.

Native graph authoring uses the host's real computer-use tools, one desktop owner and an editable checkpoint. Record bit depth, export range, tile layout, coordinate axes and mask semantics explicitly; inspect adjacent borders numerically and in-engine. Gaea success does not certify dimensions, collision or scene composition. If the installation/entitlement is missing, retain the local route and provide the exact setup/native handoff.
