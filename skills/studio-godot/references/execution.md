# Smoke protocol and isolated exports

## Project-owned smoke checks

`godot smoke` is an opt-in protocol, not a universal Godot test runner. Declare this in the game's `project.json` only after implementing it:

```json
{"capabilities": {"godot_smoke": "studio-smoke-v1"}}
```

The helper refuses absent, null or unknown declarations before starting Godot. The generic project template uses null. The generated and bundled Harbor Pocket fixture implement v1 already.

Protocol v1 launches the main scene headlessly with a user argument `--studio-smoke=<absolute JSON path>`. Read it through `OS.get_cmdline_user_args()`. Run bounded project-specific assertions, write an object containing `ok: true` only when every claimed assertion passes (otherwise false), and quit with exit code 0 for success or nonzero for failure. Include the actual assertions, measurements and untested scopes in the report. Stop audio and release resources before quitting. The helper requires a fresh output filename, successful process exit, no Godot error log and `ok` exactly true; a missing report or timeout fails. The host timeout must exceed the project's test duration.

Use Harbor Pocket's `main.gd` as an original worked example, not as a universal gameplay specification. A project's own test framework can be run directly instead. Import checks and ordinary-input native review remain available without the declaration; headless results never establish appearance, audible mix or ordinary controls.

## Export templates

The helper isolates Godot data/config/cache from the user's normal profile. For `godot export`, explicitly configure the **host-readable `export_templates` root**, containing version subdirectories:

```json
{"godot_export_templates": "C:\\Users\\YourName\\AppData\\Roaming\\Godot\\export_templates"}
```

On Linux, for example, use `/home/yourname/.local/share/godot/export_templates`. In WSL driving Windows Godot, configure the Linux-readable `/mnt/c/...` source path and the normal host path mappings. The source should contain a matching directory such as `4.5.1.stable/` with installed template binaries. Godot's [template layout](https://docs.godotengine.org/en/4.5/engine_details/development/compiling/compiling_for_android.html#installing-the-templates) and [export instructions](https://docs.godotengine.org/en/4.5/tutorials/export/exporting_projects.html) describe the engine requirements.

Each export copies that root into a fresh project-local temporary profile, retains version directory names, then deletes only that temporary copy on completion or failure. The source templates and normal user profile are never modified. Allow enough disk space for a copy of the configured root; a minimal root containing only the needed version/platform reduces cost. Missing configuration fails before launch. Wrong versions, missing platform binaries, presets or SDKs remain Godot errors. This route supports the documented native Windows/Linux profiles and WSL-to-Windows mapping; Godot self-contained `_sc_`/`._sc_` installations are refused because they bypass environment profile isolation.

Configure a real `export_presets.cfg`, then run `godot export --project <GAME> --config <HOST> --preset <name> --output <relative build path>`. Template staging is regression-tested with fake files; live exports and exported-game native acceptance remain unverified.
