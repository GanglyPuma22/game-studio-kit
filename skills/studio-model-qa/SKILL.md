---
name: studio-model-qa
description: Run attachment, clipping, LOD silhouette, triangle budget and ecology checks on exported GLB rounds before a model review upload.
---

# Model QA before review

For both Claude Code and Codex: run this on **every LOD of every model** before
uploading a round for review. FAIL, UNMEASURED and NOT SET rows remain open;
N/A and INFO are explicit applicability states, never substitute PASS labels.

From the kit root (or with the kit installed):

```text
python -m studio_tools.model_qa <model-folder-or-GLBs> --budget-tris <budget> --ecology <entry.md> --switch-distances <LOD0-preview-m> <LOD1-switch-m> <LOD2-switch-m> --out <new-report-folder> --blender <executable>
```

Use the project's actual budget and switch distances. Keep one family per
invocation when families have different distances or ecology entries.
The folder convention is `name.glb` (or `name-lod0.glb`), `name-lod1.glb`, etc.
Read [setup and limits](../../docs/model-qa.md) for dependencies and input scope.

Read `REPORT.md`, `report.json`, the contact sheet, and any named failing parts.
The default assembly rule permits no floating part at 3 mm. A model manifest
can declare scatter/clump ground contact, or clump overlaps as INFO; retain all
raw counts and the declaration. Strict M13 permits no major clip and at most two
minor clips per 100 parts. M5 compares adjacent LODs at the same camera and
distance; keep its configured threshold and correspondence warnings visible.
Missing measurements/dependencies are UNMEASURED. Missing applicable ecology or
switch metadata fails. Explicit non-living assets get ecology N/A; unknown budgets
use `--budget-tris not-set`, never a made-up positive cap. Structural ecology
completeness does not approve proposed biology. The timeout defaults to 90 seconds;
use an explicit per-run `--timeout` when needed without weakening any measurement.

Repair the model or missing evidence and rerun into a new output directory.
Never weaken a check, change the budget or substitute an easier distance to
hide a failure. A disagreement with another checker names the input hash,
part, settings and both results. A green report permits the requested review
upload; it is neither upload authorization nor human artistic acceptance.
