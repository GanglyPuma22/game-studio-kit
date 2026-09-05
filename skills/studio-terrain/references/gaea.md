# Installed-version Gaea route

Gaea remains optional. [Primary automation documentation](https://docs.gaea.app/developers/automation/index.html) starts from a graph proven in the UI and exposes variables for a repeatable Build Swarm invocation. Check the installed version and [edition entitlement](https://quadspinner.com/Order/); no studio purchase or global setup is implied.

Open a project-owned graph in an owned native app session, configure exports/profiles/regions and build it once. Copy its working command from Build Options. Record exact executable (`executables.gaea` should name the verified build executable), version, entitlement, graph hash, variables, expected export names and dimensions contract. Convert the copied command into a JSON argument array, preserving each quoted path as one element. Do not invent flags from a different installation.

The recipe fields are `version`, `entitlement_confirmed: true`, `ui_build_verified: true`, absolute host-local `graph`, `graph_sha256`, `arguments`, `variables` and `outputs`. In arguments, `{graph}` and `{output}` resolve to explicit app paths; other braces name keys in `variables`. Outputs are relative to a **new empty build directory**. For example, replace the graph and output arguments of your verified command with `{graph}` and `{output}`; the studio intentionally supplies no speculative command syntax.

```text
python <KIT>/scripts/studio.py gaea --project <GAME> --recipe host/gaea-recipe.json --output source/gaea-run-001 --config <HOST>
```

Host-specific recipe paths are not portable project facts; keep that file private/ignored. Store the graph itself and terrain contract separately in source. The helper hashes expected nonempty outputs and preserves its log. Then measure bit depth, footprint/elevation, coordinates/masks and borders, and test the terrain's scale, seams and collision in Godot. Command completion alone does not pass this review.
