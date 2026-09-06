# Installed-version Gaea route

Gaea remains optional. [Primary automation documentation](https://docs.gaea.app/developers/automation/index.html) starts from a graph proven in the UI and exposes variables for a repeatable Build Swarm invocation. Check the installed version and [edition entitlement](https://quadspinner.com/Order/); no studio purchase or global setup is implied.

Open a project-owned graph in an owned native app session, configure exports/profiles/regions and build it once. Copy its working command from Build Options. Record exact executable (`executables.gaea` should name the verified build executable), version, entitlement, graph hash, variables, expected export names and dimensions contract. Convert the copied command into a JSON argument array, preserving each quoted path as one element. Do not invent flags from a different installation.

The recipe fields are `version`, `entitlement_confirmed: true`, `ui_build_verified: true`, absolute host-local `graph`, `graph_sha256`, `arguments`, `variables` and `outputs`. In arguments, `{graph}` and `{output}` resolve to explicit app paths; other braces name keys in `variables`. The names `graph` and `output` are reserved and forbidden in `variables`; they cannot override the validated graph or destination. Outputs are relative to a **new empty build directory**. For example, replace the graph and output arguments of your verified command with `{graph}` and `{output}`; the studio intentionally supplies no speculative command syntax.

```text
python <KIT>/scripts/studio.py gaea --project <GAME> --recipe host/gaea-recipe.json --output source/gaea-run-001 --config <HOST>
```

Host-specific recipe paths are not portable project facts; keep that file private/ignored. Store the graph itself and terrain contract separately in source. The helper hashes expected nonempty outputs and preserves its log. Then measure bit depth, footprint/elevation, coordinates/masks and borders, and test the terrain's scale, seams and collision in Godot. Command completion alone does not pass this review.

## Scalar data and final-export preflight

Bind the graph, actual authoring recipe and input raster hashes to one terrain
contract. Before consuming a limited export, reconcile:

- Raster sample dimensions, sample spacing, physical extent, native terrain
  width/height and runtime mapping. An endpoint-sample span is (N - 1) times
  spacing; a pixel-area convention can differ. State the chosen convention and
  any intentional native/runtime mapping difference. Read back the saved native
  setting rather than trusting a typed value or a rounded display.
- Input scalar encoding/bit depth, units and range, effective color/transfer
  setting, output encoding, and which graph port is the authoritative height.
  Erosion maps do not imply the exported height has passed through erosion.
- Coordinate origin, row direction, channel and mask meaning. Do not infer row
  order from a file extension or assume the reader exposes rows in file order.
- Exact prepared recipe identity and new output destination. A stale recipe
  pointer is not permission to regenerate over the authoritative source.

For a linear float input, inspect the effective File-node transfer setting
(including Enforce Linear where that installed version exposes it). Do not apply
a universal on/off rule: a color/gamma transformation can alter scalar heights.
Use an asymmetric known ramp or marker to establish orientation and compare
decoded source/export scalar values without display color correction. For an
identity height export, compare all pixels and report maximum/RMS error in both
normalized values and physical units; for intentional processing, compare against
its declared transformation instead. Carry the proven row mapping into masks.
Missing or nonfinite samples, unknown settings or an unexplained range/dimension
change remain unverified. The helper's nonempty-file checks do **not** perform
these numerical checks or pass the terrain contract.

Run the cheap prepared-input collision/coverage screen described in
[studio-terrain](../SKILL.md) before a scarce native export. Afterwards repeat
the relevant checks against the actual exported, imported and published data.

## Native versus unattended execution

Recipes may set execution_mode to native (the default for existing recipes) or
unattended. Native uses the existing authorized app window; the helper does not
acquire desktop permission. Unattended additionally requires
unattended_verified: true. This is a declaration of completed host verification,
not a test performed by the helper or authorization to interrupt the desktop.

Set it true only after recording the exact executable/hash, installed version,
graph/command and evidence showing that this operation opened no UI and completed
naturally with usable fresh outputs. Reverify when those capability assumptions
change. A console executable, copied command, AlreadyBuilt message or force-killed
process does not establish unattended success. Keep it false when unverified and
provide the exact remaining native check. Do not spend an export to retest an
unrelated capability without an authorized reason.

Unattended mode requests console hiding on Windows; arbitrary app UI is still
outside that flag's control. The result records the declared execution mode and
verification separately from terrain and visual acceptance.
