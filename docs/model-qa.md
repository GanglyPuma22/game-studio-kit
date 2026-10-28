# Model QA

Run from this repository, or install the Python package. The parent CLI uses
the standard library and existing kit process helpers; YAML ecology parsing also needs PyYAML. One owned,
synchronous, headless Blender process performs the measurements and renders.
It does not open a desktop window, save a Blender file, edit inputs, install
dependencies, upload a review, or use a provider.

```text
python -m studio_tools.model_qa models/ --budget-tris 5000 --ecology entry.md --switch-distances 2 10 30 --out report-001/ --blender /path/to/blender
```

`--switch-distances` lists the LOD0 preview distance and each subsequent
incoming switch distance. These example distances are not universal game
settings. Use the actual project distances. A missing list produces diagnostic
fallback renders and a FAIL M5 row; it cannot accidentally qualify a model at
an invented distance. Distances are measured from the common family center.
The camera is level with that center, with a default 75-degree vertical FOV
and 1920x1080 output. Four sides are front, right, back and left. All LODs
share world coordinates and target; no individual auto-fitting conceals shrinkage.

## Dependencies

A Blender build with Workbench and Python is needed (tested on 5.1.0).
Its Python needs the packages
in `studio_tools/model_qa/requirements.txt`. Install them into a private virtual
environment made with **that Blender version's bundled Python**, not into the
application directory or system Python. Use absolute paths for the executable
and dependency folder:

```text
<blender-python> -m venv <qa-env>
<qa-env-python> -m pip install -r studio_tools/model_qa/requirements.txt
python -m studio_tools.model_qa models/ --budget-tris 5000 --ecology entry.md --switch-distances 2 10 30 --out report-001/ --blender <blender> --python-site-packages <qa-env-site-packages>
```

On Windows the venv interpreter is `Scripts/python.exe` and its site packages
are `Lib/site-packages`. On POSIX they are `bin/python` and
`lib/pythonX.Y/site-packages`. Blender includes `bpy` and `mathutils`; do not
pip-install replacements. The optional environment variables
`MODEL_QA_BLENDER` and `MODEL_QA_PYTHON_SITE_PACKAGES` supply these two paths.
Dependencies stay optional; the kit's other commands do not import them.

## Inputs and reports

- Pass a folder (recursive GLB discovery) or several explicit GLBs.
  `name.glb` / `name-lod0.glb`, `name-lod1.glb`, `name-lod2.glb` form a family.
  Levels must be contiguous from zero, with at least two. Multiple families
  in one invocation use the same ecology entry, budget and distance list.
- Self-contained triangle GLBs use metres and glTF's Y-up convention.
  Node transforms and instances count. Static M12 anchors at the lowest Y
  part; skinned M12 anchors at the largest part by triangle count.
- Posed models: any skins (four joint weights each), plus rigid meshes that
  ride on joints or animated nodes (a held weapon under a hand bone), with
  TRS transforms and LINEAR/slerp, STEP and CUBICSPLINE animations. Rest plus
  six samples per clip are checked by M12, M13 and M14. `--samples` controls
  this finite sampling; it does not prove continuous-motion clearance. Sparse
  measured accessors, nontriangle primitives, other required extensions,
  animated `matrix` nodes and unsupported interpolation remain UNMEASURED.
  KHR_mesh_quantization is decoded with normalized integer bounds and node/skin
  transforms. Morph targets and weight animation are ignored: the base mesh is
  measured and each report explicitly notes that morphs were not checked.
- Ecology needs a nonempty `Habitat` section (or `Habitat: ...`) and a
  `Traits`/`Adaptations` section with a reasoned trait. For example,
  `Low profile because it reduces wind exposure`, or a `Trait | Reason`
  table. This is a structural completeness check, not ecological judgement.
- `--budget-tris` is an upper bound applied separately to every LOD's actual
  transformed mesh instances. It is not automatically divided between LODs.
- M13 preserves the measured seating, hidden-crossing, ground and junction
  rules. It fails on **any major** clip or **more than 2 minor / 100 parts**.
  It is a sampled mesh crossing check, not solid collision or topology QA.
- M5 records each pair's changed pixels divided by their silhouette union.
  Default maximum is 0.05; `--max-pixel-difference` exposes this policy
  explicitly. It is a heuristic, not a user-calibrated perceptual threshold.
  A missing/empty or frame-clipped silhouette fails regardless of that ratio.
  The contact sheet uses a common center crop, retaining native pixels when
  they fit; any common reduction is labelled. It never fits each LOD separately.
  A part is flagged when at most half its vertices remain within
  `--part-match-mm` (default 3 mm) of the next LOD surface. This catches loss
  even when a seated root remains. A merged part can pass; substantial
  simplification or motion can also flag, so inspect the named part and
  distance evidence. Geometry is rendered opaque; texture alpha and runtime
  fades require a separate review.

`--out` must not exist. Exit 0 means no FAIL, UNMEASURED or NOT SET rows;
N/A and INFO retain their labels and are never converted to PASS. Exit 1 means
failed/incomplete checks or execution; 2 means invalid invocation. The outputs are `report.json`,
`REPORT.md`, `contact-sheet.png`, full PNGs in `silhouettes/`, input hashes in
`request.json`, and execution/source/executable identity plus the owned
process receipt/log. Missing dependencies or Blender leave UNMEASURED geometry rows and a
red placeholder sheet, never yesterday's render. Inputs and source are
checked for changes during execution. The request and process files contain
local paths; publish the portable report and images, not private host receipts.

The default worker timeout is 90 seconds; `--timeout` is bounded at nine
hours. There is no progress polling. On timeout/interruption the runner stops
its owned process and preserves receipts. Unverified descendants are never
killed by name and prevent a completed result. Completed rows are checkpointed atomically, so a
resource failure preserves measured defects and leaves unfinished rows UNMEASURED.

## Surface checks (0.1.26)

M12/M13/M5 look at parts touching, parts crossing each other and far LOD
silhouettes. Defects reviewers kept finding sat outside all three, so four
measured checks join them. All run offline in the same Blender process.

- **M14 self-intersection.** Triangles of one connected part that cross each
  other: a welded hood pushed through a head, a crease folded through itself.
  M13 compares different parts, so these passed before. Sampled at every pose
  M13 uses. Any crossing chain of 10 mm or more is major and fails; shorter
  ones count as minor against the M13 allowance (2 per 100 parts).
- **M15 see-through.** 26 orthographic ray grids around the model. A first hit
  on the back of a single-sided face is where an engine culls the face and
  shows the inside of the shell or whatever lies behind it: an inside-out
  part, flipped faces or a hole. Each flagged part is labelled `inside-out`
  (negative signed volume) or `open or flipped faces`. Opposed faces within
  2 mm of each other count as covered (a blade built from two sheets).
  glTF `doubleSided` materials and manifest `double_sided` names are exempt.
  Note that Blender's exporter writes `doubleSided: true` unless a material
  enables backface culling, while game shaders often cull anyway; check the
  file the game actually draws, or declare what is really double-sided.
- **M16 LOD screen error.** For each LOD, the visible surface distance to
  LOD0 measured in screen pixels at that LOD's switch distance, both ways:
  lost detail (a collapsed finger) and added geometry (a spike). Fails when
  the 99th percentile of area samples exceeds 1 px or any visible vertex is
  more than 3 px off. Hidden interior surfaces are ignored. Unlike the M5
  pixel ratio, a far switch distance does not make every change vanish, and
  unlike part correspondence it does not flag simplification nobody can see.
- **M17 mirror symmetry** (only with a manifest `symmetry` entry): parts whose
  visible surface is more than `tolerance_mm` (95th percentile) from the
  mirrored model. `allow` names deliberate asymmetry (a satchel, one pauldron).

Failing M14, M15 and M16 sites get close-up renders in `evidence/`, drawn with
back faces culled the way the engine draws them, and a JSON sidecar per image:
`schema_version`, `glb_sha256`, `image_sha256`, `lod`, `pose`, `time_s`,
`check`, `site`, `view`, `direction`, `distance_m`, `fov_deg`, `resolution`,
`renderer`, `back_faces` and `target_m`. A later reviewer (human or a visual
claim step) can then say exactly what was and was not shown. The images never
change a mechanical result.

Manifest keys for real character files:

```json
{"schema_version": 1, "exclude_meshes": ["Arms"], "exclude_clips": "^fp_",
 "free_parts": ["Spark"], "include_rest": false, "double_sided": ["Cape"],
 "symmetry": {"axis": "x", "allow": ["Satchel"], "tolerance_mm": 10}}
```

`exclude_meshes` leaves out meshes the game never shows with the body (a
first-person arms mesh). `exclude_clips` is a regular expression for clips
not played on this model (first-person views). `free_parts` names parts meant
to float (sparks, a thrown hook). `include_rest: false` skips the bind pose
when the game never shows it. Every exclusion is listed in the report notes.

## Tests

```text
python tests/model_qa_fixtures.py /new/fixture-directory
python -m unittest discover -s tests -p 'test_model_qa*.py' -v
```

Set `MODEL_QA_BLENDER` (and optionally `MODEL_QA_PYTHON_SITE_PACKAGES`) to
enable the end-to-end synthetic GLB tests. They check a clean family, a
floating cube, crossing boxes, a disappeared LOD tip, missing ecology,
missing switch metadata, budget failure, an animated detached part, an
inside-out box (M15), a top pushed through its own bottom (M14) and a LOD
spike (M16). Attachment gaps use Blender's BVH, so the direct attachment
unit tests run inside Blender's Python:

```text
blender -b --factory-startup --python-expr "import sys; sys.path[:0]=['<qa-env-site-packages>', '.', 'tests']; import unittest; unittest.main(module='test_model_qa', argv=['x', 'AttachmentTests'])"
```
Without Blender, the pure Python tests run and native tests are explicitly
skipped. No asset-generation APIs or binary fixtures are needed.

## Applicability and policy declarations (0.1.16)

Each family may carry `<family>.model-qa.json`, or a shared `model-qa.json` in
its own directory. `--manifest <file>` explicitly applies one manifest to all
input families. Unknown fields/structures are refused, rather than silently
falling back. The request records the file hash and interpreted declaration.

```json
{"schema_version": 1, "structure": "clump", "living": false, "ground_y_m": 0.0}
```

- `assembly` (default): original M12 connected-assembly rule and strict M13.
- `scatter`: each connected piece must touch the declared Y-up ground plane
  within the unchanged 3 mm tolerance, at every sampled pose. M13 stays strict.
- `clump`: the same per-piece ground check; M13 retains all raw overlap counts
  and pairs but labels the row INFO. This is an explicit applicability choice,
  not a change to the crossing thresholds. A declared flat plane is not a test
  against a terrain mesh, and deeply buried pieces still need placement review.
- `living: false`: ecology is N/A. Alternatively use `--ecology none --reason
  "Manufactured prop"`. A conflicting `living: true` is refused. The default
  requires ecology evidence; it never infers non-living from missing paperwork.
- `--budget-tris not-set`: the row is NOT SET, retaining the actual triangle
  count. A positive value is a maximum only, independently applied to every LOD;
  there is no implied minimum and no positive-number sentinel for unknown policy.

Ecology supports the previous Markdown headings and tables plus YAML front matter:

```yaml
---
status: proposed
review_status: awaiting approval
habitat:
  where: Exposed rocky ground
traits:
  - feature: Low spreading crown
    because: Reduces wind damage
---
```

Structural completeness can PASS while status remains proposed; it grants no
approval. `status` and `review_status` are reported separately, including NOT SET
when absent. Placeholder habitat/reasons do not count as evidence. Install the
optional requirements for the parent Python too when it must parse YAML while
reporting an unavailable worker.

Measurement inputs follow the [glTF interpolation specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#interpolation-cubic)
and [KHR mesh quantization](https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos/KHR_mesh_quantization).
STEP keys and tangent-scaled cubic curves are evaluated at the same six samples
per clip; rotations are normalized. No input animation or geometry is rewritten.
The geometry reader never decodes image data or copies authored materials.
