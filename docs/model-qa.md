# Model QA

Run from this repository, or install the Python package. The parent CLI uses
only the standard library and existing kit process helpers. One owned,
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
- Skinned models support one skin, four joint weights, TRS transforms and
  LINEAR/slerp animations. Rest plus six samples per clip are checked by M12
  and M13. `--samples` controls this finite sampling; it does not prove
  continuous-motion clearance. Multiple skins, mixed static/skinned geometry,
  morph targets, sparse accessors, nontriangle primitives, required extensions,
  unskinned animation and unsupported interpolation fail explicitly.
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

`--out` must not exist. Exit 0 means every row passed; 1 means failed checks
or execution; 2 means invalid invocation. The outputs are `report.json`,
`REPORT.md`, `contact-sheet.png`, full PNGs in `silhouettes/`, input hashes in
`request.json`, and execution/source/executable identity plus the owned
process receipt/log. Missing dependencies or Blender leave failed rows and a
red placeholder sheet, never yesterday's render. Inputs and source are
checked for changes during execution. The request and process files contain
local paths; publish the portable report and images, not private host receipts.

The default worker timeout is 1800 seconds; `--timeout` is bounded at nine
hours. There is no progress polling. On timeout/interruption the runner stops
its owned process and preserves receipts. Unverified descendants are never
killed by name and prevent a PASS.

## Tests

```text
python tests/model_qa_fixtures.py /new/fixture-directory
python -m unittest discover -s tests -p test_model_qa.py -v
```

Set `MODEL_QA_BLENDER` (and optionally `MODEL_QA_PYTHON_SITE_PACKAGES`) to
enable the end-to-end synthetic GLB tests. They check a clean family, a
floating cube, crossing boxes, a disappeared LOD tip, missing ecology,
missing switch metadata, budget failure and an animated detached part.
Without Blender, the pure Python tests run and native tests are explicitly
skipped. No asset-generation APIs or binary fixtures are needed.
